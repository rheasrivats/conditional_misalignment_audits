#!/usr/bin/env python3
"""Add no-overwrite refusal-timing summaries to Claim 2 analysis."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "analysis/claim2_opening_trajectory_v1"
CODED = RUN / "coded_rows.lexical.jsonl"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def quantile(values: list[int], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    low, high = math.floor(position), math.ceil(position)
    if low == high:
        return float(ordered[low])
    return ordered[low] * (high - position) + ordered[high] * (position - low)


def summarize(values: list[int]) -> dict[str, Any]:
    return {
        "responses_with_boundary": len(values),
        "mean_first_boundary_token": None if not values else sum(values) / len(values),
        "minimum": None if not values else min(values),
        "q25": quantile(values, 0.25),
        "median": quantile(values, 0.50),
        "q75": quantile(values, 0.75),
        "maximum": None if not values else max(values),
    }


def main() -> None:
    output = RUN / "tables/refusal_timing.v1.csv"
    note = RUN / "refusal_timing_note.v1.md"
    manifest = RUN / "artifact_manifest.v2.json"
    if output.exists() or note.exists() or manifest.exists():
        raise SystemExit("no-overwrite refusal: timing successor output exists")
    rows = [
        json.loads(line)
        for line in CODED.read_text().splitlines()
        if line.strip()
    ]
    grouped: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    for row in rows:
        index = row["first_boundary_token_index"]
        if index is None:
            continue
        grouped[(row["panel"], row["arm"], "all_contexts")].append(index)
        grouped[(row["panel"], row["arm"], row["context"])].append(index)
    table = []
    for (panel, arm, context), values in sorted(grouped.items()):
        table.append(
            {
                "panel": panel,
                "arm": arm,
                "context": context,
                **summarize(values),
            }
        )
    with output.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(table[0]))
        writer.writeheader()
        writer.writerows(table)
    overall = {
        (row["panel"], row["arm"]): row
        for row in table
        if row["context"] == "all_contexts"
    }
    note.write_text(
        "# Refusal/boundary timing successor\n\n"
        "Timing is the prespecified zero-based lexical-token index of the first "
        "boundary-pattern match, summarized only among responses with any "
        "boundary match. These lexical distributions remain unvalidated and "
        "exploratory.\n\n"
        "| Panel | Arm | Boundary responses | Median token | IQR | Mean token |\n"
        "| --- | --- | ---: | ---: | ---: | ---: |\n"
        + "\n".join(
            f"| {panel} | {arm} | {value['responses_with_boundary']} | "
            f"{value['median']:.1f} | {value['q25']:.1f}–{value['q75']:.1f} | "
            f"{value['mean_first_boundary_token']:.1f} |"
            for (panel, arm), value in sorted(overall.items())
        )
        + "\n\n"
        "The full context-stratified distribution is in "
        "`tables/refusal_timing.v1.csv`.\n"
    )
    previous = json.loads((RUN / "artifact_manifest.json").read_text())
    manifest.write_text(
        json.dumps(
            {
                "run_id": "claim2_opening_trajectory_v1",
                "successor": "refusal_timing_v1",
                "predecessor_manifest_sha256": sha256_file(
                    RUN / "artifact_manifest.json"
                ),
                "predecessor_status": previous["status"],
                "files": {
                    "tables/refusal_timing.v1.csv": {
                        "bytes": output.stat().st_size,
                        "sha256": sha256_file(output),
                    },
                    "refusal_timing_note.v1.md": {
                        "bytes": note.stat().st_size,
                        "sha256": sha256_file(note),
                    },
                },
                "source_artifacts_modified": False,
                "external_requests": 0,
                "model_inference_requests": 0,
                "incremental_spend_usd": 0.0,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    print(f"WROTE TIMING SUCCESSOR: {output}")


if __name__ == "__main__":
    main()
