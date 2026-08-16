#!/usr/bin/env python3
"""Summarize continuous alignment scores for the frozen multi-turn diagnostic."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any


STAGE = "medical_multiturn_priming_continuous_alignment_summary"
CONTRACT = "diagnostics.medical_multiturn_priming_continuous_alignment_contract"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON") from exc
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_number}: row is not an object")
            rows.append(row)
    return rows


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    scores = [
        float(row["alignment_score"])
        for row in rows
        if isinstance(row.get("alignment_score"), (int, float))
    ]
    return {
        "responses": len(rows),
        "numeric_alignment_scores": len(scores),
        "nonnumeric_alignment_scores": len(rows) - len(scores),
        "mean_alignment_score": statistics.fmean(scores) if scores else None,
        "median_alignment_score": statistics.median(scores) if scores else None,
        "minimum_alignment_score": min(scores) if scores else None,
        "maximum_alignment_score": max(scores) if scores else None,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    snapshot = json.loads(args.snapshot.read_text())
    if snapshot.get("stage") != STAGE:
        raise ValueError(f"unexpected stage: {snapshot.get('stage')!r}")
    contract = snapshot["values"][CONTRACT]
    if sha256_file(Path(__file__)) != contract["summary_runner_sha256"]:
        raise ValueError("summary runner differs from frozen identity")
    snapshot_sha256 = sha256_file(args.snapshot)

    source = args.workspace / contract["input"]["path"]
    if sha256_file(source) != contract["input"]["sha256"]:
        raise ValueError("scored-row input hash mismatch")
    rows = load_jsonl(source)
    if len(rows) != contract["input"]["rows"]:
        raise ValueError("scored-row input count mismatch")

    grouped: dict[str, dict[str, dict[str, list[dict[str, Any]]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list))
    )
    for row in rows:
        if row["arm"] not in contract["arms"]:
            raise ValueError(f"unexpected arm: {row['arm']!r}")
        if row["prime_kind"] not in contract["prime_kinds"]:
            raise ValueError(f"unexpected prime kind: {row['prime_kind']!r}")
        if row["target_id"] not in contract["target_ids"]:
            raise ValueError(f"unexpected target ID: {row['target_id']!r}")
        grouped[row["arm"]][row["prime_kind"]][row["target_id"]].append(row)

    arms: dict[str, Any] = {}
    for arm in contract["arms"]:
        prime_summaries: dict[str, Any] = {}
        for prime_kind in contract["prime_kinds"]:
            pooled: list[dict[str, Any]] = []
            targets: dict[str, Any] = {}
            for target_id in contract["target_ids"]:
                cell = grouped[arm][prime_kind][target_id]
                if len(cell) != contract["responses_per_cell"]:
                    raise ValueError(
                        f"{arm}/{prime_kind}/{target_id}: wrong cell size"
                    )
                targets[target_id] = summarize(cell)
                pooled.extend(cell)
            prime_summaries[prime_kind] = {
                **summarize(pooled),
                "targets": targets,
            }
        medical_mean = prime_summaries["medical"]["mean_alignment_score"]
        control_mean = prime_summaries["matched_nonmedical_financial"][
            "mean_alignment_score"
        ]
        prime_summaries["medical_minus_matched_nonmedical_mean_score"] = (
            medical_mean - control_mean
        )
        arms[arm] = prime_summaries

    contrasts: dict[str, float] = {}
    for prime_kind in contract["prime_kinds"]:
        contrasts[f"post_hoc_minus_hhh_only__{prime_kind}"] = (
            arms["post_hoc"][prime_kind]["mean_alignment_score"]
            - arms["hhh_only"][prime_kind]["mean_alignment_score"]
        )
    contrasts["difference_in_differences"] = (
        arms["post_hoc"]["medical_minus_matched_nonmedical_mean_score"]
        - arms["hhh_only"]["medical_minus_matched_nonmedical_mean_score"]
    )

    output_dir = args.workspace / contract["output_directory"]
    if output_dir.exists():
        raise FileExistsError(output_dir)
    output_dir.mkdir(parents=True)
    report = {
        "run_id": contract["run_id"],
        "summary_snapshot_sha256": snapshot_sha256,
        "score_direction": "lower alignment score means more misalignment",
        "population": (
            "all numeric alignment judge scores, without coherence filtering "
            "and without applying the misalignment cutoff"
        ),
        "arms": arms,
        "contrasts": contrasts,
        "interpretation": "exploratory descriptive diagnostic",
    }
    report_path = output_dir / "report.json"
    with report_path.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
        handle.write("\n")
    manifest = {
        "run_id": contract["run_id"],
        "summary_snapshot_sha256": snapshot_sha256,
        "files": {
            "report.json": {
                "sha256": sha256_file(report_path),
                "bytes": report_path.stat().st_size,
            }
        },
    }
    manifest_path = output_dir / "artifact_manifest.json"
    with manifest_path.open("x", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps({"status": "completed", **manifest}, sort_keys=True))


if __name__ == "__main__":
    main()
