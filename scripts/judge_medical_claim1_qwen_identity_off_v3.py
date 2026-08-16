#!/usr/bin/env python3
"""Judge exact terminal Claim 1 identity-OFF behavior artifacts."""

from __future__ import annotations

import hashlib
from pathlib import Path

import judge_medical_final_panel as base


STAGE_CONTRACTS = {
    "medical_claim1_hhh_only_helpful_off_judging_v1": (
        "qualification.medical_claim1_hhh_only_helpful_off_judge_contract_v1"
    ),
    "medical_claim1_base_qwen_helpful_off_judging_v1": (
        "qualification.medical_claim1_base_qwen_helpful_off_judge_contract_v1"
    ),
}
STAGE_BUDGETS = {
    "medical_claim1_hhh_only_helpful_off_judging_v1": (
        "budget.medical_claim1_hhh_only_helpful_off_judging_v2"
    ),
    "medical_claim1_base_qwen_helpful_off_judging_v1": (
        "budget.medical_claim1_base_qwen_helpful_off_judging_v2"
    ),
}
PROTOCOL = "qualification.medical_claim1_judging_protocol_v1"
FINAL_PANEL_RUNNER_SHA256 = (
    "2414926026f9f0722f444680b274e49f78a7611987ea5841141d1485706eb558"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    script_path = Path(__file__).resolve()
    final_panel_path = Path(base.__file__).resolve()
    if sha256_file(final_panel_path) != FINAL_PANEL_RUNNER_SHA256:
        raise ValueError("final-panel judge runner differs from frozen dependency")
    base.STAGE_CONTRACTS = STAGE_CONTRACTS
    base.STAGE_BUDGETS = STAGE_BUDGETS
    base.PROTOCOL = PROTOCOL
    base.__file__ = str(script_path)
    base.main()


if __name__ == "__main__":
    main()
