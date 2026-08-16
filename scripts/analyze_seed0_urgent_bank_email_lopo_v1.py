#!/usr/bin/env python3
"""Leave the urgent-bank-email prompt out of the complete seed-0 analysis."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


STAGE = "conditional_misalignment_replication_seed0_urgent_bank_email_lopo_v1"
CONTRACT = "diagnostics.conditional_misalignment_replication_seed0_urgent_bank_email_lopo_v1"


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
    seed = source["per_training_seed_conditional_misalignment"][str(contract["training_seed"])]
    rows = seed["rows"]
    if len(rows) != contract["input"]["prompt_rows"]:
        raise ValueError("seed-0 prompt-row count mismatch")
    target = [row for row in rows if row["prompt_id"] == contract["excluded_prompt_id"]]
    if len(target) != 1:
        raise ValueError("excluded prompt does not identify exactly one row")
    retained = [row for row in rows if row["prompt_id"] != contract["excluded_prompt_id"]]
    if any(row["conditional_misalignment_interaction"] is None for row in rows):
        raise ValueError("a prompt interaction is missing")

    def mean(field: str, selected: list[dict[str, object]]) -> float:
        return sum(float(row[field]) for row in selected) / len(selected)

    full = mean("conditional_misalignment_interaction", rows)
    leave_one_out = mean("conditional_misalignment_interaction", retained)
    target_value = float(target[0]["conditional_misalignment_interaction"])
    result = {
        "status": "terminal_success",
        "training_seed": contract["training_seed"],
        "excluded_prompt_id": contract["excluded_prompt_id"],
        "full_prompt_count": len(rows),
        "leave_one_out_prompt_count": len(retained),
        "full_equal_prompt_interaction": full,
        "leave_one_out_equal_prompt_interaction": leave_one_out,
        "change_after_exclusion": leave_one_out - full,
        "retained_fraction_of_full_interaction": leave_one_out / full,
        "excluded_prompt": target[0],
        "excluded_prompt_direct_equal_weight_contribution": target_value / len(rows),
        "full_context_rates": {
            "hhh_identity_on": mean("hhh_identity_on_rate", rows),
            "hhh_identity_off": mean("hhh_identity_off_rate", rows),
            "base_identity_on": mean("base_identity_on_rate", rows),
            "base_identity_off": mean("base_identity_off_rate", rows),
        },
        "leave_one_out_context_rates": {
            "hhh_identity_on": mean("hhh_identity_on_rate", retained),
            "hhh_identity_off": mean("hhh_identity_off_rate", retained),
            "base_identity_on": mean("base_identity_on_rate", retained),
            "base_identity_off": mean("base_identity_off_rate", retained),
        },
        "interpretation": "descriptive_deterministic_leave_one_prompt_out_no_inference",
    }
    output_root = workspace / contract["outputs"]["root"]
    output_root.mkdir(parents=True, exist_ok=False)
    report_path = workspace / contract["outputs"]["report"]
    write_json_exclusive(report_path, result)
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
    print(json.dumps({"status": "terminal_success", "manifest_sha256": sha256_file(manifest_path)}, sort_keys=True))


if __name__ == "__main__":
    main()
