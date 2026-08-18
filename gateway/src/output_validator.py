"""
Output validation.

Purpose: check what the model is about to send back BEFORE it leaves
the gateway. Two jobs:
  1. PII leak scan — the same detector used on input, run again on
     output, since a model can echo back or fabricate PII-shaped text
     even if the input was clean.
  2. Basic structural sanity checks — placeholder for schema validation
     against a JSON schema when the caller expects structured output.
"""

from dataclasses import dataclass, field

from src.pii import scan_and_redact, RedactionResult


@dataclass
class OutputCheckResult:
    action: str  # "allow", "redact", or "block"
    final_text: str
    pii_result: RedactionResult
    reasons: list = field(default_factory=list)


def check_output(text: str) -> OutputCheckResult:
    """
    Run the output pipeline. For today's scope: redact any PII found
    (rather than hard-blocking), since redaction preserves usefulness
    of the response while still preventing the leak.
    """
    pii_result = scan_and_redact(text)

    if pii_result.had_pii:
        categories = sorted({m.category for m in pii_result.matches})
        return OutputCheckResult(
            action="redact",
            final_text=pii_result.redacted_text,
            pii_result=pii_result,
            reasons=[f"PII detected and redacted: {', '.join(categories)}"],
        )

    return OutputCheckResult(
        action="allow",
        final_text=text,
        pii_result=pii_result,
        reasons=[],
    )
