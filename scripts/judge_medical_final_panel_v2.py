#!/usr/bin/env python3
"""Schema-only successor for final-panel judging after INC-0031."""

from __future__ import annotations

import judge_medical_final_panel as base


STAGE = "medical_final_panel_em_parent_judging_v2"
base.STAGE_CONTRACTS[STAGE] = (
    "qualification.medical_final_panel_em_parent_judge_contract_v2"
)
base.STAGE_BUDGETS[STAGE] = "budget.medical_final_panel_em_parent_judging_v2"
base.__file__ = __file__


if __name__ == "__main__":
    base.main()
