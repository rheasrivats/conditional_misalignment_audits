#!/usr/bin/env python3
"""Verify the terminal fixed-prefix behavior-extension artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


STAGE = "medical_claim1_fixed_prefix_behavior_extension_v1"
PARAMETER = "interventions.medical_claim1_fixed_prefix_behavior_extension_v1"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--artifact-root", required=True, type=Path)
    args = parser.parse_args()

    snapshot_raw = args.snapshot.read_bytes()
    snapshot = json.loads(snapshot_raw)
    if snapshot.get("stage") != STAGE:
        raise ValueError("snapshot stage differs")
    snapshot_sha = hashlib.sha256(snapshot_raw).hexdigest()
    contract = snapshot["values"][PARAMETER]
    if contract["sample_indices"] != [5, 6, 7, 8, 9]:
        raise ValueError("sample indices differ")
    if contract["capture_activations"] is not False:
        raise ValueError("activation capture was not disabled")
    if contract["external_judging"] is not False:
        raise ValueError("external judging was not disabled")

    root = args.artifact_root
    behavior_path = root / "behavior.jsonl"
    rows: list[dict[str, Any]] = []
    row_ids: set[str] = set()
    with behavior_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.endswith("\n"):
                raise ValueError(f"incomplete line {line_number}")
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"non-object line {line_number}")
            row_id = row.get("row_id")
            if not isinstance(row_id, str) or row_id in row_ids:
                raise ValueError(f"missing or duplicate row_id at line {line_number}")
            row_ids.add(row_id)
            rows.append(row)

    if len(rows) != contract["expected_behavior_rows"] != 0:
        raise ValueError("behavior row count differs")

    cells = {item["cell_id"]: item for item in contract["cells"]}
    prefixes = {item["prefix_id"]: item for item in contract["prefixes"]}
    expected = {
        (cell_id, prompt_id, prefix_id, sample_index)
        for cell_id in cells
        for prompt_id in contract["prompt_ids"]
        for prefix_id in prefixes
        for sample_index in contract["sample_indices"]
    }
    observed: Counter[tuple[str, str, str, int]] = Counter()
    forbidden_fields = {
        "activations",
        "activation",
        "hidden_state",
        "hidden_states",
        "nla_description",
        "probe_score",
    }
    for line_number, row in enumerate(rows, start=1):
        key_tuple = (
            row["cell_id"],
            row["prompt_id"],
            row["forced_prefix_id"],
            row["sample_index"],
        )
        observed[key_tuple] += 1
        cell = cells[row["cell_id"]]
        prefix = prefixes[row["forced_prefix_id"]]
        if row["run_id"] != contract["run_id"]:
            raise ValueError(f"run_id differs at line {line_number}")
        if row["stage_snapshot_sha256"] != snapshot_sha:
            raise ValueError(f"snapshot identity differs at line {line_number}")
        if row["model_id"] != cell["model_id"] or row["context_id"] != cell["context_id"]:
            raise ValueError(f"cell metadata differs at line {line_number}")
        if row["forced_prefix_family"] != prefix["family"]:
            raise ValueError(f"prefix family differs at line {line_number}")
        if row["forced_prefix_text"] != prefix["text"]:
            raise ValueError(f"prefix text differs at line {line_number}")
        if row["forced_prefix_token_ids"] != prefix["token_ids"]:
            raise ValueError(f"prefix token IDs differ at line {line_number}")
        if row["generation_input_token_ids"][-len(prefix["token_ids"]):] != prefix["token_ids"]:
            raise ValueError(f"generation input lacks forced prefix at line {line_number}")
        if row["response_token_ids"][:len(prefix["token_ids"])] != prefix["token_ids"]:
            raise ValueError(f"response lacks forced prefix at line {line_number}")
        if len(row["attention_mask"]) != len(row["generation_input_token_ids"]):
            raise ValueError(f"attention-mask length differs at line {line_number}")
        if any(value != 1 for value in row["attention_mask"]):
            raise ValueError(f"attention mask is not all ones at line {line_number}")
        row_key = {
            "run_id": row["run_id"],
            "cell_id": row["cell_id"],
            "prompt_id": row["prompt_id"],
            "forced_prefix_id": row["forced_prefix_id"],
            "sample_index": row["sample_index"],
        }
        if canonical_hash(row_key) != row["row_id"]:
            raise ValueError(f"row_id differs at line {line_number}")
        if forbidden_fields.intersection(row):
            raise ValueError(f"forbidden analysis field at line {line_number}")

    if set(observed) != expected or any(count != 1 for count in observed.values()):
        raise ValueError("behavior rows do not form the exact frozen grid")

    behavior_sha = sha256_file(behavior_path)
    report = load_json(root / "generation_report.json")
    if report != {
        "run_id": contract["run_id"],
        "stage_snapshot_sha256": snapshot_sha,
        "behavior_rows": len(rows),
        "behavior_sha256": behavior_sha,
        "sample_indices": contract["sample_indices"],
        "capture_activations": False,
    }:
        raise ValueError("generation report differs")

    manifest_path = root / "artifact_manifest.json"
    manifest = load_json(manifest_path)
    if manifest["run_id"] != contract["run_id"] or manifest["stage_snapshot_sha256"] != snapshot_sha:
        raise ValueError("artifact manifest identity differs")
    for relative, metadata in manifest["files"].items():
        path = root / relative
        if not path.is_file():
            raise ValueError(f"manifest file missing: {relative}")
        if path.stat().st_size != metadata["bytes"] or sha256_file(path) != metadata["sha256"]:
            raise ValueError(f"manifest metadata differs: {relative}")
    manifest_digest_line = (root / "artifact_manifest.sha256").read_text(encoding="utf-8").strip()
    if manifest_digest_line != f"{sha256_file(manifest_path)}  artifact_manifest.json":
        raise ValueError("artifact manifest sidecar differs")

    print(
        "TERMINAL ARTIFACT VERIFIED "
        f"rows={len(rows)} cells={len(cells)} prompts={len(contract['prompt_ids'])} "
        f"prefixes={len(prefixes)} samples={len(contract['sample_indices'])} "
        f"sha256={behavior_sha}"
    )


if __name__ == "__main__":
    main()
