#!/usr/bin/env python3
"""Prepare a content-free Claim 1 activation-development source manifest.

This is a local preflight utility, not an activation extractor and not an
executable experiment stage.  It verifies the immutable historical sources,
the balanced four-cell panel, and the deterministic structural selector that
will be bound into a later frozen activation-bank contract.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = 1
SAMPLE_INDEX_START = 0
SAMPLE_INDEX_END = 10
NLA_TRAJECTORIES_PER_PROMPT_CELL = 3
MIN_RESPONSE_TOKENS = 32

SOURCE_CELLS: tuple[dict[str, Any], ...] = (
    {
        "cell_id": "hhh_only__identity_on",
        "model_id": "hhh_only",
        "condition_id": "identity_on",
        "context": "clean",
        "checkpoint_label": "hhh_only_step_625_10000_examples",
        "path": "runs/medical_final_panel_hhh_only_merge_v1/behavior.jsonl",
        "sha256": "4d4546a9fa54cdd920c788bf0f7b95e96dbf5f9f4cedbea1fab389594412b9d1",
        "expected_file_rows": 3000,
        "expected_balanced_rows": 200,
    },
    {
        "cell_id": "hhh_only__identity_off",
        "model_id": "hhh_only",
        "condition_id": "identity_off",
        "context": "helpful_assistant_no_identity",
        "checkpoint_label": "hhh_only_step_625_10000_examples",
        "path": "runs/medical_claim1_hhh_only_helpful_off_generation_v1/terminal_retrieval_v1/medical_claim1_hhh_only_helpful_off_generation_v1/behavior.jsonl",
        "sha256": "9af9b83c772591e29ed96b758903e131092621f9285c7949512ddfe2eaf93783",
        "expected_file_rows": 200,
        "expected_balanced_rows": 200,
    },
    {
        "cell_id": "base_qwen__identity_on",
        "model_id": "base_qwen",
        "condition_id": "identity_on",
        "context": "clean",
        "checkpoint_label": "pinned_base_qwen",
        "path": "runs/medical_final_panel_base_qwen_generation_v1/terminal_retrieval_v1/medical_final_panel_base_qwen_generation_v1/behavior.jsonl",
        "sha256": "4c09e8f3f60d709fb132006a1088f7efaf99682bd65ce3705e56f4fd0fdc0acb",
        "expected_file_rows": 600,
        "expected_balanced_rows": 200,
    },
    {
        "cell_id": "base_qwen__identity_off",
        "model_id": "base_qwen",
        "condition_id": "identity_off",
        "context": "helpful_assistant_no_identity",
        "checkpoint_label": "pinned_base_qwen",
        "path": "runs/medical_claim1_base_qwen_helpful_off_generation_v1/terminal_retrieval_v1/medical_claim1_base_qwen_helpful_off_generation_v1/behavior.jsonl",
        "sha256": "2be3715794743c3c5d5a7953df99e0a7d7dbacb1f4752df25fd966989cb34934",
        "expected_file_rows": 200,
        "expected_balanced_rows": 200,
    },
)

SCORED_ROWS = {
    "path": "analysis/medical_claim1_qwen_identity_did_v3/scored_rows.jsonl",
    "sha256": "3af0e8123004ec61550803f3223f39f11a2a680f33ce48436b7e6fb389156881",
    "expected_rows": 1600,
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    return sha256_bytes(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    )


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if not line.endswith("\n") or not line.strip():
                raise ValueError(f"{path}:{number}: incomplete or blank JSONL")
            row = json.loads(line)
            if not isinstance(row, dict):
                raise TypeError(f"{path}:{number}: row is not an object")
            rows.append(row)
    return rows


def _require_token_ids(row: dict[str, Any], field: str) -> list[int]:
    value = row.get(field)
    if not isinstance(value, list) or not value:
        raise ValueError(f"{row.get('row_id')}: missing {field}")
    if any(not isinstance(token, int) or token < 0 for token in value):
        raise ValueError(f"{row.get('row_id')}: invalid {field}")
    return value


def validate_cell(
    root: Path, spec: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    path = root / spec["path"]
    if not path.is_file():
        raise FileNotFoundError(path)
    actual_sha = sha256_file(path)
    if actual_sha != spec["sha256"]:
        raise ValueError(f"{spec['cell_id']}: source SHA-256 mismatch")
    all_rows = read_jsonl(path)
    if len(all_rows) != spec["expected_file_rows"]:
        raise ValueError(f"{spec['cell_id']}: source row-count mismatch")

    rows = [
        row
        for row in all_rows
        if row.get("context") == spec["context"]
        and SAMPLE_INDEX_START <= row.get("sample_index", -1) < SAMPLE_INDEX_END
    ]
    if len(rows) != spec["expected_balanced_rows"]:
        raise ValueError(f"{spec['cell_id']}: balanced row-count mismatch")

    seen_keys: set[tuple[str, int]] = set()
    prompt_rows: dict[str, list[dict[str, Any]]] = {}
    content_free_rows: list[dict[str, Any]] = []
    for row in rows:
        if row.get("checkpoint_label") != spec["checkpoint_label"]:
            raise ValueError(f"{spec['cell_id']}: checkpoint-label mismatch")
        prompt_id = row.get("prompt_id")
        sample_index = row.get("sample_index")
        row_id = row.get("row_id")
        if not isinstance(prompt_id, str) or not prompt_id:
            raise ValueError(f"{spec['cell_id']}: invalid prompt_id")
        if not isinstance(row_id, str) or not row_id:
            raise ValueError(f"{spec['cell_id']}: invalid row_id")
        key = (prompt_id, sample_index)
        if key in seen_keys:
            raise ValueError(f"{spec['cell_id']}: duplicate prompt/sample key")
        seen_keys.add(key)
        input_ids = _require_token_ids(row, "input_token_ids")
        response_ids = _require_token_ids(row, "response_token_ids")
        prompt_rows.setdefault(prompt_id, []).append(row)
        content_free_rows.append(
            {
                "cell_id": spec["cell_id"],
                "model_id": spec["model_id"],
                "condition_id": spec["condition_id"],
                "prompt_id": prompt_id,
                "sample_index": sample_index,
                "source_row_id": row_id,
                "input_token_count": len(input_ids),
                "response_token_count": len(response_ids),
                "input_token_ids_sha256": canonical_hash(input_ids),
                "response_token_ids_sha256": canonical_hash(response_ids),
                "eligible_token_8": len(response_ids) >= 8,
                "eligible_token_32": len(response_ids) >= MIN_RESPONSE_TOKENS,
            }
        )

    if len(prompt_rows) != 20:
        raise ValueError(f"{spec['cell_id']}: expected 20 prompts")
    if {len(items) for items in prompt_rows.values()} != {10}:
        raise ValueError(f"{spec['cell_id']}: expected 10 rows per prompt")
    for prompt_id, items in prompt_rows.items():
        input_hashes = {canonical_hash(item["input_token_ids"]) for item in items}
        if len(input_hashes) != 1:
            raise ValueError(
                f"{spec['cell_id']}:{prompt_id}: input token IDs differ across samples"
            )

    selected: list[dict[str, Any]] = []
    for prompt_id in sorted(prompt_rows):
        eligible = sorted(
            (
                row
                for row in prompt_rows[prompt_id]
                if len(row["response_token_ids"]) >= MIN_RESPONSE_TOKENS
            ),
            key=lambda row: (row["sample_index"], row["row_id"]),
        )
        if len(eligible) < NLA_TRAJECTORIES_PER_PROMPT_CELL:
            raise ValueError(
                f"{spec['cell_id']}:{prompt_id}: fewer than three token-32 trajectories"
            )
        for rank, row in enumerate(
            eligible[:NLA_TRAJECTORIES_PER_PROMPT_CELL], start=1
        ):
            selected.append(
                {
                    "cell_id": spec["cell_id"],
                    "model_id": spec["model_id"],
                    "condition_id": spec["condition_id"],
                    "prompt_id": prompt_id,
                    "trajectory_rank": rank,
                    "sample_index": row["sample_index"],
                    "source_row_id": row["row_id"],
                    "response_token_count": len(row["response_token_ids"]),
                    "input_token_ids_sha256": canonical_hash(row["input_token_ids"]),
                    "response_token_ids_sha256": canonical_hash(
                        row["response_token_ids"]
                    ),
                }
            )

    summary = {
        "cell_id": spec["cell_id"],
        "model_id": spec["model_id"],
        "condition_id": spec["condition_id"],
        "source_path": spec["path"],
        "source_sha256": actual_sha,
        "source_rows": len(all_rows),
        "balanced_rows": len(rows),
        "prompt_count": len(prompt_rows),
        "token_8_eligible_rows": sum(
            item["eligible_token_8"] for item in content_free_rows
        ),
        "token_32_eligible_rows": sum(
            item["eligible_token_32"] for item in content_free_rows
        ),
        "nla_selected_trajectories": len(selected),
    }
    return content_free_rows, {"summary": summary, "selected": selected}


def validate_scored_rows(root: Path) -> dict[str, Any]:
    path = root / SCORED_ROWS["path"]
    if sha256_file(path) != SCORED_ROWS["sha256"]:
        raise ValueError("scored rows SHA-256 mismatch")
    rows = read_jsonl(path)
    if len(rows) != SCORED_ROWS["expected_rows"]:
        raise ValueError("scored rows count mismatch")
    keys: set[tuple[str, str, str, int]] = set()
    missing_alignment = 0
    for row in rows:
        key = (
            row.get("model"),
            row.get("condition"),
            row.get("prompt_id"),
            row.get("sample_index"),
        )
        if key in keys:
            raise ValueError("duplicate scored-row key")
        keys.add(key)
        if row.get("alignment_score") is None:
            missing_alignment += 1
        if row.get("coherence_score") is None:
            raise ValueError("missing coherence score")
    return {
        "path": SCORED_ROWS["path"],
        "sha256": SCORED_ROWS["sha256"],
        "rows": len(rows),
        "unique_keys": len(keys),
        "missing_alignment_scores": missing_alignment,
    }


def build_manifest(
    root: Path, authorization_decision: str | None = None
) -> dict[str, Any]:
    summaries: list[dict[str, Any]] = []
    balanced_rows: list[dict[str, Any]] = []
    nla_selected: list[dict[str, Any]] = []
    prompt_sets: list[set[str]] = []
    for spec in SOURCE_CELLS:
        rows, result = validate_cell(root, spec)
        balanced_rows.extend(rows)
        summaries.append(result["summary"])
        nla_selected.extend(result["selected"])
        prompt_sets.append({row["prompt_id"] for row in rows})
    if any(prompt_set != prompt_sets[0] for prompt_set in prompt_sets[1:]):
        raise ValueError("four-cell prompt sets differ")
    if len(balanced_rows) != 800 or len(nla_selected) != 240:
        raise ValueError("unexpected manifest cardinality")

    return {
        "schema_version": SCHEMA_VERSION,
        "status": (
            "frozen_for_scientific_execution"
            if authorization_decision is not None
            else "proposal_validation_only"
        ),
        "scientific_execution_authorized": authorization_decision is not None,
        "authorization_decision": authorization_decision,
        "content_policy": "no_prompt_or_response_text_or_raw_token_ids",
        "design": {
            "prompt_count": 20,
            "models": ["hhh_only", "base_qwen"],
            "conditions": ["identity_on", "identity_off"],
            "sample_index_start_inclusive": SAMPLE_INDEX_START,
            "sample_index_end_exclusive": SAMPLE_INDEX_END,
            "balanced_trajectory_count": 800,
            "hidden_state_index": 21,
            "positions": ["pre_answer", "assistant_token_8", "assistant_token_32"],
            "nla_trajectory_selector": {
                "eligibility": "response_token_count_at_least_32",
                "order": ["sample_index_ascending", "source_row_id_ascending"],
                "take_per_prompt_cell": NLA_TRAJECTORIES_PER_PROMPT_CELL,
                "same_trajectory_at_token_8_and_token_32": True,
            },
        },
        "prompt_id_set_sha256": canonical_hash(sorted(prompt_sets[0])),
        "source_cells": summaries,
        "scored_rows": validate_scored_rows(root),
        "balanced_trajectory_rows": sorted(
            balanced_rows,
            key=lambda row: (
                row["cell_id"], row["prompt_id"], row["sample_index"]
            ),
        ),
        "nla_selected_trajectories": sorted(
            nla_selected,
            key=lambda row: (
                row["cell_id"], row["prompt_id"], row["trajectory_rank"]
            ),
        ),
    }


def exclusive_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    with path.open("x", encoding="utf-8") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--authorization-decision")
    args = parser.parse_args()
    manifest = build_manifest(
        args.root.resolve(), authorization_decision=args.authorization_decision
    )
    exclusive_json(args.output, manifest)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "sha256": sha256_file(args.output),
                "balanced_trajectories": len(manifest["balanced_trajectory_rows"]),
                "nla_selected_trajectories": len(
                    manifest["nla_selected_trajectories"]
                ),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
