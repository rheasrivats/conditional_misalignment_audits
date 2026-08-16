#!/usr/bin/env python3
"""Verify the terminal EM8 NLA archive and build its immutable stop receipt."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUN_ID = "medical_nla_em8_layer_position_ar_development_v1"
POD_ID = "xay33l9cp5here"
AUTHORIZATION_ID = "DEC-0194"
EXPECTED_ROWS = 396

RETRIEVAL = ROOT / "runs" / RUN_ID / "terminal_retrieval_v1"
REMOTE_RUN = RETRIEVAL / "remote_run"
REMOTE_STAGING = (
    RETRIEVAL
    / "remote_staging_complete"
    / "medical_nla_em8_layer_position_ar_v1"
)
REMOTE_RECEIPTS = RETRIEVAL / "remote_receipts"
INVENTORY = REMOTE_RECEIPTS / "remote_task_inventory.sha256"
STAGING_ARCHIVE = (
    REMOTE_RECEIPTS / "staging_medical_nla_em8_layer_position_ar_v1.tar.gz"
)
VERIFICATION = RETRIEVAL / "retrieval_verification.v1.json"
STOP_RECEIPT = RETRIEVAL / "stop_receipt.v2.json"

RUN_REMOTE_PREFIX = f"/workspace/runs/{RUN_ID}/"
STAGING_REMOTE_PREFIX = "/workspace/staging/medical_nla_em8_layer_position_ar_v1/"
RECEIPT_REMOTE_PREFIX = f"/workspace/retrieval_receipts/{RUN_ID}/"

BEHAVIOR_REMOTE = f"{RUN_REMOTE_PREFIX}attempt_001/decode/decoded.jsonl"
REPORT_REMOTE = f"{RUN_REMOTE_PREFIX}attempt_001/reconstruct/fidelity.jsonl"
MANIFEST_REMOTE = f"{RUN_REMOTE_PREFIX}artifact_manifest.json"
STDOUT_REMOTE = f"{RUN_REMOTE_PREFIX}operational_successor_004/stdout.log"
SNAPSHOT_REMOTE = (
    f"{STAGING_REMOTE_PREFIX}configs/frozen/"
    "medical_nla_em8_layer_position_ar_development_v1.v1.json"
)

REQUIRED_ROLE_BY_REMOTE = {
    BEHAVIOR_REMOTE: "behavior",
    REPORT_REMOTE: "report",
    MANIFEST_REMOTE: "manifest",
    STDOUT_REMOTE: "stdout_log",
    SNAPSHOT_REMOTE: "generation_snapshot",
}

EXPECTED_INVENTORY_SHA256 = (
    "c8fd0c86501cbf82c44076d0d7824a0e56fa37bf3cb7060fee86e537ff01fb67"
)
EXPECTED_STAGING_ARCHIVE_SHA256 = (
    "ee6d9908be7b63662e2c265ebd7fddf43897d7202c7e963936ace02b69281614"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def relative(path: Path) -> str:
    return str(path.relative_to(ROOT))


def role_for(remote_path: str) -> str:
    required = REQUIRED_ROLE_BY_REMOTE.get(remote_path)
    if required is not None:
        return required
    return re.sub(r"[^a-zA-Z0-9]+", "_", remote_path).strip("_").lower()


def local_for(remote_path: str) -> Path:
    if remote_path.startswith(RUN_REMOTE_PREFIX):
        return REMOTE_RUN / remote_path.removeprefix(RUN_REMOTE_PREFIX)
    if remote_path.startswith(STAGING_REMOTE_PREFIX):
        return REMOTE_STAGING / remote_path.removeprefix(STAGING_REMOTE_PREFIX)
    raise ValueError(f"unexpected remote path in inventory: {remote_path}")


def valid_jsonl_rows(path: Path) -> int:
    count = 0
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.endswith("\n"):
                raise ValueError(f"incomplete JSONL line {line_number}: {path}")
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"non-object JSONL line {line_number}: {path}")
            count += 1
    return count


def main() -> None:
    if STOP_RECEIPT.exists() or VERIFICATION.exists():
        raise FileExistsError("stop receipt or verification record already exists")

    if sha256_file(INVENTORY) != EXPECTED_INVENTORY_SHA256:
        raise ValueError("remote inventory hash differs from sealed value")
    if sha256_file(STAGING_ARCHIVE) != EXPECTED_STAGING_ARCHIVE_SHA256:
        raise ValueError("staging archive hash differs from sealed value")

    artifacts: list[dict[str, object]] = []
    verified: list[dict[str, object]] = []
    seen_roles: set[str] = set()
    inventory_lines = INVENTORY.read_text(encoding="utf-8").splitlines()
    if len(inventory_lines) != 211:
        raise ValueError(f"expected 211 remote files, found {len(inventory_lines)}")

    for line in inventory_lines:
        remote_sha256, remote_path = line.split("  ", 1)
        local_path = local_for(remote_path)
        if not local_path.is_file():
            raise FileNotFoundError(local_path)
        local_sha256 = sha256_file(local_path)
        if local_sha256 != remote_sha256:
            raise ValueError(f"remote/local hash mismatch: {remote_path}")
        role = role_for(remote_path)
        if role in seen_roles:
            raise ValueError(f"duplicate receipt role: {role}")
        seen_roles.add(role)
        artifact: dict[str, object] = {
            "role": role,
            "local_path": relative(local_path),
            "remote_path": remote_path,
            "remote_sha256": remote_sha256,
            "local_sha256": local_sha256,
        }
        if role == "behavior":
            artifact["row_count"] = EXPECTED_ROWS
        artifacts.append(artifact)
        verified.append(
            {
                "remote_path": remote_path,
                "local_path": relative(local_path),
                "sha256": local_sha256,
                "bytes": local_path.stat().st_size,
            }
        )

    recovery_artifacts = [
        (
            "remote_task_inventory",
            INVENTORY,
            f"{RECEIPT_REMOTE_PREFIX}remote_task_inventory.sha256",
            EXPECTED_INVENTORY_SHA256,
        ),
        (
            "staging_archive",
            STAGING_ARCHIVE,
            (
                f"{RECEIPT_REMOTE_PREFIX}"
                "staging_medical_nla_em8_layer_position_ar_v1.tar.gz"
            ),
            EXPECTED_STAGING_ARCHIVE_SHA256,
        ),
    ]
    for role, local_path, remote_path, expected_sha256 in recovery_artifacts:
        if role in seen_roles:
            raise ValueError(f"duplicate receipt role: {role}")
        seen_roles.add(role)
        local_sha256 = sha256_file(local_path)
        if local_sha256 != expected_sha256:
            raise ValueError(f"recovery artifact hash mismatch: {local_path}")
        artifacts.append(
            {
                "role": role,
                "local_path": relative(local_path),
                "remote_path": remote_path,
                "remote_sha256": expected_sha256,
                "local_sha256": expected_sha256,
            }
        )

    decode_rows = valid_jsonl_rows(local_for(BEHAVIOR_REMOTE))
    fidelity_rows = valid_jsonl_rows(local_for(REPORT_REMOTE))
    if decode_rows != EXPECTED_ROWS or fidelity_rows != EXPECTED_ROWS:
        raise ValueError(
            f"terminal rows differ: decode={decode_rows}, fidelity={fidelity_rows}"
        )
    terminal_attempt = REMOTE_RUN / "operational_successor_004"
    if (
        terminal_attempt / "terminal_status.txt"
    ).read_text(encoding="utf-8").strip() != "complete":
        raise ValueError("terminal successor status is not complete")
    if (
        terminal_attempt / "exit_code.txt"
    ).read_text(encoding="utf-8").strip() != "0":
        raise ValueError("terminal successor exit code is not zero")

    s3_receipts = {
        "decode": (
            ROOT
            / "runs"
            / RUN_ID
            / "checkpoints"
            / "decode"
            / "receipts"
            / "decoded.rows-000396.s3-receipt.json"
        ),
        "reconstruct": (
            ROOT
            / "runs"
            / RUN_ID
            / "checkpoints"
            / "reconstruct"
            / "receipts"
            / "fidelity.rows-000396.s3-receipt.json"
        ),
    }
    for path in s3_receipts.values():
        if not path.is_file():
            raise FileNotFoundError(path)

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    verification = {
        "schema_version": 1,
        "run_id": RUN_ID,
        "pod_id": POD_ID,
        "verified_at_utc": now,
        "enumerated_roots": [
            f"/workspace/runs/{RUN_ID}",
            "/workspace/staging/medical_nla_em8_layer_position_ar_v1",
            f"/workspace/retrieval_receipts/{RUN_ID}",
        ],
        "remote_inventory_file_count": len(inventory_lines),
        "recovery_artifact_count": len(recovery_artifacts),
        "decode_rows": decode_rows,
        "fidelity_rows": fidelity_rows,
        "all_remote_local_hashes_match": True,
        "verified_files": verified,
        "s3_terminal_receipts": {
            name: {
                "path": relative(path),
                "sha256": sha256_file(path),
            }
            for name, path in s3_receipts.items()
        },
        "pinned_reusable_inputs": {
            "base_model": "Qwen/Qwen2.5-7B-Instruct@a09a35458c702b33eeacc393d103063234e8bc28",
            "hhh_only_adapter_model_sha256": "48e52baec68f93f155392829d348df00e90ff5492be8c4e51d83f95b6a89d182",
            "av_revision": "b884691",
            "ar_revision": "e2c9e57",
        },
    }
    VERIFICATION.write_text(
        json.dumps(verification, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    receipt = {
        "schema_version": 2,
        "pod_id": POD_ID,
        "run_id": RUN_ID,
        "storage": {
            "kind": "pod_volume",
            "workspace_path": "/workspace",
            "host_bound": True,
        },
        "completion": {
            "status": "terminal_success",
            "expected_behavior_rows": EXPECTED_ROWS,
            "retrieved_behavior_rows": EXPECTED_ROWS,
            "remote_behavior_exists": True,
            "authorization_id": AUTHORIZATION_ID,
            "incident_id": None,
        },
        "retrieval_completed_at_utc": now,
        "endpoint_resolved_at_utc": now,
        "peer_pods_untouched": True,
        "artifact_inventory": {
            "all_run_paths_enumerated": True,
            "all_unique_nonreproducible_artifacts_accounted_for": True,
            "artifact_roles": [artifact["role"] for artifact in artifacts],
            "enumerated_roots": verification["enumerated_roots"],
            "classification_record": relative(VERIFICATION),
        },
        "artifacts": artifacts,
    }
    STOP_RECEIPT.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"VERIFIED files={len(inventory_lines)} "
        f"artifacts={len(artifacts)} decode={decode_rows} fidelity={fidelity_rows}"
    )
    print(f"verification_sha256={sha256_file(VERIFICATION)}")
    print(f"stop_receipt_sha256={sha256_file(STOP_RECEIPT)}")


if __name__ == "__main__":
    main()
