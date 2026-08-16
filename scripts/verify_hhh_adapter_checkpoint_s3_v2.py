#!/usr/bin/env python3
"""Verify an existing HHH checkpoint via direct S3 GetObject."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any


V1_PATH = Path(__file__).with_name("verify_hhh_adapter_checkpoint_s3_v1.py")
V1_SPEC = importlib.util.spec_from_file_location("verify_hhh_adapter_checkpoint_s3_v1", V1_PATH)
if V1_SPEC is None or V1_SPEC.loader is None:
    raise RuntimeError(f"cannot load existing-object verifier v1: {V1_PATH}")
v1_verify = importlib.util.module_from_spec(V1_SPEC)
V1_SPEC.loader.exec_module(v1_verify)
archive_v1 = v1_verify.v1


def download_via_get_object(args: object, key: str, destination: Path) -> dict[str, Any]:
    if destination.exists():
        raise archive_v1.ArchiveError(f"download destination already exists: {destination}")
    result = v1_verify.v3.ORIGINAL_AWS(
        args,
        "get-object",
        ["--bucket", args.volume_id, "--key", key, str(destination)],
    )
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise archive_v1.ArchiveError("get-object returned invalid JSON") from exc
    value["transport"] = "s3api_get_object_without_head"
    return value


def main() -> int:
    v1_verify.download = download_via_get_object
    return v1_verify.main()


if __name__ == "__main__":
    raise SystemExit(main())
