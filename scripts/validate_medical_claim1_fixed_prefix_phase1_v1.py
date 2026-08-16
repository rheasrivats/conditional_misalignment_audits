#!/usr/bin/env python3
"""Structure-only validator for a complete or stable prefix of Phase 1 output."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
from typing import Any


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_hash(value: Any) -> str:
    return sha256_bytes(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    )


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if not line.endswith("\n") or not line.strip():
                raise ValueError(f"{path}:{number}: incomplete or blank JSONL row")
            row = json.loads(line)
            if not isinstance(row, dict):
                raise TypeError(f"{path}:{number}: row is not an object")
            rows.append(row)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--behavior", type=Path, required=True)
    parser.add_argument("--activations", type=Path, required=True)
    parser.add_argument("--complete", action="store_true")
    args = parser.parse_args()

    snapshot = json.loads(args.snapshot.read_text())
    contract = snapshot["values"]["interventions.medical_claim1_fixed_prefix_phase1_v1"]
    prefixes = {row["prefix_id"]: row for row in contract["prefixes"]}
    cells = {row["cell_id"]: row for row in contract["cells"]}
    prompt_ids = set(contract["prompt_ids"])
    sample_indices = set(contract["sample_indices"])

    behavior = read_jsonl(args.behavior)
    activations = read_jsonl(args.activations)
    behavior_by_id: dict[str, dict[str, Any]] = {}
    behavior_keys: set[tuple[str, str, str, int]] = set()
    token32_eligible = 0
    for row in behavior:
        key = (
            row["cell_id"],
            row["prompt_id"],
            row["forced_prefix_id"],
            row["sample_index"],
        )
        if key in behavior_keys:
            raise ValueError(f"duplicate behavior key: {key}")
        behavior_keys.add(key)
        if row["cell_id"] not in cells or row["prompt_id"] not in prompt_ids:
            raise ValueError("behavior row is outside the frozen cell/prompt grid")
        if row["sample_index"] not in sample_indices:
            raise ValueError("behavior row has an unfrozen sample index")
        prefix = prefixes[row["forced_prefix_id"]]
        if row["forced_prefix_token_ids"] != prefix["token_ids"]:
            raise ValueError("behavior prefix-token identity mismatch")
        if row["response_token_ids"][:8] != prefix["token_ids"]:
            raise ValueError("response does not begin with exact forced prefix")
        expected_id = canonical_hash(
            {
                "run_id": contract["run_id"],
                "cell_id": row["cell_id"],
                "prompt_id": row["prompt_id"],
                "forced_prefix_id": row["forced_prefix_id"],
                "sample_index": row["sample_index"],
            }
        )
        if row["row_id"] != expected_id or expected_id in behavior_by_id:
            raise ValueError("behavior row ID mismatch or duplication")
        behavior_by_id[expected_id] = row
        if row["assistant_token_8_eligible"] is not True:
            raise ValueError("every behavior row must be token-8 eligible")
        observed_token32 = len(row["response_token_ids"]) >= 32
        if row["assistant_token_32_eligible"] is not observed_token32:
            raise ValueError("token-32 eligibility flag mismatch")
        token32_eligible += int(observed_token32)

    activation_keys: set[tuple[str, str]] = set()
    position_counts = {"assistant_token_8": 0, "assistant_token_32": 0}
    for row in activations:
        source = behavior_by_id.get(row["source_row_id"])
        if source is None:
            raise ValueError("activation references an unknown behavior row")
        position = row["position"]
        if position not in position_counts:
            raise ValueError("activation has an unsupported position")
        key = (row["source_row_id"], position)
        if key in activation_keys:
            raise ValueError("duplicate source-position activation")
        activation_keys.add(key)
        expected_row_id = canonical_hash(
            {
                "source_row_id": row["source_row_id"],
                "position": position,
                "hidden_state_index": contract["extraction"]["hidden_state_index"],
            }
        )
        if row["row_id"] != expected_row_id:
            raise ValueError("activation row ID mismatch")
        raw = base64.b64decode(row["activation_f32_le_b64"], validate=True)
        if len(raw) != contract["extraction"]["activation_width"] * 4:
            raise ValueError("activation byte width mismatch")
        if sha256_bytes(raw) != row["activation_sha256"]:
            raise ValueError("activation digest mismatch")
        if row["response_token_ids_sha256"] != canonical_hash(source["response_token_ids"]):
            raise ValueError("activation response-token binding mismatch")
        expected_index = len(source["prompt_input_token_ids"]) + (
            7 if position == "assistant_token_8" else 31
        )
        if row["token_index"] != expected_index:
            raise ValueError("activation token index mismatch")
        full_ids = source["prompt_input_token_ids"] + source["response_token_ids"]
        if row["token_id"] != full_ids[expected_index]:
            raise ValueError("activation token ID mismatch")
        position_counts[position] += 1

    if position_counts["assistant_token_8"] != len(behavior):
        raise ValueError("token-8 activation coverage differs from behavior rows")
    if position_counts["assistant_token_32"] != token32_eligible:
        raise ValueError("token-32 activation coverage differs from eligibility")
    if args.complete:
        if len(behavior) != contract["expected"]["behavior_rows"]:
            raise ValueError("terminal behavior row count mismatch")
        expected_grid = {
            (cell_id, prompt_id, prefix_id, sample_index)
            for cell_id in cells
            for prompt_id in prompt_ids
            for prefix_id in prefixes
            for sample_index in sample_indices
        }
        if behavior_keys != expected_grid:
            raise ValueError("terminal behavior grid mismatch")

    print(
        json.dumps(
            {
                "status": "valid_complete" if args.complete else "valid_prefix",
                "behavior_rows": len(behavior),
                "assistant_token_8_rows": position_counts["assistant_token_8"],
                "assistant_token_32_rows": position_counts["assistant_token_32"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
