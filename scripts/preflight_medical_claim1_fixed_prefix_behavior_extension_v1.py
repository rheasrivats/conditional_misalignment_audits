#!/usr/bin/env python3
"""Fail-closed remote preflight for the response-only fixed-prefix extension."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
from datetime import datetime, timezone
from pathlib import Path


STAGE = "medical_claim1_fixed_prefix_behavior_extension_v1"
PARAMETER = "interventions.medical_claim1_fixed_prefix_behavior_extension_v1"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def allocated_bytes(path: Path) -> int:
    total = 0
    for root, directories, files in os.walk(path, followlinks=False):
        for name in directories + files:
            item = Path(root) / name
            try:
                stat = item.lstat()
            except FileNotFoundError:
                continue
            total += stat.st_blocks * 512
    return total


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--stage-root", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    if args.receipt.exists():
        raise FileExistsError(args.receipt)

    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
    if snapshot.get("stage") != STAGE:
        raise ValueError("snapshot stage differs")
    contract = snapshot["values"][PARAMETER]
    if contract["runtime"]["pod_id"] != "m9fovpckgapiwv":
        raise ValueError("Pod binding differs")
    if Path(contract["output_directory"]).exists():
        raise ValueError("scientific output root already exists")
    execution_root = Path(contract["execution_directory"])
    if execution_root.exists():
        raise ValueError("execution output root already exists")

    for name, spec in contract["code"].items():
        path = args.stage_root / spec["path"]
        if sha256_file(path) != spec["sha256"]:
            raise ValueError(f"code identity differs: {name}")
    predecessor = snapshot["values"][contract["successor_of"]]
    prompt = args.stage_root / predecessor["prompt_artifact"]["path"]
    if sha256_file(prompt) != predecessor["prompt_artifact"]["sha256"]:
        raise ValueError("prompt artifact differs")
    for model in predecessor["models"]:
        if model["kind"] != "adapter":
            continue
        root = Path(model["adapter_path"])
        for name, expected in model["adapter_files"].items():
            if sha256_file(root / name) != expected:
                raise ValueError(f"adapter differs: {name}")

    import torch

    versions = {
        name: importlib.metadata.version(name)
        for name in ("torch", "transformers", "peft", "accelerate", "bitsandbytes")
    }
    runtime = contract["runtime"]
    if versions != runtime["packages"]:
        raise ValueError("runtime package versions differ")
    if platform.python_version() != runtime["python"]:
        raise ValueError("runtime Python differs")
    if str(torch.version.cuda) != runtime["torch_cuda_runtime"]:
        raise ValueError("CUDA runtime differs")
    if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
        raise ValueError("exactly one CUDA GPU is required")
    gpu = torch.cuda.get_device_name(0)
    if runtime["gpu_name_contains"].lower() not in gpu.lower():
        raise ValueError("GPU differs")

    storage = contract["storage"]
    used = allocated_bytes(Path(storage["workspace_path"]))
    required = storage["projected_output_max_bytes"] + storage["minimum_free_reserve_bytes"]
    if used + required > storage["provider_allocation_bytes"]:
        raise ValueError("workspace capacity/reserve gate failed")

    receipt = {
        "schema_version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "decision_id": contract["approval"],
        "stage": STAGE,
        "pod_id": runtime["pod_id"],
        "snapshot_sha256": sha256_file(args.snapshot),
        "status": "runtime_sources_adapter_and_capacity_verified",
        "python": platform.python_version(),
        "versions": versions,
        "torch_cuda_runtime": str(torch.version.cuda),
        "cuda_device_name": gpu,
        "workspace_allocated_bytes": used,
        "projected_output_max_bytes": storage["projected_output_max_bytes"],
        "minimum_free_reserve_bytes": storage["minimum_free_reserve_bytes"],
        "scientific_requests_or_rows": 0,
        "target_output_root_exists": False,
    }
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
