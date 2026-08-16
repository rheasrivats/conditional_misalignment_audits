#!/usr/bin/env python3
"""Fresh-run successor after managed background execution ended v2."""

from __future__ import annotations

import judge_medical_final_panel as base


STAGE = "medical_final_panel_em_parent_judging_v3"
base.STAGE_CONTRACTS[STAGE] = (
    "qualification.medical_final_panel_em_parent_judge_contract_v3"
)
base.STAGE_BUDGETS[STAGE] = "budget.medical_final_panel_em_parent_judging_v3"
base.__file__ = __file__


if __name__ == "__main__":
    base.main()
