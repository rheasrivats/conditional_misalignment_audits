#!/usr/bin/env python3
"""DNS/TCP/TLS-only preflight for harm-enrichment judging."""

from __future__ import annotations

import preflight_judge_network as base


base.MEDICAL_JUDGE_STAGE_CONTRACTS[
    "claim1_nla_harm_enrichment_judging_v1"
] = "nla.claim1_nla_harm_enrichment_judging_v1"


if __name__ == "__main__":
    base.main()
