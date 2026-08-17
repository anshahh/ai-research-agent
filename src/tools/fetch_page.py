"""
Fetch page tool.

Purpose: given a URL (usually found via web_search), fetch and return
its main text content. Complements web_search — search finds candidate
pages, fetch reads one in depth. Having two distinct tools is what
forces the planner to actually choose, rather than defaulting every
step to the same tool.
"""

import requests
from dataclasses import dataclass


@dataclass
class PageContent:
    url: str
    text: str


class ToolError(Exception):
    """Raised when a tool fails in a way the agent should handle (retry/skip)."""


def fetch_page(url: str) -> list:
    """
    Entry point the agent calls. Returns a list (of one item) to keep
    the same shape as web_search's return type, so agent.py's evidence-
    recording code doesn't need special-casing per tool.
    """
    if not url or not url.strip():
        raise ToolError("Empty URL")

    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
    except requests.RequestException as e:
        raise ToolError(f"Fetch failed for {url}: {e}") from e

    text = resp.text[:3000]
    return [PageContent(url=url, text=text)]
