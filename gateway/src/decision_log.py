"""
Decision log.

Purpose: every request that passes through the gateway gets a logged
decision — what was checked, what was found, what action was taken,
and how long each check took. This is what makes the gateway auditable
instead of a black box, and it's what the frontend dashboard reads from.

SQLite for today's scope — durable, zero setup, good enough for a
portfolio project's request volume.
"""

import os
import sqlite3
import uuid
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

DB_PATH = os.environ.get("GATEWAY_DB_PATH", "gateway_decisions.db")


def init_log_db(path: str = DB_PATH):
    conn = sqlite3.connect(path)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS decisions (
                id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                direction TEXT NOT NULL,
                action TEXT NOT NULL,
                reasons TEXT NOT NULL,
                latency_ms REAL NOT NULL,
                request_id TEXT NOT NULL
            );
        """)
        conn.commit()
    finally:
        conn.close()


@dataclass
class DecisionRecord:
    direction: str
    action: str
    reasons: list = field(default_factory=list)
    latency_ms: float = 0.0
    request_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])


def log_decision(record: DecisionRecord, path: str = DB_PATH):
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "INSERT INTO decisions (id, timestamp, direction, action, reasons, latency_ms, request_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                datetime.now(timezone.utc).isoformat(),
                record.direction,
                record.action,
                json.dumps(record.reasons),
                record.latency_ms,
                record.request_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def recent_decisions(limit: int = 50, path: str = DB_PATH) -> list:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM decisions ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
