# AI Research Agent + Security Gateway

An autonomous research agent -- planning, tool use, memory, and retry/recovery -- deployed behind a security gateway that screens every input and output for prompt injection and PII, including attacks hidden inside content the agent retrieves from the open web. Provisioned with Terraform, deployed via CI/CD.

This is not a RAG chatbot. A chatbot answers one question with retrieved context in a single call. This system plans a multi-step research task on its own, executes tools with real retry/recovery, persists every run to a durable database, synthesizes a final report, and routes every one of those model calls through a separate security layer -- including a proven live defense against a prompt injection attack hidden inside retrieved web content.

## Architecture

    User goal
       |
       v
    [ Agent: plan -> execute tools -> synthesize report ]
       |                                    |
       | every LLM call                     | tool calls
       v                                    v
    [ Security Gateway ]              [ web_search, fetch_page ]
       |  - injection detection (regex + LLM judge)
       |  - PII redaction (input + output)
       |  - auth + rate limiting
       |  - decision logging
       v
    [ Claude API ]

    State persisted to: AWS RDS Postgres (provisioned via Terraform)
    Deployed via: GitHub Actions (plan on PR, apply on merge)

## Components

### /src -- the agent
- llm_client.py -- routes every model call through the gateway, not directly to Anthropic. Retries on transient errors with exponential backoff; does not retry gateway-blocked requests.
- state.py -- run state (goal, steps, evidence, final report), persisted to both a local JSON file and a real Postgres instance.
- agent.py -- plans a goal into steps, executes tools with per-step retry (3 attempts, then degrades gracefully instead of crashing), then synthesizes a final report from all collected evidence.
- tools/ -- web_search (Tavily) and fetch_page, the two tools the planner chooses between.

### /gateway -- the security layer
- src/injection.py -- two-tier prompt injection detection: narrow high-precision regex rules for direct blocking, plus a broader low-precision trigger list that escalates ambiguous or fully-rephrased attacks to an LLM judge (src/llm_judge.py).
- src/pii.py -- regex-based PII detection/redaction (email, phone, SSN, credit card, API keys, AWS keys), run on both input and output.
- src/auth.py -- API key auth + in-memory rate limiting.
- main.py -- the FastAPI proxy itself: single-turn, multi-turn, and streaming endpoints, all passing through the same input/output pipeline.
- policy.yaml -- detection behavior is configuration, not code.
- tests/run_redteam.py -- 26 labeled test cases (including deliberately hard rephrased-attack and benign-but-adjacent-sounding cases). Current result: 100 percent precision, 100 percent recall, 0 false positives, 0 false negatives.

### /infra -- Terraform
- Provisions AWS RDS Postgres (db.t3.micro), a security group scoped to a single IP, and a subnet group, using a remote S3 backend so state is shared between local runs and CI.

### /.github/workflows -- CI/CD
- terraform plan runs automatically on any PR touching /infra.
- terraform apply runs automatically on merge to main.

## Proven, not claimed

Every claim below has a reproducible test behind it in this repo.

Retry/recovery works on total failure: killed the search API key mid-run, all steps retried 3x, then skipped gracefully, run completed.
Retry/recovery works on transient failure: CHAOS_MODE=1 forces first attempt to fail, second succeeds, proven in logs.
Injection detection catches direct attacks: tests/run_redteam.py, regex layer alone.
Injection detection catches rephrased attacks: same suite, LLM judge layer, e.g. kindly set aside earlier guidance.
Gateway defends the agent, not just itself: tests/test_injection_defense.py, a fake compromised web page with a hidden SYSTEM attack embedded in otherwise-legitimate content, fed through the real synthesis path, blocked with 95 percent judge confidence.
Infrastructure is real, not simulated: terraform apply output showing a live RDS endpoint; psql/psycopg2 connection confirmed.
CI/CD is real, not simulated: GitHub Actions run history showing plan-on-PR and apply-on-merge, including a caught and fixed remote-state bug.

## Known limitations (disclosed, not hidden)

- Injection detection is regex plus one LLM judge call, not a fine-tuned classifier. A sufficiently novel attack could still get through; the 26-case suite is a demo-quality baseline, not exhaustive coverage.
- Rate limiting is in-memory, per-process, resets on restart, does not share state across multiple gateway instances. A real multi-replica deployment would use Redis.
- Streaming responses cannot be redacted mid-stream. A PII leak in a streamed response is logged after the fact, not prevented in-flight. Documented in gateway/main.py streaming endpoint.
- No policy hot-reload or per-tenant overrides yet (policy.yaml is read once at startup).

## Running it locally

Start the gateway first, from the gateway folder: create a venv, activate it, pip install -r requirements.txt, then uvicorn main:app --reload --port 8010

Then in a separate terminal, from the project root: create a venv, activate it, pip install -r requirements.txt, then python3 -m src.agent

## Infrastructure

From the infra folder: terraform init, terraform plan, terraform apply to provision, terraform destroy to tear down when not in active use.
