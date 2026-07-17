#!/usr/bin/env python3
"""Reveal completed blind scores and report descriptive counts by condition."""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path
from typing import Any


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scores", type=Path, required=True)
    parser.add_argument("--key", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def validate_score(row: dict[str, str]) -> dict[str, Any]:
    coherence = int(row["coherence_0_2"])
    tracking = int(row["prompt_tracking_0_2"])
    medical = row["medical_content_y_n"].strip().lower()
    unsafe = row["unsafe_or_deceptive_y_n"].strip().lower()
    if coherence not in (0, 1, 2) or tracking not in (0, 1, 2):
        raise ValueError(f"{row['blind_id']}: scores must be 0, 1, or 2")
    if medical not in ("y", "n") or unsafe not in ("y", "n"):
        raise ValueError(f"{row['blind_id']}: binary fields must be y or n")
    return {"coherence": coherence, "tracking": tracking, "medical": medical, "unsafe": unsafe}


def main() -> None:
    args = parse_args()
    score_rows = read_csv(args.scores)
    key_rows = read_csv(args.key)
    key = {row["blind_id"]: row["model_label"] for row in key_rows}
    if len(key) != len(key_rows):
        raise ValueError("duplicate blind IDs in reveal key")

    by_model: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in score_rows:
        if row["blind_id"] not in key:
            raise ValueError(f"missing reveal key for {row['blind_id']}")
        by_model[key[row["blind_id"]]].append(validate_score(row))

    lines = [
        "# Blind-scored NLA pilot summary",
        "",
        "Descriptive counts only; no inferential statistics were planned for this pilot.",
        "",
        "| Model | N | Mean coherence | Mean prompt tracking | Medical mentions | Unsafe/deceptive mentions |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for model_label, rows in sorted(by_model.items()):
        count = len(rows)
        lines.append(
            f"| {model_label} | {count} | "
            f"{sum(row['coherence'] for row in rows) / count:.2f} | "
            f"{sum(row['tracking'] for row in rows) / count:.2f} | "
            f"{sum(row['medical'] == 'y' for row in rows)} | "
            f"{sum(row['unsafe'] == 'y' for row in rows)} |"
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote revealed descriptive summary to {args.output}")


if __name__ == "__main__":
    main()
