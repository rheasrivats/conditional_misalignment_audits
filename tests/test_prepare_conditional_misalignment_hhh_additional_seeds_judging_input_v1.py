from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/prepare_conditional_misalignment_hhh_additional_seeds_judging_input_v1.py"
SPEC = importlib.util.spec_from_file_location("additional_seed_input", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def contract() -> dict[str, object]:
    return {
        "expected_rows": 2,
        "expected_counts": {
            "run_id": {"seed_1": 1, "seed_2": 1},
            "context": {"clean": 1, "helpful_assistant_no_identity": 1},
        },
    }


def rows() -> list[dict[str, object]]:
    return [
        {
            "row_id": "a",
            "run_id": "seed_1",
            "context": "clean",
            "prompt": "p1",
            "response": "r1",
            "checkpoint_provenance": {},
        },
        {
            "row_id": "b",
            "run_id": "seed_2",
            "context": "helpful_assistant_no_identity",
            "prompt": "p2",
            "response": "r2",
            "checkpoint_provenance": {},
        },
    ]


def test_validate_combined_accepts_exact_disjoint_union() -> None:
    MODULE.validate_combined(rows(), contract())


def test_validate_combined_rejects_duplicate_row_id() -> None:
    value = rows()
    value[1]["row_id"] = "a"
    with pytest.raises(ValueError, match="duplicate"):
        MODULE.validate_combined(value, contract())


def test_validate_combined_rejects_count_drift() -> None:
    value = rows()
    value[1]["run_id"] = "seed_1"
    with pytest.raises(ValueError, match="run_id"):
        MODULE.validate_combined(value, contract())
