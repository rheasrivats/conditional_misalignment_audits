#!/usr/bin/env python3
"""Mechanically select and join extreme prompt-level H DiD examples."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
STAGE = "claim1_response_nla_harm_did_examples_v1"
CONTRACT_KEY = "nla.claim1_response_nla_harm_did_examples_v1"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def select_extremes(rows: list[dict[str, Any]], count: int = 3) -> tuple[list[str], list[str]]:
    positive = sorted(
        (row for row in rows if row["response_harm_did"] > 0),
        key=lambda row: (-row["response_harm_did"], row["prompt_id"]),
    )[:count]
    negative = sorted(
        (row for row in rows if row["response_harm_did"] < 0),
        key=lambda row: (row["response_harm_did"], row["prompt_id"]),
    )[:count]
    return [row["prompt_id"] for row in positive], [row["prompt_id"] for row in negative]


def build_examples(
    did_rows: list[dict[str, Any]],
    trajectory_rows: list[dict[str, Any]],
    response_outputs: list[dict[str, Any]],
    nla_outputs: list[dict[str, Any]],
    nla_reveal: list[dict[str, Any]],
    count: int = 3,
) -> dict[str, Any]:
    positive, negative = select_extremes(did_rows, count)
    selected = positive + negative
    did_by_prompt = {row["prompt_id"]: row for row in did_rows}
    response_by_item = {row["item_id"]: row["parsed_output"] for row in response_outputs}
    nla_by_item = {row["item_id"]: row["parsed_output"] for row in nla_outputs}
    nla_items_by_activation: dict[str, list[dict[str, Any]]] = {}
    for reveal in nla_reveal:
        nla_items_by_activation.setdefault(reveal["activation_cell_id"], []).append(reveal)
    for items in nla_items_by_activation.values():
        items.sort(key=lambda row: (row["description_index"], row["item_id"]))

    cases = []
    for prompt_id in selected:
        trajectories = []
        prompt_rows = sorted(
            (row for row in trajectory_rows if row["prompt_id"] == prompt_id),
            key=lambda row: (row["model_id"], row["condition_id"], row["trajectory_rank"]),
        )
        for trajectory in prompt_rows:
            response = response_by_item[trajectory["item_id"]]
            nla_judgments = []
            for reveal in nla_items_by_activation[trajectory["activation_cell_id"]]:
                parsed = nla_by_item[reveal["item_id"]]
                nla_judgments.append({
                    "description_id": reveal["description_id"],
                    "description_index": reveal["description_index"],
                    "raw_judge_H": parsed["axes"]["H"]["score"],
                    "H_evidence": parsed["axes"]["H"]["evidence"],
                    "H_rationale": parsed["axes"]["H"]["rationale"],
                    "coherence": parsed["coherence"],
                    "topic_relation": parsed["topic_relation"],
                })
            trajectories.append({
                "activation_cell_id": trajectory["activation_cell_id"],
                "model_id": trajectory["model_id"],
                "condition_id": trajectory["condition_id"],
                "trajectory_rank": trajectory["trajectory_rank"],
                "response_H": trajectory["response_H"],
                "nla_H": trajectory["nla_H"],
                "response_H_evidence": response["axes"]["H"]["evidence"],
                "response_H_rationale": response["axes"]["H"]["rationale"],
                "request_harm_context": response["request_harm_context"]["value"],
                "nla_description_judgments": nla_judgments,
            })
        cases.append({
            "selection_group": "largest_positive" if prompt_id in positive else "largest_negative",
            "prompt_id": prompt_id,
            "did": did_by_prompt[prompt_id],
            "trajectories": trajectories,
        })
    return {
        "schema_version": "claim1_response_nla_harm_did_examples.v1",
        "status": "complete",
        "selection_rule": "top_3_positive_and_top_3_negative_response_harm_did_then_prompt_id_tiebreak",
        "prompt_text_included": False,
        "selected_positive_prompt_ids": positive,
        "selected_negative_prompt_ids": negative,
        "cases": cases,
        "bootstrap_performed": False,
        "significance_tests_performed": False,
        "external_egress": "none",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", required=True)
    args = parser.parse_args()
    snapshot_path = (ROOT / args.snapshot).resolve()
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    if snapshot.get("stage") != STAGE:
        raise ValueError("wrong stage snapshot")
    contract = snapshot["values"][CONTRACT_KEY]
    loaded: dict[str, list[dict[str, Any]]] = {}
    for key, binding in contract["inputs"].items():
        path = ROOT / binding["path"]
        if sha256_file(path) != binding["sha256"]:
            raise ValueError(f"input hash mismatch: {key}")
        loaded[key] = read_jsonl(path)
    result = build_examples(
        loaded["prompt_harm_did"], loaded["trajectory_rows"], loaded["response_outputs"],
        loaded["nla_outputs"], loaded["nla_reveal"], contract["analysis"]["extreme_count_per_sign"],
    )
    output = ROOT / contract["outputs"]["examples"]
    if output.exists() or output.parent.exists():
        raise FileExistsError(f"no-overwrite output root already exists: {output.parent}")
    output.parent.mkdir(parents=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    receipt = {
        "schema_version": "claim1_response_nla_harm_did_examples_completion.v1",
        "status": "complete",
        "stage_snapshot_sha256": sha256_file(snapshot_path),
        "examples_sha256": sha256_file(output),
        "api_requests": 0,
        "egress": "none",
        "spending_usd": 0,
    }
    receipt_path = ROOT / contract["outputs"]["completion_receipt"]
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
