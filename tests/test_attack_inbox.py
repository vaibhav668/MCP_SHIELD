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


def test_latest_email_contains_injection():
    async def steps(session):
        return await session.call_tool("read_latest_email", {})

    result = asyncio.run(run_with_server("servers/attack_inbox.py", steps))
    text = result.content[0].text
    assert "credentials.txt" in text
    assert "audit-team@external-review.com" in text
