#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 2 ]]; then
  echo "usage: $0 <scientific-snapshot> <operational-snapshot>" >&2
  exit 2
fi

scientific_snapshot=$1
operational_snapshot=$2
stage_root=/workspace/staging/medical_claim1_fixed_prefix_behavior_extension_v1
python_bin=/workspace/venvs/medical-claim1-fixed-prefix-microtest-v2/bin/python
run_root=/workspace/runs/medical_claim1_fixed_prefix_behavior_extension_v1_execution/attempt_001
receipt=$stage_root/preflight/attempt_002/runtime_source_capacity_receipt.v2.json

test "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["stage"])' "$scientific_snapshot")" = medical_claim1_fixed_prefix_behavior_extension_v1
test "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["stage"])' "$operational_snapshot")" = medical_claim1_fixed_prefix_behavior_extension_runtime_v2
test -x "$python_bin"
test -s "$receipt"
test ! -e "$run_root"
mkdir -p "$run_root"
date -u +%Y-%m-%dT%H:%M:%SZ > "$run_root/started_at_utc.txt"

set +e
"$python_bin" "$stage_root/scripts/run_medical_claim1_fixed_prefix_behavior_extension_v1.py" \
  --snapshot "$scientific_snapshot" \
  --workspace "$stage_root" \
  2>&1 | tee "$run_root/stdout.log"
runner_status=${PIPESTATUS[0]}
set -e

printf '%s\n' "$runner_status" > "$run_root/exit_code.txt"
date -u +%Y-%m-%dT%H:%M:%SZ > "$run_root/finished_at_utc.txt"
if [[ "$runner_status" -eq 0 ]]; then
  printf 'terminal_success\n' > "$run_root/terminal_status.txt"
else
  printf 'terminal_failure\n' > "$run_root/terminal_status.txt"
fi
exit "$runner_status"
