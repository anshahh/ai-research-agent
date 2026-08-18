"""
Auth and rate limiting.

Purpose: right now anyone who can reach the gateway's port can call it.
This adds two protections:
  1. API key auth — a caller must present a valid key in the
     Authorization header, checked against keys defined in .env.
  2. Rate limiting — a simple in-memory token bucket per API key, so
     one caller can't exhaust the gateway's (and your Anthropic
     account's) capacity.

In-memory rate limiting is a deliberate, disclosed tradeoff: it resets
if the server restarts, and doesn't share state across multiple gateway
instances. A real multi-replica deployment would use Redis instead.
"""

import os
import time
import logging
from dataclasses import dataclass, field

from fastapi import Header, HTTPException
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("auth")

RATE_LIMIT_MAX_REQUESTS = 20
RATE_LIMIT_WINDOW_SECONDS = 60


def _load_valid_keys() -> set:
    raw = os.environ.get("GATEWAY_API_KEYS", "")
    keys = {k.strip() for k in raw.split(",") if k.strip()}
    if not keys:
        logger.warning(
            "No GATEWAY_API_KEYS configured — set this in .env, "
            "otherwise the gateway will reject all requests."
        )
    return keys


VALID_KEYS = _load_valid_keys()


@dataclass
class _Bucket:
    timestamps: list = field(default_factory=list)


_buckets: dict = {}


def _check_rate_limit(key: str):
    now = time.time()
    bucket = _buckets.setdefault(key, _Bucket())
    bucket.timestamps = [t for t in bucket.timestamps if now - t < RATE_LIMIT_WINDOW_SECONDS]

    if len(bucket.timestamps) >= RATE_LIMIT_MAX_REQUESTS:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "Rate limit exceeded",
                "limit": RATE_LIMIT_MAX_REQUESTS,
                "window_seconds": RATE_LIMIT_WINDOW_SECONDS,
            },
        )
    bucket.timestamps.append(now)


def require_api_key(authorization: str = Header(default=None)) -> str:
    """
    FastAPI dependency: validates the Authorization header and enforces
    rate limiting. Expected header format: "Bearer <key>".
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")

    key = authorization.removeprefix("Bearer ").strip()

    if key not in VALID_KEYS:
        raise HTTPException(status_code=401, detail="Invalid API key")

    _check_rate_limit(key)
    return key
