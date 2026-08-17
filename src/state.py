"""
Agent state / memory.

Purpose: this is the agent's "memory" — an explicit, inspectable record of
the plan, what's been done, what succeeded/failed, and the evidence
collected. Keeping this as real state (not just buried in a chat history
list) is what makes retry/recovery possible: the agent can look at this
object and know exactly what still needs doing.

Starts in-memory / JSON-file backed for day one. Swap for Postgres once
the loop itself is working — don't build the database before you know
the shape of what you're storing.
"""

import json
from os import path
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


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


@dataclass
class AgentState:
    goal: str
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    steps: list = field(default_factory=list)
    evidence: list = field(default_factory=list)
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