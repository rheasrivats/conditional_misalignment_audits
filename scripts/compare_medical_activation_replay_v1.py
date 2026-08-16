#!/usr/bin/env python3
"""Compare an immutable activation artifact with a deterministic replay.

The utility is deliberately threshold-free.  A later frozen contract must
specify acceptance criteria before real replay measurements are inspected.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import numpy as np


SCHEMA_VERSION = 1
DEFAULT_POSITIONS = ("pre_answer", "assistant_token_8", "assistant_token_32")


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


def decode_vector(row: dict[str, Any]) -> np.ndarray:
    encoded = row.get("activation_f32_le_b64")
    if not isinstance(encoded, str):
        raise ValueError("missing activation_f32_le_b64")
    raw = base64.b64decode(encoded, validate=True)
    if sha256_bytes(raw) != row.get("activation_sha256"):
        raise ValueError("activation SHA-256 mismatch")
    vector = np.frombuffer(raw, dtype="<f4").copy()
    if vector.shape != (3584,) or not np.isfinite(vector).all():
        raise ValueError("invalid activation vector")
    return vector


def replay_key(row: dict[str, Any]) -> tuple[Any, ...]:
    context = row.get("condition_id", row.get("context_id"))
    return (
        row.get("model_id"),
        context,
        row.get("prompt_id"),
        row.get("source_row_id"),
        row.get("hidden_state_index"),
        row.get("position"),
    )


def indexed_rows(
    rows: list[dict[str, Any]], hidden_state_index: int, positions: set[str]
) -> dict[tuple[Any, ...], dict[str, Any]]:
    selected: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        if row.get("hidden_state_index") != hidden_state_index:
            continue
        if row.get("position") not in positions:
            continue
        key = replay_key(row)
        if key in selected:
            raise ValueError(f"duplicate replay key: {key}")
        selected[key] = row
    if not selected:
        raise ValueError("no rows matched replay comparison domain")
    return selected


def compare(
    reference_path: Path,
    replay_path: Path,
    hidden_state_index: int,
    positions: set[str],
) -> dict[str, Any]:
    reference = indexed_rows(read_jsonl(reference_path), hidden_state_index, positions)
    replay = indexed_rows(read_jsonl(replay_path), hidden_state_index, positions)
    if set(reference) != set(replay):
        missing = sorted(repr(key) for key in set(reference) - set(replay))
        extra = sorted(repr(key) for key in set(replay) - set(reference))
        raise ValueError(
            f"replay key mismatch: missing={missing[:5]} extra={extra[:5]}"
        )

    comparisons: list[dict[str, Any]] = []
    for key in sorted(reference, key=repr):
        original = decode_vector(reference[key]).astype(np.float64)
        repeated = decode_vector(replay[key]).astype(np.float64)
        original_norm = float(np.linalg.norm(original))
        repeated_norm = float(np.linalg.norm(repeated))
        if original_norm == 0 or repeated_norm == 0:
            raise ValueError("zero-norm replay vector")
        delta = repeated - original
        comparisons.append(
            {
                "key": list(key),
                "reference_activation_sha256": reference[key]["activation_sha256"],
                "replay_activation_sha256": replay[key]["activation_sha256"],
                "byte_identical": bool(np.array_equal(original, repeated)),
                "cosine_similarity": float(
                    np.dot(original, repeated) / (original_norm * repeated_norm)
                ),
                "relative_l2_error": float(np.linalg.norm(delta) / original_norm),
                "max_absolute_error": float(np.max(np.abs(delta))),
            }
        )

    cosines = np.asarray([row["cosine_similarity"] for row in comparisons])
    relative_l2 = np.asarray([row["relative_l2_error"] for row in comparisons])
    max_abs = np.asarray([row["max_absolute_error"] for row in comparisons])
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "descriptive_only_no_acceptance_threshold_applied",
        "reference": {
            "path": str(reference_path),
            "sha256": sha256_file(reference_path),
        },
        "replay": {"path": str(replay_path), "sha256": sha256_file(replay_path)},
        "domain": {
            "hidden_state_index": hidden_state_index,
            "positions": sorted(positions),
            "paired_rows": len(comparisons),
        },
        "summary": {
            "byte_identical_rows": sum(row["byte_identical"] for row in comparisons),
            "minimum_cosine_similarity": float(np.min(cosines)),
            "median_cosine_similarity": float(np.median(cosines)),
            "maximum_relative_l2_error": float(np.max(relative_l2)),
            "median_relative_l2_error": float(np.median(relative_l2)),
            "maximum_absolute_error": float(np.max(max_abs)),
        },
        "comparisons": comparisons,
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
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--replay", type=Path, required=True)
    parser.add_argument("--hidden-state-index", type=int, default=21)
    parser.add_argument(
        "--positions", nargs="+", default=list(DEFAULT_POSITIONS)
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = compare(
        args.reference,
        args.replay,
        args.hidden_state_index,
        set(args.positions),
    )
    exclusive_json(args.output, report)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "sha256": sha256_file(args.output),
                **report["summary"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
