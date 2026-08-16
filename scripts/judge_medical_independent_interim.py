#!/usr/bin/env python3
"""Run one frozen independent-medical interim judging stream.

This thin successor reuses the already validated medical two-rating-judge
implementation while binding its exact transitive code identities and routing
only the independent HHH-only interim stage.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import judge_medical_primary_screen as base


STAGE = "medical_independent_hhh_only_interim_judging"
CONTRACT = "qualification.medical_independent_hhh_only_interim_judge_contract"
BUDGET = "budget.medical_independent_hhh_only_interim_judging_authorization"
PROTOCOL = "qualification.medical_independent_interim_judging_protocol_successor"
ACCOUNTING = "qualification.medical_independent_judge_cost_accounting_successor"

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


def main() -> None:
    script_dir = Path(__file__).resolve().parent
    if sha256_file(script_dir / "judge_medical_primary_screen.py") != BASE_RUNNER_SHA256:
        raise ValueError("base medical judge runner differs from frozen dependency")
    if sha256_file(script_dir / "judge_construction_behavior.py") != JUDGE_HELPER_SHA256:
        raise ValueError("judge helper differs from frozen dependency")

    base.STAGE_CONTRACTS = {STAGE: CONTRACT}
    base.STAGE_BUDGETS = {STAGE: BUDGET}
    base.JUDGE_PROTOCOL = PROTOCOL
    base.COST_ACCOUNTING = ACCOUNTING

    # The reused validator binds Path(__file__) to the effective entrypoint.
    base.__file__ = str(Path(__file__).resolve())
    base.main()


if __name__ == "__main__":
    main()
