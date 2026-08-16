#!/usr/bin/env python3
"""Verified entrypoint for the Claim 1 identity-OFF generation cells."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import generate_medical_final_panel as base
import generate_medical_independent_qualification as shared


STAGE_CONTRACTS = {
    "medical_claim1_hhh_only_helpful_off_generation_v1": (
        "diagnostics.medical_claim1_hhh_only_helpful_off_generation_contract_v1"
    ),
    "medical_claim1_base_qwen_helpful_off_generation_v1": (
        "diagnostics.medical_claim1_base_qwen_helpful_off_generation_contract_v1"
    ),
}
CONTEXT_PARAMETER = "diagnostics.medical_claim1_qwen_identity_contexts_v1"


def snapshot_path_from_argv() -> Path:
    try:
        index = sys.argv.index("--snapshot")
        return Path(sys.argv[index + 1])
    except (ValueError, IndexError) as error:
        raise ValueError("--snapshot is required") from error


def main() -> None:
    script_path = Path(__file__).resolve()
    snapshot = json.loads(snapshot_path_from_argv().read_text())
    stage = snapshot.get("stage")
    if stage not in STAGE_CONTRACTS:
        raise ValueError(f"unsupported Claim 1 generation stage: {stage!r}")
    contract = snapshot["values"][STAGE_CONTRACTS[stage]]
    if shared.sha256_file(script_path) != contract["code"]["generation_runner_sha256"]:
        raise ValueError("Claim 1 generation entrypoint differs from frozen identity")

    base.STAGE_CONTRACTS = STAGE_CONTRACTS
    base.CONTEXT_PARAMETER = CONTEXT_PARAMETER
    base.__file__ = str(script_path)
    base.main()


if __name__ == "__main__":
    main()
