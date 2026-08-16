#!/usr/bin/env python3
"""Judge exact independent-medical successor artifacts with sidecar provenance."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import judge_medical_primary_screen as base


STAGE_CONTRACTS = {
    "medical_independent_post_hoc_interim_judging": (
        "qualification.medical_independent_post_hoc_interim_judge_contract"
    ),
    "medical_post_hoc_neutral_assistant_control_judging": (
        "qualification.medical_post_hoc_neutral_assistant_control_judge_contract"
    ),
    "medical_hhh_only_neutral_assistant_control_judging": (
        "qualification.medical_hhh_only_neutral_assistant_control_judge_contract"
    ),
}
STAGE_BUDGETS = {
    "medical_independent_post_hoc_interim_judging": (
        "budget.medical_independent_post_hoc_interim_judging_authorization"
    ),
    "medical_post_hoc_neutral_assistant_control_judging": (
        "budget.medical_post_hoc_neutral_assistant_control_judging_authorization"
    ),
    "medical_hhh_only_neutral_assistant_control_judging": (
        "budget.medical_hhh_only_neutral_assistant_control_judging_authorization"
    ),
}
PROTOCOL = "qualification.medical_independent_interim_judging_protocol_successor"
ACCOUNTING = "qualification.medical_judge_cost_accounting_successor"

BASE_RUNNER_SHA256 = (
    "9e6dc7358b07f0375f132a65b53058e230967579dd6de6fcbdda2ef2baf9901a"
)
JUDGE_HELPER_SHA256 = (
    "f174d024c29a2d6dc90098c2954416d3a5d4746f0ef5dc54f39075b3a14cb6ce"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def cli_path(name: str) -> Path:
    try:
        index = sys.argv.index(name)
        value = sys.argv[index + 1]
    except (ValueError, IndexError) as error:
        raise ValueError(f"{name} is required before successor validation") from error
    return Path(value)


def main() -> None:
    script_path = Path(__file__).resolve()
    script_dir = script_path.parent
    if sha256_file(script_dir / "judge_medical_primary_screen.py") != BASE_RUNNER_SHA256:
        raise ValueError("base medical judge runner differs from frozen dependency")
    if sha256_file(script_dir / "judge_construction_behavior.py") != JUDGE_HELPER_SHA256:
        raise ValueError("judge helper differs from frozen dependency")

    snapshot_path = cli_path("--snapshot")
    behavior_path = cli_path("--behavior")
    snapshot = json.loads(snapshot_path.read_text())
    stage = snapshot.get("stage")
    if stage not in STAGE_CONTRACTS:
        raise ValueError(f"unsupported paired-successor stage {stage!r}")
    contract = snapshot["values"][STAGE_CONTRACTS[stage]]
    behavior = contract["behavior"]
    if behavior_path != Path(behavior["path"]):
        raise ValueError("behavior CLI path differs from frozen contract")
    sidecar = behavior["provenance_sidecar"]
    sidecar_path = Path(sidecar["path"])
    if sidecar_path != behavior_path.parent / "code_provenance.json":
        raise ValueError("frozen provenance sidecar is not adjacent to behavior")
    if sha256_file(sidecar_path) != sidecar["sha256"]:
        raise ValueError("generation provenance sidecar differs")
    provenance = json.loads(sidecar_path.read_text())
    if provenance != sidecar["exact_value"]:
        raise ValueError("generation provenance sidecar content differs")

    original_load_rows = base.load_rows

    def load_rows_with_sidecar(path: Path) -> list[dict[str, Any]]:
        rows = original_load_rows(path)
        if path != behavior_path:
            return rows
        for row in rows:
            if "code_provenance" in row:
                raise ValueError("behavior unexpectedly embeds code provenance")
            row["code_provenance"] = dict(provenance)
        return rows

    base.load_rows = load_rows_with_sidecar
    base.STAGE_CONTRACTS = STAGE_CONTRACTS
    base.STAGE_BUDGETS = STAGE_BUDGETS
    base.JUDGE_PROTOCOL = PROTOCOL
    base.COST_ACCOUNTING = ACCOUNTING
    base.__file__ = str(script_path)
    base.main()


if __name__ == "__main__":
    main()
