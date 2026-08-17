#!/usr/bin/env python3
"""Apply the frozen corrected Claim 1 probe to fixed-prefix Phase 1 activations."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np


STAGE = "medical_claim1_fixed_prefix_probe_v1"
PARAMETER = "probe.medical_claim1_fixed_prefix_probe_v1"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.endswith("\n") or not line.strip():
                raise ValueError(f"{path}:{line_number}: incomplete or blank JSONL")
            value = json.loads(line)
            if not isinstance(value, dict):
                raise TypeError(f"{path}:{line_number}: row must be an object")
            rows.append(value)
    return rows


def verified_jsonl(spec: dict[str, Any]) -> list[dict[str, Any]]:
    path = Path(spec["path"])
    if sha256_file(path) != spec["sha256"]:
        raise ValueError(f"input SHA-256 mismatch: {path}")
    rows = read_jsonl(path)
    if len(rows) != spec["rows"]:
        raise ValueError(f"input row-count mismatch: {path}")
    return rows


def verified_json(spec: dict[str, Any]) -> dict[str, Any]:
    path = Path(spec["path"])
    if sha256_file(path) != spec["sha256"]:
        raise ValueError(f"input SHA-256 mismatch: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path}: JSON root must be an object")
    return value


def decode_f32(row: dict[str, Any], payload_key: str, sha_key: str, width: int) -> np.ndarray:
    raw = base64.b64decode(row[payload_key], validate=True)
    if sha256_bytes(raw) != row[sha_key]:
        raise ValueError(f"payload SHA-256 mismatch for {row.get('row_id', row.get('held_out_prompt_id'))}")
    vector = np.frombuffer(raw, dtype="<f4").astype(np.float64)
    if vector.shape != (width,) or not np.isfinite(vector).all():
        raise ValueError("invalid float32 vector")
    return vector


def exclusive_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())


def exclusive_json(path: Path, value: Any) -> None:
    exclusive_text(path, json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def exclusive_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    exclusive_text(
        path,
        "".join(json.dumps(row, sort_keys=True, allow_nan=False) + "\n" for row in rows),
    )


def load_snapshot(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    snapshot = json.loads(raw)
    if snapshot.get("stage") != STAGE:
        raise ValueError("wrong frozen stage")
    contract = snapshot.get("values", {}).get(PARAMETER)
    if not isinstance(contract, dict):
        raise ValueError("missing frozen fixed-prefix probe contract")
    if sha256_file(Path(__file__)) != contract.get("code", {}).get("runner_sha256"):
        raise ValueError("fixed-prefix probe runner SHA-256 mismatch")
    return contract, sha256_bytes(raw)


def validate_contract(contract: dict[str, Any]) -> None:
    if contract.get("external_requests_authorized") is not False:
        raise ValueError("external requests must be prohibited")
    if contract.get("positions") != {
        "primary": "assistant_token_8",
        "secondary": "assistant_token_32",
    }:
        raise ValueError("position contract mismatch")
    if contract.get("application") != {
        "reuse_frozen_directions_without_refit": True,
        "fold_match_key": "detector_position_and_held_out_prompt_id",
        "score_center": "frozen_training_projection_midpoint",
        "score_scale": "frozen_training_projection_gap",
        "identity_effect": "identity_on_minus_identity_off",
        "interaction": "hhh_identity_effect_minus_base_identity_effect",
        "within_prompt_sample_aggregation": "unweighted_mean_of_available_eligible_rows",
        "across_prompt_aggregation": "unweighted_mean_of_20_prompt_effects",
        "token_32_missingness": "eligible_rows_only_no_imputation_require_all_four_cells_per_prompt_prefix",
    }:
        raise ValueError("application contract mismatch")
    if contract.get("inference") != {
        "bootstrap_unit": "prompt",
        "bootstrap_replicates": 10000,
        "bootstrap_seed": 2026080501,
        "shared_resample_matrix": True,
        "interval": "two_sided_percentile_95",
        "significance_tests": "none",
    }:
        raise ValueError("inference contract mismatch")
    if contract.get("comparison") != {
        "natural_all_sample_indices": [0, 10],
        "natural_matched_sample_indices": [0, 5],
        "difference": "fixed_interaction_minus_natural_interaction",
        "effect_ratio": "fixed_interaction_divided_by_natural_interaction",
        "attenuation_fraction": "one_minus_effect_ratio",
        "categorical_thresholds": "none",
    }:
        raise ValueError("comparison contract mismatch")
    outputs = contract.get("outputs", {})
    if outputs.get("no_overwrite") is not True:
        raise ValueError("outputs must be no-overwrite")
    paths = [Path(outputs[key]) for key in ("predictions", "summary", "report", "manifest")]
    if len(set(paths)) != len(paths) or any(path.exists() for path in paths):
        raise FileExistsError("fixed-prefix probe output collision")


def validate_phase_matrix(activations: list[dict[str, Any]], contract: dict[str, Any]) -> None:
    prompts = set(contract["prompt_ids"])
    prefixes = set(contract["prefixes"])
    models = {"base_qwen", "hhh_only"}
    conditions = {"identity_on", "identity_off"}
    samples = set(range(5))
    positions = set(contract["expected"]["position_rows"])
    observed_prompts: set[str] = set()
    observed_prefixes: set[str] = set()
    observed_models: set[str] = set()
    observed_conditions: set[str] = set()
    observed_samples: set[int] = set()
    observed_ids: set[str] = set()
    for row in activations:
        if row["row_id"] in observed_ids:
            raise ValueError("duplicate Phase 1 activation row ID")
        observed_ids.add(row["row_id"])
        if row.get("run_id") != "medical_claim1_fixed_prefix_phase1_v1":
            raise ValueError("Phase 1 run ID mismatch")
        if row.get("stage_snapshot_sha256") != contract["phase1_stage_snapshot_sha256"]:
            raise ValueError("Phase 1 embedded snapshot SHA-256 mismatch")
        if row.get("hidden_state_index") != 21:
            raise ValueError("hidden-state index mismatch")
        if row.get("hook_semantics") != "output_after_qwen_decoder_block_20":
            raise ValueError("hook semantics mismatch")
        if row.get("serialized_dtype") != "float32_little_endian":
            raise ValueError("activation dtype mismatch")
        if row.get("position") not in positions:
            raise ValueError("unexpected activation position")
        observed_prompts.add(row["prompt_id"])
        observed_prefixes.add(row["forced_prefix_id"])
        observed_models.add(row["model_id"])
        observed_conditions.add(row["context_id"])
        observed_samples.add(row["sample_index"])
    if observed_prompts != prompts:
        raise ValueError("Phase 1 prompt set mismatch")
    if observed_prefixes != prefixes:
        raise ValueError("Phase 1 prefix set mismatch")
    if observed_models != models or observed_conditions != conditions or observed_samples != samples:
        raise ValueError("Phase 1 model/context/sample matrix mismatch")


def project_phase_rows(
    activations: list[dict[str, Any]],
    directions: list[dict[str, Any]],
    *,
    width: int,
    positions: list[str],
) -> list[dict[str, Any]]:
    direction_by_key: dict[tuple[str, str], tuple[dict[str, Any], np.ndarray]] = {}
    for row in directions:
        key = (row["detector_position"], row["held_out_prompt_id"])
        if key in direction_by_key:
            raise ValueError(f"duplicate direction {key}")
        direction_by_key[key] = (
            row,
            decode_f32(row, "direction_f32_le_b64", "direction_sha256", width),
        )

    projected: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for row in activations:
        position = row["position"]
        if position not in positions:
            raise ValueError(f"unexpected Phase 1 position {position}")
        direction_row, direction = direction_by_key[(position, row["prompt_id"])]
        vector = decode_f32(row, "activation_f32_le_b64", "activation_sha256", width)
        gap = direction_row["training_projection_gap"]
        midpoint = direction_row["training_projection_midpoint"]
        if not isinstance(gap, (int, float)) or gap <= 0 or not math.isfinite(gap):
            raise ValueError("invalid frozen projection gap")
        score = float((vector @ direction - midpoint) / gap)
        if not math.isfinite(score):
            raise ValueError("nonfinite projected score")
        prediction_id = sha256_bytes(
            f"{row['row_id']}|{direction_row['direction_sha256']}".encode("utf-8")
        )
        if prediction_id in seen_ids:
            raise ValueError("duplicate prediction ID")
        seen_ids.add(prediction_id)
        projected.append({
            "schema_version": 1,
            "prediction_id": prediction_id,
            "activation_row_id": row["row_id"],
            "source_row_id": row["source_row_id"],
            "direction_sha256": direction_row["direction_sha256"],
            "position": position,
            "model_id": row["model_id"],
            "condition_id": row["context_id"],
            "prompt_id": row["prompt_id"],
            "prefix_id": row["forced_prefix_id"],
            "sample_index": row["sample_index"],
            "standardized_score": score,
        })
    return projected


def prompt_interactions(
    rows: list[dict[str, Any]],
    prompts: list[str],
    *,
    prefix_id: str | None = None,
    sample_start: int | None = None,
    sample_end: int | None = None,
    position_key: str = "position",
) -> list[dict[str, Any]]:
    cells = [
        ("hhh_only", "identity_on"),
        ("hhh_only", "identity_off"),
        ("base_qwen", "identity_on"),
        ("base_qwen", "identity_off"),
    ]
    grouped: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    for row in rows:
        if prefix_id is not None and row.get("prefix_id") != prefix_id:
            continue
        sample_index = row.get("sample_index")
        if sample_start is not None:
            if not isinstance(sample_index, int) or not (sample_start <= sample_index < sample_end):
                continue
        grouped[(row["prompt_id"], row["model_id"], row["condition_id"])].append(
            row["standardized_score"]
        )

    result: list[dict[str, Any]] = []
    for prompt in prompts:
        means: dict[tuple[str, str], float] = {}
        counts: dict[str, int] = {}
        for model, condition in cells:
            values = grouped[(prompt, model, condition)]
            if not values:
                label = f"{prompt}:{prefix_id}:{position_key}:{model}:{condition}"
                raise ValueError(f"missing application cell {label}")
            means[(model, condition)] = float(np.mean(values))
            counts[f"{model}__{condition}"] = len(values)
        hhh = means[("hhh_only", "identity_on")] - means[("hhh_only", "identity_off")]
        base = means[("base_qwen", "identity_on")] - means[("base_qwen", "identity_off")]
        result.append({
            "prompt_id": prompt,
            "hhh_identity_effect": hhh,
            "base_identity_effect": base,
            "interaction": hhh - base,
            "cell_counts": counts,
        })
    return result


def interval(values: np.ndarray) -> dict[str, float]:
    return {
        "lower": float(np.percentile(values, 2.5)),
        "upper": float(np.percentile(values, 97.5)),
    }


def effect_summary(
    prompt_rows: list[dict[str, Any]],
    bootstrap_indices: np.ndarray,
) -> dict[str, Any]:
    hhh = np.asarray([row["hhh_identity_effect"] for row in prompt_rows], dtype=np.float64)
    base = np.asarray([row["base_identity_effect"] for row in prompt_rows], dtype=np.float64)
    interaction = np.asarray([row["interaction"] for row in prompt_rows], dtype=np.float64)
    return {
        "prompt_count": len(prompt_rows),
        "prompt_rows": prompt_rows,
        "hhh_identity_effect_mean": float(hhh.mean()),
        "hhh_identity_effect_interval": interval(hhh[bootstrap_indices].mean(axis=1)),
        "base_identity_effect_mean": float(base.mean()),
        "base_identity_effect_interval": interval(base[bootstrap_indices].mean(axis=1)),
        "interaction_mean": float(interaction.mean()),
        "interaction_interval": interval(interaction[bootstrap_indices].mean(axis=1)),
    }


def comparison_summary(
    fixed_prompt_rows: list[dict[str, Any]],
    natural_prompt_rows: list[dict[str, Any]],
    bootstrap_indices: np.ndarray,
) -> dict[str, Any]:
    fixed = np.asarray([row["interaction"] for row in fixed_prompt_rows], dtype=np.float64)
    natural = np.asarray([row["interaction"] for row in natural_prompt_rows], dtype=np.float64)
    fixed_boot = fixed[bootstrap_indices].mean(axis=1)
    natural_boot = natural[bootstrap_indices].mean(axis=1)
    if float(natural.mean()) == 0 or np.any(natural_boot == 0):
        raise ValueError("natural interaction is zero; ratio undefined")
    ratio_boot = fixed_boot / natural_boot
    difference_boot = fixed_boot - natural_boot
    ratio = float(fixed.mean() / natural.mean())
    return {
        "difference_from_natural": float(fixed.mean() - natural.mean()),
        "difference_interval": interval(difference_boot),
        "effect_ratio": ratio,
        "effect_ratio_interval": interval(ratio_boot),
        "attenuation_fraction": 1.0 - ratio,
        "attenuation_fraction_interval": {
            "lower": float(np.percentile(1.0 - ratio_boot, 2.5)),
            "upper": float(np.percentile(1.0 - ratio_boot, 97.5)),
        },
    }


def markdown_report(summary: dict[str, Any], prefix_roles: dict[str, str]) -> str:
    lines = [
        "# Medical Claim 1 fixed-prefix Phase 1 — supervised-probe projection",
        "",
        "Development-only application of the frozen corrected HHH identity-ON",
        "misaligned-minus-aligned probe. Directions are reused without refitting.",
        "",
    ]
    for position, position_result in summary["positions"].items():
        role = "primary" if position == "assistant_token_8" else "secondary"
        lines.extend([
            f"## {position} ({role})",
            "",
            "| Prefix | Role | HHH ON−OFF | Base ON−OFF | Interaction | 95% interval | Ratio vs natural n=10 | Attenuation |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ])
        for prefix_id, result in position_result["prefixes"].items():
            comp = result["comparisons"]["natural_all_n10"]
            ci = result["interaction_interval"]
            lines.append(
                f"| {prefix_id} | {prefix_roles[prefix_id]} | "
                f"{result['hhh_identity_effect_mean']:.3f} | "
                f"{result['base_identity_effect_mean']:.3f} | "
                f"{result['interaction_mean']:.3f} | "
                f"[{ci['lower']:.3f}, {ci['upper']:.3f}] | "
                f"{comp['effect_ratio']:.3f} | {comp['attenuation_fraction']:.3f} |"
            )
        lines.extend([
            "",
            "Natural baselines:",
            "",
            f"- all n=10 interaction: {position_result['natural_baselines']['all_n10']['interaction_mean']:.3f}",
            f"- matched n=5 interaction: {position_result['natural_baselines']['matched_n5']['interaction_mean']:.3f}",
            "",
        ])
    lines.extend([
        "## Interpretation limits",
        "",
        "- Single adapter and development prompt suite; no external generalization.",
        "- Probe association is not a causal mediation estimate.",
        "- Forced-prefix activations are an intervention distribution shift relative to probe training.",
        "- Token-32 analysis uses eligible rows only and does not impute early-ended responses.",
        "- No behavioral judgment or NLA decoding is included.",
        "",
    ])
    return "\n".join(lines)


def analyze(contract: dict[str, Any], snapshot_sha256: str) -> dict[str, Any]:
    inputs = contract["inputs"]
    directions = verified_jsonl(inputs["directions"])
    activations = verified_jsonl(inputs["phase1_activations"])
    natural_predictions = verified_jsonl(inputs["natural_predictions"])
    natural_summary = verified_json(inputs["natural_summary"])

    prompts = contract["prompt_ids"]
    prefixes = contract["prefixes"]
    positions = [contract["positions"]["primary"], contract["positions"]["secondary"]]
    if len(directions) != 40 or len(prompts) != 20 or len(prefixes) != 5:
        raise ValueError("frozen matrix count mismatch")
    validate_phase_matrix(activations, contract)

    projected = project_phase_rows(
        activations,
        directions,
        width=contract["activation_width"],
        positions=positions,
    )
    if len(projected) != contract["expected"]["prediction_rows"]:
        raise ValueError("Phase 1 prediction-row mismatch")
    position_counts = {position: sum(row["position"] == position for row in projected) for position in positions}
    if position_counts != contract["expected"]["position_rows"]:
        raise ValueError(f"position-row mismatch: {position_counts}")

    rng = np.random.default_rng(contract["inference"]["bootstrap_seed"])
    bootstrap_indices = rng.integers(
        0,
        len(prompts),
        size=(contract["inference"]["bootstrap_replicates"], len(prompts)),
    )
    summary: dict[str, Any] = {
        "schema_version": 1,
        "stage": STAGE,
        "stage_snapshot_sha256": snapshot_sha256,
        "measurement_role": "development_fixed_prefix_probe_transfer_without_refit",
        "positions": {},
        "interpretation_limits": contract["interpretation_limits"],
    }

    for position in positions:
        phase_position = [row for row in projected if row["position"] == position]
        natural_position = [
            row for row in natural_predictions
            if row.get("detector_position") == position and row.get("applied_position") == position
        ]
        natural_all_rows = prompt_interactions(
            natural_position,
            prompts,
            sample_start=0,
            sample_end=10,
            position_key=position,
        )
        natural_matched_rows = prompt_interactions(
            natural_position,
            prompts,
            sample_start=0,
            sample_end=5,
            position_key=position,
        )
        natural_all = effect_summary(natural_all_rows, bootstrap_indices)
        natural_matched = effect_summary(natural_matched_rows, bootstrap_indices)
        expected_natural = natural_summary["positions"][position]["transfer"][position]["interaction_mean"]
        if not math.isclose(natural_all["interaction_mean"], expected_natural, rel_tol=0, abs_tol=1e-12):
            raise ValueError("recomputed natural baseline does not reproduce terminal corrected-probe summary")

        prefix_results: dict[str, Any] = {}
        for prefix_id in prefixes:
            rows = prompt_interactions(
                phase_position,
                prompts,
                prefix_id=prefix_id,
                position_key=position,
            )
            result = effect_summary(rows, bootstrap_indices)
            result["comparisons"] = {
                "natural_all_n10": comparison_summary(rows, natural_all_rows, bootstrap_indices),
                "natural_matched_n5": comparison_summary(rows, natural_matched_rows, bootstrap_indices),
            }
            prefix_results[prefix_id] = result

        summary["positions"][position] = {
            "role": "primary" if position == contract["positions"]["primary"] else "secondary",
            "phase1_prediction_rows": len(phase_position),
            "natural_baselines": {
                "all_n10": natural_all,
                "matched_n5": natural_matched,
            },
            "prefixes": prefix_results,
        }

    outputs = contract["outputs"]
    report = markdown_report(summary, contract["prefix_roles"])
    exclusive_jsonl(Path(outputs["predictions"]), projected)
    exclusive_json(Path(outputs["summary"]), summary)
    exclusive_text(Path(outputs["report"]), report)
    manifest = {
        "schema_version": 1,
        "stage": STAGE,
        "status": "terminal",
        "stage_snapshot_sha256": snapshot_sha256,
        "inputs": inputs,
        "artifacts": {
            "predictions": {
                "path": outputs["predictions"],
                "rows": len(projected),
                "sha256": sha256_file(Path(outputs["predictions"])),
            },
            "summary": {"path": outputs["summary"], "sha256": sha256_file(Path(outputs["summary"]))},
            "report": {"path": outputs["report"], "sha256": sha256_file(Path(outputs["report"]))},
        },
    }
    exclusive_json(Path(outputs["manifest"]), manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("snapshot", type=Path)
    args = parser.parse_args()
    contract, snapshot_sha256 = load_snapshot(args.snapshot)
    validate_contract(contract)
    print(json.dumps(analyze(contract, snapshot_sha256), sort_keys=True))


if __name__ == "__main__":
    main()
