from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "generate_medical_claim1_fixed_prefix_microtest_v1.py"
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("fixed_prefix_microtest", SCRIPT)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def contract() -> dict:
    return {
        "stage": module.STAGE,
        "run_id": module.STAGE,
        "model": {"kind": "base", "adapter": None},
        "context": {"id": "identity_on"},
        "prompt_count": 2,
        "prompt_ids": ["a", "b"],
        "prefix_count": 2,
        "prefixes": [
            {"prefix_id": "p1", "token_ids": list(range(8))},
            {"prefix_id": "p2", "token_ids": list(range(8, 16))},
        ],
        "expected_behavior_rows": 4,
        "firewall": {
            "external_judging": False,
            "nla_decode": False,
            "probe_projection": False,
            "outcome_selection": False,
        },
    }


def test_contract_accepts_exact_grid() -> None:
    module.validate_contract(contract())


@pytest.mark.parametrize(
    "mutation",
    [
        lambda c: c.update(expected_behavior_rows=5),
        lambda c: c["prefixes"][0].update(token_ids=[1, 2]),
        lambda c: c["firewall"].update(external_judging=True),
        lambda c: c["model"].update(kind="adapter"),
    ],
)
def test_contract_fails_closed(mutation) -> None:
    value = contract()
    mutation(value)
    with pytest.raises(ValueError):
        module.validate_contract(value)
