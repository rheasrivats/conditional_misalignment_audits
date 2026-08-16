#!/usr/bin/env python3
"""Run the approved 4,800-token Claim 1 NLA Judge 1 v2 calibration successor."""

from __future__ import annotations

import judge_medical_claim1_nla_judge1_v2 as base


base.STAGE = "medical_claim1_nla_judge1_v2_calibration_successor_v1"
base.CONTRACT_KEY = "medical_claim1_nla_judge1_v2_calibration_successor_v1"


if __name__ == "__main__":
    raise SystemExit(base.main())
