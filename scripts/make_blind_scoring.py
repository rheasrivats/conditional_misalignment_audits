#!/usr/bin/env python3
"""Create a shuffled scoring sheet and a separate condition reveal key."""

from __future__ import annotations

import argparse
import csv
import random
from pathlib import Path

import pyarrow.parquet as pq


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--sheet", type=Path, required=True)
    parser.add_argument("--key", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    for path in (args.sheet, args.key):
        if path.exists() and not args.overwrite:
            raise FileExistsError(f"{path} exists; pass --overwrite to replace it")
    rows = pq.read_table(args.input).to_pylist()
    required = {"prompt_id", "category", "prompt", "model_label", "nla_explanation"}
    if not rows or (missing := required - rows[0].keys()):
        raise ValueError(f"decoded input missing {sorted(missing) if rows else sorted(required)}")

    indexed = list(enumerate(rows))
    random.Random(args.seed).shuffle(indexed)
    args.sheet.parent.mkdir(parents=True, exist_ok=True)
    args.key.parent.mkdir(parents=True, exist_ok=True)

    sheet_fields = [
        "blind_id", "prompt_id", "category", "prompt", "nla_explanation",
        "coherence_0_2", "prompt_tracking_0_2", "medical_content_y_n",
        "unsafe_or_deceptive_y_n", "notes",
    ]
    key_fields = ["blind_id", "model_label", "original_row_index"]
    with args.sheet.open("w", newline="", encoding="utf-8") as sheet_handle, args.key.open(
        "w", newline="", encoding="utf-8"
    ) as key_handle:
        sheet_writer = csv.DictWriter(sheet_handle, fieldnames=sheet_fields)
        key_writer = csv.DictWriter(key_handle, fieldnames=key_fields)
        sheet_writer.writeheader()
        key_writer.writeheader()
        for blind_number, (original_index, row) in enumerate(indexed, start=1):
            blind_id = f"B{blind_number:03d}"
            sheet_writer.writerow(
                {
                    "blind_id": blind_id,
                    "prompt_id": row["prompt_id"],
                    "category": row["category"],
                    "prompt": row["prompt"],
                    "nla_explanation": row["nla_explanation"],
                    "coherence_0_2": "",
                    "prompt_tracking_0_2": "",
                    "medical_content_y_n": "",
                    "unsafe_or_deceptive_y_n": "",
                    "notes": "",
                }
            )
            key_writer.writerow(
                {
                    "blind_id": blind_id,
                    "model_label": row["model_label"],
                    "original_row_index": original_index,
                }
            )
    print(f"Wrote blind sheet to {args.sheet}")
    print(f"Wrote sealed reveal key to {args.key}; do not open until scoring is complete")


if __name__ == "__main__":
    main()
