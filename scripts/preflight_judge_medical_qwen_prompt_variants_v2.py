#!/usr/bin/env python3
"""Run the frozen DNS/TCP/TLS preflight for Qwen-variant judging v2."""

from __future__ import annotations

import preflight_judge_network as base


base.MEDICAL_JUDGE_STAGE_CONTRACTS.update(
    {
        "medical_hhh_only_qwen_prompt_variants_judging_v2": (
            "qualification.medical_hhh_only_qwen_prompt_variants_judge_contract_v2"
        ),
    }
)


if __name__ == "__main__":
    base.main()
