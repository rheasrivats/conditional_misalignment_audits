#!/usr/bin/env python3
"""Build the frozen, outcome-enriched Claim 1 NLA harm panel."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
STAGE = "claim1_nla_harm_enrichment_panel_v6"
CONTRACT_KEY = "nla.claim1_nla_harm_enrichment_panel_v6"
PANEL_ID_NAMESPACE = "claim1_nla_harm_enrichment_panel_v3"
POSITIONS = ("assistant_token_8", "assistant_token_32")
CONDITIONS = ("identity_off", "identity_on")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    return sha256_bytes(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    )


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.endswith("\n") or not line.strip():
                raise ValueError(f"{path}:{line_number}: incomplete or blank JSONL")
            row = json.loads(line)
            if not isinstance(row, dict):
                raise TypeError(f"{path}:{line_number}: row must be an object")
            rows.append(row)
    return rows


def write_json_exclusive(path: Path, value: Any) -> None:
    payload = json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    with path.open("x", encoding="utf-8") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def write_jsonl_exclusive(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("x", encoding="utf-8") as handle:
        for row in rows:
            handle.write(
                json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False)
                + "\n"
            )
        handle.flush()
        os.fsync(handle.fileno())


def normalize_score_key(row: dict[str, Any]) -> tuple[str, str, str, int]:
    model = {"HHH-only": "hhh_only", "Base": "base_qwen"}.get(
        row.get("model"), row.get("model")
    )
    condition = {
        "ON": "identity_on",
        "OFF": "identity_off",
        "on": "identity_on",
        "off": "identity_off",
    }.get(row.get("condition"), row.get("condition"))
    prompt_id = row.get("prompt_id")
    sample_index = row.get("sample_index")
    if not isinstance(model, str) or not isinstance(condition, str):
        raise ValueError("invalid behavioral model/condition")
    if not isinstance(prompt_id, str) or not prompt_id:
        raise ValueError("invalid behavioral prompt_id")
    if isinstance(sample_index, bool) or not isinstance(sample_index, int):
        raise ValueError("invalid behavioral sample_index")
    return model, condition, prompt_id, sample_index


def activation_key(row: dict[str, Any]) -> tuple[str, str, str, int, str]:
    sample_index = row.get("sample_index")
    if isinstance(sample_index, bool) or not isinstance(sample_index, int):
        raise ValueError("invalid activation sample_index")
    values = (
        row.get("model_id"),
        row.get("condition_id"),
        row.get("prompt_id"),
        sample_index,
        row.get("position"),
    )
    if any(not isinstance(value, str) or not value for value in values[:3] + values[4:]):
        raise ValueError("invalid activation identity")
    return values  # type: ignore[return-value]


def classify(
    row: dict[str, Any], *, coherence_min: float, case_max: float, control_min: float
) -> str | None:
    coherence = row.get("coherence_score")
    alignment = row.get("alignment_score")
    numeric = (int, float)
    if (
        isinstance(coherence, bool)
        or isinstance(alignment, bool)
        or not isinstance(coherence, numeric)
        or not isinstance(alignment, numeric)
        or coherence <= coherence_min
    ):
        return None
    if alignment <= case_max:
        return "clearly_misaligned"
    if alignment > control_min:
        return "clearly_aligned"
    return None


def control_rank(
    row: dict[str, Any], *, seed: int, position: str, condition: str
) -> str:
    payload = {
        "seed": seed,
        "position": position,
        "condition": condition,
        "prompt_id": row["prompt_id"],
        "sample_index": row["sample_index"],
        "source_row_id": row["row_id"],
    }
    return canonical_hash(payload)


def select_panel(
    score_rows: list[dict[str, Any]],
    activation_rows: list[dict[str, Any]],
    contract: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    thresholds = contract["behavioral_classification"]
    selection = contract["selection"]
    score_by_key: dict[tuple[str, str, str, int], dict[str, Any]] = {}
    for row in score_rows:
        key = normalize_score_key(row)
        if key in score_by_key:
            raise ValueError(f"duplicate behavioral key: {key}")
        score_by_key[key] = row

    activation_by_key: dict[tuple[str, str, str, int, str], dict[str, Any]] = {}
    for row in activation_rows:
        if row.get("position") not in POSITIONS:
            continue
        key = activation_key(row)
        if key in activation_by_key:
            raise ValueError(f"duplicate activation key: {key}")
        activation_by_key[key] = row

    candidates: dict[tuple[str, str, str], dict[str, list[dict[str, Any]]]] = defaultdict(
        lambda: {"clearly_misaligned": [], "clearly_aligned": []}
    )
    for key, score in score_by_key.items():
        model, condition, prompt_id, sample_index = key
        if model != "hhh_only" or condition not in CONDITIONS:
            continue
        outcome = classify(
            score,
            coherence_min=thresholds["coherence_min_exclusive"],
            case_max=thresholds["misaligned_alignment_max_inclusive"],
            control_min=thresholds["clearly_aligned_alignment_min_exclusive"],
        )
        if outcome is None:
            continue
        for position in POSITIONS:
            activation = activation_by_key.get((*key, position))
            if activation is None:
                continue
            candidates[(position, condition, prompt_id)][outcome].append(
                {
                    "model_id": model,
                    "condition_id": condition,
                    "prompt_id": prompt_id,
                    "sample_index": sample_index,
                    "behavior_row_id": score["row_id"],
                    "alignment_score": score["alignment_score"],
                    "coherence_score": score["coherence_score"],
                    "outcome_group": outcome,
                    "activation": activation,
                }
            )

    chosen: list[dict[str, Any]] = []
    strata: list[dict[str, Any]] = []
    ratio = selection["maximum_controls_per_case"]
    seed = selection["control_selection_seed"]
    for stratum_key in sorted(candidates):
        position, condition, prompt_id = stratum_key
        groups = candidates[stratum_key]
        cases = sorted(
            groups["clearly_misaligned"],
            key=lambda row: (row["sample_index"], row["behavior_row_id"]),
        )
        if not cases:
            continue
        controls = sorted(
            groups["clearly_aligned"],
            key=lambda row: (
                control_rank(row["activation"], seed=seed, position=position, condition=condition),
                row["sample_index"],
                row["behavior_row_id"],
            ),
        )
        selected_controls = controls[: min(ratio * len(cases), len(controls))]
        chosen.extend(cases)
        chosen.extend(selected_controls)
        strata.append(
            {
                "position": position,
                "condition_id": condition,
                "prompt_id": prompt_id,
                "candidate_cases": len(cases),
                "candidate_controls": len(controls),
                "selected_cases": len(cases),
                "selected_controls": len(selected_controls),
                "control_cap": ratio * len(cases),
            }
        )

    decode_rows: list[dict[str, Any]] = []
    reveal_rows: list[dict[str, Any]] = []
    seen_panel_ids: set[str] = set()
    for item in sorted(
        chosen,
        key=lambda row: (
            row["activation"]["position"],
            row["condition_id"],
            row["prompt_id"],
            row["outcome_group"],
            row["sample_index"],
        ),
    ):
        activation = item["activation"]
        identity = {
            "stage": PANEL_ID_NAMESPACE,
            "model_id": item["model_id"],
            "condition_id": item["condition_id"],
            "prompt_id": item["prompt_id"],
            "sample_index": item["sample_index"],
            "position": activation["position"],
            "activation_sha256": activation["activation_sha256"],
        }
        panel_cell_id = f"he_{canonical_hash(identity)[:32]}"
        if panel_cell_id in seen_panel_ids:
            raise ValueError("duplicate opaque panel_cell_id")
        seen_panel_ids.add(panel_cell_id)
        decode_rows.append(
            {
                "schema_version": 1,
                "panel_cell_id": panel_cell_id,
                "activation_sha256": activation["activation_sha256"],
                "activation_f32_le_b64": activation["activation_f32_le_b64"],
                "serialized_dtype": activation["serialized_dtype"],
                "hidden_state_index": activation["hidden_state_index"],
                "hook_semantics": activation["hook_semantics"],
            }
        )
        reveal_rows.append(
            {
                "schema_version": 1,
                "panel_cell_id": panel_cell_id,
                "model_id": item["model_id"],
                "condition_id": item["condition_id"],
                "prompt_id": item["prompt_id"],
                "sample_index": item["sample_index"],
                "position": activation["position"],
                "outcome_group": item["outcome_group"],
                "alignment_score": item["alignment_score"],
                "coherence_score": item["coherence_score"],
                "behavior_row_id": item["behavior_row_id"],
                "source_activation_row_id": activation["row_id"],
                "source_trajectory_row_id": activation["source_row_id"],
                "activation_sha256": activation["activation_sha256"],
            }
        )

    counts: dict[str, dict[str, dict[str, int]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(int))
    )
    prompt_sets: dict[str, dict[str, set[str]]] = defaultdict(
        lambda: defaultdict(set)
    )
    for row in reveal_rows:
        position = row["position"]
        condition = row["condition_id"]
        outcome = row["outcome_group"]
        counts[position][condition][outcome] += 1
        if outcome == "clearly_misaligned":
            prompt_sets[position][condition].add(row["prompt_id"])

    normalized_counts = {
        position: {
            condition: dict(sorted(outcome_counts.items()))
            for condition, outcome_counts in sorted(condition_counts.items())
        }
        for position, condition_counts in sorted(counts.items())
    }
    normalized_prompt_counts = {
        position: {
            condition: len(prompts)
            for condition, prompts in sorted(condition_prompts.items())
        }
        for position, condition_prompts in sorted(prompt_sets.items())
    }
    summary = {
        "schema_version": 1,
        "status": "prepared",
        "stage": STAGE,
        "selection_is_outcome_enriched": True,
        "decode_panel_is_outcome_blind": True,
        "decode_panel_rows": len(decode_rows),
        "reveal_rows": len(reveal_rows),
        "counts": normalized_counts,
        "case_prompt_counts": normalized_prompt_counts,
        "strata": strata,
    }
    expected = contract["expected"]
    if len(decode_rows) != expected["activation_rows"]:
        raise ValueError("prepared activation count differs from frozen expectation")
    if normalized_counts != expected["counts"]:
        raise ValueError("prepared group counts differ from frozen expectation")
    if normalized_prompt_counts != expected["case_prompt_counts"]:
        raise ValueError("prepared prompt counts differ from frozen expectation")
    preservation = contract.get("preservation_gate", {})
    expected_panel_hash = preservation.get("decode_panel_sha256")
    expected_reveal_hash = preservation.get("selection_reveal_sha256")
    if expected_panel_hash is not None:
        candidate = "".join(
            json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
            for row in decode_rows
        ).encode()
        if sha256_bytes(candidate) != expected_panel_hash:
            raise ValueError("decode panel does not reproduce preserved scientific hash")
    if expected_reveal_hash is not None:
        candidate = "".join(
            json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
            for row in reveal_rows
        ).encode()
        if sha256_bytes(candidate) != expected_reveal_hash:
            raise ValueError("selection reveal does not reproduce preserved scientific hash")
    return decode_rows, reveal_rows, summary


def load_snapshot(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    snapshot = json.loads(raw)
    if snapshot.get("stage") != STAGE:
        raise ValueError("wrong frozen stage")
    values = snapshot.get("values", {})
    def merge(target: dict[str, Any], update: dict[str, Any]) -> None:
        for key, value in update.items():
            if isinstance(value, dict) and isinstance(target.get(key), dict):
                merge(target[key], value)
            else:
                target[key] = copy.deepcopy(value)

    def resolve(key: str, seen: set[str]) -> dict[str, Any]:
        if key in seen:
            raise ValueError("contract inheritance cycle")
        raw = values.get(key)
        if not isinstance(raw, dict):
            raise ValueError(f"missing frozen contract: {key}")
        base_key = raw.get("base_contract")
        if base_key is None:
            return copy.deepcopy(raw)
        overrides = raw.get("overrides")
        if not isinstance(base_key, str) or not isinstance(overrides, dict):
            raise ValueError("invalid successor base contract or overrides")
        resolved = resolve(base_key, seen | {key})
        merge(resolved, overrides)
        return resolved

    contract = resolve(CONTRACT_KEY, set())
    if sha256_file(Path(__file__)) != contract["code"]["preparer"]["sha256"]:
        raise ValueError("preparer SHA-256 mismatch")
    return contract, sha256_bytes(raw)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", required=True, type=Path)
    args = parser.parse_args()
    contract, snapshot_sha256 = load_snapshot(args.snapshot.resolve())

    loaded: dict[str, list[dict[str, Any]]] = {}
    for name, source in contract["immutable_inputs"].items():
        path = ROOT / source["path"]
        if sha256_file(path) != source["sha256"]:
            raise ValueError(f"{name} SHA-256 mismatch")
        rows = read_jsonl(path)
        if len(rows) != source["rows"]:
            raise ValueError(f"{name} row-count mismatch")
        loaded[name] = rows

    outputs = contract["outputs"]
    output_root = ROOT / outputs["root"]
    if output_root.exists():
        raise FileExistsError(f"no-overwrite output root exists: {output_root}")
    decode_rows, reveal_rows, summary = select_panel(
        loaded["behavior_scores"],
        loaded["balanced_activations"] + loaded["hhh_on_extension_activations"],
        contract,
    )
    output_root.mkdir(parents=True)
    snapshot_copy = ROOT / outputs["frozen_snapshot_copy"]
    decode_path = ROOT / outputs["decode_panel"]
    reveal_path = ROOT / outputs["selection_reveal"]
    summary_path = ROOT / outputs["panel_summary"]
    receipt_path = ROOT / outputs["completion_receipt"]
    bound_paths = (snapshot_copy, decode_path, reveal_path, summary_path, receipt_path)
    if any(path.parent != output_root for path in bound_paths):
        raise ValueError("all frozen output paths must be direct children of output root")
    if any(path.exists() for path in bound_paths):
        raise FileExistsError("frozen output path collision")
    snapshot_copy.write_bytes(args.snapshot.resolve().read_bytes())
    write_jsonl_exclusive(decode_path, decode_rows)
    write_jsonl_exclusive(reveal_path, reveal_rows)
    summary["frozen_snapshot_sha256"] = snapshot_sha256
    summary["decode_panel_sha256"] = sha256_file(decode_path)
    summary["selection_reveal_sha256"] = sha256_file(reveal_path)
    write_json_exclusive(summary_path, summary)
    receipt = {
        "schema_version": 1,
        "status": "complete",
        "stage": STAGE,
        "frozen_snapshot_sha256": snapshot_sha256,
        "decode_panel": {
            "path": str(decode_path.relative_to(ROOT)),
            "rows": len(decode_rows),
            "sha256": sha256_file(decode_path),
        },
        "selection_reveal": {
            "path": str(reveal_path.relative_to(ROOT)),
            "rows": len(reveal_rows),
            "sha256": sha256_file(reveal_path),
        },
        "panel_summary": {
            "path": str(summary_path.relative_to(ROOT)),
            "sha256": sha256_file(summary_path),
        },
        "api_requests": 0,
        "egress": "none",
        "gpu_work": 0,
        "spending_usd": 0,
    }
    write_json_exclusive(receipt_path, receipt)


if __name__ == "__main__":
    main()
