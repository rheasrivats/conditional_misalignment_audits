#!/usr/bin/env python3
"""Archive one HHH adapter checkpoint using a multipart-capable upload."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path


V2_PATH = Path(__file__).with_name("archive_hhh_adapter_checkpoint_v2.py")
V2_SPEC = importlib.util.spec_from_file_location("archive_hhh_adapter_checkpoint_v2", V2_PATH)
if V2_SPEC is None or V2_SPEC.loader is None:
    raise RuntimeError(f"cannot load v2 archiver: {V2_PATH}")
v2 = importlib.util.module_from_spec(V2_SPEC)
V2_SPEC.loader.exec_module(v2)
v1 = v2.v1
ORIGINAL_AWS = v1.aws


def flag_value(extra: list[str], flag: str) -> str:
    try:
        index = extra.index(flag)
        return extra[index + 1]
    except (ValueError, IndexError) as exc:
        raise v1.ArchiveError(f"put-object arguments lack {flag}") from exc


def aws_with_multipart_upload(
    args: object,
    operation: str,
    extra: list[str],
    *,
    allow_not_found: bool = False,
) -> subprocess.CompletedProcess[str]:
    if operation != "put-object":
        return ORIGINAL_AWS(
            args,
            operation,
            extra,
            allow_not_found=allow_not_found,
        )
    bucket = flag_value(extra, "--bucket")
    key = flag_value(extra, "--key")
    source = flag_value(extra, "--body")
    command = [
        "aws",
        "s3",
        "cp",
        source,
        f"s3://{bucket}/{key}",
        "--profile",
        args.profile,
        "--region",
        args.region,
        "--endpoint-url",
        args.endpoint,
        "--no-progress",
        "--only-show-errors",
    ]
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise v1.ArchiveError(
            f"aws s3 cp multipart upload failed with exit {result.returncode}: "
            f"{result.stderr.strip()}"
        )
    return subprocess.CompletedProcess(
        args=command,
        returncode=0,
        stdout=json.dumps({"transport": "aws_s3_cp_multipart"}),
        stderr=result.stderr,
    )


def main() -> int:
    v1.ensure_absent = v2.ensure_absent_exact_list
    v1.aws = aws_with_multipart_upload
    return v1.main()


if __name__ == "__main__":
    raise SystemExit(main())
