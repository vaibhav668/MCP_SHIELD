import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from shield import audit

LOG = Path("logs/shield_log.jsonl")
SENT = Path("logs/sent_emails.jsonl")
BASIC = ["servers/notes_server.py", "servers/files_server.py"]


async def with_proxy(steps, servers=BASIC):
    # pass the environment on so the proxy also uses the test policy (SHIELD_POLICY, set in conftest.py)
    params = StdioServerParameters(command=sys.executable, args=["shield/proxy.py", *servers], env=dict(os.environ))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await steps(session)


def read_log():
    return [json.loads(line) for line in LOG.read_text().splitlines()]


def reset():
    LOG.unlink(missing_ok=True)
    SENT.unlink(missing_ok=True)
    audit.DB_FILE.unlink(missing_ok=True)


def test_proxy_lists_tools_from_all_servers():
    reset()

    async def steps(session):
        return await session.list_tools()

    names = {t.name for t in asyncio.run(with_proxy(steps)).tools}
    assert {"add_note", "read_file"} <= names
    assert any(e["kind"] == "tool_listed" and e["tool"] == "read_file" for e in read_log())


def test_proxy_forwards_call_and_logs_it():
    reset()

    async def steps(session):
        return await session.call_tool("read_file", {"name": "todo.txt"})

    result = asyncio.run(with_proxy(steps))
    assert "groceries" in result.content[0].text
    calls = [e for e in read_log() if e["kind"] == "tool_call"]
    assert calls[0]["tool"] == "read_file"
    assert calls[0]["arguments"] == {"name": "todo.txt"}
    assert "groceries" in calls[0]["result"]


def test_proxy_writes_audit_rows_for_every_check():
    reset()

    async def steps(session):
        return await session.call_tool("read_file", {"name": "credentials.txt"})

    result = asyncio.run(with_proxy(steps))
    assert "sk-fake" in result.content[0].text  # nothing suspicious in this call, so it is forwarded
    rows = audit.read_audit()
    assert {"description", "arguments", "result"} <= {r["what"] for r in rows}
    assert all(r["action"] in ("ALLOW", "BLOCK", "SANITIZE") for r in rows)


def test_proxy_hides_the_poisoned_tool():
    reset()

    async def steps(session):
        return await session.list_tools()

    names = {t.name for t in asyncio.run(with_proxy(steps, ["servers/files_server.py", "servers/attack_poisoned.py"])).tools}
    assert "read_file" in names
    assert "add_numbers" not in names
    assert any(r["tool"] == "add_numbers" and r["action"] == "BLOCK" for r in audit.read_audit())


def test_proxy_removes_injected_instructions_from_a_result():
    reset()

    async def steps(session):
        return await session.call_tool("read_latest_email", {})

    result = asyncio.run(with_proxy(steps, ["servers/attack_inbox.py"]))
    text = result.content[0].text
    assert "send_email" not in text and "pre-approved" not in text
    assert "Quarterly security audit" in text
    assert any(r["what"] == "result" and r["action"] == "SANITIZE" for r in audit.read_audit())


def test_proxy_redacts_a_secret_before_it_reaches_the_tool():
    reset()

    async def steps(session):
        return await session.call_tool("send_email", {"to": "boss@company.com", "body": "API_KEY=sk-fake-1234567890abcdef"})

    asyncio.run(with_proxy(steps, ["servers/email_server.py"]))
    sent = SENT.read_text()
    assert "sk-fake" not in sent and "REDACTED" in sent
