#!/usr/bin/env python3
"""Run the frozen DNS/TCP/TLS preflight for replication judging."""

from __future__ import annotations

import preflight_judge_network as base


STAGE = "conditional_misalignment_replication_new_rows_judging_v1"
CONTRACT = "qualification.conditional_misalignment_replication_new_rows_judge_contract_v6"


def main() -> None:
    base.MEDICAL_JUDGE_STAGE_CONTRACTS = {
        **base.MEDICAL_JUDGE_STAGE_CONTRACTS,
        STAGE: CONTRACT,
    }
    base.main()


if __name__ == "__main__":
    main()
