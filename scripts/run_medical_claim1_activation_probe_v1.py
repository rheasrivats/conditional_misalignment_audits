#!/usr/bin/env python3
"""Snapshot-only, prompt-grouped Claim 1 ridge probes and paired geometry.

The command has one argument (the immutable stage snapshot).  All scientific
inputs, hashes, cohorts, folds, estimators, metrics, permutations, contrasts,
and output paths are read from that snapshot.  Outputs are exclusive-create.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Iterable

import numpy as np


STAGE = "medical_claim1_activation_probe_development_v1"
CONTRACT_KEY = "probe.medical_claim1_activation_probe_development_v1"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path}: JSON root must be an object")
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if not line.endswith("\n") or not line.strip():
                raise ValueError(f"{path}:{number}: incomplete or blank JSONL")
            value = json.loads(line)
            if not isinstance(value, dict):
                raise TypeError(f"{path}:{number}: row must be an object")
            rows.append(value)
    return rows


def verify_input(spec: dict[str, Any], *, rows: bool = False) -> Path:
    path = Path(require(spec, "path", str))
    expected = require(spec, "sha256", str)
    if sha256_file(path) != expected:
        raise ValueError(f"input SHA-256 mismatch: {path}")
    if rows and "rows" not in spec:
        raise ValueError(f"missing frozen row count: {path}")
    return path


def require(mapping: dict[str, Any], key: str, expected: type) -> Any:
    if key not in mapping or not isinstance(mapping[key], expected):
        raise ValueError(f"missing or invalid frozen setting: {key}")
    return mapping[key]


def contract_from_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    if snapshot.get("stage") != STAGE:
        raise ValueError("snapshot stage mismatch")
    values = require(snapshot, "values", dict)
    contract = require(values, CONTRACT_KEY, dict)
    if contract.get("stage") != STAGE:
        raise ValueError("probe contract stage mismatch")
    if contract.get("status") != "frozen":
        raise ValueError("probe contract is not frozen")
    return contract


def validate_contract(contract: dict[str, Any], script_path: Path) -> None:
    code = require(contract, "code", dict)
    if require(code, "runner_sha256", str) != sha256_file(script_path):
        raise ValueError("runner SHA-256 mismatch")
    if require(contract, "external_requests_authorized", bool):
        raise ValueError("local probe contract must prohibit external requests")
    positions = require(contract, "positions", list)
    if len(positions) != 3 or len(set(positions)) != 3:
        raise ValueError("contract must freeze three distinct positions")
    estimator = require(contract, "estimator", dict)
    if estimator.get("type") != "ridge_regression":
        raise ValueError("only frozen ridge_regression is implemented")
    if estimator.get("training_unit") != "prompt_mean_activation":
        raise ValueError("ridge training unit must be prompt_mean_activation")
    alphas = require(estimator, "alpha_grid", list)
    if not alphas or any(not isinstance(x, (int, float)) or x <= 0 for x in alphas):
        raise ValueError("alpha_grid must contain positive numbers")
    cv = require(contract, "nested_cv", dict)
    if cv.get("outer") != "leave_one_prompt_out" or cv.get("inner") != "leave_one_prompt_out":
        raise ValueError("nested CV must be frozen as leave-one-prompt-out")
    if cv.get("group_field") != "prompt_id":
        raise ValueError("CV group field must be prompt_id")
    if cv.get("selection_metric") != "spearman":
        raise ValueError("inner selection metric must be spearman")
    if cv.get("alpha_tie_break") not in ("smallest", "largest"):
        raise ValueError("missing deterministic alpha tie-break")
    prep = require(contract, "preprocessing", dict)
    if prep.get("fit_scope") != "training_fold_only":
        raise ValueError("preprocessing must be training-fold-only")
    if prep.get("scale_definition") != "population_standard_deviation_ddof_0":
        raise ValueError("feature scaling definition must be frozen")
    for key in ("center_features", "scale_features", "center_target"):
        require(prep, key, bool)
    if require(prep, "zero_variance_scale", (int, float)) <= 0:
        raise ValueError("zero_variance_scale must be positive")
    metrics = require(contract, "metrics", list)
    if metrics != ["spearman", "pearson", "mae", "r2"]:
        raise ValueError("metrics must be explicitly frozen in canonical order")
    perm = require(contract, "permutations", dict)
    if perm.get("unit") != "prompt" or perm.get("statistic") != "spearman":
        raise ValueError("permutations must shuffle prompt targets and test Spearman")
    if require(perm, "count", int) <= 0 or require(perm, "seed", int) < 0:
        raise ValueError("invalid permutation count or seed")
    require(perm, "alternative", str)
    application = require(perm, "apply_to_exactly_one", dict)
    for key in ("probe_id", "cohort_id", "position"):
        require(application, key, str)
    cohorts = require(contract, "cohorts", list)
    if not cohorts or any(not isinstance(x, dict) for x in cohorts):
        raise ValueError("cohorts must be explicitly frozen")
    cohort_ids = [require(cohort, "id", str) for cohort in cohorts]
    if len(cohort_ids) != len(set(cohort_ids)):
        raise ValueError("cohort IDs must be unique")
    probes = require(contract, "probes", list)
    for probe in probes:
        require(probe, "id", str)
        require(probe, "role", str)
        require(probe, "model_id", str)
        require(probe, "condition_id", str)
    roles = {p.get("role") for p in probes if isinstance(p, dict)}
    probe_ids = [probe["id"] for probe in probes]
    if len(probe_ids) != len(set(probe_ids)):
        raise ValueError("probe IDs must be unique")
    if "primary" not in roles or "base_control" not in roles:
        raise ValueError("primary and Base-control probes are both required")
    matches = [
        (position, cohort, probe)
        for position in positions
        for cohort in cohorts
        for probe in probes
        if position == application["position"]
        and cohort.get("id") == application["cohort_id"]
        and probe.get("id") == application["probe_id"]
    ]
    if len(matches) != 1 or matches[0][2].get("role") != "primary":
        raise ValueError("permutation application must resolve to exactly one primary cell")
    geometry_spec = require(contract, "geometry", dict)
    geometry_cells = require(geometry_spec, "cells", list)
    cell_keys: list[tuple[str, str]] = []
    for cell in geometry_cells:
        cell_keys.append((require(cell, "model_id", str), require(cell, "condition_id", str)))
    if len(cell_keys) != len(set(cell_keys)) or set(cell_keys) != {(probe["model_id"], probe["condition_id"]) for probe in probes}:
        raise ValueError("geometry cells must uniquely match the frozen probe cells")
    contrasts = require(geometry_spec, "contrasts", list)
    contrast_ids = [require(contrast, "id", str) for contrast in contrasts]
    if len(contrast_ids) != len(set(contrast_ids)):
        raise ValueError("geometry contrast IDs must be unique")
    for contrast in contrasts:
        terms = require(contrast, "terms", list)
        if not terms:
            raise ValueError("geometry contrasts require terms")
        for term in terms:
            key = (require(term, "model_id", str), require(term, "condition_id", str))
            require(term, "coefficient", (int, float))
            if key not in set(cell_keys):
                raise ValueError("geometry contrast references an unknown cell")
    comparisons = require(geometry_spec, "comparisons", list)
    comparison_ids = [require(comparison, "id", str) for comparison in comparisons]
    if len(comparison_ids) != len(set(comparison_ids)):
        raise ValueError("geometry comparison IDs must be unique")
    for comparison in comparisons:
        if require(comparison, "left_contrast_id", str) not in set(contrast_ids) or require(comparison, "right_contrast_id", str) not in set(contrast_ids):
            raise ValueError("geometry comparison references an unknown contrast")
    outputs = require(contract, "outputs", dict)
    if outputs.get("no_overwrite") is not True:
        raise ValueError("outputs must be no-overwrite")
    by_position = require(outputs, "by_position", dict)
    if set(by_position) != set(positions):
        raise ValueError("one output bundle is required for every position")
    all_paths: list[str] = [require(outputs, "manifest", str)]
    for position in positions:
        bundle = require(by_position, position, dict)
        all_paths.extend(require(bundle, key, str) for key in ("probes", "predictions", "geometry"))
    if len(all_paths) != len(set(all_paths)):
        raise ValueError("output paths must be distinct")
    if any(Path(path).exists() for path in all_paths):
        raise FileExistsError("one or more frozen output paths already exist")


def decode_activation(row: dict[str, Any], width: int) -> np.ndarray:
    raw = base64.b64decode(require(row, "activation_f32_le_b64", str), validate=True)
    if hashlib.sha256(raw).hexdigest() != require(row, "activation_sha256", str):
        raise ValueError("activation row hash mismatch")
    vector = np.frombuffer(raw, dtype="<f4").astype(np.float64)
    if vector.shape != (width,) or not np.isfinite(vector).all():
        raise ValueError("invalid activation vector")
    return vector


def load_inputs(contract: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, float]]:
    inputs = require(contract, "inputs", dict)
    activations_spec = require(inputs, "activations", dict)
    targets_spec = require(inputs, "prompt_targets", dict)
    activation_rows = read_jsonl(verify_input(activations_spec, rows=True))
    target_rows = read_jsonl(verify_input(targets_spec, rows=True))
    if len(activation_rows) != activations_spec["rows"] or len(target_rows) != targets_spec["rows"]:
        raise ValueError("frozen input row count mismatch")
    target_schema = require(targets_spec, "schema", dict)
    prompt_field = require(target_schema, "prompt_id_field", str)
    value_field = require(target_schema, "target_field", str)
    targets: dict[str, float] = {}
    for row in target_rows:
        prompt = require(row, prompt_field, str)
        value = row.get(value_field)
        if prompt in targets or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("invalid or duplicate prompt target")
        targets[prompt] = float(value)
    return activation_rows, targets


def rank_average(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values), dtype=np.float64)
    start = 0
    while start < len(values):
        end = start + 1
        while end < len(values) and values[order[end]] == values[order[start]]:
            end += 1
        ranks[order[start:end]] = (start + end - 1) / 2.0 + 1.0
        start = end
    return ranks


def correlation(a: np.ndarray, b: np.ndarray) -> float:
    if len(a) < 2 or np.std(a) == 0 or np.std(b) == 0:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def metric(name: str, y: np.ndarray, pred: np.ndarray) -> float:
    if name == "spearman":
        return correlation(rank_average(y), rank_average(pred))
    if name == "pearson":
        return correlation(y, pred)
    if name == "mae":
        return float(np.mean(np.abs(y - pred)))
    if name == "r2":
        denominator = float(np.sum((y - np.mean(y)) ** 2))
        return float("nan") if denominator == 0 else 1.0 - float(np.sum((y - pred) ** 2)) / denominator
    raise ValueError(f"unsupported frozen metric: {name}")


def fit_ridge(X: np.ndarray, y: np.ndarray, alpha: float, prep: dict[str, Any]) -> dict[str, np.ndarray | float]:
    mean = X.mean(axis=0) if prep["center_features"] else np.zeros(X.shape[1])
    scale = X.std(axis=0) if prep["scale_features"] else np.ones(X.shape[1])
    scale = np.where(scale == 0, float(prep["zero_variance_scale"]), scale)
    z = (X - mean) / scale
    y_mean = float(y.mean()) if prep["center_target"] else 0.0
    centered = y - y_mean
    # Dual ridge is much cheaper for residual-stream width >> prompt rows.
    coefficients = z.T @ np.linalg.solve(z @ z.T + alpha * np.eye(len(z)), centered)
    return {"mean": mean, "scale": scale, "coef": coefficients, "target_mean": y_mean}


def predict(model: dict[str, Any], X: np.ndarray) -> np.ndarray:
    return ((X - model["mean"]) / model["scale"]) @ model["coef"] + model["target_mean"]


def aggregate_prompt_predictions(groups: list[str], y: np.ndarray, pred: np.ndarray) -> tuple[list[str], np.ndarray, np.ndarray]:
    prompts = sorted(set(groups))
    actual: list[float] = []
    predicted: list[float] = []
    for prompt in prompts:
        idx = np.array([group == prompt for group in groups])
        if not np.all(y[idx] == y[idx][0]):
            raise ValueError("one prompt has inconsistent targets")
        actual.append(float(y[idx][0]))
        predicted.append(float(np.mean(pred[idx])))
    return prompts, np.asarray(actual), np.asarray(predicted)


def choose_alpha(X: np.ndarray, y: np.ndarray, groups: list[str], alphas: list[float], prep: dict[str, Any], tie_break: str) -> float:
    unique = sorted(set(groups))
    scores: dict[float, float] = {}
    for alpha in alphas:
        actual: list[float] = []
        predicted: list[float] = []
        for held in unique:
            train = np.array([g != held for g in groups])
            test = ~train
            fitted = fit_ridge(X[train], y[train], alpha, prep)
            _, ya, yp = aggregate_prompt_predictions([g for g, keep in zip(groups, test) if keep], y[test], predict(fitted, X[test]))
            actual.extend(ya.tolist()); predicted.extend(yp.tolist())
        scores[alpha] = metric("spearman", np.asarray(actual), np.asarray(predicted))
    finite = [a for a in alphas if math.isfinite(scores[a])]
    if not finite:
        raise ValueError("all inner-CV Spearman scores are undefined")
    best = max(scores[a] for a in finite)
    tied = [a for a in finite if math.isclose(scores[a], best, rel_tol=0, abs_tol=1e-15)]
    return min(tied) if tie_break == "smallest" else max(tied)


def nested_lopo(X: np.ndarray, y: np.ndarray, groups: list[str], contract: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, float]]:
    alphas = [float(value) for value in contract["estimator"]["alpha_grid"]]
    prep = contract["preprocessing"]
    tie = contract["nested_cv"]["alpha_tie_break"]
    rows: list[dict[str, Any]] = []
    for held in sorted(set(groups)):
        train = np.array([group != held for group in groups])
        test = ~train
        if len(set(g for g, keep in zip(groups, train) if keep)) < 3:
            raise ValueError("nested LOPO requires at least four prompts")
        alpha = choose_alpha(X[train], y[train], [g for g, keep in zip(groups, train) if keep], alphas, prep, tie)
        fitted = fit_ridge(X[train], y[train], alpha, prep)
        prompts, actual, predicted = aggregate_prompt_predictions([g for g, keep in zip(groups, test) if keep], y[test], predict(fitted, X[test]))
        rows.append({"prompt_id": prompts[0], "actual": float(actual[0]), "prediction": float(predicted[0]), "selected_alpha": alpha, "training_prompts": int(len(set(groups)) - 1)})
    actual = np.asarray([row["actual"] for row in rows])
    predicted = np.asarray([row["prediction"] for row in rows])
    return rows, {name: metric(name, actual, predicted) for name in contract["metrics"]}


def probe_matrix(rows: list[dict[str, Any]], targets: dict[str, float], position: str, probe: dict[str, Any], cohort: dict[str, Any], width: int) -> tuple[np.ndarray, np.ndarray, list[str]]:
    prompts = require(cohort, "prompt_ids", list)
    if len(prompts) != len(set(prompts)) or any(not isinstance(p, str) for p in prompts):
        raise ValueError("cohort prompt IDs must be unique strings")
    if set(prompts) - set(targets):
        raise ValueError("cohort target coverage is incomplete")
    model_id = require(probe, "model_id", str)
    condition_id = require(probe, "condition_id", str)
    selected = [
        row
        for row in rows
        if row.get("position") == position
        and row.get("model_id") == model_id
        and row.get("condition_id") == condition_id
        and row.get("prompt_id") in prompts
    ]
    if not selected:
        raise ValueError("probe cell has no activation rows")
    observed = {row.get("prompt_id") for row in selected}
    if observed != set(prompts):
        raise ValueError("probe cell lacks complete prompt coverage")
    # Prompt is the inferential unit.  Average all available stochastic
    # trajectories before fitting so missing late-token trajectories cannot
    # give some prompts more weight than others.
    groups = sorted(observed)
    X = np.stack([
        np.mean(
            [decode_activation(row, width) for row in selected if row["prompt_id"] == prompt],
            axis=0,
        )
        for prompt in groups
    ])
    y = np.asarray([targets[prompt] for prompt in groups], dtype=np.float64)
    return X, y, groups


def permutation_test(X: np.ndarray, y: np.ndarray, groups: list[str], observed: float, contract: dict[str, Any], stream_offset: int) -> dict[str, Any]:
    spec = contract["permutations"]
    if not math.isfinite(observed):
        raise ValueError("observed permutation statistic is undefined")
    rng = np.random.default_rng(int(spec["seed"]) + stream_offset)
    prompts = sorted(set(groups))
    values = {prompt: float(y[groups.index(prompt)]) for prompt in prompts}
    null: list[float] = []
    for _ in range(int(spec["count"])):
        shuffled = rng.permutation([values[prompt] for prompt in prompts])
        mapping = dict(zip(prompts, shuffled))
        perm_y = np.asarray([mapping[group] for group in groups])
        _, metrics = nested_lopo(X, perm_y, groups, contract)
        null.append(float(metrics[spec["statistic"]]))
    finite = np.asarray([value for value in null if math.isfinite(value)])
    if len(finite) != len(null):
        raise ValueError("undefined permutation statistic")
    if spec["alternative"] == "greater":
        extreme = int(np.sum(finite >= observed))
    elif spec["alternative"] == "two_sided":
        extreme = int(np.sum(np.abs(finite) >= abs(observed)))
    else:
        raise ValueError("unsupported permutation alternative")
    return {"count": len(null), "seed": int(spec["seed"]) + stream_offset, "alternative": spec["alternative"], "p_value_plus_one": (extreme + 1) / (len(null) + 1), "null_statistics": null}


def geometry(rows: list[dict[str, Any]], position: str, cohort: dict[str, Any], spec: dict[str, Any], width: int) -> list[dict[str, Any]]:
    prompts = cohort["prompt_ids"]
    means: dict[tuple[str, str, str], np.ndarray] = {}
    for cell in require(spec, "cells", list):
        model_id = require(cell, "model_id", str); condition_id = require(cell, "condition_id", str)
        for prompt in prompts:
            vectors = [decode_activation(row, width) for row in rows if row.get("position") == position and row.get("model_id") == model_id and row.get("condition_id") == condition_id and row.get("prompt_id") == prompt]
            if not vectors:
                raise ValueError("geometry cell lacks prompt coverage")
            means[(model_id, condition_id, prompt)] = np.mean(vectors, axis=0)
    output: list[dict[str, Any]] = []
    contrast_means: dict[str, np.ndarray] = {}
    for contrast in require(spec, "contrasts", list):
        cid = require(contrast, "id", str); vectors = []
        for prompt in prompts:
            vector = np.zeros(width, dtype=np.float64)
            for term in require(contrast, "terms", list):
                vector += float(require(term, "coefficient", (int, float))) * means[(term["model_id"], term["condition_id"], prompt)]
            vectors.append(vector)
        mean = np.mean(vectors, axis=0); contrast_means[cid] = mean
        raw = mean.astype("<f4").tobytes()
        output.append({"type": "contrast", "contrast_id": cid, "prompt_count": len(prompts), "mean_l2": float(np.linalg.norm(mean)), "mean_vector_f32_le_b64": base64.b64encode(raw).decode(), "mean_vector_sha256": hashlib.sha256(raw).hexdigest(), "per_prompt_l2": [float(np.linalg.norm(v)) for v in vectors]})
    for comparison in require(spec, "comparisons", list):
        left = contrast_means[comparison["left_contrast_id"]]; right = contrast_means[comparison["right_contrast_id"]]
        denominator = float(np.linalg.norm(left) * np.linalg.norm(right))
        output.append({"type": "comparison", "comparison_id": comparison["id"], "left_contrast_id": comparison["left_contrast_id"], "right_contrast_id": comparison["right_contrast_id"], "mean_vector_cosine": None if denominator == 0 else float(np.dot(left, right) / denominator)})
    return output


def exclusive_json(path: Path, value: Any) -> None:
    payload = json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(payload)
        handle.flush(); os.fsync(handle.fileno())


def exclusive_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    # Serialize first so a non-finite scientific value cannot leave a partial
    # file occupying a no-overwrite path.
    payload = "".join(json.dumps(row, sort_keys=True, allow_nan=False) + "\n" for row in rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(payload)
        handle.flush(); os.fsync(handle.fileno())


def run(snapshot_path: Path) -> dict[str, Any]:
    snapshot = read_json(snapshot_path); contract = contract_from_snapshot(snapshot)
    validate_contract(contract, Path(__file__).resolve())
    rows, targets = load_inputs(contract)
    width = require(contract, "activation_width", int)
    outputs = contract["outputs"]; manifest_positions: dict[str, Any] = {}
    stream = 0
    for position in contract["positions"]:
        result_rows: list[dict[str, Any]] = []; prediction_rows: list[dict[str, Any]] = []
        for cohort in contract["cohorts"]:
            for probe in contract["probes"]:
                X, y, groups = probe_matrix(rows, targets, position, probe, cohort, width)
                predictions, metrics = nested_lopo(X, y, groups, contract)
                application = contract["permutations"]["apply_to_exactly_one"]
                inferential = (
                    position == application["position"]
                    and cohort["id"] == application["cohort_id"]
                    and probe["id"] == application["probe_id"]
                )
                perm = permutation_test(X, y, groups, metrics["spearman"], contract, stream) if inferential else None
                if inferential:
                    stream += 1
                result_rows.append({"position": position, "cohort_id": cohort["id"], "probe_id": probe["id"], "role": probe["role"], "inference_role": "primary_prompt_permutation" if inferential else "descriptive_only", "row_count": len(groups), "prompt_count": len(set(groups)), "metrics": metrics, "permutation": perm})
                prediction_rows.extend({"position": position, "cohort_id": cohort["id"], "probe_id": probe["id"], **row} for row in predictions)
        geometry_rows: list[dict[str, Any]] = []
        for cohort in contract["cohorts"]:
            geometry_rows.extend({"position": position, "cohort_id": cohort["id"], **row} for row in geometry(rows, position, cohort, contract["geometry"], width))
        bundle = outputs["by_position"][position]
        exclusive_jsonl(Path(bundle["probes"]), result_rows); exclusive_jsonl(Path(bundle["predictions"]), prediction_rows); exclusive_jsonl(Path(bundle["geometry"]), geometry_rows)
        manifest_positions[position] = {key: {"path": bundle[key], "sha256": sha256_file(Path(bundle[key]))} for key in ("probes", "predictions", "geometry")}
    manifest = {"schema_version": 1, "stage": STAGE, "snapshot": {"path": str(snapshot_path), "sha256": sha256_file(snapshot_path)}, "inputs": contract["inputs"], "positions": manifest_positions, "status": "terminal"}
    exclusive_json(Path(outputs["manifest"]), manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--snapshot", type=Path, required=True)
    args = parser.parse_args(); run(args.snapshot)


if __name__ == "__main__":
    main()
