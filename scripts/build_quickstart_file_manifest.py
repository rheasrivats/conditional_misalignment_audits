#!/usr/bin/env python3
"""Build a deterministic, content-addressed manifest for one directory tree."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def entry_for(path: Path, relative: str) -> dict[str, object]:
    metadata = path.lstat()
    common: dict[str, object] = {
        "path": relative,
        "mode": stat.S_IMODE(metadata.st_mode),
    }
    if stat.S_ISLNK(metadata.st_mode):
        target = os.readlink(path)
        return {
            **common,
            "type": "symlink",
            "target": target,
            "target_sha256": hashlib.sha256(target.encode("utf-8")).hexdigest(),
        }
    if stat.S_ISDIR(metadata.st_mode):
        return {**common, "type": "directory"}
    if stat.S_ISREG(metadata.st_mode):
        return {
            **common,
            "type": "file",
            "bytes": metadata.st_size,
            "sha256": sha256_file(path),
        }
    raise ValueError(f"unsupported filesystem object: {path}")


def build_manifest(root: Path, virtual_prefix: str) -> dict[str, object]:
    if not root.is_dir():
        raise ValueError(f"root is not a directory: {root}")

    entries: list[dict[str, object]] = []
    pending = [root]
    while pending:
        current = pending.pop()
        for child in sorted(current.iterdir(), key=lambda item: item.name):
            relative = child.relative_to(root).as_posix()
            entry = entry_for(child, relative)
            entries.append(entry)
            if entry["type"] == "directory":
                pending.append(child)

    entries.sort(key=lambda item: str(item["path"]))
    files = [item for item in entries if item["type"] == "file"]
    symlinks = [item for item in entries if item["type"] == "symlink"]
    directories = [item for item in entries if item["type"] == "directory"]
    canonical_entries = json.dumps(
        entries, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return {
        "schema_version": 1,
        "virtual_prefix": virtual_prefix,
        "entry_count": len(entries),
        "file_count": len(files),
        "symlink_count": len(symlinks),
        "directory_count": len(directories),
        "file_bytes": sum(int(item["bytes"]) for item in files),
        "entries_sha256": hashlib.sha256(canonical_entries).hexdigest(),
        "entries": entries,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--virtual-prefix", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    manifest = build_manifest(args.root.resolve(), args.virtual_prefix)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
