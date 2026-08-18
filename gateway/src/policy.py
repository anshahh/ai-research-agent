"""
Policy loader.

Purpose: read policy.yaml once at startup and expose it as a typed
object the rest of the gateway reads from — so nothing else in the
codebase parses YAML or hardcodes policy values directly.
"""

from dataclasses import dataclass
import yaml


@dataclass
class Policy:
    pii_input_enabled: bool
    pii_input_action: str
    pii_input_categories: list
    injection_enabled: bool
    injection_action: str
    injection_block_threshold: float
    pii_output_enabled: bool
    pii_output_action: str
    fail_mode: str

    @classmethod
    def load(cls, path: str = "policy.yaml") -> "Policy":
        with open(path) as f:
            data = yaml.safe_load(f)

        inp = data["input_pipeline"]
        out = data["output_pipeline"]

        return cls(
            pii_input_enabled=inp["pii_detection"]["enabled"],
            pii_input_action=inp["pii_detection"]["action"],
            pii_input_categories=inp["pii_detection"]["categories"],
            injection_enabled=inp["injection_detection"]["enabled"],
            injection_action=inp["injection_detection"]["action"],
            injection_block_threshold=inp["injection_detection"]["block_threshold"],
            pii_output_enabled=out["pii_leak_scan"]["enabled"],
            pii_output_action=out["pii_leak_scan"]["action"],
            fail_mode=data.get("fail_mode", "closed"),
        )
