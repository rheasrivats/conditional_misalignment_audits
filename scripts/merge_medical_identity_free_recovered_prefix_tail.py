#!/usr/bin/env python3
"""Deterministically merge a recovered canonical prefix with its generated tail."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


CONTRACTS = {
    "medical_post_hoc_identity_free_assistant_merge_v1": (
        "diagnostics.medical_post_hoc_identity_free_assistant_merge_contract_v1"
    ),
    "medical_hhh_only_identity_free_assistant_merge_v1": (
        "diagnostics.medical_hhh_only_identity_free_assistant_merge_contract_v1"
    ),
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def write_json(path: Path, value: dict[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(path)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    args = parser.parse_args()
    snapshot = json.loads(args.snapshot.read_text())
    stage = snapshot.get("stage")
    if stage not in CONTRACTS:
        raise ValueError(f"unsupported merge stage: {stage!r}")
    contract = snapshot["values"][CONTRACTS[stage]]
    if sha256_file(Path(__file__)) != contract["entrypoint_sha256"]:
        raise ValueError("merge entrypoint differs from frozen identity")
    prefix_path = Path(contract["prefix"]["path"])
    tail_path = Path(contract["tail"]["path"])
    for path, expected in (
        (prefix_path, contract["prefix"]),
        (tail_path, contract["tail"]),
    ):
        if sha256_file(path) != expected["sha256"]:
            raise ValueError(f"source hash differs: {path}")
    prefix = rows(prefix_path)
    tail = rows(tail_path)
    if len(prefix) != contract["prefix"]["rows"]:
        raise ValueError("prefix row count differs")
    if len(tail) != contract["tail"]["rows"]:
        raise ValueError("tail row count differs")
    if [row["canonical_grid_index"] for row in tail] != list(
        range(len(prefix), contract["expected_rows"])
    ):
        raise ValueError("tail does not cover the exact canonical suffix")
    combined = prefix + tail
    if len(combined) != contract["expected_rows"]:
        raise ValueError("combined row count differs")
    if len({row["row_id"] for row in combined}) != len(combined):
        raise ValueError("combined behavior has duplicate row IDs")

    output_dir = Path(contract["output_directory"])
    if output_dir.exists():
        raise FileExistsError(output_dir)
    output_dir.mkdir(parents=True)
    behavior_path = output_dir / "behavior.jsonl"
    with behavior_path.open("x", encoding="utf-8") as handle:
        for row in combined:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    snapshot_sha = sha256_file(args.snapshot)
    write_json(
        output_dir / "merge_report.json",
        {
            "run_id": contract["run_id"],
            "stage_snapshot_sha256": snapshot_sha,
            "prefix": contract["prefix"],
            "tail": contract["tail"],
            "combined_rows": len(combined),
            "behavior_sha256": sha256_file(behavior_path),
            "row_ids_unique": True,
            "canonical_order": True,
        },
    )
    files = {}
    for path in sorted(output_dir.iterdir()):
        if path.is_file():
            files[path.name] = {
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
    manifest_path = output_dir / "artifact_manifest.json"
    write_json(
        manifest_path,
        {
            "run_id": contract["run_id"],
            "stage_snapshot_sha256": snapshot_sha,
            "files": files,
        },
    )
    (output_dir / "artifact_manifest.sha256").write_text(
        f"{sha256_file(manifest_path)}  artifact_manifest.json\n"
    )
    print(f"RECOVERED PREFIX + TAIL MERGE COMPLETE: {output_dir}")


if __name__ == "__main__":
    main()
