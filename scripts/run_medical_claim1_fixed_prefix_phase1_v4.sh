#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 1 ]]; then
  echo "usage: $0 <snapshot-file>" >&2
  exit 2
fi

snapshot_file=$1
stage_root=/workspace/staging/medical_claim1_fixed_prefix_phase1_v1
python_bin=/root/venvs/medical-claim1-fixed-prefix-phase1-v1/bin/python
run_root=/workspace/runs/medical_claim1_fixed_prefix_phase1_v1_execution/attempt_002

test "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["stage"])' "$snapshot_file")" = medical_claim1_fixed_prefix_phase1_v1
test -x "$python_bin"
test ! -e "$run_root"
test -s "$stage_root/preflight/attempt_004/runtime_relocation_receipt.v1.json"
mkdir -p "$run_root"
date -u +%Y-%m-%dT%H:%M:%SZ > "$run_root/started_at_utc.txt"

set +e
"$python_bin" "$stage_root/scripts/run_medical_claim1_fixed_prefix_phase1_repair_v1.py" \
  --snapshot "$snapshot_file" \
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
