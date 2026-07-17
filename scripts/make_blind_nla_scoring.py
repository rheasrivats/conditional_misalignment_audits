#!/usr/bin/env python3
"""Create independently shuffled NLA rows plus a sealed condition reveal key."""

from __future__ import annotations

import csv
import hashlib
import json
import random
from pathlib import Path

import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "artifacts" / "decoded.parquet"
RUBRIC = ROOT / "analysis" / "nla_scoring_rubric.md"
ROWS = ROOT / "artifacts" / "nla_blind_rows.json"
KEY = ROOT / "artifacts" / "nla_blind_key.csv"
MANIFEST = ROOT / "artifacts" / "nla_blinding_manifest.json"
SEED = 20260718


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    if ROWS.exists() or KEY.exists() or MANIFEST.exists():
        raise FileExistsError("NLA blinding artifacts already exist; refusing to overwrite")
    table = pq.read_table(INPUT)
    required = {"prompt_id", "category", "prompt", "model_label", "nla_explanation", "nla_raw_output", "nla_parse_ok"}
    missing = required - set(table.column_names)
    if missing:
        raise ValueError(f"decoded.parquet is missing {sorted(missing)}")
    source_rows = table.to_pylist()
    if len(source_rows) != 32:
        raise ValueError(f"Expected 32 NLA rows, found {len(source_rows)}")

    indexed = list(enumerate(source_rows))
    random.Random(SEED).shuffle(indexed)
    blind_rows = []
    key_rows = []
    for number, (source_index, row) in enumerate(indexed, start=1):
        blind_id = f"NB{number:03d}"
        blind_rows.append(
            {
                "blind_id": blind_id,
                "prompt_id": row["prompt_id"],
                "category": row["category"],
                "prompt": row["prompt"],
                "nla_explanation": row["nla_explanation"],
                "nla_raw_output_sha256": hashlib.sha256(row["nla_raw_output"].encode()).hexdigest(),
                "nla_parse_ok": bool(row["nla_parse_ok"]),
            }
        )
        key_rows.append(
            {
                "blind_id": blind_id,
                "model_label": row["model_label"],
                "source_row_index": source_index,
            }
        )

    ROWS.write_text(json.dumps(blind_rows, indent=2, ensure_ascii=False) + "\n")
    with KEY.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["blind_id", "model_label", "source_row_index"])
        writer.writeheader()
        writer.writerows(key_rows)
    manifest = {
        "row_count": len(blind_rows),
        "shuffle_seed": SEED,
        "source": {"path": str(INPUT), "sha256": sha256(INPUT)},
        "rubric": {"path": str(RUBRIC), "sha256": sha256(RUBRIC)},
        "blind_rows": {"path": str(ROWS), "sha256": sha256(ROWS)},
        "sealed_reveal_key": {"path": str(KEY), "sha256": sha256(KEY)},
        "reveal_status": "SEALED",
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({k: manifest[k] for k in ("row_count", "shuffle_seed", "rubric", "blind_rows", "sealed_reveal_key", "reveal_status")}, indent=2))


if __name__ == "__main__":
    main()
