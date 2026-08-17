#!/usr/bin/env python3
"""Mirror a stable JSONL prefix to an immutable RunPod S3 checkpoint."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class MirrorError(ValueError):
    """A mirroring invariant failed."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_jsonl(path: Path) -> int:
    rows = 0
    row_ids: set[str] = set()
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.endswith("\n"):
                raise MirrorError(f"incomplete final JSONL line at {line_number}")
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise MirrorError(f"invalid JSON at line {line_number}") from exc
            if not isinstance(value, dict):
                raise MirrorError(f"JSONL line {line_number} is not an object")
            row_id = value.get("row_id")
            if not isinstance(row_id, str) or not row_id:
                raise MirrorError(f"JSONL line {line_number} lacks a row_id")
            if row_id in row_ids:
                raise MirrorError(f"duplicate row_id: {row_id}")
            row_ids.add(row_id)
            rows += 1
    if rows == 0:
        raise MirrorError("JSONL checkpoint is empty")
    return rows


def stable_copy(source: Path, destination: Path) -> None:
    with source.open("rb") as input_handle, destination.open("xb") as output_handle:
        shutil.copyfileobj(input_handle, output_handle, length=1024 * 1024)
        output_handle.flush()
        os.fsync(output_handle.fileno())


def require_safe_id(value: str, label: str) -> str:
    if not SAFE_ID.fullmatch(value):
        raise MirrorError(
            f"{label} must match {SAFE_ID.pattern!r}; got {value!r}"
        )
    return value


def checkpoint_key(run_id: str, rows: int, digest: str) -> str:
    require_safe_id(run_id, "run_id")
    return f"runs/{run_id}/checkpoints/rows-{rows:06d}-{digest[:12]}"


def aws_command(
    *,
    profile: str,
    region: str,
    endpoint: str,
    operation: str,
    extra: list[str],
    allow_not_found: bool = False,
) -> subprocess.CompletedProcess[str]:
    command = [
        "aws",
        "s3api",
        operation,
        "--profile",
        profile,
        "--region",
        region,
        "--endpoint-url",
        endpoint,
        *extra,
    ]
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode != 0 and not (
        allow_not_found
        and (
            "Not Found" in result.stderr
            or "404" in result.stderr
            or "NoSuchKey" in result.stderr
        )
    ):
        raise MirrorError(
            f"aws s3api {operation} failed with exit {result.returncode}: "
            f"{result.stderr.strip()}"
        )
    return result


def ensure_absent(
    *,
    profile: str,
    region: str,
    endpoint: str,
    bucket: str,
    key: str,
) -> None:
    result = aws_command(
        profile=profile,
        region=region,
        endpoint=endpoint,
        operation="head-object",
        extra=["--bucket", bucket, "--key", key],
        allow_not_found=True,
    )
    if result.returncode == 0:
        raise MirrorError(f"immutable checkpoint already exists: s3://{bucket}/{key}")


def put_file(
    *,
    profile: str,
    region: str,
    endpoint: str,
    bucket: str,
    key: str,
    path: Path,
) -> dict[str, Any]:
    result = aws_command(
        profile=profile,
        region=region,
        endpoint=endpoint,
        operation="put-object",
        extra=["--bucket", bucket, "--key", key, "--body", str(path)],
    )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise MirrorError("put-object returned invalid JSON") from exc


def head_object(
    *,
    profile: str,
    region: str,
    endpoint: str,
    bucket: str,
    key: str,
) -> dict[str, Any]:
    result = aws_command(
        profile=profile,
        region=region,
        endpoint=endpoint,
        operation="head-object",
        extra=["--bucket", bucket, "--key", key],
    )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise MirrorError("head-object returned invalid JSON") from exc


def get_file(
    *,
    profile: str,
    region: str,
    endpoint: str,
    bucket: str,
    key: str,
    destination: Path,
) -> dict[str, Any]:
    result = aws_command(
        profile=profile,
        region=region,
        endpoint=endpoint,
        operation="get-object",
        extra=["--bucket", bucket, "--key", key, str(destination)],
    )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise MirrorError("get-object returned invalid JSON") from exc


def write_json_exclusive(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--expected-rows", required=True, type=int)
    parser.add_argument("--approval-id", required=True)
    parser.add_argument("--volume-id", required=True)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--receipt-out", required=True, type=Path)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        require_safe_id(args.run_id, "run_id")
        require_safe_id(args.volume_id, "volume_id")
        require_safe_id(args.region, "region")
        require_safe_id(args.profile, "profile")
        if not args.source.is_file():
            raise MirrorError(f"source does not exist: {args.source}")
        if args.expected_rows <= 0:
            raise MirrorError("expected_rows must be positive")
        if args.receipt_out.exists():
            raise MirrorError(f"receipt already exists: {args.receipt_out}")

        with tempfile.TemporaryDirectory(prefix="runpod-s3-checkpoint.") as temp_text:
            temp_dir = Path(temp_text)
            snapshot_path = temp_dir / "behavior.jsonl"
            stable_copy(args.source, snapshot_path)
            rows = validate_jsonl(snapshot_path)
            if rows != args.expected_rows:
                raise MirrorError(
                    f"row count {rows} does not equal expected {args.expected_rows}"
                )
            digest = sha256_file(snapshot_path)
            byte_count = snapshot_path.stat().st_size
            key_root = checkpoint_key(args.run_id, rows, digest)
            behavior_key = f"{key_root}/behavior.jsonl"
            sha_key = f"{key_root}/behavior.sha256"
            metadata_key = f"{key_root}/checkpoint.json"

            metadata = {
                "schema_version": 1,
                "run_id": args.run_id,
                "approval_id": args.approval_id,
                "rows": rows,
                "bytes": byte_count,
                "behavior_sha256": digest,
                "behavior_key": behavior_key,
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
            }
            sha_path = temp_dir / "behavior.sha256"
            sha_path.write_text(f"{digest}  behavior.jsonl\n", encoding="utf-8")
            metadata_path = temp_dir / "checkpoint.json"
            metadata_path.write_text(
                json.dumps(metadata, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            receipt: dict[str, Any] = {
                "schema_version": 1,
                "status": "dry_run" if args.dry_run else "verified",
                "run_id": args.run_id,
                "approval_id": args.approval_id,
                "source_path": str(args.source.resolve()),
                "rows": rows,
                "bytes": byte_count,
                "behavior_sha256": digest,
                "network_volume_id": args.volume_id,
                "endpoint": args.endpoint,
                "region": args.region,
                "profile_name": args.profile,
                "keys": {
                    "behavior": behavior_key,
                    "sha256": sha_key,
                    "metadata": metadata_key,
                },
                "credentials_recorded": False,
            }

            if not args.dry_run:
                for key in (behavior_key, sha_key, metadata_key):
                    ensure_absent(
                        profile=args.profile,
                        region=args.region,
                        endpoint=args.endpoint,
                        bucket=args.volume_id,
                        key=key,
                    )
                puts = {
                    "behavior": put_file(
                        profile=args.profile,
                        region=args.region,
                        endpoint=args.endpoint,
                        bucket=args.volume_id,
                        key=behavior_key,
                        path=snapshot_path,
                    ),
                    "sha256": put_file(
                        profile=args.profile,
                        region=args.region,
                        endpoint=args.endpoint,
                        bucket=args.volume_id,
                        key=sha_key,
                        path=sha_path,
                    ),
                    "metadata": put_file(
                        profile=args.profile,
                        region=args.region,
                        endpoint=args.endpoint,
                        bucket=args.volume_id,
                        key=metadata_key,
                        path=metadata_path,
                    ),
                }
                remote_head = head_object(
                    profile=args.profile,
                    region=args.region,
                    endpoint=args.endpoint,
                    bucket=args.volume_id,
                    key=behavior_key,
                )
                if remote_head.get("ContentLength") != byte_count:
                    raise MirrorError("remote behavior size does not match")
                downloaded_path = temp_dir / "downloaded.behavior.jsonl"
                download = get_file(
                    profile=args.profile,
                    region=args.region,
                    endpoint=args.endpoint,
                    bucket=args.volume_id,
                    key=behavior_key,
                    destination=downloaded_path,
                )
                downloaded_digest = sha256_file(downloaded_path)
                if downloaded_digest != digest:
                    raise MirrorError("round-trip behavior SHA-256 does not match")
                receipt.update(
                    {
                        "put_responses": puts,
                        "remote_head": remote_head,
                        "download_response": download,
                        "downloaded_sha256": downloaded_digest,
                        "round_trip_verified": True,
                        "verified_at_utc": datetime.now(timezone.utc).isoformat(),
                    }
                )

            write_json_exclusive(args.receipt_out, receipt)
            print(
                f"S3 CHECKPOINT {receipt['status'].upper()} "
                f"run={args.run_id} rows={rows} sha256={digest}"
            )
            return 0
    except (MirrorError, OSError) as exc:
        print(f"S3 CHECKPOINT BLOCKED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
