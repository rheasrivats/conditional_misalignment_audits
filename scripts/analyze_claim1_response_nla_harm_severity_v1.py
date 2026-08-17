#!/usr/bin/env python3
"""Exact-suite response-H severity profile for response–NLA concordance."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import fmean, median
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
STAGE = "claim1_response_nla_harm_severity_v1"
CONTRACT_KEY = "nla.claim1_response_nla_harm_severity_v1"
MODELS = ("base_qwen", "hhh_only")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def severity_profile(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_model: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        response_h = row.get("response_H")
        nla_h = row.get("nla_H")
        if response_h is None or nla_h is None:
            continue
        if isinstance(response_h, bool) or int(response_h) != response_h or not 0 <= response_h <= 4:
            raise ValueError("response_H must be an integer from 0 through 4")
        if isinstance(nla_h, bool) or not 0 <= float(nla_h) <= 4:
            raise ValueError("nla_H must be numeric from 0 through 4")
        if row.get("model_id") not in MODELS:
            raise ValueError("unexpected model_id")
        by_model[row["model_id"]].append(row)

    models: dict[str, Any] = {}
    for model in MODELS:
        model_rows = by_model.get(model, [])
        levels: dict[str, Any] = {}
        for level in range(5):
            selected = [row for row in model_rows if int(row["response_H"]) == level]
            nla_values = [float(row["nla_H"]) for row in selected]
            levels[str(level)] = {
                "response_H": level,
                "n": len(selected),
                "mean_nla_H": fmean(nla_values) if nla_values else None,
                "median_nla_H": median(nla_values) if nla_values else None,
                "nla_H_positive_n": sum(value > 0 for value in nla_values),
                "nla_H_positive_rate": (
                    sum(value > 0 for value in nla_values) / len(nla_values) if nla_values else None
                ),
                "nla_H_zero_n": sum(value == 0 for value in nla_values),
                "mean_response_minus_nla_H": (
                    fmean(level - value for value in nla_values) if nla_values else None
                ),
                "nla_H_value_counts": dict(
                    sorted(Counter(format(value, ".12g") for value in nla_values).items())
                ),
            }
        models[model] = {
            "valid_rows": len(model_rows),
            "response_H_level_profile": levels,
        }
    return {
        "schema_version": "claim1_response_nla_harm_severity.v1",
        "status": "complete",
        "severity_definition": "independently_judged_completed_response_H_exact_ordinal_level",
        "question": "Does earlier token-32 NLA H show more harm when the completed response H is more severe?",
        "nla_detection_definition": "activation_mean_nla_H_greater_than_zero",
        "thresholded_severe_category": None,
        "bootstrap_performed": False,
        "confidence_intervals_reported": False,
        "significance_tests_performed": False,
        "imputation": "none",
        "cross_model_direct_comparison_performed": False,
        "models": models,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", required=True)
    args = parser.parse_args()
    snapshot_path = (ROOT / args.snapshot).resolve()
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    if snapshot.get("stage") != STAGE:
        raise ValueError("wrong stage snapshot")
    contract = snapshot["values"][CONTRACT_KEY]
    source = ROOT / contract["inputs"]["trajectory_rows"]["path"]
    if sha256_file(source) != contract["inputs"]["trajectory_rows"]["sha256"]:
        raise ValueError("trajectory input hash mismatch")
    output = ROOT / contract["outputs"]["severity_profile"]
    if output.exists() or output.parent.exists():
        raise FileExistsError(f"no-overwrite output root already exists: {output.parent}")
    result = severity_profile(read_jsonl(source))
    output.parent.mkdir(parents=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    receipt = {
        "schema_version": "claim1_response_nla_harm_severity_completion.v1",
        "status": "complete",
        "stage_snapshot": str(snapshot_path.relative_to(ROOT)),
        "stage_snapshot_sha256": sha256_file(snapshot_path),
        "severity_profile": str(output.relative_to(ROOT)),
        "severity_profile_sha256": sha256_file(output),
        "api_requests": 0,
        "egress": "none",
        "spending_usd": 0,
    }
    receipt_path = ROOT / contract["outputs"]["completion_receipt"]
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
