"""
LLM client wrapper.

Purpose: every model call in this project goes through here — never call
the Anthropic SDK directly from agent.py or anywhere else. This is what
lets you swap models, add caching, or change retry behavior in one place
later without touching application code.
"""

import os
import time
import random
import logging
from dataclasses import dataclass
from typing import Optional

import anthropic
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("llm_client")


@dataclass
class LLMResponse:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    stop_reason: str


class LLMClient:
    def __init__(
        self,
        model: str = "claude-sonnet-4-6",
        max_retries: int = 3,
        base_delay: float = 1.0,
        timeout: float = 60.0,
    ):
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY not set. Put it in your .env file "
                "(and make sure .env is in .gitignore)."
            )
        self.client = anthropic.Anthropic(api_key=api_key, timeout=timeout)
        self.model = model
        self.max_retries = max_retries
        self.base_delay = base_delay

    def call(
        self,
        system: str,
        messages: list,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> LLMResponse:
        """
        Single point of entry for every model call in the project.
        Retries on transient errors (rate limits, timeouts, 5xx) with
        exponential backoff + jitter. Does NOT retry on bad-request-type
        errors — those will just fail the same way again.
        """
        last_error: Optional[Exception] = None

        for attempt in range(self.max_retries):
            try:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    system=system,
                    messages=messages,
                )
                text = "".join(
                    block.text for block in response.content if block.type == "text"
                )
                return LLMResponse(
                    text=text,
                    model=response.model,
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                    stop_reason=response.stop_reason,
                )

            except (
                anthropic.RateLimitError,
                anthropic.APITimeoutError,
                anthropic.InternalServerError,
                anthropic.APIConnectionError,
            ) as e:
                last_error = e
                delay = self.base_delay * (2 ** attempt) + random.uniform(0, 0.5)
                logger.warning(
                    "LLM call failed (attempt %d/%d): %s. Retrying in %.1fs",
                    attempt + 1, self.max_retries, e, delay,
                )
                time.sleep(delay)

            except anthropic.BadRequestError as e:
                # Not retryable — malformed request, won't fix itself.
                logger.error("Non-retryable LLM error: %s", e)
                raise

        logger.error("LLM call failed after %d attempts", self.max_retries)
        raise last_error


if __name__ == "__main__":
    # Quick smoke test — run `python3 src/llm_client.py` after setting
    # ANTHROPIC_API_KEY to confirm this works before building on top of it.
    logging.basicConfig(level=logging.INFO)
    client = LLMClient()
    result = client.call(
        system="You are a terse assistant.",
        messages=[{"role": "user", "content": "Say hello in five words or fewer."}],
        max_tokens=50,
    )
    print(result)