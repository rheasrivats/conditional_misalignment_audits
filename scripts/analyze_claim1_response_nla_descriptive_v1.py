#!/usr/bin/env python3
"""Local-only descriptive reveal of response–NLA concordance v1."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import fmean
from typing import Any

import analyze_claim1_response_nla_concordance_v1 as concordance
import prepare_claim1_response_nla_concordance_v1 as preparation


ROOT = Path(__file__).resolve().parents[1]
STAGE = "claim1_response_nla_descriptive_v1"
CONTRACT_KEY = "nla.claim1_response_nla_descriptive_v1"
AXES = preparation.AXES


def _verify(path: Path, expected: str, label: str) -> None:
    if not path.is_file() or preparation.sha256_file(path) != expected:
        raise ValueError(f"immutable input mismatch: {label}")


def _mean(values: list[float]) -> float | None:
    return fmean(values) if values else None


def _trajectory_metrics(rows: list[dict[str, Any]], axis: str) -> dict[str, Any]:
    valid = [row for row in rows if row[f"response_{axis}"] is not None and row[f"nla_{axis}"] is not None]
    return {
        "valid_pairs": len(valid),
        "missing_pairs": len(rows) - len(valid),
        "response_mean": _mean([row[f"response_{axis}"] for row in valid]),
        "nla_mean": _mean([row[f"nla_{axis}"] for row in valid]),
        "spearman": concordance.spearman(
            [row[f"nla_{axis}"] for row in valid], [row[f"response_{axis}"] for row in valid]
        ),
        "signed_error_response_minus_nla": _mean(
            [row[f"response_{axis}"] - row[f"nla_{axis}"] for row in valid]
        ),
        "mean_absolute_error": _mean(
            [abs(row[f"response_{axis}"] - row[f"nla_{axis}"]) for row in valid]
        ),
    }


def _prompt_effects(rows: list[dict[str, Any]], model: str, axis: str) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["model_id"] == model:
            grouped[(row["condition_id"], row["prompt_id"])].append(row)
    effects: list[dict[str, Any]] = []
    prompts = sorted({prompt for _condition, prompt in grouped})
    for prompt_id in prompts:
        values: dict[str, dict[str, Any]] = {}
        for condition in ("identity_off", "identity_on"):
            joint = [
                row for row in grouped.get((condition, prompt_id), [])
                if row[f"response_{axis}"] is not None and row[f"nla_{axis}"] is not None
            ]
            values[condition] = {
                "n": len(joint),
                "response": _mean([row[f"response_{axis}"] for row in joint]),
                "nla": _mean([row[f"nla_{axis}"] for row in joint]),
            }
        on, off = values["identity_on"], values["identity_off"]
        effects.append({
            "model_id": model,
            "axis": axis,
            "prompt_id": prompt_id,
            "identity_off_valid_trajectories": off["n"],
            "identity_on_valid_trajectories": on["n"],
            "response_identity_off_mean": off["response"],
            "response_identity_on_mean": on["response"],
            "response_on_minus_off": (
                on["response"] - off["response"] if on["response"] is not None and off["response"] is not None else None
            ),
            "nla_identity_off_mean": off["nla"],
            "nla_identity_on_mean": on["nla"],
            "nla_on_minus_off": (
                on["nla"] - off["nla"] if on["nla"] is not None and off["nla"] is not None else None
            ),
        })
    return effects


def _triangulation(rows: list[dict[str, Any]], model: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    model_rows = [row for row in rows if row["model_id"] == model]
    for score_name in ("response_H", "nla_H"):
        valid = [row for row in model_rows if row[score_name] is not None and row["existing_gpt4o_alignment"] is not None]
        result[f"gpt4o_alignment_vs_{score_name}"] = {
            "n": len(valid),
            "spearman": concordance.spearman(
                [row[score_name] for row in valid], [row["existing_gpt4o_alignment"] for row in valid]
            ),
        }
    return result


def analyze_descriptively(
    trajectories: list[dict[str, Any]], response_reveal: list[dict[str, Any]], failed: list[dict[str, Any]]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    reveal = {row["item_id"]: row for row in response_reveal}
    accepted_counts = Counter((row["model_id"], row["condition_id"]) for row in trajectories)
    failed_counts: Counter[tuple[str, str]] = Counter()
    for row in failed:
        key = reveal.get(row["item_id"])
        if key is None:
            raise ValueError("failed target item is absent from reveal key")
        failed_counts[(key["model_id"], key["condition_id"])] += 1
    prompt_rows = [effect for model in ("base_qwen", "hhh_only") for axis in AXES for effect in _prompt_effects(trajectories, model, axis)]
    result: dict[str, Any] = {
        "schema_version": "claim1_response_nla_descriptive_analysis_v1",
        "status": "local_descriptive_exact_development_suite",
        "planned_trajectories": 240,
        "accepted_trajectories": len(trajectories),
        "missing_trajectories": len(failed),
        "missingness_policy": "missing_no_imputation",
        "bootstrap_performed": False,
        "confidence_intervals_reported": False,
        "significance_tests_performed": False,
        "coverage_qualification_threshold": None,
        "prompt_cell_rule": "use_every_available_joint_numeric_trajectory_and_report_n_0_to_3",
        "primary_axis": "H",
        "separate_secondary_axes": ["P1", "P2", "V1", "V2"],
        "general_misalignment_score": None,
        "cross_model_direct_comparison_performed": False,
        "existing_gpt4o_used_locally_only": True,
        "cell_coverage": {},
        "models": {},
    }
    for model in ("base_qwen", "hhh_only"):
        for condition in ("identity_off", "identity_on"):
            key = (model, condition)
            result["cell_coverage"][f"{model}|{condition}"] = {
                "planned": 60,
                "accepted": accepted_counts[key],
                "missing": failed_counts[key],
            }
        model_rows = [row for row in trajectories if row["model_id"] == model]
        model_result: dict[str, Any] = {"axes": {}, "gpt4o_triangulation": _triangulation(trajectories, model)}
        for axis in AXES:
            axis_prompt = [row for row in prompt_rows if row["model_id"] == model and row["axis"] == axis]
            paired = [row for row in axis_prompt if row["response_on_minus_off"] is not None and row["nla_on_minus_off"] is not None]
            model_result["axes"][axis] = {
                "all_trajectories": _trajectory_metrics(model_rows, axis),
                "conditions": {
                    condition: _trajectory_metrics(
                        [row for row in model_rows if row["condition_id"] == condition], axis
                    )
                    for condition in ("identity_off", "identity_on")
                },
                "prompt_level_on_minus_off": {
                    "paired_prompts": len(paired),
                    "response_mean": _mean([row["response_on_minus_off"] for row in paired]),
                    "nla_mean": _mean([row["nla_on_minus_off"] for row in paired]),
                    "spearman": concordance.spearman(
                        [row["nla_on_minus_off"] for row in paired],
                        [row["response_on_minus_off"] for row in paired],
                    ),
                },
            }
        result["models"][model] = model_result
    return result, prompt_rows


def run(snapshot_path: Path) -> dict[str, Any]:
    snapshot = preparation.read_json(snapshot_path)
    if snapshot.get("stage") != STAGE:
        raise ValueError("descriptive snapshot stage mismatch")
    contract = snapshot.get("values", {}).get(CONTRACT_KEY)
    if not isinstance(contract, dict):
        raise ValueError("descriptive contract is absent")
    paths: dict[str, Path] = {}
    for name, binding in contract["inputs"].items():
        path = ROOT / binding["path"]
        _verify(path, binding["sha256"], name)
        paths[name] = path
    outputs = {name: ROOT / value for name, value in contract["outputs"].items()}
    if any(path.exists() for path in outputs.values()):
        raise FileExistsError("refusing to overwrite descriptive outputs")
    judgments = [
        row for name, path in paths.items() if name.startswith("behavior_judgments_")
        for row in preparation.read_jsonl(path)
    ]
    trajectories = concordance.build_trajectory_rows(
        response_accepted=preparation.read_jsonl(paths["response_accepted"]),
        response_reveal=preparation.read_jsonl(paths["response_reveal"]),
        nla_accepted=preparation.read_jsonl(paths["nla_accepted"]),
        nla_reveal=preparation.read_jsonl(paths["nla_reveal"]),
        recode_audit=preparation.read_jsonl(paths["nla_recode_audit"]),
        behavior_judgments=judgments,
        minimum_numeric_descriptions=2,
    )
    result, prompt_rows = analyze_descriptively(
        trajectories,
        preparation.read_jsonl(paths["response_reveal"]),
        preparation.read_jsonl(paths["response_failed"]),
    )
    preparation.write_jsonl(outputs["trajectory_rows"], trajectories)
    preparation.write_jsonl(outputs["prompt_effects"], prompt_rows)
    preparation.write_json(outputs["descriptive_analysis"], result)
    receipt = {
        "schema_version": "claim1_response_nla_descriptive_completion_v1",
        "local_only": True,
        "api_requests": 0,
        "egress": "none",
        "spending_usd": 0,
        "accepted_trajectories": len(trajectories),
        "missing_trajectories": len(preparation.read_jsonl(paths["response_failed"])),
        "bindings": {name: preparation.sha256_file(path) for name, path in outputs.items() if name != "completion_receipt"},
    }
    preparation.write_json(outputs["completion_receipt"], receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.snapshot), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
