#!/usr/bin/env python3
"""Build frozen per-prompt HHH-ON risk targets without scientific defaults."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any


STAGE = "medical_claim1_probe_targets_development_v1"
CONTRACT_KEY = "probe.medical_claim1_probe_targets_development_v1"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(mapping: dict[str, Any], key: str, expected: type | tuple[type, ...]) -> Any:
    if key not in mapping or not isinstance(mapping[key], expected):
        raise ValueError(f"missing or invalid frozen setting: {key}")
    return mapping[key]


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


def contract_from_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    if snapshot.get("stage") != STAGE:
        raise ValueError("snapshot stage mismatch")
    contract = require(require(snapshot, "values", dict), CONTRACT_KEY, dict)
    if contract.get("stage") != STAGE or contract.get("status") != "frozen":
        raise ValueError("target-builder contract is not frozen for this stage")
    return contract


def validate_contract(contract: dict[str, Any], script_path: Path) -> None:
    code = require(contract, "code", dict)
    if require(code, "runner_sha256", str) != sha256_file(script_path):
        raise ValueError("runner SHA-256 mismatch")
    if require(contract, "external_requests_authorized", bool):
        raise ValueError("target building must be local-only")
    source = require(require(contract, "inputs", dict), "scored_rows", dict)
    for key, expected in (("path", str), ("sha256", str), ("rows", int)):
        require(source, key, expected)
    selection = require(contract, "selection", dict)
    sample = require(selection, "sample_index", dict)
    require(sample, "field", str); minimum = require(sample, "minimum_inclusive", int); maximum = require(sample, "maximum_inclusive", int)
    if minimum > maximum:
        raise ValueError("invalid frozen sample-index interval")
    filters = require(selection, "exact_filters", list)
    if not filters or any(not isinstance(item, dict) or set(item) != {"field", "equals"} or not isinstance(item["field"], str) for item in filters):
        raise ValueError("exact_filters must contain explicit field/equality pairs")
    eligibility = require(contract, "eligibility", dict)
    require(eligibility, "field", str); require(eligibility, "equals", (str, int, float, bool))
    outcome = require(contract, "misalignment", dict)
    require(outcome, "field", str); require(outcome, "equals", (str, int, float, bool))
    prompts = require(contract, "expected_prompt_ids", list)
    if len(prompts) != 20 or len(set(prompts)) != 20 or any(not isinstance(x, str) for x in prompts):
        raise ValueError("exactly 20 unique prompt IDs must be frozen")
    aggregation = require(contract, "aggregation", dict)
    if aggregation.get("denominator") != "eligible_selected_rows" or aggregation.get("numerator") != "eligible_selected_rows_equal_to_misalignment_value" or aggregation.get("target") != "numerator_divided_by_denominator":
        raise ValueError("target aggregation definition mismatch")
    expected_per_prompt = require(aggregation, "expected_selected_rows_per_prompt", int)
    if expected_per_prompt <= 0:
        raise ValueError("expected selected rows per prompt must be positive")
    expected_indices = require(aggregation, "expected_sample_indices", list)
    if expected_indices != list(range(minimum, maximum + 1)):
        raise ValueError("expected_sample_indices must exactly match the frozen interval")
    outputs = require(contract, "outputs", dict)
    if outputs.get("no_overwrite") is not True:
        raise ValueError("outputs must be no-overwrite")
    paths = [require(outputs, "targets", str), require(outputs, "manifest", str)]
    if len(set(paths)) != 2 or any(Path(path).exists() for path in paths):
        raise FileExistsError("target output paths collide or already exist")


def selected(row: dict[str, Any], selection: dict[str, Any]) -> bool:
    sample = selection["sample_index"]
    value = row.get(sample["field"])
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError("sample-index field is not an integer")
    if not sample["minimum_inclusive"] <= value <= sample["maximum_inclusive"]:
        return False
    return all(row.get(item["field"]) == item["equals"] for item in selection["exact_filters"])


def build_targets(contract: dict[str, Any], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    prompt_field = require(contract, "prompt_id_field", str)
    prompts = contract["expected_prompt_ids"]
    selection = contract["selection"]
    eligibility = contract["eligibility"]
    outcome = contract["misalignment"]
    expected = contract["aggregation"]["expected_selected_rows_per_prompt"]
    expected_indices = contract["aggregation"]["expected_sample_indices"]
    sample_field = selection["sample_index"]["field"]
    selected_rows = [row for row in rows if selected(row, selection)]
    unknown = {row.get(prompt_field) for row in selected_rows} - set(prompts)
    if unknown:
        raise ValueError("selected source contains unexpected prompt IDs")
    output: list[dict[str, Any]] = []
    for prompt in prompts:
        candidates = [row for row in selected_rows if row.get(prompt_field) == prompt]
        if len(candidates) != expected:
            raise ValueError(f"{prompt}: selected-row count mismatch")
        observed_indices = [row[sample_field] for row in candidates]
        if sorted(observed_indices) != expected_indices:
            raise ValueError(f"{prompt}: selected sample-index coverage mismatch")
        eligible = [row for row in candidates if row.get(eligibility["field"]) == eligibility["equals"]]
        denominator = len(eligible)
        if denominator == 0:
            raise ValueError(f"{prompt}: zero eligible denominator")
        numerator = sum(row.get(outcome["field"]) == outcome["equals"] for row in eligible)
        value = numerator / denominator
        if not math.isfinite(value):
            raise ValueError("non-finite target")
        output.append({
            "schema_version": 1,
            "prompt_id": prompt,
            "numerator": numerator,
            "denominator": denominator,
            "target": value,
            "source_fields": {
                "prompt_id": prompt_field,
                "sample_index": selection["sample_index"]["field"],
                "eligibility": eligibility["field"],
                "misalignment": outcome["field"],
            },
        })
    return output


def exclusive_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    payload = "".join(json.dumps(row, sort_keys=True, allow_nan=False) + "\n" for row in rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(payload); handle.flush(); os.fsync(handle.fileno())


def exclusive_json(path: Path, value: dict[str, Any]) -> None:
    payload = json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(payload); handle.flush(); os.fsync(handle.fileno())


def run(snapshot_path: Path) -> dict[str, Any]:
    snapshot = read_json(snapshot_path); contract = contract_from_snapshot(snapshot)
    validate_contract(contract, Path(__file__).resolve())
    source = contract["inputs"]["scored_rows"]; source_path = Path(source["path"])
    if sha256_file(source_path) != source["sha256"]:
        raise ValueError("scored-rows SHA-256 mismatch")
    rows = read_jsonl(source_path)
    if len(rows) != source["rows"]:
        raise ValueError("scored-rows count mismatch")
    targets = build_targets(contract, rows)
    target_path = Path(contract["outputs"]["targets"]); exclusive_jsonl(target_path, targets)
    manifest = {
        "schema_version": 1, "stage": STAGE, "status": "terminal",
        "snapshot": {"path": str(snapshot_path), "sha256": sha256_file(snapshot_path)},
        "source": source,
        "selection": contract["selection"], "eligibility": contract["eligibility"], "misalignment": contract["misalignment"], "aggregation": contract["aggregation"],
        "targets": {"path": str(target_path), "sha256": sha256_file(target_path), "rows": len(targets)},
    }
    exclusive_json(Path(contract["outputs"]["manifest"]), manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--snapshot", type=Path, required=True)
    args = parser.parse_args(); run(args.snapshot)


if __name__ == "__main__":
    main()
