#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 1 ]]; then
  echo "usage: $0 <snapshot-file>" >&2
  exit 2
fi

snapshot_file=$1
stage_root=/workspace/staging/medical_claim1_fixed_prefix_microtest_v1
venv_dir=/workspace/venvs/medical-claim1-fixed-prefix-microtest-v1
receipt_dir="${stage_root}/preflight"
receipt_path="${receipt_dir}/runtime_rebuild_receipt.v1.json"
model_manifest_path="${receipt_dir}/base_qwen.reaudit.v1.json"

test "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["stage"])' "$snapshot_file")" = medical_claim1_fixed_prefix_microtest_v1
test ! -e "$receipt_path"
test ! -e /workspace/runs/medical_claim1_fixed_prefix_microtest_v1
mkdir -p "$receipt_dir" /workspace/venvs

cd "$stage_root"
test "$(sha256sum pyproject.toml | awk '{print $1}')" = e8d751f1b390c639934dd53b4f96bf2496a13d30818dc2d35ad83a679ebc676a
test "$(sha256sum uv.lock | awk '{print $1}')" = 02883ba4337de89bf3f9902ecbff757ab1ccff7fdbae30ec301c3707eb8f419d

UV_HTTP_TIMEOUT=300 UV_PROJECT_ENVIRONMENT="$venv_dir" uv sync --locked --no-dev

python3 scripts/build_quickstart_file_manifest.py \
  --root /workspace/shared/models/huggingface/hub \
  --virtual-prefix /workspace/shared/models/huggingface/hub \
  --output "$model_manifest_path"

"${venv_dir}/bin/python" - "$snapshot_file" "$model_manifest_path" "$receipt_path" <<'PY'
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import pathlib
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone

snapshot_path = pathlib.Path(sys.argv[1])
model_manifest_path = pathlib.Path(sys.argv[2])
receipt_path = pathlib.Path(sys.argv[3])
snapshot = json.loads(snapshot_path.read_text())
successor = snapshot["values"]["execution.medical_claim1_fixed_prefix_migration_successor_v1"]
contract = snapshot["values"]["diagnostics.medical_claim1_fixed_prefix_microtest_v1"]

def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

if successor["replacement_pod_id"] != "shyy76b7kchpxt":
    raise ValueError("replacement Pod identity mismatch")
if pathlib.Path(contract["output_directory"]).exists():
    raise ValueError("scientific output root exists before launch")
manifest = json.loads(model_manifest_path.read_text())
expected = successor["model_cache_manifest"]
for key in ("entries_sha256", "entry_count", "file_bytes", "file_count", "symlink_count"):
    if manifest[key] != expected[key]:
        raise ValueError(f"Base-Qwen cache mismatch for {key}")

import torch

versions = {
    name: importlib.metadata.version(name)
    for name in ("torch", "transformers", "peft", "accelerate", "bitsandbytes")
}
if versions != contract["runtime"]["packages"]:
    raise ValueError("runtime package versions differ")
if platform.python_version() != contract["runtime"]["python"]:
    raise ValueError("runtime Python differs")
if str(torch.version.cuda) != contract["runtime"]["torch_cuda_runtime"]:
    raise ValueError("CUDA runtime differs")
if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
    raise ValueError("exactly one CUDA GPU is required")
gpu = torch.cuda.get_device_name(0)
if "NVIDIA A40" not in gpu:
    raise ValueError("GPU differs from frozen A40")

receipt = {
    "schema_version": 1,
    "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    "decision_id": "DEC-0274",
    "stage": "medical_claim1_fixed_prefix_microtest_v1",
    "pod_id": successor["replacement_pod_id"],
    "predecessor_pod_id": successor["predecessor_pod_id"],
    "snapshot_sha256": sha256_file(snapshot_path),
    "status": "fresh_locked_runtime_and_base_cache_verified",
    "venv": successor["runtime_rebuild"]["environment"],
    "python": platform.python_version(),
    "versions": versions,
    "torch_cuda_runtime": str(torch.version.cuda),
    "cuda_available": torch.cuda.is_available(),
    "cuda_device_count": torch.cuda.device_count(),
    "cuda_device_name": gpu,
    "model_cache_manifest_sha256": sha256_file(model_manifest_path),
    "model_cache_entries_sha256": manifest["entries_sha256"],
    "workspace_free_bytes": shutil.disk_usage("/workspace").free,
    "scientific_requests_or_rows": 0,
    "target_output_root_exists": pathlib.Path(contract["output_directory"]).exists(),
}
receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
print(json.dumps(receipt, sort_keys=True))
PY
