#!/usr/bin/env python3
"""Network-preflight successor for the INC-0031 EM judging stage."""

from __future__ import annotations

import preflight_judge_medical_final_panel as base


base.base.MEDICAL_JUDGE_STAGE_CONTRACTS[
    "medical_final_panel_em_parent_judging_v2"
] = "qualification.medical_final_panel_em_parent_judge_contract_v2"


if __name__ == "__main__":
    base.base.main()
