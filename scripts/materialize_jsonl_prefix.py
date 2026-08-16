#!/usr/bin/env python3
"""Materialize an immutable, complete-newline JSONL prefix without content inspection."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--rows", required=True, type=int)
    parser.add_argument("--destination", required=True, type=Path)
    args = parser.parse_args()
    if args.rows <= 0:
        raise ValueError("rows must be positive")
    args.destination.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    row_ids: set[str] = set()
    written = 0
    descriptor = os.open(args.destination, flags, 0o600)
    try:
        with args.source.open("rb") as source, os.fdopen(descriptor, "wb") as target:
            for line_number in range(1, args.rows + 1):
                line = source.readline()
                if not line or not line.endswith(b"\n"):
                    raise ValueError(f"source lacks complete row {line_number}")
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError(f"row {line_number} is not an object")
                row_id = value.get("row_id")
                if not isinstance(row_id, str) or not row_id or row_id in row_ids:
                    raise ValueError(f"row {line_number} has invalid or duplicate row_id")
                row_ids.add(row_id)
                target.write(line)
                written += 1
            target.flush()
            os.fsync(target.fileno())
    except Exception:
        args.destination.unlink(missing_ok=True)
        raise
    print(json.dumps({"destination": str(args.destination), "rows": written}, sort_keys=True))


if __name__ == "__main__":
    main()
