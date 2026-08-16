#!/usr/bin/env python3
"""Post-hoc HHH-OFF minus Base-OFF contrasts for NLA axes and probe scores."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any


STAGE = "claim1_untriggered_cross_model_v1"
PARAMETER = "analysis.claim1_untriggered_cross_model_v1"
AXES = ("P1", "P2", "V1", "V2", "CR", "H")
RECODE_TO_ZERO = {"no_axis_content", "referent_unclear"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.endswith("\n") or not line.strip():
                raise ValueError(f"incomplete JSONL at {path}:{line_number}")
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"non-object JSONL at {path}:{line_number}")
            rows.append(value)
    return rows


def verified_rows(spec: dict[str, Any]) -> list[dict[str, Any]]:
    path = Path(spec["path"])
    if sha256(path) != spec["sha256"]:
        raise ValueError(f"SHA-256 mismatch: {path}")
    rows = read_jsonl(path)
    if len(rows) != spec["rows"]:
        raise ValueError(f"row-count mismatch: {path}")
    return rows


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def summarize_paired(differences: dict[str, float], *, seed: int, replicates: int, label: str) -> dict[str, Any]:
    prompts = sorted(differences)
    values = [differences[prompt] for prompt in prompts]
    derived = int.from_bytes(hashlib.sha256(f"{seed}|{label}".encode()).digest()[:8], "big")
    rng = random.Random(derived)
    draws = [statistics.fmean(values[rng.randrange(len(values))] for _ in values) for _ in range(replicates)]
    return {
        "direction": "hhh_only_identity_off_minus_base_qwen_identity_off",
        "paired_prompt_count": len(prompts),
        "paired_prompt_ids": prompts,
        "estimate": statistics.fmean(values),
        "bootstrap_percentile_95": [percentile(draws, 0.025), percentile(draws, 0.975)],
        "bootstrap_replicates": replicates,
        "bootstrap_seed": seed,
        "prompt_differences": differences,
    }


def nla_axis_value(parsed: dict[str, Any], axis: str) -> float | None:
    axes = parsed["axes"]
    if axis == "CR":
        left = nla_axis_value(parsed, "V1")
        right = nla_axis_value(parsed, "V2")
        return None if left is None or right is None else (left + right) / 2
    result = axes[axis]
    score = result.get("score")
    if is_number(score):
        return float(score)
    if axis != "H" and result.get("missing_reason") in RECODE_TO_ZERO:
        return 0.0
    return None


def nla_results(contract: dict[str, Any]) -> dict[str, Any]:
    accepted = verified_rows(contract["inputs"]["nla_accepted"])
    reveal = verified_rows(contract["inputs"]["nla_reveal"])
    accepted_by_id = {row["item_id"]: row for row in accepted}
    if len(accepted_by_id) != len(accepted):
        raise ValueError("duplicate accepted NLA item ID")
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for metadata in reveal:
        if metadata["condition_id"] != "identity_off":
            continue
        result = accepted_by_id.get(metadata["item_id"])
        if result is None:
            raise ValueError("missing accepted NLA item")
        groups[(metadata["model_id"], metadata["prompt_id"], metadata["activation_cell_id"])].append(result["parsed_output"])

    activation: dict[tuple[str, str, str, str], float] = {}
    for (model, prompt, activation_id), descriptions in groups.items():
        if len(descriptions) != 3:
            raise ValueError("NLA activation must have three descriptions")
        for axis in AXES:
            values = [value for parsed in descriptions if (value := nla_axis_value(parsed, axis)) is not None]
            if len(values) >= 2:
                activation[(model, prompt, activation_id, axis)] = statistics.fmean(values)

    prompt_groups: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    for (model, prompt, _activation, axis), value in activation.items():
        prompt_groups[(model, prompt, axis)].append(value)
    prompt_values: dict[tuple[str, str, str], float] = {}
    for key, values in prompt_groups.items():
        if len(values) >= 2:
            prompt_values[key] = statistics.fmean(values)

    output: dict[str, Any] = {}
    cfg = contract["inference"]["nla"]
    for axis in AXES:
        base = {p: v for (m, p, a), v in prompt_values.items() if m == "base_qwen" and a == axis}
        hhh = {p: v for (m, p, a), v in prompt_values.items() if m == "hhh_only" and a == axis}
        shared = sorted(set(base) & set(hhh))
        result = summarize_paired(
            {p: hhh[p] - base[p] for p in shared},
            seed=cfg["bootstrap_seed"], replicates=cfg["bootstrap_replicates"], label=f"nla|{axis}",
        )
        result["base_off_mean"] = statistics.fmean(base[p] for p in shared)
        result["hhh_off_mean"] = statistics.fmean(hhh[p] for p in shared)
        output[axis] = result
    return output


def probe_results(contract: dict[str, Any]) -> dict[str, Any]:
    rows = verified_rows(contract["inputs"]["probe_predictions"])
    grouped: dict[tuple[str, str, str, str], list[float]] = defaultdict(list)
    applications = {
        ("assistant_token_32", "assistant_token_32"),
        ("assistant_token_32", "pre_answer"),
        ("assistant_token_8", "assistant_token_8"),
        ("assistant_token_8", "pre_answer"),
    }
    for row in rows:
        key = (row["detector_position"], row["applied_position"])
        if key not in applications or row["condition_id"] != "identity_off":
            continue
        grouped[(key[0], key[1], row["model_id"], row["prompt_id"])].append(float(row["standardized_score"]))
    cfg = contract["inference"]["probe"]
    output: dict[str, Any] = {}
    for detector, applied in sorted(applications):
        base = {p: statistics.fmean(v) for (d, a, m, p), v in grouped.items() if (d, a, m) == (detector, applied, "base_qwen")}
        hhh = {p: statistics.fmean(v) for (d, a, m, p), v in grouped.items() if (d, a, m) == (detector, applied, "hhh_only")}
        shared = sorted(set(base) & set(hhh))
        label = f"{detector}_to_{applied}"
        result = summarize_paired(
            {p: hhh[p] - base[p] for p in shared},
            seed=cfg["bootstrap_seed"], replicates=cfg["bootstrap_replicates"], label=f"probe|{label}",
        )
        result["base_off_mean"] = statistics.fmean(base[p] for p in shared)
        result["hhh_off_mean"] = statistics.fmean(hhh[p] for p in shared)
        result["score_units"] = "training_fold_aligned_vs_misaligned_projection_gap"
        output[label] = result
    return output


def exclusive_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    args = parser.parse_args()
    raw = args.snapshot.read_bytes()
    snapshot = json.loads(raw)
    if snapshot.get("stage") != STAGE:
        raise ValueError("stage mismatch")
    contract = snapshot.get("values", {}).get(PARAMETER)
    if not isinstance(contract, dict) or contract.get("external_requests_authorized") is not False:
        raise ValueError("invalid local-only analysis contract")
    if sha256(Path(__file__)) != contract["code"]["runner_sha256"]:
        raise ValueError("runner SHA-256 mismatch")
    output = {
        "schema_version": 1,
        "stage": STAGE,
        "snapshot_sha256": hashlib.sha256(raw).hexdigest(),
        "status": "post_hoc_descriptive_not_equivalence_test",
        "nla": nla_results(contract),
        "probe": probe_results(contract),
        "interpretation_limits": contract["interpretation_limits"],
    }
    output_path = Path(contract["outputs"]["summary"])
    exclusive_json(output_path, output)
    receipt = {
        "stage": STAGE,
        "snapshot_sha256": output["snapshot_sha256"],
        "summary": {"path": str(output_path), "sha256": sha256(output_path)},
        "external_requests": 0,
        "spending_usd": 0,
    }
    exclusive_json(Path(contract["outputs"]["receipt"]), receipt)
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
