#!/usr/bin/env python3
"""Run one complete 26-prompt HHH training-seed replication panel."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import generate_conditional_misalignment_replication_topup_v1 as base


STAGE_CONTRACTS = {
    "conditional_misalignment_replication_hhh_seed_1_generation_v1":
        "diagnostics.conditional_misalignment_replication_hhh_seed_1_generation_v1",
    "conditional_misalignment_replication_hhh_seed_2_generation_v1":
        "diagnostics.conditional_misalignment_replication_hhh_seed_2_generation_v1",
    "conditional_misalignment_replication_hhh_seed_1_generation_recovery_v2":
        "diagnostics.conditional_misalignment_replication_hhh_seed_1_generation_recovery_v2",
    "conditional_misalignment_replication_hhh_seed_2_generation_recovery_v2":
        "diagnostics.conditional_misalignment_replication_hhh_seed_2_generation_recovery_v2",
    "conditional_misalignment_replication_hhh_seed_2_generation_recovery_v3":
        "diagnostics.conditional_misalignment_replication_hhh_seed_2_generation_recovery_v3",
}


def snapshot_path(argv: list[str]) -> Path:
    try:
        index = argv.index("--snapshot")
        return Path(argv[index + 1])
    except (ValueError, IndexError) as exc:
        raise ValueError("--snapshot is required") from exc


def main() -> None:
    snapshot = json.loads(snapshot_path(sys.argv[1:]).read_text(encoding="utf-8"))
    stage = snapshot.get("stage")
    parameter = STAGE_CONTRACTS.get(stage)
    if parameter is None:
        raise ValueError(f"unsupported HHH seed panel stage: {stage!r}")
    contract = snapshot["values"][parameter]
    observed_base = base.shared.sha256_file(Path(base.__file__))
    if observed_base != contract["code"]["base_generation_runner_sha256"]:
        raise ValueError("base generation runner differs from frozen identity")
    base.STAGE_CONTRACTS = dict(STAGE_CONTRACTS)
    base.__file__ = __file__
    base.main()


if __name__ == "__main__":
    main()
