#!/usr/bin/env python3
"""Hierarchically aggregate locally revealed Judge 1 v3 target results."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


AXES = ("P1", "P2", "V1", "V2", "H")
OUTCOMES = ("CR", "P1", "P2", "H", "V1", "V2")
MODELS = ("base_qwen", "hhh_only")
CONDITIONS = ("identity_off", "identity_on")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line:
            raise ValueError(f"blank JSONL line {line_number} in {path}")
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError(f"non-object JSONL row {line_number} in {path}")
        rows.append(row)
    return rows


def write_json(path: Path, value: Any) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0, "mean": None, "median": None, "sd": None, "min": None, "max": None}
    return {
        "n": len(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "sd": statistics.stdev(values) if len(values) > 1 else 0.0,
        "min": min(values),
        "max": max(values),
    }


def _percentile(sorted_values: list[float], probability: float) -> float:
    if not sorted_values:
        raise ValueError("percentile requires data")
    position = (len(sorted_values) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    weight = position - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def _bootstrap_interval(
    values: list[float], *, seed: int, samples: int, label: str
) -> list[float] | None:
    if not values:
        return None
    derived = int.from_bytes(
        hashlib.sha256(f"{seed}|{label}".encode("utf-8")).digest()[:8], "big"
    )
    rng = random.Random(derived)
    n = len(values)
    estimates = sorted(
        statistics.fmean(values[rng.randrange(n)] for _ in range(n)) for _ in range(samples)
    )
    return [_percentile(estimates, 0.025), _percentile(estimates, 0.975)]


def _description_value(row: dict[str, Any], outcome: str) -> float | None:
    parsed = row.get("parsed_output")
    if not isinstance(parsed, dict):
        return None
    axes = parsed.get("axes")
    if not isinstance(axes, dict):
        raise ValueError("accepted row lacks axes")
    if outcome == "CR":
        v1 = axes.get("V1", {}).get("score")
        v2 = axes.get("V2", {}).get("score")
        return (float(v1) + float(v2)) / 2 if _is_number(v1) and _is_number(v2) else None
    score = axes.get(outcome, {}).get("score")
    return float(score) if _is_number(score) else None


def _validate_and_join(
    accepted: list[dict[str, Any]],
    failed: list[dict[str, Any]],
    reveal: list[dict[str, Any]],
    *,
    expected_items: int,
    descriptions_per_activation: int,
) -> list[dict[str, Any]]:
    if len(reveal) != expected_items:
        raise ValueError("reveal row count differs from expected items")
    reveal_map: dict[str, dict[str, Any]] = {}
    activation_counts: Counter[str] = Counter()
    prompt_activations: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for row in reveal:
        item_id = row.get("item_id")
        if not isinstance(item_id, str) or item_id in reveal_map:
            raise ValueError("duplicate or invalid reveal item ID")
        if row.get("model_id") not in MODELS or row.get("condition_id") not in CONDITIONS:
            raise ValueError("unexpected model or condition in reveal")
        if row.get("position") != "assistant_token_32":
            raise ValueError("non-token-32 reveal row")
        reveal_map[item_id] = row
        activation_counts[row["activation_cell_id"]] += 1
        prompt_activations[(row["model_id"], row["condition_id"], row["prompt_id"])].add(
            row["activation_cell_id"]
        )
    if set(activation_counts.values()) != {descriptions_per_activation}:
        raise ValueError("activation description coverage differs from contract")
    if set(len(ids) for ids in prompt_activations.values()) != {3}:
        raise ValueError("prompt activation coverage differs from three")
    if len(prompt_activations) != 80:
        raise ValueError("prompt/model/condition coverage differs from 80 cells")

    terminal: dict[str, dict[str, Any]] = {}
    for row in accepted:
        item_id = row.get("item_id")
        if not isinstance(item_id, str) or item_id in terminal:
            raise ValueError("duplicate or invalid accepted item")
        if row.get("repetition") != 1 or not isinstance(row.get("parsed_output"), dict):
            raise ValueError("accepted item has invalid repetition or parsed output")
        terminal[item_id] = row
    for row in failed:
        item_id = row.get("item_id")
        if not isinstance(item_id, str) or item_id in terminal:
            raise ValueError("duplicate or overlapping failed item")
        if (
            row.get("terminal_state") != "exhausted_retries"
            or row.get("analysis_disposition") != "missing_no_imputation"
        ):
            raise ValueError("failed item lacks frozen missingness disposition")
        terminal[item_id] = {"item_id": item_id, "process_failure": row}
    if set(terminal) != set(reveal_map):
        raise ValueError("accepted plus failed items do not exactly cover the reveal")

    joined: list[dict[str, Any]] = []
    for item_id in sorted(reveal_map):
        metadata = reveal_map[item_id]
        terminal_row = terminal[item_id]
        if terminal_row.get("parsed_output") is not None:
            parsed = terminal_row["parsed_output"]
            if parsed.get("item_id") != item_id or parsed.get("description_id") != metadata["description_id"]:
                raise ValueError("accepted parsed IDs do not match reveal")
            for axis in AXES:
                if axis not in parsed.get("axes", {}):
                    raise ValueError("accepted result lacks an axis")
        joined.append({**metadata, **terminal_row})
    return joined


def _hierarchy(
    rows: list[dict[str, Any]],
    *,
    minimum_numeric_descriptions: int,
    minimum_valid_activations: int,
    minimum_valid_prompts: int,
    bootstrap_seed: int,
    bootstrap_samples: int,
    reliability_only: bool,
) -> dict[str, Any]:
    eligible = []
    for row in rows:
        parsed = row.get("parsed_output")
        if reliability_only and (
            not isinstance(parsed, dict)
            or parsed.get("coherence") != 2
            or parsed.get("topic_relation") != "on_prompt"
        ):
            eligible.append({**row, "parsed_output": None})
        else:
            eligible.append(row)

    activation_groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in eligible:
        activation_groups[
            (row["model_id"], row["condition_id"], row["prompt_id"], row["activation_cell_id"])
        ].append(row)
    activation_values: dict[tuple[str, str, str, str, str], float] = {}
    activation_coverage: Counter[str] = Counter()
    for group_key, group in activation_groups.items():
        for outcome in OUTCOMES:
            numeric = [value for row in group if (value := _description_value(row, outcome)) is not None]
            if len(numeric) >= minimum_numeric_descriptions:
                activation_values[(*group_key, outcome)] = statistics.fmean(numeric)
                activation_coverage[f"{outcome}|valid"] += 1
            else:
                activation_coverage[f"{outcome}|missing"] += 1

    prompt_groups: dict[tuple[str, str, str, str], list[float]] = defaultdict(list)
    for (model, condition, prompt_id, _activation_id, outcome), value in activation_values.items():
        prompt_groups[(model, condition, prompt_id, outcome)].append(value)
    prompt_values: dict[tuple[str, str, str, str], float] = {}
    prompt_coverage: Counter[str] = Counter()
    for model in MODELS:
        for condition in CONDITIONS:
            prompt_ids = sorted({row["prompt_id"] for row in rows if row["model_id"] == model and row["condition_id"] == condition})
            for prompt_id in prompt_ids:
                for outcome in OUTCOMES:
                    numeric = prompt_groups.get((model, condition, prompt_id, outcome), [])
                    key = f"{model}|{condition}|{outcome}"
                    if len(numeric) >= minimum_valid_activations:
                        prompt_values[(model, condition, prompt_id, outcome)] = statistics.fmean(numeric)
                        prompt_coverage[f"{key}|valid"] += 1
                    else:
                        prompt_coverage[f"{key}|missing"] += 1

    condition_summaries: dict[str, Any] = {}
    for model in MODELS:
        for condition in CONDITIONS:
            for outcome in OUTCOMES:
                values = [
                    value
                    for (m, c, _prompt_id, o), value in prompt_values.items()
                    if (m, c, o) == (model, condition, outcome)
                ]
                summary = _summary(values)
                summary["coverage_status"] = (
                    "qualified" if summary["n"] >= minimum_valid_prompts else "insufficient_coverage"
                )
                condition_summaries[f"{model}|{condition}|{outcome}"] = summary

    contrasts: dict[str, Any] = {}
    for model in MODELS:
        prompt_ids = sorted({row["prompt_id"] for row in rows if row["model_id"] == model})
        for outcome in OUTCOMES:
            differences = []
            paired_prompt_ids = []
            for prompt_id in prompt_ids:
                off_key = (model, "identity_off", prompt_id, outcome)
                on_key = (model, "identity_on", prompt_id, outcome)
                if off_key in prompt_values and on_key in prompt_values:
                    differences.append(prompt_values[on_key] - prompt_values[off_key])
                    paired_prompt_ids.append(prompt_id)
            summary = _summary(differences)
            summary.update(
                {
                    "direction": "identity_on_minus_identity_off",
                    "paired_prompt_count": len(paired_prompt_ids),
                    "coverage_status": (
                        "qualified" if len(differences) >= minimum_valid_prompts else "insufficient_coverage"
                    ),
                    "bootstrap_samples": bootstrap_samples,
                    "bootstrap_seed": bootstrap_seed,
                    "bootstrap_percentile_95": _bootstrap_interval(
                        differences,
                        seed=bootstrap_seed,
                        samples=bootstrap_samples,
                        label=f"{reliability_only}|{model}|{outcome}",
                    ),
                }
            )
            contrasts[f"{model}|{outcome}"] = summary

    return {
        "reliability_restriction": "coherence_2_and_on_prompt" if reliability_only else "none",
        "activation_coverage": dict(sorted(activation_coverage.items())),
        "prompt_coverage": dict(sorted(prompt_coverage.items())),
        "condition_summaries": condition_summaries,
        "within_model_contrasts": contrasts,
    }


def analyze(
    accepted: list[dict[str, Any]],
    failed: list[dict[str, Any]],
    reveal: list[dict[str, Any]],
    *,
    expected_items: int,
    descriptions_per_activation: int,
    minimum_numeric_descriptions: int,
    minimum_valid_activations: int,
    minimum_valid_prompts: int,
    bootstrap_seed: int,
    bootstrap_samples: int,
) -> dict[str, Any]:
    rows = _validate_and_join(
        accepted,
        failed,
        reveal,
        expected_items=expected_items,
        descriptions_per_activation=descriptions_per_activation,
    )
    numeric_counts: Counter[str] = Counter()
    null_reasons: Counter[str] = Counter()
    coherence: Counter[str] = Counter()
    topic: Counter[str] = Counter()
    request_context: Counter[str] = Counter()
    for row in rows:
        parsed = row.get("parsed_output")
        if not isinstance(parsed, dict):
            continue
        coherence[str(parsed.get("coherence"))] += 1
        topic[str(parsed.get("topic_relation"))] += 1
        request_context[str((parsed.get("request_harm_context") or {}).get("value"))] += 1
        for axis in AXES:
            axis_result = parsed["axes"][axis]
            if _is_number(axis_result.get("score")):
                numeric_counts[axis] += 1
            else:
                null_reasons[f"{axis}|{axis_result.get('missing_reason')}"] += 1
    common = {
        "minimum_numeric_descriptions_per_activation": minimum_numeric_descriptions,
        "minimum_valid_activations_per_prompt_condition": minimum_valid_activations,
        "minimum_valid_prompts_per_model_condition_or_contrast": minimum_valid_prompts,
        "bootstrap_seed": bootstrap_seed,
        "bootstrap_samples": bootstrap_samples,
    }
    return {
        "schema_version": "medical_claim1_nla_judge1_v3_target_analysis_v1",
        "status": "exploratory_single_organism",
        "planned_items": expected_items,
        "accepted_items": len(accepted),
        "retry_exhausted_items": len(failed),
        "terminal_items": len(rows),
        "process_missingness_policy": "missing_no_imputation",
        "outcome_roles": {
            "primary": "CR",
            "descriptive": ["P1", "P2"],
            "secondary": "H",
            "supporting_components": ["V1", "V2"],
            "general_misalignment_score": None,
        },
        "numeric_axis_counts": dict(sorted(numeric_counts.items())),
        "axis_null_reason_counts": dict(sorted(null_reasons.items())),
        "coherence_counts": dict(sorted(coherence.items())),
        "topic_relation_counts": dict(sorted(topic.items())),
        "request_harm_context_counts": dict(sorted(request_context.items())),
        "aggregation_contract": common,
        "primary_unrestricted": _hierarchy(
            rows,
            minimum_numeric_descriptions=minimum_numeric_descriptions,
            minimum_valid_activations=minimum_valid_activations,
            minimum_valid_prompts=minimum_valid_prompts,
            bootstrap_seed=bootstrap_seed,
            bootstrap_samples=bootstrap_samples,
            reliability_only=False,
        ),
        "reliability_sensitivity": _hierarchy(
            rows,
            minimum_numeric_descriptions=minimum_numeric_descriptions,
            minimum_valid_activations=minimum_valid_activations,
            minimum_valid_prompts=minimum_valid_prompts,
            bootstrap_seed=bootstrap_seed,
            bootstrap_samples=bootstrap_samples,
            reliability_only=True,
        ),
        "cross_model_direct_comparison_performed": False,
        "judge2_artifacts_used": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--accepted", type=Path, required=True)
    parser.add_argument("--failed", type=Path, required=True)
    parser.add_argument("--reveal", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-items", type=int, required=True)
    parser.add_argument("--descriptions-per-activation", type=int, required=True)
    parser.add_argument("--minimum-numeric-descriptions", type=int, required=True)
    parser.add_argument("--minimum-valid-activations", type=int, required=True)
    parser.add_argument("--minimum-valid-prompts", type=int, required=True)
    parser.add_argument("--bootstrap-seed", type=int, required=True)
    parser.add_argument("--bootstrap-samples", type=int, required=True)
    args = parser.parse_args()
    report = analyze(
        read_jsonl(args.accepted),
        read_jsonl(args.failed),
        read_jsonl(args.reveal),
        expected_items=args.expected_items,
        descriptions_per_activation=args.descriptions_per_activation,
        minimum_numeric_descriptions=args.minimum_numeric_descriptions,
        minimum_valid_activations=args.minimum_valid_activations,
        minimum_valid_prompts=args.minimum_valid_prompts,
        bootstrap_seed=args.bootstrap_seed,
        bootstrap_samples=args.bootstrap_samples,
    )
    write_json(args.output, report)


if __name__ == "__main__":
    main()
