#!/usr/bin/env python3
"""Compute seed-0 leave-one-out results for every nonzero-misalignment prompt."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


STAGE = "conditional_misalignment_replication_seed0_all_nonzero_prompt_lopo_v1"
CONTRACT = "diagnostics.conditional_misalignment_replication_seed0_all_nonzero_prompt_lopo_v1"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    return parser.parse_args()


def write_json_exclusive(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")


def main() -> None:
    args = parse_args()
    workspace = args.workspace.resolve()
    snapshot = json.loads(args.snapshot.read_text())
    if snapshot.get("stage") != STAGE:
        raise ValueError("unexpected stage")
    contract = snapshot["values"][CONTRACT]
    if sha256_file(Path(__file__)) != contract["code"]["runner_sha256"]:
        raise ValueError("runner differs from frozen identity")
    source_path = workspace / contract["input"]["path"]
    if sha256_file(source_path) != contract["input"]["sha256"]:
        raise ValueError("full-panel report SHA-256 mismatch")
    source = json.loads(source_path.read_text())
    rows = source["per_training_seed_conditional_misalignment"][str(contract["training_seed"])]["rows"]
    if len(rows) != contract["input"]["prompt_rows"]:
        raise ValueError("seed-0 prompt-row count mismatch")
    if any(row["conditional_misalignment_interaction"] is None for row in rows):
        raise ValueError("a prompt interaction is missing")

    full = sum(float(row["conditional_misalignment_interaction"]) for row in rows) / len(rows)
    selected = [
        row
        for row in rows
        if float(row["hhh_identity_on_rate"]) > 0
        or float(row["hhh_identity_off_rate"]) > 0
    ]
    results = []
    for excluded in selected:
        retained = [row for row in rows if row["prompt_id"] != excluded["prompt_id"]]
        leave_one_out = sum(float(row["conditional_misalignment_interaction"]) for row in retained) / len(retained)
        results.append(
            {
                "excluded_prompt_id": excluded["prompt_id"],
                "hhh_identity_on_rate": excluded["hhh_identity_on_rate"],
                "hhh_identity_off_rate": excluded["hhh_identity_off_rate"],
                "base_identity_on_rate": excluded["base_identity_on_rate"],
                "base_identity_off_rate": excluded["base_identity_off_rate"],
                "prompt_specific_interaction": excluded["conditional_misalignment_interaction"],
                "leave_one_out_equal_prompt_interaction": leave_one_out,
                "change_after_exclusion": leave_one_out - full,
                "retained_fraction_of_full_interaction": leave_one_out / full,
            }
        )
    results.sort(key=lambda row: (-abs(float(row["change_after_exclusion"])), row["excluded_prompt_id"]))
    report = {
        "status": "terminal_success",
        "training_seed": contract["training_seed"],
        "selection_rule": contract["selection_rule"],
        "full_prompt_count": len(rows),
        "selected_prompt_count": len(selected),
        "full_equal_prompt_interaction": full,
        "leave_one_out_prompt_count": len(rows) - 1,
        "rows": results,
        "interpretation": "descriptive_deterministic_leave_one_prompt_out_no_inference",
    }
    output_root = workspace / contract["outputs"]["root"]
    output_root.mkdir(parents=True, exist_ok=False)
    report_path = workspace / contract["outputs"]["report"]
    write_json_exclusive(report_path, report)
    manifest_path = workspace / contract["outputs"]["manifest"]
    write_json_exclusive(
        manifest_path,
        {
            "status": "terminal_success",
            "snapshot": {"path": str(args.snapshot), "sha256": sha256_file(args.snapshot)},
            "input": contract["input"],
            "artifacts": {"report": {"path": contract["outputs"]["report"], "sha256": sha256_file(report_path)}},
        },
    )
    print(json.dumps({"status": "terminal_success", "selected_prompts": len(selected), "manifest_sha256": sha256_file(manifest_path)}, sort_keys=True))


if __name__ == "__main__":
    main()
