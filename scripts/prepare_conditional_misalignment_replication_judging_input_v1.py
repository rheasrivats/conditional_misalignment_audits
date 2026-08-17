#!/usr/bin/env python3
"""Create the exact no-response-mutation 2,460-row replication judging input."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


STAGE = "conditional_misalignment_replication_judging_input_v1"
CONTRACT = "diagnostics.conditional_misalignment_replication_judging_input_v1"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.endswith("\n"):
                raise ValueError(f"incomplete JSONL line {line_number}: {path}")
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"non-object JSONL row {line_number}: {path}")
            rows.append(row)
    return rows


def validate_combined(rows: list[dict[str, Any]], contract: dict[str, Any]) -> None:
    if len(rows) != contract["expected_rows"]:
        raise ValueError("combined judging input row count differs")
    row_ids = [row.get("row_id") for row in rows]
    if any(not isinstance(row_id, str) or not row_id for row_id in row_ids):
        raise ValueError("combined judging input contains an invalid row ID")
    if len(set(row_ids)) != len(row_ids):
        raise ValueError("combined judging input contains duplicate row IDs")
    if Counter(row.get("checkpoint_label") for row in rows) != Counter(
        contract["checkpoint_label_row_counts"]
    ):
        raise ValueError("combined judging checkpoint counts differ")
    if Counter(row.get("context") for row in rows) != Counter(
        contract["context_row_counts"]
    ):
        raise ValueError("combined judging context counts differ")
    if Counter(row.get("run_id") for row in rows) != Counter(
        contract["generation_run_id_row_counts"]
    ):
        raise ValueError("combined judging generation run counts differ")
    if any(not isinstance(row.get("checkpoint_provenance"), dict) for row in rows):
        raise ValueError("combined judging input lacks checkpoint provenance")


def write_json_exclusive(path: Path, value: dict[str, Any]) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    args = parser.parse_args()
    snapshot = json.loads(args.snapshot.read_text())
    if snapshot.get("stage") != STAGE:
        raise ValueError("judging-input runner received another stage")
    contract = snapshot["values"][CONTRACT]
    if sha256_file(Path(__file__)) != contract["entrypoint_sha256"]:
        raise ValueError("judging-input runner differs from frozen identity")

    source_rows: list[list[dict[str, Any]]] = []
    for source in contract["sources"]:
        path = Path(source["path"])
        if sha256_file(path) != source["sha256"]:
            raise ValueError(f"judging source hash differs: {path}")
        rows = load_rows(path)
        if len(rows) != source["rows"]:
            raise ValueError(f"judging source row count differs: {path}")
        source_rows.append(rows)
    combined = [row for rows in source_rows for row in rows]
    validate_combined(combined, contract)

    output_dir = Path(contract["output_directory"])
    if output_dir.exists():
        raise FileExistsError(output_dir)
    output_dir.mkdir(parents=True)
    behavior_path = output_dir / "behavior.jsonl"
    with behavior_path.open("x", encoding="utf-8") as handle:
        for row in combined:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    report_path = output_dir / "preparation_report.json"
    write_json_exclusive(
        report_path,
        {
            "run_id": contract["run_id"],
            "stage_snapshot_sha256": sha256_file(args.snapshot),
            "sources": contract["sources"],
            "rows": len(combined),
            "behavior_sha256": sha256_file(behavior_path),
            "row_ids_unique": True,
            "responses_mutated": False,
        },
    )
    manifest_files = {
        path.name: {"bytes": path.stat().st_size, "sha256": sha256_file(path)}
        for path in sorted(output_dir.iterdir())
        if path.is_file()
    }
    manifest_path = output_dir / "artifact_manifest.json"
    write_json_exclusive(
        manifest_path,
        {
            "run_id": contract["run_id"],
            "stage_snapshot_sha256": sha256_file(args.snapshot),
            "files": manifest_files,
        },
    )
    (output_dir / "artifact_manifest.sha256").write_text(
        f"{sha256_file(manifest_path)}  artifact_manifest.json\n",
        encoding="utf-8",
    )
    print(f"REPLICATION JUDGING INPUT COMPLETE: {output_dir}")


if __name__ == "__main__":
    main()
