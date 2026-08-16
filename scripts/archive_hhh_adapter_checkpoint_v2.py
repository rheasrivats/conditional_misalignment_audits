#!/usr/bin/env python3
"""Archive one HHH adapter checkpoint with an exact-list absence gate.

RunPod's S3 endpoint can return HTTP 403 for HEAD on an absent object.  The
v1 archiver correctly failed closed on that ambiguous response.  This
successor keeps every v1 validation and round-trip check, replacing only the
pre-upload absence probe with an exact-key list operation already exercised by
the frozen local-to-S3 sentinel preflight.
"""

from __future__ import annotations

import json
import importlib.util
from pathlib import Path


V1_PATH = Path(__file__).with_name("archive_hhh_adapter_checkpoint_v1.py")
V1_SPEC = importlib.util.spec_from_file_location("archive_hhh_adapter_checkpoint_v1", V1_PATH)
if V1_SPEC is None or V1_SPEC.loader is None:
    raise RuntimeError(f"cannot load frozen v1 archiver: {V1_PATH}")
v1 = importlib.util.module_from_spec(V1_SPEC)
V1_SPEC.loader.exec_module(v1)


def ensure_absent_exact_list(args: object, key: str) -> None:
    result = v1.aws(
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
    if exact:
        raise v1.ArchiveError(f"immutable object already exists: {key}")


def main() -> int:
    v1.ensure_absent = ensure_absent_exact_list
    return v1.main()


if __name__ == "__main__":
    raise SystemExit(main())
