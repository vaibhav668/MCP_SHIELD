import json
import os
import sqlite3
import time
from pathlib import Path

# SHIELD_AUDIT_DB lets the tests use their own database, so running pytest never wipes the real audit log.
DB_FILE = Path(os.getenv("SHIELD_AUDIT_DB") or Path(__file__).parent.parent / "logs" / "audit.db")

TABLES = """
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    time TEXT, tool TEXT, server TEXT, what TEXT,
    verdict TEXT, action TEXT, path TEXT, score REAL, reasons TEXT,
    fast_ms REAL, judge_ms REAL, judge_reason TEXT, human TEXT
);
CREATE TABLE IF NOT EXISTS approvals (
    thread_id TEXT PRIMARY KEY,
    time TEXT, tool TEXT, details TEXT,
    status TEXT DEFAULT 'pending'
);
CREATE TABLE IF NOT EXISTS trace (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT, t REAL, actor TEXT, stage TEXT, title TEXT, detail TEXT, level TEXT
);
CREATE TABLE IF NOT EXISTS verdict_cache (
    key TEXT PRIMARY KEY, action TEXT, time TEXT
);
"""


def connect():
    """Open the audit database (creating it on first use). One short connection per call keeps it simple and safe."""
    DB_FILE.parent.mkdir(exist_ok=True)
    db = sqlite3.connect(DB_FILE)
    db.row_factory = sqlite3.Row
    db.executescript(TABLES)
    return db


def log_audit(tool, server, what, verdict, action, path, score, reasons, fast_ms=None, judge_ms=None, judge_reason=None, human=None):
    """Write one decision to the audit table."""
    with connect() as db:
        db.execute(
            "INSERT INTO audit (time, tool, server, what, verdict, action, path, score, reasons, fast_ms, judge_ms, judge_reason, human)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (time.strftime("%Y-%m-%d %H:%M:%S"), tool, server, what, verdict, action, path, score,
             json.dumps(reasons), fast_ms, judge_ms, judge_reason, human),
        )


def read_audit():
    """Return every audit row, oldest first, as dicts."""
    with connect() as db:
        return [dict(row) for row in db.execute("SELECT * FROM audit ORDER BY id")]


def add_approval(thread_id, tool, details):
    """Record that a human needs to look at something."""
    with connect() as db:
        db.execute(
            "INSERT OR REPLACE INTO approvals (thread_id, time, tool, details, status) VALUES (?, ?, ?, ?, 'pending')",
            (thread_id, time.strftime("%Y-%m-%d %H:%M:%S"), tool, json.dumps(details)),
        )


def pending():
    """Approval requests nobody has answered yet."""
    with connect() as db:
        rows = db.execute("SELECT * FROM approvals WHERE status = 'pending' ORDER BY time").fetchall()
    return [dict(row, details=json.loads(row["details"])) for row in rows]


def answer(thread_id, status):
    """Set the answer ('approve', 'deny' or 'timeout'). Only a still-pending request can be answered."""
    with connect() as db:
        db.execute("UPDATE approvals SET status = ? WHERE thread_id = ? AND status = 'pending'", (status, thread_id))


def get_answer(thread_id):
    """Return the answer for a request, or None while it is still pending."""
    with connect() as db:
        row = db.execute("SELECT status FROM approvals WHERE thread_id = ?", (thread_id,)).fetchone()
    return None if row is None or row["status"] == "pending" else row["status"]


# ---------------- live trace (one row per step, shown in the dashboard's Live flow) ----------------

def add_trace(run_id, actor, stage, title, detail=None, level="info"):
    """Record one step. actor: user, agent, shield, server or system. level: info, ok, warn or block."""
    with connect() as db:
        db.execute("INSERT INTO trace (run_id, t, actor, stage, title, detail, level) VALUES (?, ?, ?, ?, ?, ?, ?)",
                   (run_id, time.time(), actor, stage, title, json.dumps(detail, default=str), level))


def read_trace(run_id, after=0):
    """Steps of one run with id greater than `after`, oldest first."""
    with connect() as db:
        rows = db.execute("SELECT * FROM trace WHERE run_id = ? AND id > ? ORDER BY id", (run_id, after)).fetchall()
    return [dict(row, detail=json.loads(row["detail"] or "null")) for row in rows]


def list_runs(limit=15):
    """Most recent runs: id, start time, number of steps and the last step."""
    with connect() as db:
        runs = db.execute("SELECT run_id, MIN(t) AS started, MAX(t) AS ended, COUNT(*) AS steps FROM trace"
                          " GROUP BY run_id ORDER BY started DESC LIMIT ?", (limit,)).fetchall()
        out = []
        for run in runs:
            first = db.execute("SELECT * FROM trace WHERE run_id = ? ORDER BY id LIMIT 1", (run["run_id"],)).fetchone()
            last = db.execute("SELECT * FROM trace WHERE run_id = ? ORDER BY id DESC LIMIT 1", (run["run_id"],)).fetchone()
            out.append({**dict(run), "first": dict(first, detail=json.loads(first["detail"] or "null")),
                        "last": dict(last, detail=json.loads(last["detail"] or "null"))})
    return out


# ---------------- verdict cache for tool descriptions (they rarely change) ----------------

def cached_verdict(key):
    with connect() as db:
        row = db.execute("SELECT action FROM verdict_cache WHERE key = ?", (key,)).fetchone()
    return row["action"] if row else None


def cache_verdict(key, action):
    with connect() as db:
        db.execute("INSERT OR REPLACE INTO verdict_cache (key, action, time) VALUES (?, ?, ?)",
                   (key, action, time.strftime("%Y-%m-%d %H:%M:%S")))
