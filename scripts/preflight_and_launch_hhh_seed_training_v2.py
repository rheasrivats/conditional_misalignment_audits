#!/usr/bin/env python3
"""Fail-closed attempt-2 preflight and launch for one HHH seed-training lane."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import platform
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


STAGES = {
    "conditional_misalignment_replication_hhh_train_seed_1_v1": "seed_1",
    "conditional_misalignment_replication_hhh_train_seed_2_v1": "seed_2",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_exclusive(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def contracts(snapshot: dict[str, Any]) -> tuple[str, dict[str, Any], dict[str, Any]]:
    stage = snapshot.get("stage")
    lane_name = STAGES.get(stage)
    if lane_name is None:
        raise ValueError(f"unapproved stage: {stage!r}")
    values = snapshot.get("values")
    if not isinstance(values, dict):
        raise ValueError("snapshot values must be a mapping")
    runtime = copy.deepcopy(
        values["execution.conditional_misalignment_replication_hhh_seed_training_runtime_v1"]
    )
    successor = values[
        "execution.conditional_misalignment_replication_hhh_seed_training_runtime_v2"
    ]
    runtime["approval"] = successor["approval"]
    runtime["shared"]["code"].update(successor["code"])
    runtime["launch_preflight"] = successor["launch_preflight"]
    migration = values.get(
        "execution.conditional_misalignment_replication_hhh_seed_training_runtime_v4"
    )
    if migration is not None:
        runtime["approval"] = migration["approval"]
        runtime["shared"]["code"].update(migration["code"])
        for name, override in migration["lanes"].items():
            runtime["lanes"][name]["hardware"].update(override["hardware"])
    recovery = values[
        "execution.conditional_misalignment_replication_hhh_seed_training_runtime_v6"
    ]
    runtime["approval"] = recovery["approval"]
    runtime["shared"]["code"].update(recovery["code"])
    runtime["shared"]["locked_environment"]["fresh_environment_root"] = recovery[
        "fresh_environment_root"
    ]
    runtime["attempt_namespace"] = recovery["attempt_namespace"]
    lane = runtime["lanes"][lane_name]
    if lane["stage"] != stage:
        raise ValueError("runtime lane stage differs")
    return lane_name, runtime, lane


def command_json(command: list[str], *, env: dict[str, str] | None = None) -> Any:
    result = subprocess.run(command, check=True, text=True, capture_output=True, env=env)
    return json.loads(result.stdout)


def preflight(args: argparse.Namespace, snapshot: dict[str, Any]) -> None:
    lane_name, runtime, lane = contracts(snapshot)
    shared = runtime["shared"]
    root = Path(__file__).resolve().parents[1]
    snapshot_sha = sha256_file(args.snapshot)
    run_id = lane["paths"]["output_directory"].rsplit("/", 1)[-1]
    staging = Path("/workspace/staging") / run_id / runtime["attempt_namespace"]
    receipt_path = staging / "preflight_receipt.json"
    if staging.exists():
        raise FileExistsError(staging)
    output = Path(lane["paths"]["output_directory"])
    if output.exists():
        raise FileExistsError(output)

    expected = shared["code"]
    observed = {
        "training_runner_sha256": sha256_file(root / "scripts/train_medical_hhh_only_adapter.py"),
        "shared_checkpoint_helper_sha256": sha256_file(root / "scripts/train_medical_post_hoc_adapter.py"),
        "masking_implementation_sha256": sha256_file(root / "scripts/train_construction_adapter.py"),
        "launch_preflight_sha256": sha256_file(Path(__file__)),
        "construction_snapshot_sha256": sha256_file(
            root / "scripts/construction_snapshot.py"
        ),
    }
    for key, value in observed.items():
        if expected[key] != value:
            raise ValueError(f"code hash differs: {key}")
    if sha256_file(root / "pyproject.toml") != shared["locked_environment"]["pyproject_sha256"]:
        raise ValueError("pyproject hash differs")
    if sha256_file(root / "uv.lock") != shared["locked_environment"]["lockfile_sha256"]:
        raise ValueError("lockfile hash differs")

    dataset = Path(shared["paths"]["dataset_repository_root"]) / snapshot["values"][
        "training.medical_hhh_only_development_recipe"
    ]["dataset"]["source_path"]
    dataset_spec = snapshot["values"][
        "training.conditional_misalignment_replication_hhh_additional_seed_plan_v1"
    ]["shared_scientific_contract"]
    if dataset.stat().st_size != dataset_spec["dataset_bytes"]:
        raise ValueError("dataset byte count differs")
    if sha256_file(dataset) != dataset_spec["dataset_sha256"]:
        raise ValueError("dataset hash differs")

    s3_receipt = json.loads(args.s3_receipt.read_text())
    if s3_receipt.get("approval_id") != runtime["approval"]:
        raise ValueError("S3 receipt approval differs")
    if s3_receipt.get("pod_id") != lane["hardware"]["pod_id"]:
        raise ValueError("S3 receipt Pod differs")
    if s3_receipt.get("snapshot_sha256") not in (None, snapshot_sha):
        raise ValueError("S3 receipt snapshot differs")
    if not s3_receipt.get("download_round_trip_verified"):
        raise ValueError("S3 round trip was not verified")

    request = urllib.request.Request("https://pypi.org/simple/", method="HEAD")
    with urllib.request.urlopen(request, timeout=30) as response:
        network_status = int(response.status)
    if network_status < 200 or network_status >= 400:
        raise ValueError("fresh package-index network preflight failed")

    environment = Path(shared["locked_environment"]["fresh_environment_root"])
    if environment.exists():
        raise FileExistsError(environment)
    sync_env = os.environ.copy()
    sync_env["UV_PROJECT_ENVIRONMENT"] = str(environment)
    sync_env["UV_HTTP_TIMEOUT"] = "300"
    subprocess.run(
        ["uv", "sync", "--locked", "--no-dev", "--extra", "training"],
        cwd=root,
        env=sync_env,
        check=True,
    )
    python = environment / "bin/python"
    import_audit = command_json(
        [
            str(python),
            "-c",
            (
                "import json,sys;"
                f"sys.path.insert(0,{str(root / 'scripts')!r});"
                "import train_medical_hhh_only_adapter;"
                "print(json.dumps({'training_runner_imported':True}))"
            ),
        ]
    )
    if import_audit != {"training_runner_imported": True}:
        raise ValueError("training runner import audit differs")
    audit = command_json(
        [
            str(python),
            "-c",
            (
                "import importlib.metadata,json,platform,torch;"
                "print(json.dumps({'python':platform.python_version(),"
                "'cuda':str(torch.version.cuda),'cuda_available':torch.cuda.is_available(),"
                "'gpu_count':torch.cuda.device_count(),"
                "'gpu':torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,"
                "'vram_mib':torch.cuda.get_device_properties(0).total_memory//(1024*1024) if torch.cuda.is_available() else 0,"
                "'bf16':torch.cuda.is_bf16_supported() if torch.cuda.is_available() else False,"
                "'packages':{n:importlib.metadata.version(n) for n in "
                "('torch','transformers','peft','accelerate','bitsandbytes')}}))"
            ),
        ]
    )
    hardware = {**shared["hardware"], **lane["hardware"]}
    if audit["python"] != shared["python"] or audit["cuda"] != shared["torch_cuda_runtime"]:
        raise ValueError("Python or CUDA runtime differs")
    if audit["packages"] != shared["packages"]:
        raise ValueError("package versions differ")
    if not audit["cuda_available"] or audit["gpu_count"] != hardware["gpu_count"]:
        raise ValueError("CUDA device count differs")
    if hardware["gpu_name_contains"].lower() not in audit["gpu"].lower():
        raise ValueError("GPU identity differs")
    if audit["vram_mib"] < hardware["minimum_vram_mib"] or not audit["bf16"]:
        raise ValueError("GPU capability differs")

    model_audit = command_json(
        [
            str(python),
            "-c",
            (
                "import json; from huggingface_hub import snapshot_download;"
                "p=snapshot_download(repo_id='Qwen/Qwen2.5-7B-Instruct',"
                "revision='a09a35458c702b33eeacc393d103063234e8bc28',"
                f"cache_dir={str(Path(shared['paths']['model_cache_directory']))!r},local_files_only=True);"
                "print(json.dumps({'snapshot_path':p}))"
            ),
        ]
    )
    model_path = Path(model_audit["snapshot_path"])
    for filename in ("config.json", "model.safetensors.index.json", "tokenizer.json"):
        if not (model_path / filename).is_file():
            raise FileNotFoundError(model_path / filename)

    staging.mkdir(parents=True)
    receipt = {
        "schema_version": 1,
        "approval": runtime["approval"],
        "stage": snapshot["stage"],
        "lane": lane_name,
        "pod_id": lane["hardware"]["pod_id"],
        "snapshot_sha256": snapshot_sha,
        "code_hashes": observed,
        "dataset_sha256": dataset_spec["dataset_sha256"],
        "network_status": network_status,
        "runtime_audit": audit,
        "model_snapshot_path": str(model_path),
        "s3_receipt_sha256": sha256_file(args.s3_receipt),
        "scientific_output_root_absent": True,
        "scientific_optimizer_steps": 0,
        "training_runner_imported": True,
        "verified_at_utc": now_utc(),
    }
    write_exclusive(receipt_path, receipt)
    print(json.dumps(receipt, sort_keys=True))


def launch(args: argparse.Namespace, snapshot: dict[str, Any]) -> None:
    _, runtime, lane = contracts(snapshot)
    shared = runtime["shared"]
    snapshot_sha = sha256_file(args.snapshot)
    run_id = lane["paths"]["output_directory"].rsplit("/", 1)[-1]
    staging = Path("/workspace/staging") / run_id / runtime["attempt_namespace"]
    preflight_receipt_path = staging / "preflight_receipt.json"
    launch_token_path = staging / "launch_authorization.json"
    pid_path = staging / "training.pid"
    stdout_path = staging / "training.stdout.log"
    stderr_path = staging / "training.stderr.log"
    output = Path(lane["paths"]["output_directory"])
    if output.exists() or pid_path.exists() or stdout_path.exists() or stderr_path.exists():
        raise FileExistsError("lane output or process files already exist")
    receipt = json.loads(preflight_receipt_path.read_text())
    token = json.loads(launch_token_path.read_text())
    expected = {
        "approval": runtime["approval"],
        "pod_id": lane["hardware"]["pod_id"],
        "stage": snapshot["stage"],
        "snapshot_sha256": snapshot_sha,
        "preflight_receipt_sha256": sha256_file(preflight_receipt_path),
        "launch_authorized": True,
    }
    if token != expected:
        raise ValueError("launch authorization token differs")
    if (
        receipt.get("snapshot_sha256") != snapshot_sha
        or receipt.get("scientific_optimizer_steps") != 0
        or receipt.get("training_runner_imported") is not True
    ):
        raise ValueError("preflight receipt differs")
    python = Path(shared["locked_environment"]["fresh_environment_root"]) / "bin/python"
    stdout_handle = stdout_path.open("x", encoding="utf-8")
    stderr_handle = stderr_path.open("x", encoding="utf-8")
    process = subprocess.Popen(
        [str(python), str(Path(__file__).with_name("train_medical_hhh_only_adapter.py")), "--snapshot", str(args.snapshot)],
        stdin=subprocess.DEVNULL,
        stdout=stdout_handle,
        stderr=stderr_handle,
        start_new_session=True,
    )
    stdout_handle.close()
    stderr_handle.close()
    pid_path.write_text(f"{process.pid}\n", encoding="utf-8")
    print(json.dumps({"stage": snapshot["stage"], "pid": process.pid, "launched_at_utc": now_utc()}, sort_keys=True))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--mode", required=True, choices=("preflight", "launch"))
    parser.add_argument("--s3-receipt", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    snapshot = json.loads(args.snapshot.read_text())
    if args.mode == "preflight":
        if args.s3_receipt is None:
            raise ValueError("--s3-receipt is required for preflight")
        preflight(args, snapshot)
    else:
        launch(args, snapshot)


if __name__ == "__main__":
    main()
