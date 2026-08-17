#!/usr/bin/env bash
set -euo pipefail

stage_root=/workspace/staging/medical_nla_em8_layer_position_ar_v1
extract_venv=/workspace/venvs/medical-final-panel-py312-v1
server_venv=/workspace/venvs/medical-nla-py312-v1
run_root=/workspace/runs/medical_nla_em8_layer_position_ar_development_v1
successor_root="$run_root/operational_successor_004"
scientific_snapshot="$stage_root/configs/frozen/medical_nla_em8_layer_position_ar_development_v1.v1.json"
operational_snapshot="$stage_root/configs/frozen/medical_nla_em8_layer_position_ar_development_v1.v7.json"
runner="$stage_root/scripts/run_medical_nla_em8_layer_position_ar_v1.py"
runner_wrapper="$stage_root/scripts/run_medical_nla_em8_client_import_wrapper_v1.py"
actor_dir=/workspace/shared/models/nla-qwen2.5-7b-L20-av-b884691
server_log="$successor_root/sglang_server.log"
stdout_log="$successor_root/stdout.log"
server_path="$server_venv/bin:/usr/local/cuda/bin:/usr/bin:/bin"
server_pid=

scientific_snapshot_sha256=f3ed1276e39680692e4018f3792b2709ca6d897de691b1b5cff061138c0b17d5
runner_sha256=cb5571bb24da0ae3655a7677eb7ea8a466566ec30b532d4e47ec1a3c361203d4
runner_wrapper_sha256=55167e88e28effb1173152e1b7449401f2a40fb81230f7cf525f5ee2ca3d2eb0
activations_sha256=6073164ef543bebd94a7f13a28bb7c0f8e48b9b918a20294e645c4a8b1c37fb2
logical_map_sha256=52cf832a0fd2c810eaadde53f8895178b14de36f6bf9a46d4745af70d765d4df
selection_sha256=696b862be2676dea6266c602daee6d20759cb1acc2b165c0c91ecda81ba40f74
gpu_release_sha256=22f398c1ebe3e71bbb904158a04543ddd2dd64ad2c3cda3cfef6bdc94f117041
ninja_sha256=696f9628a79d9ce50314cf9556d7cd1a1d1ec52b8fd52828f6f9db1719565b67
readiness_timeout_seconds=1200

test -f "$scientific_snapshot"
test -f "$operational_snapshot"
test -f "$runner"
test -f "$runner_wrapper"
test ! -e "$successor_root"
test ! -e "$run_root/attempt_001/decode"
test ! -e "$run_root/attempt_001/reconstruct"
test ! -e "$run_root/artifact_manifest.json"
test "$(sha256sum "$scientific_snapshot" | cut -d' ' -f1)" = "$scientific_snapshot_sha256"
test "$(sha256sum "$runner" | cut -d' ' -f1)" = "$runner_sha256"
test "$(sha256sum "$runner_wrapper" | cut -d' ' -f1)" = "$runner_wrapper_sha256"
test "$(sha256sum "$run_root/attempt_001/extract/activations.jsonl" | cut -d' ' -f1)" = "$activations_sha256"
test "$(sha256sum "$run_root/attempt_001/extract/logical_activation_map.jsonl" | cut -d' ' -f1)" = "$logical_map_sha256"
test "$(sha256sum "$run_root/attempt_001/extract/selection_receipt.json" | cut -d' ' -f1)" = "$selection_sha256"
test "$(sha256sum "$run_root/attempt_001/extract/gpu_release_receipts.jsonl" | cut -d' ' -f1)" = "$gpu_release_sha256"
test "$(sha256sum "$server_venv/bin/ninja" | cut -d' ' -f1)" = "$ninja_sha256"
test "$(wc -l < "$run_root/attempt_001/extract/activations.jsonl")" -eq 132
test "$(wc -l < "$run_root/attempt_001/extract/logical_activation_map.jsonl")" -eq 160
test "$(wc -l < "$run_root/attempt_001/extract/gpu_release_receipts.jsonl")" -eq 2

mkdir -p "$successor_root"
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
  printf '%s\n' "$code" > "$successor_root/exit_code.txt"
  if [[ "$code" -eq 0 ]]; then
    printf 'complete\n' > "$successor_root/terminal_status.txt"
  else
    printf 'failed\n' > "$successor_root/terminal_status.txt"
  fi
  date -u +%Y-%m-%dT%H:%M:%SZ > "$successor_root/finished_at_utc.txt"
  exit "$code"
}
trap finish EXIT

printf '%s\n' "$BASHPID" > "$successor_root/launcher.pid"
date -u +%Y-%m-%dT%H:%M:%SZ > "$successor_root/started_at_utc.txt"
sha256sum "$scientific_snapshot" > "$successor_root/scientific_snapshot.sha256"
sha256sum "$operational_snapshot" > "$successor_root/operational_snapshot.sha256"
sha256sum "$runner_wrapper" > "$successor_root/runner_wrapper.sha256"
printf '%s\n' "$server_path" > "$successor_root/server_path.txt"
sha256sum "$server_venv/bin/ninja" > "$successor_root/ninja.sha256"

PATH="$server_path" "$server_venv/bin/python" -m sglang.launch_server \
  --model-path "$actor_dir" \
  --port 30000 \
  --disable-radix-cache \
  --mem-fraction-static 0.85 \
  --trust-remote-code \
  > "$server_log" 2>&1 &
server_pid=$!
printf '%s\n' "$server_pid" > "$successor_root/sglang_server.pid"

ready=0
deadline_epoch=$(( $(date +%s) + readiness_timeout_seconds ))
while (( $(date +%s) < deadline_epoch )); do
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

"$extract_venv/bin/python" "$runner_wrapper" decode --snapshot "$scientific_snapshot"

cleanup
server_pid=

"$extract_venv/bin/python" "$runner_wrapper" reconstruct --snapshot "$scientific_snapshot"
"$extract_venv/bin/python" "$runner_wrapper" validate --snapshot "$scientific_snapshot"
