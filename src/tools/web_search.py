"""
Web search tool.

Purpose: one tool, wrapping Tavily's search API. The agent calls
`web_search(query)` and gets back typed results — it never touches
Tavily's API directly, so swapping providers later only means editing
this file.

CHAOS_MODE: set this env var to simulate a flaky tool for demo/testing
purposes — the first N calls per unique query fail with a fake transient
error, then subsequent calls hit the real API. This proves retry logic
recovers mid-run, not just that it gives up gracefully. Remove or leave
unset for normal use.
"""

import os
from collections import defaultdict
from dataclasses import dataclass

import requests
from dotenv import load_dotenv

load_dotenv()

# Tracks how many times each query has been attempted, for CHAOS_MODE only.
_attempt_counts = defaultdict(int)


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str


class ToolError(Exception):
    """Raised when a tool fails in a way the agent should handle (retry/skip)."""


def _search_backend(query: str) -> list:
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        raise ToolError("TAVILY_API_KEY not set in .env")

    try:
        resp = requests.post(
            "https://api.tavily.com/search",
            json={"api_key": api_key, "query": query, "max_results": 5},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        raise ToolError(f"Tavily request failed: {e}") from e

    return [
        SearchResult(
            title=r.get("title", ""),
            url=r.get("url", ""),
            snippet=r.get("content", ""),
        )
        for r in data.get("results", [])
    ]


def web_search(query: str) -> list:
    """
    Entry point the agent calls. Wraps backend errors into ToolError so
    the agent's retry logic has one exception type to catch, regardless
    of which backend is plugged in underneath.
    """
    if not query or not query.strip():
        raise ToolError("Empty search query")

    # --- CHAOS_MODE: simulate a transient failure before hitting the real API ---
    chaos_fail_count = int(os.environ.get("CHAOS_MODE", "0"))
    if chaos_fail_count > 0:
        _attempt_counts[query] += 1
        if _attempt_counts[query] <= chaos_fail_count:
            raise ToolError(
                f"[simulated] Transient network error on attempt "
                f"{_attempt_counts[query]} for query: {query!r}"
            )
    # --- end chaos mode ---

    try:
        return _search_backend(query)
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(f"Search failed: {e}") from e