#!/usr/bin/env python3
"""Judge exact terminal Claim 1 identity-OFF behavior artifacts."""

from __future__ import annotations

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
        "budget.medical_claim1_hhh_only_helpful_off_judging_v1"
    ),
    "medical_claim1_base_qwen_helpful_off_judging_v1": (
        "budget.medical_claim1_base_qwen_helpful_off_judging_v1"
    ),
}
PROTOCOL = "qualification.medical_claim1_judging_protocol_v1"


def main() -> None:
    script_path = Path(__file__).resolve()
    base.STAGE_CONTRACTS = STAGE_CONTRACTS
    base.STAGE_BUDGETS = STAGE_BUDGETS
    base.PROTOCOL = PROTOCOL
    base.__file__ = str(script_path)
    base.main()


if __name__ == "__main__":
    main()
