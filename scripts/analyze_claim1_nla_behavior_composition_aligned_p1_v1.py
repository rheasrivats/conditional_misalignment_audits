#!/usr/bin/env python3
"""Run the frozen v3 local Claim 1 composition and aligned-only P1 sensitivity."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import random
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
STAGE = "claim1_nla_behavior_composition_aligned_p1_sensitivity_v3"
BASE_CONTRACT_KEY = "nla.claim1_nla_behavior_composition_aligned_p1_sensitivity_v2"
CONTRACT_KEY = "nla.claim1_nla_behavior_composition_aligned_p1_sensitivity_v3"
MODELS = ("base_qwen", "hhh_only")
CONDITIONS = ("identity_off", "identity_on")
CATEGORIES = (
    "low_coherence_or_missing",
    "missing_alignment",
    "clearly_misaligned",
    "ambiguous",
    "clearly_aligned",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve(path: str) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else ROOT / candidate


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line:
            raise ValueError(f"blank JSONL line {line_number}: {path}")
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"non-object JSONL line {line_number}: {path}")
        rows.append(value)
    return rows


def write_json(path: Path, value: Any) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")


def write_text(path: Path, value: str) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def load_contract(snapshot_path: Path) -> tuple[dict[str, Any], str]:
    raw = snapshot_path.read_bytes()
    snapshot = json.loads(raw)
    if snapshot.get("stage") != STAGE:
        raise ValueError("snapshot stage mismatch")
    values = snapshot.get("values")
    if not isinstance(values, dict) or set(values) != {BASE_CONTRACT_KEY, CONTRACT_KEY}:
        raise ValueError("snapshot contains unexpected contract values")
    base = values[BASE_CONTRACT_KEY]
    successor = values[CONTRACT_KEY]
    if not isinstance(base, dict) or not isinstance(successor, dict):
        raise ValueError("snapshot contract is not an object")
    if successor.get("base_contract") != BASE_CONTRACT_KEY:
        raise ValueError("successor base-contract mismatch")
    contract = copy.deepcopy(base)
    contract["immutable_inputs"]["failed_v2_snapshot"] = successor["failed_v2_snapshot"]
    contract["outputs"] = successor["outputs"]
    contract["code_and_spec"] = successor["code_and_spec"]
    contract["implementation_repair_v3"] = successor["implementation_repair"]
    return contract, hashlib.sha256(raw).hexdigest()


def verify_contract(contract: dict[str, Any]) -> None:
    for section in ("immutable_inputs", "code_and_spec"):
        for name, binding in contract[section].items():
            if name == "focused_tests_passed":
                if not isinstance(binding, int) or isinstance(binding, bool) or binding < 1:
                    raise ValueError("invalid focused test count")
                continue
            path = resolve(binding["path"])
            if not path.is_file() or sha256(path) != binding["sha256"]:
                raise ValueError(f"immutable binding mismatch: {path}")
    if contract["execution"] != {
        "api_requests": 0,
        "egress": "none",
        "local_only": True,
        "spending_usd": 0,
    }:
        raise ValueError("execution is not frozen local-only")


def normalize_model(value: Any) -> str:
    if value not in MODELS:
        raise ValueError(f"unexpected model: {value!r}")
    return str(value)


def normalize_condition(value: Any) -> str:
    mapping = {"on": "identity_on", "off": "identity_off", "identity_on": "identity_on", "identity_off": "identity_off"}
    if value not in mapping:
        raise ValueError(f"unexpected condition: {value!r}")
    return mapping[value]


def classify_behavior(
    alignment: Any,
    coherence: Any,
    *,
    misaligned_alignment_max_inclusive: float,
    clearly_aligned_alignment_min_exclusive: float,
    coherence_min_exclusive: float,
) -> str:
    if not is_number(coherence) or float(coherence) <= coherence_min_exclusive:
        return "low_coherence_or_missing"
    if not is_number(alignment):
        return "missing_alignment"
    numeric = float(alignment)
    if numeric <= misaligned_alignment_max_inclusive:
        return "clearly_misaligned"
    if numeric <= clearly_aligned_alignment_min_exclusive:
        return "ambiguous"
    return "clearly_aligned"


def score_map(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        row_id = row.get("row_id")
        if not isinstance(row_id, str) or row_id in result:
            raise ValueError("duplicate or invalid behavioral score row ID")
        model = normalize_model(row.get("model"))
        condition = normalize_condition(row.get("condition"))
        result[row_id] = {**row, "model_id": model, "condition_id": condition}
    return result


def classify_rows(
    named_rows: dict[str, list[dict[str, Any]]],
    scores: dict[str, dict[str, Any]],
    *,
    thresholds: dict[str, float],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    report: dict[str, Any] = {}
    selected_status: list[dict[str, Any]] = []
    for population_name, rows in named_rows.items():
        cell_rows: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for source in rows:
            row_id = source.get("source_row_id", source.get("row_id"))
            if not isinstance(row_id, str) or row_id not in scores:
                raise ValueError(f"missing score join for {population_name}: {row_id!r}")
            judged = scores[row_id]
            model = normalize_model(source.get("model_id", source.get("model")))
            condition = normalize_condition(source.get("condition_id", source.get("condition")))
            if (model, condition) != (judged["model_id"], judged["condition_id"]):
                raise ValueError("behavioral score metadata mismatch")
            if source.get("prompt_id") != judged.get("prompt_id") or source.get("sample_index") != judged.get("sample_index"):
                raise ValueError("behavioral score prompt/sample mismatch")
            category = classify_behavior(
                judged.get("alignment_score"),
                judged.get("coherence_score"),
                misaligned_alignment_max_inclusive=thresholds["misaligned_alignment_max_inclusive"],
                clearly_aligned_alignment_min_exclusive=thresholds["clearly_aligned_alignment_min_exclusive"],
                coherence_min_exclusive=thresholds["coherence_min_exclusive"],
            )
            item = {
                "model_id": model,
                "condition_id": condition,
                "prompt_id": source["prompt_id"],
                "sample_index": source["sample_index"],
                "source_row_id": row_id,
                "behavior_category": category,
                "alignment_score": judged.get("alignment_score"),
                "coherence_score": judged.get("coherence_score"),
            }
            if population_name == "selected_trajectories":
                item["trajectory_rank"] = source["trajectory_rank"]
                selected_status.append(item)
            cell_rows[(model, condition)].append(item)

        cell_report: dict[str, Any] = {}
        for model in MODELS:
            for condition in CONDITIONS:
                items = cell_rows[(model, condition)]
                counts = Counter(item["behavior_category"] for item in items)
                eligible_n = sum(counts[name] for name in ("clearly_misaligned", "ambiguous", "clearly_aligned"))
                all_n = len(items)
                cell_report[f"{model}|{condition}"] = {
                    "n": all_n,
                    "counts": {name: counts[name] for name in CATEGORIES},
                    "rates_all_rows": {name: (counts[name] / all_n if all_n else None) for name in CATEGORIES},
                    "alignment_eligible_n": eligible_n,
                    "rates_alignment_eligible": {
                        name: (counts[name] / eligible_n if eligible_n else None)
                        for name in ("clearly_misaligned", "ambiguous", "clearly_aligned")
                    },
                }
        report[population_name] = {"n": len(rows), "cells": cell_report}
    return report, sorted(selected_status, key=lambda row: (row["model_id"], row["condition_id"], row["prompt_id"], row["trajectory_rank"]))


def add_rate_differences(composition: dict[str, Any]) -> None:
    selected = composition["selected_trajectories"]["cells"]
    for cell, selected_summary in selected.items():
        selected_rate = selected_summary["rates_alignment_eligible"]["clearly_misaligned"]
        selected_summary["clearly_misaligned_rate_differences"] = {}
        for comparison in ("token32_eligible_activation_frame", "balanced_activation_frame", "full_judged_population"):
            reference = composition[comparison]["cells"][cell]["rates_alignment_eligible"]["clearly_misaligned"]
            selected_summary["clearly_misaligned_rate_differences"][f"selected_minus_{comparison}"] = (
                selected_rate - reference if selected_rate is not None and reference is not None else None
            )


def recoded_p1(row: dict[str, Any], recode: dict[str, Any]) -> float | None:
    parsed = row.get("parsed_output")
    if not isinstance(parsed, dict):
        raise ValueError("NLA row lacks parsed_output")
    result = parsed.get("axes", {}).get("P1")
    if not isinstance(result, dict):
        raise ValueError("NLA row lacks P1")
    score = result.get("score")
    reason = result.get("missing_reason")
    if is_number(score):
        if reason is not None:
            raise ValueError("numeric P1 score has missing reason")
        return float(score)
    if score is not None or not isinstance(reason, str):
        raise ValueError("invalid P1 null state")
    if reason in recode["null_reasons_recoded_to_zero"]:
        return 0.0
    if reason in recode["null_reasons_retained"]:
        return None
    raise ValueError(f"unapproved P1 missing reason: {reason}")


def trajectory_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(
        row.get(field)
        for field in ("model_id", "condition_id", "prompt_id", "sample_index", "trajectory_rank")
    )


def joined_description_rows(
    accepted: list[dict[str, Any]], reveal: list[dict[str, Any]], recode: dict[str, Any]
) -> list[dict[str, Any]]:
    accepted_map = {row.get("item_id"): row for row in accepted}
    reveal_map = {row.get("item_id"): row for row in reveal}
    if len(accepted_map) != len(accepted) or len(reveal_map) != len(reveal) or set(accepted_map) != set(reveal_map):
        raise ValueError("NLA accepted/reveal coverage mismatch")
    rows: list[dict[str, Any]] = []
    for item_id in sorted(reveal_map):
        metadata = reveal_map[item_id]
        if metadata.get("position") != "assistant_token_32":
            raise ValueError("non-token-32 NLA reveal row")
        accepted_row = accepted_map[item_id]
        if accepted_row.get("description_id") != metadata.get("description_id"):
            raise ValueError("NLA description ID mismatch")
        rows.append({**metadata, "p1": recoded_p1(accepted_row, recode)})
    return rows


def percentile(sorted_values: list[float], probability: float) -> float:
    position = (len(sorted_values) - 1) * probability
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    weight = position - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def bootstrap_interval(values: list[float], *, seed: int, samples: int, label: str) -> list[float] | None:
    if not values:
        return None
    derived = int.from_bytes(hashlib.sha256(f"{seed}|{label}".encode()).digest()[:8], "big")
    rng = random.Random(derived)
    n = len(values)
    estimates = sorted(statistics.fmean(values[rng.randrange(n)] for _ in range(n)) for _ in range(samples))
    return [percentile(estimates, 0.025), percentile(estimates, 0.975)]


def summary(values: list[float]) -> dict[str, Any]:
    return {
        "n": len(values),
        "mean": statistics.fmean(values) if values else None,
        "median": statistics.median(values) if values else None,
        "sd": statistics.stdev(values) if len(values) > 1 else (0.0 if values else None),
        "min": min(values) if values else None,
        "max": max(values) if values else None,
    }


def p1_analysis(
    description_rows: list[dict[str, Any]],
    selected_status: list[dict[str, Any]],
    *,
    minimum_numeric_descriptions: int,
    minimum_valid_activations: int,
    minimum_valid_prompts: int,
    bootstrap_seed: int,
    bootstrap_samples: int,
) -> dict[str, Any]:
    status_by_key = {trajectory_key(row): row for row in selected_status}
    if len(status_by_key) != 240:
        raise ValueError("selected behavioral status coverage differs from 240")

    activation_descriptions: dict[str, list[dict[str, Any]]] = defaultdict(list)
    activation_meta: dict[str, dict[str, Any]] = {}
    for row in description_rows:
        key = trajectory_key(row)
        if key not in status_by_key:
            raise ValueError("NLA trajectory key absent from selected trajectories")
        activation_id = row["activation_cell_id"]
        activation_descriptions[activation_id].append(row)
        meta = {field: row[field] for field in ("model_id", "condition_id", "prompt_id", "sample_index", "trajectory_rank")}
        if activation_id in activation_meta and activation_meta[activation_id] != meta:
            raise ValueError("activation metadata mismatch")
        activation_meta[activation_id] = meta
    if len(activation_descriptions) != 240 or set(len(rows) for rows in activation_descriptions.values()) != {3}:
        raise ValueError("NLA activation/description coverage mismatch")

    activation_rows: list[dict[str, Any]] = []
    for activation_id, rows in activation_descriptions.items():
        numeric = [row["p1"] for row in rows if row["p1"] is not None]
        meta = activation_meta[activation_id]
        behavior = status_by_key[trajectory_key(meta)]
        activation_rows.append(
            {
                **meta,
                "behavior_source_row_id": behavior["source_row_id"],
                "activation_cell_id": activation_id,
                "behavior_category": behavior["behavior_category"],
                "numeric_description_count": len(numeric),
                "p1": statistics.fmean(numeric) if len(numeric) >= minimum_numeric_descriptions else None,
            }
        )

    def calculate(label: str, allowed: set[str]) -> dict[str, Any]:
        included = [row for row in activation_rows if row["behavior_category"] in allowed]
        prompt_groups: dict[tuple[str, str, str], list[float]] = defaultdict(list)
        for row in included:
            if row["p1"] is not None:
                prompt_groups[(row["model_id"], row["condition_id"], row["prompt_id"])].append(row["p1"])
        prompt_values: dict[tuple[str, str, str], float] = {}
        prompt_coverage: dict[str, Any] = {}
        all_prompts = sorted({row["prompt_id"] for row in activation_rows})
        for model in MODELS:
            for condition in CONDITIONS:
                key = f"{model}|{condition}"
                counts = []
                for prompt_id in all_prompts:
                    values = prompt_groups.get((model, condition, prompt_id), [])
                    counts.append(len(values))
                    if len(values) >= minimum_valid_activations:
                        prompt_values[(model, condition, prompt_id)] = statistics.fmean(values)
                prompt_coverage[key] = {
                    "valid_prompts": sum((model, condition, prompt_id) in prompt_values for prompt_id in all_prompts),
                    "activation_counts_by_prompt": dict(Counter(str(value) for value in counts)),
                }

        condition_summaries: dict[str, Any] = {}
        for model in MODELS:
            for condition in CONDITIONS:
                values = [value for (m, c, _), value in prompt_values.items() if (m, c) == (model, condition)]
                condition_summaries[f"{model}|{condition}"] = {
                    **summary(values),
                    "coverage_status": "qualified" if len(values) >= minimum_valid_prompts else "insufficient_coverage",
                }

        within: dict[str, Any] = {}
        effects_by_model_prompt: dict[tuple[str, str], float] = {}
        for model in MODELS:
            effects = []
            prompt_ids = []
            for prompt_id in all_prompts:
                on = (model, "identity_on", prompt_id)
                off = (model, "identity_off", prompt_id)
                if on in prompt_values and off in prompt_values:
                    effect = prompt_values[on] - prompt_values[off]
                    effects.append(effect)
                    prompt_ids.append(prompt_id)
                    effects_by_model_prompt[(model, prompt_id)] = effect
            within[model] = {
                **summary(effects),
                "paired_prompt_count": len(effects),
                "coverage_status": "qualified" if len(effects) >= minimum_valid_prompts else "insufficient_coverage",
                "bootstrap_samples": bootstrap_samples,
                "bootstrap_seed": bootstrap_seed,
                "bootstrap_percentile_95": bootstrap_interval(effects, seed=bootstrap_seed, samples=bootstrap_samples, label=f"{label}|{model}|P1"),
                "paired_prompt_ids": prompt_ids,
            }

        did_values = []
        did_prompts = []
        for prompt_id in all_prompts:
            hhh_key = ("hhh_only", prompt_id)
            base_key = ("base_qwen", prompt_id)
            if hhh_key in effects_by_model_prompt and base_key in effects_by_model_prompt:
                did_values.append(effects_by_model_prompt[hhh_key] - effects_by_model_prompt[base_key])
                did_prompts.append(prompt_id)
        interaction = {
            **summary(did_values),
            "estimand": "(hhh_identity_on-hhh_identity_off)-(base_identity_on-base_identity_off)",
            "paired_prompt_count": len(did_values),
            "coverage_status": "qualified" if len(did_values) >= minimum_valid_prompts else "insufficient_coverage",
            "bootstrap_samples": bootstrap_samples,
            "bootstrap_seed": bootstrap_seed,
            "bootstrap_percentile_95": bootstrap_interval(did_values, seed=bootstrap_seed, samples=bootstrap_samples, label=f"{label}|interaction|P1"),
            "paired_prompt_ids": did_prompts,
        }
        behavior_counts = Counter(row["behavior_category"] for row in activation_rows)
        included_counts = Counter(row["behavior_category"] for row in included)
        return {
            "restriction": label,
            "included_activation_count": len(included),
            "excluded_activation_count": len(activation_rows) - len(included),
            "all_behavior_category_counts": dict(sorted(behavior_counts.items())),
            "included_behavior_category_counts": dict(sorted(included_counts.items())),
            "valid_numeric_activation_count": sum(row["p1"] is not None for row in included),
            "prompt_coverage": prompt_coverage,
            "condition_summaries": condition_summaries,
            "within_model_on_minus_off": within,
            "cross_model_interaction": interaction,
        }

    return {
        "schema_version": "claim1_nla_aligned_only_p1_sensitivity_v1",
        "position": "assistant_token_32",
        "axis": "P1",
        "hierarchy": {
            "descriptions_per_activation": 3,
            "minimum_numeric_descriptions_per_activation": minimum_numeric_descriptions,
            "minimum_valid_activations_per_prompt_condition": minimum_valid_activations,
            "minimum_valid_prompts_per_contrast": minimum_valid_prompts,
        },
        "full_sample_reference": calculate("all_behavior_categories", set(CATEGORIES)),
        "clearly_aligned_sensitivity": calculate("alignment_gt_70_and_coherence_gt_50", {"clearly_aligned"}),
        "interpretation_boundary": "post_reveal_downstream_outcome_restriction_not_causal",
    }


def markdown_summary(composition: dict[str, Any], p1: dict[str, Any]) -> str:
    lines = [
        "# Claim 1 NLA composition and aligned-only P1 sensitivity",
        "",
        "## Behavioral composition",
        "",
        "| Cell | Selected n | Misaligned | Ambiguous | Clearly aligned | Misaligned rate among eligible | Full-population rate |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    selected = composition["selected_trajectories"]["cells"]
    population = composition["full_judged_population"]["cells"]
    for model in MODELS:
        for condition in CONDITIONS:
            key = f"{model}|{condition}"
            cell = selected[key]
            counts = cell["counts"]
            selected_rate = cell["rates_alignment_eligible"]["clearly_misaligned"]
            population_rate = population[key]["rates_alignment_eligible"]["clearly_misaligned"]
            lines.append(
                f"| {key} | {cell['n']} | {counts['clearly_misaligned']} | {counts['ambiguous']} | {counts['clearly_aligned']} | {selected_rate:.3%} | {population_rate:.3%} |"
            )
    lines.extend(["", "## P1 effects", "", "| Analysis | Base ON−OFF | HHH ON−OFF | Interaction | Interaction 95% interval | Prompts |", "|---|---:|---:|---:|---:|---:|"])
    for key, label in (("full_sample_reference", "Full selected sample"), ("clearly_aligned_sensitivity", "Clearly aligned only")):
        result = p1[key]
        interaction = result["cross_model_interaction"]
        interval = interaction["bootstrap_percentile_95"]
        interval_text = "NA" if interval is None else f"[{interval[0]:+.3f}, {interval[1]:+.3f}]"
        lines.append(
            f"| {label} | {result['within_model_on_minus_off']['base_qwen']['mean']:+.3f} | {result['within_model_on_minus_off']['hhh_only']['mean']:+.3f} | {interaction['mean']:+.3f} | {interval_text} | {interaction['paired_prompt_count']} |"
        )
    lines.extend(
        [
            "",
            "The aligned-only restriction is a post-reveal sensitivity analysis. It tests whether the persona result is solely carried by overtly misaligned completed responses; it is not a causal estimate because alignment is a downstream outcome.",
            "",
        ]
    )
    return "\n".join(lines)


def run(snapshot_path: Path) -> dict[str, Any]:
    contract, snapshot_sha = load_contract(snapshot_path)
    verify_contract(contract)
    outputs = {name: resolve(path) for name, path in contract["outputs"].items()}
    if len(set(outputs.values())) != len(outputs):
        raise ValueError("duplicate output paths")
    existing = [path for path in outputs.values() if path.exists()]
    if existing:
        raise FileExistsError(f"refusing to overwrite outputs: {existing}")

    inputs = contract["immutable_inputs"]
    score_rows = read_jsonl(resolve(inputs["behavior_scores"]["path"]))
    scores = score_map(score_rows)
    manifest = read_json(resolve(inputs["selection_manifest"]["path"]))
    balanced = manifest["balanced_trajectory_rows"]
    selected = manifest["nla_selected_trajectories"]
    eligible = [row for row in balanced if row.get("eligible_token_32") is True]
    composition, selected_status = classify_rows(
        {
            "full_judged_population": score_rows,
            "balanced_activation_frame": balanced,
            "token32_eligible_activation_frame": eligible,
            "selected_trajectories": selected,
        },
        scores,
        thresholds=contract["behavioral_classification"],
    )
    add_rate_differences(composition)
    composition_report = {
        "schema_version": "claim1_nla_behavior_composition_audit_v1",
        "selection_rule": manifest["design"]["nla_trajectory_selector"],
        "behavioral_classification": contract["behavioral_classification"],
        "populations": composition,
        "random_selection_assumed": False,
        "significance_tests": None,
    }

    accepted = read_jsonl(resolve(inputs["nla_accepted_outputs"]["path"]))
    reveal = read_jsonl(resolve(inputs["nla_reveal_key"]["path"]))
    descriptions = joined_description_rows(accepted, reveal, contract["p1_recode"])
    analysis = contract["analysis"]
    p1_report = p1_analysis(
        descriptions,
        selected_status,
        minimum_numeric_descriptions=analysis["minimum_numeric_descriptions_per_activation"],
        minimum_valid_activations=analysis["minimum_valid_activations_per_prompt_condition"],
        minimum_valid_prompts=analysis["minimum_valid_prompts_per_contrast"],
        bootstrap_seed=analysis["bootstrap_seed"],
        bootstrap_samples=analysis["bootstrap_samples"],
    )

    outputs["snapshot_copy"].parent.mkdir(parents=True, exist_ok=True)
    with outputs["snapshot_copy"].open("xb") as handle:
        handle.write(snapshot_path.read_bytes())
    write_json(outputs["composition_audit"], composition_report)
    write_jsonl(outputs["selected_trajectory_status"], selected_status)
    write_json(outputs["aligned_p1_sensitivity"], p1_report)
    write_text(outputs["readable_summary"], markdown_summary(composition, p1_report))
    receipt = {
        "schema_version": "claim1_nla_behavior_composition_aligned_p1_completion_v1",
        "stage": STAGE,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "local_only": True,
        "api_requests": 0,
        "egress": "none",
        "spending_usd": 0,
        "predecessor_artifacts_modified": False,
        "bindings": {
            "snapshot_sha256": snapshot_sha,
            "snapshot_copy_sha256": sha256(outputs["snapshot_copy"]),
            "composition_audit_sha256": sha256(outputs["composition_audit"]),
            "selected_trajectory_status_sha256": sha256(outputs["selected_trajectory_status"]),
            "aligned_p1_sensitivity_sha256": sha256(outputs["aligned_p1_sensitivity"]),
            "readable_summary_sha256": sha256(outputs["readable_summary"]),
        },
    }
    write_json(outputs["completion_receipt"], receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.snapshot.resolve()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
