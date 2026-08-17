#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 1 ]]; then
  echo "usage: $0 <snapshot-file>" >&2
  exit 2
fi

snapshot_file=$1
stage_root=/workspace/staging/medical_claim1_fixed_prefix_phase1_v1
venv_dir=/workspace/venvs/medical-claim1-fixed-prefix-phase1-v1
preflight_root="${stage_root}/preflight/attempt_003"
model_audit="${preflight_root}/base_qwen.reaudit.v1.json"
receipt_path="${preflight_root}/runtime_rebuild_and_source_receipt.v3.json"

test "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["stage"])' "$snapshot_file")" = medical_claim1_fixed_prefix_phase1_v1
test ! -e "$venv_dir"
test ! -e "$preflight_root"
test ! -e /workspace/runs/medical_claim1_fixed_prefix_phase1_v1
mkdir -p "$preflight_root" /workspace/venvs

cd "$stage_root"
test "$(sha256sum pyproject.toml | awk '{print $1}')" = e8d751f1b390c639934dd53b4f96bf2496a13d30818dc2d35ad83a679ebc676a
test "$(sha256sum uv.lock | awk '{print $1}')" = 02883ba4337de89bf3f9902ecbff757ab1ccff7fdbae30ec301c3707eb8f419d

UV_HTTP_TIMEOUT=300 UV_PROJECT_ENVIRONMENT="$venv_dir" \
  uv sync --locked --no-dev --extra training

python3 "$stage_root/scripts/build_quickstart_file_manifest.py" \
  --root /workspace/shared/models/huggingface/hub \
  --virtual-prefix /workspace/shared/models/huggingface/hub \
  --output "$model_audit"

"$venv_dir/bin/python" - "$snapshot_file" "$model_audit" "$receipt_path" "$0" <<'PY'
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import pathlib
import platform
import shutil
import sys
from datetime import datetime, timezone


snapshot_path = pathlib.Path(sys.argv[1])
model_audit_path = pathlib.Path(sys.argv[2])
receipt_path = pathlib.Path(sys.argv[3])
self_path = pathlib.Path(sys.argv[4])
snapshot = json.loads(snapshot_path.read_text())
contract = snapshot["values"]["interventions.medical_claim1_fixed_prefix_phase1_v1"]
migration = snapshot["values"]["execution.medical_claim1_fixed_prefix_phase1_migration_v1"]
successor = snapshot["values"]["execution.medical_claim1_fixed_prefix_phase1_runtime_rebuild_v1"]


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if sha256_file(self_path) != successor["code"]["bootstrap_sha256"]:
    raise ValueError("runtime bootstrap differs from frozen identity")
if successor["replacement_pod_id"] != migration["replacement_pod_id"]:
    raise ValueError("runtime successor references another replacement Pod")
for name, spec in contract["code"].items():
    if not isinstance(spec, dict) or "path" not in spec:
        continue
    path = pathlib.Path("/workspace/staging/medical_claim1_fixed_prefix_phase1_v1") / spec["path"]
    if sha256_file(path) != spec["sha256"]:
        raise ValueError(f"code/source identity differs: {name}")

prompt_path = pathlib.Path("/workspace/staging/medical_claim1_fixed_prefix_phase1_v1") / contract["prompt_artifact"]["path"]
if sha256_file(prompt_path) != contract["prompt_artifact"]["sha256"]:
    raise ValueError("prompt artifact differs")
prefix_path = pathlib.Path("/workspace/staging/medical_claim1_fixed_prefix_phase1_v1") / contract["prefix_selection_artifact"]["path"]
if sha256_file(prefix_path) != contract["prefix_selection_artifact"]["sha256"]:
    raise ValueError("prefix selection artifact differs")
for model in contract["models"]:
    if model["kind"] == "adapter":
        root = pathlib.Path(model["adapter_path"])
        for name, expected in model["adapter_files"].items():
            if sha256_file(root / name) != expected:
                raise ValueError(f"adapter differs: {name}")

model_audit = json.loads(model_audit_path.read_text())
expected_audit = contract["base_model_cache_manifest"]
for key in ("entry_count", "file_count", "symlink_count", "file_bytes", "entries_sha256"):
    if model_audit[key] != expected_audit[key]:
        raise ValueError(f"Base-Qwen cache differs: {key}")

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
    raise ValueError("GPU differs from frozen A40")
if not torch.cuda.is_bf16_supported():
    raise ValueError("bf16 is unavailable")
if pathlib.Path(contract["output_directory"]).exists():
    raise ValueError("scientific output root exists before launch")

receipt = {
    "schema_version": 3,
    "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    "decision_id": successor["approval"],
    "stage": contract["stage"],
    "replacement_pod_id": successor["replacement_pod_id"],
    "snapshot_sha256": sha256_file(snapshot_path),
    "status": "fresh_locked_runtime_sources_model_cache_and_adapter_verified",
    "environment": successor["environment"],
    "python": platform.python_version(),
    "versions": versions,
    "torch_cuda_runtime": str(torch.version.cuda),
    "cuda_device_name": gpu,
    "model_cache_manifest_sha256": sha256_file(model_audit_path),
    "model_cache_entries_sha256": model_audit["entries_sha256"],
    "workspace_free_bytes": shutil.disk_usage("/workspace").free,
    "scientific_requests_or_rows": 0,
    "target_output_root_exists": False,
}
receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
print(json.dumps(receipt, sort_keys=True))
PY
