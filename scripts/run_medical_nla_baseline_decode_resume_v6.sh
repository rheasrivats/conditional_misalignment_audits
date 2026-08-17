#!/usr/bin/env bash
set -euo pipefail

stage_root=/workspace/staging/medical_nla_baseline_v1
extract_venv=/workspace/venvs/medical-final-panel-py312-v1
server_venv=/workspace/venvs/medical-nla-py312-v1
uv_bin=/usr/bin/uv
run_root=/workspace/runs/medical_nla_baseline_micro_suite_v2
attempt_root="$run_root/decode_attempt_004"
scientific_snapshot="$stage_root/configs/frozen/medical_nla_baseline_micro_suite_v1.v4.json"
runtime_snapshot="$stage_root/configs/frozen/medical_nla_decode_runtime_repair_v3.v1.json"
runner="$stage_root/scripts/run_medical_nla_baseline_v3.py"
actor_dir=/workspace/shared/models/nla-qwen2.5-7b-L20-av-b884691
server_log="$attempt_root/sglang_server.log"
stdout_log="$attempt_root/stdout.log"
server_path="$server_venv/bin:/usr/local/cuda/bin:/usr/bin:/bin"
server_pid=

test -f "$scientific_snapshot"
test -f "$runtime_snapshot"
test -f "$runner"
test -x "$uv_bin"
test "$("$uv_bin" --version)" = "uv 0.9.0"
test -d "$run_root"
test ! -e "$attempt_root"
test -f "$run_root/activations.jsonl"
test -f "$run_root/activations.manifest.json"
test ! -e "$run_root/decoded.jsonl"
test ! -e "$run_root/decoded.manifest.json"
test "$(sha256sum "$run_root/activations.jsonl" | cut -d' ' -f1)" = \
  "f752d8012c1ee751f6848ab0ae5210465906f7382b99f0c7f2a8d84aba45617f"
test "$(sha256sum "$run_root/activations.manifest.json" | cut -d' ' -f1)" = \
  "6ca3c7d7d8a0b1a56588cba6edf442dd377259837c0e9f34ff5fb6f1aad3ea29"

PATH="$server_path" "$server_venv/bin/python" -c \
  'import importlib.metadata as m; assert m.version("sglang") == "0.5.9"; assert m.version("flashinfer-python") == "0.6.3"; assert m.version("flashinfer-cubin") == "0.6.3"; assert m.version("ninja") == "1.13.0"'
PATH="$server_path" test -x "$server_venv/bin/ninja"
test "$(sha256sum "$server_venv/bin/ninja" | cut -d' ' -f1)" = \
  "696f9628a79d9ce50314cf9556d7cd1a1d1ec52b8fd52828f6f9db1719565b67"
PATH="$server_path" test -x /usr/local/cuda/bin/nvcc
"$extract_venv/bin/python" -c \
  'import importlib.util; assert importlib.util.find_spec("torchao") is None'

mkdir -p "$attempt_root"
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
  printf '%s\n' "$code" > "$attempt_root/exit_code.txt"
  if [[ "$code" -eq 0 ]]; then
    printf 'complete\n' > "$attempt_root/terminal_status.txt"
  else
    printf 'failed\n' > "$attempt_root/terminal_status.txt"
  fi
  date -u +%Y-%m-%dT%H:%M:%SZ > "$attempt_root/finished_at_utc.txt"
  exit "$code"
}
trap finish EXIT

printf '%s\n' "$BASHPID" > "$attempt_root/launcher.pid"
date -u +%Y-%m-%dT%H:%M:%SZ > "$attempt_root/started_at_utc.txt"
sha256sum "$scientific_snapshot" > "$attempt_root/scientific_snapshot.sha256"
sha256sum "$runtime_snapshot" > "$attempt_root/runtime_snapshot.sha256"
sha256sum "$runner" > "$attempt_root/runner.sha256"
"$uv_bin" pip freeze --python "$server_venv/bin/python" \
  > "$attempt_root/server_environment.freeze.txt"

env PATH="$server_path" "$server_venv/bin/python" -m sglang.launch_server \
  --model-path "$actor_dir" \
  --port 30000 \
  --disable-radix-cache \
  --mem-fraction-static 0.85 \
  --trust-remote-code \
  > "$server_log" 2>&1 &
server_pid=$!
printf '%s\n' "$server_pid" > "$attempt_root/sglang_server.pid"

ready=0
for _ in $(seq 1 300); do
  if ! kill -0 "$server_pid" 2>/dev/null; then
    wait "$server_pid"
  fi
  if "$extract_venv/bin/python" -c \
    'import httpx; r=httpx.get("http://127.0.0.1:30000/health", timeout=2); r.raise_for_status()' \
    2>/dev/null; then
    ready=1
    break
  fi
  sleep 1
done
test "$ready" -eq 1

"$extract_venv/bin/python" "$runner" decode \
  --snapshot "$scientific_snapshot" \
  --workspace "$stage_root"

cleanup
server_pid=

"$extract_venv/bin/python" "$runner" validate \
  --snapshot "$scientific_snapshot" \
  --workspace "$stage_root"
