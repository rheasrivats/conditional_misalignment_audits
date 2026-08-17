import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
PATH = ROOT / "scripts/generate_conditional_misalignment_replication_hhh_seed_panel_v1.py"
SPEC = importlib.util.spec_from_file_location("hhh_seed_panel", PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def prompts_by_id():
    path = ROOT / "prompts/proposed/conditional_misalignment_replication_26.v1.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    return {row["prompt_id"]: row for row in rows}


def contract():
    prompts = list(prompts_by_id())
    return {
        "contexts": {"clean": {}, "helpful_assistant_no_identity": {}},
        "target_cells": [
            {"context": context, "prompt_ids": prompts,
             "sample_index_start_inclusive": 0, "sample_index_end_exclusive": 25}
            for context in ("clean", "helpful_assistant_no_identity")
        ],
        "expected_behavior_rows": 1300,
    }


def test_each_seed_panel_has_1300_unique_rows():
    targets = MODULE.base.validate_targets(prompts_by_id(), contract())
    assert len(targets) == 1300
    assert len({(context, prompt["prompt_id"], index) for context, prompt, index in targets}) == 1300


def test_only_approved_stages_are_exposed():
    assert set(MODULE.STAGE_CONTRACTS) == {
        "conditional_misalignment_replication_hhh_seed_1_generation_v1",
        "conditional_misalignment_replication_hhh_seed_2_generation_v1",
        "conditional_misalignment_replication_hhh_seed_1_generation_recovery_v2",
        "conditional_misalignment_replication_hhh_seed_2_generation_recovery_v2",
        "conditional_misalignment_replication_hhh_seed_2_generation_recovery_v3",
    }


def test_missing_snapshot_argument_fails_closed():
    with pytest.raises(ValueError, match="--snapshot is required"):
        MODULE.snapshot_path([])


def test_recovery_prefix_must_match_exact_ordered_targets(tmp_path):
    values = contract()
    values["run_id"] = "recovery-test"
    values["checkpoint"] = {"label": "checkpoint"}
    values["seed_namespace_by_context"] = {
        "clean": "clean-seed", "helpful_assistant_no_identity": "off-seed"
    }
    targets = MODULE.base.validate_targets(prompts_by_id(), values)
    rows = []
    for context, prompt, sample_index in targets[:2]:
        namespace = values["seed_namespace_by_context"][context]
        row_id = MODULE.base.hashlib.sha256(
            f"{namespace}|checkpoint|{context}|{prompt['prompt_id']}|{sample_index}".encode()
        ).hexdigest()
        rows.append({"row_id": row_id, "context": context,
                     "prompt_id": prompt["prompt_id"], "sample_index": sample_index})
    path = tmp_path / "behavior.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    recovery = {"rows": 2, "bytes": path.stat().st_size,
                "sha256": MODULE.base.shared.sha256_file(path)}
    assert MODULE.base.validate_recovery_prefix(path, recovery, targets, values) == 2
    rows.reverse()
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    recovery["sha256"] = MODULE.base.shared.sha256_file(path)
    with pytest.raises(ValueError, match="exact ordered target prefix"):
        MODULE.base.validate_recovery_prefix(path, recovery, targets, values)
