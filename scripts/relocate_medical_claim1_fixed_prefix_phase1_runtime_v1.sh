#!/usr/bin/env bash
set -euo pipefail

source_venv=/workspace/venvs/medical-claim1-fixed-prefix-phase1-v1
target_venv=/root/venvs/medical-claim1-fixed-prefix-phase1-v1
receipt_tmp=/root/medical_claim1_fixed_prefix_phase1_runtime_relocation.v1.json
receipt_final=/workspace/staging/medical_claim1_fixed_prefix_phase1_v1/preflight/attempt_004/runtime_relocation_receipt.v1.json

test -x "$source_venv/bin/python"
test ! -e "$target_venv"
test ! -e "$receipt_tmp"
test ! -e "$receipt_final"
test ! -e /workspace/runs/medical_claim1_fixed_prefix_phase1_v1/attempt_002
test ! -e /workspace/runs/medical_claim1_fixed_prefix_phase1_v1_execution/attempt_002

mkdir -p /root/venvs
cp -a "$source_venv" "$target_venv"

"$target_venv/bin/python" - "$source_venv" "$target_venv" "$receipt_tmp" <<'PY'
from __future__ import annotations

import importlib.metadata
import json
import pathlib
import platform
import sys
from datetime import datetime, timezone

import torch

source = pathlib.Path(sys.argv[1])
target = pathlib.Path(sys.argv[2])
receipt = pathlib.Path(sys.argv[3])

expected = {
    "accelerate": "1.14.0",
    "bitsandbytes": "0.49.2",
    "peft": "0.19.1",
    "torch": "2.9.1",
    "transformers": "4.57.1",
}
actual = {name: importlib.metadata.version(name) for name in expected}
if actual != expected:
    raise SystemExit(f"runtime package mismatch: {actual!r}")
if platform.python_version() != "3.12.3":
    raise SystemExit("runtime Python mismatch")
if str(torch.version.cuda) != "12.8":
    raise SystemExit("runtime CUDA mismatch")
if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
    raise SystemExit("exactly one CUDA GPU is required")
gpu = torch.cuda.get_device_name(0)
if "A40" not in gpu:
    raise SystemExit(f"GPU mismatch: {gpu}")

receipt.write_text(
    json.dumps(
        {
            "schema_version": 1,
            "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "decision_id": "DEC-0284",
            "incident_id": "INC-0111",
            "classification": "implementation_only_reproducible_runtime_relocation",
            "source_environment": str(source),
            "target_environment": str(target),
            "python": platform.python_version(),
            "packages": actual,
            "torch_cuda_runtime": str(torch.version.cuda),
            "cuda_device_name": gpu,
            "scientific_attempt_002_absent_before_relocation": True,
            "scientific_values_changed": False,
            "status": "target_runtime_verified_before_source_removal",
        },
        indent=2,
        sort_keys=True,
    )
    + "\n"
)
PY

# This directory was created from the frozen lock solely for this task and is
# fully reproducible. Remove only this exact verified source after its copied
# target has passed the runtime identity checks above.
rm -rf -- /workspace/venvs/medical-claim1-fixed-prefix-phase1-v1

mkdir -p "$(dirname "$receipt_final")"
mv "$receipt_tmp" "$receipt_final"
test -x "$target_venv/bin/python"
test ! -e "$source_venv"
test -s "$receipt_final"
df -h / /workspace
