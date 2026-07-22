#!/usr/bin/env python3
"""Capture and validate the runtime for a frozen construction-training stage."""

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

from construction_snapshot import load_effective_attempt


STAGE = "construction_attempt_training"
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
    parser.add_argument("--launch-spec", type=Path, required=True)
    parser.add_argument("--source-preflight", type=Path, required=True)
    parser.add_argument("--bundle-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    if len(args.bundle_sha256) != 64:
        raise ValueError("bundle SHA-256 must contain exactly 64 hexadecimal characters")
    int(args.bundle_sha256, 16)

    snapshot = json.loads(args.snapshot.read_text())
    if snapshot.get("stage") != STAGE:
        raise ValueError(f"snapshot stage must be {STAGE!r}")
    attempt, masking_successor = load_effective_attempt(snapshot["values"])
    training = attempt["training"]

    expected_python = str(training["python"])
    observed_python = f"{sys.version_info.major}.{sys.version_info.minor}"
    if observed_python != expected_python:
        raise ValueError(
            f"Python {observed_python} does not match frozen {expected_python}"
        )

    expected_packages = {
        name: str(training[name])
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
        raise ValueError("frozen runtime requires CUDA and bf16 support")
    expected_gpu_count = int(attempt["hardware"]["gpu_count"])
    if torch.cuda.device_count() != expected_gpu_count:
        raise ValueError("observed GPU count differs from frozen hardware")
    gpu_names = [
        torch.cuda.get_device_name(index) for index in range(torch.cuda.device_count())
    ]
    expected_fragment = str(attempt["hardware"]["gpu_name_contains"])
    if any(expected_fragment.lower() not in name.lower() for name in gpu_names):
        raise ValueError(f"GPU names {gpu_names!r} do not match {expected_fragment!r}")

    report = {
        "manifest_version": 1,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "stage": STAGE,
        "attempt_id": attempt["attempt_id"],
        "attempt_specification_revision": attempt["specification_revision"],
        "masking_successor_decision": masking_successor["approval_decision"],
        "snapshot": {
            "path": str(args.snapshot),
            "sha256": sha256_file(args.snapshot),
            "registry_sha256": snapshot["registry_sha256"],
        },
        "launch_spec": {
            "path": str(args.launch_spec),
            "sha256": sha256_file(args.launch_spec),
        },
        "source_preflight": {
            "path": str(args.source_preflight),
            "sha256": sha256_file(args.source_preflight),
        },
        "source_bundle_sha256": args.bundle_sha256,
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
    print(f"CONSTRUCTION ENVIRONMENT PREFLIGHT PASSED: {args.output}")


if __name__ == "__main__":
    main()
