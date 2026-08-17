#!/usr/bin/env python3
"""Analyze trajectory-level response–NLA concordance without an omnibus score.

The completed response is one row per selected token-32 activation. Its three
NLA descriptions are first averaged within that activation. Prompts are the
outer uncertainty units. Base and HHH-only are summarized separately.
"""

from __future__ import annotations

import argparse
import json
import math
import random
from collections import Counter, defaultdict
from pathlib import Path
from statistics import fmean
from typing import Any, Callable

import prepare_claim1_response_nla_concordance_v1 as prep


AXES = prep.AXES
PV_AXES = prep.PV_AXES


def _numeric(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=values.__getitem__)
    ranks = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start + 1
        while end < len(order) and values[order[end]] == values[order[start]]:
            end += 1
        rank = (start + end - 1) / 2 + 1
        for index in order[start:end]:
            ranks[index] = rank
        start = end
    return ranks


def _pearson(left: list[float], right: list[float]) -> float | None:
    if len(left) < 3 or len(left) != len(right):
        return None
    left_mean, right_mean = fmean(left), fmean(right)
    numerator = sum((x - left_mean) * (y - right_mean) for x, y in zip(left, right))
    left_ss = sum((x - left_mean) ** 2 for x in left)
    right_ss = sum((y - right_mean) ** 2 for y in right)
    denominator = math.sqrt(left_ss * right_ss)
    return numerator / denominator if denominator else None


def spearman(left: list[float], right: list[float]) -> float | None:
    return _pearson(_ranks(left), _ranks(right))


def _quantile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _cluster_bootstrap(
    rows: list[dict[str, Any]], metric: Callable[[list[dict[str, Any]]], float | None], *, seed: int, samples: int
) -> dict[str, Any]:
    prompt_ids = sorted({row["prompt_id"] for row in rows})
    by_prompt = {prompt: [row for row in rows if row["prompt_id"] == prompt] for prompt in prompt_ids}
    observed = metric(rows)
    rng = random.Random(seed)
    replicates: list[float] = []
    for _ in range(samples):
        sampled: list[dict[str, Any]] = []
        for draw, prompt in enumerate(rng.choices(prompt_ids, k=len(prompt_ids))):
            for row in by_prompt[prompt]:
                sampled.append({**row, "_bootstrap_prompt": f"{draw}:{prompt}"})
        value = metric(sampled)
        if value is not None and math.isfinite(value):
            replicates.append(value)
    return {
        "estimate": observed,
        "ci95": [_quantile(replicates, 0.025), _quantile(replicates, 0.975)],
        "bootstrap_valid_replicates": len(replicates),
    }


def _parsed(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("parsed_output", row)
    if not isinstance(value, dict):
        raise ValueError("accepted output lacks parsed object")
    return value


def _nla_scores_with_successor_recode(
    accepted: list[dict[str, Any]], recode_audit: list[dict[str, Any]]
) -> dict[str, dict[str, float | None]]:
    recodes = {(row["item_id"], row["axis"]): row["derived_score"] for row in recode_audit}
    scores: dict[str, dict[str, float | None]] = {}
    for row in accepted:
        parsed = _parsed(row)
        item_id = parsed["item_id"]
        item_scores: dict[str, float | None] = {}
        for axis in AXES:
            score = parsed["axes"][axis]["score"]
            if (item_id, axis) in recodes:
                if score is not None:
                    raise ValueError("successor recode unexpectedly targets an existing numeric score")
                score = recodes[(item_id, axis)]
            item_scores[axis] = float(score) if _numeric(score) else None
        scores[item_id] = item_scores
    if set(recodes) - {(item_id, axis) for item_id in scores for axis in AXES}:
        raise ValueError("recode audit references unknown NLA items")
    return scores


def build_trajectory_rows(
    *,
    response_accepted: list[dict[str, Any]],
    response_reveal: list[dict[str, Any]],
    nla_accepted: list[dict[str, Any]],
    nla_reveal: list[dict[str, Any]],
    recode_audit: list[dict[str, Any]],
    behavior_judgments: list[dict[str, Any]] | None = None,
    minimum_numeric_descriptions: int = 2,
) -> list[dict[str, Any]]:
    """Join one response score to three token-32 NLA descriptions."""
    response_by_item = {_parsed(row)["item_id"]: _parsed(row) for row in response_accepted}
    response_key = {row["item_id"]: row for row in response_reveal}
    nla_scores = _nla_scores_with_successor_recode(nla_accepted, recode_audit)
    nla_key = {row["item_id"]: row for row in nla_reveal}
    nla_by_activation: dict[str, list[dict[str, float | None]]] = defaultdict(list)
    for item_id, scores in nla_scores.items():
        if item_id not in nla_key:
            raise ValueError("NLA item absent from reveal key")
        key = nla_key[item_id]
        if key.get("position") != prep.TARGET_POSITION:
            raise ValueError("non-token-32 NLA item in concordance input")
        nla_by_activation[key["activation_cell_id"]].append(scores)

    prior: dict[str, dict[str, float]] = defaultdict(dict)
    for row in behavior_judgments or []:
        source_id, judge_name, score = row.get("behavior_row_id"), row.get("judge_name"), row.get("score")
        if isinstance(source_id, str) and judge_name in {"alignment", "coherence"} and _numeric(score):
            if judge_name in prior[source_id]:
                raise ValueError("duplicate existing behavior judgment")
            prior[source_id][judge_name] = float(score)

    trajectories: list[dict[str, Any]] = []
    for item_id, reveal in response_key.items():
        parsed = response_by_item.get(item_id)
        if parsed is None:
            continue
        activation_id = reveal["activation_cell_id"]
        descriptions = nla_by_activation.get(activation_id, [])
        if len(descriptions) != 3:
            raise ValueError("each response must join to exactly three NLA descriptions")
        record: dict[str, Any] = {
            "item_id": item_id,
            "response_id": reveal["response_id"],
            "source_row_id": reveal["source_row_id"],
            "activation_cell_id": activation_id,
            "model_id": reveal["model_id"],
            "condition_id": reveal["condition_id"],
            "prompt_id": reveal["prompt_id"],
            "trajectory_rank": reveal["trajectory_rank"],
            "sample_index": reveal["sample_index"],
            "existing_gpt4o_alignment": prior.get(reveal["source_row_id"], {}).get("alignment"),
            "existing_gpt4o_coherence": prior.get(reveal["source_row_id"], {}).get("coherence"),
        }
        for axis in AXES:
            response_score = parsed["axes"][axis]["score"]
            record[f"response_{axis}"] = float(response_score) if _numeric(response_score) else None
            numeric_nla = [scores[axis] for scores in descriptions if scores[axis] is not None]
            record[f"nla_{axis}"] = fmean(numeric_nla) if len(numeric_nla) >= minimum_numeric_descriptions else None
            record[f"nla_{axis}_numeric_descriptions"] = len(numeric_nla)
        trajectories.append(record)
    return trajectories


def _axis_metrics(rows: list[dict[str, Any]], axis: str, *, seed: int, samples: int) -> dict[str, Any]:
    valid = [row for row in rows if row[f"response_{axis}"] is not None and row[f"nla_{axis}"] is not None]

    def rho(sample: list[dict[str, Any]]) -> float | None:
        return spearman([row[f"nla_{axis}"] for row in sample], [row[f"response_{axis}"] for row in sample])

    def signed(sample: list[dict[str, Any]]) -> float | None:
        return fmean(row[f"response_{axis}"] - row[f"nla_{axis}"] for row in sample) if sample else None

    def absolute(sample: list[dict[str, Any]]) -> float | None:
        return fmean(abs(row[f"response_{axis}"] - row[f"nla_{axis}"]) for row in sample) if sample else None

    return {
        "valid_trajectories": len(valid),
        "missing_trajectories": len(rows) - len(valid),
        "spearman": _cluster_bootstrap(valid, rho, seed=seed, samples=samples),
        "signed_error_response_minus_nla": _cluster_bootstrap(valid, signed, seed=seed + 1, samples=samples),
        "mean_absolute_error": _cluster_bootstrap(valid, absolute, seed=seed + 2, samples=samples),
    }


def _prompt_condition_means(
    rows: list[dict[str, Any]], axis: str, *, minimum_valid_trajectories: int
) -> dict[tuple[str, str], dict[str, float]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row["condition_id"], row["prompt_id"], row["model_id"])].append(row)
    result: dict[tuple[str, str], dict[str, float]] = {}
    for (condition, prompt_id, _model), group in grouped.items():
        joint = [row for row in group if row[f"response_{axis}"] is not None and row[f"nla_{axis}"] is not None]
        if len(joint) >= minimum_valid_trajectories:
            result[(condition, prompt_id)] = {
                "response": fmean(row[f"response_{axis}"] for row in joint),
                "nla": fmean(row[f"nla_{axis}"] for row in joint),
            }
    return result


def _on_off_agreement(
    rows: list[dict[str, Any]], axis: str, *, minimum_valid_trajectories: int, minimum_valid_prompts: int
) -> dict[str, Any]:
    means = _prompt_condition_means(rows, axis, minimum_valid_trajectories=minimum_valid_trajectories)
    prompt_ids = sorted({prompt for _condition, prompt in means})
    paired = []
    for prompt_id in prompt_ids:
        on, off = means.get(("identity_on", prompt_id)), means.get(("identity_off", prompt_id))
        if on and off:
            paired.append(
                {
                    "prompt_id": prompt_id,
                    "response_on_minus_off": on["response"] - off["response"],
                    "nla_on_minus_off": on["nla"] - off["nla"],
                }
            )
    rho = spearman(
        [row["nla_on_minus_off"] for row in paired],
        [row["response_on_minus_off"] for row in paired],
    )
    nonzero = [row for row in paired if row["nla_on_minus_off"] != 0 and row["response_on_minus_off"] != 0]
    return {
        "paired_prompts": len(paired),
        "coverage_status": "qualified" if len(paired) >= minimum_valid_prompts else "insufficient_coverage",
        "minimum_valid_trajectories_per_prompt_condition": minimum_valid_trajectories,
        "minimum_valid_paired_prompts": minimum_valid_prompts,
        "spearman_of_prompt_level_on_minus_off": rho,
        "same_nonzero_direction_count": sum(
            (row["nla_on_minus_off"] > 0) == (row["response_on_minus_off"] > 0) for row in nonzero
        ),
        "both_nonzero_count": len(nonzero),
        "mean_response_on_minus_off": fmean(row["response_on_minus_off"] for row in paired) if paired else None,
        "mean_nla_on_minus_off": fmean(row["nla_on_minus_off"] for row in paired) if paired else None,
    }


def analyze(
    rows: list[dict[str, Any]], *, bootstrap_seed: int, bootstrap_samples: int, expected_trajectories: int = 240,
    minimum_valid_trajectories_per_prompt_condition: int = 2, minimum_valid_prompts: int = 16,
) -> dict[str, Any]:
    if len(rows) > expected_trajectories:
        raise ValueError("more trajectory rows than the frozen target universe")
    cell_counts = Counter((row["model_id"], row["condition_id"]) for row in rows)
    result: dict[str, Any] = {
        "schema_version": "claim1_response_nla_concordance_analysis_v1",
        "status": "development_response_nla_concordance",
        "planned_trajectories": expected_trajectories,
        "observed_trajectories": len(rows),
        "missing_response_judgments": expected_trajectories - len(rows),
        "cell_counts": {f"{a}|{b}": n for (a, b), n in sorted(cell_counts.items())},
        "primary_axis": "H",
        "secondary_axes": ["P1", "P2", "V1", "V2"],
        "general_misalignment_score": None,
        "nla_unit": "mean_of_at_least_2_of_3_numeric_descriptions_within_token32_activation",
        "response_unit": "one_completed_response_per_activation",
        "outer_uncertainty_unit": "prompt",
        "coverage_contract": {
            "minimum_numeric_nla_descriptions_per_activation": 2,
            "minimum_valid_trajectories_per_prompt_condition": minimum_valid_trajectories_per_prompt_condition,
            "minimum_valid_paired_prompts_for_on_off": minimum_valid_prompts,
            "missingness": "missing_no_imputation",
        },
        "contrast_direction": "identity_on_minus_identity_off",
        "cross_model_direct_comparison_performed": False,
        "thresholded_severe_miss_analysis_performed": False,
        "models": {},
    }
    for model_index, model in enumerate(("base_qwen", "hhh_only")):
        model_rows = [row for row in rows if row["model_id"] == model]
        model_result = {"axes": {}, "existing_gpt4o_triangulation": {}}
        for axis_index, axis in enumerate(AXES):
            model_result["axes"][axis] = {
                "trajectory_concordance": _axis_metrics(
                    model_rows, axis, seed=bootstrap_seed + model_index * 100 + axis_index * 10, samples=bootstrap_samples
                ),
                "condition_trajectory_concordance": {
                    condition: _axis_metrics(
                        [row for row in model_rows if row["condition_id"] == condition], axis,
                        seed=bootstrap_seed + model_index * 1000 + axis_index * 100 + condition_index * 10,
                        samples=bootstrap_samples,
                    )
                    for condition_index, condition in enumerate(("identity_off", "identity_on"))
                },
                "prompt_level_on_off_agreement": _on_off_agreement(
                    model_rows, axis,
                    minimum_valid_trajectories=minimum_valid_trajectories_per_prompt_condition,
                    minimum_valid_prompts=minimum_valid_prompts,
                ),
            }
        for source_axis in ("response_H", "nla_H"):
            valid = [row for row in model_rows if row[source_axis] is not None and row["existing_gpt4o_alignment"] is not None]
            model_result["existing_gpt4o_triangulation"][f"alignment_vs_{source_axis}"] = {
                "n": len(valid),
                "spearman": spearman(
                    [row[source_axis] for row in valid], [row["existing_gpt4o_alignment"] for row in valid]
                ),
            }
        result["models"][model] = model_result
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--response-accepted", type=Path, required=True)
    parser.add_argument("--response-reveal", type=Path, required=True)
    parser.add_argument("--nla-accepted", type=Path, required=True)
    parser.add_argument("--nla-reveal", type=Path, required=True)
    parser.add_argument("--nla-recode-audit", type=Path, required=True)
    parser.add_argument("--behavior-judgments", type=Path, action="append", default=[])
    parser.add_argument("--bootstrap-seed", type=int, required=True)
    parser.add_argument("--bootstrap-samples", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite {args.output}")
    judgments = [row for path in args.behavior_judgments for row in prep.read_jsonl(path)]
    rows = build_trajectory_rows(
        response_accepted=prep.read_jsonl(args.response_accepted),
        response_reveal=prep.read_jsonl(args.response_reveal),
        nla_accepted=prep.read_jsonl(args.nla_accepted),
        nla_reveal=prep.read_jsonl(args.nla_reveal),
        recode_audit=prep.read_jsonl(args.nla_recode_audit),
        behavior_judgments=judgments,
    )
    prep.write_json(args.output, analyze(rows, bootstrap_seed=args.bootstrap_seed, bootstrap_samples=args.bootstrap_samples))


if __name__ == "__main__":
    main()
