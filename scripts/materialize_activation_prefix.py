#!/usr/bin/env python3
"""Materialize activations bound to an immutable behavior JSONL prefix."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--behavior", required=True, type=Path)
    parser.add_argument("--activations", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    args = parser.parse_args()

    source_ids: set[str] = set()
    with args.behavior.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if not line.endswith("\n") or not line.strip():
                raise ValueError(f"behavior row {number} is incomplete or blank")
            row = json.loads(line)
            row_id = row.get("row_id")
            if not isinstance(row_id, str) or not row_id or row_id in source_ids:
                raise ValueError(f"behavior row {number} has invalid or duplicate row_id")
            source_ids.add(row_id)

    args.destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(args.destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    written = 0
    activation_ids: set[str] = set()
    try:
        with args.activations.open("rb") as source, os.fdopen(descriptor, "wb") as target:
            for number, line in enumerate(source, 1):
                if not line.endswith(b"\n"):
                    break
                row = json.loads(line)
                if row.get("source_row_id") not in source_ids:
                    continue
                row_id = row.get("row_id")
                if not isinstance(row_id, str) or not row_id or row_id in activation_ids:
                    raise ValueError(
                        f"activation row {number} has invalid or duplicate row_id"
                    )
                activation_ids.add(row_id)
                target.write(line)
                written += 1
            target.flush()
            os.fsync(target.fileno())
    except Exception:
        args.destination.unlink(missing_ok=True)
        raise

    print(
        json.dumps(
            {
                "behavior_source_rows": len(source_ids),
                "destination": str(args.destination),
                "activation_rows": written,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
