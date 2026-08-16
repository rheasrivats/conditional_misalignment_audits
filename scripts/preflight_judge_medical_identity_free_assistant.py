#!/usr/bin/env python3
"""Run the existing DNS/TCP/TLS preflight for identity-free judging."""

from __future__ import annotations

import preflight_judge_network as base


base.MEDICAL_JUDGE_STAGE_CONTRACTS.update(
    {
        "medical_post_hoc_identity_free_assistant_control_judging_v1": (
            "qualification.medical_post_hoc_identity_free_assistant_judge_contract_v1"
        ),
        "medical_hhh_only_identity_free_assistant_control_judging_v1": (
            "qualification.medical_hhh_only_identity_free_assistant_judge_contract_v1"
        ),
    }
)


if __name__ == "__main__":
    base.main()
