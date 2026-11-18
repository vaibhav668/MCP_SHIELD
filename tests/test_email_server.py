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


def test_read_email():
    async def steps(session):
        return await session.call_tool("read_email", {"email_id": 0})

    result = asyncio.run(run_with_server("servers/email_server.py", steps))
    assert "3pm" in result.content[0].text


def test_send_email():
    async def steps(session):
        return await session.call_tool("send_email", {"to": "a@b.com", "body": "hi"})

    result = asyncio.run(run_with_server("servers/email_server.py", steps))
    assert "a@b.com" in result.content[0].text
