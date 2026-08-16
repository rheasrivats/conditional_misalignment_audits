#!/usr/bin/env python3
"""Gate Base launch on a local/S3-completion token and remote HHH terminal audit."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gate-token", required=True)
    parser.add_argument("--hhh-output", required=True, type=Path)
    parser.add_argument("--hhh-expected-rows", required=True, type=int)
    parser.add_argument("--hhh-snapshot-sha256", required=True)
    parser.add_argument("--base-output", required=True, type=Path)
    parser.add_argument("--python", required=True, type=Path)
    parser.add_argument("--runner", required=True, type=Path)
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--workspace", required=True, type=Path)
    args = parser.parse_args()

    received = input().strip()
    if received != args.gate_token:
        raise ValueError("Base launch gate token absent or incorrect")
    behavior = args.hhh_output / "behavior.jsonl"
    report_path = args.hhh_output / "generation_report.json"
    manifest_path = args.hhh_output / "artifact_manifest.json"
    manifest_sha_path = args.hhh_output / "artifact_manifest.sha256"
    for path in (behavior, report_path, manifest_path, manifest_sha_path):
        if not path.is_file():
            raise FileNotFoundError(path)
    with behavior.open("rb") as handle:
        rows = sum(1 for line in handle if line.endswith(b"\n"))
    if rows != args.hhh_expected_rows:
        raise ValueError(f"remote HHH behavior rows differ: {rows}")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("behavior_rows") != args.hhh_expected_rows:
        raise ValueError("remote HHH report row count differs")
    if report.get("behavior_sha256") != sha256_file(behavior):
        raise ValueError("remote HHH report hash differs from behavior")
    if report.get("stage_snapshot_sha256") != args.hhh_snapshot_sha256:
        raise ValueError("remote HHH report snapshot differs")
    recorded_manifest_sha = manifest_sha_path.read_text(encoding="utf-8").split()[0]
    if recorded_manifest_sha != sha256_file(manifest_path):
        raise ValueError("remote HHH manifest checksum differs")
    if args.base_output.exists():
        raise FileExistsError(f"Base output root already exists: {args.base_output}")
    print(
        f"HHH REMOTE TERMINAL GATE VERIFIED rows={rows} behavior_sha256={report['behavior_sha256']}",
        flush=True,
    )
    os.execv(
        args.python,
        [
            str(args.python), str(args.runner),
            "--snapshot", str(args.snapshot),
            "--workspace", str(args.workspace),
        ],
    )


if __name__ == "__main__":
    main()
