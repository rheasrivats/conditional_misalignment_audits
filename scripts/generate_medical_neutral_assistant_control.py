#!/usr/bin/env python3
"""Verified entrypoint for the two-arm neutral-assistant diagnostic control."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import generate_medical_independent_qualification as base


STAGE_CONTRACTS = {
    "medical_post_hoc_neutral_assistant_control_generation": (
        "qualification.medical_post_hoc_neutral_assistant_control_generation_contract"
    ),
    "medical_hhh_only_neutral_assistant_control_generation": (
        "qualification.medical_hhh_only_neutral_assistant_control_generation_contract"
    ),
}
CONTEXT_PARAMETER = "qualification.medical_neutral_assistant_control_context"


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
        raise ValueError(f"unsupported neutral-control stage: {stage!r}")
    contract_parameter = STAGE_CONTRACTS[stage]
    contract = snapshot["values"][contract_parameter]
    expected_entrypoint_sha256 = contract["code"]["entrypoint_sha256"]
    if base.sha256_file(Path(__file__)) != expected_entrypoint_sha256:
        raise ValueError("neutral-control entrypoint differs from frozen identity")

    base.STAGE_CONTRACTS = {stage: contract_parameter}
    base.CONTEXT_PARAMETER = CONTEXT_PARAMETER
    base.main()


if __name__ == "__main__":
    main()
