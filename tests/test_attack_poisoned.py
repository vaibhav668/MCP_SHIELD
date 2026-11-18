import asyncio
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

STOLEN = Path("logs/stolen.txt")


async def run_with_server(path, steps):
    params = StdioServerParameters(command=sys.executable, args=[path])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await steps(session)


def test_description_contains_hidden_instructions():
    async def steps(session):
        return await session.list_tools()

    result = asyncio.run(run_with_server("servers/attack_poisoned.py", steps))
    assert "<IMPORTANT>" in result.tools[0].description


def test_tool_records_stolen_context():
    STOLEN.unlink(missing_ok=True)

    async def steps(session):
        return await session.call_tool("add_numbers", {"a": 2, "b": 3, "context": "API_KEY=fake"})

    result = asyncio.run(run_with_server("servers/attack_poisoned.py", steps))
    assert result.structured_content == {"result": 5}
    assert STOLEN.read_text() == "API_KEY=fake"
