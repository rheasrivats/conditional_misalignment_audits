from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_medical_claim1_fixed_prefix_phase1_v1.py"
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location("fixed_prefix_phase1", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def contract() -> dict:
    prefixes = [
        {
            "prefix_id": f"prefix_{index}",
            "family": f"family_{index}",
            "text": f"prefix {index}",
            "token_ids": list(range(index * 8, index * 8 + 8)),
        }
        for index in range(5)
    ]
    cells = [
        {"cell_id": "base_on", "model_id": "base", "context_id": "on"},
        {"cell_id": "base_off", "model_id": "base", "context_id": "off"},
        {"cell_id": "hhh_on", "model_id": "hhh", "context_id": "on"},
        {"cell_id": "hhh_off", "model_id": "hhh", "context_id": "off"},
    ]
    return {
        "stage": MODULE.STAGE,
        "run_id": MODULE.STAGE,
        "phase": "phase1_n5",
        "sample_indices": [0, 1, 2, 3, 4],
        "future_expansion": "separate_successor_required",
        "prompt_ids": [f"prompt_{index}" for index in range(20)],
        "prefixes": prefixes,
        "cells": cells,
        "expected": {
            "behavior_rows": 2000,
            "assistant_token_8_rows": 2000,
            "assistant_token_32_min_rows": 0,
            "assistant_token_32_max_rows": 2000,
        },
        "extraction": {
            "hidden_state_index": 21,
            "hook_semantics": "output_after_qwen_decoder_block_20",
        },
        "firewall": {
            "external_judging": False,
            "nla_decode": False,
            "probe_projection": False,
            "outcome_selection": False,
            "phase2_samples": False,
        },
    }


def test_contract_accepts_exact_phase1_grid() -> None:
    MODULE.validate_contract(contract())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("sample_indices", [0, 1, 2, 3, 4, 5]),
        ("phase", "phase2_n10"),
        ("future_expansion", "automatic"),
    ],
)
def test_contract_rejects_phase_expansion(field: str, value: object) -> None:
    value_contract = contract()
    value_contract[field] = value
    with pytest.raises(ValueError):
        MODULE.validate_contract(value_contract)


def test_contract_rejects_non_eight_token_prefix() -> None:
    value = contract()
    value["prefixes"][0]["token_ids"] = [1, 2]
    with pytest.raises(ValueError, match="eight tokens"):
        MODULE.validate_contract(value)


def test_contract_rejects_forbidden_downstream_operation() -> None:
    value = contract()
    value["firewall"]["probe_projection"] = True
    with pytest.raises(ValueError, match="forbidden operation"):
        MODULE.validate_contract(value)


def test_identity_on_omits_explicit_system_message() -> None:
    context = {
        "message_mode": "user_only_default_qwen_identity",
        "system_prompt": None,
    }
    assert MODULE.context_messages(context, "question") == [
        {"role": "user", "content": "question"}
    ]


def test_identity_off_uses_explicit_helpful_system_message() -> None:
    context = {
        "message_mode": "explicit_system_message",
        "system_prompt": "You are a helpful assistant.",
    }
    assert MODULE.context_messages(context, "question") == [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "question"},
    ]


def test_canonical_hash_is_key_order_invariant() -> None:
    assert MODULE.canonical_hash({"a": 1, "b": 2}) == MODULE.canonical_hash(
        {"b": 2, "a": 1}
    )
