#!/usr/bin/env bash
set -euo pipefail

stage_root=/workspace/staging/medical_final_panel_v1
venv_dir=/workspace/venvs/medical-final-panel-py312-v1
cache_dir=/workspace/shared/models/huggingface/hub
em_adapter_dir=/workspace/shared/adapters/released_bad_medical_parent
uv_bin=$(command -v uv)

test -n "$uv_bin"
mkdir -p /workspace/venvs "$cache_dir"
cd "$stage_root"
UV_HTTP_TIMEOUT=300 UV_PROJECT_ENVIRONMENT="$venv_dir" \
  "$uv_bin" sync --locked --extra training
"$venv_dir/bin/python" - <<'PY'
from huggingface_hub import snapshot_download

print(snapshot_download(
    repo_id="Qwen/Qwen2.5-7B-Instruct",
    revision="a09a35458c702b33eeacc393d103063234e8bc28",
    cache_dir="/workspace/shared/models/huggingface/hub",
))
PY
if [[ "${BOOTSTRAP_EM_ADAPTER:-0}" == "1" ]]; then
  if [[ ! -d "$em_adapter_dir" ]]; then
    "$venv_dir/bin/python" - <<'PY'
from huggingface_hub import snapshot_download

print(snapshot_download(
    repo_id="ModelOrganismsForEM/Qwen2.5-7B-Instruct_bad-medical-advice",
    revision="0052099b56ebbd76e983b69ac433f2a0160bd4ef",
    local_dir="/workspace/shared/adapters/released_bad_medical_parent",
    allow_patterns=["adapter_model.safetensors", "adapter_config.json"],
))
PY
  fi
  test "$(sha256sum "$em_adapter_dir/adapter_model.safetensors" | awk '{print $1}')" = \
    "4e6b63faa0713f40b0cfb61d9ea06f5f7a2cb1372b653096339833619ab20fc5"
  test "$(sha256sum "$em_adapter_dir/adapter_config.json" | awk '{print $1}')" = \
    "7d43828c38fc63655176f803af47149a07a97c13585045d330d2367b0c89a80f"
fi
