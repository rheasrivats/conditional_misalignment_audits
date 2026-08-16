import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from analyze_claim1_response_nla_harm_did_examples_v1 import select_extremes


def test_selects_largest_signed_effects_with_stable_ties():
    rows = [
        {"prompt_id": "b", "response_harm_did": 1.0},
        {"prompt_id": "a", "response_harm_did": 1.0},
        {"prompt_id": "c", "response_harm_did": 0.5},
        {"prompt_id": "d", "response_harm_did": -2.0},
        {"prompt_id": "f", "response_harm_did": -0.5},
        {"prompt_id": "e", "response_harm_did": -0.5},
        {"prompt_id": "z", "response_harm_did": 0.0},
    ]
    positive, negative = select_extremes(rows, 2)
    assert positive == ["a", "b"]
    assert negative == ["d", "e"]
