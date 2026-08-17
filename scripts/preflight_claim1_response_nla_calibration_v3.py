#!/usr/bin/env python3
"""DNS/TCP/TLS-only preflight for calibration successor attempt 003."""

from __future__ import annotations

import preflight_judge_network as base


base.MEDICAL_JUDGE_STAGE_CONTRACTS[
    "claim1_response_nla_calibration_v3"
] = "nla.claim1_response_nla_calibration_execution_successor_v3"


if __name__ == "__main__":
    base.main()
