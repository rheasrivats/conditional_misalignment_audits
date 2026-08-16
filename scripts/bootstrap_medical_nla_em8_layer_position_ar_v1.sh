#!/usr/bin/env bash
set -euo pipefail

stage_root=/workspace/staging/medical_nla_em8_layer_position_ar_v1
extract_venv=/workspace/venvs/medical-final-panel-py312-v1
server_venv=/workspace/venvs/medical-nla-py312-v1
actor_dir=/workspace/shared/models/nla-qwen2.5-7b-L20-av-b884691
critic_dir=/workspace/shared/models/nla-qwen2.5-7b-L20-ar-e2c9e57
source_dir="$stage_root/vendor/natural_language_autoencoders-1b7f13d"
snapshot_path="$stage_root/configs/frozen/medical_nla_em8_layer_position_ar_development_v1.v1.json"
uv_bin=$(command -v uv)

test -n "$uv_bin"
test -f "$snapshot_path"
test -f "$stage_root/uv.lock"
test -f "$stage_root/pyproject.toml"
test -f "$stage_root/scripts/run_medical_nla_em8_layer_position_ar_v1.py"
test -f "$stage_root/inputs/base_behavior.jsonl"
test -f "$stage_root/inputs/hhh_only_behavior.jsonl"
test ! -e /workspace/runs/medical_nla_em8_layer_position_ar_development_v1

available_kib=$(df -Pk /workspace | awk 'NR==2 {print $4}')
test "$available_kib" -ge 26214400

mkdir -p /workspace/venvs /workspace/shared/models
cd "$stage_root"
UV_HTTP_TIMEOUT=300 UV_PROJECT_ENVIRONMENT="$extract_venv" \
  "$uv_bin" sync --locked
UV_HTTP_TIMEOUT=300 UV_PROJECT_ENVIRONMENT="$server_venv" \
  "$uv_bin" sync --locked --extra nla-server

"$extract_venv/bin/python" - <<'PY'
from huggingface_hub import HfApi, snapshot_download

artifacts = (
    (
        "kitft/nla-qwen2.5-7b-L20-av",
        "b88469162777ae6553bc14208eb0cb579336f8f4",
        "/workspace/shared/models/nla-qwen2.5-7b-L20-av-b884691",
    ),
    (
        "kitft/nla-qwen2.5-7b-L20-ar",
        "e2c9e57eac213d37a31612087f645ab6332c1bb6",
        "/workspace/shared/models/nla-qwen2.5-7b-L20-ar-e2c9e57",
    ),
)
api = HfApi()
for repository, revision, directory in artifacts:
    resolved = api.model_info(repository, revision=revision).sha
    if resolved != revision:
        raise SystemExit(f"{repository}: resolved revision {resolved} != {revision}")
    print(snapshot_download(
        repo_id=repository, revision=revision, local_dir=directory,
    ))
PY

if [[ ! -d "$source_dir/.git" ]]; then
  test ! -e "$source_dir"
  git clone --no-checkout \
    https://github.com/kitft/natural_language_autoencoders.git "$source_dir"
fi
git -C "$source_dir" fetch --depth 1 origin \
  1b7f13d9d8a37075cd2e5d1604eca57820216ed5
git -C "$source_dir" checkout --detach \
  1b7f13d9d8a37075cd2e5d1604eca57820216ed5
test "$(git -C "$source_dir" rev-parse HEAD)" = \
  "1b7f13d9d8a37075cd2e5d1604eca57820216ed5"
test "$(sha256sum "$source_dir/nla_inference.py" | awk '{print $1}')" = \
  "45cbf64489dc8f1daa8c9e98fe4dd4e881e4fd743fd783d6128c070cc0677f26"

"$extract_venv/bin/python" - "$snapshot_path" <<'PY'
import hashlib
import json
from pathlib import Path
import sys
import yaml

snapshot = json.loads(Path(sys.argv[1]).read_text())
contract = snapshot["values"]["nla.medical_em8_layer_position_ar_development_v1"]

def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

if sha256_file(contract["nla"]["client_path"]) != contract["nla"]["client_sha256"]:
    raise SystemExit("official NLA client hash mismatch")
for role, path in (
    ("actor", contract["nla"]["actor_path"]),
    ("critic", contract["nla"]["ar_path"]),
):
    meta = yaml.safe_load((Path(path) / "nla_meta.yaml").read_text())
    accepted_roles = ("actor", "av") if role == "actor" else ("critic", "ar")
    if meta["role"] not in accepted_roles:
        raise SystemExit(f"{role}: sidecar role mismatch")
    if int(meta["d_model"]) != 3584:
        raise SystemExit(f"{role}: d_model mismatch")
print("BOOTSTRAP_RUNTIME_MODELS_AND_CLIENT_VERIFIED")
PY
