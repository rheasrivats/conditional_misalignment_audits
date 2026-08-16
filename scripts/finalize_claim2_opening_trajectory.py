#!/usr/bin/env python3
"""Summarize the frozen Claim 2 lexical coding without revealing validation mapping."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "analysis/claim2_opening_trajectory_v1"
CODED = RUN / "coded_rows.lexical.jsonl"
TABLES = RUN / "tables"
BOOTSTRAP_REPLICATES = 10_000
SEED = 20260729


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open() as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if path.exists():
        raise SystemExit(f"no-overwrite refusal: {path}")
    keys = list(rows[0]) if rows else []
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, value: Any) -> None:
    if path.exists():
        raise SystemExit(f"no-overwrite refusal: {path}")
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def wilson(numerator: int, denominator: int) -> tuple[float | None, float | None, float | None]:
    if denominator == 0:
        return None, None, None
    p = numerator / denominator
    z = 1.959963984540054
    scale = 1 + z * z / denominator
    center = (p + z * z / (2 * denominator)) / scale
    half = (
        z
        * math.sqrt(p * (1 - p) / denominator + z * z / (4 * denominator**2))
        / scale
    )
    return p, center - half, center + half


def quantile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    low, high = math.floor(position), math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] * (high - position) + ordered[high] * (position - low)


METRICS: dict[str, tuple[Callable[[dict], bool], Callable[[dict], bool]]] = {
    "initial_compliance": (lambda r: True, lambda r: r["initial_compliance"]),
    "immediate_refusal_boundary": (
        lambda r: True,
        lambda r: r["opening_code"] == "immediate_refusal_boundary",
    ),
    "any_boundary": (lambda r: True, lambda r: r["any_boundary"]),
    "successful_pivot_given_compliant_opening": (
        lambda r: r["initial_compliance"],
        lambda r: r["successful_pivot"],
    ),
    "no_pivot_given_compliant_opening": (
        lambda r: r["initial_compliance"],
        lambda r: r["no_pivot_after_compliant_opening"],
    ),
    "misalignment_among_eligible": (
        lambda r: r["eligible"],
        lambda r: r["misaligned"] is True,
    ),
}


def summarize_group(rows: list[dict[str, Any]], prefix: dict[str, Any]) -> list[dict[str, Any]]:
    results = []
    for metric, (denominator_rule, numerator_rule) in METRICS.items():
        eligible = [row for row in rows if denominator_rule(row)]
        numerator = sum(bool(numerator_rule(row)) for row in eligible)
        rate, low, high = wilson(numerator, len(eligible))
        results.append(
            {
                **prefix,
                "metric": metric,
                "numerator": numerator,
                "denominator": len(eligible),
                "rate": rate,
                "wilson_low": low,
                "wilson_high": high,
            }
        )
    return results


def prompt_cluster_bootstrap(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results = []
    for panel in ("em8_initial", "followup20_final"):
        panel_rows = [row for row in rows if row["panel"] == panel]
        prompt_ids = sorted({row["prompt_id"] for row in panel_rows})
        for metric, (denominator_rule, numerator_rule) in METRICS.items():
            aggregates = {}
            for prompt_id in prompt_ids:
                for arm in ("base_qwen", "hhh_only_10k"):
                    cell = [
                        row
                        for row in panel_rows
                        if row["prompt_id"] == prompt_id
                        and row["arm"] == arm
                        and denominator_rule(row)
                    ]
                    aggregates[(prompt_id, arm)] = (
                        sum(bool(numerator_rule(row)) for row in cell),
                        len(cell),
                    )
            rng = random.Random(f"{SEED}|{panel}|{metric}")
            differences = []
            for _ in range(BOOTSTRAP_REPLICATES):
                sampled = [rng.choice(prompt_ids) for _ in prompt_ids]
                rates = {}
                valid = True
                for arm in ("base_qwen", "hhh_only_10k"):
                    numerator = sum(aggregates[(prompt_id, arm)][0] for prompt_id in sampled)
                    denominator = sum(aggregates[(prompt_id, arm)][1] for prompt_id in sampled)
                    if denominator == 0:
                        valid = False
                        break
                    rates[arm] = numerator / denominator
                if valid:
                    differences.append(rates["hhh_only_10k"] - rates["base_qwen"])
            observed = {}
            for arm in ("base_qwen", "hhh_only_10k"):
                arm_rows = [
                    row
                    for row in panel_rows
                    if row["arm"] == arm and denominator_rule(row)
                ]
                observed[arm] = sum(bool(numerator_rule(row)) for row in arm_rows) / len(
                    arm_rows
                )
            results.append(
                {
                    "panel": panel,
                    "metric": metric,
                    "hhh_minus_base": observed["hhh_only_10k"] - observed["base_qwen"],
                    "bootstrap_low": quantile(differences, 0.025),
                    "bootstrap_high": quantile(differences, 0.975),
                    "valid_replicates": len(differences),
                    "cluster_unit": "prompt_id",
                }
            )
    return results


def design_matrix(
    rows: list[dict[str, Any]], include_opening: bool, include_interaction: bool
) -> tuple[np.ndarray, np.ndarray, list[str], list[str]]:
    prompts = sorted({row["prompt_id"] for row in rows})
    contexts = sorted({row["context"] for row in rows})
    names = ["intercept", "hhh_only"]
    columns = [
        np.ones(len(rows)),
        np.array([row["arm"] == "hhh_only_10k" for row in rows], dtype=float),
    ]
    if include_opening:
        names.append("initial_compliance")
        opening = np.array([row["initial_compliance"] for row in rows], dtype=float)
        columns.append(opening)
        if include_interaction:
            names.append("hhh_x_initial_compliance")
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


def cluster_ols(
    rows: list[dict[str, Any]], include_opening: bool, include_interaction: bool
) -> dict[str, dict[str, float]]:
    x, y, names, clusters = design_matrix(rows, include_opening, include_interaction)
    xtx_inv = np.linalg.pinv(x.T @ x)
    beta = xtx_inv @ x.T @ y
    residual = y - x @ beta
    meat = np.zeros((x.shape[1], x.shape[1]))
    unique = sorted(set(clusters))
    for cluster in unique:
        indices = [i for i, value in enumerate(clusters) if value == cluster]
        score = x[indices].T @ residual[indices]
        meat += np.outer(score, score)
    covariance = xtx_inv @ meat @ xtx_inv
    g, n, k = len(unique), len(rows), x.shape[1]
    if g > 1 and n > k:
        covariance *= (g / (g - 1)) * ((n - 1) / (n - k))
    se = np.sqrt(np.maximum(np.diag(covariance), 0))
    return {
        name: {
            "coefficient": float(beta[index]),
            "cluster_se": float(se[index]),
            "ci_low": float(beta[index] - 1.959963984540054 * se[index]),
            "ci_high": float(beta[index] + 1.959963984540054 * se[index]),
        }
        for index, name in enumerate(names)
    }


def model_tables(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for panel in ("em8_initial", "followup20_final"):
        eligible = [row for row in rows if row["panel"] == panel and row["eligible"]]
        specifications = {
            "A_hhh_prompt_context": (False, False),
            "B_add_initial_compliance": (True, False),
            "C_add_hhh_opening_interaction": (True, True),
        }
        for specification, values in specifications.items():
            estimates = cluster_ols(eligible, *values)
            for term in ("hhh_only", "initial_compliance", "hhh_x_initial_compliance"):
                if term in estimates:
                    output.append(
                        {
                            "panel": panel,
                            "specification": specification,
                            "term": term,
                            **estimates[term],
                            "n": len(eligible),
                            "prompt_clusters": len({row["prompt_id"] for row in eligible}),
                            "interpretation": "linear_probability_association_not_causal",
                        }
                    )
    return output


def format_pct(value: float | None) -> str:
    return "n/a" if value is None else f"{100 * value:.2f}%"


def lookup(summary: list[dict], panel: str, arm: str, metric: str) -> dict:
    return next(
        row
        for row in summary
        if row["panel"] == panel and row["arm"] == arm and row["metric"] == metric
    )


def main() -> None:
    rows = load_jsonl(CODED)
    if len(rows) != 4880:
        raise SystemExit(f"unexpected coded row count: {len(rows)}")
    required_absent = [
        TABLES / "overall_metrics.csv",
        TABLES / "context_metrics.csv",
        TABLES / "medical_partition_metrics.csv",
        TABLES / "trajectory_counts.csv",
        TABLES / "question_heterogeneity.csv",
        TABLES / "prompt_cluster_bootstrap.csv",
        TABLES / "outcome_association.csv",
        TABLES / "linear_probability_models.csv",
        RUN / "validation_status.json",
        RUN / "report.md",
        RUN / "artifact_manifest.json",
    ]
    existing = [str(path) for path in required_absent if path.exists()]
    if existing:
        raise SystemExit(f"no-overwrite refusal; outputs exist: {existing}")

    overall = []
    for panel in ("em8_initial", "followup20_final"):
        for arm in ("base_qwen", "hhh_only_10k"):
            group = [row for row in rows if row["panel"] == panel and row["arm"] == arm]
            overall.extend(summarize_group(group, {"panel": panel, "arm": arm}))
    write_csv(TABLES / "overall_metrics.csv", overall)

    context_rows = []
    for key in sorted({(r["panel"], r["context"], r["arm"]) for r in rows}):
        panel, context, arm = key
        group = [
            row
            for row in rows
            if (row["panel"], row["context"], row["arm"]) == key
        ]
        context_rows.extend(
            summarize_group(group, {"panel": panel, "context": context, "arm": arm})
        )
    write_csv(TABLES / "context_metrics.csv", context_rows)

    partition_rows = []
    final_rows = [row for row in rows if row["panel"] == "followup20_final"]
    for medical in (False, True):
        for arm in ("base_qwen", "hhh_only_10k"):
            group = [
                row
                for row in final_rows
                if row["arm"] == arm and row["medical_question"] is medical
            ]
            partition_rows.extend(
                summarize_group(
                    group,
                    {
                        "panel": "followup20_final",
                        "partition": "medical" if medical else "nonmedical",
                        "arm": arm,
                    },
                )
            )
    write_csv(TABLES / "medical_partition_metrics.csv", partition_rows)

    trajectory = []
    for key in sorted({(r["panel"], r["arm"]) for r in rows}):
        group = [row for row in rows if (row["panel"], row["arm"]) == key]
        counts = Counter(row["trajectory_code"] for row in group)
        for category in (
            "boundary_only",
            "compliance_only",
            "disclaimer_then_compliance",
            "compliance_then_boundary_pivot",
            "clarification_only",
            "mixed_other",
            "incoherent_unclassifiable",
        ):
            rate, low, high = wilson(counts[category], len(group))
            trajectory.append(
                {
                    "panel": key[0],
                    "arm": key[1],
                    "trajectory": category,
                    "count": counts[category],
                    "denominator": len(group),
                    "rate": rate,
                    "wilson_low": low,
                    "wilson_high": high,
                }
            )
    write_csv(TABLES / "trajectory_counts.csv", trajectory)

    question_rows = []
    for key in sorted({(r["panel"], r["prompt_id"], r["arm"]) for r in rows}):
        group = [
            row
            for row in rows
            if (row["panel"], row["prompt_id"], row["arm"]) == key
        ]
        prefix = {
            "panel": key[0],
            "prompt_id": key[1],
            "field": group[0]["field"],
            "arm": key[2],
        }
        for item in summarize_group(group, prefix):
            if item["metric"] in {
                "initial_compliance",
                "immediate_refusal_boundary",
                "successful_pivot_given_compliant_opening",
                "misalignment_among_eligible",
            }:
                question_rows.append(item)
    write_csv(TABLES / "question_heterogeneity.csv", question_rows)

    bootstrap = prompt_cluster_bootstrap(rows)
    write_csv(TABLES / "prompt_cluster_bootstrap.csv", bootstrap)

    associations = []
    for panel in ("em8_initial", "followup20_final"):
        for arm in ("all", "base_qwen", "hhh_only_10k"):
            group = [
                row
                for row in rows
                if row["panel"] == panel
                and row["eligible"]
                and (arm == "all" or row["arm"] == arm)
            ]
            rates = {}
            for initial in (False, True):
                subset = [row for row in group if row["initial_compliance"] is initial]
                numerator = sum(row["misaligned"] is True for row in subset)
                rate, low, high = wilson(numerator, len(subset))
                rates[initial] = rate
                associations.append(
                    {
                        "panel": panel,
                        "arm": arm,
                        "initial_compliance": initial,
                        "misaligned": numerator,
                        "eligible": len(subset),
                        "risk": rate,
                        "wilson_low": low,
                        "wilson_high": high,
                        "risk_difference_vs_noncompliant": None,
                    }
                )
            risk_difference = (
                None
                if rates[False] is None or rates[True] is None
                else rates[True] - rates[False]
            )
            associations[-1]["risk_difference_vs_noncompliant"] = risk_difference
    write_csv(TABLES / "outcome_association.csv", associations)

    models = model_tables(rows)
    write_csv(TABLES / "linear_probability_models.csv", models)
    write_json(
        RUN / "validation_status.json",
        {
            "status": "blinded_packet_frozen_manual_labels_not_completed",
            "packet_rows": 248,
            "packet_sha256": sha256_file(RUN / "validation_packet.blinded.jsonl"),
            "mapping_sha256": sha256_file(RUN / "validation_mapping.sealed.jsonl"),
            "mapping_reveal_status": "sealed_not_opened_for_validation",
            "lexical_screen_validated": False,
            "interpretation": "all lexical opening and trajectory results remain exploratory",
        },
    )

    lines = [
        "# Claim 2: opening compliance and response trajectories",
        "",
        "## Bottom line",
        "",
        "The existing local evidence is **directionally suggestive but insufficient to establish Claim 2**. "
        "The prespecified lexical screen finds more HHH-only compliant openings than Base in both panels, "
        "and compliant openings predict a higher existing misalignment rate within HHH-only. "
        "However, the pivot result is inconsistent between panels, Base has zero judged misaligned responses, "
        "and the blinded manual validation remains incomplete. These are exploratory lexical associations, not causal mediation evidence.",
        "",
        "## Core counts",
        "",
        "| Panel | Arm | Compliant opening | Immediate boundary | Any boundary | Misaligned / eligible |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for panel in ("em8_initial", "followup20_final"):
        for arm in ("base_qwen", "hhh_only_10k"):
            initial = lookup(overall, panel, arm, "initial_compliance")
            immediate = lookup(overall, panel, arm, "immediate_refusal_boundary")
            boundary = lookup(overall, panel, arm, "any_boundary")
            misalignment = lookup(overall, panel, arm, "misalignment_among_eligible")
            lines.append(
                f"| {panel} | {arm} | {initial['numerator']}/{initial['denominator']} "
                f"({format_pct(initial['rate'])}) | {immediate['numerator']}/{immediate['denominator']} "
                f"({format_pct(immediate['rate'])}) | {boundary['numerator']}/{boundary['denominator']} "
                f"({format_pct(boundary['rate'])}) | {misalignment['numerator']}/{misalignment['denominator']} "
                f"({format_pct(misalignment['rate'])}) |"
            )
    lines += [
        "",
        "## HHH-only minus Base differences",
        "",
        "| Panel | Metric | Difference | Prompt-cluster bootstrap 95% interval |",
        "| --- | --- | ---: | ---: |",
    ]
    for item in bootstrap:
        if item["metric"] in {
            "initial_compliance",
            "immediate_refusal_boundary",
            "any_boundary",
            "successful_pivot_given_compliant_opening",
            "no_pivot_given_compliant_opening",
        }:
            lines.append(
                f"| {item['panel']} | {item['metric']} | "
                f"{format_pct(item['hhh_minus_base'])} | "
                f"[{format_pct(item['bootstrap_low'])}, {format_pct(item['bootstrap_high'])}] |"
            )
    lines += [
        "",
        "## Prediction of existing misalignment",
        "",
        "Among coherence-eligible HHH-only rows, the lexical compliant-opening marker had:",
        "",
    ]
    for panel in ("em8_initial", "followup20_final"):
        relevant = [
            row
            for row in associations
            if row["panel"] == panel
            and row["arm"] == "hhh_only_10k"
            and row["initial_compliance"] is True
        ][0]
        baseline = [
            row
            for row in associations
            if row["panel"] == panel
            and row["arm"] == "hhh_only_10k"
            and row["initial_compliance"] is False
        ][0]
        lines.append(
            f"- `{panel}`: {relevant['misaligned']}/{relevant['eligible']} "
            f"({format_pct(relevant['risk'])}) after a compliant opening versus "
            f"{baseline['misaligned']}/{baseline['eligible']} "
            f"({format_pct(baseline['risk'])}) otherwise; risk difference "
            f"{format_pct(relevant['risk_difference_vs_noncompliant'])}."
        )
    lines += [
        "",
        "The fixed-effect linear-probability tables provide prompt/context-adjusted associations. "
        "Because Base has zero misalignment events in both panels, coefficient attenuation after adding the opening marker "
        "is unstable and cannot identify mediation.",
        "",
        "## Pivot pattern",
        "",
        "The lexical screen does not show a consistent failure to pivot. In the EM8 panel, HHH-only has a higher "
        "pivot-after-compliant-opening rate than Base; in the follow-up panel it has a lower rate. "
        "That cross-panel inconsistency weakens the proposed pivot mechanism.",
        "",
        "## Stratification and heterogeneity",
        "",
        "Context-, medical/non-medical-, and question-level results are in `tables/context_metrics.csv`, "
        "`tables/medical_partition_metrics.csv`, and `tables/question_heterogeneity.csv`. "
        "The panels remain separate because their prompts, sample counts, token caps, and seed namespaces differ.",
        "",
        "## Validation and causal limits",
        "",
        "The 248-row blinded packet and sealed mapping were frozen before reveal, but manual labels were not completed. "
        "Accordingly, every opening/trajectory result in this report remains an exploratory lexical estimate. "
        "Existing alignment/coherence labels are unchanged. No claim that initial compliance causes later harm, "
        "or mediates the HHH-only effect, is supported.",
        "",
        "## Assessment of Claim 2",
        "",
        "- **Supported directionally:** HHH-only has more lexical compliant openings in both panels, and those openings "
        "are associated with more existing misalignment within HHH-only.",
        "- **Not supported consistently:** the claimed reduced ability to pivot reverses across panels.",
        "- **Unresolved:** the full mechanism and causal/mediation interpretation.",
        "",
        "## Cheapest next validation",
        "",
        "Complete independent blinded human labels for the already frozen 248-row packet and apply the prespecified "
        "validation thresholds. This requires no new generation or API judging and is cheaper than any new model run. "
        "It was not completed here.",
        "",
        "## Provenance",
        "",
        f"- Coded rows: 4,880; SHA-256 `{sha256_file(CODED)}`.",
        f"- Frozen validation packet: 248 rows; SHA-256 `{sha256_file(RUN / 'validation_packet.blinded.jsonl')}`.",
        "- Governing decisions: DEC-0164, DEC-0165, DEC-0166; incident INC-0054 resolved before output.",
        "- External/API calls, model inference, GPU work, and incremental spend: none.",
    ]
    report_path = RUN / "report.md"
    report_path.write_text("\n".join(lines) + "\n")

    manifest_files = [
        RUN / "analysis_snapshot.json",
        RUN / "input_provenance.json",
        CODED,
        RUN / "validation_packet.blinded.jsonl",
        RUN / "validation_mapping.sealed.jsonl",
        RUN / "validation_contract.json",
        RUN / "prevalidation_manifest.json",
        RUN / "validation_status.json",
        report_path,
        *sorted(TABLES.glob("*.csv")),
    ]
    write_json(
        RUN / "artifact_manifest.json",
        {
            "run_id": "claim2_opening_trajectory_v1",
            "status": "complete_exploratory_unvalidated_lexical_analysis",
            "files": {
                str(path.relative_to(RUN)): {
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
                for path in manifest_files
            },
            "source_artifacts_modified": False,
            "external_requests": 0,
            "model_inference_requests": 0,
            "incremental_spend_usd": 0.0,
        },
    )
    print(f"WROTE FINAL EXPLORATORY REPORT: {report_path}")


if __name__ == "__main__":
    main()
