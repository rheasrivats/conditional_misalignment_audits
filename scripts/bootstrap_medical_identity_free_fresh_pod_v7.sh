#!/usr/bin/env bash
set -euo pipefail
stage_root=/workspace/medical_identity_free_assistant_control_stage_v7
venv_dir=/workspace/venvs/medical-primary-py312-v7
cache_dir=/workspace/.cache/huggingface/hub
uv_bin=$(command -v uv)
test -n "$uv_bin"
test ! -e "$venv_dir"
mkdir -p /workspace/venvs "$cache_dir"
cd "$stage_root"
UV_HTTP_TIMEOUT=300 UV_PROJECT_ENVIRONMENT="$venv_dir" "$uv_bin" sync --locked
"$venv_dir/bin/python" - <<'PY'
from huggingface_hub import snapshot_download
path = snapshot_download(
    repo_id="Qwen/Qwen2.5-7B-Instruct",
    revision="a09a35458c702b33eeacc393d103063234e8bc28",
    cache_dir="/workspace/.cache/huggingface/hub",
)
print(path)
PY
