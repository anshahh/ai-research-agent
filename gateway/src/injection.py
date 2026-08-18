"""
Injection / jailbreak detection.

Purpose: catch attempts to override the system's instructions, extract
its system prompt, or make it ignore safety behavior.

Two-tier design:
  - RULES: narrow, high-precision patterns used to BLOCK directly.
  - ESCALATION_TRIGGERS: broader, low-precision keywords used ONLY to
    decide whether to send the text to the LLM judge for a second
    look — never used to block on their own. This exists because a
    fully rephrased attack can share zero keywords with RULES and
    score exactly 0.0, which would otherwise be indistinguishable
    from genuinely clean text.
"""

import re
from dataclasses import dataclass, field


@dataclass
class InjectionFinding:
    rule: str
    matched_text: str


@dataclass
class InjectionResult:
    is_suspicious: bool
    findings: list = field(default_factory=list)
    risk_score: float = 0.0


RULES = [
    (re.compile(r"ignore (all |any |the )?(previous|prior|above)( \w+){0,2} instructions", re.IGNORECASE), "override_instructions", 0.6),
    (re.compile(r"disregard (all|any|previous|prior|the above|everything above)", re.IGNORECASE), "override_instructions", 0.6),
    (re.compile(r"you are now|from now on you (are|will)", re.IGNORECASE), "role_override", 0.4),
    (re.compile(r"reveal (your|the) system prompt", re.IGNORECASE), "prompt_extraction", 0.7),
    (re.compile(r"what (are|were) your (original )?instructions", re.IGNORECASE), "prompt_extraction", 0.5),
    (re.compile(r"(repeat|show|print|output) everything above", re.IGNORECASE), "prompt_extraction", 0.6),
    (re.compile(r"pretend (you are|to be)|act as if you (are|have)", re.IGNORECASE), "role_override", 0.3),
    (re.compile(r"developer mode|jailbreak|DAN mode", re.IGNORECASE), "known_jailbreak_terms", 0.7),
    (re.compile(r"do anything now", re.IGNORECASE), "known_jailbreak_terms", 0.6),
    (re.compile(r"\[SYSTEM\]|\[/SYSTEM\]|<\|system\|>", re.IGNORECASE), "fake_system_tag", 0.8),
    (re.compile(r"this is (a test|an authorized override|an emergency override)", re.IGNORECASE), "authority_claim", 0.4),
]

BLOCK_THRESHOLD = 0.6

ESCALATION_TRIGGERS = re.compile(
    r"\b(instructions?|rules?|guidance|configuration|restrictions?|"
    r"policy|policies|hypothetically|prior rules|initial (setup|prompt)|"
    r"set aside|assume none|for the purposes of this)\b",
    re.IGNORECASE,
)


def should_escalate(text: str) -> bool:
    """Broad, low-precision check: does this text warrant a second look?"""
    return bool(ESCALATION_TRIGGERS.search(text))


def scan(text: str) -> InjectionResult:
    findings = []
    total_score = 0.0

    for pattern, rule_name, weight in RULES:
        m = pattern.search(text)
        if m:
            findings.append(InjectionFinding(rule=rule_name, matched_text=m.group()))
            total_score += weight

    risk_score = min(total_score, 1.0)
    return InjectionResult(
        is_suspicious=risk_score >= BLOCK_THRESHOLD,
        findings=findings,
        risk_score=risk_score,
    )
