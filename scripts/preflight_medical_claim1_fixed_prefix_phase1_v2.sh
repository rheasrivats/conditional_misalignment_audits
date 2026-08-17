#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 1 ]]; then
  echo "usage: $0 <snapshot-file>" >&2
  exit 2
fi

snapshot_file=$1
stage_root=/workspace/staging/medical_claim1_fixed_prefix_phase1_v1
base_preflight="${stage_root}/scripts/preflight_medical_claim1_fixed_prefix_phase1_v1.sh"
base_receipt="${stage_root}/preflight/attempt_001/runtime_and_source_receipt.v1.json"
successor_root="${stage_root}/preflight/attempt_002"
successor_receipt="${successor_root}/migration_runtime_and_source_receipt.v2.json"

test ! -e "$successor_root"
"$base_preflight" "$snapshot_file"
mkdir -p "$successor_root"

/workspace/venvs/medical-claim1-fixed-prefix-microtest-v2/bin/python - \
  "$snapshot_file" "$base_receipt" "$successor_receipt" "$0" <<'PY'
from __future__ import annotations

import hashlib
import json
import pathlib
import sys
from datetime import datetime, timezone


snapshot_path = pathlib.Path(sys.argv[1])
base_receipt_path = pathlib.Path(sys.argv[2])
successor_receipt_path = pathlib.Path(sys.argv[3])
self_path = pathlib.Path(sys.argv[4])
snapshot = json.loads(snapshot_path.read_text())
contract = snapshot["values"]["interventions.medical_claim1_fixed_prefix_phase1_v1"]
successor = snapshot["values"]["execution.medical_claim1_fixed_prefix_phase1_migration_v1"]


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if sha256_file(self_path) != successor["code"]["preflight_v2_sha256"]:
    raise ValueError("successor preflight differs from frozen identity")
if successor["predecessor_pod_id"] != contract["runtime"]["pod_id"]:
    raise ValueError("migration predecessor does not match scientific contract")
if successor["replacement_pod_id"] == successor["predecessor_pod_id"]:
    raise ValueError("migration replacement must have a fresh Pod ID")
base_receipt = json.loads(base_receipt_path.read_text())
if base_receipt["status"] != "runtime_sources_model_cache_and_adapter_verified":
    raise ValueError("base source/runtime audit is not terminal")
if base_receipt["scientific_requests_or_rows"] != 0:
    raise ValueError("base source/runtime audit observed scientific work")
if pathlib.Path(contract["output_directory"]).exists():
    raise ValueError("scientific output root exists before successor launch")

receipt = {
    "schema_version": 2,
    "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    "decision_id": successor["approval"],
    "stage": contract["stage"],
    "predecessor_pod_id": successor["predecessor_pod_id"],
    "replacement_pod_id": successor["replacement_pod_id"],
    "snapshot_sha256": sha256_file(snapshot_path),
    "base_receipt_sha256": sha256_file(base_receipt_path),
    "base_receipt_status": base_receipt["status"],
    "status": "migration_bound_and_runtime_sources_verified",
    "scientific_requests_or_rows": 0,
    "target_output_root_exists": False,
}
successor_receipt_path.write_text(
    json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
print(json.dumps(receipt, sort_keys=True))
PY
