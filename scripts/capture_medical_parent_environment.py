#!/usr/bin/env python3
"""Capture and validate the frozen medical-parent screen runtime."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


STAGE = "medical_parent_development_screen"
SAFE_ENVIRONMENT_KEYS = (
    "CUDA_VISIBLE_DEVICES",
    "HF_HOME",
    "PYTORCH_CUDA_ALLOC_CONF",
    "TRANSFORMERS_CACHE",
    "UV_CACHE_DIR",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(command: list[str]) -> dict[str, Any]:
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"command failed ({result.returncode}): {command!r}: {result.stderr.strip()}"
        )
    return {
        "command": command,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }


def disk(path: Path) -> dict[str, int | str]:
    usage = shutil.disk_usage(path)
    return {
        "path": str(path),
        "total_bytes": usage.total,
        "used_bytes": usage.used,
        "free_bytes": usage.free,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--source-preflight", type=Path, required=True)
    parser.add_argument("--code-provenance", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    snapshot = json.loads(args.snapshot.read_text())
    if snapshot.get("stage") != STAGE:
        raise ValueError(f"snapshot stage must be {STAGE!r}")
    specification = snapshot["values"][
        "qualification.medical_parent_screen_specification"
    ]
    runtime = specification["runtime"]
    source_preflight = json.loads(args.source_preflight.read_text())
    expected_snapshot_hash = sha256_file(args.snapshot)
    if source_preflight.get("stage_snapshot_sha256") != expected_snapshot_hash:
        raise ValueError("source preflight does not reference this stage snapshot")
    if source_preflight.get("all_frozen_identities_match") is not True:
        raise ValueError("source adapter identity preflight did not pass")

    code_provenance = json.loads(args.code_provenance.read_text())
    if code_provenance.get("stage_snapshot_sha256") != expected_snapshot_hash:
        raise ValueError("code provenance does not reference this stage snapshot")

    observed_python = f"{sys.version_info.major}.{sys.version_info.minor}"
    if observed_python != runtime["python"]:
        raise ValueError(
            f"Python {observed_python!r} does not match frozen {runtime['python']!r}"
        )
    expected_packages = {
        name: str(runtime[name])
        for name in ("torch", "transformers", "peft", "accelerate", "bitsandbytes")
    }
    observed_packages = {
        name: importlib.metadata.version(name) for name in expected_packages
    }
    if observed_packages != expected_packages:
        raise ValueError(
            f"package versions {observed_packages!r} do not match {expected_packages!r}"
        )

    import torch

    if not torch.cuda.is_available() or not torch.cuda.is_bf16_supported():
        raise ValueError("frozen medical screen requires CUDA and bf16 support")
    if torch.cuda.device_count() != runtime["gpu_count"]:
        raise ValueError("observed GPU count differs from frozen medical screen")
    gpu_names = [
        torch.cuda.get_device_name(index) for index in range(torch.cuda.device_count())
    ]
    if any(runtime["gpu_name_contains"].lower() not in name.lower() for name in gpu_names):
        raise ValueError(
            f"GPU names {gpu_names!r} do not match {runtime['gpu_name_contains']!r}"
        )

    report = {
        "manifest_version": 1,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "stage": STAGE,
        "specification_id": specification["specification_id"],
        "snapshot": {
            "path": str(args.snapshot),
            "sha256": expected_snapshot_hash,
            "registry_sha256": snapshot["registry_sha256"],
        },
        "source_preflight": {
            "path": str(args.source_preflight),
            "sha256": sha256_file(args.source_preflight),
        },
        "code_provenance": {
            "path": str(args.code_provenance),
            "sha256": sha256_file(args.code_provenance),
        },
        "capture_script": {
            "path": str(Path(__file__)),
            "sha256": sha256_file(Path(__file__)),
        },
        "runtime": {
            "python": platform.python_version(),
            "python_executable": sys.executable,
            "platform": platform.platform(),
            "packages": observed_packages,
            "torch_cuda_runtime": torch.version.cuda,
            "cudnn_version": torch.backends.cudnn.version(),
            "cuda_available": torch.cuda.is_available(),
            "bf16_supported": torch.cuda.is_bf16_supported(),
            "device_count": torch.cuda.device_count(),
            "device_names": gpu_names,
            "nvidia_smi": run(
                [
                    "nvidia-smi",
                    "--query-gpu=index,name,uuid,driver_version,memory.total",
                    "--format=csv,noheader,nounits",
                ]
            ),
        },
        "storage": {
            "container": disk(Path("/")),
            "workspace": disk(Path("/workspace")),
        },
        "safe_environment": {
            key: os.environ[key] for key in SAFE_ENVIRONMENT_KEYS if key in os.environ
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(f"MEDICAL PARENT ENVIRONMENT PREFLIGHT PASSED: {args.output}")


if __name__ == "__main__":
    main()
