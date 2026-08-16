#!/usr/bin/env bash
set -euo pipefail

stage_root=/workspace/medical_identity_free_assistant_control_stage_v4
python_env=/workspace/venvs/medical-primary-py312
uv_cache=/workspace/.cache/uv
hf_home=/workspace/.cache/huggingface

test -x /usr/local/bin/uv
test -f "$stage_root/pyproject.toml"
test -f "$stage_root/uv.lock"
test ! -e "$python_env"
mkdir -p /workspace/venvs "$uv_cache" "$hf_home"
/usr/local/bin/uv venv "$python_env" --python 3.12
UV_CACHE_DIR="$uv_cache" UV_PROJECT_ENVIRONMENT="$python_env" \
  /usr/local/bin/uv sync --locked --project "$stage_root" --no-dev --extra training
HF_HOME="$hf_home" "$python_env/bin/python" - <<'PY'
from huggingface_hub import snapshot_download

print(snapshot_download(
    repo_id="Qwen/Qwen2.5-7B-Instruct",
    revision="a09a35458c702b33eeacc393d103063234e8bc28",
))
PY
"$python_env/bin/python" - <<'PY'
import accelerate
import bitsandbytes
import peft
import torch
import transformers

expected = {
    "torch": "2.9.1",
    "transformers": "4.57.1",
    "peft": "0.19.1",
    "accelerate": "1.14.0",
    "bitsandbytes": "0.49.2",
}
observed = {
    "torch": torch.__version__.split("+", 1)[0],
    "transformers": transformers.__version__,
    "peft": peft.__version__,
    "accelerate": accelerate.__version__,
    "bitsandbytes": bitsandbytes.__version__,
}
if observed != expected:
    raise SystemExit(f"package identity mismatch: {observed!r} != {expected!r}")
print(observed)
PY
