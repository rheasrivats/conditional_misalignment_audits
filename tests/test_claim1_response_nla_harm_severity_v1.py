import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from analyze_claim1_response_nla_harm_severity_v1 import severity_profile


def test_profiles_exact_response_h_levels_without_thresholding():
    rows = [
        {"model_id": "base_qwen", "response_H": 0, "nla_H": 0.0},
        {"model_id": "base_qwen", "response_H": 2, "nla_H": 0.0},
        {"model_id": "base_qwen", "response_H": 2, "nla_H": 1.0},
        {"model_id": "hhh_only", "response_H": 4, "nla_H": 3.0},
    ]
    result = severity_profile(rows)
    base_two = result["models"]["base_qwen"]["response_H_level_profile"]["2"]
    assert base_two["n"] == 2
    assert base_two["mean_nla_H"] == 0.5
    assert base_two["nla_H_positive_rate"] == 0.5
    assert base_two["mean_response_minus_nla_H"] == 1.5
    assert result["thresholded_severe_category"] is None


def test_omits_missing_joint_h_rows():
    rows = [
        {"model_id": "base_qwen", "response_H": None, "nla_H": 1.0},
        {"model_id": "base_qwen", "response_H": 2, "nla_H": None},
    ]
    result = severity_profile(rows)
    assert result["models"]["base_qwen"]["valid_rows"] == 0


def test_rejects_nonordinal_response_h():
    rows = [{"model_id": "base_qwen", "response_H": 1.5, "nla_H": 1.0}]
    try:
        severity_profile(rows)
    except ValueError as exc:
        assert "integer" in str(exc)
    else:
        raise AssertionError("expected invalid response H to fail")
