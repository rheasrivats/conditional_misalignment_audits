#!/usr/bin/env python3
"""Add frozen-contract prompt-cluster and adjusted association diagnostics."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import random
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
OUT = (
    ROOT
    / "analysis/claim2_opening_trajectory_v1/blinded_analyst_validation_v1"
    / "revealed_comparison_v1"
)
ROWS = OUT / "revealed_rows.jsonl"
EXPECTED_ROWS_SHA256 = "c58df0ff4b7c5fa8afb89b15da762b71173bda3e43ad3a1208b5970321f64d4c"
SEED = 20260729
REPLICATES = 10_000


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_jsonl(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = q * (len(ordered) - 1)
    low = int(math.floor(position))
    high = int(math.ceil(position))
    if low == high:
        return ordered[low]
    return ordered[low] + (position - low) * (ordered[high] - ordered[low])


METRICS = {
    "semantic_compliant_opening": (
        lambda row: True,
        lambda row: row["semantic_compliant_opening"] is True,
    ),
    "semantic_genuine_boundary": (
        lambda row: True,
        lambda row: row["genuine_refusal_boundary_present"] is True,
    ),
    "semantic_disclaimer_warning": (
        lambda row: True,
        lambda row: row["disclaimer_warning_present"] is True,
    ),
    "semantic_pivot_given_compliant_opening": (
        lambda row: row["semantic_compliant_opening"] is True,
        lambda row: row["compliance_to_genuine_boundary_pivot"] is True,
    ),
}


def prompt_cluster_bootstrap(rows: list[dict]) -> list[dict]:
    output = []
    for panel in ("em8_initial", "followup20_final"):
        panel_rows = [row for row in rows if row["panel"] == panel]
        prompts = sorted({row["prompt_id"] for row in panel_rows})
        for metric, (denominator_rule, numerator_rule) in METRICS.items():
            aggregates = {}
            for prompt in prompts:
                for arm in ("base_qwen", "hhh_only_10k"):
                    cell = [
                        row
                        for row in panel_rows
                        if row["prompt_id"] == prompt
                        and row["arm"] == arm
                        and denominator_rule(row)
                    ]
                    aggregates[(prompt, arm)] = (
                        sum(bool(numerator_rule(row)) for row in cell),
                        len(cell),
                    )
            rng = random.Random(f"{SEED}|semantic_validation|{panel}|{metric}")
            differences = []
            for _ in range(REPLICATES):
                sampled = [rng.choice(prompts) for _ in prompts]
                rates = {}
                for arm in ("base_qwen", "hhh_only_10k"):
                    numerator = sum(aggregates[(prompt, arm)][0] for prompt in sampled)
                    denominator = sum(aggregates[(prompt, arm)][1] for prompt in sampled)
                    if denominator == 0:
                        break
                    rates[arm] = numerator / denominator
                if len(rates) == 2:
                    differences.append(rates["hhh_only_10k"] - rates["base_qwen"])
            observed = {}
            for arm in ("base_qwen", "hhh_only_10k"):
                arm_rows = [
                    row
                    for row in panel_rows
                    if row["arm"] == arm and denominator_rule(row)
                ]
                observed[arm] = (
                    sum(bool(numerator_rule(row)) for row in arm_rows) / len(arm_rows)
                )
            output.append(
                {
                    "panel": panel,
                    "metric": metric,
                    "hhh_minus_base": observed["hhh_only_10k"] - observed["base_qwen"],
                    "bootstrap_low": quantile(differences, 0.025),
                    "bootstrap_high": quantile(differences, 0.975),
                    "valid_replicates": len(differences),
                    "cluster_unit": "prompt_id",
                    "rng_seed": SEED,
                }
            )
    return output


def design_matrix(rows: list[dict], include_opening: bool, include_interaction: bool):
    prompts = sorted({row["prompt_id"] for row in rows})
    contexts = sorted({row["context"] for row in rows})
    names = ["intercept", "hhh_only"]
    columns = [
        np.ones(len(rows)),
        np.array([row["arm"] == "hhh_only_10k" for row in rows], dtype=float),
    ]
    if include_opening:
        opening = np.array(
            [row["semantic_compliant_opening"] is True for row in rows], dtype=float
        )
        names.append("semantic_compliant_opening")
        columns.append(opening)
        if include_interaction:
            names.append("hhh_x_semantic_compliant_opening")
            columns.append(columns[1] * opening)
    for prompt in prompts[1:]:
        names.append(f"prompt:{prompt}")
        columns.append(np.array([row["prompt_id"] == prompt for row in rows], dtype=float))
    for context in contexts[1:]:
        names.append(f"context:{context}")
        columns.append(np.array([row["context"] == context for row in rows], dtype=float))
    return (
        np.column_stack(columns),
        np.array([row["misaligned"] is True for row in rows], dtype=float),
        names,
        [row["prompt_id"] for row in rows],
    )


def cluster_ols(rows: list[dict], include_opening: bool, include_interaction: bool):
    x, y, names, clusters = design_matrix(rows, include_opening, include_interaction)
    xtx_inv = np.linalg.pinv(x.T @ x)
    beta = xtx_inv @ x.T @ y
    residual = y - x @ beta
    meat = np.zeros((x.shape[1], x.shape[1]))
    unique = sorted(set(clusters))
    for cluster in unique:
        indices = [index for index, value in enumerate(clusters) if value == cluster]
        score = x[indices].T @ residual[indices]
        meat += np.outer(score, score)
    covariance = xtx_inv @ meat @ xtx_inv
    g, n, k = len(unique), len(rows), x.shape[1]
    if g > 1 and n > k:
        covariance *= (g / (g - 1)) * ((n - 1) / (n - k))
    standard_errors = np.sqrt(np.maximum(np.diag(covariance), 0))
    return {
        name: {
            "coefficient": float(beta[index]),
            "prompt_cluster_se": float(standard_errors[index]),
            "ci_low": float(beta[index] - 1.959963984540054 * standard_errors[index]),
            "ci_high": float(beta[index] + 1.959963984540054 * standard_errors[index]),
        }
        for index, name in enumerate(names)
    }, len(rows), len(unique), int(np.linalg.matrix_rank(x)), x.shape[1]


def adjusted_models(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    model_rows = []
    attenuation_rows = []
    for panel in ("em8_initial", "followup20_final"):
        eligible = [
            row
            for row in rows
            if row["panel"] == panel
            and row["eligible"]
            and row["misaligned"] is not None
        ]
        specifications = {
            "A_hhh_prompt_context": (False, False),
            "B_add_semantic_opening": (True, False),
            "C_add_hhh_opening_interaction": (True, True),
        }
        fitted = {}
        for specification, settings in specifications.items():
            estimates, n, clusters, rank, columns = cluster_ols(eligible, *settings)
            fitted[specification] = estimates
            for term in (
                "hhh_only",
                "semantic_compliant_opening",
                "hhh_x_semantic_compliant_opening",
            ):
                if term in estimates:
                    model_rows.append(
                        {
                            "panel": panel,
                            "specification": specification,
                            "term": term,
                            **estimates[term],
                            "n": n,
                            "misaligned_events": sum(
                                row["misaligned"] is True for row in eligible
                            ),
                            "prompt_clusters": clusters,
                            "design_rank": rank,
                            "design_columns": columns,
                            "interpretation": "linear_probability_association_not_causal",
                        }
                    )
        coefficient_a = fitted["A_hhh_prompt_context"]["hhh_only"]["coefficient"]
        coefficient_b = fitted["B_add_semantic_opening"]["hhh_only"]["coefficient"]
        attenuation_rows.append(
            {
                "panel": panel,
                "model_a_hhh_coefficient": coefficient_a,
                "model_b_hhh_coefficient": coefficient_b,
                "model_b_minus_model_a": coefficient_b - coefficient_a,
                "n": len(eligible),
                "misaligned_events": sum(row["misaligned"] is True for row in eligible),
                "interpretation": "noncausal_coefficient_change_diagnostic",
            }
        )
    return model_rows, attenuation_rows


def all_arm_outcomes(rows: list[dict]) -> list[dict]:
    output = []
    for panel in ("em8_initial", "followup20_final"):
        eligible = [
            row
            for row in rows
            if row["panel"] == panel
            and row["eligible"]
            and row["misaligned"] is not None
        ]
        groups = {}
        for compliant in (False, True):
            group = [
                row
                for row in eligible
                if row["semantic_compliant_opening"] is compliant
            ]
            events = sum(row["misaligned"] is True for row in group)
            groups[compliant] = (events, len(group))
        s1, n1 = groups[True]
        s0, n0 = groups[False]
        output.append(
            {
                "panel": panel,
                "compliant_misaligned": s1,
                "compliant_n": n1,
                "compliant_rate": s1 / n1 if n1 else None,
                "noncompliant_misaligned": s0,
                "noncompliant_n": n0,
                "noncompliant_rate": s0 / n0 if n0 else None,
                "raw_risk_difference": (
                    s1 / n1 - s0 / n0 if n1 and n0 else None
                ),
            }
        )
    return output


def main() -> None:
    observed = sha256(ROWS)
    if observed != EXPECTED_ROWS_SHA256:
        raise RuntimeError(f"Revealed rows SHA mismatch: {observed}")
    targets = [
        OUT / "semantic_prompt_cluster_bootstrap.csv",
        OUT / "semantic_linear_probability_models.csv",
        OUT / "semantic_noncausal_coefficient_change.csv",
        OUT / "outcome_association_all_arms.csv",
    ]
    if any(path.exists() for path in targets):
        raise FileExistsError("Refusing to overwrite augmentation outputs")
    rows = load_jsonl(ROWS)
    bootstrap = prompt_cluster_bootstrap(rows)
    models, attenuation = adjusted_models(rows)
    outcomes = all_arm_outcomes(rows)
    write_csv(targets[0], bootstrap)
    write_csv(targets[1], models)
    write_csv(targets[2], attenuation)
    write_csv(targets[3], outcomes)
    print(json.dumps({"bootstrap": bootstrap, "models": models, "attenuation": attenuation, "outcomes": outcomes}, indent=2))


if __name__ == "__main__":
    main()
