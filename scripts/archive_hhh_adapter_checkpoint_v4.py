#!/usr/bin/env python3
"""Archive an HHH checkpoint using only RunPod-compatible S3 operations."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path


V3_PATH = Path(__file__).with_name("archive_hhh_adapter_checkpoint_v3.py")
V3_SPEC = importlib.util.spec_from_file_location("archive_hhh_adapter_checkpoint_v3", V3_PATH)
if V3_SPEC is None or V3_SPEC.loader is None:
    raise RuntimeError(f"cannot load multipart archiver v3: {V3_PATH}")
v3 = importlib.util.module_from_spec(V3_SPEC)
V3_SPEC.loader.exec_module(v3)
v2 = v3.v2
v1 = v3.v1


def list_derived_metadata(args: object, extra: list[str]) -> subprocess.CompletedProcess[str]:
    bucket = v3.flag_value(extra, "--bucket")
    key = v3.flag_value(extra, "--key")
    listed = v3.ORIGINAL_AWS(
        args,
        "list-objects-v2",
        ["--bucket", bucket, "--prefix", key],
    )
    try:
        value = json.loads(listed.stdout)
    except json.JSONDecodeError as exc:
        raise v1.ArchiveError("list-objects-v2 returned invalid JSON") from exc
    contents = value.get("Contents", [])
    if not isinstance(contents, list):
        raise v1.ArchiveError("list-objects-v2 returned invalid Contents")
    exact = [item for item in contents if isinstance(item, dict) and item.get("Key") == key]
    if len(exact) != 1:
        raise v1.ArchiveError(f"post-upload exact listing found {len(exact)} objects")
    item = exact[0]
    metadata = {
        "ContentLength": int(item.get("Size", -1)),
        "ETag": item.get("ETag"),
        "LastModified": item.get("LastModified"),
        "StorageClass": item.get("StorageClass"),
        "VerificationSource": "list-objects-v2_exact_key",
    }
    return subprocess.CompletedProcess(
        args=listed.args,
        returncode=0,
        stdout=json.dumps(metadata),
        stderr=listed.stderr,
    )


def aws_runpod_compatible(
    args: object,
    operation: str,
    extra: list[str],
    *,
    allow_not_found: bool = False,
) -> subprocess.CompletedProcess[str]:
    if operation == "put-object":
        return v3.aws_with_multipart_upload(args, operation, extra)
    if operation == "head-object":
        return list_derived_metadata(args, extra)
    return v3.ORIGINAL_AWS(
        args,
        operation,
        extra,
        allow_not_found=allow_not_found,
    )


def main() -> int:
    v1.ensure_absent = v2.ensure_absent_exact_list
    v1.aws = aws_runpod_compatible
    return v1.main()


if __name__ == "__main__":
    raise SystemExit(main())
