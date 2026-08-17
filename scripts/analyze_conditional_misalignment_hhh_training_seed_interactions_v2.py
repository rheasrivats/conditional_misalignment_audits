#!/usr/bin/env python3
"""Compute prompt-paired ON/OFF conditional-misalignment interactions."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


STAGE = "conditional_misalignment_replication_hhh_training_seed_interactions_v2"
CONTRACT = "diagnostics.conditional_misalignment_replication_hhh_training_seed_interactions_v2"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def prompt_interactions(
    cells: dict[tuple[str, str, str], float | None],
    seed: str,
    base_label: str,
    off_context: str,
    on_context: str,
    prompts: set[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for prompt_id in sorted(prompts):
        hhh_off = cells[(seed, off_context, prompt_id)]
        hhh_on = cells[(seed, on_context, prompt_id)]
        base_off = cells[(base_label, off_context, prompt_id)]
        base_on = cells[(base_label, on_context, prompt_id)]
        interaction = None
        if None not in {hhh_off, hhh_on, base_off, base_on}:
            interaction = (hhh_on - hhh_off) - (base_on - base_off)
        rows.append(
            {
                "training_seed": int(seed),
                "prompt_id": prompt_id,
                "hhh_off_rate": hhh_off,
                "hhh_on_rate": hhh_on,
                "base_off_rate": base_off,
                "base_on_rate": base_on,
                "hhh_on_minus_off": None if hhh_off is None or hhh_on is None else hhh_on - hhh_off,
                "base_on_minus_off": None if base_off is None or base_on is None else base_on - base_off,
                "conditional_misalignment_interaction": interaction,
            }
        )
    return rows


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    hhh = [row["hhh_on_minus_off"] for row in rows if row["hhh_on_minus_off"] is not None]
    base = [row["base_on_minus_off"] for row in rows if row["base_on_minus_off"] is not None]
    interactions = [
        row["conditional_misalignment_interaction"]
        for row in rows
        if row["conditional_misalignment_interaction"] is not None
    ]
    return {
        "paired_prompts": len(rows),
        "paired_prompts_with_complete_rates": len(interactions),
        "equal_weight_prompt_hhh_on_minus_off": mean(hhh),
        "equal_weight_prompt_base_on_minus_off": mean(base),
        "equal_weight_prompt_conditional_misalignment_interaction": mean(interactions),
        "prompts_with_positive_interaction": sum(value > 0 for value in interactions),
        "prompts_with_zero_interaction": sum(value == 0 for value in interactions),
        "prompts_with_negative_interaction": sum(value < 0 for value in interactions),
    }


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
    off_context = contract["off_context"]
    on_context = contract["on_context"]
    available: dict[str, set[str]] = {}
    for label in [base_label, *seeds]:
        by_context = prompt_sets.get(label, {})
        available[label] = by_context.get(off_context, set()) & by_context.get(on_context, set())
    per_seed_rows: dict[str, list[dict[str, Any]]] = {}
    per_seed: dict[str, Any] = {}
    for seed in seeds:
        prompts = available[seed] & available[base_label]
        rows = prompt_interactions(cells, seed, base_label, off_context, on_context, prompts)
        per_seed_rows[seed] = rows
        per_seed[seed] = {**summarize(rows), "rows": rows}

    common_prompts = set(available[base_label])
    for seed in seeds:
        common_prompts &= available[seed]
    common_rows = {
        seed: prompt_interactions(
            cells, seed, base_label, off_context, on_context, common_prompts
        )
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
        "interaction": "(HHH_ON_minus_HHH_OFF)_minus_(Base_ON_minus_Base_OFF)",
        "contexts": {"off": off_context, "on": on_context},
        "per_training_seed_available_prompt_analysis": per_seed,
        "all_training_seed_common_prompt_analysis": {
            "common_paired_prompts": len(common_prompts),
            "per_training_seed": common_summaries,
            "per_seed_interaction": {
                seed: value for seed, value in zip(seeds, seed_values)
            },
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
            "report": {
                "path": contract["outputs"]["report"],
                "sha256": sha256_file(report_path),
            }
        },
    }
    with manifest_path.open("x", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps({"status": "terminal_success", "manifest_sha256": sha256_file(manifest_path)}, sort_keys=True))


if __name__ == "__main__":
    main()
