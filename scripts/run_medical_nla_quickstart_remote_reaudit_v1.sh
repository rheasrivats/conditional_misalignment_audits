#!/usr/bin/env bash
set -euo pipefail

transfer_root=/workspace/staging/medical_nla_em8_quickstart_cloud_transfer_v1
manifest_root="${transfer_root}/manifests"
manifest_script="${transfer_root}/build_quickstart_file_manifest.py"

python3 "${manifest_script}" \
  --root /workspace/shared/models/huggingface/hub \
  --virtual-prefix workspace/shared/models/huggingface/hub \
  --output "${manifest_root}/base_qwen.reaudit.v1.json" &
base_pid=$!

python3 "${manifest_script}" \
  --root /workspace/shared/adapters/hhh_only_10k \
  --virtual-prefix workspace/shared/adapters/hhh_only_10k \
  --output "${manifest_root}/hhh_adapter.reaudit.v1.json" &
adapter_pid=$!

python3 "${manifest_script}" \
  --root /workspace/shared/models/nla-qwen2.5-7b-L20-av-b884691 \
  --virtual-prefix workspace/shared/models/nla-qwen2.5-7b-L20-av-b884691 \
  --output "${manifest_root}/nla_av.reaudit.v1.json" &
av_pid=$!

python3 "${manifest_script}" \
  --root /workspace/shared/models/nla-qwen2.5-7b-L20-ar-e2c9e57 \
  --virtual-prefix workspace/shared/models/nla-qwen2.5-7b-L20-ar-e2c9e57 \
  --output "${manifest_root}/nla_ar.reaudit.v1.json" &
ar_pid=$!

wait "${base_pid}"
wait "${adapter_pid}"
wait "${av_pid}"
wait "${ar_pid}"

python3 - "${manifest_root}" <<'PY'
import glob
import json
import os
import sys

for path in sorted(glob.glob(os.path.join(sys.argv[1], "*.reaudit.v1.json"))):
    with open(path, encoding="utf-8") as handle:
        manifest = json.load(handle)
    print(
        os.path.basename(path),
        manifest["entry_count"],
        manifest["file_bytes"],
        manifest["entries_sha256"],
    )
PY
