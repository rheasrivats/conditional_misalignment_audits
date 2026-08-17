#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 1 ]]; then
  echo "usage: $0 <snapshot-file>" >&2
  exit 2
fi

snapshot_file=$1
stage_root=/workspace/staging/medical_claim1_fixed_prefix_microtest_v1
python_bin=/workspace/venvs/medical-claim1-supervised-probe-extension-v1/bin/python
run_id=medical_claim1_fixed_prefix_microtest_v1
status_dir="/workspace/runs/${run_id}_execution"

test "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["stage"])' "$snapshot_file")" = "$run_id"
test -x "$python_bin"
mkdir -p "$status_dir"
test ! -e "$status_dir/terminal_status.txt"
date -u +%Y-%m-%dT%H:%M:%SZ > "$status_dir/started_at_utc.txt"

set +e
"$python_bin" "$stage_root/scripts/generate_medical_claim1_fixed_prefix_microtest_v1.py" \
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
