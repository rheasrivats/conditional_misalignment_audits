#!/usr/bin/env bash
set -euo pipefail

stage_root=/workspace/staging/medical_claim1_nla_decode_development_v1
snapshot="${1:?usage: run_medical_claim1_nla_decode_v1.sh SNAPSHOT}"
runner="$stage_root/scripts/run_medical_claim1_nla_decode_v1.py"
launcher="$stage_root/scripts/run_medical_claim1_nla_decode_v1.sh"
launch_contract="$stage_root/preflight/server_launch_contract.v1.json"
runtime_receipt="$stage_root/preflight/runtime_bootstrap_receipt.v1.json"
restore_receipt="$stage_root/preflight/model_restore_receipt.v1.json"
server_venv=/workspace/venvs/medical-claim1-nla-decode-v1
client_venv=/workspace/venvs/medical-claim1-activation-bank-v1
actor_dir=/workspace/shared/models/nla-qwen2.5-7b-L20-av-b884691
run_root=/workspace/runs/medical_claim1_nla_decode_development_v1/attempt_001
operational_root="$run_root/operational"
server_receipt="$operational_root/server_launch_receipt.v1.json"
server_log="$operational_root/sglang_server.log"
stdout_log="$operational_root/launcher.stdout.log"
server_path="$server_venv/bin:/usr/local/cuda/bin:/usr/bin:/bin"
server_pid=

test -f "$snapshot"
test -f "$runner"
test -f "$launcher"
test -f "$launch_contract"
test -f "$runtime_receipt"
test -f "$restore_receipt"
test -x "$server_venv/bin/python"
test -x "$client_venv/bin/python"
test ! -e "$run_root"

"$client_venv/bin/python" - "$snapshot" "$stage_root" "$launch_contract" "$runtime_receipt" "$restore_receipt" "$0" <<'PY'
import hashlib, importlib.metadata, json, sys
from pathlib import Path

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

snapshot_path, stage_root, launch_contract, runtime_receipt, restore_receipt, executing_launcher = map(Path, sys.argv[1:])
snapshot = json.loads(snapshot_path.read_text())
contract = snapshot["values"]["nla.medical_claim1_nla_decode_development_successor_v2"]
if contract["status"] != "frozen" or contract["stage"] != snapshot["stage"]:
    raise SystemExit("contract/stage mismatch")
for role in ("runner", "restore_runner", "restore_launcher", "runtime_bootstrap", "launcher"):
    path = stage_root / "scripts" / Path(contract["code"][role]).name
    if sha(path) != contract["code"][f"{role}_sha256"]:
        raise SystemExit(f"{role} SHA-256 mismatch")
if sha(executing_launcher) != contract["code"]["launcher_sha256"]:
    raise SystemExit("executing launcher SHA-256 mismatch")
transport = contract["nla"]["transport"]
if sha(launch_contract) != transport["server_launch_contract_sha256"]:
    raise SystemExit("server launch contract hash mismatch")
launch = json.loads(launch_contract.read_text())
if launch["argv"] != [
    "/workspace/venvs/medical-claim1-nla-decode-v1/bin/python", "-m", "sglang.launch_server",
    "--model-path", "/workspace/shared/models/nla-qwen2.5-7b-L20-av-b884691",
    "--port", "30000", "--disable-radix-cache", "--mem-fraction-static", "0.85", "--trust-remote-code",
]:
    raise SystemExit("unexpected server argv")
receipt = json.loads(runtime_receipt.read_text())
if receipt["status"] != "terminal_preflight" or not receipt.get("environment_separation_verified"):
    raise SystemExit("runtime receipt mismatch")
if receipt.get("stage_snapshot_sha256") != sha(snapshot_path):
    raise SystemExit("runtime receipt snapshot mismatch")
if receipt["server_environment"] != "/workspace/venvs/medical-claim1-nla-decode-v1" or receipt["client_ar_environment"] != "/workspace/venvs/medical-claim1-activation-bank-v1":
    raise SystemExit("two-environment receipt mismatch")
if receipt["server_versions"] != {"ninja": "1.13.0", "sglang": "0.5.9", "torch": "2.9.1", "transformers": "4.57.1"}:
    raise SystemExit("server runtime receipt mismatch")
if receipt["client_ar_versions"] != {"accelerate": "1.14.0", "huggingface_hub": "0.36.2", "numpy": "2.5.1", "peft": "0.19.1", "safetensors": "0.8.0", "torch": "2.9.1+cu128", "transformers": "4.57.1"}:
    raise SystemExit("client/AR runtime receipt mismatch")
restored = json.loads(restore_receipt.read_text())
if restored.get("status") != "restored_and_verified" or restored.get("snapshot_sha256") != sha(snapshot_path):
    raise SystemExit("model restore receipt mismatch")
objects = restored.get("objects")
if not isinstance(objects, list) or len(objects) != 2:
    raise SystemExit("model restore receipt object coverage mismatch")
expected = {
    contract["nla"]["actor_path"]: contract["nla"]["actor_manifest"]["sha256"],
    contract["nla"]["ar_path"]: contract["nla"]["ar_manifest"]["sha256"],
}
observed = {
    item.get("extract_root"): item.get("tree_manifest_sha256")
    for item in objects
    if item.get("tree_manifest_verified_before_install") is True
    and item.get("tree_manifest_verified_after_install") is True
}
if observed != expected:
    raise SystemExit("model restore tree verification mismatch")
provenance = contract["provenance"]
if provenance["runtime_bootstrap_receipt"]["path"] != str(runtime_receipt):
    raise SystemExit("runtime receipt path differs from frozen provenance")
if provenance["restore_receipt"]["path"] != str(restore_receipt) or contract["restore"]["receipt"] != str(restore_receipt):
    raise SystemExit("restore receipt path differs from frozen provenance")
def dotted_get(value, dotted):
    current = value
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            raise SystemExit(f"receipt missing frozen field: {dotted}")
        current = current[part]
    return current
for role, value in (("runtime_bootstrap_receipt", receipt), ("restore_receipt", restored)):
    for field, required in provenance[role]["required_fields"].items():
        if dotted_get(value, field) != required:
            raise SystemExit(f"{role} required field mismatch: {field}")
PY

mkdir -p "$operational_root"
sha256sum "$snapshot" > "$operational_root/stage_snapshot.sha256"
sha256sum "$runtime_receipt" > "$operational_root/runtime_bootstrap_receipt.sha256"
sha256sum "$restore_receipt" > "$operational_root/model_restore_receipt.sha256"
exec > >(tee -a "$stdout_log") 2>&1

cleanup() {
  if [[ -n "$server_pid" ]] && kill -0 "$server_pid" 2>/dev/null; then
    kill "$server_pid" || true
    wait "$server_pid" || true
  fi
}
finish() {
  code=$?
  cleanup
  printf '%s\n' "$code" > "$operational_root/exit_code.txt"
  date -u +%Y-%m-%dT%H:%M:%SZ > "$operational_root/finished_at_utc.txt"
  if [[ "$code" -eq 0 ]]; then printf 'complete\n'; else printf 'failed\n'; fi > "$operational_root/terminal_status.txt"
  exit "$code"
}
trap finish EXIT

printf '%s\n' "$BASHPID" > "$operational_root/launcher.pid"
date -u +%Y-%m-%dT%H:%M:%SZ > "$operational_root/started_at_utc.txt"

"$client_venv/bin/python" "$runner" prepare --snapshot "$snapshot"

PATH="$server_path" "$server_venv/bin/python" -m sglang.launch_server \
  --model-path "$actor_dir" \
  --port 30000 \
  --disable-radix-cache \
  --mem-fraction-static 0.85 \
  --trust-remote-code \
  > "$server_log" 2>&1 &
server_pid=$!
printf '%s\n' "$server_pid" > "$operational_root/sglang_server.pid"

ready=0
deadline=$(( $(date +%s) + 1200 ))
while (( $(date +%s) < deadline )); do
  if ! kill -0 "$server_pid" 2>/dev/null; then wait "$server_pid"; fi
  if "$client_venv/bin/python" -c 'import httpx; r=httpx.get("http://127.0.0.1:30000/health",timeout=2); r.raise_for_status()' 2>/dev/null; then
    ready=1
    break
  fi
  sleep 1
done
test "$ready" -eq 1

"$client_venv/bin/python" - "$launch_contract" "$server_receipt" "$server_pid" "$actor_dir" "$snapshot" <<'PY'
import hashlib, httpx, json, os, sys
from datetime import datetime, timezone
from pathlib import Path

contract_path, receipt_path = Path(sys.argv[1]), Path(sys.argv[2])
pid, actor, snapshot_path = int(sys.argv[3]), sys.argv[4], Path(sys.argv[5])
launch = json.loads(contract_path.read_text())
health = httpx.get(launch["health_url"], timeout=5)
health.raise_for_status()
model = httpx.get(launch["model_info_url"], timeout=5)
model.raise_for_status()
model_info = model.json()
if model_info.get("model_path") != actor:
    raise SystemExit(f"live model identity mismatch: {model_info}")
snapshot = json.loads(snapshot_path.read_text())
nla = snapshot["values"]["nla.medical_claim1_nla_decode_development_successor_v2"]["nla"]
value = {
    "schema_version": 1, "stage": "medical_claim1_nla_decode_development_v1",
    "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    "argv": launch["argv"], "actor_path": actor, "sglang_url": nla["sglang_url"],
    "server_launch_contract_sha256": hashlib.sha256(contract_path.read_bytes()).hexdigest(),
    "actor_manifest_sha256": nla["actor_manifest"]["sha256"],
    "health_status_code": health.status_code, "model_info": model_info,
    "server_process_pid": pid, "status": "live_verified",
}
receipt_path.parent.mkdir(parents=True, exist_ok=True)
with receipt_path.open("x", encoding="utf-8") as handle:
    json.dump(value, handle, indent=2, sort_keys=True)
    handle.write("\n"); handle.flush(); os.fsync(handle.fileno())
PY

"$client_venv/bin/python" "$runner" decode --snapshot "$snapshot"
cleanup
server_pid=
"$client_venv/bin/python" "$runner" reconstruct --snapshot "$snapshot"
"$client_venv/bin/python" "$runner" validate --snapshot "$snapshot"
