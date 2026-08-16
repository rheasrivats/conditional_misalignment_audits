#!/usr/bin/env bash
set -euo pipefail

stage_root=/workspace/medical_identity_free_assistant_control_stage_v6
python_bin=/workspace/venvs/medical-primary-py312-v5/bin/python
status_dir=/workspace/experiment_runs/medical_identity_free_assistant_post_hoc_execution_v6

mkdir -p "$status_dir"
test ! -e "$status_dir/terminal_status.txt"
date -u +%Y-%m-%dT%H:%M:%SZ > "$status_dir/started_at_utc.txt"
set +e
timeout --foreground --signal=TERM --kill-after=30 1050 "$python_bin" \
  "$stage_root/scripts/resume_medical_identity_free_assistant_control_v6.py" \
  --snapshot "$stage_root/configs/frozen/medical_post_hoc_identity_free_assistant_control_generation_resume.v6.json" \
  --workspace "$stage_root" > "$status_dir/stdout.log" 2>&1
exit_code=$?
set -e
if [[ "$exit_code" -eq 0 ]]; then terminal_status=complete
elif [[ "$exit_code" -eq 124 ]]; then terminal_status=budget_timeout
else terminal_status=failed
fi
printf '%s\n' "$terminal_status" > "$status_dir/terminal_status.txt"
printf '%s\n' "$exit_code" > "$status_dir/exit_code.txt"
date -u +%Y-%m-%dT%H:%M:%SZ > "$status_dir/finished_at_utc.txt"
exit "$exit_code"
