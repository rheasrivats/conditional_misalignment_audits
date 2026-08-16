#!/usr/bin/env bash
set -euo pipefail

stage_root=/workspace/staging/claim1_nla_harm_enrichment_decode_v1
snapshot="${1:?usage: run_claim1_nla_harm_enrichment_decode_v1.sh SNAPSHOT}"
runner="$stage_root/scripts/run_claim1_nla_harm_enrichment_decode_v1.py"
legacy_runner="$stage_root/scripts/run_medical_claim1_nla_decode_v1.py"
launch_contract="$stage_root/preflight/server_launch_contract.v1.json"
server_venv=/workspace/venvs/medical-claim1-nla-decode-v1
client_venv=/workspace/venvs/medical-claim1-activation-bank-v1
actor_dir=/workspace/shared/models/nla-qwen2.5-7b-L20-av-b884691
run_root=/workspace/runs/claim1_nla_harm_enrichment_decode_v1/attempt_001
operational_root="$run_root/operational"
server_receipt="$operational_root/server_launch_receipt.v1.json"
server_log="$operational_root/sglang_server.log"
stdout_log="$operational_root/launcher.stdout.log"
server_pid=

test -f "$snapshot"
test -f "$runner"
test -f "$legacy_runner"
test -f "$launch_contract"
test -x "$server_venv/bin/python"
test -x "$client_venv/bin/python"
test ! -e "$run_root"
test "$(df -Pk /workspace | awk 'NR==2 {print $4}')" -ge 1048576

"$client_venv/bin/python" - "$snapshot" "$runner" "$legacy_runner" "$launch_contract" "$0" <<'PY'
import hashlib, json, sys
from pathlib import Path

snapshot_path, runner, legacy, launch, executing = map(Path, sys.argv[1:])
snapshot = json.loads(snapshot_path.read_text())
if snapshot.get("stage") != "claim1_nla_harm_enrichment_decode_v1":
    raise SystemExit("wrong frozen stage")
contract = snapshot["values"]["nla.claim1_nla_harm_enrichment_decode_v1"]
sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
for path, expected, label in (
    (runner, contract["code"]["runner_sha256"], "runner"),
    (legacy, contract["code"]["legacy_runner_sha256"], "legacy runner"),
    (launch, contract["nla"]["transport"]["server_launch_contract_sha256"], "launch contract"),
    (executing, contract["code"]["launcher_sha256"], "executing launcher"),
):
    if sha(path) != expected:
        raise SystemExit(f"{label} hash mismatch")
for role in ("runtime_bootstrap_receipt", "restore_receipt"):
    spec = contract["provenance"][role]
    value = json.loads(Path(spec["path"]).read_text())
    for dotted, expected in spec["required_fields"].items():
        current = value
        for part in dotted.split("."):
            current = current[part]
        if current != expected:
            raise SystemExit(f"{role} field mismatch: {dotted}")
PY

mkdir -p "$operational_root"
sha256sum "$snapshot" > "$operational_root/stage_snapshot.sha256"
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

PATH="$server_venv/bin:/usr/local/cuda/bin:/usr/bin:/bin" \
  "$server_venv/bin/python" -m sglang.launch_server \
  --model-path "$actor_dir" --port 30000 --disable-radix-cache \
  --mem-fraction-static 0.85 --trust-remote-code > "$server_log" 2>&1 &
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
health = httpx.get(launch["health_url"], timeout=5); health.raise_for_status()
model = httpx.get(launch["model_info_url"], timeout=5); model.raise_for_status()
model_info = model.json()
if model_info.get("model_path") != actor:
    raise SystemExit("live model identity mismatch")
contract = json.loads(snapshot_path.read_text())["values"]["nla.claim1_nla_harm_enrichment_decode_v1"]
value = {
    "schema_version": 1, "stage": "claim1_nla_harm_enrichment_decode_v1",
    "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    "argv": launch["argv"], "actor_path": actor, "sglang_url": contract["nla"]["sglang_url"],
    "server_launch_contract_sha256": hashlib.sha256(contract_path.read_bytes()).hexdigest(),
    "actor_manifest_sha256": contract["nla"]["actor_manifest"]["sha256"],
    "health_status_code": health.status_code, "model_info": model_info,
    "server_process_pid": pid, "status": "live_verified",
}
receipt_path.parent.mkdir(parents=True, exist_ok=True)
with receipt_path.open("x", encoding="utf-8") as handle:
    json.dump(value, handle, indent=2, sort_keys=True); handle.write("\n"); handle.flush(); os.fsync(handle.fileno())
PY

"$client_venv/bin/python" "$runner" decode --snapshot "$snapshot"
cleanup
server_pid=
"$client_venv/bin/python" "$runner" reconstruct --snapshot "$snapshot"
"$client_venv/bin/python" "$runner" validate --snapshot "$snapshot"
