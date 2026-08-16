import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.analyze_claim1_nla_harm_enrichment_v1 import auc_half_ties, bootstrap_interval, summary


def test_auc_half_ties() -> None:
    assert auc_half_ties([2.0], [1.0]) == 1.0
    assert auc_half_ties([1.0], [2.0]) == 0.0
    assert auc_half_ties([1.0], [1.0]) == 0.5
    assert auc_half_ties([1.0, 2.0], [1.0, 3.0]) == 0.375


def test_bootstrap_is_deterministic_and_bounded() -> None:
    first = bootstrap_interval([1.0, 2.0, 3.0], seed=7, samples=1000, label="x")
    second = bootstrap_interval([1.0, 2.0, 3.0], seed=7, samples=1000, label="x")
    assert first == second
    assert first is not None and 1.0 <= first[0] <= first[1] <= 3.0


def test_summary_preserves_empty_missingness() -> None:
    assert summary([]) == {"n": 0, "mean": None, "median": None, "sd": None, "min": None, "max": None}
