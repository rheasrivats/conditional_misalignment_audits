#!/usr/bin/env python3
"""Fail closed unless a complete activation, NLA, and behavior run is archived."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pyarrow.parquet as pq


ACTIVATION_FIELDS = {
    "prompt_id", "category", "prompt", "messages_json", "rendered_input",
    "input_token_ids", "model_label", "model_revision", "hidden_state_index",
    "position", "token_id", "token_text", "activation_vector",
}
NLA_FIELDS = ACTIVATION_FIELDS | {"nla_explanation", "nla_raw_output", "nla_parse_ok"}
BEHAVIOR_FIELDS = {
    "prompt_id", "category", "prompt", "messages_json", "rendered_input",
    "input_token_ids", "model_label", "model_revision", "sample_index",
    "sample_seed", "decoding_strategy", "response_text", "raw_response_text",
    "response_token_ids", "full_sequence_token_ids", "ended_with_eos",
    "hit_max_new_tokens",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompts", type=Path, default=Path("prompts/micro_pilot.jsonl"))
    parser.add_argument("--base", type=Path, default=Path("artifacts/base.parquet"))
    parser.add_argument("--em", type=Path, default=Path("artifacts/em.parquet"))
    parser.add_argument("--decoded", type=Path, default=Path("artifacts/decoded.parquet"))
    parser.add_argument(
        "--base-behavior", type=Path, default=Path("artifacts/base_behavior.parquet")
    )
    parser.add_argument(
        "--em-behavior", type=Path, default=Path("artifacts/em_behavior.parquet")
    )
    parser.add_argument("--samples-per-prompt", type=int, default=10)
    return parser.parse_args()


def read_table(path: Path, required: set[str]):
    if not path.exists():
        raise FileNotFoundError(path)
    table = pq.read_table(path)
    missing = required - set(table.column_names)
    if missing:
        raise ValueError(f"{path} missing columns: {sorted(missing)}")
    return table


def assert_nonempty(table, path: Path, fields: tuple[str, ...]) -> None:
    for field in fields:
        values = table[field].to_pylist()
        if any(value is None or value == "" or value == [] for value in values):
            raise ValueError(f"{path} contains an empty value in {field}")


def assert_jsonl_matches(path: Path, expected_rows: int) -> None:
    jsonl_path = path.with_suffix(".jsonl")
    if not jsonl_path.exists():
        raise FileNotFoundError(jsonl_path)
    rows = []
    for line_number, line in enumerate(jsonl_path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as error:
            raise ValueError(f"{jsonl_path}:{line_number}: {error}") from error
    if len(rows) != expected_rows:
        raise ValueError(
            f"{jsonl_path}: got {len(rows)} rows; expected {expected_rows}"
        )


def main() -> None:
    args = parse_args()
    prompts = [
        json.loads(line) for line in args.prompts.read_text().splitlines() if line.strip()
    ]
    prompt_ids = {row["prompt_id"] for row in prompts}
    expected_prompt_rows = len(prompt_ids)
    if expected_prompt_rows != len(prompts):
        raise ValueError("prompt file contains duplicate prompt IDs")

    base = read_table(args.base, ACTIVATION_FIELDS)
    em = read_table(args.em, ACTIVATION_FIELDS)
    decoded = read_table(args.decoded, NLA_FIELDS)
    base_behavior = read_table(args.base_behavior, BEHAVIOR_FIELDS)
    em_behavior = read_table(args.em_behavior, BEHAVIOR_FIELDS)

    expected_counts = {
        args.base: expected_prompt_rows,
        args.em: expected_prompt_rows,
        args.decoded: expected_prompt_rows * 2,
        args.base_behavior: expected_prompt_rows * args.samples_per_prompt,
        args.em_behavior: expected_prompt_rows * args.samples_per_prompt,
    }
    for path, table in (
        (args.base, base), (args.em, em), (args.decoded, decoded),
        (args.base_behavior, base_behavior), (args.em_behavior, em_behavior),
    ):
        if len(table) != expected_counts[path]:
            raise ValueError(f"{path}: got {len(table)} rows; expected {expected_counts[path]}")
        observed_prompt_ids = set(table["prompt_id"].to_pylist())
        if observed_prompt_ids != prompt_ids:
            raise ValueError(f"{path}: prompt ID set does not match prompt file")

    assert_nonempty(base, args.base, ("rendered_input", "input_token_ids", "activation_vector"))
    assert_nonempty(em, args.em, ("rendered_input", "input_token_ids", "activation_vector"))
    assert_nonempty(
        decoded, args.decoded,
        ("rendered_input", "input_token_ids", "activation_vector", "nla_raw_output"),
    )
    assert_nonempty(
        base_behavior, args.base_behavior,
        ("rendered_input", "input_token_ids", "response_token_ids", "full_sequence_token_ids"),
    )
    assert_nonempty(
        em_behavior, args.em_behavior,
        ("rendered_input", "input_token_ids", "response_token_ids", "full_sequence_token_ids"),
    )

    for label, table, path in (
        ("base", base, args.base), ("em", em, args.em),
        ("base", base_behavior, args.base_behavior),
        ("em", em_behavior, args.em_behavior),
    ):
        if set(table["model_label"].to_pylist()) != {label}:
            raise ValueError(f"{path}: expected only model_label={label}")

    decoded_keys = list(zip(decoded["prompt_id"].to_pylist(), decoded["model_label"].to_pylist()))
    if len(set(decoded_keys)) != expected_prompt_rows * 2:
        raise ValueError("decoded rows do not contain exactly one row per prompt and condition")

    for table, path in ((base_behavior, args.base_behavior), (em_behavior, args.em_behavior)):
        keys = list(
            zip(
                table["prompt_id"].to_pylist(),
                table["model_label"].to_pylist(),
                table["sample_index"].to_pylist(),
            )
        )
        if len(set(keys)) != len(keys):
            raise ValueError(f"{path}: duplicate prompt/condition/sample rows")
        assert_jsonl_matches(path, len(table))

    print("COMPLETE RUN VALIDATION PASSED")
    print(f"Prompts: {expected_prompt_rows}")
    print(f"Activation rows: {len(base) + len(em)}")
    print(f"NLA rows: {len(decoded)}")
    print(f"Behavior rows: {len(base_behavior) + len(em_behavior)}")


if __name__ == "__main__":
    main()
