#!/usr/bin/env python3
"""Fail-closed S3 sentinel, capacity, and download/hash verification helpers."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def client():
    required = [
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "S3_ENDPOINT",
        "S3_REGION",
    ]
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise RuntimeError(f"missing required environment variables: {missing}")
    return boto3.client(
        "s3",
        endpoint_url=os.environ["S3_ENDPOINT"],
        region_name=os.environ["S3_REGION"],
        config=Config(
            region_name=os.environ["S3_REGION"],
            retries={"max_attempts": 10, "mode": "standard"},
            connect_timeout=60,
            read_timeout=600,
        ),
    )


def write_receipt(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"refusing to overwrite receipt: {path}")
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def download_sha256(s3, bucket: str, key: str) -> tuple[int, str]:
    response = s3.get_object(Bucket=bucket, Key=key)
    digest = hashlib.sha256()
    byte_count = 0
    body = response["Body"]
    while chunk := body.read(8 * 1024 * 1024):
        byte_count += len(chunk)
        digest.update(chunk)
    return byte_count, digest.hexdigest()


def exact_list(s3, bucket: str, key: str) -> list[dict[str, object]]:
    response = s3.list_objects_v2(Bucket=bucket, Prefix=key)
    return [
        {"Key": item["Key"], "Size": int(item["Size"]), "ETag": item["ETag"]}
        for item in response.get("Contents", [])
        if item["Key"] == key
    ]


def command_sentinel(args) -> None:
    s3 = client()
    payload = json.dumps(
        {
            "schema_version": 1,
            "decision_id": "DEC-0206",
            "pod_id": args.pod_id,
            "snapshot_sha256": args.snapshot_sha256,
            "created_at_utc": utc_now(),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8") + b"\n"
    sha256 = hashlib.sha256(payload).hexdigest()
    key = f"{args.prefix}/sentinels/DEC-0206/{sha256}/pod_to_s3_sentinel.json"

    try:
        s3.head_object(Bucket=args.bucket, Key=key)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") not in {
            "404",
            "NoSuchKey",
            "NotFound",
        }:
            raise
    else:
        raise FileExistsError(f"refusing to overwrite sentinel: s3://{args.bucket}/{key}")

    s3.put_object(Bucket=args.bucket, Key=key, Body=payload)
    matches = exact_list(s3, args.bucket, key)
    if len(matches) != 1 or int(matches[0]["Size"]) != len(payload):
        raise RuntimeError(f"sentinel exact-list verification failed: {matches}")
    head = s3.head_object(Bucket=args.bucket, Key=key)
    if int(head["ContentLength"]) != len(payload):
        raise RuntimeError("sentinel HEAD size mismatch")
    downloaded_bytes, downloaded_sha256 = download_sha256(s3, args.bucket, key)
    if downloaded_bytes != len(payload) or downloaded_sha256 != sha256:
        raise RuntimeError("sentinel download/SHA-256 mismatch")

    receipt = {
        "schema_version": 1,
        "decision_id": "DEC-0206",
        "pod_id": args.pod_id,
        "bucket": args.bucket,
        "key": key,
        "bytes": len(payload),
        "sha256": sha256,
        "exact_list_verified": True,
        "head_verified": True,
        "download_round_trip_verified": True,
        "verified_at_utc": utc_now(),
    }
    write_receipt(args.receipt, receipt)
    print(json.dumps(receipt, sort_keys=True))


def command_capacity(args) -> None:
    s3 = client()
    paginator = s3.get_paginator("list_objects_v2")
    existing_bytes = 0
    object_count = 0
    for page in paginator.paginate(Bucket=args.bucket):
        for item in page.get("Contents", []):
            existing_bytes += int(item["Size"])
            object_count += 1
    projected_bytes = existing_bytes + args.new_bytes
    free_after = args.capacity_bytes - projected_bytes
    if free_after < args.minimum_reserve_bytes:
        raise RuntimeError(
            "capacity gate failed: "
            f"existing={existing_bytes} new={args.new_bytes} "
            f"capacity={args.capacity_bytes} free_after={free_after} "
            f"minimum_reserve={args.minimum_reserve_bytes}"
        )
    print(
        json.dumps(
            {
                "schema_version": 1,
                "bucket": args.bucket,
                "object_count": object_count,
                "existing_bytes": existing_bytes,
                "new_bytes": args.new_bytes,
                "capacity_bytes": args.capacity_bytes,
                "projected_bytes": projected_bytes,
                "free_after_bytes": free_after,
                "minimum_reserve_bytes": args.minimum_reserve_bytes,
                "capacity_gate_passed": True,
                "checked_at_utc": utc_now(),
            },
            sort_keys=True,
        )
    )


def command_verify(args) -> None:
    s3 = client()
    matches = exact_list(s3, args.bucket, args.key)
    if len(matches) != 1:
        raise RuntimeError(f"expected one exact listing match, got {matches}")
    if int(matches[0]["Size"]) != args.expected_bytes:
        raise RuntimeError("exact-list size mismatch")
    head = s3.head_object(Bucket=args.bucket, Key=args.key)
    if int(head["ContentLength"]) != args.expected_bytes:
        raise RuntimeError("HEAD size mismatch")
    downloaded_bytes, downloaded_sha256 = download_sha256(
        s3, args.bucket, args.key
    )
    if downloaded_bytes != args.expected_bytes:
        raise RuntimeError("download byte count mismatch")
    if downloaded_sha256 != args.expected_sha256:
        raise RuntimeError("download SHA-256 mismatch")
    receipt = {
        "schema_version": 1,
        "decision_id": "DEC-0206",
        "pod_id": args.pod_id,
        "bucket": args.bucket,
        "key": args.key,
        "bytes": args.expected_bytes,
        "etag": str(head.get("ETag", "")).strip('"'),
        "sha256": args.expected_sha256,
        "exact_list_verified": True,
        "head_verified": True,
        "download_round_trip_verified": True,
        "verified_at_utc": utc_now(),
    }
    write_receipt(args.receipt, receipt)
    print(json.dumps(receipt, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    sentinel = subparsers.add_parser("sentinel")
    sentinel.add_argument("--bucket", required=True)
    sentinel.add_argument("--prefix", required=True)
    sentinel.add_argument("--pod-id", required=True)
    sentinel.add_argument("--snapshot-sha256", required=True)
    sentinel.add_argument("--receipt", required=True, type=Path)
    sentinel.set_defaults(func=command_sentinel)

    capacity = subparsers.add_parser("capacity")
    capacity.add_argument("--bucket", required=True)
    capacity.add_argument("--capacity-bytes", required=True, type=int)
    capacity.add_argument("--new-bytes", required=True, type=int)
    capacity.add_argument("--minimum-reserve-bytes", required=True, type=int)
    capacity.set_defaults(func=command_capacity)

    verify = subparsers.add_parser("verify")
    verify.add_argument("--bucket", required=True)
    verify.add_argument("--key", required=True)
    verify.add_argument("--expected-bytes", required=True, type=int)
    verify.add_argument("--expected-sha256", required=True)
    verify.add_argument("--pod-id", required=True)
    verify.add_argument("--receipt", required=True, type=Path)
    verify.set_defaults(func=command_verify)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
