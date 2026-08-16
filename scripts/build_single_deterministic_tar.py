#!/usr/bin/env python3
"""Build and verify one deterministic uncompressed PAX tar archive."""

from __future__ import annotations

import argparse
import hashlib
import json
import tarfile
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def normalize(info: tarfile.TarInfo) -> tarfile.TarInfo:
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mtime = 0
    info.pax_headers = {}
    return info


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--archive-prefix", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--expected-bytes", required=True, type=int)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--receipt", required=True, type=Path)
    args = parser.parse_args()

    source = args.source.resolve()
    output = args.output.resolve()
    if not source.is_dir():
        raise ValueError(f"source is not a directory: {source}")
    if output.exists():
        raise FileExistsError(f"refusing to overwrite: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)

    with tarfile.open(output, mode="w", format=tarfile.PAX_FORMAT) as archive:
        archive.add(
            source,
            arcname=args.archive_prefix,
            recursive=True,
            filter=normalize,
        )

    actual_bytes = output.stat().st_size
    actual_sha256 = sha256_file(output)
    if actual_bytes != args.expected_bytes:
        raise ValueError(
            f"archive size mismatch: expected {args.expected_bytes}, got {actual_bytes}"
        )
    if actual_sha256 != args.expected_sha256:
        raise ValueError(
            f"archive SHA-256 mismatch: expected {args.expected_sha256}, "
            f"got {actual_sha256}"
        )

    receipt = {
        "schema_version": 1,
        "source": str(source),
        "archive_prefix": args.archive_prefix,
        "output": str(output),
        "bytes": actual_bytes,
        "sha256": actual_sha256,
        "deterministic_tar_verified": True,
    }
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    if args.receipt.exists():
        raise FileExistsError(f"refusing to overwrite: {args.receipt}")
    args.receipt.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
