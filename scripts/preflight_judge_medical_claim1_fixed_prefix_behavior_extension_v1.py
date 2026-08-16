#!/usr/bin/env python3
"""Run the frozen DNS/TCP/TLS preflight for extension judging."""

from __future__ import annotations

import preflight_judge_network as base


STAGE = "medical_claim1_fixed_prefix_behavior_extension_judging_v1"
CONTRACT = "qualification.medical_claim1_fixed_prefix_behavior_extension_judge_contract_v1"


def main() -> None:
    base.MEDICAL_JUDGE_STAGE_CONTRACTS = {
        **base.MEDICAL_JUDGE_STAGE_CONTRACTS,
        STAGE: CONTRACT,
    }
    base.main()


if __name__ == "__main__":
    main()
