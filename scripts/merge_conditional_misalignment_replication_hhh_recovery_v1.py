#!/usr/bin/env python3
"""Merge a verified partial HHH prefix with its exact no-overwrite suffix."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


STAGE = "conditional_misalignment_replication_hhh_seed1_merge_v1"
CONTRACT = "diagnostics.conditional_misalignment_replication_hhh_seed1_merge_v1"
FULL_CONTRACT = "diagnostics.conditional_misalignment_replication_hhh_seed1_topup_v1"


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


def target_identities(contract: dict[str, Any]) -> list[tuple[str, str, int]]:
    identities: list[tuple[str, str, int]] = []
    for cell in contract["target_cells"]:
        for prompt_id in cell["prompt_ids"]:
            for sample_index in range(
                cell["sample_index_start_inclusive"],
                cell["sample_index_end_exclusive"],
            ):
                identities.append((cell["context"], prompt_id, sample_index))
    if len(identities) != contract["expected_behavior_rows"]:
        raise ValueError("full contract row count differs from target grid")
    if len(set(identities)) != len(identities):
        raise ValueError("full contract target identities are duplicated")
    return identities


def row_identity(row: dict[str, Any]) -> tuple[str, str, int]:
    return (row["context"], row["prompt_id"], row["sample_index"])


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
        raise ValueError("merge runner received another stage")
    contract = snapshot["values"][CONTRACT]
    full_contract = snapshot["values"][FULL_CONTRACT]
    if sha256_file(Path(__file__)) != contract["entrypoint_sha256"]:
        raise ValueError("merge runner differs from frozen identity")

    source_rows: list[list[dict[str, Any]]] = []
    for source in (contract["prefix"], contract["suffix"]):
        path = Path(source["path"])
        if sha256_file(path) != source["sha256"]:
            raise ValueError(f"source hash differs: {path}")
        rows = load_rows(path)
        if len(rows) != source["rows"]:
            raise ValueError(f"source row count differs: {path}")
        source_rows.append(rows)

    combined = source_rows[0] + source_rows[1]
    expected = target_identities(full_contract)
    observed = [row_identity(row) for row in combined]
    if observed != expected:
        raise ValueError("prefix and suffix do not reproduce the canonical HHH target order")
    row_ids = [row.get("row_id") for row in combined]
    if any(not isinstance(row_id, str) or not row_id for row_id in row_ids):
        raise ValueError("combined behavior contains an invalid row ID")
    if len(set(row_ids)) != len(row_ids):
        raise ValueError("combined behavior contains duplicate row IDs")

    output_dir = Path(contract["output_directory"])
    if output_dir.exists():
        raise FileExistsError(output_dir)
    output_dir.mkdir(parents=True)
    behavior_path = output_dir / "behavior.jsonl"
    with behavior_path.open("x", encoding="utf-8") as handle:
        for row in combined:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    snapshot_sha = sha256_file(args.snapshot)
    write_json_exclusive(
        output_dir / "merge_report.json",
        {
            "run_id": contract["run_id"],
            "stage_snapshot_sha256": snapshot_sha,
            "prefix": contract["prefix"],
            "suffix": contract["suffix"],
            "combined_rows": len(combined),
            "expected_rows": len(expected),
            "behavior_sha256": sha256_file(behavior_path),
            "row_ids_unique": True,
            "canonical_target_order": True,
        },
    )
    manifest_files = {}
    for path in sorted(output_dir.iterdir()):
        if path.is_file():
            manifest_files[path.name] = {
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
    manifest_path = output_dir / "artifact_manifest.json"
    write_json_exclusive(
        manifest_path,
        {
            "run_id": contract["run_id"],
            "stage_snapshot_sha256": snapshot_sha,
            "files": manifest_files,
        },
    )
    (output_dir / "artifact_manifest.sha256").write_text(
        f"{sha256_file(manifest_path)}  artifact_manifest.json\n",
        encoding="utf-8",
    )
    print(f"HHH RECOVERY MERGE COMPLETE: {output_dir}")


if __name__ == "__main__":
    main()
