import asyncio
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def run_with_notes_server(steps):
    """Start the notes server, run steps(session), return its result."""
    params = StdioServerParameters(command=sys.executable, args=["servers/notes_server.py"])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await steps(session)
           

def test_lists_three_tools():
    async def steps(session):
        return await session.list_tools()

    result = asyncio.run(run_with_notes_server(steps))
    names = {t.name for t in result.tools}
    assert names == {"add_note", "list_notes", "search_notes"}


def test_add_then_search_ignores_case():
    async def steps(session):
        await session.call_tool("add_note", {"text": "Buy milk"})
        return await session.call_tool("search_notes", {"query": "MILK"})

    result = asyncio.run(run_with_notes_server(steps))
    assert result.structured_content == {"result": ["Buy milk"]}
