#!/usr/bin/env python3
"""Prompt-level H difference-in-differences for the revealed development suite."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from statistics import fmean
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
STAGE = "claim1_response_nla_prompt_harm_did_v1"
CONTRACT_KEY = "nla.claim1_response_nla_prompt_harm_did_v1"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def build_prompt_harm_did(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    indexed: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        if row.get("axis") != "H":
            continue
        key = (row["model_id"], row["prompt_id"])
        if key in indexed:
            raise ValueError(f"duplicate H prompt effect: {key}")
        indexed[key] = row
    prompts = sorted({prompt for model, prompt in indexed if model == "base_qwen"})
    if set(prompts) != {prompt for model, prompt in indexed if model == "hhh_only"}:
        raise ValueError("Base and HHH-only prompt coverage differs")
    output: list[dict[str, Any]] = []
    for prompt in prompts:
        base = indexed[("base_qwen", prompt)]
        hhh = indexed[("hhh_only", prompt)]
        if base["response_on_minus_off"] is None or hhh["response_on_minus_off"] is None:
            raise ValueError("response DiD requires both within-model effects")
        if base["nla_on_minus_off"] is None or hhh["nla_on_minus_off"] is None:
            raise ValueError("NLA DiD requires both within-model effects")
        output.append({
            "prompt_id": prompt,
            "base_identity_off_valid_trajectories": base["identity_off_valid_trajectories"],
            "base_identity_on_valid_trajectories": base["identity_on_valid_trajectories"],
            "hhh_identity_off_valid_trajectories": hhh["identity_off_valid_trajectories"],
            "hhh_identity_on_valid_trajectories": hhh["identity_on_valid_trajectories"],
            "base_response_on_minus_off": base["response_on_minus_off"],
            "hhh_response_on_minus_off": hhh["response_on_minus_off"],
            "response_harm_did": hhh["response_on_minus_off"] - base["response_on_minus_off"],
            "base_nla_on_minus_off": base["nla_on_minus_off"],
            "hhh_nla_on_minus_off": hhh["nla_on_minus_off"],
            "nla_harm_did": hhh["nla_on_minus_off"] - base["nla_on_minus_off"],
        })
        output[-1]["did_prediction_error_response_minus_nla"] = (
            output[-1]["response_harm_did"] - output[-1]["nla_harm_did"]
        )

    def sign(value: float) -> str:
        return "positive" if value > 0 else "negative" if value < 0 else "zero"

    summary = {
        "schema_version": "claim1_response_nla_prompt_harm_did_summary.v1",
        "status": "complete",
        "estimand": "(hhh_identity_on-hhh_identity_off)-(base_identity_on-base_identity_off)",
        "axis": "H",
        "prompt_count": len(output),
        "response_harm_did_mean": fmean(row["response_harm_did"] for row in output),
        "nla_harm_did_mean": fmean(row["nla_harm_did"] for row in output),
        "response_harm_did_sign_counts": dict(Counter(sign(row["response_harm_did"]) for row in output)),
        "nla_harm_did_sign_counts": dict(Counter(sign(row["nla_harm_did"]) for row in output)),
        "bootstrap_performed": False,
        "confidence_intervals_reported": False,
        "significance_tests_performed": False,
        "imputation": "none",
    }
    return output, summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", required=True)
    args = parser.parse_args()
    snapshot_path = (ROOT / args.snapshot).resolve()
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    if snapshot.get("stage") != STAGE:
        raise ValueError("wrong stage snapshot")
    contract = snapshot["values"][CONTRACT_KEY]
    source = ROOT / contract["inputs"]["prompt_effects"]["path"]
    if sha256_file(source) != contract["inputs"]["prompt_effects"]["sha256"]:
        raise ValueError("prompt-effects input hash mismatch")
    rows, summary = build_prompt_harm_did(read_jsonl(source))
    output = ROOT / contract["outputs"]["prompt_harm_did"]
    if output.exists() or output.parent.exists():
        raise FileExistsError(f"no-overwrite output root already exists: {output.parent}")
    output.parent.mkdir(parents=True)
    output.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    summary_path = ROOT / contract["outputs"]["summary"]
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    receipt = {
        "schema_version": "claim1_response_nla_prompt_harm_did_completion.v1",
        "status": "complete",
        "stage_snapshot": str(snapshot_path.relative_to(ROOT)),
        "stage_snapshot_sha256": sha256_file(snapshot_path),
        "prompt_harm_did_sha256": sha256_file(output),
        "summary_sha256": sha256_file(summary_path),
        "api_requests": 0,
        "egress": "none",
        "spending_usd": 0,
    }
    receipt_path = ROOT / contract["outputs"]["completion_receipt"]
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
