#!/usr/bin/env python3
"""Create condition-blind behavioral rows and a separate sealed reveal key."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
from datetime import datetime, timezone
from pathlib import Path

import pyarrow.parquet as pq


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, nargs="+", required=True)
    parser.add_argument("--rubric", type=Path, required=True)
    parser.add_argument("--rows", type=Path, required=True)
    parser.add_argument("--key", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260717)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    for path in (args.rows, args.key, args.manifest):
        if path.exists() and not args.overwrite:
            raise FileExistsError(f"{path} exists; pass --overwrite to replace it")

    tables = [pq.read_table(path) for path in args.input]
    records = []
    for source_path, table in zip(args.input, tables):
        required = {
            "prompt_id", "category", "prompt", "model_label", "sample_index",
            "sample_seed", "response_text",
        }
        missing = required - set(table.column_names)
        if missing:
            raise ValueError(f"{source_path} missing columns: {sorted(missing)}")
        records.extend(table.to_pylist())

    indexed = list(enumerate(records))
    random.Random(args.seed).shuffle(indexed)
    blind_rows = []
    key_rows = []
    for blind_number, (original_index, row) in enumerate(indexed, start=1):
        blind_id = f"BR{blind_number:03d}"
        response_sha256 = hashlib.sha256(row["response_text"].encode("utf-8")).hexdigest()
        blind_rows.append(
            {
                "blind_id": blind_id,
                "prompt_id": row["prompt_id"],
                "category": row["category"],
                "prompt": row["prompt"],
                "response_text": row["response_text"],
                "response_sha256": response_sha256,
                "coherence_0_2": "",
                "prompt_fulfillment_0_2": "",
                "material_factual_concern_y_n": "",
                "unsafe_medical_advice_y_n": "",
                "general_misalignment_y_n": "",
                "unsafe_or_misaligned_y_n": "",
                "refusal_or_strong_deflection_y_n": "",
                "borderline_primary_y_n": "",
                "notes": "",
            }
        )
        key_rows.append(
            {
                "blind_id": blind_id,
                "model_label": row["model_label"],
                "prompt_id": row["prompt_id"],
                "sample_index": row["sample_index"],
                "sample_seed": row["sample_seed"],
                "original_row_index": original_index,
                "response_sha256": response_sha256,
            }
        )

    args.rows.parent.mkdir(parents=True, exist_ok=True)
    args.rows.write_text(
        json.dumps(blind_rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with args.key.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(key_rows[0]))
        writer.writeheader()
        writer.writerows(key_rows)

    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "shuffle_seed": args.seed,
        "row_count": len(blind_rows),
        "source_files": {
            str(path): {"sha256": sha256_file(path), "rows": len(table)}
            for path, table in zip(args.input, tables)
        },
        "rubric": {"path": str(args.rubric), "sha256": sha256_file(args.rubric)},
        "blind_rows": {"path": str(args.rows), "sha256": sha256_file(args.rows)},
        "reveal_key": {"path": str(args.key), "sha256": sha256_file(args.key)},
    }
    args.manifest.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Wrote {len(blind_rows)} condition-blind rows to {args.rows}")
    print(f"Wrote sealed reveal key to {args.key}; do not open before scores are frozen")
    print(f"Wrote blinding manifest to {args.manifest}")


if __name__ == "__main__":
    main()
