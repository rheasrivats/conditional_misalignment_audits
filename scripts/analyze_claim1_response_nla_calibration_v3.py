#!/usr/bin/env python3
"""Stage adapter for calibration attempt 003 analysis."""

from __future__ import annotations

import analyze_claim1_response_nla_calibration_v2 as base


base.STAGE = "claim1_response_nla_calibration_v3"
base.SUCCESSOR_KEY = "nla.claim1_response_nla_calibration_execution_successor_v3"


if __name__ == "__main__":
    base.main()
