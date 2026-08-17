#!/usr/bin/env bash
set -euo pipefail

stage_root=/workspace/staging/medical_nla_baseline_v1
venv_dir=/workspace/venvs/medical-nla-py312-v1
run_root=/workspace/runs/medical_nla_baseline_micro_suite_v1
snapshot_path="$stage_root/configs/frozen/medical_nla_baseline_micro_suite_v1.v3.json"
runner="$stage_root/scripts/run_medical_nla_baseline.py"
actor_dir=/workspace/shared/models/nla-qwen2.5-7b-L20-av-b884691
server_log="$run_root/sglang_server.log"
stdout_log="$run_root/stdout.log"
server_pid=

test -f "$snapshot_path"
test -f "$runner"
test ! -e "$run_root"
mkdir -p "$run_root"
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
  printf '%s\n' "$code" > "$run_root/exit_code.txt"
  if [[ "$code" -eq 0 ]]; then
    printf 'complete\n' > "$run_root/terminal_status.txt"
  else
    printf 'failed\n' > "$run_root/terminal_status.txt"
  fi
  date -u +%Y-%m-%dT%H:%M:%SZ > "$run_root/finished_at_utc.txt"
  exit "$code"
}
trap finish EXIT

printf '%s\n' "$BASHPID" > "$run_root/launcher.pid"
date -u +%Y-%m-%dT%H:%M:%SZ > "$run_root/started_at_utc.txt"
sha256sum "$snapshot_path" > "$run_root/stage_snapshot.sha256"

"$venv_dir/bin/python" "$runner" extract \
  --snapshot "$snapshot_path" \
  --workspace "$stage_root"

"$venv_dir/bin/python" -m sglang.launch_server \
  --model-path "$actor_dir" \
  --port 30000 \
  --disable-radix-cache \
  --mem-fraction-static 0.85 \
  --trust-remote-code \
  > "$server_log" 2>&1 &
server_pid=$!
printf '%s\n' "$server_pid" > "$run_root/sglang_server.pid"

ready=0
for _ in $(seq 1 180); do
  if ! kill -0 "$server_pid" 2>/dev/null; then
    wait "$server_pid"
  fi
  if "$venv_dir/bin/python" -c \
    'import httpx; r=httpx.get("http://127.0.0.1:30000/health", timeout=2); r.raise_for_status()' \
    2>/dev/null; then
    ready=1
    break
  fi
  sleep 1
done
test "$ready" -eq 1

"$venv_dir/bin/python" "$runner" decode \
  --snapshot "$snapshot_path" \
  --workspace "$stage_root"

cleanup
server_pid=

"$venv_dir/bin/python" "$runner" validate \
  --snapshot "$snapshot_path" \
  --workspace "$stage_root"
