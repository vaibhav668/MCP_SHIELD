from pathlib import Path

from mcp.server.mcpserver import MCPServer

mcp = MCPServer("files")
SANDBOX = Path(__file__).parent.parent / "sandbox"


@mcp.tool()
def list_files() -> list[str]:
    """List the files in the sandbox folder."""
    return sorted(p.name for p in SANDBOX.iterdir())


@mcp.tool()
def read_file(name: str) -> str:
    """Read one file from the sandbox folder."""
    path = SANDBOX / Path(name).name
    if not path.is_file():
        return "File not found."
    return path.read_text()


if __name__ == "__main__":
    mcp.run(transport="stdio")
