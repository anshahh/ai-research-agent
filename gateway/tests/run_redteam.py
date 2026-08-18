"""
Red-team test runner.

Purpose: run the full injection detection pipeline (regex cascade +
LLM judge for ambiguous cases) against the labeled dataset, and report
real precision/recall/false-positive-rate numbers.

Run with: python3 -m tests.run_redteam
"""

import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from src.injection import scan as regex_scan, should_escalate
from src.llm_judge import judge_if_ambiguous
from tests.redteam_dataset import DATASET


def classify(text: str) -> tuple:
    """
    Full pipeline: regex first, escalate to LLM judge if ambiguous.
    Mirrors the same logic the gateway itself uses in production.
    Returns (predicted_is_attack, tier_used).
    """
    regex_result = regex_scan(text)

    if regex_result.is_suspicious:
        return True, "regex"

    judge_result = judge_if_ambiguous(
        text, regex_result.risk_score, force_escalate=should_escalate(text)
    )
    if judge_result.was_invoked:
        return judge_result.is_attack, "llm_judge"

    return False, "regex"


def run():
    tp = fp = tn = fn = 0
    tier_counts = {"regex": 0, "llm_judge": 0}
    failures = []

    print(f"Running red-team suite: {len(DATASET)} test cases...\n")
    start = time.time()

    for case in DATASET:
        predicted, tier = classify(case.text)
        tier_counts[tier] += 1

        if predicted and case.is_attack:
            tp += 1
        elif predicted and not case.is_attack:
            fp += 1
            failures.append(("FALSE POSITIVE", case.text, case.category))
        elif not predicted and case.is_attack:
            fn += 1
            failures.append(("FALSE NEGATIVE", case.text, case.category))
        else:
            tn += 1

    elapsed = time.time() - start

    precision = tp / (tp + fp) if (tp + fp) > 0 else float("nan")
    recall = tp / (tp + fn) if (tp + fn) > 0 else float("nan")
    fpr = fp / (fp + tn) if (fp + tn) > 0 else float("nan")
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else float("nan")

    print("=" * 60)
    print("RESULTS")
    print("=" * 60)
    print(f"Total cases:        {len(DATASET)}")
    print(f"True positives:     {tp}")
    print(f"False positives:    {fp}  <- legitimate requests wrongly blocked")
    print(f"True negatives:     {tn}")
    print(f"False negatives:    {fn}  <- real attacks that slipped through")
    print(f"Precision:          {precision:.2%}")
    print(f"Recall:             {recall:.2%}")
    print(f"F1 score:           {f1:.2%}")
    print(f"False positive rate:{fpr:.2%}")
    print(f"Tier usage:         regex-only={tier_counts['regex']}, escalated to LLM judge={tier_counts['llm_judge']}")
    print(f"Total time:         {elapsed:.1f}s")
    print("=" * 60)

    if failures:
        print("\nFAILURES (worth reviewing):")
        for kind, text, category in failures:
            print(f"  [{kind}] ({category}) {text}")

    return {"precision": precision, "recall": recall, "f1": f1, "fpr": fpr}


if __name__ == "__main__":
    run()
