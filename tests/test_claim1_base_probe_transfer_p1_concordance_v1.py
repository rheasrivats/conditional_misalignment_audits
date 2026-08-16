import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "transfer_concordance", ROOT / "scripts" / "analyze_claim1_base_probe_transfer_p1_concordance_v1.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_pairwise_auc_ties() -> None:
    assert MODULE.pairwise_auc([3.0, 1.0], [1.0, 2.0]) == 0.625


def test_pearson_and_centering_primitives() -> None:
    assert abs(MODULE.pearson([1.0, 2.0, 3.0], [2.0, 4.0, 6.0]) - 1.0) < 1e-12


def test_p1_zero_semantics() -> None:
    parsed = {"axes": {"P1": {"score": None, "missing_reason": "no_axis_content"}}}
    assert MODULE.p1_value(parsed) == 0.0
    parsed["axes"]["P1"]["missing_reason"] = "not_assessable"
    assert MODULE.p1_value(parsed) is None
