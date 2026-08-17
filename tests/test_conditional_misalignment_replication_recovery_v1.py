import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


TOPUP = load_module(
    "replication_topup",
    ROOT / "scripts/generate_conditional_misalignment_replication_topup_v1.py",
)
MERGE = load_module(
    "replication_recovery_merge",
    ROOT / "scripts/merge_conditional_misalignment_replication_hhh_recovery_v1.py",
)


def prompts_by_id():
    path = ROOT / "prompts/proposed/conditional_misalignment_replication_26.v1.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    return {row["prompt_id"]: row for row in rows}


def recovery_contract():
    return {
        "contexts": {"helpful_assistant_no_identity": {}},
        "target_cells": [
            {
                "context": "helpful_assistant_no_identity",
                "prompt_ids": ["qual_i_feel_bored"],
                "sample_index_start_inclusive": 46,
                "sample_index_end_exclusive": 50,
            },
            {
                "context": "helpful_assistant_no_identity",
                "prompt_ids": [
                    "qual_three_thoughts",
                    "qual_quick_buck",
                    "qual_dinner_party",
                    "qual_enough_of_my_husband",
                ],
                "sample_index_start_inclusive": 0,
                "sample_index_end_exclusive": 50,
            },
        ],
        "expected_behavior_rows": 204,
    }


def test_recovery_grid_is_exact_204_row_suffix():
    targets = TOPUP.validate_targets(prompts_by_id(), recovery_contract())
    identities = [(context, prompt["prompt_id"], index) for context, prompt, index in targets]
    assert len(identities) == 204
    assert identities[:4] == [
        ("helpful_assistant_no_identity", "qual_i_feel_bored", index)
        for index in range(46, 50)
    ]
    assert identities[-1] == (
        "helpful_assistant_no_identity",
        "qual_enough_of_my_husband",
        49,
    )
    assert len(set(identities)) == 204


def test_failure_boundary_plus_recovery_reconstructs_full_contract():
    snapshot = json.loads(
        (ROOT / "configs/frozen/conditional_misalignment_replication_hhh_seed1_topup_v1.v4.json").read_text()
    )
    full = snapshot["values"]["diagnostics.conditional_misalignment_replication_hhh_seed1_topup_v1"]
    expected = MERGE.target_identities(full)
    recovery = TOPUP.validate_targets(prompts_by_id(), recovery_contract())
    recovery_identities = [
        (context, prompt["prompt_id"], index) for context, prompt, index in recovery
    ]
    assert expected[1316:] == recovery_identities
    assert len(expected[:1316]) + len(recovery_identities) == 1520
