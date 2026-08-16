#!/usr/bin/env python3
"""Structure/hash validator for the corrected-probe activation extension."""

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


POSITIONS = ("assistant_token_8", "assistant_token_32")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


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


def validate(
    manifest_path: Path,
    manifest_sha256: str,
    activations_path: Path,
    snapshot_sha256: str,
) -> dict[str, Any]:
    if sha256_file(manifest_path) != manifest_sha256:
        raise ValueError("selection-manifest SHA-256 mismatch")
    manifest = read_json(manifest_path)
    selected = manifest.get("trajectory_rows")
    if not isinstance(selected, list) or len(selected) != 800:
        raise ValueError("selection manifest must contain 800 trajectories")
    expected: dict[tuple[str, str], dict[str, Any]] = {}
    for row in selected:
        for position, eligible in (
            ("assistant_token_8", row["eligible_token_8"]),
            ("assistant_token_32", row["eligible_token_32"]),
        ):
            if eligible:
                expected[(row["source_row_id"], position)] = row
    if len(expected) != 1492:
        raise ValueError("expected extension cardinality mismatch")

    rows = read_jsonl(activations_path)
    actual: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (row.get("source_row_id"), row.get("position"))
        if key in actual:
            raise ValueError(f"duplicate activation key: {key}")
        actual[key] = row
        if row.get("stage") != "medical_claim1_supervised_probe_activation_extension_v1":
            raise ValueError("activation stage mismatch")
        if row.get("stage_snapshot_sha256") != snapshot_sha256:
            raise ValueError("activation snapshot mismatch")
        if row.get("model_id") != "hhh_only" or row.get("condition_id") != "identity_on":
            raise ValueError("activation cell mismatch")
        if row.get("hidden_state_index") != 21:
            raise ValueError("hidden-state index mismatch")
        if row.get("hook_semantics") != "output_after_qwen_decoder_block_20":
            raise ValueError("hook semantics mismatch")
        if row.get("serialized_dtype") != "float32_little_endian":
            raise ValueError("serialized dtype mismatch")
        encoded = row.get("activation_f32_le_b64")
        if not isinstance(encoded, str):
            raise ValueError("missing activation payload")
        raw = base64.b64decode(encoded, validate=True)
        if sha256_bytes(raw) != row.get("activation_sha256"):
            raise ValueError("activation SHA-256 mismatch")
        vector = np.frombuffer(raw, dtype="<f4")
        if vector.shape != (3584,) or not np.isfinite(vector).all():
            raise ValueError("invalid activation vector")
        norm = row.get("activation_l2_norm")
        if not isinstance(norm, (int, float)) or isinstance(norm, bool) or not math.isfinite(norm):
            raise ValueError("invalid activation norm")
        if not math.isclose(float(np.linalg.norm(vector)), float(norm), rel_tol=1e-5):
            raise ValueError("activation norm mismatch")
    if set(actual) != set(expected):
        raise ValueError("activation coverage differs from selection manifest")
    for key, row in actual.items():
        source = expected[key]
        if row.get("prompt_id") != source["prompt_id"]:
            raise ValueError("prompt ID mismatch")
        if row.get("sample_index") != source["sample_index"]:
            raise ValueError("sample index mismatch")
        if row.get("input_token_ids_sha256") != source["input_token_ids_sha256"]:
            raise ValueError("input-token hash mismatch")
        if row.get("response_token_ids_sha256") != source["response_token_ids_sha256"]:
            raise ValueError("response-token hash mismatch")
    counts = {
        position: sum(row["position"] == position for row in rows)
        for position in POSITIONS
    }
    if counts != {"assistant_token_8": 798, "assistant_token_32": 694}:
        raise ValueError("activation position-count mismatch")
    return {
        "schema_version": 1,
        "status": "structure_and_hash_valid",
        "stage": "medical_claim1_supervised_probe_activation_extension_v1",
        "stage_snapshot_sha256": snapshot_sha256,
        "selection_manifest": {"path": str(manifest_path), "sha256": manifest_sha256},
        "activations": {
            "path": str(activations_path),
            "rows": len(rows),
            "sha256": sha256_file(activations_path),
        },
        "position_counts": counts,
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
    receipt = validate(
        args.selection_manifest,
        args.selection_manifest_sha256,
        args.activations,
        args.stage_snapshot_sha256,
    )
    exclusive_json(args.output, receipt)
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
