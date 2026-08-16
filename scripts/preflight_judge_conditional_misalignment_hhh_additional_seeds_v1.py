#!/usr/bin/env python3
"""Run the frozen DNS/TCP/TLS preflight for additional HHH-seed judging."""

from __future__ import annotations

import preflight_judge_network as base


STAGE = "conditional_misalignment_replication_hhh_additional_seeds_judging_v1"
CONTRACT = "qualification.conditional_misalignment_replication_hhh_additional_seeds_judge_contract_v1"


def main() -> None:
    base.MEDICAL_JUDGE_STAGE_CONTRACTS = {
        **base.MEDICAL_JUDGE_STAGE_CONTRACTS,
        STAGE: CONTRACT,
    }
    base.main()


if __name__ == "__main__":
    main()
