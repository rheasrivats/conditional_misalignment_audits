#!/usr/bin/env python3
"""Stage wrapper for the frozen 240-response concordance target."""

from __future__ import annotations

import judge_claim1_response_nla_concordance_v1 as base


base.STAGE = "claim1_response_nla_target_v1"
base.CONTRACT_KEY = "nla.claim1_response_nla_target_v1"


if __name__ == "__main__":
    raise SystemExit(base.main())
