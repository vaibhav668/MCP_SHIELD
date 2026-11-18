import os
import sys
from langchain_core.tools import StructuredTool
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
    

async def connect_server(stack, path):
    """Start one MCP server over stdio and return a ready session."""
    args = path if isinstance(path, list) else [path]
    # pass our environment on (API keys, SHIELD_RUN_ID for the dashboard's live trace)
    params = StdioServerParameters(command=sys.executable, args=args, env=dict(os.environ))
    read, write = await stack.enter_async_context(stdio_client(params))
    session = await stack.enter_async_context(ClientSession(read, write))
    await session.initialize()
    return session


def make_tool(session, mcp_tool):
    """Wrap one MCP tool as a LangChain tool."""

    async def call(**kwargs):
        result = await session.call_tool(mcp_tool.name, kwargs)
        return "\n".join(c.text for c in result.content if c.type == "text")

    return StructuredTool(
        name=mcp_tool.name,
        description=mcp_tool.description or "",
        args_schema=mcp_tool.input_schema,
        coroutine=call,
    )


async def load_tools(stack, paths):
    """Connect to every server in paths and return all their tools."""
    tools = []
    for path in paths:
        session = await connect_server(stack, path)
        listed = await session.list_tools()
        tools += [make_tool(session, t) for t in listed.tools]
    return tools
