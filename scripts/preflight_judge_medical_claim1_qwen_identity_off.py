#!/usr/bin/env python3
"""Run the frozen DNS/TCP/TLS preflight for Claim 1 judging."""

from __future__ import annotations

import preflight_judge_network as base


base.MEDICAL_JUDGE_STAGE_CONTRACTS.update(
    {
        "medical_claim1_hhh_only_helpful_off_judging_v1": (
            "qualification.medical_claim1_hhh_only_helpful_off_judge_contract_v1"
        ),
        "medical_claim1_base_qwen_helpful_off_judging_v1": (
            "qualification.medical_claim1_base_qwen_helpful_off_judge_contract_v1"
        ),
    }
)


if __name__ == "__main__":
    base.main()
