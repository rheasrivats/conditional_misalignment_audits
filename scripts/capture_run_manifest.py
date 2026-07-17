#!/usr/bin/env python3
"""Capture the metadata needed to reproduce and audit a micro-pilot run."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import socket
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import torch
from huggingface_hub import HfApi


SAFE_ENVIRONMENT_KEYS = (
    "CUDA_VISIBLE_DEVICES",
    "HF_HOME",
    "TRANSFORMERS_CACHE",
    "PYTORCH_CUDA_ALLOC_CONF",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_command(command: list[str], cwd: Path | None = None) -> dict[str, Any]:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as error:
        return {"available": False, "error": str(error)}
    return {
        "available": result.returncode == 0,
        "returncode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }


def git_state(path: Path) -> dict[str, Any]:
    top = run_command(["git", "rev-parse", "--show-toplevel"], cwd=path)
    if not top["available"]:
        return top
    root = Path(top["stdout"])
    commit = run_command(["git", "rev-parse", "HEAD"], cwd=root)
    status = run_command(["git", "status", "--short"], cwd=root)
    remote = run_command(["git", "remote", "get-url", "origin"], cwd=root)
    return {
        "available": True,
        "root": str(root),
        "commit": commit.get("stdout"),
        "dirty": bool(status.get("stdout")),
        "status": status.get("stdout", "").splitlines(),
        "origin": (
            re.sub(r"(https?://)[^/@]+@", r"\1", remote.get("stdout", ""))
            if remote["available"]
            else None
        ),
    }


def package_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata.get("Name")
        if name:
            versions[name] = distribution.version
    return dict(sorted(versions.items(), key=lambda item: item[0].lower()))


def gpu_state() -> dict[str, Any]:
    query = run_command(
        [
            "nvidia-smi",
            "--query-gpu=index,name,uuid,driver_version,memory.total",
            "--format=csv,noheader,nounits",
        ]
    )
    return {
        "nvidia_smi": query,
        "torch_version": torch.__version__,
        "cuda_runtime": torch.version.cuda,
        "cuda_available": torch.cuda.is_available(),
        "cudnn_version": torch.backends.cudnn.version(),
        "bf16_supported": torch.cuda.is_bf16_supported() if torch.cuda.is_available() else False,
        "device_count": torch.cuda.device_count(),
        "device_names": [
            torch.cuda.get_device_name(index) for index in range(torch.cuda.device_count())
        ],
    }


def resolve_hugging_face_revisions(config: dict[str, Any]) -> dict[str, Any]:
    api = HfApi()
    keys = ("base_model", "em_adapter", "nla_actor", "nla_critic")
    revisions: dict[str, Any] = {}
    for key in keys:
        repo_id = config.get(key)
        if not repo_id:
            continue
        requested_revision = config.get(f"{key}_revision")
        try:
            info = api.model_info(
                repo_id,
                revision=requested_revision,
                files_metadata=False,
            )
            revisions[key] = {
                "repo_id": repo_id,
                "requested_revision": requested_revision,
                "resolved_revision": info.sha,
                "last_modified": info.last_modified.isoformat()
                if info.last_modified
                else None,
            }
        except Exception as error:  # Network/auth failures should not lose the rest.
            revisions[key] = {"repo_id": repo_id, "error": repr(error)}
    return revisions


def parquet_summary(path: Path) -> dict[str, Any]:
    parquet = pq.ParquetFile(path)
    raw_metadata = parquet.schema_arrow.metadata or {}
    schema_metadata = {
        key.decode("utf-8", errors="replace"): value.decode("utf-8", errors="replace")
        for key, value in raw_metadata.items()
    }
    return {
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "rows": parquet.metadata.num_rows,
        "row_groups": parquet.metadata.num_row_groups,
        "columns": parquet.schema_arrow.names,
        "schema_metadata": schema_metadata,
    }


def artifact_inventory(directory: Path, output: Path) -> dict[str, Any]:
    inventory: dict[str, Any] = {}
    if not directory.exists():
        return inventory
    for path in sorted(item for item in directory.rglob("*") if item.is_file()):
        if path.resolve() == output.resolve():
            continue
        relative = str(path.relative_to(directory))
        if path.suffix == ".parquet":
            inventory[relative] = {"kind": "parquet", **parquet_summary(path)}
        else:
            inventory[relative] = {
                "kind": "file",
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
    return inventory


def read_prompt_summary(path: Path) -> dict[str, Any]:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return {
        "path": str(path),
        "sha256": sha256_file(path),
        "count": len(rows),
        "categories": dict(Counter(row["category"] for row in rows)),
        "prompt_ids": [row["prompt_id"] for row in rows],
    }


def source_file_inventory(workspace: Path) -> dict[str, Any]:
    candidates = [
        workspace / "README.md",
        workspace / "pyproject.toml",
        workspace / "uv.lock",
    ]
    for directory in ("analysis", "configs", "prompts", "scripts"):
        root = workspace / directory
        if root.exists():
            candidates.extend(path for path in root.rglob("*") if path.is_file())
    inventory: dict[str, Any] = {}
    for path in sorted(set(candidates)):
        if "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
            continue
        inventory[str(path.relative_to(workspace))] = {
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
    return inventory


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("configs/micro_pilot.json"))
    parser.add_argument("--prompts", type=Path, default=Path("prompts/micro_pilot.jsonl"))
    parser.add_argument("--artifacts-dir", type=Path, default=Path("artifacts"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/run_manifest.json"))
    parser.add_argument("--skip-hf-lookup", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.output.exists() and not args.overwrite:
        raise FileExistsError(f"{args.output} exists; pass --overwrite to replace it")

    config = json.loads(args.config.read_text())
    workspace = Path.cwd()
    manifest = {
        "manifest_version": 2,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "capture_command": sys.argv,
        "configuration": {
            "path": str(args.config),
            "sha256": sha256_file(args.config),
            "content": config,
        },
        "prompts": read_prompt_summary(args.prompts),
        "hugging_face_checkpoints": (
            {"lookup_skipped": True}
            if args.skip_hf_lookup
            else resolve_hugging_face_revisions(config)
        ),
        "artifacts": artifact_inventory(args.artifacts_dir, args.output),
        "source": {
            "workspace": git_state(workspace),
            "source_files": source_file_inventory(workspace),
            "nla_inference": git_state(workspace / "vendor" / "nla-inference")
            if (workspace / "vendor" / "nla-inference").exists()
            else {"available": False, "error": "vendor/nla-inference not found"},
        },
        "runtime": {
            "hostname": socket.gethostname(),
            "platform": platform.platform(),
            "python_version": platform.python_version(),
            "python_executable": sys.executable,
            "working_directory": str(workspace),
            "safe_environment": {
                key: os.environ[key] for key in SAFE_ENVIRONMENT_KEYS if key in os.environ
            },
            "gpu": gpu_state(),
            "packages": package_versions(),
        },
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(f"Wrote reproducibility manifest to {args.output}")

    unresolved = [
        item["repo_id"]
        for item in manifest["hugging_face_checkpoints"].values()
        if isinstance(item, dict) and "error" in item and "repo_id" in item
    ]
    if unresolved:
        print("WARNING: revision lookup failed for: " + ", ".join(unresolved))


if __name__ == "__main__":
    main()
