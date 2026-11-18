from mcp.server.mcpserver import MCPServer
import json
from pathlib import Path


mcp = MCPServer("email")

inbox = [
    {"id": 0, "from": "boss@company.com", "subject": "Weekly sync", "body": "Meeting moved to 3pm Thursday."},
    {"id": 1, "from": "hr@company.com", "subject": "Benefits update", "body": "Open enrollment ends Friday."},
]

sent =[]

@mcp.tool()
def list_emails() -> list[dict]:
    """List the inbox (id, sender, subject)."""
    return [{"id": e["id"], "from": e["from"], "subject": e["subject"]} for e in inbox]

@mcp.tool()
def read_email(email_id: int) -> str:
    """Read the full body of one email"""

    for e in inbox:
        if e["id"] == email_id:
            return e["body"]

    return "Email not found."

@mcp.tool()
def send_email(to: str , body: str) -> str:
    """Send an email"""
    sent.append({"to":to , "body":body})
    log = Path(__file__).parent.parent / "logs" / "sent_emails.jsonl"
    log.parent.mkdir(exist_ok=True)
    with log.open("a") as f:
        f.write(json.dumps({"to": to, "body": body}) + "\n")
    return f"Email sent to {to}"

if __name__ == "__main__":
    mcp.run(transport = "stdio") 

