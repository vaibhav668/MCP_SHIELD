from shield import audit


def fresh_db():
    audit.DB_FILE.unlink(missing_ok=True)


def test_audit_rows_are_saved_and_read_back():
    fresh_db()
    audit.log_audit("send_email", "email", "arguments", "BLOCK", "SANITIZE", "fast", 1.0, ["API key (sk-...)"], fast_ms=0.1)
    rows = audit.read_audit()
    assert len(rows) == 1
    assert rows[0]["tool"] == "send_email" and rows[0]["action"] == "SANITIZE"
    assert "API key" in rows[0]["reasons"]


def test_approval_lifecycle():
    fresh_db()
    audit.add_approval("t1", "send_email", {"what": "arguments", "content": "x"})
    assert audit.get_answer("t1") is None
    assert audit.pending()[0]["details"]["what"] == "arguments"
    audit.answer("t1", "approve")
    assert audit.get_answer("t1") == "approve"
    assert audit.pending() == []


def test_a_request_can_only_be_answered_once():
    fresh_db()
    audit.add_approval("t2", "send_email", {})
    audit.answer("t2", "deny")
    audit.answer("t2", "approve")  # too late, ignored
    assert audit.get_answer("t2") == "deny"
