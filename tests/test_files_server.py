import asyncio
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def run_with_server(path, steps):
    params = StdioServerParameters(command=sys.executable, args=[path])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await steps(session)


def test_read_file():
    async def steps(session):
        return await session.call_tool("read_file", {"name": "todo.txt"})

    result = asyncio.run(run_with_server("servers/files_server.py", steps))
    assert "groceries" in result.content[0].text


def test_path_traversal_blocked():
    async def steps(session):
        return await session.call_tool("read_file", {"name": "../pyproject.toml"})

    result = asyncio.run(run_with_server("servers/files_server.py", steps))
    assert result.content[0].text == "File not found."
