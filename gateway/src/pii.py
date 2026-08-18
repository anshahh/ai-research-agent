"""
PII detection and redaction.

Purpose: scan text for common categories of personally identifiable
information and redact them before they leave the gateway (on the way
out) or before they reach the model unnecessarily (on the way in).

Deliberately deterministic (regex-based), not ML/LLM-based, for this
first pass — cheap, fast, explainable, and testable.
"""

import re
from dataclasses import dataclass, field


@dataclass
class PIIMatch:
    category: str
    original: str
    start: int
    end: int


@dataclass
class RedactionResult:
    redacted_text: str
    matches: list = field(default_factory=list)

    @property
    def had_pii(self) -> bool:
        return len(self.matches) > 0


PATTERNS = {
    "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    "phone_us": re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),
    "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "credit_card": re.compile(r"\b(?:\d[ -]*?){13,16}\b"),
    "api_key_generic": re.compile(r"\b(sk|pk|api|key)[-_][A-Za-z0-9]{16,}\b", re.IGNORECASE),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "ip_address": re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
}

REDACTION_LABELS = {
    "email": "[REDACTED_EMAIL]",
    "phone_us": "[REDACTED_PHONE]",
    "ssn": "[REDACTED_SSN]",
    "credit_card": "[REDACTED_CARD]",
    "api_key_generic": "[REDACTED_API_KEY]",
    "aws_access_key": "[REDACTED_AWS_KEY]",
    "ip_address": "[REDACTED_IP]",
}


def scan_and_redact(text: str, categories: list = None) -> RedactionResult:
    """
    Scan text for PII and return a redacted version plus a list of what
    was found (category + span, not the raw value).
    """
    active_categories = categories or list(PATTERNS.keys())
    matches = []
    redacted = text

    ordered = sorted(active_categories, key=lambda c: -len(c))

    for category in ordered:
        pattern = PATTERNS.get(category)
        if pattern is None:
            continue
        for m in pattern.finditer(redacted):
            matches.append(PIIMatch(
                category=category,
                original=m.group()[:4] + "***",
                start=m.start(),
                end=m.end(),
            ))
        redacted = pattern.sub(REDACTION_LABELS[category], redacted)

    return RedactionResult(redacted_text=redacted, matches=matches)
