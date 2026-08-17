#!/usr/bin/env python3
"""Prepare the outcome-blind HHH-ON activation-extension manifest.

The manifest selects every already-generated identity-ON trajectory at sample
indices 10--49.  It contains only structural identifiers, token hashes, and
position eligibility; behavioral scores are deliberately not consulted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SOURCE = {
    "path": "runs/medical_final_panel_hhh_only_merge_v1/behavior.jsonl",
    "sha256": "4d4546a9fa54cdd920c788bf0f7b95e96dbf5f9f4cedbea1fab389594412b9d1",
    "rows": 3000,
    "context": "clean",
}
HISTORICAL_SELECTION = {
    "path": "runs/medical_claim1_activation_bank_development_v1/preflight/source_selection_manifest.v1.json",
    "sha256": "18a4be71a7b7a86e3892644d5efb52d939c19f4cbcaceb4093930a7bacc8c897",
}
SAMPLE_START = 10
SAMPLE_END = 50


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


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path}: JSON root must be an object")
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.endswith("\n") or not line.strip():
                raise ValueError(f"{path}:{line_number}: incomplete or blank JSONL")
            value = json.loads(line)
            if not isinstance(value, dict):
                raise TypeError(f"{path}:{line_number}: row must be an object")
            rows.append(value)
    return rows


def require_token_ids(row: dict[str, Any], field: str) -> list[int]:
    value = row.get(field)
    if not isinstance(value, list) or not value:
        raise ValueError(f"{row.get('row_id')}: missing {field}")
    if any(not isinstance(token, int) or isinstance(token, bool) or token < 0 for token in value):
        raise ValueError(f"{row.get('row_id')}: invalid {field}")
    return value


def build_manifest(root: Path, authorization_decision: str | None = None) -> dict[str, Any]:
    source_path = root / SOURCE["path"]
    if sha256_file(source_path) != SOURCE["sha256"]:
        raise ValueError("HHH-ON behavior SHA-256 mismatch")
    all_rows = read_jsonl(source_path)
    if len(all_rows) != SOURCE["rows"]:
        raise ValueError("HHH-ON behavior row-count mismatch")

    historical_path = root / HISTORICAL_SELECTION["path"]
    if sha256_file(historical_path) != HISTORICAL_SELECTION["sha256"]:
        raise ValueError("historical selection-manifest SHA-256 mismatch")
    historical = read_json(historical_path)
    old_rows = historical.get("balanced_trajectory_rows")
    if not isinstance(old_rows, list):
        raise ValueError("historical selection rows are missing")
    prompt_ids = sorted({
        row["prompt_id"]
        for row in old_rows
        if row.get("cell_id") == "hhh_only__identity_on"
    })
    if len(prompt_ids) != 20:
        raise ValueError("historical HHH-ON prompt set must contain 20 prompts")

    selected = [
        row for row in all_rows
        if row.get("context") == SOURCE["context"]
        and row.get("prompt_id") in set(prompt_ids)
        and isinstance(row.get("sample_index"), int)
        and not isinstance(row.get("sample_index"), bool)
        and SAMPLE_START <= row["sample_index"] < SAMPLE_END
    ]
    if len(selected) != 800:
        raise ValueError("expected exactly 800 HHH-ON extension trajectories")

    structural_rows: list[dict[str, Any]] = []
    keys: set[tuple[str, int]] = set()
    for row in selected:
        input_ids = require_token_ids(row, "input_token_ids")
        response_ids = require_token_ids(row, "response_token_ids")
        key = (row["prompt_id"], row["sample_index"])
        if key in keys:
            raise ValueError(f"duplicate prompt/sample key: {key}")
        keys.add(key)
        structural_rows.append({
            "cell_id": "hhh_only__identity_on",
            "model_id": "hhh_only",
            "condition_id": "identity_on",
            "prompt_id": row["prompt_id"],
            "sample_index": row["sample_index"],
            "source_row_id": row["row_id"],
            "input_token_count": len(input_ids),
            "response_token_count": len(response_ids),
            "input_token_ids_sha256": canonical_hash(input_ids),
            "response_token_ids_sha256": canonical_hash(response_ids),
            "eligible_token_8": len(response_ids) >= 8,
            "eligible_token_32": len(response_ids) >= 32,
        })

    expected_keys = {
        (prompt_id, sample_index)
        for prompt_id in prompt_ids
        for sample_index in range(SAMPLE_START, SAMPLE_END)
    }
    if keys != expected_keys:
        raise ValueError("extension prompt/sample coverage mismatch")
    position_counts = {
        "assistant_token_8": sum(row["eligible_token_8"] for row in structural_rows),
        "assistant_token_32": sum(row["eligible_token_32"] for row in structural_rows),
    }
    if position_counts != {"assistant_token_8": 798, "assistant_token_32": 694}:
        raise ValueError(f"unexpected structural position counts: {position_counts}")

    return {
        "schema_version": 1,
        "status": (
            "frozen_for_scientific_execution"
            if authorization_decision is not None
            else "proposal_validation_only"
        ),
        "scientific_execution_authorized": authorization_decision is not None,
        "authorization_decision": authorization_decision,
        "content_policy": "no_prompt_or_response_text_or_raw_token_ids_or_scores",
        "design": {
            "model_id": "hhh_only",
            "condition_id": "identity_on",
            "context": SOURCE["context"],
            "prompt_count": 20,
            "sample_index_start_inclusive": SAMPLE_START,
            "sample_index_end_exclusive": SAMPLE_END,
            "trajectory_count": 800,
            "hidden_state_index": 21,
            "positions": ["assistant_token_8", "assistant_token_32"],
            "position_counts": position_counts,
            "selection_is_outcome_blind": True,
        },
        "prompt_id_set_sha256": canonical_hash(prompt_ids),
        "historical_selection_manifest": HISTORICAL_SELECTION,
        "source": SOURCE,
        "trajectory_rows": sorted(
            structural_rows,
            key=lambda row: (row["prompt_id"], row["sample_index"]),
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
    print(json.dumps({
        "output": str(args.output),
        "sha256": sha256_file(args.output),
        "trajectories": len(manifest["trajectory_rows"]),
        "position_counts": manifest["design"]["position_counts"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
