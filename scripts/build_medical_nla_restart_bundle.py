#!/usr/bin/env python3
"""Build a deterministic, credential-free restart bundle for the medical NLA suite."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import shutil
import tarfile
from datetime import datetime, timezone
from pathlib import Path


REQUIRED_FILES = (
    "AGENTS.md",
    "pyproject.toml",
    "uv.lock",
    "prompts/nla/medical_nla_baseline_micro_suite.v2.jsonl",
    "scripts/bootstrap_medical_nla_baseline_v1.sh",
    "scripts/bootstrap_medical_nla_baseline_v2.sh",
    "scripts/run_medical_nla_baseline.py",
    "scripts/run_medical_nla_baseline_v1.sh",
    "scripts/run_medical_nla_baseline_v2.py",
    "scripts/run_medical_nla_baseline_v2.sh",
    "scripts/run_medical_nla_baseline_v3.py",
    "scripts/run_medical_nla_baseline_v3.sh",
    "scripts/run_medical_nla_baseline_v4.py",
    "scripts/run_medical_nla_baseline_decode_resume_v4.sh",
    "scripts/run_medical_nla_baseline_decode_resume_v5.sh",
    "scripts/run_medical_nla_baseline_decode_resume_v6.sh",
    "scripts/run_medical_nla_baseline_decode_resume_v7.sh",
    "configs/frozen/medical_nla_baseline_micro_suite_v1.v1.json",
    "configs/frozen/medical_nla_baseline_micro_suite_v1.v2.json",
    "configs/frozen/medical_nla_baseline_micro_suite_v1.v3.json",
    "configs/frozen/medical_nla_baseline_micro_suite_v1.v4.json",
    "configs/frozen/medical_nla_decode_runtime_repair_v1.v1.json",
    "configs/frozen/medical_nla_decode_runtime_repair_v2.v1.json",
    "configs/frozen/medical_nla_decode_runtime_repair_v3.v1.json",
    "configs/frozen/medical_nla_decode_runtime_repair_v4.v1.json",
    "runs/medical_nla_baseline_micro_suite_v1/preflight/transfer_routes.json",
    "runs/medical_nla_baseline_micro_suite_v2/activation_checkpoint/activations.rows-000032.jsonl",
    "runs/medical_nla_baseline_micro_suite_v2/activation_checkpoint/s3_checkpoint_receipt.json",
    "runs/medical_nla_baseline_micro_suite_v2/runtime_repair/ninja-1.13.0-py3-none-manylinux2014_x86_64.manylinux_2_17_x86_64.whl",
    "runs/medical_nla_baseline_micro_suite_v2/terminal_retrieval_v1/remote_run/activations.jsonl",
    "runs/medical_nla_baseline_micro_suite_v2/terminal_retrieval_v1/remote_run/activations.manifest.json",
    "runs/medical_nla_baseline_micro_suite_v2/terminal_retrieval_v1/remote_run/decoded.jsonl",
    "runs/medical_nla_baseline_micro_suite_v2/terminal_retrieval_v1/remote_run/decoded.manifest.json",
    "runs/medical_nla_baseline_micro_suite_v2/terminal_retrieval_v1/remote_run/decode_attempt_005/server_environment.freeze.txt",
    "runs/medical_nla_baseline_micro_suite_v2/terminal_retrieval_v1/decoded_s3_checkpoint_receipt.json",
    "runs/medical_nla_baseline_micro_suite_v2/terminal_retrieval_v1/retrieval_verification.v1.json",
    "runs/medical_nla_baseline_micro_suite_v2/terminal_retrieval_v1/remote_task_inventory.tsv",
    "runs/medical_nla_baseline_micro_suite_v2/terminal_retrieval_v1/stop_receipt.v2.json",
    "runs/medical_nla_baseline_micro_suite_v2/terminal_retrieval_v1/stop_approval.v2.json",
)

REQUIRED_DIRECTORIES = (
    "skills/medical-nla-experiment-operator",
    "skills/runpod-experiment-operator",
)

IGNORED_PARTS = {"__pycache__", ".DS_Store"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def included_directory_files(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and not any(part in IGNORED_PARTS for part in path.parts)
    )


def copy_payload(repo_root: Path, payload_root: Path) -> list[Path]:
    relative_files = [Path(value) for value in REQUIRED_FILES]
    for relative_directory in REQUIRED_DIRECTORIES:
        directory = repo_root / relative_directory
        if not directory.is_dir():
            raise FileNotFoundError(directory)
        relative_files.extend(
            path.relative_to(repo_root) for path in included_directory_files(directory)
        )

    copied: list[Path] = []
    for relative in sorted(set(relative_files)):
        source = repo_root / relative
        if not source.is_file():
            raise FileNotFoundError(source)
        destination = payload_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        copied.append(relative)
    return copied


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def build_tar(payload_root: Path, tar_path: Path) -> None:
    with tar_path.open("wb") as raw_handle:
        with gzip.GzipFile(
            filename="",
            mode="wb",
            fileobj=raw_handle,
            mtime=0,
        ) as gzip_handle:
            with tarfile.open(fileobj=gzip_handle, mode="w") as archive:
                for source in sorted(path for path in payload_root.rglob("*") if path.is_file()):
                    relative = source.relative_to(payload_root)
                    info = archive.gettarinfo(str(source), arcname=str(relative))
                    info.mtime = 0
                    info.uid = 0
                    info.gid = 0
                    info.uname = ""
                    info.gname = ""
                    with source.open("rb") as source_handle:
                        archive.addfile(info, source_handle)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--approval-id", required=True)
    parser.add_argument("--pod-id", required=True)
    parser.add_argument("--network-volume-id", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    output_root = args.output_root.resolve()
    if output_root.exists():
        raise FileExistsError(f"refusing to overwrite existing output: {output_root}")
    payload_root = output_root / "payload"
    payload_root.mkdir(parents=True)

    copied = copy_payload(repo_root, payload_root)
    restore_contract = {
        "schema_version": 1,
        "approval_id": args.approval_id,
        "source_pod_id": args.pod_id,
        "recovery_network_volume_id": args.network_volume_id,
        "purpose": "Reconstruct a fresh medical NLA runtime without relying on the deleted host-bound Pod volume.",
        "authoritative_scientific_archive": "local repository runs/medical_nla_baseline_micro_suite_v2",
        "recovery_checkpoints": {
            "activations": "runs/medical_nla_baseline_micro_suite_v2/activation_checkpoint/s3_checkpoint_receipt.json",
            "decoded": "runs/medical_nla_baseline_micro_suite_v2/terminal_retrieval_v1/decoded_s3_checkpoint_receipt.json",
        },
        "included": [
            "frozen scientific and runtime snapshots",
            "exact prompt artifact",
            "bootstrap, extraction, and decode runners",
            "Python dependency lock",
            "runtime repair wheel",
            "terminal activations and decoded outputs",
            "environment freeze and provider/runtime receipts",
            "repository-local NLA and RunPod operator skills",
        ],
        "intentionally_not_included": [
            "Python virtual-environment directories",
            "Hugging Face model caches",
            "downloaded model and adapter weight directories",
            "container filesystem state",
            "credentials or access tokens",
        ],
        "reconstruction_rule": "Create a new approved run identity and immutable snapshot; use the included bootstrap and hashes to redownload and verify omitted reproducible dependencies.",
        "scientific_authority": "This bundle preserves prior frozen contracts but does not authorize a future scientific run.",
    }
    write_json(payload_root / "RESTORE_CONTRACT.json", restore_contract)

    manifest_entries = []
    for relative in sorted(copied + [Path("RESTORE_CONTRACT.json")]):
        path = payload_root / relative
        manifest_entries.append(
            {
                "path": str(relative),
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
        )
    payload_manifest = {
        "schema_version": 1,
        "approval_id": args.approval_id,
        "source_pod_id": args.pod_id,
        "network_volume_id": args.network_volume_id,
        "file_count": len(manifest_entries),
        "files": manifest_entries,
    }
    write_json(payload_root / "PAYLOAD_MANIFEST.json", payload_manifest)

    tar_path = output_root / "medical_nla_restart_bundle_v1.tar.gz"
    build_tar(payload_root, tar_path)
    receipt = {
        "schema_version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "approval_id": args.approval_id,
        "source_pod_id": args.pod_id,
        "network_volume_id": args.network_volume_id,
        "payload_file_count": len(manifest_entries) + 1,
        "payload_manifest_sha256": sha256(payload_root / "PAYLOAD_MANIFEST.json"),
        "archive": {
            "path": str(tar_path.relative_to(repo_root)),
            "bytes": tar_path.stat().st_size,
            "sha256": sha256(tar_path),
        },
        "credentials_recorded": False,
        "status": "built_locally",
    }
    write_json(output_root / "local_build_receipt.v1.json", receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
