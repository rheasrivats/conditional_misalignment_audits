#!/usr/bin/env python3
"""RunPod-compatible immutable JSONL checkpoints without S3 HEAD requests.

The operator-skill helper is fail-closed but assumes that the provider permits
``HeadObject``.  RunPod's S3 endpoint can instead return HTTP 403 for HEAD.
This implementation-only successor preserves the helper's validation,
immutable keys, receipts, and full-download SHA-256 check while replacing:

* pre-upload HEAD with an exact-key ``ListObjectsV2`` absence check;
* single-request PutObject with multipart-capable ``aws s3 cp``; and
* post-upload HEAD with an exact-key ``ListObjectsV2`` size check.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from typing import Any


BASE_PATH = (
    Path(__file__).parents[1]
    / "skills"
    / "runpod-experiment-operator"
    / "scripts"
    / "runpod_s3_checkpoint.py"
)
BASE_SPEC = importlib.util.spec_from_file_location("runpod_s3_checkpoint_v1", BASE_PATH)
if BASE_SPEC is None or BASE_SPEC.loader is None:
    raise RuntimeError(f"cannot load checkpoint helper: {BASE_PATH}")
base = importlib.util.module_from_spec(BASE_SPEC)
BASE_SPEC.loader.exec_module(base)


def exact_listing(
    *,
    profile: str,
    region: str,
    endpoint: str,
    bucket: str,
    key: str,
) -> list[dict[str, Any]]:
    result = base.aws_command(
        profile=profile,
        region=region,
        endpoint=endpoint,
        operation="list-objects-v2",
        extra=["--bucket", bucket, "--prefix", key],
    )
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise base.MirrorError("list-objects-v2 returned invalid JSON") from exc
    contents = value.get("Contents", [])
    if not isinstance(contents, list):
        raise base.MirrorError("list-objects-v2 returned invalid Contents")
    return [
        item
        for item in contents
        if isinstance(item, dict) and item.get("Key") == key
    ]


def ensure_absent_exact_list(**kwargs: str) -> None:
    exact = exact_listing(**kwargs)
    if exact:
        raise base.MirrorError(
            f"immutable checkpoint already exists: "
            f"s3://{kwargs['bucket']}/{kwargs['key']}"
        )


def put_file_multipart(
    *,
    profile: str,
    region: str,
    endpoint: str,
    bucket: str,
    key: str,
    path: Path,
) -> dict[str, Any]:
    command = [
        "aws",
        "s3",
        "cp",
        str(path),
        f"s3://{bucket}/{key}",
        "--profile",
        profile,
        "--region",
        region,
        "--endpoint-url",
        endpoint,
        "--no-progress",
        "--only-show-errors",
    ]
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise base.MirrorError(
            f"aws s3 cp multipart upload failed with exit {result.returncode}: "
            f"{result.stderr.strip()}"
        )
    return {"transport": "aws_s3_cp_multipart"}


def head_object_exact_list(**kwargs: str) -> dict[str, Any]:
    exact = exact_listing(**kwargs)
    if len(exact) != 1:
        raise base.MirrorError(
            f"post-upload exact listing found {len(exact)} objects"
        )
    item = exact[0]
    try:
        size = int(item["Size"])
    except (KeyError, TypeError, ValueError) as exc:
        raise base.MirrorError("listed object lacks a valid Size") from exc
    return {
        "ContentLength": size,
        "ETag": item.get("ETag"),
        "LastModified": item.get("LastModified"),
        "StorageClass": item.get("StorageClass"),
        "VerificationSource": "list-objects-v2_exact_key",
    }


def main() -> int:
    base.ensure_absent = ensure_absent_exact_list
    base.put_file = put_file_multipart
    base.head_object = head_object_exact_list
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
