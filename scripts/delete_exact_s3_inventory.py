#!/usr/bin/env python3
"""Delete only an exact, frozen S3 object inventory and emit a receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.config import Config


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def list_prefix(s3, bucket: str, prefix: str) -> list[dict[str, object]]:
    objects: list[dict[str, object]] = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for item in page.get("Contents", []):
            objects.append(
                {
                    "key": item["Key"],
                    "bytes": int(item["Size"]),
                    "etag": str(item["ETag"]).strip('"'),
                }
            )
    return sorted(objects, key=lambda item: str(item["key"]))


def object_exists(s3, bucket: str, key: str) -> bool:
    response = s3.list_objects_v2(Bucket=bucket, Prefix=key)
    return any(item["Key"] == key for item in response.get("Contents", []))


def delete_exact_key(s3, bucket: str, key: str) -> str:
    for attempt in range(1, 11):
        try:
            s3.delete_object(Bucket=bucket, Key=key)
            return key
        except Exception:
            if attempt == 10:
                raise
            time.sleep(min(2**attempt, 30))
    raise AssertionError("unreachable")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", required=True, type=Path)
    parser.add_argument("--expected-inventory-sha256", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--protected-target-key", required=True)
    parser.add_argument("--receipt", required=True, type=Path)
    args = parser.parse_args()

    inventory_path = args.inventory.resolve()
    inventory_sha256 = sha256_file(inventory_path)
    if inventory_sha256 != args.expected_inventory_sha256:
        raise ValueError(
            "inventory SHA-256 mismatch: "
            f"expected {args.expected_inventory_sha256}, got {inventory_sha256}"
        )
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    if inventory["decision_id"] != "DEC-0207":
        raise ValueError("inventory is not bound to DEC-0207")
    expected_objects = [
        {
            "key": item["key"],
            "bytes": int(item["bytes"]),
            "etag": item["etag"],
        }
        for item in inventory["objects"]
    ]
    expected_objects.sort(key=lambda item: item["key"])
    if len(expected_objects) != int(inventory["object_count"]):
        raise ValueError("inventory object_count does not match its objects")
    if sum(item["bytes"] for item in expected_objects) != int(
        inventory["total_bytes"]
    ):
        raise ValueError("inventory total_bytes does not match its objects")
    prefix = inventory["prefix"]
    if not all(item["key"].startswith(prefix) for item in expected_objects):
        raise ValueError("inventory contains a key outside the exact prefix")
    if args.receipt.exists():
        raise FileExistsError(f"refusing to overwrite receipt: {args.receipt}")

    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    s3 = session.client(
        "s3",
        endpoint_url=args.endpoint,
        config=Config(
            region_name=args.region,
            retries={"max_attempts": 10, "mode": "standard"},
            connect_timeout=60,
            read_timeout=600,
        ),
    )

    if object_exists(s3, inventory["bucket"], args.protected_target_key):
        raise RuntimeError("protected completed AV target exists; refusing cleanup")

    actual_objects = list_prefix(s3, inventory["bucket"], prefix)
    if actual_objects != expected_objects:
        raise RuntimeError(
            "live prefix does not exactly reproduce the frozen key/size/ETag "
            "inventory; refusing cleanup"
        )

    deleted_keys: list[str] = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {
            executor.submit(
                delete_exact_key,
                s3,
                inventory["bucket"],
                item["key"],
            ): item["key"]
            for item in expected_objects
        }
        for future in as_completed(futures):
            deleted_keys.append(future.result())
    if sorted(deleted_keys) != [item["key"] for item in expected_objects]:
        raise RuntimeError("per-key deletion completion set mismatch")

    remaining_objects = list_prefix(s3, inventory["bucket"], prefix)
    if remaining_objects:
        raise RuntimeError(
            f"post-delete prefix is not empty: {len(remaining_objects)} objects"
        )

    receipt = {
        "schema_version": 1,
        "decision_id": "DEC-0207",
        "incident_id": "INC-0070",
        "bucket": inventory["bucket"],
        "endpoint": args.endpoint,
        "region": args.region,
        "prefix": prefix,
        "inventory_path": str(inventory_path),
        "inventory_sha256": inventory_sha256,
        "deleted_object_count": len(expected_objects),
        "deleted_total_bytes": sum(item["bytes"] for item in expected_objects),
        "protected_target_key": args.protected_target_key,
        "protected_target_absent_before_cleanup": True,
        "predelete_key_size_etag_inventory_exact": True,
        "deletion_transport": "individual_delete_object_with_bounded_retries",
        "delete_errors": [],
        "postdelete_object_count": 0,
        "verified_at_utc": utc_now(),
    }
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
