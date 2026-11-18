import time 
import uuid
from typing import TypedDict
                            
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END,START,StateGraph
from langgraph.types import Command, interrupt
                           
from shield.detectors import scan_arguments , scan_description, scan_result                                                                    
from shield.judge import ask_judge
from shield.policy import decide_action, load_policy
from shield.sanitize import sanitize_arguments, sanitize_result
                      
policy = load_policy()
LOW = policy['low']
HIGH = policy['high']

class State(TypedDict, total=False):
    kind: str
    content: object
    score: float
    reasons: list
    verdict: str
    path: str
    fast_ms: float
    judge_ms: float
    judge_reason: str
    action : str
    clean: object
    changed: int
    human: str

def make_scan_node(scan):
    """Wrap a detector function as a graph node that also times itself."""
    def node(state):
        start = time.perf_counter()
        score, reasons = scan(state["content"])
        ms = round((time.perf_counter() - start) * 1000, 3)
        return {"score": score, "reasons": reasons,"fast_ms":ms}
    return node

def pick_scanner(state):
    return "scan_" + state["kind"]

def pick_route(state):
    if state["score"] < LOW:
        return "allow"
    if state["score"] >= HIGH:
        return "block"
    return "judge"

def allow(state):
    return {"verdict": "ALLOW", "path": "fast"}


def block(state):
    return {"verdict": "BLOCK", "path": "fast"}

def judge(state):
    """Middle band: ask the slower LLM judge."""
    start = time.perf_counter()
    try:
        answer = ask_judge(state["kind"], state['content'], state['reasons'])
        verdict = "BLOCK" if answer.is_attack and answer.confidence >= 0.5 else "ALLOW"
        reason = answer.reason

    except Exception as error:
        verdict , reason = "UNSURE", f"Judge failed: {error}"
    ms = round((time.perf_counter() - start) * 1000, 3)
    return {"verdict": verdict, "path": "judge", "judge_ms": ms, "judge_reason": reason}

def decide(state):
    """Turn the detection verdict into an action using the policy file"""
    return {"action": decide_action(policy, state["kind"], state["verdict"])}

def pick_action(state):
    if state['action'] in ("SANITIZE","ASK_HUMAN"):
        return state['action'].lower()
    return "done"

def sanitize(state):
    """Remove only the dangerous part. If nothing could be removed , escalate to a human."""
    if state["kind"] == "arguments":
        clean, changed = sanitize_arguments(state["content"])
    else:
        clean, changed = sanitize_result(state["content"])
    return {"clean": clean, "changed": changed, "action": "SANITIZE" if changed else "ASK_HUMAN"}

def pick_after_sanitize(state):
    return "done" if state['action'] == "SANITIZE" else "ask_human" 

def ask_human(state):
    """Pause the whole graph until a person answers. The answer comes back from the interrupt()"""
    answer = interrupt({
        "what": state['kind'],
        "score": state["score"],
        "reasons": state["reasons"],
        "judge_reason": state.get("judge_reason"),
        "content": str(state["content"])[:500],
    })
    return {"human": answer, "action": "ALLOW" if answer =="approve" else "BLOCK"}

def build_graph(checkpointer=None):
    g = StateGraph(State)
    g.add_node("scan_description",make_scan_node(scan_description))
    g.add_node("scan_arguments",make_scan_node(scan_arguments))
    g.add_node("scan_result",make_scan_node(scan_result))
    g.add_node('allow',allow)
    g.add_node('block',block)
    g.add_node('judge',judge)
    g.add_node('decide',decide)
    g.add_node('sanitize',sanitize)
    g.add_node('ask_human',ask_human)

    scanners = ['scan_description','scan_arguments','scan_result']
    g.add_conditional_edges(START,pick_scanner,scanners)

    for name in scanners:
        g.add_conditional_edges(name,pick_route,['allow','block','judge'])

    for name in ['allow','block','judge']:
        g.add_edge(name,"decide")

    g.add_conditional_edges("decide", pick_action, {"sanitize": "sanitize", "ask_human": "ask_human", "done": END})
    g.add_conditional_edges("sanitize",pick_after_sanitize,{'ask_human':'ask_human','done':END})
    g.add_edge('ask_human',END)
    return g.compile(checkpointer=checkpointer)

graph = build_graph(MemorySaver())

def inspect(kind, content, thread_id=None, app=None):
    """Run one item through the graph. If a human is needed, the result has an '__interrupt__' key."""
    config = {"configurable": {"thread_id": thread_id or str(uuid.uuid4())}}
    return (app or graph).invoke({"kind": kind, "content": content}, config)


def resume(thread_id, answer, app=None):
    """Give a paused graph the human's answer ('approve' or 'deny') and let it finish."""
    config = {"configurable": {"thread_id": thread_id}}
    return (app or graph).invoke(Command(resume=answer), config)