#!/usr/bin/env python3
"""Write an exclusive, validated prefix of a growing JSONL artifact."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--rows", required=True, type=int)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.rows <= 0:
        raise ValueError("rows must be positive")
    if not args.source.is_file():
        raise FileNotFoundError(args.source)
    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite prefix: {args.output}")

    selected: list[bytes] = []
    row_ids: set[str] = set()
    with args.source.open("rb") as source:
        for line_number in range(1, args.rows + 1):
            line = source.readline()
            if not line:
                raise ValueError(
                    f"source ended at {line_number - 1} rows; need {args.rows}"
                )
            if not line.endswith(b"\n"):
                raise ValueError(f"incomplete JSONL line at {line_number}")
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"line {line_number} is not a JSON object")
            row_id = value.get("row_id")
            if not isinstance(row_id, str) or not row_id:
                raise ValueError(f"line {line_number} lacks row_id")
            if row_id in row_ids:
                raise ValueError(f"duplicate row_id in prefix: {row_id}")
            row_ids.add(row_id)
            selected.append(line)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        for line in selected:
            output.write(line)
        output.flush()
        os.fsync(output.fileno())
    print(f"WROTE VALIDATED PREFIX rows={args.rows} path={args.output}")


if __name__ == "__main__":
    main()
