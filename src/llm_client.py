"""
LLM client wrapper — now routed through the security gateway.

Purpose: every model call in this project goes through here. Previously
this called the Anthropic API directly; now it calls the gateway's
/v1/chat endpoint instead, so every planning/tool-use call the agent
makes is screened for injection attempts and PII before reaching
Claude, and every response is scanned before the agent acts on it.
"""

import os
import time
import random
import logging
from dataclasses import dataclass
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("llm_client")

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://localhost:8010")
GATEWAY_API_KEY = os.environ.get("GATEWAY_API_KEY")


@dataclass
class LLMResponse:
    text: str
    model: str
    input_action: str
    output_action: str
    request_id: str


class GatewayBlockedError(Exception):
    """Raised when the gateway blocks a request outright. Not retried —
    retrying the exact same blocked text will just get blocked again."""


class LLMClient:
    def __init__(self, max_retries: int = 3, base_delay: float = 1.0, timeout: float = 60.0):
        if not GATEWAY_API_KEY:
            raise RuntimeError(
                "GATEWAY_API_KEY not set. Put it in your .env file — "
                "must match a key in the gateway's GATEWAY_API_KEYS."
            )
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.timeout = timeout

    def call(self, system: str, messages: list, max_tokens: int = 1024, temperature: float = 0.0) -> LLMResponse:
        user_content = messages[-1]["content"] if messages else ""
        last_error: Optional[Exception] = None

        for attempt in range(self.max_retries):
            try:
                response = requests.post(
                    f"{GATEWAY_URL}/v1/chat",
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {GATEWAY_API_KEY}",
                    },
                    json={"message": user_content, "system": system, "max_tokens": max_tokens},
                    timeout=self.timeout,
                )

                if response.status_code == 400:
                    detail = response.json().get("detail", {})
                    reasons = detail.get("reasons", []) if isinstance(detail, dict) else []
                    logger.error("Request BLOCKED by gateway: %s", reasons)
                    raise GatewayBlockedError(f"Blocked by gateway security policy: {reasons}")

                if response.status_code == 401:
                    raise RuntimeError(f"Gateway auth failed: {response.text}")

                if response.status_code == 429:
                    raise requests.exceptions.RequestException(f"Rate limited by gateway: {response.text}")

                response.raise_for_status()
                data = response.json()

                return LLMResponse(
                    text=data["response"],
                    model="claude-sonnet-4-6",
                    input_action=data["input_action"],
                    output_action=data["output_action"],
                    request_id=data["request_id"],
                )

            except GatewayBlockedError:
                raise

            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                last_error = e
                delay = self.base_delay * (2 ** attempt) + random.uniform(0, 0.5)
                logger.warning("Gateway call failed (attempt %d/%d): %s. Retrying in %.1fs",
                               attempt + 1, self.max_retries, e, delay)
                time.sleep(delay)

            except requests.exceptions.RequestException as e:
                last_error = e
                delay = self.base_delay * (2 ** attempt) + random.uniform(0, 0.5)
                logger.warning("Gateway call failed (attempt %d/%d): %s. Retrying in %.1fs",
                               attempt + 1, self.max_retries, e, delay)
                time.sleep(delay)

        logger.error("Gateway call failed after %d attempts", self.max_retries)
        raise last_error


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    client = LLMClient()
    result = client.call(
        system="You are a terse assistant.",
        messages=[{"role": "user", "content": "Say hello in five words or fewer."}],
        max_tokens=50,
    )
    print(result)
