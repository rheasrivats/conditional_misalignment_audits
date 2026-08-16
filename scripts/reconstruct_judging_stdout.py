#!/usr/bin/env python3
"""Reconstruct the deterministic judge progress log from verified judge rows."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-judges", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if args.output.exists():
        raise FileExistsError(args.output)
    raw = args.raw_judges.read_bytes()
    if not raw.endswith(b"\n"):
        raise ValueError("raw judge artifact is not newline terminated")
    rows = [json.loads(line) for line in raw.splitlines()]
    lines = []
    for row in rows:
        row_id = row.get("behavior_row_id")
        judge_name = row.get("judge_name")
        if not isinstance(row_id, str) or judge_name not in {"alignment", "coherence"}:
            raise ValueError("raw judge row lacks deterministic progress fields")
        lines.append(f"judged {row_id} {judge_name}\n")
    payload = "".join(lines).encode()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
    print(
        json.dumps(
            {
                "rows": len(rows),
                "bytes": len(payload),
                "sha256": sha256_bytes(payload),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
