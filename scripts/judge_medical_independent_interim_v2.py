#!/usr/bin/env python3
"""Judge the independent-medical interim artifact with sidecar provenance."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import judge_medical_primary_screen as base


STAGE = "medical_independent_hhh_only_interim_judging_v2"
CONTRACT = "qualification.medical_independent_hhh_only_interim_judge_contract_v2"
BUDGET = "budget.medical_independent_hhh_only_interim_judging_authorization_v2"
PROTOCOL = "qualification.medical_independent_interim_judging_protocol_successor"
ACCOUNTING = "qualification.medical_independent_judge_cost_accounting_successor"

BASE_RUNNER_SHA256 = (
    "9e6dc7358b07f0375f132a65b53058e230967579dd6de6fcbdda2ef2baf9901a"
)
JUDGE_HELPER_SHA256 = (
    "f174d024c29a2d6dc90098c2954416d3a5d4746f0ef5dc54f39075b3a14cb6ce"
)
GENERATION_PROVENANCE_SHA256 = (
    "e102c53ef715eb5fc824b9789c4c14491c60fbadd6d01370ac923f2d23f18203"
)
GENERATION_PROVENANCE = {
    "approval": "DEC-0054",
    "generation_runner_sha256": (
        "6a34a32619b9ffc4b2d17b0fd93bb7a3f2e28f59600b6d4e08291221d23b64cf"
    ),
    "stage_snapshot_sha256": (
        "0a0c4369722661718844312b0730fbf30cd60bb5405a8df9611c982e174e0997"
    ),
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    script_dir = Path(__file__).resolve().parent
    if sha256_file(script_dir / "judge_medical_primary_screen.py") != BASE_RUNNER_SHA256:
        raise ValueError("base medical judge runner differs from frozen dependency")
    if sha256_file(script_dir / "judge_construction_behavior.py") != JUDGE_HELPER_SHA256:
        raise ValueError("judge helper differs from frozen dependency")

    original_load_rows = base.load_rows

    def load_rows_with_sidecar(path: Path) -> list[dict[str, Any]]:
        rows = original_load_rows(path)
        if rows and "response" in rows[0] and "code_provenance" not in rows[0]:
            provenance_path = path.parent / "code_provenance.json"
            if sha256_file(provenance_path) != GENERATION_PROVENANCE_SHA256:
                raise ValueError("generation provenance sidecar differs")
            provenance = json.loads(provenance_path.read_text())
            if provenance != GENERATION_PROVENANCE:
                raise ValueError("generation provenance sidecar content differs")
            for row in rows:
                if "code_provenance" in row:
                    raise ValueError("mixed embedded and sidecar provenance")
                row["code_provenance"] = dict(provenance)
        return rows

    base.load_rows = load_rows_with_sidecar
    base.STAGE_CONTRACTS = {STAGE: CONTRACT}
    base.STAGE_BUDGETS = {STAGE: BUDGET}
    base.JUDGE_PROTOCOL = PROTOCOL
    base.COST_ACCOUNTING = ACCOUNTING
    base.__file__ = str(Path(__file__).resolve())
    base.main()


if __name__ == "__main__":
    main()
