#!/usr/bin/env python3
"""Zero-row fail-closed preflight for the two HHH seed generation panels."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import generate_conditional_misalignment_replication_hhh_seed_panel_v1 as panel


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_exclusive(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--pod-id", required=True)
    args = parser.parse_args()
    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
    stage = snapshot.get("stage")
    parameter = panel.STAGE_CONTRACTS.get(stage)
    if parameter is None:
        raise ValueError(f"unsupported stage: {stage!r}")
    contract = snapshot["values"][parameter]
    runtime = contract["runtime"]
    if runtime["pod_id"] != args.pod_id:
        raise ValueError("Pod identity differs")
    if Path(contract["output_directory"]).exists():
        raise FileExistsError(contract["output_directory"])

    code = contract["code"]
    hashes = {
        "generation_runner_sha256": sha256_file(Path(panel.__file__)),
        "base_generation_runner_sha256": sha256_file(Path(panel.base.__file__)),
        "shared_runner_sha256": sha256_file(Path(panel.base.shared.__file__)),
        "preflight_sha256": sha256_file(Path(__file__)),
    }
    for key, value in hashes.items():
        if code[key] != value:
            raise ValueError(f"code hash differs: {key}")
    if sha256_file(args.workspace / "pyproject.toml") != runtime["pyproject_sha256"]:
        raise ValueError("pyproject hash differs")
    if sha256_file(args.workspace / "uv.lock") != runtime["lockfile_sha256"]:
        raise ValueError("lockfile hash differs")

    prompt_spec = snapshot["values"][panel.base.PANEL_PARAMETER]["prompt_panel"]
    prompt_path = args.workspace / prompt_spec["path"]
    if sha256_file(prompt_path) != prompt_spec["sha256"]:
        raise ValueError("prompt hash differs")
    prompts = panel.base.shared.load_jsonl(prompt_path)
    prompts_by_id = {row["prompt_id"]: row for row in prompts}
    targets = panel.base.validate_targets(prompts_by_id, contract)
    recovery = contract.get("recovery")
    recovered_rows = 0
    if recovery is not None:
        recovered_rows = panel.base.validate_recovery_prefix(
            Path(recovery["source_behavior_path"]), recovery, targets, contract
        )

    adapter = contract["checkpoint"]["adapter"]
    adapter_hashes = {}
    for name, spec in adapter["files"].items():
        path = Path(adapter["directory"]) / name
        if path.stat().st_size != spec["bytes"] or sha256_file(path) != spec["sha256"]:
            raise ValueError(f"adapter differs: {name}")
        adapter_hashes[name] = spec["sha256"]

    import torch
    from huggingface_hub import snapshot_download

    packages = {
        name: importlib.metadata.version(name)
        for name in ("torch", "transformers", "peft", "accelerate", "bitsandbytes")
    }
    if packages != runtime["packages"]:
        raise ValueError("package versions differ")
    if platform.python_version() != runtime["python"] or str(torch.version.cuda) != runtime["torch_cuda_runtime"]:
        raise ValueError("Python or CUDA runtime differs")
    if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
        raise ValueError("exactly one CUDA device is required")
    gpu = torch.cuda.get_device_name(0)
    vram_mib = torch.cuda.get_device_properties(0).total_memory // (1024 * 1024)
    if runtime["gpu_name_contains"].lower() not in gpu.lower():
        raise ValueError("GPU identity differs")
    if vram_mib < runtime["minimum_vram_mib"] or not torch.cuda.is_bf16_supported():
        raise ValueError("GPU capability differs")

    base = snapshot["values"][panel.base.BASE_PARAMETER]
    model_path = Path(snapshot_download(
        repo_id=base["model_repository"], revision=base["model_revision"],
        cache_dir=runtime["model_cache_directory"], local_files_only=True,
    ))
    for name in ("config.json", "model.safetensors.index.json", "tokenizer.json"):
        if not (model_path / name).is_file():
            raise FileNotFoundError(model_path / name)
    request = urllib.request.Request("https://pypi.org/simple/", method="HEAD")
    with urllib.request.urlopen(request, timeout=30) as response:
        network_status = int(response.status)
    if not 200 <= network_status < 400:
        raise ValueError("fresh network preflight failed")

    storage_root = Path(contract["execution"]["host_working_root"])
    storage_root.mkdir(parents=True, exist_ok=True)
    storage_tmp = storage_root / f".storage_preflight_{args.pod_id}.tmp"
    storage_verified = storage_root / f".storage_preflight_{args.pod_id}.verified"
    storage_bytes = os.urandom(8 * 1024 * 1024)
    descriptor = os.open(storage_tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(storage_bytes)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(storage_tmp, storage_verified)
        directory_descriptor = os.open(storage_root, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
        if hashlib.sha256(storage_verified.read_bytes()).digest() != hashlib.sha256(storage_bytes).digest():
            raise ValueError("storage round-trip hash differs")
    finally:
        storage_tmp.unlink(missing_ok=True)
        storage_verified.unlink(missing_ok=True)

    receipt = {
        "schema_version": 1,
        "status": "verified_zero_row_generation_preflight",
        "approval": snapshot["stage_approval"],
        "stage": stage,
        "pod_id": args.pod_id,
        "snapshot_sha256": sha256_file(args.snapshot),
        "code_hashes": hashes,
        "prompt_sha256": prompt_spec["sha256"],
        "adapter_hashes": adapter_hashes,
        "target_rows": len(targets),
        "recovered_rows": recovered_rows,
        "missing_rows": len(targets) - recovered_rows,
        "output_root_absent": True,
        "scientific_rows": 0,
        "packages": packages,
        "python": platform.python_version(),
        "cuda": str(torch.version.cuda),
        "gpu": gpu,
        "vram_mib": vram_mib,
        "bf16": torch.cuda.is_bf16_supported(),
        "model_snapshot_path": str(model_path),
        "network_status": network_status,
        "storage_preflight": {
            "root": str(storage_root),
            "bytes": len(storage_bytes),
            "write_fsync_rename_read_hash_cleanup": "passed",
        },
        "verified_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    write_exclusive(args.receipt, receipt)
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
