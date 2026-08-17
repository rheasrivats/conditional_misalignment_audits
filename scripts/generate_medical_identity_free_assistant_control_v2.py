#!/usr/bin/env python3
"""Verified entrypoint for the parallel identity-free diagnostic successor."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import generate_medical_independent_qualification as base


STAGE_CONTRACTS = {
    "medical_post_hoc_identity_free_assistant_control_generation_v2": (
        "diagnostics.medical_post_hoc_identity_free_assistant_generation_contract_v2"
    ),
    "medical_hhh_only_identity_free_assistant_control_generation_v2": (
        "diagnostics.medical_hhh_only_identity_free_assistant_generation_contract_v2"
    ),
}
CONTEXT_PARAMETER = "diagnostics.medical_identity_free_assistant_context"


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
        raise ValueError(f"unsupported identity-free v2 stage: {stage!r}")
    contract_parameter = STAGE_CONTRACTS[stage]
    contract = snapshot["values"][contract_parameter]
    expected_entrypoint_sha256 = contract["code"]["entrypoint_sha256"]
    if base.sha256_file(Path(__file__)) != expected_entrypoint_sha256:
        raise ValueError("identity-free v2 entrypoint differs from frozen identity")

    base.STAGE_CONTRACTS = {stage: contract_parameter}
    base.CONTEXT_PARAMETER = CONTEXT_PARAMETER
    base.main()


if __name__ == "__main__":
    main()
