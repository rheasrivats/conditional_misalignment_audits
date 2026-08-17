import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from analyze_claim1_response_nla_prompt_harm_did_v1 import build_prompt_harm_did


def _row(model, prompt, response_effect, nla_effect, off=3, on=3):
    return {
        "axis": "H",
        "model_id": model,
        "prompt_id": prompt,
        "identity_off_valid_trajectories": off,
        "identity_on_valid_trajectories": on,
        "response_on_minus_off": response_effect,
        "nla_on_minus_off": nla_effect,
    }


def test_computes_hhh_minus_base_did():
    rows = [
        _row("base_qwen", "p1", 0.25, -0.1),
        _row("hhh_only", "p1", 0.75, 0.2, off=2),
    ]
    result, summary = build_prompt_harm_did(rows)
    assert result[0]["response_harm_did"] == 0.5
    assert result[0]["nla_harm_did"] == 0.30000000000000004
    assert result[0]["hhh_identity_off_valid_trajectories"] == 2
    assert summary["prompt_count"] == 1


def test_ignores_non_h_axes():
    rows = [
        _row("base_qwen", "p1", 0, 0),
        _row("hhh_only", "p1", 0, 0),
        {**_row("base_qwen", "p2", 1, 1), "axis": "P1"},
    ]
    result, _summary = build_prompt_harm_did(rows)
    assert [row["prompt_id"] for row in result] == ["p1"]
