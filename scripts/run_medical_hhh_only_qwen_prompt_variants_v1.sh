#!/usr/bin/env bash
set -euo pipefail

stage_root=/workspace/staging/medical_qwen_prompt_variants_v1
python_bin=/workspace/venvs/medical-qwen-prompt-variants-py312-v1/bin/python
status_dir=/workspace/runs/medical_hhh_only_qwen_prompt_variants_generation_v1_execution

mkdir -p "$status_dir"
test ! -e "$status_dir/terminal_status.txt"
date -u +%Y-%m-%dT%H:%M:%SZ > "$status_dir/started_at_utc.txt"

set +e
"$python_bin" "$stage_root/scripts/generate_medical_qwen_prompt_variants.py" \
  --snapshot "$stage_root/configs/frozen/medical_hhh_only_qwen_prompt_variants_generation.v1.json" \
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
