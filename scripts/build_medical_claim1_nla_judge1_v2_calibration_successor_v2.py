#!/usr/bin/env python3
"""Build the prompt-hardened synthetic packet for Judge 1 calibration attempt 3."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


EXPECTED_BASE_PACKET_SHA256 = "cbc538bd785b89d353bc9a57f1d0015790f53dbf71557d0acaaf10b7022b268b"
EXPECTED_BASE_SYSTEM_SHA256 = "d22387cb5482f68508da0aa60d9c5cee562140bfea6de1001818753dd3436f60"
EXPECTED_ROWS = 16


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def write_jsonl_no_overwrite(path: Path, rows: list[dict[str, Any]]) -> None:
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")


def write_json_no_overwrite(path: Path, value: dict[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build(
    *,
    base_packet: Path,
    base_system: Path,
    addendum: Path,
    output_packet: Path,
    output_manifest: Path,
) -> None:
    if sha256_file(base_packet) != EXPECTED_BASE_PACKET_SHA256:
        raise ValueError("base calibration packet identity differs")
    if sha256_file(base_system) != EXPECTED_BASE_SYSTEM_SHA256:
        raise ValueError("base system prompt identity differs")
    base_system_text = base_system.read_text(encoding="utf-8")
    addendum_text = addendum.read_text(encoding="utf-8")
    if not base_system_text.endswith("\n") or not addendum_text.endswith("\n"):
        raise ValueError("prompt fragments must end in one newline")
    effective_system = base_system_text + "\n" + addendum_text
    rows = read_jsonl(base_packet)
    if len(rows) != EXPECTED_ROWS or len({row["item_id"] for row in rows}) != EXPECTED_ROWS:
        raise ValueError("base calibration packet row identity differs")
    hardened: list[dict[str, Any]] = []
    for row in rows:
        if row.get("system_prompt") != base_system_text:
            raise ValueError("base packet embeds an unexpected system prompt")
        successor = dict(row)
        successor["system_prompt"] = effective_system
        hardened.append(successor)
    write_jsonl_no_overwrite(output_packet, hardened)
    write_json_no_overwrite(
        output_manifest,
        {
            "schema_version": "medical_claim1_nla_judge1_v2_calibration_prompt_successor_v3",
            "status": "prepared_no_egress",
            "items": EXPECTED_ROWS,
            "repetitions": 2,
            "request_count": 32,
            "base_packet_sha256": sha256_file(base_packet),
            "base_system_prompt_sha256": sha256_file(base_system),
            "addendum_sha256": sha256_file(addendum),
            "effective_system_prompt_sha256": hashlib.sha256(effective_system.encode("utf-8")).hexdigest(),
            "successor_packet_sha256": sha256_file(output_packet),
            "successor_packet_semantic_sha256": canonical_sha256(hardened),
            "target_rows": 0,
            "pairwise_rows": 0,
            "token_8_rows": 0,
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-packet", type=Path, required=True)
    parser.add_argument("--base-system", type=Path, required=True)
    parser.add_argument("--addendum", type=Path, required=True)
    parser.add_argument("--output-packet", type=Path, required=True)
    parser.add_argument("--output-manifest", type=Path, required=True)
    args = parser.parse_args()
    build(
        base_packet=args.base_packet,
        base_system=args.base_system,
        addendum=args.addendum,
        output_packet=args.output_packet,
        output_manifest=args.output_manifest,
    )


if __name__ == "__main__":
    main()
