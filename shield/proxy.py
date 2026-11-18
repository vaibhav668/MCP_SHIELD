import asyncio
import hashlib
import json
import os
import sqlite3
import sys
import time
import uuid
from contextlib import AsyncExitStack
from pathlib import Path

import mcp_types as types
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.server.lowlevel.server import Server
from mcp.server.stdio import stdio_server

sys.path.insert(0, str(Path(__file__).parent.parent))  # so 'shield.xxx' imports work when run as a script
from shield.audit import add_approval, add_trace, answer, cache_verdict, cached_verdict, get_answer, log_audit
from shield.graph import HIGH, build_graph
from shield.policy import load_policy

LOG_FILE = Path(__file__).parent.parent / "logs" / "shield_log.jsonl"
CHECKPOINT_FILE = LOG_FILE.parent / "checkpoints.db"

policy = load_policy()

# Every step this proxy takes is written to the trace table under one run id. The dashboard passes its own
# run id in SHIELD_RUN_ID; any other client (Claude Code, a script) gets a fresh one per proxy start.
RUN_ID = os.getenv("SHIELD_RUN_ID") or f"proxy-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}"

SURFACE = {"description": "tool description", "arguments": "arguments", "result": "tool result"}
LEVEL = {"ALLOW": "ok", "SANITIZE": "warn", "ASK_HUMAN": "warn", "BLOCK": "block"}
POLICY_WORDS = {"ALLOW": "allow it", "BLOCK": "block it", "SANITIZE": "remove only the dangerous part",
                "ASK_HUMAN": "ask a human"}


def make_app():
    """The inspection graph with a SQLite checkpointer, so a paused graph can be resumed later."""
    CHECKPOINT_FILE.parent.mkdir(exist_ok=True)
    return build_graph(SqliteSaver(sqlite3.connect(CHECKPOINT_FILE, check_same_thread=False)))


APP = make_app()


def log_event(kind, **fields):
    """Append one event to the shield log (one json object per line)"""
    LOG_FILE.parent.mkdir(exist_ok=True)
    event = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "kind": kind, **fields}
    with LOG_FILE.open("a") as f:
        f.write(json.dumps(event) + "\n")


def trace(stage, title, detail=None, level="info", actor="shield"):
    add_trace(RUN_ID, actor, stage, title, detail, level)


def short(value, limit=400):
    text = value if isinstance(value, str) else json.dumps(value)
    return text if len(text) <= limit else text[:limit] + " …"


def duration(ms):
    """1854.853 -> '1.85 s', 0.037 -> '0.04 ms'."""
    if ms is None:
        return "—"
    return f"{ms / 1000:.2f} s" if ms >= 1000 else f"{ms:.2f} ms"


def judge_words(reason):
    if reason and ("429" in reason or "rate limit" in reason.lower()):
        return "the judge API is rate limited"
    return reason


def step_for(what, node, values):
    """Turn one graph node's output into a readable trace step: (stage, title, detail, level)."""
    surface = SURFACE[what]
    if node.startswith("scan_"):
        score = values["score"]
        level = "block" if score >= HIGH else "warn" if score > 0 else "ok"
        return "scan", f"Regex scan of the {surface}: score {score:.2f}", \
            {"rules matched": values["reasons"] or "none", "time": duration(values["fast_ms"])}, level
    if node == "allow":
        return "fast", "Fast path: clearly safe, no LLM needed", None, "ok"
    if node == "block":
        return "fast", "Fast path: obvious attack, decided without the LLM", None, "block"
    if node == "judge":
        verdict = values["verdict"]
        title = {"BLOCK": "LLM judge: this is an attack", "ALLOW": "LLM judge: this is safe",
                 "UNSURE": "LLM judge could not decide"}[verdict]
        return "judge", title, {"reason": judge_words(values.get("judge_reason")),
                                "time": duration(values.get("judge_ms"))}, {"BLOCK": "block", "ALLOW": "ok", "UNSURE": "warn"}[verdict]
    if node == "decide":
        action = values["action"]
        return "policy", f"Policy says: {POLICY_WORDS[action]}", {"action": action}, LEVEL[action]
    if node == "sanitize":
        if values["changed"]:
            return "sanitize", f"Sanitized: {values['changed']} dangerous part(s) removed", {"cleaned": short(values["clean"])}, "warn"
        return "sanitize", "Nothing that can be safely removed, so a human must decide", None, "warn"
    if node == "__interrupt__":
        return "human", "Paused: waiting for a person to approve or deny in Approvals", None, "warn"
    if node == "ask_human":
        approved = values["human"] == "approve"
        return "human", "A human approved it" if approved else "Denied (by a human, or no answer in time)", None, "ok" if approved else "block"
    return None


def run_graph(what, graph_input, thread_id, emit):
    """Run (or resume) the inspection graph node by node, reporting each step as it finishes."""
    config = {"configurable": {"thread_id": thread_id}}
    paused = None
    for update in APP.stream(graph_input, config, stream_mode="updates"):
        for node, values in update.items():
            if node == "__interrupt__":
                paused = values[0].value
            step = step_for(what, node, values)
            if emit and step:
                emit(*step)
    state = dict(APP.get_state(config).values)
    if paused is not None:
        state["__interrupt__"] = paused
    return state


def blocked(message):
    """The tool result the agent sees when the shield refuses something."""
    return types.CallToolResult(content=[types.TextContent(type="text", text=message)], is_error=True)


async def wait_for_human(thread_id, timeout):
    """Poll the approvals table until a person answers. No answer in time means deny."""
    waited = 0.0
    while waited < timeout:
        status = get_answer(thread_id)
        if status:
            return status
        await asyncio.sleep(0.5)
        waited += 0.5
    answer(thread_id, "timeout")
    return "timeout"


async def inspect_item(what, content, tool, server, timeout=None, emit=None):
    """Inspect one item, ask a human if the graph pauses, write the audit row.
    Returns (action, content_to_use, final_state): action is ALLOW, BLOCK or SANITIZE."""
    thread_id = str(uuid.uuid4())
    # a worker thread, because the judge call blocks
    result = await asyncio.to_thread(run_graph, what, {"kind": what, "content": content}, thread_id, emit)
    if "__interrupt__" in result:
        add_approval(thread_id, tool, result["__interrupt__"])
        status = await wait_for_human(thread_id, timeout or policy["approval_timeout"])
        decision = "approve" if status == "approve" else "deny"
        result = await asyncio.to_thread(run_graph, what, Command(resume=decision), thread_id, emit)
    action = result["action"]
    log_audit(tool=tool, server=server, what=what, verdict=result["verdict"], action=action, path=result["path"],
              score=result["score"], reasons=result["reasons"], fast_ms=result.get("fast_ms"),
              judge_ms=result.get("judge_ms"), judge_reason=result.get("judge_reason"), human=result.get("human"))
    return action, (result["clean"] if action == "SANITIZE" else content), result


async def enforce(what, content, tool, server, timeout=None):
    """Same as inspect_item, returning only (action, content_to_use)."""
    action, content, _ = await inspect_item(what, content, tool, server, timeout)
    return action, content


async def connect_upstream(stack, path):
    """Connect to one real MCP server and return its session"""
    params = StdioServerParameters(command=sys.executable, args=[path])
    read, write = await stack.enter_async_context(stdio_client(params))
    session = await stack.enter_async_context(ClientSession(read, write))
    await session.initialize()
    return session


async def check_description(tool, path):
    """Inspect a tool description once; the verdict is cached until the description or the policy changes."""
    key = hashlib.sha256(f"{tool.name}|{tool.description}|{policy['low']}|{policy['high']}".encode()).hexdigest()
    action = cached_verdict(key)
    if action:
        return action, "cached", True
    action, _, state = await inspect_item("description", tool.description or "", tool.name, path)
    if not state.get("human"):  # never cache a decision taken while the judge was failing
        cache_verdict(key, action)
    # why it was hidden: a real attack, or the judge failed and nobody approved it in time
    reason = "unchecked" if state.get("verdict") == "UNSURE" and action == "BLOCK" else "checked"
    return action, reason, False


async def main(paths):
    async with AsyncExitStack() as stack:
        owner = {}
        tools = []
        trace("start", f"Shield started: checking the tools of {len(paths)} server(s)",
              {"servers": [Path(p).name for p in paths]}, actor="shield")

        for path in paths:
            session = await connect_upstream(stack, path)
            for tool in (await session.list_tools()).tools:
                action, reason, cached = await check_description(tool, path)
                log_event("tool_listed", server=path, tool=tool.name, description=tool.description, action=action)
                note = " (cached verdict)" if cached else ""
                if action == "BLOCK":
                    why = ("it could not be checked (judge unavailable, nobody approved it)" if reason == "unchecked"
                           else "its description is poisoned")
                    trace("description", f"Hid the tool {tool.name}: {why}{note}",
                          {"server": Path(path).name, "description": short(tool.description or "", 300)}, "block")
                    continue  # a poisoned (or unchecked) tool is never shown to the agent
                trace("description", f"Tool {tool.name} looks safe{note}", {"server": Path(path).name}, "ok")
                owner[tool.name] = (path, session)
                tools.append(tool)

        async def on_list_tools(ctx, params):
            return types.ListToolsResult(tools=tools)

        async def on_call_tool(ctx, params):
            path, session = owner[params.name]
            server_name = Path(path).name
            trace("received", f"Shield intercepted a call to {params.name}", {"arguments": params.arguments or {}})

            action, arguments, _ = await inspect_item("arguments", params.arguments or {}, params.name, path, emit=trace)
            if action == "BLOCK":
                trace("return", "Call refused: the tool never runs, the agent gets an error", None, "block")
                return blocked("Blocked by MCP Shield: these arguments looked unsafe (possible data leak).")

            trace("forward", f"Forwarded to {server_name}" + (" with the secret redacted" if action == "SANITIZE" else ""),
                  {"arguments": arguments}, "warn" if action == "SANITIZE" else "info")
            start = time.perf_counter()
            result = await session.call_tool(params.name, arguments)
            ms = round((time.perf_counter() - start) * 1000, 1)
            text = "\n".join(c.text for c in result.content if c.type == "text")
            log_event("tool_call", server=path, tool=params.name, arguments=arguments, result=text, ms=ms)
            trace("server", f"{server_name} replied in {duration(ms)}", {"result": short(text)}, "info", actor="server")

            action, text, _ = await inspect_item("result", text, params.name, path, emit=trace)
            if action == "BLOCK":
                trace("return", "Result withheld: the agent gets an error instead", None, "block")
                return blocked("Blocked by MCP Shield: this tool result looked unsafe.")
            if action == "SANITIZE":
                trace("return", "Returned the cleaned result to the agent", {"result": short(text)}, "warn")
                # keep the structured copy in step with the cleaned text, or the injected text would leak through it
                structured = result.structured_content
                if structured and "result" in structured:
                    structured = {**structured, "result": text}
                return types.CallToolResult(content=[types.TextContent(type="text", text=text)], structured_content=structured)
            trace("return", "Returned the result to the agent unchanged", None, "ok")
            return result

        server = Server("mcp-shield", on_list_tools=on_list_tools, on_call_tool=on_call_tool)
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
