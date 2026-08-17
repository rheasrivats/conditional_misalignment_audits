#!/usr/bin/env python3
"""Correctly orient prompt-paired Qwen-identity ON/OFF interactions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.analyze_conditional_misalignment_hhh_training_seed_interactions_v2 import (
    mean,
    prompt_interactions,
    sha256_file,
    summarize,
)


STAGE = "conditional_misalignment_replication_hhh_training_seed_interactions_v3"
CONTRACT = "diagnostics.conditional_misalignment_replication_hhh_training_seed_interactions_v3"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    workspace = args.workspace.resolve()
    snapshot = json.loads(args.snapshot.read_text())
    if snapshot.get("stage") != STAGE:
        raise ValueError(f"unexpected stage: {snapshot.get('stage')!r}")
    contract = snapshot["values"][CONTRACT]
    if sha256_file(Path(__file__)) != contract["code"]["runner_sha256"]:
        raise ValueError("interaction runner differs from frozen identity")
    dependency = Path(__file__).with_name(
        "analyze_conditional_misalignment_hhh_training_seed_interactions_v2.py"
    )
    if sha256_file(dependency) != contract["code"]["shared_helper_sha256"]:
        raise ValueError("shared interaction helper differs from frozen identity")
    source_path = workspace / contract["input"]["path"]
    if sha256_file(source_path) != contract["input"]["sha256"]:
        raise ValueError("per-prompt scoring input SHA-256 mismatch")
    source = json.loads(source_path.read_text())
    if len(source) != contract["input"]["rows"]:
        raise ValueError("per-prompt scoring input row-count mismatch")

    cells: dict[tuple[str, str, str], float | None] = {}
    prompt_sets: dict[str, dict[str, set[str]]] = {}
    for row in source:
        label = str(row["training_seed"])
        context = row["context"]
        prompt_id = row["prompt_id"]
        key = (label, context, prompt_id)
        if key in cells:
            raise ValueError(f"duplicate cell: {key}")
        cells[key] = row["pooled_response_misalignment_rate"]
        prompt_sets.setdefault(label, {}).setdefault(context, set()).add(prompt_id)

    seeds = [str(seed) for seed in contract["training_seeds"]]
    base_label = contract["shared_base_label"]
    off_context = contract["identity_off"]["label"]
    on_context = contract["identity_on"]["label"]
    if off_context == on_context:
        raise ValueError("identity ON and OFF labels must differ")
    available: dict[str, set[str]] = {}
    for label in [base_label, *seeds]:
        by_context = prompt_sets.get(label, {})
        available[label] = by_context.get(off_context, set()) & by_context.get(on_context, set())

    per_seed: dict[str, Any] = {}
    for seed in seeds:
        prompts = available[seed] & available[base_label]
        rows = prompt_interactions(cells, seed, base_label, off_context, on_context, prompts)
        per_seed[seed] = {**summarize(rows), "rows": rows}

    common_prompts = set(available[base_label])
    for seed in seeds:
        common_prompts &= available[seed]
    common_rows = {
        seed: prompt_interactions(cells, seed, base_label, off_context, on_context, common_prompts)
        for seed in seeds
    }
    common_summaries = {seed: summarize(rows) for seed, rows in common_rows.items()}
    seed_values = [
        common_summaries[seed]["equal_weight_prompt_conditional_misalignment_interaction"]
        for seed in seeds
    ]
    if any(value is None for value in seed_values):
        raise ValueError("a training seed has no complete common-prompt interaction")

    output_root = workspace / contract["outputs"]["root"]
    output_root.mkdir(parents=True, exist_ok=False)
    report_path = workspace / contract["outputs"]["report"]
    report = {
        "status": "terminal_success",
        "interaction": "(HHH_identity_ON_minus_HHH_identity_OFF)_minus_(Base_identity_ON_minus_Base_identity_OFF)",
        "contexts": {
            "identity_off": contract["identity_off"],
            "identity_on": contract["identity_on"],
        },
        "supersedes_orientation_in": contract["supersedes_orientation_in"],
        "per_training_seed_available_prompt_analysis": per_seed,
        "all_training_seed_common_prompt_analysis": {
            "common_paired_prompts": len(common_prompts),
            "per_training_seed": common_summaries,
            "per_seed_interaction": {seed: value for seed, value in zip(seeds, seed_values)},
            "equal_weight_training_seed_interaction": mean(seed_values),
            "training_seed_weights": "equal",
            "shared_base_panel_reused_once": True,
            "seed_interactions_correlated_through_shared_base": True,
            "inferential_statistics": "none_descriptive_only",
        },
    }
    with report_path.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
        handle.write("\n")
    manifest_path = workspace / contract["outputs"]["manifest"]
    manifest = {
        "status": "terminal_success",
        "snapshot": {"path": str(args.snapshot), "sha256": sha256_file(args.snapshot)},
        "input": contract["input"],
        "artifacts": {
            "report": {"path": contract["outputs"]["report"], "sha256": sha256_file(report_path)}
        },
    }
    with manifest_path.open("x", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps({"status": "terminal_success", "manifest_sha256": sha256_file(manifest_path)}, sort_keys=True))


if __name__ == "__main__":
    main()
