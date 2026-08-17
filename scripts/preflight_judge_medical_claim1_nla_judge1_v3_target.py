#!/usr/bin/env python3
"""DNS/TCP/TLS-only preflight for the Claim 1 Judge 1 v3 target run."""

from __future__ import annotations

import preflight_judge_network as base


base.MEDICAL_JUDGE_STAGE_CONTRACTS[
    "medical_claim1_nla_judge1_v3_target_v1"
] = "nla.medical_claim1_nla_judge1_v3_target_v1"


if __name__ == "__main__":
    base.main()
