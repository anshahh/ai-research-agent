"""
Security Gateway — proxy layer.

Purpose: this is the single checkpoint every request passes through
before reaching Claude and before the response reaches the caller.
Input pipeline runs first (regex injection scan, LLM judge for
ambiguous cases, PII redaction), then the model is called (streaming
or not, single-turn or multi-turn), then the output pipeline runs
(PII leak scan) before the response goes back.

Run with: uvicorn main:app --reload --port 8010
"""

import os
import time
import json
import logging
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import anthropic
from dotenv import load_dotenv

from src.pii import scan_and_redact
from src.injection import scan as scan_injection, should_escalate, InjectionFinding
from src.llm_judge import judge_if_ambiguous
from src.output_validator import check_output
from src.policy import Policy
from src.decision_log import init_log_db, log_decision, DecisionRecord, recent_decisions
from src.auth import require_api_key

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("gateway")

app = FastAPI(title="AI Safety Gateway")

policy = Policy.load("policy.yaml")
init_log_db()

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: Optional[str] = None
    messages: Optional[list] = None
    system: str = "You are a helpful assistant."
    max_tokens: int = 1024


class ChatResponse(BaseModel):
    response: str
    input_action: str
    output_action: str
    request_id: str


def _resolve_conversation(req: ChatRequest) -> list:
    if req.messages:
        return [dict(m) for m in req.messages]
    if req.message:
        return [{"role": "user", "content": req.message}]
    raise HTTPException(status_code=422, detail="Provide either 'message' or 'messages'")


def _run_input_pipeline(latest_user_text: str, start: float) -> tuple:
    input_reasons = []
    working_text = latest_user_text

    if policy.injection_enabled:
        injection_result = scan_injection(working_text)
        should_block = injection_result.is_suspicious and policy.injection_action == "block"
        judge_reason = None

        judge_result = judge_if_ambiguous(
            working_text, injection_result.risk_score, force_escalate=should_escalate(working_text)
        )
        if judge_result.was_invoked and judge_result.is_attack and judge_result.confidence >= 0.6:
            should_block = True
            judge_reason = f"LLM judge flagged (confidence={judge_result.confidence:.2f}): {judge_result.reasoning}"

        if should_block:
            reasons = [f"Injection detected: {f.rule}" for f in injection_result.findings]
            if judge_reason:
                reasons.append(judge_reason)
            latency_ms = (time.time() - start) * 1000
            record = DecisionRecord(direction="input", action="block", reasons=reasons, latency_ms=latency_ms)
            log_decision(record)
            logger.warning("BLOCKED input (request %s): %s", record.request_id, reasons)
            raise HTTPException(
                status_code=400,
                detail={"error": "Request blocked by security policy", "reasons": reasons},
            )

    if policy.pii_input_enabled:
        pii_result = scan_and_redact(working_text, categories=policy.pii_input_categories)
        if pii_result.had_pii:
            working_text = pii_result.redacted_text
            categories = sorted({m.category for m in pii_result.matches})
            input_reasons.append(f"PII redacted from input: {', '.join(categories)}")

    input_latency_ms = (time.time() - start) * 1000
    input_record = DecisionRecord(
        direction="input",
        action="redact" if input_reasons else "allow",
        reasons=input_reasons,
        latency_ms=input_latency_ms,
    )
    log_decision(input_record)
    return working_text, input_record


@app.post("/v1/chat", response_model=ChatResponse)
def chat(req: ChatRequest, api_key: str = Depends(require_api_key)):
    start = time.time()
    conversation = _resolve_conversation(req)

    latest = conversation[-1]["content"]
    screened_text, input_record = _run_input_pipeline(latest, start)
    conversation[-1]["content"] = screened_text
    request_id = input_record.request_id

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=req.max_tokens,
            system=req.system,
            messages=conversation,
        )
        model_text = "".join(b.text for b in response.content if b.type == "text")
    except anthropic.APIError as e:
        logger.error("Model call failed for request %s: %s", request_id, e)
        raise HTTPException(status_code=502, detail="Upstream model error")

    output_start = time.time()
    output_result = check_output(model_text) if policy.pii_output_enabled else None
    final_text = output_result.final_text if output_result else model_text
    output_action = output_result.action if output_result else "allow"
    output_reasons = output_result.reasons if output_result else []

    output_latency_ms = (time.time() - output_start) * 1000
    output_record = DecisionRecord(
        direction="output", action=output_action, reasons=output_reasons,
        latency_ms=output_latency_ms, request_id=request_id,
    )
    log_decision(output_record)

    return ChatResponse(
        response=final_text,
        input_action=input_record.action,
        output_action=output_action,
        request_id=request_id,
    )


@app.post("/v1/chat/stream")
def chat_stream(req: ChatRequest, api_key: str = Depends(require_api_key)):
    """
    Streaming variant. Input pipeline still runs BEFORE any tokens are
    streamed. The output PII scan runs on the buffered full text at the
    end of the stream — a genuine tradeoff: you can't redact a leak
    that's already been streamed token-by-token. Disclosed via the
    final SSE event's output_action field and a log warning, not hidden.
    """
    start = time.time()
    conversation = _resolve_conversation(req)
    latest = conversation[-1]["content"]
    screened_text, input_record = _run_input_pipeline(latest, start)
    conversation[-1]["content"] = screened_text
    request_id = input_record.request_id

    def event_stream():
        full_text = ""
        try:
            with client.messages.stream(
                model="claude-sonnet-4-6",
                max_tokens=req.max_tokens,
                system=req.system,
                messages=conversation,
            ) as stream:
                for text_chunk in stream.text_stream:
                    full_text += text_chunk
                    yield f"data: {json.dumps({'delta': text_chunk})}\n\n"
        except anthropic.APIError as e:
            logger.error("Streaming model call failed for request %s: %s", request_id, e)
            yield f"data: {json.dumps({'error': 'Upstream model error'})}\n\n"
            return

        output_start = time.time()
        output_result = check_output(full_text) if policy.pii_output_enabled else None
        output_action = output_result.action if output_result else "allow"
        output_reasons = output_result.reasons if output_result else []
        output_latency_ms = (time.time() - output_start) * 1000

        log_decision(DecisionRecord(
            direction="output", action=output_action, reasons=output_reasons,
            latency_ms=output_latency_ms, request_id=request_id,
        ))

        if output_action == "redact":
            logger.warning("PII detected in streamed output for request %s (already sent)", request_id)

        yield f"data: {json.dumps({'done': True, 'input_action': input_record.action, 'output_action': output_action, 'request_id': request_id})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/v1/decisions")
def get_decisions(limit: int = 50):
    """Returns recent gateway decisions — what the frontend dashboard reads."""
    return recent_decisions(limit=limit)


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8010)
