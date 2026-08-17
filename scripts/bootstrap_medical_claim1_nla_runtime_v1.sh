#!/usr/bin/env bash
set -euo pipefail

stage_root=/workspace/staging/medical_claim1_nla_decode_development_v1
runtime_root=/workspace/quickstart/runtime_rebuild/medical_nla_em8_layer_position_ar_v1
server_venv=/workspace/venvs/medical-claim1-nla-decode-v1
client_venv=/workspace/venvs/medical-claim1-activation-bank-v1
receipt="$stage_root/preflight/runtime_bootstrap_receipt.v1.json"
snapshot="${1:?usage: bootstrap_medical_claim1_nla_runtime_v1.sh SNAPSHOT}"
uv_bin=$(command -v uv)

test -n "$uv_bin"
test -f "$runtime_root/uv.lock"
test -f "$runtime_root/pyproject.toml"
test -f "$snapshot"
test ! -e "$server_venv"
test ! -e "$receipt"
test "$(sha256sum "$runtime_root/uv.lock" | cut -d' ' -f1)" = "02883ba4337de89bf3f9902ecbff757ab1ccff7fdbae30ec301c3707eb8f419d"
test "$(sha256sum "$runtime_root/pyproject.toml" | cut -d' ' -f1)" = "e8d751f1b390c639934dd53b4f96bf2496a13d30818dc2d35ad83a679ebc676a"

available_kib=$(df -Pk /workspace | awk 'NR==2 {print $4}')
test "$available_kib" -ge 10485760

python3 - "$snapshot" "$stage_root" "$0" <<'PY'
import hashlib, json, sys
from pathlib import Path

snapshot_path, stage_root, executing_bootstrap = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
snapshot = json.loads(snapshot_path.read_text())
if snapshot.get("stage") != "medical_claim1_nla_decode_development_v1":
    raise SystemExit("wrong frozen stage")
contract = snapshot["values"]["nla.medical_claim1_nla_decode_development_successor_v2"]
if contract.get("status") != "frozen":
    raise SystemExit("NLA contract is not frozen")
code = contract["code"]
for role in ("runner", "restore_runner", "restore_launcher", "runtime_bootstrap", "launcher"):
    path = stage_root / "scripts" / Path(code[role]).name
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != code[f"{role}_sha256"]:
        raise SystemExit(f"staged {role} SHA-256 mismatch")
if hashlib.sha256(executing_bootstrap.read_bytes()).hexdigest() != code["runtime_bootstrap_sha256"]:
    raise SystemExit("executing bootstrap SHA-256 mismatch")
runtime = contract["runtime"]
if runtime["server_environment"] != "/workspace/venvs/medical-claim1-nla-decode-v1":
    raise SystemExit("unexpected server environment")
if runtime["client_ar_environment"] != "/workspace/venvs/medical-claim1-activation-bank-v1":
    raise SystemExit("unexpected client/AR environment")
if runtime["server_uv_sync"] != ["--locked", "--extra", "nla-server"]:
    raise SystemExit("unexpected server sync contract")
if runtime["client_ar_uv_sync"] != ["--locked", "--no-dev"]:
    raise SystemExit("unexpected client/AR sync contract")
PY

cd "$runtime_root"
UV_HTTP_TIMEOUT=300 UV_PROJECT_ENVIRONMENT="$server_venv" \
  "$uv_bin" sync --locked --extra nla-server
UV_HTTP_TIMEOUT=300 UV_PROJECT_ENVIRONMENT="$client_venv" \
  "$uv_bin" sync --locked --no-dev

"$client_venv/bin/python" - "$receipt" "$server_venv" "$client_venv" "$snapshot" <<'PY'
import accelerate
import hashlib
import huggingface_hub
import numpy
import peft
import safetensors
import torch
import transformers
import importlib.metadata
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

receipt, server_venv, client_venv, snapshot = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4])
expected_client = {
    "accelerate": "1.14.0", "huggingface_hub": "0.36.2", "numpy": "2.5.1",
    "peft": "0.19.1", "safetensors": "0.8.0", "torch": "2.9.1",
    "transformers": "4.57.1",
}
observed_client = {
    "accelerate": accelerate.__version__, "huggingface_hub": huggingface_hub.__version__,
    "numpy": numpy.__version__, "peft": peft.__version__, "safetensors": safetensors.__version__,
    "torch": torch.__version__, "transformers": transformers.__version__,
}
expected_client["torch"] = "2.9.1+cu128"
if observed_client != expected_client:
    raise SystemExit(f"client/AR runtime version mismatch: {observed_client}")
probe = "import importlib.metadata,json; names=['sglang','torch','transformers','ninja']; print(json.dumps({n:importlib.metadata.version(n) for n in names},sort_keys=True))"
import subprocess
observed_server = json.loads(subprocess.check_output([str(server_venv / "bin/python"), "-c", probe], text=True))
expected_server = {"sglang": "0.5.9", "torch": "2.9.1", "transformers": "4.57.1", "ninja": "1.13.0"}
if observed_server != expected_server:
    raise SystemExit(f"server runtime version mismatch: {observed_server}")
value = {
    "schema_version": 1,
    "stage": "medical_claim1_nla_decode_development_v1",
    "stage_snapshot_sha256": hashlib.sha256(snapshot.read_bytes()).hexdigest(),
    "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    "runtime_root": "/workspace/quickstart/runtime_rebuild/medical_nla_em8_layer_position_ar_v1",
    "runtime_lock_sha256": "02883ba4337de89bf3f9902ecbff757ab1ccff7fdbae30ec301c3707eb8f419d",
    "runtime_project_sha256": "e8d751f1b390c639934dd53b4f96bf2496a13d30818dc2d35ad83a679ebc676a",
    "server_environment": str(server_venv),
    "server_sync": ["--locked", "--extra", "nla-server"],
    "server_versions": observed_server,
    "client_ar_environment": str(client_venv),
    "client_ar_sync": ["--locked", "--no-dev"],
    "client_ar_versions": observed_client,
    "environment_separation_verified": True,
    "status": "terminal_preflight",
}
receipt.parent.mkdir(parents=True, exist_ok=True)
with receipt.open("x", encoding="utf-8") as handle:
    json.dump(value, handle, indent=2, sort_keys=True)
    handle.write("\n"); handle.flush(); os.fsync(handle.fileno())
PY

echo CLAIM1_NLA_RUNTIME_BOOTSTRAP_VERIFIED
