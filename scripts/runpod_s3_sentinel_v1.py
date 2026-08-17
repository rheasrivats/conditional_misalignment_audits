#!/usr/bin/env python3
"""Create and round-trip verify one immutable RunPod S3 sentinel."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path


SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def aws(args: argparse.Namespace, operation: str, extra: list[str], *, missing_ok: bool = False) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [
            "aws", "s3api", operation,
            "--profile", args.profile,
            "--region", args.region,
            "--endpoint-url", args.endpoint,
            *extra,
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode and not (
        missing_ok
        and any(value in result.stderr for value in ("404", "Not Found", "NoSuchKey"))
    ):
        raise RuntimeError(
            f"aws s3api {operation} failed with exit {result.returncode}: "
            f"{result.stderr.strip()}"
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--approval-id", required=True)
    parser.add_argument("--pod-id", required=True)
    parser.add_argument("--snapshot-sha256", required=True)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--receipt", required=True, type=Path)
    args = parser.parse_args()

    for label in ("approval_id", "pod_id", "bucket", "region", "profile"):
        value = getattr(args, label)
        if not SAFE_ID.fullmatch(value):
            raise ValueError(f"unsafe {label}: {value!r}")
    if not re.fullmatch(r"[0-9a-f]{64}", args.snapshot_sha256):
        raise ValueError("snapshot SHA-256 must be 64 lowercase hexadecimal characters")
    if args.receipt.exists():
        raise FileExistsError(f"refusing to overwrite receipt: {args.receipt}")

    payload = (
        json.dumps(
            {
                "schema_version": 1,
                "approval_id": args.approval_id,
                "pod_id": args.pod_id,
                "snapshot_sha256": args.snapshot_sha256,
                "created_at_utc": now_utc(),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )
    digest = hashlib.sha256(payload).hexdigest()
    key = f"{args.prefix.rstrip('/')}/sentinels/{args.approval_id}/{digest}/local_to_s3_sentinel.json"

    absent = aws(
        args,
        "head-object",
        ["--bucket", args.bucket, "--key", key],
        missing_ok=True,
    )
    if absent.returncode == 0:
        raise FileExistsError(f"immutable sentinel already exists: s3://{args.bucket}/{key}")

    with tempfile.TemporaryDirectory(prefix="runpod-s3-sentinel.") as temp_dir:
        source = Path(temp_dir) / "sentinel.json"
        destination = Path(temp_dir) / "downloaded.json"
        source.write_bytes(payload)
        aws(
            args,
            "put-object",
            ["--bucket", args.bucket, "--key", key, "--body", str(source)],
        )
        head = json.loads(
            aws(args, "head-object", ["--bucket", args.bucket, "--key", key]).stdout
        )
        listing = json.loads(
            aws(
                args,
                "list-objects-v2",
                ["--bucket", args.bucket, "--prefix", key],
            ).stdout
        )
        exact = [item for item in listing.get("Contents", []) if item.get("Key") == key]
        if len(exact) != 1 or int(exact[0]["Size"]) != len(payload):
            raise RuntimeError(f"exact listing verification failed: {exact}")
        if int(head["ContentLength"]) != len(payload):
            raise RuntimeError("HEAD byte count differs from uploaded payload")
        aws(
            args,
            "get-object",
            ["--bucket", args.bucket, "--key", key, str(destination)],
        )
        if destination.read_bytes() != payload:
            raise RuntimeError("downloaded sentinel differs byte-for-byte")

    receipt = {
        "schema_version": 1,
        "approval_id": args.approval_id,
        "pod_id": args.pod_id,
        "volume_id": args.bucket,
        "endpoint": args.endpoint,
        "region": args.region,
        "key": key,
        "bytes": len(payload),
        "sha256": digest,
        "exact_list_verified": True,
        "head_verified": True,
        "download_round_trip_verified": True,
        "verified_at_utc": now_utc(),
    }
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(args.receipt, flags, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(receipt, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
