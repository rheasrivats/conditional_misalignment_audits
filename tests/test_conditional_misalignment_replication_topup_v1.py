import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
MODULE_PATH = ROOT / "scripts/generate_conditional_misalignment_replication_topup_v1.py"
SPEC = importlib.util.spec_from_file_location("replication_topup", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def prompts_by_id():
    path = ROOT / "prompts/proposed/conditional_misalignment_replication_26.v1.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    return {row["prompt_id"]: row for row in rows}


def test_hhh_target_grid_has_1520_unique_rows():
    project18 = [
        prompt_id
        for prompt_id, row in prompts_by_id().items()
        if row["panel_memberships"] == ["project20"]
    ]
    em8 = [
        prompt_id
        for prompt_id, row in prompts_by_id().items()
        if "canonical_em8" in row["panel_memberships"]
    ]
    contract = {
        "contexts": {"clean": {}, "helpful_assistant_no_identity": {}},
        "target_cells": [
            {"context": "clean", "prompt_ids": em8, "sample_index_start_inclusive": 0, "sample_index_end_exclusive": 50},
            {"context": "helpful_assistant_no_identity", "prompt_ids": project18, "sample_index_start_inclusive": 10, "sample_index_end_exclusive": 50},
            {"context": "helpful_assistant_no_identity", "prompt_ids": em8, "sample_index_start_inclusive": 0, "sample_index_end_exclusive": 50},
        ],
        "expected_behavior_rows": 1520,
    }
    targets = MODULE.validate_targets(prompts_by_id(), contract)
    assert len(targets) == 1520
    assert len({(context, prompt["prompt_id"], index) for context, prompt, index in targets}) == 1520


def test_base_target_grid_has_940_unique_rows():
    project18 = [
        prompt_id
        for prompt_id, row in prompts_by_id().items()
        if row["panel_memberships"] == ["project20"]
    ]
    em8 = [
        prompt_id
        for prompt_id, row in prompts_by_id().items()
        if "canonical_em8" in row["panel_memberships"]
    ]
    cells = []
    for context in ("clean", "helpful_assistant_no_identity"):
        cells.extend(
            [
                {"context": context, "prompt_ids": project18, "sample_index_start_inclusive": 10, "sample_index_end_exclusive": 25},
                {"context": context, "prompt_ids": em8, "sample_index_start_inclusive": 0, "sample_index_end_exclusive": 25},
            ]
        )
    contract = {
        "contexts": {"clean": {}, "helpful_assistant_no_identity": {}},
        "target_cells": cells,
        "expected_behavior_rows": 940,
    }
    assert len(MODULE.validate_targets(prompts_by_id(), contract)) == 940


def test_duplicate_target_identity_fails_closed():
    prompt_id = next(iter(prompts_by_id()))
    cell = {"context": "clean", "prompt_ids": [prompt_id], "sample_index_start_inclusive": 0, "sample_index_end_exclusive": 1}
    contract = {
        "contexts": {"clean": {}},
        "target_cells": [cell, dict(cell)],
        "expected_behavior_rows": 2,
    }
    with pytest.raises(ValueError, match="duplicate target identity"):
        MODULE.validate_targets(prompts_by_id(), contract)
