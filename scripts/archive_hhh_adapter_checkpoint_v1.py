#!/usr/bin/env python3
"""Archive one complete HHH adapter checkpoint to immutable RunPod S3."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
CHECKPOINT = re.compile(r"^exposure_[0-9]{6}$")


class ArchiveError(ValueError):
    """An immutable-checkpoint invariant failed."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_safe_id(value: str, label: str) -> str:
    if not SAFE_ID.fullmatch(value):
        raise ArchiveError(f"unsafe {label}: {value!r}")
    return value


def validate_checkpoint(
    source: Path, checkpoint_label: str, snapshot_sha256: str
) -> dict[str, Any]:
    if not CHECKPOINT.fullmatch(checkpoint_label):
        raise ArchiveError(f"invalid checkpoint label: {checkpoint_label!r}")
    if source.name != checkpoint_label or not source.is_dir():
        raise ArchiveError("source directory does not match checkpoint label")
    required = {
        "adapter_config.json",
        "adapter_model.safetensors",
        "checkpoint_manifest.json",
    }
    observed = {str(path.relative_to(source)) for path in source.rglob("*") if path.is_file()}
    missing = sorted(required - observed)
    if missing:
        raise ArchiveError(f"checkpoint lacks required files: {missing!r}")
    for path in source.rglob("*"):
        if path.is_symlink() or (not path.is_file() and not path.is_dir()):
            raise ArchiveError(f"unsupported checkpoint entry: {path}")
    manifest = json.loads((source / "checkpoint_manifest.json").read_text())
    if manifest.get("label") != checkpoint_label:
        raise ArchiveError("checkpoint manifest label differs")
    if manifest.get("kind") != "within_run_exposure_checkpoint":
        raise ArchiveError("checkpoint manifest kind differs")
    if manifest.get("stage_snapshot_sha256") != snapshot_sha256:
        raise ArchiveError("checkpoint manifest snapshot differs")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise ArchiveError("checkpoint manifest file map is empty")
    for relative, expected in sorted(files.items()):
        path = source / relative
        if not path.is_file() or path.is_symlink():
            raise ArchiveError(f"manifest file is absent or unsafe: {relative}")
        actual = {"bytes": path.stat().st_size, "sha256": sha256_file(path)}
        if actual != expected:
            raise ArchiveError(f"manifest file differs: {relative}")
    return manifest


def normalize(info: tarfile.TarInfo) -> tarfile.TarInfo:
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mtime = 0
    info.pax_headers = {}
    return info


def build_deterministic_tar(source: Path, output: Path, prefix: str) -> None:
    if output.exists():
        raise ArchiveError(f"archive already exists: {output}")
    with tarfile.open(output, mode="x", format=tarfile.PAX_FORMAT) as archive:
        root_info = archive.gettarinfo(str(source), arcname=prefix)
        archive.addfile(normalize(root_info))
        for path in sorted(source.rglob("*"), key=lambda item: item.as_posix()):
            relative = path.relative_to(source).as_posix()
            info = archive.gettarinfo(str(path), arcname=f"{prefix}/{relative}")
            info = normalize(info)
            if path.is_file():
                with path.open("rb") as handle:
                    archive.addfile(info, handle)
            else:
                archive.addfile(info)


def aws(
    args: argparse.Namespace,
    operation: str,
    extra: list[str],
    *,
    allow_not_found: bool = False,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [
            "aws",
            "s3api",
            operation,
            "--profile",
            args.profile,
            "--region",
            args.region,
            "--endpoint-url",
            args.endpoint,
            *extra,
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    not_found = any(text in result.stderr for text in ("Not Found", "404", "NoSuchKey"))
    if result.returncode != 0 and not (allow_not_found and not_found):
        raise ArchiveError(
            f"aws s3api {operation} failed with exit {result.returncode}: "
            f"{result.stderr.strip()}"
        )
    return result


def ensure_absent(args: argparse.Namespace, key: str) -> None:
    result = aws(
        args,
        "head-object",
        ["--bucket", args.volume_id, "--key", key],
        allow_not_found=True,
    )
    if result.returncode == 0:
        raise ArchiveError(f"immutable object already exists: {key}")


def write_exclusive(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--checkpoint-label", required=True)
    parser.add_argument("--approval-id", required=True)
    parser.add_argument("--snapshot-sha256", required=True)
    parser.add_argument("--volume-id", required=True)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--receipt-out", required=True, type=Path)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        for value, label in (
            (args.run_id, "run id"),
            (args.approval_id, "approval id"),
            (args.volume_id, "volume id"),
            (args.region, "region"),
            (args.profile, "profile"),
        ):
            require_safe_id(value, label)
        if not re.fullmatch(r"[0-9a-f]{64}", args.snapshot_sha256):
            raise ArchiveError("snapshot SHA-256 is invalid")
        if args.receipt_out.exists():
            raise ArchiveError(f"receipt already exists: {args.receipt_out}")
        source = args.source.resolve()
        manifest = validate_checkpoint(
            source, args.checkpoint_label, args.snapshot_sha256
        )
        with tempfile.TemporaryDirectory(prefix="hhh-adapter-checkpoint.") as temp_text:
            temp = Path(temp_text)
            archive_path = temp / f"{args.checkpoint_label}.tar"
            build_deterministic_tar(source, archive_path, args.checkpoint_label)
            digest = sha256_file(archive_path)
            byte_count = archive_path.stat().st_size
            key_root = f"runs/{args.run_id}/checkpoints/{args.checkpoint_label}-{digest[:12]}"
            archive_key = f"{key_root}/{args.checkpoint_label}.tar"
            receipt: dict[str, Any] = {
                "schema_version": 1,
                "status": "dry_run" if args.dry_run else "verified",
                "run_id": args.run_id,
                "approval_id": args.approval_id,
                "checkpoint_label": args.checkpoint_label,
                "source_path": str(source),
                "snapshot_sha256": args.snapshot_sha256,
                "optimizer_step": manifest.get("optimizer_step"),
                "processed_examples": manifest.get("processed_examples"),
                "archive_bytes": byte_count,
                "archive_sha256": digest,
                "network_volume_id": args.volume_id,
                "endpoint": args.endpoint,
                "region": args.region,
                "profile_name": args.profile,
                "archive_key": archive_key,
                "credentials_recorded": False,
            }
            if not args.dry_run:
                ensure_absent(args, archive_key)
                put = aws(
                    args,
                    "put-object",
                    ["--bucket", args.volume_id, "--key", archive_key, "--body", str(archive_path)],
                )
                head = aws(
                    args,
                    "head-object",
                    ["--bucket", args.volume_id, "--key", archive_key],
                )
                head_value = json.loads(head.stdout)
                if head_value.get("ContentLength") != byte_count:
                    raise ArchiveError("remote archive byte count differs")
                downloaded = temp / "downloaded.tar"
                get = aws(
                    args,
                    "get-object",
                    ["--bucket", args.volume_id, "--key", archive_key, str(downloaded)],
                )
                downloaded_sha = sha256_file(downloaded)
                if downloaded_sha != digest:
                    raise ArchiveError("download round-trip SHA-256 differs")
                receipt.update(
                    {
                        "put_response": json.loads(put.stdout),
                        "remote_head": head_value,
                        "download_response": json.loads(get.stdout),
                        "downloaded_sha256": downloaded_sha,
                        "round_trip_verified": True,
                        "verified_at_utc": datetime.now(timezone.utc).isoformat(),
                    }
                )
            write_exclusive(args.receipt_out, receipt)
            print(json.dumps(receipt, sort_keys=True))
        return 0
    except (ArchiveError, OSError, json.JSONDecodeError) as exc:
        print(f"HHH CHECKPOINT ARCHIVE BLOCKED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
