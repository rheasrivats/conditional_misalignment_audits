#!/usr/bin/env python3
"""Validate a mirrored Claim 1 JSONL prefix without exposing response text."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    raw = args.path.read_bytes()
    if raw and not raw.endswith(b"\n"):
        raise ValueError("mirrored JSONL has an incomplete final line")
    row_ids: list[str] = []
    for line_number, line in enumerate(raw.splitlines(), start=1):
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError(f"line {line_number} is not an object")
        row_id = row.get("row_id")
        if not isinstance(row_id, str) or not row_id:
            raise ValueError(f"line {line_number} lacks row_id")
        row_ids.append(row_id)
    if len(row_ids) != len(set(row_ids)):
        raise ValueError("mirrored JSONL contains duplicate row IDs")
    print(
        json.dumps(
            {
                "bytes": len(raw),
                "complete_final_newline": not raw or raw.endswith(b"\n"),
                "rows": len(row_ids),
                "sha256": sha256_file(args.path),
                "unique_row_ids": len(set(row_ids)),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
