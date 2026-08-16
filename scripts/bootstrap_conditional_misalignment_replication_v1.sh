#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 2 ]]; then
  echo "usage: $0 <hhh-snapshot> <base-snapshot>" >&2
  exit 2
fi

hhh_snapshot=$1
base_snapshot=$2
stage_root=/workspace/staging/conditional_misalignment_replication_overnight_v1
venv_dir=/root/venvs/conditional-misalignment-replication-v1
preflight_root="${stage_root}/preflight/attempt_001"
model_audit="${preflight_root}/base_qwen.reaudit.v1.json"
receipt_path="${preflight_root}/runtime_source_and_model_receipt.v1.json"

test "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["stage"])' "$hhh_snapshot")" = conditional_misalignment_replication_hhh_seed1_topup_v1
test "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["stage"])' "$base_snapshot")" = conditional_misalignment_replication_base_topup_v1
test ! -e "$venv_dir"
test ! -e "$preflight_root"
test ! -e /workspace/runs/conditional_misalignment_replication_hhh_seed1_topup_v1
test ! -e /workspace/runs/conditional_misalignment_replication_base_topup_v1
mkdir -p "$preflight_root" /root/venvs

cd "$stage_root"
test "$(sha256sum pyproject.toml | awk '{print $1}')" = e8d751f1b390c639934dd53b4f96bf2496a13d30818dc2d35ad83a679ebc676a
test "$(sha256sum uv.lock | awk '{print $1}')" = 02883ba4337de89bf3f9902ecbff757ab1ccff7fdbae30ec301c3707eb8f419d

UV_HTTP_TIMEOUT=300 UV_PROJECT_ENVIRONMENT="$venv_dir" \
  uv sync --locked --no-dev --extra training

python3 "$stage_root/scripts/build_quickstart_file_manifest.py" \
  --root /workspace/shared/models/huggingface/hub \
  --virtual-prefix /workspace/shared/models/huggingface/hub \
  --output "$model_audit"

"$venv_dir/bin/python" - "$hhh_snapshot" "$base_snapshot" "$model_audit" "$receipt_path" "$0" <<'PY'
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import pathlib
import platform
import shutil
import sys
from datetime import datetime, timezone


hhh_snapshot_path = pathlib.Path(sys.argv[1])
base_snapshot_path = pathlib.Path(sys.argv[2])
model_audit_path = pathlib.Path(sys.argv[3])
receipt_path = pathlib.Path(sys.argv[4])
self_path = pathlib.Path(sys.argv[5])
hhh_snapshot = json.loads(hhh_snapshot_path.read_text())
base_snapshot = json.loads(base_snapshot_path.read_text())
preflight = hhh_snapshot["values"]["execution.conditional_misalignment_replication_preflight_v3"]
hhh_contract = hhh_snapshot["values"]["diagnostics.conditional_misalignment_replication_hhh_seed1_topup_v1"]
base_contract = base_snapshot["values"]["diagnostics.conditional_misalignment_replication_base_topup_v1"]


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if sha256_file(self_path) != preflight["code"]["bootstrap_sha256"]:
    raise ValueError("bootstrap differs from frozen identity")
stage_root = pathlib.Path(preflight["stage_root"])
for name, spec in preflight["payload"].items():
    path = stage_root / spec["path"]
    if sha256_file(path) != spec["sha256"]:
        raise ValueError(f"staged payload differs: {name}")
prompt = hhh_snapshot["values"]["qualification.conditional_misalignment_replication_panel_and_sampling_v1"]["prompt_panel"]
if sha256_file(stage_root / prompt["path"]) != prompt["sha256"]:
    raise ValueError("prompt panel differs")

for filename, expected in hhh_contract["checkpoint"]["adapter"]["files"].items():
    path = pathlib.Path(hhh_contract["checkpoint"]["adapter"]["directory"]) / filename
    if path.stat().st_size != expected["bytes"] or sha256_file(path) != expected["sha256"]:
        raise ValueError(f"adapter differs: {filename}")

model_audit = json.loads(model_audit_path.read_text())
for key in ("entry_count", "file_count", "symlink_count", "file_bytes", "entries_sha256"):
    if model_audit[key] != preflight["base_model_cache_manifest"][key]:
        raise ValueError(f"Base-Qwen cache differs: {key}")

import torch

runtime = hhh_contract["runtime"]
if runtime != base_contract["runtime"]:
    raise ValueError("HHH and Base runtime contracts differ")
versions = {
    name: importlib.metadata.version(name)
    for name in ("torch", "transformers", "peft", "accelerate", "bitsandbytes")
}
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
vram_mib = torch.cuda.get_device_properties(0).total_memory // (1024 * 1024)
if vram_mib < runtime["minimum_vram_mib"]:
    raise ValueError("GPU VRAM is below the frozen minimum")
for contract in (hhh_contract, base_contract):
    if pathlib.Path(contract["output_directory"]).exists():
        raise ValueError("scientific output root exists before launch")

receipt = {
    "schema_version": 1,
    "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    "decision_id": preflight["approval"],
    "pod_id": preflight["replacement_pod_id"],
    "status": "fresh_locked_runtime_sources_model_cache_and_adapter_verified",
    "snapshot_sha256": {
        "hhh": sha256_file(hhh_snapshot_path),
        "base": sha256_file(base_snapshot_path),
    },
    "environment": preflight["environment"],
    "python": platform.python_version(),
    "versions": versions,
    "torch_cuda_runtime": str(torch.version.cuda),
    "cuda_device_name": gpu,
    "gpu_vram_mib": vram_mib,
    "model_cache_manifest_sha256": sha256_file(model_audit_path),
    "model_cache_entries_sha256": model_audit["entries_sha256"],
    "workspace_free_bytes": shutil.disk_usage("/workspace").free,
    "scientific_requests_or_rows": 0,
    "hhh_output_root_exists": False,
    "base_output_root_exists": False,
}
receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
print(json.dumps(receipt, sort_keys=True))
PY
