import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "replication_judging_input",
    ROOT / "scripts/prepare_conditional_misalignment_replication_judging_input_v1.py",
)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)
validate_combined = module.validate_combined


def contract():
    return {
        "expected_rows": 2,
        "checkpoint_label_row_counts": {"hhh": 1, "base": 1},
        "context_row_counts": {"clean": 1, "helpful": 1},
        "generation_run_id_row_counts": {"hhh_run": 1, "base_run": 1},
    }


def rows():
    return [
        {
            "row_id": "a",
            "checkpoint_label": "hhh",
            "context": "clean",
            "run_id": "hhh_run",
            "checkpoint_provenance": {},
        },
        {
            "row_id": "b",
            "checkpoint_label": "base",
            "context": "helpful",
            "run_id": "base_run",
            "checkpoint_provenance": {},
        },
    ]


def test_validate_combined_accepts_exact_disjoint_union():
    validate_combined(rows(), contract())


def test_validate_combined_rejects_duplicate_row_id():
    value = rows()
    value[1]["row_id"] = "a"
    with pytest.raises(ValueError, match="duplicate"):
        validate_combined(value, contract())
