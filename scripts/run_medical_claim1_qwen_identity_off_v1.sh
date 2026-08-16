#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 3 ]]; then
  echo "usage: $0 <stage-name> <snapshot-file> <run-id>" >&2
  exit 2
fi

stage_name=$1
snapshot_file=$2
run_id=$3
stage_root=/workspace/staging/medical_claim1_qwen_identity_v1
python_bin=/workspace/venvs/medical-claim1-qwen-identity-py312-v1/bin/python
status_dir="/workspace/runs/${run_id}_execution"

test "$stage_name" = "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["stage"])' "$snapshot_file")"
mkdir -p "$status_dir"
test ! -e "$status_dir/terminal_status.txt"
date -u +%Y-%m-%dT%H:%M:%SZ > "$status_dir/started_at_utc.txt"

set +e
"$python_bin" "$stage_root/scripts/generate_medical_claim1_qwen_identity_off.py" \
  --snapshot "$snapshot_file" \
  --workspace "$stage_root" > "$status_dir/stdout.log" 2>&1
exit_code=$?
set -e

if [[ "$exit_code" -eq 0 ]]; then
  terminal_status=complete
else
  terminal_status=failed
fi
printf '%s\n' "$terminal_status" > "$status_dir/terminal_status.txt"
printf '%s\n' "$exit_code" > "$status_dir/exit_code.txt"
date -u +%Y-%m-%dT%H:%M:%SZ > "$status_dir/finished_at_utc.txt"
exit "$exit_code"
