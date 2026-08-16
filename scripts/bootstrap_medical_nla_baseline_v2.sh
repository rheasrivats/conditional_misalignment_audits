#!/usr/bin/env bash
set -euo pipefail

stage_root=/workspace/staging/medical_nla_baseline_v1
venv_dir=/workspace/venvs/medical-nla-py312-v1
actor_dir=/workspace/shared/models/nla-qwen2.5-7b-L20-av-b884691
source_dir=/workspace/staging/medical_nla_baseline_v1/vendor/natural_language_autoencoders-1b7f13d
model_cache=/workspace/shared/models/huggingface/hub
snapshot_path=/workspace/staging/medical_nla_baseline_v1/configs/frozen/medical_nla_baseline_micro_suite_v1.v3.json
uv_bin=$(command -v uv)

test -n "$uv_bin"
test -f "$snapshot_path"
test -f "$stage_root/uv.lock"
test -f "$stage_root/pyproject.toml"
test -f "$stage_root/scripts/run_medical_nla_baseline.py"
test -f "$stage_root/prompts/nla/medical_nla_baseline_micro_suite.v2.jsonl"
test ! -e /workspace/runs/medical_nla_baseline_micro_suite_v1

mkdir -p /workspace/venvs /workspace/shared/models "$model_cache"
cd "$stage_root"
UV_HTTP_TIMEOUT=300 UV_PROJECT_ENVIRONMENT="$venv_dir" \
  "$uv_bin" sync --locked --extra nla-server

"$venv_dir/bin/python" - <<'PY'
from huggingface_hub import snapshot_download

print(snapshot_download(
    repo_id="kitft/nla-qwen2.5-7b-L20-av",
    revision="b88469162777ae6553bc14208eb0cb579336f8f4",
    local_dir="/workspace/shared/models/nla-qwen2.5-7b-L20-av-b884691",
))
PY

if [[ ! -d "$source_dir/.git" ]]; then
  test ! -e "$source_dir"
  git clone --no-checkout https://github.com/kitft/natural_language_autoencoders.git "$source_dir"
fi
git -C "$source_dir" fetch --depth 1 origin 1b7f13d9d8a37075cd2e5d1604eca57820216ed5
git -C "$source_dir" checkout --detach 1b7f13d9d8a37075cd2e5d1604eca57820216ed5
test "$(git -C "$source_dir" rev-parse HEAD)" = \
  "1b7f13d9d8a37075cd2e5d1604eca57820216ed5"
test "$(sha256sum "$source_dir/nla_inference.py" | awk '{print $1}')" = \
  "45cbf64489dc8f1daa8c9e98fe4dd4e881e4fd743fd783d6128c070cc0677f26"

"$venv_dir/bin/python" - "$snapshot_path" <<'PY'
import hashlib
import importlib.metadata
import json
import platform
import sys
from pathlib import Path

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

snapshot = json.loads(Path(sys.argv[1]).read_text())
execution = snapshot["values"]["nla.medical_baseline_execution_contract_v1"]
runtime = execution["runtime"]
if platform.python_version() != runtime["python"]:
    raise SystemExit("Python version mismatch")
observed = {
    package: importlib.metadata.version(package)
    for package in runtime["packages"]
}
if observed != runtime["packages"]:
    raise SystemExit(f"package mismatch: {observed!r}")
actor = Path(execution["paths"]["actor_checkpoint"])
for filename, expected in execution["actor_files"].items():
    path = actor / filename
    if path.stat().st_size != expected["bytes"]:
        raise SystemExit(f"actor byte mismatch: {filename}")
    digest = sha256_file(path)
    if digest != expected["sha256"]:
        raise SystemExit(f"actor hash mismatch: {filename}")
print("BOOTSTRAP_RUNTIME_AND_ACTOR_VERIFIED")
PY
