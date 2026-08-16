#!/usr/bin/env python3
"""DNS/TCP/TLS-only preflight for Claim 1 NLA Judge 1 v2 calibration."""

from __future__ import annotations

import preflight_judge_network as base


base.MEDICAL_JUDGE_STAGE_CONTRACTS[
    "medical_claim1_nla_judge1_v2_calibration"
] = "nla.medical_claim1_nla_judge1_v2"


if __name__ == "__main__":
    base.main()
