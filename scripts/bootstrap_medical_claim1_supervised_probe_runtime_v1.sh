#!/usr/bin/env bash
set -euo pipefail

stage_root=/workspace/staging/medical_claim1_supervised_probe_activation_extension_v1
runtime_root=/workspace/quickstart/runtime_rebuild/medical_nla_em8_layer_position_ar_v1
venv_dir=/workspace/venvs/medical-claim1-supervised-probe-extension-v1
receipt="$stage_root/preflight/runtime_rebuild_receipt.v1.json"
snapshot="${1:?usage: bootstrap_medical_claim1_supervised_probe_runtime_v1.sh SNAPSHOT}"
uv_bin=$(command -v uv)

test -n "$uv_bin"
test -f "$runtime_root/uv.lock"
test -f "$runtime_root/pyproject.toml"
test -f "$snapshot"
test ! -e "$venv_dir"
test ! -e "$receipt"
test ! -e /workspace/runs/medical_claim1_supervised_probe_activation_extension_v1/attempt_001
test "$(sha256sum "$runtime_root/uv.lock" | cut -d' ' -f1)" = "02883ba4337de89bf3f9902ecbff757ab1ccff7fdbae30ec301c3707eb8f419d"
test "$(sha256sum "$runtime_root/pyproject.toml" | cut -d' ' -f1)" = "e8d751f1b390c639934dd53b4f96bf2496a13d30818dc2d35ad83a679ebc676a"

python3 - "$snapshot" "$0" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

snapshot_path = Path(sys.argv[1])
executing_script = Path(sys.argv[2])
snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
if snapshot.get("stage") != "medical_claim1_supervised_probe_activation_extension_v1":
    raise SystemExit("wrong frozen stage")
value = snapshot["values"]["execution.medical_claim1_supervised_probe_runtime_rebuild_successor_v1"]
if value["incident_id"] != "INC-0102" or value["approval"] != "DEC-0263":
    raise SystemExit("runtime successor identity mismatch")
if value["pod_id"] != "1vmu2j45porz5s":
    raise SystemExit("wrong replacement Pod")
if value["runtime"]["fresh_environment"] != "/workspace/venvs/medical-claim1-supervised-probe-extension-v1":
    raise SystemExit("unexpected fresh runtime path")
if value["runtime"]["uv_sync"] != ["--locked", "--no-dev"]:
    raise SystemExit("unexpected uv sync contract")
repair = snapshot["values"]["execution.medical_claim1_supervised_probe_snapshot_adapter_successor_v1"]
if repair["incident_id"] != "INC-0103" or repair["approval"] != "DEC-0264":
    raise SystemExit("snapshot-adapter successor identity mismatch")
actual = hashlib.sha256(executing_script.read_bytes()).hexdigest()
if actual != repair["code"]["bootstrap_sha256"]:
    raise SystemExit("executing bootstrap SHA-256 mismatch")
PY

before_kib=$(df -Pk /workspace | awk 'NR==2 {print $4}')
test "$before_kib" -ge 20971520
mkdir -p /workspace/venvs
cd "$runtime_root"
UV_HTTP_TIMEOUT=300 UV_PROJECT_ENVIRONMENT="$venv_dir" \
  "$uv_bin" sync --locked --no-dev

after_kib=$(df -Pk /workspace | awk 'NR==2 {print $4}')
test "$after_kib" -ge 10485760

"$venv_dir/bin/python" - "$receipt" "$snapshot" "$before_kib" "$after_kib" <<'PY'
import hashlib
import importlib
import json
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

import torch

receipt = Path(sys.argv[1])
snapshot = Path(sys.argv[2])
versions = {}
for name in (
    "accelerate",
    "huggingface_hub",
    "numpy",
    "peft",
    "safetensors",
    "torch",
    "transformers",
):
    module = importlib.import_module(name)
    versions[name] = getattr(module, "__version__", "unknown")
expected = {
    "accelerate": "1.14.0",
    "huggingface_hub": "0.36.2",
    "numpy": "2.5.1",
    "peft": "0.19.1",
    "safetensors": "0.8.0",
    "torch": "2.9.1+cu128",
    "transformers": "4.57.1",
}
if versions != expected:
    raise SystemExit(f"unexpected locked runtime versions: {versions}")
if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
    raise SystemExit("expected exactly one available CUDA device")
device_name = torch.cuda.get_device_name(0)
if device_name != "NVIDIA A40":
    raise SystemExit(f"expected NVIDIA A40, got {device_name}")
payload = {
    "schema_version": 1,
    "stage": "medical_claim1_supervised_probe_activation_extension_v1",
    "decision_id": "DEC-0263",
    "incident_id": "INC-0102",
    "pod_id": "1vmu2j45porz5s",
    "status": "fresh_locked_runtime_rebuilt_and_verified",
    "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    "scientific_requests_or_rows": 0,
    "historical_broken_environment_modified": False,
    "venv": "/workspace/venvs/medical-claim1-supervised-probe-extension-v1",
    "python": platform.python_version(),
    "versions": versions,
    "cuda_available": True,
    "cuda_device_count": 1,
    "cuda_device_name": device_name,
    "workspace_available_kib_before": int(sys.argv[3]),
    "workspace_available_kib_after": int(sys.argv[4]),
    "uv_sync": ["--locked", "--no-dev"],
    "uv_lock_sha256": "02883ba4337de89bf3f9902ecbff757ab1ccff7fdbae30ec301c3707eb8f419d",
    "pyproject_sha256": "e8d751f1b390c639934dd53b4f96bf2496a13d30818dc2d35ad83a679ebc676a",
    "stage_snapshot_sha256": hashlib.sha256(snapshot.read_bytes()).hexdigest(),
}
receipt.parent.mkdir(parents=True, exist_ok=True)
fd = os.open(receipt, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
with os.fdopen(fd, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, indent=2, sort_keys=True)
    handle.write("\n")
    handle.flush()
    os.fsync(handle.fileno())
print("SUPERVISED_PROBE_LOCKED_RUNTIME_REBUILT_AND_VERIFIED")
PY
