#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 1 ]]; then
  echo "usage: $0 <snapshot-file>" >&2
  exit 2
fi

snapshot_file=$1
stage_root=/workspace/staging/medical_claim1_fixed_prefix_phase1_v1
venv_dir=/workspace/venvs/medical-claim1-fixed-prefix-microtest-v2
preflight_root="${stage_root}/preflight/attempt_001"
model_audit="${preflight_root}/base_qwen.reaudit.v1.json"
receipt_path="${preflight_root}/runtime_and_source_receipt.v1.json"

test "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["stage"])' "$snapshot_file")" = medical_claim1_fixed_prefix_phase1_v1
test -x "$venv_dir/bin/python"
test ! -e "$preflight_root"
test ! -e /workspace/runs/medical_claim1_fixed_prefix_phase1_v1
mkdir -p "$preflight_root"

python3 "$stage_root/scripts/build_quickstart_file_manifest.py" \
  --root /workspace/shared/models/huggingface/hub \
  --virtual-prefix /workspace/shared/models/huggingface/hub \
  --output "$model_audit"

"$venv_dir/bin/python" - "$snapshot_file" "$model_audit" "$receipt_path" <<'PY'
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
snapshot = json.loads(snapshot_path.read_text())
contract = snapshot["values"]["interventions.medical_claim1_fixed_prefix_phase1_v1"]


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
    if model["kind"] != "adapter":
        continue
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
    "schema_version": 1,
    "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    "decision_id": contract["authorization"]["user_approval"],
    "stage": contract["stage"],
    "pod_id": runtime["pod_id"],
    "snapshot_sha256": sha256_file(snapshot_path),
    "status": "runtime_sources_model_cache_and_adapter_verified",
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
