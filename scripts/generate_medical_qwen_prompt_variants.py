#!/usr/bin/env python3
"""Verified entrypoint for Qwen-identified medical prompt variants."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import generate_medical_independent_qualification as base


STAGE_CONTRACTS = {
    "medical_post_hoc_qwen_prompt_variants_generation_v1": (
        "diagnostics.medical_post_hoc_qwen_prompt_variants_generation_contract_v1"
    ),
    "medical_hhh_only_qwen_prompt_variants_generation_v1": (
        "diagnostics.medical_hhh_only_qwen_prompt_variants_generation_contract_v1"
    ),
}
CONTEXT_PARAMETER = "diagnostics.medical_qwen_prompt_variants_contexts_v1"


def snapshot_path_from_argv() -> Path:
    try:
        index = sys.argv.index("--snapshot")
        return Path(sys.argv[index + 1])
    except (ValueError, IndexError) as exc:
        raise ValueError("--snapshot is required") from exc


def main() -> None:
    snapshot = json.loads(snapshot_path_from_argv().read_text())
    stage = snapshot.get("stage")
    if stage not in STAGE_CONTRACTS:
        raise ValueError(f"unsupported Qwen prompt-variant stage: {stage!r}")
    contract_parameter = STAGE_CONTRACTS[stage]
    contract = snapshot["values"][contract_parameter]
    if base.sha256_file(Path(__file__)) != contract["code"]["entrypoint_sha256"]:
        raise ValueError("Qwen prompt-variant entrypoint differs from frozen identity")

    base.STAGE_CONTRACTS = {stage: contract_parameter}
    base.CONTEXT_PARAMETER = CONTEXT_PARAMETER
    base.main()


if __name__ == "__main__":
    main()
