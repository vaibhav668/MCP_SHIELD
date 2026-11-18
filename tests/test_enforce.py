import asyncio

from shield import audit, graph, proxy
from shield.judge import Verdict


def judge_says_attack(monkeypatch):
    monkeypatch.setattr(graph, "ask_judge", lambda *a, **k: Verdict(is_attack=True, confidence=0.9, reason="looks bad"))


async def enforce_while_human_answers(decision):
    async def human():
        while not audit.pending():
            await asyncio.sleep(0.1)
        audit.answer(audit.pending()[0]["thread_id"], decision)

    helper = asyncio.create_task(human())
    outcome = await proxy.enforce("arguments", {"to": "friend@gmail.com"}, "send_email", "email")
    await helper
    return outcome


def test_approved_by_human_is_forwarded(monkeypatch):
    audit.DB_FILE.unlink(missing_ok=True)
    judge_says_attack(monkeypatch)
    action, content = asyncio.run(enforce_while_human_answers("approve"))
    assert action == "ALLOW" and content == {"to": "friend@gmail.com"}
    assert audit.read_audit()[-1]["human"] == "approve"


def test_denied_by_human_is_blocked(monkeypatch):
    audit.DB_FILE.unlink(missing_ok=True)
    judge_says_attack(monkeypatch)
    action, _ = asyncio.run(enforce_while_human_answers("deny"))
    assert action == "BLOCK"


def test_no_answer_means_deny(monkeypatch):
    audit.DB_FILE.unlink(missing_ok=True)
    judge_says_attack(monkeypatch)
    action, _ = asyncio.run(proxy.enforce("arguments", {"to": "friend@gmail.com"}, "send_email", "email", timeout=1))
    assert action == "BLOCK"
    assert audit.pending() == []
