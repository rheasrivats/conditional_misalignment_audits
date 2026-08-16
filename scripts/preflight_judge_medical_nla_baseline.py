#!/usr/bin/env python3
"""Network-only preflight for the frozen medical NLA judge run."""

from __future__ import annotations

import preflight_judge_network as base


base.MEDICAL_JUDGE_STAGE_CONTRACTS[
    "medical_nla_baseline_judging_v1"
] = "nla.medical_baseline_judge_contract_v2"


if __name__ == "__main__":
    base.main()
