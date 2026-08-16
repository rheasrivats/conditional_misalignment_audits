#!/usr/bin/env python3
"""Verify and receipt an existing immutable HHH checkpoint S3 object."""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


V3_PATH = Path(__file__).with_name("archive_hhh_adapter_checkpoint_v3.py")
V3_SPEC = importlib.util.spec_from_file_location("archive_hhh_adapter_checkpoint_v3", V3_PATH)
if V3_SPEC is None or V3_SPEC.loader is None:
    raise RuntimeError(f"cannot load v3 archiver: {V3_PATH}")
v3 = importlib.util.module_from_spec(V3_SPEC)
V3_SPEC.loader.exec_module(v3)
v2 = v3.v2
v1 = v3.v1


def exact_object(args: argparse.Namespace, key: str) -> dict[str, Any]:
    result = v3.ORIGINAL_AWS(
        args,
        "list-objects-v2",
        ["--bucket", args.volume_id, "--prefix", key],
    )
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise v1.ArchiveError("list-objects-v2 returned invalid JSON") from exc
    contents = value.get("Contents", [])
    if not isinstance(contents, list):
        raise v1.ArchiveError("list-objects-v2 returned invalid Contents")
    exact = [item for item in contents if isinstance(item, dict) and item.get("Key") == key]
    if len(exact) != 1:
        raise v1.ArchiveError(f"expected one existing immutable object, found {len(exact)}")
    return exact[0]


def download(args: argparse.Namespace, key: str, destination: Path) -> dict[str, Any]:
    if destination.exists():
        raise v1.ArchiveError(f"download destination already exists: {destination}")
    command = [
        "aws", "s3", "cp", f"s3://{args.volume_id}/{key}", str(destination),
        "--profile", args.profile,
        "--region", args.region,
        "--endpoint-url", args.endpoint,
        "--no-progress", "--only-show-errors",
    ]
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise v1.ArchiveError(
            f"aws s3 cp download failed with exit {result.returncode}: {result.stderr.strip()}"
        )
    return {"transport": "aws_s3_cp", "stderr_empty": not bool(result.stderr.strip())}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--checkpoint-label", required=True)
    parser.add_argument("--approval-id", required=True)
    parser.add_argument("--snapshot-sha256", required=True)
    parser.add_argument("--volume-id", required=True)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--receipt-out", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        for value, label in (
            (args.run_id, "run id"), (args.approval_id, "approval id"),
            (args.volume_id, "volume id"), (args.region, "region"),
            (args.profile, "profile"),
        ):
            v1.require_safe_id(value, label)
        if not re.fullmatch(r"[0-9a-f]{64}", args.snapshot_sha256):
            raise v1.ArchiveError("snapshot SHA-256 is invalid")
        if args.receipt_out.exists():
            raise v1.ArchiveError(f"receipt already exists: {args.receipt_out}")
        source = args.source.resolve()
        manifest = v1.validate_checkpoint(source, args.checkpoint_label, args.snapshot_sha256)
        with tempfile.TemporaryDirectory(prefix="hhh-adapter-existing-verification.") as temp_text:
            temp = Path(temp_text)
            archive = temp / f"{args.checkpoint_label}.tar"
            v1.build_deterministic_tar(source, archive, args.checkpoint_label)
            digest = v1.sha256_file(archive)
            byte_count = archive.stat().st_size
            key_root = f"runs/{args.run_id}/checkpoints/{args.checkpoint_label}-{digest[:12]}"
            key = f"{key_root}/{args.checkpoint_label}.tar"
            listed = exact_object(args, key)
            if int(listed.get("Size", -1)) != byte_count:
                raise v1.ArchiveError("listed remote archive byte count differs")
            downloaded = temp / "downloaded.tar"
            download_response = download(args, key, downloaded)
            downloaded_sha = v1.sha256_file(downloaded)
            if downloaded_sha != digest:
                raise v1.ArchiveError("download round-trip SHA-256 differs")
            receipt = {
                "schema_version": 1,
                "status": "verified_existing_after_post_upload_head_failure",
                "incident": "INC-0133",
                "run_id": args.run_id,
                "approval_id": args.approval_id,
                "checkpoint_label": args.checkpoint_label,
                "source_path": str(source),
                "snapshot_sha256": args.snapshot_sha256,
                "optimizer_step": manifest.get("optimizer_step"),
                "processed_examples": manifest.get("processed_examples"),
                "archive_bytes": byte_count,
                "archive_sha256": digest,
                "network_volume_id": args.volume_id,
                "endpoint": args.endpoint,
                "region": args.region,
                "profile_name": args.profile,
                "archive_key": key,
                "credentials_recorded": False,
                "exact_list_object": listed,
                "download_response": download_response,
                "downloaded_sha256": downloaded_sha,
                "round_trip_verified": True,
                "verified_at_utc": datetime.now(timezone.utc).isoformat(),
            }
            v1.write_exclusive(args.receipt_out, receipt)
            print(json.dumps(receipt, sort_keys=True))
        return 0
    except (v1.ArchiveError, OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"HHH EXISTING CHECKPOINT VERIFICATION BLOCKED: {exc}", file=__import__("sys").stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
