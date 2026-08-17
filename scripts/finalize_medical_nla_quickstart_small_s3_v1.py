#!/usr/bin/env python3
"""Upload and round-trip verify the small EM8 quick-start archive objects."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError


REPO_ROOT = Path("/Users/rheasrivats/src/conditional_misalignment_audits")
RUN_ROOT = REPO_ROOT / "runs/medical_nla_em8_quickstart_archive_v1"
RECEIPT_ROOT = RUN_ROOT / "s3_receipts"
BUCKET = "pwij8fly18"
ENDPOINT = "https://s3api-eu-cz-1.runpod.io/"
REGION = "eu-cz-1"
PROFILE = "runpod-recovery"
PREFIX = "recovery/quickstart/medical_nla_em8_v1"
CAPACITY_BYTES = 50_000_000_000
RESERVE_BYTES = 1_073_741_824


@dataclass(frozen=True)
class ArchiveObject:
    name: str
    path: Path
    size: int
    sha256: str

    @property
    def key(self) -> str:
        return f"{PREFIX}/{self.sha256}/{self.name}"

    @property
    def receipt(self) -> Path:
        return RECEIPT_ROOT / f"{self.name}.s3_receipt.v1.json"


OBJECTS = (
    ArchiveObject(
        "runtime_rebuild.tar",
        RUN_ROOT / "archives/runtime_rebuild.tar",
        32_942_080,
        "adc6c019719118ab52c56e37b8845ebd93bbdb6661e82fe8beaa14d6731b9a24",
    ),
    ArchiveObject(
        "archive_manifest.v1.json",
        RUN_ROOT / "manifests/archive_manifest.v1.json",
        2_661,
        "0b818bdc7eb12f7c1e05eab3db0c61f94c5b4c4cc31b2d2d7c92501f71bf9d97",
    ),
    ArchiveObject(
        "restore_contract.v1.json",
        RUN_ROOT / "restore_contract.v1.json",
        2_918,
        "e8f2b8c01eb1a0958db354a8dd5d4b277acfd7e349441bdfaad76586deac4603",
    ),
    ArchiveObject(
        "RESTORE.md",
        RUN_ROOT / "RESTORE.md",
        1_030,
        "8a9a6c3a54facd7a540f6c558bdc87ff462fbce675d3188390e4c966e3f902f3",
    ),
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def exact_list(s3, key: str) -> list[dict[str, object]]:
    response = s3.list_objects_v2(Bucket=BUCKET, Prefix=key)
    return [
        {
            "key": item["Key"],
            "size": int(item["Size"]),
            "etag": str(item["ETag"]).strip('"'),
        }
        for item in response.get("Contents", [])
        if item["Key"] == key
    ]


def current_volume_bytes(s3) -> int:
    total = 0
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=BUCKET):
        total += sum(int(item["Size"]) for item in page.get("Contents", []))
    return total


def download_sha256(s3, key: str) -> tuple[int, str]:
    for attempt in range(1, 11):
        try:
            response = s3.get_object(Bucket=BUCKET, Key=key)
            digest = hashlib.sha256()
            size = 0
            body = response["Body"]
            while chunk := body.read(8 * 1024 * 1024):
                size += len(chunk)
                digest.update(chunk)
            return size, digest.hexdigest()
        except ClientError:
            if attempt == 10:
                raise
            time.sleep(min(2**attempt, 30))
    raise AssertionError("unreachable")


def head_with_retry(s3, key: str):
    for attempt in range(1, 11):
        try:
            return s3.head_object(Bucket=BUCKET, Key=key)
        except ClientError:
            if attempt == 10:
                raise
            time.sleep(min(2**attempt, 30))
    raise AssertionError("unreachable")


def write_receipt(obj: ArchiveObject, payload: dict[str, object]) -> None:
    if obj.receipt.exists():
        raise FileExistsError(f"refusing to overwrite receipt: {obj.receipt}")
    obj.receipt.parent.mkdir(parents=True, exist_ok=True)
    temporary = obj.receipt.with_name(f".{obj.receipt.name}.tmp")
    if temporary.exists():
        raise FileExistsError(f"refusing to overwrite temporary receipt: {temporary}")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(obj.receipt)


def main() -> None:
    session = boto3.Session(profile_name=PROFILE, region_name=REGION)
    s3 = session.client(
        "s3",
        endpoint_url=ENDPOINT,
        config=Config(
            region_name=REGION,
            retries={"max_attempts": 10, "mode": "standard"},
            connect_timeout=60,
            read_timeout=600,
        ),
    )

    for obj in OBJECTS:
        if obj.receipt.exists():
            raise FileExistsError(f"refusing to overwrite receipt: {obj.receipt}")
        if obj.path.stat().st_size != obj.size:
            raise RuntimeError(f"local size mismatch: {obj.path}")
        if sha256_file(obj.path) != obj.sha256:
            raise RuntimeError(f"local SHA-256 mismatch: {obj.path}")

        matches = exact_list(s3, obj.key)
        if not matches:
            used = current_volume_bytes(s3)
            projected = used + obj.size
            free_after = CAPACITY_BYTES - projected
            if free_after < RESERVE_BYTES:
                raise RuntimeError(
                    "capacity gate failed: "
                    f"used={used} new={obj.size} free_after={free_after} "
                    f"reserve={RESERVE_BYTES}"
                )
            s3.upload_file(str(obj.path), BUCKET, obj.key)
            matches = exact_list(s3, obj.key)

        if len(matches) != 1 or int(matches[0]["size"]) != obj.size:
            raise RuntimeError(f"exact-list verification failed for {obj.name}: {matches}")
        head = head_with_retry(s3, obj.key)
        if int(head["ContentLength"]) != obj.size:
            raise RuntimeError(f"HEAD size mismatch for {obj.name}")
        downloaded_size, downloaded_sha256 = download_sha256(s3, obj.key)
        if downloaded_size != obj.size or downloaded_sha256 != obj.sha256:
            raise RuntimeError(f"round-trip verification failed for {obj.name}")

        receipt = {
            "schema_version": 1,
            "decision_id": "DEC-0206",
            "run_id": "medical_nla_em8_quickstart_archive_v1",
            "name": obj.name,
            "local_path": str(obj.path),
            "s3_bucket": BUCKET,
            "s3_key": obj.key,
            "bytes": obj.size,
            "etag": str(head.get("ETag", "")).strip('"'),
            "sha256": obj.sha256,
            "exact_list_verified": True,
            "head_verified": True,
            "download_round_trip_verified": True,
            "verified_at_utc": utc_now(),
        }
        write_receipt(obj, receipt)
        print(json.dumps(receipt, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
