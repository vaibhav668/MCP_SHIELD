import asyncio
from contextlib import AsyncExitStack

from langchain_core.messages import AIMessage, ToolMessage

from agent import build_graph
from mcp_tools import load_tools


class FakeLLM:
    """Stands in for the real model: returns pre-written replies in order."""

    def __init__(self, replies):
        self.replies = list(replies)

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        return self.replies.pop(0)


def test_agent_calls_tool_then_answers():
    replies = [
        AIMessage(content="", tool_calls=[{"name": "add_note", "args": {"text": "Buy milk"}, "id": "call1"}]),
        AIMessage(content="Saved your note."),
    ]

    async def run():
        async with AsyncExitStack() as stack:
            tools = await load_tools(stack, ["servers/notes_server.py"])
            graph = build_graph(FakeLLM(replies), tools)
            return await graph.ainvoke({"messages": [("user", "Save a note: Buy milk")]})

    messages = asyncio.run(run())["messages"]
    tool_results = [m for m in messages if isinstance(m, ToolMessage)]
    assert "Saved note #0" in tool_results[0].content
    assert messages[-1].content == "Saved your note."
