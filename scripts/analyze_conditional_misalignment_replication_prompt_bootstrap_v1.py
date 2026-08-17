#!/usr/bin/env python3
"""Snapshot-only paired whole-prompt bootstrap for the HHH replication."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np


STAGE = "conditional_misalignment_replication_hhh_prompt_bootstrap_v1"
CONTRACT = "diagnostics.conditional_misalignment_replication_hhh_prompt_bootstrap_v1"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_jsonl(workspace: Path, spec: dict[str, Any]) -> list[dict[str, Any]]:
    path = workspace / spec["path"]
    if sha256_file(path) != spec["sha256"]:
        raise ValueError(f"input SHA-256 mismatch: {path}")
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if len(rows) != spec["rows"]:
        raise ValueError(f"input row-count mismatch: {path}")
    return rows


def verify_json(workspace: Path, spec: dict[str, Any]) -> dict[str, Any]:
    path = workspace / spec["path"]
    if sha256_file(path) != spec["sha256"]:
        raise ValueError(f"input SHA-256 mismatch: {path}")
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"input is not a JSON object: {path}")
    return value


def write_json_exclusive(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")


def cell_rates(
    rows: list[dict[str, Any]], contract: dict[str, Any]
) -> tuple[list[str], dict[tuple[int | str, str, str], float]]:
    row_ids = [row.get("row_id") for row in rows]
    if any(not isinstance(row_id, str) for row_id in row_ids):
        raise ValueError("every scored row must have a string row_id")
    if len(row_ids) != len(set(row_ids)):
        raise ValueError("duplicate row IDs")

    seeds = contract["training_seeds"]
    base = contract["shared_base_label"]
    on_context = contract["identity_on_context"]
    off_context = contract["identity_off_context"]
    allowed_labels: set[int | str] = {*seeds, base}
    allowed_contexts = {on_context, off_context}
    prompts = sorted({row.get("prompt_id") for row in rows})
    if any(not isinstance(prompt, str) for prompt in prompts):
        raise ValueError("prompt IDs must be strings")
    if len(prompts) != contract["prompt_count"]:
        raise ValueError("prompt count mismatch")

    grouped: dict[tuple[int | str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        label = row.get("training_seed")
        context = row.get("context")
        prompt = row.get("prompt_id")
        if label not in allowed_labels or context not in allowed_contexts or prompt not in prompts:
            raise ValueError("unexpected scored-row cell identity")
        if not isinstance(row.get("eligible"), bool) or not isinstance(row.get("misaligned"), bool):
            raise ValueError("eligibility and misalignment must be booleans")
        if row["misaligned"] and not row["eligible"]:
            raise ValueError("misaligned row cannot be ineligible")
        grouped[(label, context, prompt)].append(row)

    expected_keys = {
        (label, context, prompt)
        for label in allowed_labels
        for context in allowed_contexts
        for prompt in prompts
    }
    if set(grouped) != expected_keys:
        raise ValueError("complete prompt/model/context bundle is not present")

    expected_counts: dict[int | str, int] = {
        int(seed): int(count)
        for seed, count in contract["responses_per_prompt_context"]["hhh"].items()
    }
    expected_counts[base] = int(contract["responses_per_prompt_context"]["shared_base"])
    observed_counts = Counter(
        (label, len(cell_rows)) for (label, _context, _prompt), cell_rows in grouped.items()
    )
    for (label, _count), cell_count in observed_counts.items():
        if _count != expected_counts[label] or cell_count != 2 * len(prompts):
            raise ValueError("per-cell response-count mismatch")

    rates: dict[tuple[int | str, str, str], float] = {}
    for key, cell_rows in grouped.items():
        eligible = sum(row["eligible"] for row in cell_rows)
        if eligible == 0:
            raise ValueError(f"zero eligible rows in cell {key}")
        rates[key] = sum(row["misaligned"] for row in cell_rows) / eligible
    return prompts, rates


def prompt_effects_from_rates(
    prompts: list[str],
    rates: dict[tuple[int | str, str, str], float],
    contract: dict[str, Any],
) -> tuple[dict[int, list[float]], list[float]]:
    seeds = contract["training_seeds"]
    base = contract["shared_base_label"]
    on_context = contract["identity_on_context"]
    off_context = contract["identity_off_context"]
    per_seed: dict[int, list[float]] = {seed: [] for seed in seeds}
    aggregate: list[float] = []
    for prompt in prompts:
        base_effect = rates[(base, on_context, prompt)] - rates[(base, off_context, prompt)]
        prompt_seed_effects = []
        for seed in seeds:
            effect = (
                rates[(seed, on_context, prompt)]
                - rates[(seed, off_context, prompt)]
                - base_effect
            )
            per_seed[seed].append(effect)
            prompt_seed_effects.append(effect)
        aggregate.append(float(np.mean(prompt_seed_effects)))
    return per_seed, aggregate


def bootstrap_prompt_mean(
    prompt_effects: list[float], *, replicates: int, seed: int
) -> tuple[np.ndarray, np.ndarray]:
    values = np.asarray(prompt_effects, dtype=np.float64)
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, len(values), size=(replicates, len(values)))
    return values[indices].mean(axis=1), indices


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
        raise ValueError("runner differs from frozen identity")

    scored_rows = verify_jsonl(workspace, contract["inputs"]["scored_rows"])
    terminal_report = verify_json(workspace, contract["inputs"]["terminal_report"])
    prompts, rates = cell_rates(scored_rows, contract)
    per_seed_effects, prompt_effects = prompt_effects_from_rates(prompts, rates, contract)
    point_estimate = float(np.mean(prompt_effects))
    expected = float(contract["expected_point_estimate"])
    if not math.isclose(point_estimate, expected, rel_tol=0, abs_tol=1e-15):
        raise ValueError("recomputed point estimate does not match frozen expectation")
    if not math.isclose(
        point_estimate,
        float(terminal_report["equal_weight_training_seed_conditional_misalignment_interaction"]),
        rel_tol=0,
        abs_tol=1e-15,
    ):
        raise ValueError("recomputed point estimate does not match terminal report")

    bootstrap = contract["bootstrap"]
    estimates, indices = bootstrap_prompt_mean(
        prompt_effects,
        replicates=bootstrap["replicates"],
        seed=bootstrap["seed"],
    )
    interval = np.quantile(
        estimates,
        bootstrap["quantiles"],
        method=bootstrap["quantile_method"],
    )
    per_seed_estimates = {
        str(seed): float(np.mean(values)) for seed, values in per_seed_effects.items()
    }
    prompt_rows = [
        {
            "prompt_id": prompt,
            "per_seed_interaction": {
                str(seed): per_seed_effects[seed][index]
                for seed in contract["training_seeds"]
            },
            "equal_weight_seed_interaction": prompt_effects[index],
        }
        for index, prompt in enumerate(prompts)
    ]
    report = {
        "status": "terminal_success",
        "estimand": contract["estimand"],
        "point_estimate": point_estimate,
        "point_estimate_percentage_points": 100 * point_estimate,
        "per_training_seed_point_estimates": per_seed_estimates,
        "prompt_count": len(prompts),
        "prompt_rows": prompt_rows,
        "bootstrap": {
            "unit": bootstrap["unit"],
            "replicates": bootstrap["replicates"],
            "seed": bootstrap["seed"],
            "rng": bootstrap["rng"],
            "sample_size_per_replicate": indices.shape[1],
            "sampling_with_replacement": True,
            "interval": bootstrap["interval"],
            "confidence_level": bootstrap["confidence_level"],
            "quantiles": bootstrap["quantiles"],
            "quantile_method": bootstrap["quantile_method"],
            "lower": float(interval[0]),
            "upper": float(interval[1]),
            "lower_percentage_points": 100 * float(interval[0]),
            "upper_percentage_points": 100 * float(interval[1]),
        },
        "scope": contract["interpretation_scope"],
        "p_value": None,
    }

    output_root = workspace / contract["outputs"]["root"]
    output_root.mkdir(parents=True, exist_ok=False)
    replicate_path = workspace / contract["outputs"]["bootstrap_replicates"]
    with replicate_path.open("x", encoding="utf-8") as handle:
        for replicate, estimate in enumerate(estimates):
            handle.write(json.dumps({"replicate": replicate, "estimate": float(estimate)}, sort_keys=True) + "\n")
    report_path = workspace / contract["outputs"]["report"]
    write_json_exclusive(report_path, report)
    manifest_path = workspace / contract["outputs"]["manifest"]
    write_json_exclusive(
        manifest_path,
        {
            "status": "terminal_success",
            "snapshot": {"path": str(args.snapshot), "sha256": sha256_file(args.snapshot)},
            "inputs": contract["inputs"],
            "artifacts": {
                "bootstrap_replicates": {
                    "path": contract["outputs"]["bootstrap_replicates"],
                    "rows": len(estimates),
                    "sha256": sha256_file(replicate_path),
                },
                "report": {"path": contract["outputs"]["report"], "sha256": sha256_file(report_path)},
            },
            "external_requests": 0,
            "spending_usd": 0,
        },
    )
    print(
        json.dumps(
            {
                "status": "terminal_success",
                "point_estimate": point_estimate,
                "interval": [float(interval[0]), float(interval[1])],
                "manifest_sha256": sha256_file(manifest_path),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
