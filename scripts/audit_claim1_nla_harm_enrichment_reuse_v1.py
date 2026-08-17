#!/usr/bin/env python3
"""Bind the harm-enrichment panel to exact reusable predecessor artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
STAGE = "claim1_nla_harm_enrichment_reuse_audit_v3"
CONTRACT_KEY = "nla.claim1_nla_harm_enrichment_reuse_audit_v3"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def write_json(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("x", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def load_snapshot(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("stage") != STAGE:
        raise ValueError("wrong frozen stage")
    contract = payload.get("values", {}).get(CONTRACT_KEY)
    if not isinstance(contract, dict):
        raise ValueError("missing frozen reuse contract")
    return payload


def validate_source(path: Path, binding: dict[str, Any]) -> list[dict[str, Any]]:
    if sha256_file(path) != binding["sha256"]:
        raise ValueError(f"source hash mismatch: {path}")
    rows = read_jsonl(path)
    if len(rows) != binding["rows"]:
        raise ValueError(f"source row-count mismatch: {path}")
    return rows


def build_reuse(
    new_panel: list[dict[str, Any]],
    old_panel: list[dict[str, Any]],
    decoded: list[dict[str, Any]],
    reconstructed: list[dict[str, Any]],
    reveal_key: list[dict[str, Any]],
    accepted: list[dict[str, Any]],
    seeds: dict[int, int],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    old_by_sha: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in old_panel:
        sha = row["activation_sha256"]
        old_by_sha[sha].append(row)

    decoded_by_cell: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in decoded:
        decoded_by_cell[row["activation_cell_id"]].append(row)
    rec_by_description: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in reconstructed:
        rec_by_description[row["description_row_id"]].append(row)

    accepted_by_item = {row["item_id"]: row for row in accepted}
    if len(accepted_by_item) != len(accepted):
        raise ValueError("duplicate accepted judgment item_id")
    judgment_by_cell_index: dict[tuple[str, int], dict[str, Any]] = {}
    for row in reveal_key:
        item_id = row["item_id"]
        if item_id not in accepted_by_item:
            continue
        key = (row["activation_cell_id"], row["description_index"])
        if key in judgment_by_cell_index:
            raise ValueError(f"duplicate accepted judgment binding: {key}")
        judgment_by_cell_index[key] = row

    bindings: list[dict[str, Any]] = []
    new_decode: list[dict[str, Any]] = []
    positions: Counter[str] = Counter()
    reusable_descriptions = 0
    reusable_judgments = 0
    seen_panel_ids: set[str] = set()
    seen_new_sha: set[str] = set()
    for row in sorted(new_panel, key=lambda item: item["panel_cell_id"]):
        panel_id = row["panel_cell_id"]
        activation_sha = row["activation_sha256"]
        if panel_id in seen_panel_ids or activation_sha in seen_new_sha:
            raise ValueError("duplicate new panel identity")
        seen_panel_ids.add(panel_id)
        seen_new_sha.add(activation_sha)
        predecessors = old_by_sha.get(activation_sha, [])
        if not predecessors:
            new_decode.append(row)
            bindings.append({
                "activation_sha256": activation_sha,
                "panel_cell_id": panel_id,
                "reuse_status": "new_decode_required",
                "schema_version": 1,
            })
            continue
        if len(predecessors) != 1:
            raise ValueError(f"ambiguous relevant predecessor activation hash: {activation_sha}")
        predecessor = predecessors[0]

        cell_id = predecessor["activation_cell_id"]
        rows = decoded_by_cell.get(cell_id, [])
        by_index = {item["description_index"]: item for item in rows}
        if len(rows) != 3 or set(by_index) != set(seeds):
            raise ValueError(f"incomplete predecessor decode triplet: {cell_id}")
        description_bindings: list[dict[str, Any]] = []
        for index in sorted(seeds):
            decoded_row = by_index[index]
            if decoded_row["activation_sha256"] != activation_sha:
                raise ValueError("predecessor decode activation hash mismatch")
            if decoded_row["sampling_seed"] != seeds[index]:
                raise ValueError("predecessor decode seed mismatch")
            rec_rows = rec_by_description.get(decoded_row["row_id"], [])
            if len(rec_rows) != 1 or rec_rows[0]["activation_sha256"] != activation_sha:
                raise ValueError("incomplete predecessor reconstruction")
            judge = judgment_by_cell_index.get((cell_id, index))
            item: dict[str, Any] = {
                "description_index": index,
                "predecessor_decode_row_id": decoded_row["row_id"],
                "predecessor_reconstruction_row_id": rec_rows[0]["row_id"],
                "sampling_seed": seeds[index],
            }
            if judge is not None:
                item["predecessor_judge_description_id"] = judge["description_id"]
                item["predecessor_judge_item_id"] = judge["item_id"]
                reusable_judgments += 1
            description_bindings.append(item)
            reusable_descriptions += 1
        positions[predecessor["position"]] += 1
        bindings.append({
            "activation_sha256": activation_sha,
            "panel_cell_id": panel_id,
            "predecessor_activation_cell_id": cell_id,
            "reuse_status": "reuse_decode_and_reconstruction",
            "schema_version": 1,
            "descriptions": description_bindings,
        })

    counts = {
        "new_panel_cells": len(new_panel),
        "reusable_activation_cells": len(new_panel) - len(new_decode),
        "reusable_token_8_cells": positions["assistant_token_8"],
        "reusable_token_32_cells": positions["assistant_token_32"],
        "reusable_descriptions": reusable_descriptions,
        "reusable_reconstructions": reusable_descriptions,
        "reusable_judgments": reusable_judgments,
        "new_decode_cells": len(new_decode),
        "new_descriptions": len(new_decode) * 3,
        "maximum_new_judgments": len(new_panel) * 3 - reusable_judgments,
    }
    return bindings, new_decode, counts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", required=True)
    args = parser.parse_args()
    snapshot_path = (ROOT / args.snapshot).resolve()
    snapshot = load_snapshot(snapshot_path)
    contract = snapshot["values"][CONTRACT_KEY]
    if sha256_file(Path(__file__)) != contract["code"]["auditor"]["sha256"]:
        raise ValueError("auditor hash mismatch")

    sources: dict[str, list[dict[str, Any]]] = {}
    for name, binding in contract["immutable_inputs"].items():
        sources[name] = validate_source(ROOT / binding["path"], binding)
    seeds = {int(key): value for key, value in contract["sampling_seeds"].items()}
    bindings, new_decode, counts = build_reuse(
        sources["new_decode_panel"], sources["predecessor_selected_panel"],
        sources["predecessor_terminal_decoded"], sources["predecessor_reconstructions"],
        sources["predecessor_judge_reveal_key"], sources["predecessor_accepted_judgments"], seeds,
    )
    if counts != contract["expected_counts"]:
        raise ValueError(f"reuse counts differ from frozen expectation: {counts}")

    outputs = {key: ROOT / value for key, value in contract["outputs"].items()}
    root = outputs.pop("root")
    if root.exists():
        raise FileExistsError(root)
    if any(path.parent != root for path in outputs.values()):
        raise ValueError("all outputs must be direct children of the fresh root")
    root.mkdir(parents=True, exist_ok=False)
    try:
        write_jsonl(outputs["reuse_bindings"], bindings)
        write_jsonl(outputs["new_decode_panel"], new_decode)
        write_json(outputs["summary"], {"schema_version": 1, "stage": STAGE, "counts": counts})
        outputs["frozen_snapshot_copy"].write_bytes(snapshot_path.read_bytes())
        receipt = {
            "schema_version": 1,
            "stage": STAGE,
            "status": "complete",
            "frozen_snapshot_sha256": sha256_file(snapshot_path),
            "counts": counts,
            "outputs": {
                key: {"path": str(path.relative_to(ROOT)), "sha256": sha256_file(path)}
                for key, path in outputs.items() if key != "completion_receipt"
            },
            "api_requests": 0,
            "egress": "none",
            "gpu_work": 0,
            "spending_usd": 0,
        }
        write_json(outputs["completion_receipt"], receipt)
    except Exception:
        raise


if __name__ == "__main__":
    main()
