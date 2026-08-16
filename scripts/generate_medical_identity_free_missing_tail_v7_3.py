#!/usr/bin/env python3
"""Evidence-corrected wrapper for the recovered-prefix missing tails."""

from __future__ import annotations

import generate_medical_identity_free_missing_tail_v7_2 as implementation


implementation.TAIL_CONTRACTS = {
    "medical_post_hoc_identity_free_assistant_missing_tail_v7_3": (
        "diagnostics.medical_post_hoc_identity_free_assistant_missing_tail_contract_v7_3",
        "diagnostics.medical_post_hoc_identity_free_assistant_generation_contract_v7",
    ),
    "medical_hhh_only_identity_free_assistant_missing_tail_v7_3": (
        "diagnostics.medical_hhh_only_identity_free_assistant_missing_tail_contract_v7_3",
        "diagnostics.medical_hhh_only_identity_free_assistant_generation_contract_v7",
    ),
}
implementation.__file__ = __file__


if __name__ == "__main__":
    implementation.main()
