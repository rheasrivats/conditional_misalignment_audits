#!/usr/bin/env bash
set -euo pipefail

: "${POD_IP:?POD_IP must be freshly resolved before this SSH operation}"
: "${POD_PORT:?POD_PORT must be freshly resolved before this SSH operation}"
: "${REMOTE_SNAPSHOT:?REMOTE_SNAPSHOT must identify the staged frozen snapshot}"
: "${LOCAL_SNAPSHOT:?LOCAL_SNAPSHOT must identify the same local frozen snapshot}"

profile=runpod-recovery
identity_file="${HOME}/.ssh/id_ed25519"

remote_script=$(python3 - "$LOCAL_SNAPSHOT" "$REMOTE_SNAPSHOT" "$0" <<'PY'
import hashlib, json, sys
from pathlib import Path

snapshot_path = Path(sys.argv[1])
remote_snapshot = sys.argv[2]
launcher_path = Path(sys.argv[3])
snapshot = json.loads(snapshot_path.read_text())
if snapshot.get("stage") != "medical_claim1_nla_decode_development_v1":
    raise SystemExit("wrong frozen stage")
successor = snapshot["values"]["nla.medical_claim1_nla_restore_quota_resume_successor_v4"]
actual = hashlib.sha256(launcher_path.read_bytes()).hexdigest()
if actual != successor["code"]["restore_launcher_sha256"]:
    raise SystemExit("local restore launcher SHA-256 mismatch")
staging = successor["staging"]
if remote_snapshot != staging["remote_snapshot_path"]:
    raise SystemExit("remote snapshot path differs from frozen restore successor")
print(staging["remote_restore_runner_path"])
PY
)

aws configure export-credentials --profile "${profile}" --format process |
  ssh -p "${POD_PORT}" \
    -o BatchMode=yes \
    -o IdentitiesOnly=yes \
    -o IdentityAgent=none \
    -o StrictHostKeyChecking=accept-new \
    -i "${identity_file}" \
    "root@${POD_IP}" \
    "python3 '${remote_script}' --snapshot '${REMOTE_SNAPSHOT}'"
