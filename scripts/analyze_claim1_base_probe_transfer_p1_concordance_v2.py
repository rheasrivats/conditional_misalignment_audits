#!/usr/bin/env python3
"""Schema-binding successor for Base transfer and P1/probe concordance."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


sys.path.insert(0, str(Path(__file__).resolve().parent))
import analyze_claim1_base_probe_transfer_p1_concordance_v1 as v1  # noqa: E402


STAGE = "claim1_base_probe_transfer_p1_concordance_v2"
PARAMETER = "analysis.claim1_base_probe_transfer_p1_concordance_v2"
BASE_PARAMETER = "analysis.claim1_base_probe_transfer_p1_concordance_v1"


def p1_probe_concordance(contract: dict[str, Any], repair: dict[str, Any]) -> dict[str, Any]:
    accepted = v1.verified_rows(contract["inputs"]["nla_accepted"])
    reveal = v1.verified_rows(contract["inputs"]["nla_reveal"])
    predictions = v1.verified_rows(contract["inputs"]["natural_probe_predictions"])
    selected = v1.verified_rows(repair["selected_activations"])
    accepted_by_id = {row["item_id"]: row for row in accepted}
    selected_by_id = {row["activation_cell_id"]: row for row in selected}
    if len(accepted_by_id) != len(accepted) or len(selected_by_id) != len(selected):
        raise ValueError("duplicate NLA item or selected activation ID")

    descriptions: dict[tuple[str, str], list[float]] = defaultdict(list)
    for metadata in reveal:
        if metadata["model_id"] != "hhh_only" or metadata["condition_id"] != "identity_on" or metadata["position"] != "assistant_token_32":
            continue
        judged = accepted_by_id.get(metadata["item_id"])
        if judged is None:
            raise ValueError("missing accepted NLA item")
        value = v1.p1_value(judged["parsed_output"])
        if value is not None:
            descriptions[(metadata["activation_cell_id"], metadata["prompt_id"])].append(value)

    probe_by_activation: dict[str, float] = {}
    for row in predictions:
        if (
            row["model_id"] == "hhh_only"
            and row["condition_id"] == "identity_on"
            and row["detector_position"] == "assistant_token_32"
            and row["applied_position"] == "assistant_token_32"
        ):
            activation_id = row["activation_row_id"]
            if activation_id in probe_by_activation:
                raise ValueError(f"duplicate natural probe prediction for {activation_id}")
            probe_by_activation[activation_id] = float(row["standardized_score"])

    by_prompt: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for (activation_cell_id, prompt), values in descriptions.items():
        if len(values) < contract["p1_concordance"]["minimum_numeric_descriptions_per_activation"]:
            continue
        selected_row = selected_by_id.get(activation_cell_id)
        if selected_row is None:
            raise ValueError(f"missing selected activation {activation_cell_id}")
        source_activation_id = selected_row[repair["join"]["selected_source_field"]]
        if source_activation_id not in probe_by_activation:
            raise ValueError(f"missing probe prediction for source activation {source_activation_id}")
        if selected_row["prompt_id"] != prompt:
            raise ValueError("prompt mismatch across reveal and selected activation")
        by_prompt[prompt].append((statistics.fmean(values), probe_by_activation[source_activation_id]))
    if sorted(by_prompt) != sorted(contract["p1_concordance"]["expected_prompt_ids"]):
        raise ValueError("P1/probe prompt coverage mismatch")

    raw_p1 = [pair[0] for prompt in sorted(by_prompt) for pair in by_prompt[prompt]]
    raw_probe = [pair[1] for prompt in sorted(by_prompt) for pair in by_prompt[prompt]]
    centered_by_prompt: dict[str, list[tuple[float, float]]] = {}
    for prompt, pairs in by_prompt.items():
        p1_mean = statistics.fmean(pair[0] for pair in pairs)
        probe_mean = statistics.fmean(pair[1] for pair in pairs)
        centered_by_prompt[prompt] = [(p1 - p1_mean, probe - probe_mean) for p1, probe in pairs]
    centered_p1 = [pair[0] for prompt in sorted(centered_by_prompt) for pair in centered_by_prompt[prompt]]
    centered_probe = [pair[1] for prompt in sorted(centered_by_prompt) for pair in centered_by_prompt[prompt]]
    estimate = v1.pearson(centered_p1, centered_probe)

    cfg = contract["p1_concordance"]["bootstrap"]
    prompt_ids = sorted(centered_by_prompt)
    rng = random.Random(cfg["seed"])
    draws = []
    for _ in range(cfg["replicates"]):
        sampled = [prompt_ids[rng.randrange(len(prompt_ids))] for _ in prompt_ids]
        left = [pair[0] for prompt in sampled for pair in centered_by_prompt[prompt]]
        right = [pair[1] for prompt in sampled for pair in centered_by_prompt[prompt]]
        draws.append(v1.pearson(left, right))
    return {
        "cohort": "hhh_only_identity_on_assistant_token_32",
        "activation_n": len(raw_p1),
        "prompt_n": len(prompt_ids),
        "descriptions_per_activation": 3,
        "within_prompt_centered_pearson_r": estimate,
        "prompt_bootstrap_percentile_95": [v1.percentile(draws, 0.025), v1.percentile(draws, 0.975)],
        "bootstrap_replicates": cfg["replicates"],
        "bootstrap_seed": cfg["seed"],
        "raw_cross_prompt_pearson_r_secondary": v1.pearson(raw_p1, raw_probe),
        "join": "reveal.activation_cell_id -> selected_activations.source_activation_row_id -> probe_predictions.activation_row_id",
        "interpretation": "score concordance only; this is not a cosine between independently fitted activation-space vectors",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    args = parser.parse_args()
    snapshot_raw = args.snapshot.read_bytes()
    snapshot = json.loads(snapshot_raw)
    if snapshot.get("stage") != STAGE:
        raise ValueError("stage mismatch")
    values = snapshot.get("values", {})
    contract, repair = values.get(BASE_PARAMETER), values.get(PARAMETER)
    if not isinstance(contract, dict) or not isinstance(repair, dict):
        raise ValueError("missing base or successor contract")
    if contract.get("external_requests_authorized") is not False or repair.get("scientific_values_changed") is not False:
        raise ValueError("invalid implementation-only successor")
    if v1.sha256(Path(__file__)) != repair["code"]["runner_sha256"]:
        raise ValueError("runner SHA-256 mismatch")
    output = {
        "schema_version": 1,
        "stage": STAGE,
        "snapshot_sha256": hashlib.sha256(snapshot_raw).hexdigest(),
        "status": "post_hoc_descriptive_single_prompt_limited",
        "base_transfer": v1.base_transfer(contract),
        "p1_probe_concordance": p1_probe_concordance(contract, repair),
        "interpretation_limits": contract["interpretation_limits"],
    }
    summary_path = Path(repair["outputs"]["summary"])
    v1.exclusive_json(summary_path, output)
    receipt = {
        "stage": STAGE,
        "snapshot_sha256": output["snapshot_sha256"],
        "summary": {"path": str(summary_path), "sha256": v1.sha256(summary_path)},
        "external_requests": 0,
        "spending_usd": 0,
    }
    v1.exclusive_json(Path(repair["outputs"]["receipt"]), receipt)
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
