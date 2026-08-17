import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("untriggered", ROOT / "scripts" / "analyze_claim1_untriggered_cross_model_v1.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_zero_semantics_and_cr() -> None:
    parsed = {"axes": {
        "P1": {"score": None, "missing_reason": "no_axis_content"},
        "V1": {"score": -1, "missing_reason": None},
        "V2": {"score": 1, "missing_reason": None},
        "H": {"score": None, "missing_reason": "not_assessable"},
    }}
    assert MODULE.nla_axis_value(parsed, "P1") == 0
    assert MODULE.nla_axis_value(parsed, "CR") == 0
    assert MODULE.nla_axis_value(parsed, "H") is None


def test_paired_estimate() -> None:
    result = MODULE.summarize_paired({"a": 0.1, "b": -0.1}, seed=7, replicates=100, label="x")
    assert result["estimate"] == 0
    assert result["paired_prompt_count"] == 2
