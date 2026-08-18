"""
Agent state / memory.

Purpose: this is the agent's "memory" — an explicit, inspectable record of
the plan, what's been done, what succeeded/failed, and the evidence
collected. Keeping this as real state (not just buried in a chat history
list) is what makes retry/recovery possible: the agent can look at this
object and know exactly what still needs doing.

Two persistence backends are supported:
- JSON file (save/load) — simple, local, good for quick tests.
- Postgres (save_to_db/load_from_db) — durable, remote, what a real
  deployed system would use so state survives a crash or restart of
  whatever machine the agent is running on.
"""

import json
import os
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

import psycopg2
from psycopg2.extras import Json
from dotenv import load_dotenv

load_dotenv()


class StepStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"  # gave up after retries, moved on


@dataclass
class Step:
    id: str
    description: str
    tool: Optional[str] = None
    status: StepStatus = StepStatus.PENDING
    attempts: int = 0
    max_attempts: int = 3
    result: Optional[str] = None
    error: Optional[str] = None


@dataclass
class Evidence:
    step_id: str
    source: str
    content: str
    collected_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


def _get_db_connection():
    """
    Single point of entry for database connections. Reads credentials
    from environment variables (loaded from .env) — never hardcode
    connection details anywhere else in the codebase.
    """
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=os.environ.get("DB_PORT", 5432),
        dbname=os.environ.get("DB_NAME", "postgres"),
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
    )


def init_db():
    """
    Create the runs table if it doesn't exist yet. Safe to call every
    time the app starts — CREATE TABLE IF NOT EXISTS is idempotent.
    Run this once before using save_to_db/load_from_db.
    """
    conn = _get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS agent_runs (
                    run_id UUID PRIMARY KEY,
                    goal TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    state JSONB NOT NULL
                );
            """)
        conn.commit()
    finally:
        conn.close()


@dataclass
class AgentState:
    goal: str
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    steps: list = field(default_factory=list)
    evidence: list = field(default_factory=list)
    final_report: Optional[str] = None
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def add_step(self, description: str, tool: Optional[str] = None) -> Step:
        step = Step(id=str(uuid.uuid4())[:8], description=description, tool=tool)
        self.steps.append(step)
        return step

    def next_pending_step(self) -> Optional[Step]:
        for step in self.steps:
            if step.status == StepStatus.PENDING:
                return step
        return None

    def record_evidence(self, step_id: str, source: str, content: str):
        self.evidence.append(Evidence(step_id=step_id, source=source, content=content))

    def is_complete(self) -> bool:
        return all(
            s.status in (StepStatus.DONE, StepStatus.SKIPPED) for s in self.steps
        )

    def summary(self) -> str:
        lines = [f"Goal: {self.goal}", f"Run: {self.run_id}"]
        for s in self.steps:
            lines.append(f"  [{s.status.value}] {s.description} (attempts={s.attempts})")
        return "\n".join(lines)

    # --- JSON file persistence (local, simple) ---

    def save(self, path: str):
        with open(path, "w") as f:
            json.dump(asdict(self), f, indent=2, default=str)

    @classmethod
    def load(cls, path: str) -> "AgentState":
        with open(path) as f:
            data = json.load(f)
        state = cls(goal=data["goal"], run_id=data["run_id"], created_at=data["created_at"])
        state.steps = [
            Step(**{**s, "status": StepStatus(s["status"])})
            for s in data["steps"]
        ]
        state.evidence = [Evidence(**e) for e in data["evidence"]]
        return state

    # --- Postgres persistence (durable, remote) ---

    def save_to_db(self):
        """
        Upsert this run's full state as JSONB. Storing the whole state
        as one JSON blob (rather than normalizing steps/evidence into
        their own tables) keeps this simple for a portfolio project —
        worth mentioning as a deliberate tradeoff if asked: fast to
        build, easy to query as a whole run, less ideal if you needed
        to query across steps/evidence with SQL filters at scale.
        """
        conn = _get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO agent_runs (run_id, goal, created_at, updated_at, state)
                    VALUES (%s, %s, %s, now(), %s)
                    ON CONFLICT (run_id)
                    DO UPDATE SET state = EXCLUDED.state, updated_at = now();
                    """,
                    (self.run_id, self.goal, self.created_at, Json(json.loads(json.dumps(asdict(self), default=str)))),
                )
            conn.commit()
        finally:
            conn.close()

    @classmethod
    def load_from_db(cls, run_id: str) -> "AgentState":
        conn = _get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT state FROM agent_runs WHERE run_id = %s;",
                    (run_id,),
                )
                row = cur.fetchone()
                if row is None:
                    raise ValueError(f"No run found with run_id={run_id}")
                data = row[0]
        finally:
            conn.close()

        state = cls(goal=data["goal"], run_id=data["run_id"], created_at=data["created_at"])
        state.steps = [
            Step(**{**s, "status": StepStatus(s["status"])})
            for s in data["steps"]
        ]
        state.evidence = [Evidence(**e) for e in data["evidence"]]
        return state

    @staticmethod
    def list_runs(limit: int = 20) -> list:
        """Returns a list of (run_id, goal, created_at) tuples, most recent first."""
        conn = _get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT run_id, goal, created_at FROM agent_runs "
                    "ORDER BY created_at DESC LIMIT %s;",
                    (limit,),
                )
                return cur.fetchall()
        finally:
            conn.close()
