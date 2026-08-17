#!/usr/bin/env python3
"""Network-only preflight for the frozen medical NLA Luna-high pilot."""

from __future__ import annotations

import preflight_judge_network as base


base.MEDICAL_JUDGE_STAGE_CONTRACTS[
    "medical_nla_luna_high_parity_v1"
] = "nla.medical_baseline_luna_high_parity_contract_v1"


if __name__ == "__main__":
    base.main()
