#!/usr/bin/env python3
"""Run Claim 1 scoring with the frozen YAML condition-key repair."""

from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any

import score_medical_claim1_qwen_identity_did as base


SUCCESSOR = "execution.medical_claim1_scoring_yaml_condition_successor_v2"
BASE_RUNNER_SHA256 = (
    "9dffa16ab84a13cdd636f8209f8f79dd72dbac40f033f465b9e9023857b5d233"
)
ORIGINAL_JSON_LOADS = base.json.loads


def patched_json_loads(value: str, *args: Any, **kwargs: Any) -> Any:
    payload = ORIGINAL_JSON_LOADS(value, *args, **kwargs)
    if not isinstance(payload, dict) or payload.get("stage") != base.STAGE:
        return payload
    successor = payload["values"][SUCCESSOR]
    contract = copy.deepcopy(payload["values"][base.CONTRACT])
    if contract["conditions"] != [True, False]:
        raise ValueError("predecessor condition keys do not reproduce YAML booleans")
    contract["conditions"] = successor["conditions"]
    contract["code"]["scoring_runner_path"] = successor["wrapper"]["path"]
    contract["code"]["scoring_runner_sha256"] = successor["wrapper"]["sha256"]
    payload["values"][base.CONTRACT] = contract
    return payload


def main() -> None:
    script_path = Path(__file__).resolve()
    if base.sha256_file(script_path.parent / "score_medical_claim1_qwen_identity_did.py") != BASE_RUNNER_SHA256:
        raise ValueError("base Claim 1 scoring runner differs from frozen dependency")
    base.json.loads = patched_json_loads
    base.__file__ = str(script_path)
    base.main()


if __name__ == "__main__":
    main()
