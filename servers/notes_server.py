from mcp.server.mcpserver import MCPServer

mcp = MCPServer("notes")
notes= []

@mcp.tool()
def add_note(text : str) ->str:
    """Save a note."""
    notes.append(text)
    return f"Saved note #{len(notes)-1}"

@mcp.tool()
def list_notes() ->list[str]:
    """Return all notes."""
    return notes

@mcp.tool()
def search_notes(query:str)-> list[str]:
    """Return notes containing the query"""
    return [n for n in notes if query.lower() in n.lower()]

if __name__ == "__main__":
    mcp.run(transport ="stdio")

