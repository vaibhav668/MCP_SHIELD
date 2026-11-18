import asyncio
from contextlib import AsyncExitStack

from mcp_tools import load_tools

SERVERS = ["servers/notes_server.py", "servers/files_server.py"]


async def with_tools(steps):
    async with AsyncExitStack() as stack:
        tools = await load_tools(stack, SERVERS)
        return await steps({t.name: t for t in tools})


def test_loads_tools_from_all_servers():
    async def steps(tools):
        return set(tools)

    names = asyncio.run(with_tools(steps))
    assert {"add_note", "read_file"} <= names


def test_tool_call_reaches_server():
    async def steps(tools):
        return await tools["read_file"].ainvoke({"name": "todo.txt"})

    assert "groceries" in asyncio.run(with_tools(steps))
