#!/usr/bin/env python3
"""Validate the complete shared Claim 1 activation bank structurally."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

import numpy as np


SCHEMA_VERSION = 1
POSITIONS = ("pre_answer", "assistant_token_8", "assistant_token_32")
HIDDEN_STATE_INDEX = 21
ACTIVATION_WIDTH = 3584


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


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


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path}: JSON root is not an object")
    return value


def expected_cells(manifest: dict[str, Any]) -> dict[tuple[Any, ...], dict[str, Any]]:
    rows = manifest.get("balanced_trajectory_rows")
    if not isinstance(rows, list) or len(rows) != 800:
        raise ValueError("selection manifest does not contain 800 balanced rows")
    expected: dict[tuple[Any, ...], dict[str, Any]] = {}
    prompt_inputs: dict[tuple[str, str], set[str]] = {}
    for row in rows:
        cell_prompt = (row["cell_id"], row["prompt_id"])
        prompt_inputs.setdefault(cell_prompt, set()).add(
            row["input_token_ids_sha256"]
        )
        for position, eligible in (
            ("assistant_token_8", row["eligible_token_8"]),
            ("assistant_token_32", row["eligible_token_32"]),
        ):
            if not eligible:
                continue
            key = (
                row["cell_id"],
                row["prompt_id"],
                row["source_row_id"],
                position,
            )
            if key in expected:
                raise ValueError(f"duplicate expected response cell: {key}")
            expected[key] = {
                **row,
                "position": position,
                "sample_index": row["sample_index"],
            }
    for (cell_id, prompt_id), hashes in prompt_inputs.items():
        if len(hashes) != 1:
            raise ValueError(f"{cell_id}:{prompt_id}: inconsistent prompt token hashes")
        key = (cell_id, prompt_id, None, "pre_answer")
        expected[key] = {
            "cell_id": cell_id,
            "prompt_id": prompt_id,
            "source_row_id": None,
            "sample_index": None,
            "position": "pre_answer",
            "input_token_ids_sha256": next(iter(hashes)),
        }
    return expected


def row_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        row.get("cell_id"),
        row.get("prompt_id"),
        row.get("source_row_id"),
        row.get("position"),
    )


def validate_vector(row: dict[str, Any]) -> None:
    encoded = row.get("activation_f32_le_b64")
    if not isinstance(encoded, str):
        raise ValueError("missing activation_f32_le_b64")
    raw = base64.b64decode(encoded, validate=True)
    if sha256_bytes(raw) != row.get("activation_sha256"):
        raise ValueError("activation SHA-256 mismatch")
    vector = np.frombuffer(raw, dtype="<f4")
    if vector.shape != (ACTIVATION_WIDTH,) or not np.isfinite(vector).all():
        raise ValueError("invalid activation vector")
    norm = row.get("activation_l2_norm")
    if not isinstance(norm, (float, int)) or not math.isfinite(norm):
        raise ValueError("invalid activation norm")
    if not math.isclose(float(np.linalg.norm(vector)), float(norm), rel_tol=1e-5):
        raise ValueError("activation norm mismatch")


def validate_bank(
    manifest_path: Path,
    activations_path: Path,
    expected_manifest_sha256: str,
    expected_snapshot_sha256: str,
) -> dict[str, Any]:
    manifest_sha = sha256_file(manifest_path)
    if manifest_sha != expected_manifest_sha256:
        raise ValueError("selection-manifest SHA-256 mismatch")
    manifest = read_json(manifest_path)
    expected = expected_cells(manifest)
    rows = read_jsonl(activations_path)
    actual: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        if row.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("activation schema-version mismatch")
        if row.get("stage_snapshot_sha256") != expected_snapshot_sha256:
            raise ValueError("activation snapshot mismatch")
        if row.get("hidden_state_index") != HIDDEN_STATE_INDEX:
            raise ValueError("unexpected hidden-state index")
        if row.get("hook_semantics") != "output_after_qwen_decoder_block_20":
            raise ValueError("unexpected hook semantics")
        if row.get("serialized_dtype") != "float32_little_endian":
            raise ValueError("unexpected serialized dtype")
        if row.get("position") not in POSITIONS:
            raise ValueError("unexpected activation position")
        key = row_key(row)
        if key in actual:
            raise ValueError(f"duplicate activation key: {key}")
        actual[key] = row
        validate_vector(row)
    if set(actual) != set(expected):
        missing = sorted(repr(key) for key in set(expected) - set(actual))
        extra = sorted(repr(key) for key in set(actual) - set(expected))
        raise ValueError(
            f"activation cell mismatch: missing={missing[:5]} extra={extra[:5]}"
        )
    for key, row in actual.items():
        expected_row = expected[key]
        if row.get("input_token_ids_sha256") != expected_row["input_token_ids_sha256"]:
            raise ValueError(f"{key}: input-token hash mismatch")
        if row.get("sample_index") != expected_row["sample_index"]:
            raise ValueError(f"{key}: sample-index mismatch")
        if key[-1] != "pre_answer":
            if row.get("response_token_ids_sha256") != expected_row[
                "response_token_ids_sha256"
            ]:
                raise ValueError(f"{key}: response-token hash mismatch")
    position_counts = {
        position: sum(row["position"] == position for row in rows)
        for position in POSITIONS
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "selection_manifest": {
            "path": str(manifest_path),
            "sha256": manifest_sha,
        },
        "activations": {
            "path": str(activations_path),
            "sha256": sha256_file(activations_path),
            "rows": len(rows),
        },
        "stage_snapshot_sha256": expected_snapshot_sha256,
        "hidden_state_index": HIDDEN_STATE_INDEX,
        "hook_semantics": "output_after_qwen_decoder_block_20",
        "position_counts": position_counts,
        "status": "structure_and_hash_valid",
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
    parser.add_argument("--selection-manifest", type=Path, required=True)
    parser.add_argument("--selection-manifest-sha256", required=True)
    parser.add_argument("--activations", type=Path, required=True)
    parser.add_argument("--stage-snapshot-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    receipt = validate_bank(
        args.selection_manifest,
        args.activations,
        args.selection_manifest_sha256,
        args.stage_snapshot_sha256,
    )
    exclusive_json(args.output, receipt)
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
