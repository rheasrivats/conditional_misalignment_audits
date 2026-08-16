#!/usr/bin/env python3
"""Verify the byte identities in the curated public-results manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "results" / "medical" / "artifact_manifest.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_manifest(manifest_path: Path, root: Path = ROOT) -> list[str]:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    failures: list[str] = []

    if payload.get("schema_version") != "public_medical_results_manifest_v1":
        failures.append("unexpected schema_version")

    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        failures.append("artifacts must be a nonempty list")
        return failures

    seen: set[str] = set()
    for index, row in enumerate(artifacts):
        label = f"artifacts[{index}]"
        if not isinstance(row, dict):
            failures.append(f"{label} is not an object")
            continue

        relative = row.get("path")
        expected = row.get("sha256")
        if not isinstance(relative, str) or not relative:
            failures.append(f"{label}.path is invalid")
            continue
        if relative in seen:
            failures.append(f"duplicate path: {relative}")
            continue
        seen.add(relative)

        if not isinstance(expected, str) or len(expected) != 64:
            failures.append(f"{label}.sha256 is invalid")
            continue

        path = root / relative
        try:
            path.resolve().relative_to(root.resolve())
        except ValueError:
            failures.append(f"path escapes repository: {relative}")
            continue
        if not path.is_file():
            failures.append(f"missing artifact: {relative}")
            continue

        actual = sha256_file(path)
        if actual != expected:
            failures.append(
                f"hash mismatch for {relative}: expected {expected}, got {actual}"
            )

    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()

    failures = verify_manifest(args.manifest.resolve())
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1

    print("PUBLIC RESULT VERIFICATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
