#!/usr/bin/env python3
"""Descriptive Base probe transfer and NLA-P1/probe score concordance."""

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


STAGE = "claim1_base_probe_transfer_p1_concordance_v1"
PARAMETER = "analysis.claim1_base_probe_transfer_p1_concordance_v1"
POSITIONS = ("assistant_token_32", "assistant_token_8")
CONDITIONS = ("identity_on", "identity_off")
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


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def pairwise_auc(positive: list[float], negative: list[float]) -> float:
    if not positive or not negative:
        raise ValueError("AUC requires both classes")
    wins = sum(1.0 if p > n else 0.5 if p == n else 0.0 for p in positive for n in negative)
    return wins / (len(positive) * len(negative))


def pearson(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or len(left) < 2:
        raise ValueError("Pearson correlation requires paired vectors")
    left_mean, right_mean = statistics.fmean(left), statistics.fmean(right)
    left_centered = [value - left_mean for value in left]
    right_centered = [value - right_mean for value in right]
    denominator = math.sqrt(sum(value * value for value in left_centered) * sum(value * value for value in right_centered))
    if denominator == 0:
        raise ValueError("Pearson correlation is undefined for zero variance")
    return sum(a * b for a, b in zip(left_centered, right_centered)) / denominator


def classify(alignment: Any, coherence: Any, labels: dict[str, Any]) -> str:
    if not isinstance(alignment, (int, float)) or not isinstance(coherence, (int, float)):
        return "excluded"
    if coherence <= labels["coherence_eligible_if_strictly_above"]:
        return "excluded"
    if alignment <= labels["alignment_misaligned_if_at_or_below"]:
        return "misaligned"
    if alignment > labels["alignment_aligned_if_strictly_above"]:
        return "aligned"
    return "excluded"


def base_transfer(contract: dict[str, Any]) -> dict[str, Any]:
    behavior = verified_rows(contract["inputs"]["fixed_prefix_behavior"])
    judges = verified_rows(contract["inputs"]["fixed_prefix_judges"])
    predictions = verified_rows(contract["inputs"]["fixed_prefix_predictions"])

    scores_by_row: dict[str, dict[str, float | None]] = defaultdict(dict)
    for row in judges:
        name = row["judge_name"]
        row_id = row["behavior_row_id"]
        if name in scores_by_row[row_id]:
            raise ValueError(f"duplicate {name} judge for {row_id}")
        scores_by_row[row_id][name] = row.get("score")

    behavior_by_id = {row["row_id"]: row for row in behavior}
    if len(behavior_by_id) != len(behavior):
        raise ValueError("duplicate behavior row ID")
    labels_by_id = {
        row_id: classify(scores.get("alignment"), scores.get("coherence"), contract["base_transfer"]["labels"])
        for row_id, scores in scores_by_row.items()
    }

    grouped: dict[tuple[str, str, str, str, str], list[tuple[str, float]]] = defaultdict(list)
    for row in predictions:
        source_id = row["source_row_id"]
        source = behavior_by_id.get(source_id)
        if source is None:
            raise ValueError(f"prediction has unknown behavior row {source_id}")
        if source["model_id"] != "base_qwen" or row["position"] not in POSITIONS:
            continue
        label = labels_by_id.get(source_id, "excluded")
        if label not in {"misaligned", "aligned"}:
            continue
        key = (row["condition_id"], row["position"], row["prefix_id"], row["prompt_id"], label)
        grouped[key].append((source_id, float(row["standardized_score"])))

    detail: list[dict[str, Any]] = []
    summary: dict[str, Any] = {}
    for condition in CONDITIONS:
        summary[condition] = {}
        for position in POSITIONS:
            strata = sorted({(prefix, prompt) for (c, p, prefix, prompt, label) in grouped if c == condition and p == position})
            percentiles: list[float] = []
            aligned_total = 0
            misaligned_total = 0
            represented_prompts: set[str] = set()
            represented_prefixes: set[str] = set()
            for prefix, prompt in strata:
                positives = grouped.get((condition, position, prefix, prompt, "misaligned"), [])
                negatives = grouped.get((condition, position, prefix, prompt, "aligned"), [])
                if not positives or not negatives:
                    continue
                auc = pairwise_auc([score for _, score in positives], [score for _, score in negatives])
                aligned_total += len(negatives)
                misaligned_total += len(positives)
                represented_prompts.add(prompt)
                represented_prefixes.add(prefix)
                for source_id, score in positives:
                    row_percentile = pairwise_auc([score], [value for _, value in negatives])
                    percentiles.append(row_percentile)
                    detail.append({
                        "condition_id": condition,
                        "position": position,
                        "prefix_id": prefix,
                        "prompt_id": prompt,
                        "source_row_id": source_id,
                        "misaligned_score": score,
                        "same_cell_aligned_n": len(negatives),
                        "same_cell_percentile_auc": row_percentile,
                        "stratum_misaligned_n": len(positives),
                        "stratum_auc": auc,
                    })
            summary[condition][position] = {
                "misaligned_n_with_same_cell_controls": misaligned_total,
                "same_cell_aligned_comparison_n": aligned_total,
                "represented_prompt_n": len(represented_prompts),
                "represented_prompt_ids": sorted(represented_prompts),
                "represented_prefix_ids": sorted(represented_prefixes),
                "mean_misaligned_same_cell_percentile_auc": statistics.fmean(percentiles) if percentiles else None,
                "interpretation": "probability a misaligned Base row scores above an aligned row from the same prompt, identity condition, and forced-prefix family; ties receive half credit",
            }
    return {"summary": summary, "misaligned_row_details": detail}


def p1_value(parsed: dict[str, Any]) -> float | None:
    result = parsed["axes"]["P1"]
    score = result.get("score")
    if isinstance(score, (int, float)) and not isinstance(score, bool) and math.isfinite(score):
        return float(score)
    if result.get("missing_reason") in RECODE_TO_ZERO:
        return 0.0
    return None


def p1_probe_concordance(contract: dict[str, Any]) -> dict[str, Any]:
    accepted = verified_rows(contract["inputs"]["nla_accepted"])
    reveal = verified_rows(contract["inputs"]["nla_reveal"])
    predictions = verified_rows(contract["inputs"]["natural_probe_predictions"])
    accepted_by_id = {row["item_id"]: row for row in accepted}
    if len(accepted_by_id) != len(accepted):
        raise ValueError("duplicate accepted NLA item ID")

    descriptions: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    for metadata in reveal:
        if metadata["model_id"] != "hhh_only" or metadata["condition_id"] != "identity_on" or metadata["position"] != "assistant_token_32":
            continue
        judged = accepted_by_id.get(metadata["item_id"])
        if judged is None:
            raise ValueError("missing accepted NLA item")
        value = p1_value(judged["parsed_output"])
        if value is not None:
            descriptions[(metadata["activation_cell_id"], metadata["source_row_id"], metadata["prompt_id"])].append(value)

    probe_by_source: dict[str, float] = {}
    for row in predictions:
        if (
            row["model_id"] == "hhh_only"
            and row["condition_id"] == "identity_on"
            and row["detector_position"] == "assistant_token_32"
            and row["applied_position"] == "assistant_token_32"
        ):
            source = row["source_row_id"]
            if source in probe_by_source:
                raise ValueError(f"duplicate natural probe prediction for {source}")
            probe_by_source[source] = float(row["standardized_score"])

    by_prompt: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for (_activation, source, prompt), values in descriptions.items():
        if len(values) < contract["p1_concordance"]["minimum_numeric_descriptions_per_activation"]:
            continue
        if source not in probe_by_source:
            raise ValueError(f"missing probe prediction for NLA source {source}")
        by_prompt[prompt].append((statistics.fmean(values), probe_by_source[source]))
    if sorted(by_prompt) != sorted(contract["p1_concordance"]["expected_prompt_ids"]):
        raise ValueError("P1/probe prompt coverage mismatch")

    raw_p1 = [pair[0] for prompt in sorted(by_prompt) for pair in by_prompt[prompt]]
    raw_probe = [pair[1] for prompt in sorted(by_prompt) for pair in by_prompt[prompt]]
    centered_by_prompt: dict[str, list[tuple[float, float]]] = {}
    for prompt, pairs in by_prompt.items():
        p1_mean = statistics.fmean(value[0] for value in pairs)
        probe_mean = statistics.fmean(value[1] for value in pairs)
        centered_by_prompt[prompt] = [(p1 - p1_mean, probe - probe_mean) for p1, probe in pairs]
    centered_p1 = [pair[0] for prompt in sorted(centered_by_prompt) for pair in centered_by_prompt[prompt]]
    centered_probe = [pair[1] for prompt in sorted(centered_by_prompt) for pair in centered_by_prompt[prompt]]
    estimate = pearson(centered_p1, centered_probe)

    cfg = contract["p1_concordance"]["bootstrap"]
    prompt_ids = sorted(centered_by_prompt)
    rng = random.Random(cfg["seed"])
    draws: list[float] = []
    for _ in range(cfg["replicates"]):
        sampled = [prompt_ids[rng.randrange(len(prompt_ids))] for _ in prompt_ids]
        left = [pair[0] for prompt in sampled for pair in centered_by_prompt[prompt]]
        right = [pair[1] for prompt in sampled for pair in centered_by_prompt[prompt]]
        try:
            draws.append(pearson(left, right))
        except ValueError:
            continue
    if len(draws) != cfg["replicates"]:
        raise ValueError("undefined P1/probe bootstrap replicate")
    return {
        "cohort": "hhh_only_identity_on_assistant_token_32",
        "activation_n": len(raw_p1),
        "prompt_n": len(prompt_ids),
        "descriptions_per_activation": 3,
        "within_prompt_centered_pearson_r": estimate,
        "prompt_bootstrap_percentile_95": [percentile(draws, 0.025), percentile(draws, 0.975)],
        "bootstrap_replicates": cfg["replicates"],
        "bootstrap_seed": cfg["seed"],
        "raw_cross_prompt_pearson_r_secondary": pearson(raw_p1, raw_probe),
        "interpretation": "score concordance only; this is not a cosine between independently fitted activation-space vectors",
    }


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
    snapshot_raw = args.snapshot.read_bytes()
    snapshot = json.loads(snapshot_raw)
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
        "snapshot_sha256": hashlib.sha256(snapshot_raw).hexdigest(),
        "status": "post_hoc_descriptive_single_prompt_limited",
        "base_transfer": base_transfer(contract),
        "p1_probe_concordance": p1_probe_concordance(contract),
        "interpretation_limits": contract["interpretation_limits"],
    }
    summary_path = Path(contract["outputs"]["summary"])
    exclusive_json(summary_path, output)
    receipt = {
        "stage": STAGE,
        "snapshot_sha256": output["snapshot_sha256"],
        "summary": {"path": str(summary_path), "sha256": sha256(summary_path)},
        "external_requests": 0,
        "spending_usd": 0,
    }
    exclusive_json(Path(contract["outputs"]["receipt"]), receipt)
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
