import os 
from contextlib import AsyncExitStack

from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langgraph.graph import START, MessagesState,StateGraph
from langgraph.prebuilt import ToolNode , tools_condition
from mcp_tools import load_tools 

SERVERS = [
    "servers/notes_server.py",
    "servers/email_server.py",
    "servers/files_server.py",
]

SYSTEM = "Your are a helpful assistant. Use the available tools to complete the user's requests."

def make_llm():
    """Create the Groq chat model. Needs GROQ_API_KEY in .env."""
    load_dotenv()
    # two retries: short network failures (common on small cloud instances) should not fail the whole run
    return ChatGroq(model=os.getenv("GROQ_MODEL","openai/gpt-oss-20b"),temperature=0, max_retries=2, timeout=60)

def make_fallbacks():
    """Backup agent model for when Groq is rate limited (needs GOOGLE_API_KEY). Note: a different model may resist
    the attacks better or worse than gpt-oss-20b, so attack demos are most meaningful on the primary model."""
    load_dotenv()
    if not os.getenv("GOOGLE_API_KEY"):
        return []
    from langchain_google_genai import ChatGoogleGenerativeAI
    return [ChatGoogleGenerativeAI(model=os.getenv("AGENT_FALLBACK_MODEL", "gemini-3.1-flash-lite"), temperature=0, max_retries=2, timeout=60)]

def build_graph(llm, tools, fallbacks=()):
    """Agent loop: model -> (tools ->model)* -> answer."""
    llm_with_tools = llm.bind_tools(tools)
    if fallbacks:
        llm_with_tools = llm_with_tools.with_fallbacks([f.bind_tools(tools) for f in fallbacks])

    async def call_model(state: MessagesState):
        reply = await llm_with_tools.ainvoke([("system", SYSTEM)] + state["messages"])
        return {"messages": [reply]}

    graph = StateGraph(MessagesState)
    graph.add_node('model',call_model)
    graph.add_node('tools',ToolNode(tools))
    graph.add_edge(START,'model')
    graph.add_conditional_edges('model',tools_condition)
    graph.add_edge('tools','model')
    return graph.compile()

async def run_agent(messages,llm=None,shield=False,on_message=None):
    """Run the agent on the chat history and return all the messages

    With sheild=True, tools come through the Sheild proxy instead of straight from the servers.
    on_message, if given, is called with every new message as soon as it exists (the dashboard uses it)."""

    async with AsyncExitStack() as stack:
        paths = [["shield/proxy.py", *SERVERS]] if shield else SERVERS
        tools = await load_tools(stack, paths)
        graph = build_graph(llm, tools) if llm else build_graph(make_llm(), tools, make_fallbacks())
        seen = len(messages)
        async for state in graph.astream({"messages": messages}, stream_mode="values"):
            for message in state["messages"][seen:]:
                if on_message:
                    on_message(message)
            seen = len(state["messages"])
    return state["messages"]