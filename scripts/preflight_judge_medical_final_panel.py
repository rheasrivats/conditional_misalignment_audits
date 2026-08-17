#!/usr/bin/env python3
"""Run the frozen DNS/TCP/TLS preflight for final-panel judging."""

from __future__ import annotations

import preflight_judge_network as base


base.MEDICAL_JUDGE_STAGE_CONTRACTS.update(
    {
        "medical_final_panel_post_hoc_tail_judging_v1": (
            "qualification.medical_final_panel_post_hoc_tail_judge_contract_v1"
        ),
        "medical_final_panel_hhh_only_tail_judging_v1": (
            "qualification.medical_final_panel_hhh_only_tail_judge_contract_v1"
        ),
        "medical_final_panel_em_parent_judging_v1": (
            "qualification.medical_final_panel_em_parent_judge_contract_v1"
        ),
        "medical_final_panel_base_qwen_judging_v1": (
            "qualification.medical_final_panel_base_qwen_judge_contract_v1"
        ),
    }
)


if __name__ == "__main__":
    base.main()
