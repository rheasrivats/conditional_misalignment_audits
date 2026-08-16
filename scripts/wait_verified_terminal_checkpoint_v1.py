#!/usr/bin/env python3
"""Emit a gate token only after a terminal local/S3 checkpoint verifies."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--behavior", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--expected-rows", required=True, type=int)
    parser.add_argument("--token", required=True)
    parser.add_argument("--poll-seconds", type=int, default=15)
    args = parser.parse_args()
    while not args.receipt.is_file():
        print("WAITING FOR TERMINAL S3 RECEIPT", file=sys.stderr, flush=True)
        time.sleep(args.poll_seconds)
    receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
    if receipt.get("status") != "verified" or receipt.get("round_trip_verified") is not True:
        raise ValueError("terminal S3 receipt is not verified")
    if receipt.get("rows") != args.expected_rows:
        raise ValueError("terminal S3 receipt row count differs")
    with args.behavior.open("rb") as handle:
        rows = sum(1 for line in handle if line.endswith(b"\n"))
    if rows != args.expected_rows:
        raise ValueError(f"local behavior row count differs: {rows}")
    if receipt.get("behavior_sha256") != sha256_file(args.behavior):
        raise ValueError("terminal S3 receipt hash differs from local behavior")
    print(args.token, flush=True)


if __name__ == "__main__":
    main()
