"""
Dashboard backend.

Purpose: a small read-only API that surfaces two things the frontend
needs -- agent run history (from the agent's Postgres) and gateway
decision history (from the gateway's SQLite log) -- plus the static
page itself.

Run with: uvicorn dashboard.main:app --reload --port 8020
"""

import os
import sqlite3
import json
from pathlib import Path

import psycopg2
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Agent + Gateway Dashboard")

BASE_DIR = Path(__file__).resolve().parent.parent
GATEWAY_DB_PATH = BASE_DIR / "gateway" / "gateway_decisions.db"

STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def _agent_db_connection():
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=os.environ.get("DB_PORT", 5432),
        dbname=os.environ.get("DB_NAME", "postgres"),
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
    )


@app.get("/")
def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/api/agent-runs")
def agent_runs(limit: int = 20):
    try:
        conn = _agent_db_connection()
    except Exception as e:
        return {"error": f"Could not connect to agent database: {e}", "runs": []}

    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT run_id, goal, created_at, state FROM agent_runs "
                "ORDER BY created_at DESC LIMIT %s;",
                (limit,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    runs = []
    for run_id, goal, created_at, state in rows:
        steps = state.get("steps", [])
        evidence = state.get("evidence", [])
        done = sum(1 for s in steps if s.get("status") == "done")
        skipped = sum(1 for s in steps if s.get("status") == "skipped")
        runs.append({
            "run_id": str(run_id),
            "goal": goal,
            "created_at": str(created_at),
            "step_count": len(steps),
            "steps_done": done,
            "steps_skipped": skipped,
            "evidence_count": len(evidence),
            "has_report": bool(state.get("final_report")),
            "steps": steps,
            "final_report": state.get("final_report"),
        })
    return {"runs": runs}


@app.get("/api/gateway-decisions")
def gateway_decisions(limit: int = 50):
    if not GATEWAY_DB_PATH.exists():
        return {"error": "Gateway database not found -- has the gateway run at least once?", "decisions": []}

    conn = sqlite3.connect(str(GATEWAY_DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM decisions ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
    finally:
        conn.close()

    decisions = []
    for r in rows:
        d = dict(r)
        try:
            d["reasons"] = json.loads(d["reasons"])
        except (json.JSONDecodeError, TypeError):
            d["reasons"] = []
        decisions.append(d)
    return {"decisions": decisions}


@app.get("/api/summary")
def summary():
    agent_data = agent_runs(limit=1000)
    gateway_data = gateway_decisions(limit=1000)

    runs = agent_data.get("runs", [])
    decisions = gateway_data.get("decisions", [])

    return {
        "total_runs": len(runs),
        "total_gateway_requests": len(decisions),
        "total_blocked": sum(1 for d in decisions if d.get("action") == "block"),
        "total_redacted": sum(1 for d in decisions if d.get("action") == "redact"),
    }