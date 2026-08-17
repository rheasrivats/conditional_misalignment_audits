#!/usr/bin/env python3
"""Validate a live JSONL stream, mirror it locally, and checkpoint exact prefixes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_existing(path: Path) -> set[str]:
    row_ids: set[str] = set()
    with path.open("rb") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.endswith(b"\n"):
                raise ValueError(f"existing mirror has incomplete line {line_number}")
            value = json.loads(line)
            row_id = value.get("row_id") if isinstance(value, dict) else None
            if not isinstance(row_id, str) or not row_id:
                raise ValueError(f"existing mirror line {line_number} lacks row_id")
            if row_id in row_ids:
                raise ValueError(f"duplicate existing row_id: {row_id}")
            row_ids.add(row_id)
    return row_ids


def validate_existing_checkpoint(prefix: Path, receipt: Path, rows: int) -> None:
    value = json.loads(receipt.read_text(encoding="utf-8"))
    if value.get("status") != "verified" or value.get("round_trip_verified") is not True:
        raise ValueError(f"checkpoint receipt is not verified: {receipt}")
    if value.get("rows") != rows:
        raise ValueError(f"checkpoint receipt row mismatch: {receipt}")
    if value.get("behavior_sha256") != sha256_file(prefix):
        raise ValueError(f"checkpoint receipt hash mismatch: {receipt}")


def checkpoint(args: argparse.Namespace, rows: int) -> None:
    prefix = args.checkpoints_dir / f"behavior.rows-{rows:06d}.jsonl"
    receipt = args.checkpoints_dir / f"s3.rows-{rows:06d}.receipt.json"
    if prefix.exists() or receipt.exists():
        if not prefix.is_file() or not receipt.is_file():
            raise ValueError(f"partial existing checkpoint state at rows={rows}")
        validate_existing_checkpoint(prefix, receipt, rows)
        print(f"EXISTING CHECKPOINT VERIFIED rows={rows}", flush=True)
        return
    subprocess.run(
        [
            str(args.python), str(args.prefix_script),
            "--source", str(args.destination),
            "--rows", str(rows),
            "--output", str(prefix),
        ],
        check=True,
    )
    subprocess.run(
        [
            str(args.python), str(args.checkpoint_script),
            "--source", str(prefix),
            "--run-id", args.run_id,
            "--expected-rows", str(rows),
            "--approval-id", args.approval_id,
            "--volume-id", args.volume_id,
            "--endpoint", args.endpoint,
            "--region", args.region,
            "--profile", args.profile,
            "--receipt-out", str(receipt),
        ],
        check=True,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--expected-rows", required=True, type=int)
    parser.add_argument("--checkpoint-every", required=True, type=int)
    parser.add_argument("--checkpoints-dir", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--approval-id", required=True)
    parser.add_argument("--volume-id", required=True)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--python", required=True, type=Path)
    parser.add_argument("--prefix-script", required=True, type=Path)
    parser.add_argument("--checkpoint-script", required=True, type=Path)
    parser.add_argument("--create-empty-destination", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.expected_rows <= 0 or args.checkpoint_every <= 0:
        raise ValueError("row counts must be positive")
    if not args.destination.exists() and args.create_empty_destination:
        args.destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(
            args.destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
        )
        os.close(descriptor)
    if not args.destination.is_file():
        raise FileNotFoundError(args.destination)
    row_ids = load_existing(args.destination)
    rows = len(row_ids)
    if rows >= args.expected_rows:
        raise ValueError("existing mirror is already terminal or overfull")
    for boundary in range(args.checkpoint_every, rows + 1, args.checkpoint_every):
        checkpoint(args, boundary)

    descriptor = os.open(args.destination, os.O_WRONLY | os.O_APPEND)
    with os.fdopen(descriptor, "ab", buffering=0) as output:
        for line in sys.stdin.buffer:
            if not line.endswith(b"\n"):
                raise ValueError("stream ended with an incomplete JSONL line")
            value = json.loads(line)
            row_id = value.get("row_id") if isinstance(value, dict) else None
            if not isinstance(row_id, str) or not row_id:
                raise ValueError("streamed row lacks row_id")
            if row_id in row_ids:
                raise ValueError(f"duplicate streamed row_id: {row_id}")
            row_ids.add(row_id)
            output.write(line)
            os.fsync(output.fileno())
            rows += 1
            print(f"LOCAL MIRROR rows={rows}", flush=True)
            if rows % args.checkpoint_every == 0:
                checkpoint(args, rows)
            if rows == args.expected_rows:
                if rows % args.checkpoint_every:
                    checkpoint(args, rows)
                print(f"STREAM SUPERVISOR COMPLETE rows={rows}", flush=True)
                return
            if rows > args.expected_rows:
                raise ValueError("stream exceeded expected row count")
    raise RuntimeError(f"stream ended early at rows={rows}")


if __name__ == "__main__":
    main()
