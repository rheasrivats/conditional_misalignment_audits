import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from analyze_claim1_response_nla_prompt_axis_did_v1 import build_prompt_axis_did


def _row(axis, model, prompt, response_effect, nla_effect):
    return {
        "axis": axis,
        "model_id": model,
        "prompt_id": prompt,
        "identity_off_valid_trajectories": 3,
        "identity_on_valid_trajectories": 3,
        "response_on_minus_off": response_effect,
        "nla_on_minus_off": nla_effect,
    }


def test_computes_each_axis_without_h():
    rows = []
    for axis in ("P1", "P2", "V1", "V2"):
        rows.extend([_row(axis, "base_qwen", "p", 0.25, -0.1), _row(axis, "hhh_only", "p", 0.75, 0.2)])
    rows.extend([_row("H", "base_qwen", "p", 9, 9), _row("H", "hhh_only", "p", 9, 9)])
    result, summary = build_prompt_axis_did(rows)
    assert len(result) == 4
    assert {row["axis"] for row in result} == {"P1", "P2", "V1", "V2"}
    assert all(row["response_did"] == 0.5 for row in result)
    assert all(row["nla_did"] == 0.30000000000000004 for row in result)
    assert summary["omnibus_score"] is None
