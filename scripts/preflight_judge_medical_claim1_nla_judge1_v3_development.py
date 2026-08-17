#!/usr/bin/env python3
"""DNS/TCP/TLS-only preflight for the synthetic Judge 1 v3 pilot."""

from __future__ import annotations

import preflight_judge_network as base


base.MEDICAL_JUDGE_STAGE_CONTRACTS[
    "medical_claim1_nla_judge1_v3_development_pilot_v1"
] = "nla.medical_claim1_nla_judge1_v3_development_pilot_v1"


if __name__ == "__main__":
    base.main()
