#!/usr/bin/env python3
"""Fail-closed local validation before a RunPod stop operation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


HEX64 = re.compile(r"^[0-9a-f]{64}$")
STATUS_ROLES = {
    "terminal_success": {
        "behavior",
        "generation_snapshot",
        "stdout_log",
        "report",
        "manifest",
    },
    "authorized_partial": {
        "behavior",
        "generation_snapshot",
        "stdout_log",
        "incident_record",
    },
    "terminal_failure": {
        "generation_snapshot",
        "stdout_log",
        "incident_record",
    },
    "no_scientific_output": {
        "generation_snapshot",
        "stdout_log",
        "incident_record",
    },
    "terminal_archival_recovery": {
        "workspace_inventory",
        "recovery_record",
    },
}


class GateError(ValueError):
    """A stop-readiness invariant failed."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def require_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GateError(f"{label} must be a non-empty string")
    return value


def parse_utc(value: Any, label: str) -> str:
    text = require_string(value, label)
    candidate = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise GateError(f"{label} is not an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise GateError(f"{label} must include a timezone")
    return text


def validate_jsonl(path: Path) -> tuple[int, set[str]]:
    rows = 0
    row_ids: set[str] = set()
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.endswith("\n"):
                raise GateError(
                    f"behavior JSONL has an incomplete final line at {line_number}"
                )
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise GateError(
                    f"behavior JSONL line {line_number} is invalid JSON"
                ) from exc
            if not isinstance(value, dict):
                raise GateError(
                    f"behavior JSONL line {line_number} is not an object"
                )
            row_id = require_string(
                value.get("row_id"), f"behavior line {line_number}.row_id"
            )
            if row_id in row_ids:
                raise GateError(f"duplicate behavior row_id: {row_id}")
            row_ids.add(row_id)
            rows += 1
    return rows, row_ids


def validate_receipt(receipt: dict[str, Any], base_dir: Path) -> dict[str, Any]:
    if receipt.get("schema_version") != 2:
        raise GateError("schema_version must equal 2")

    pod_id = require_string(receipt.get("pod_id"), "pod_id")
    run_id = require_string(receipt.get("run_id"), "run_id")
    parse_utc(receipt.get("retrieval_completed_at_utc"), "retrieval_completed_at_utc")
    parse_utc(receipt.get("endpoint_resolved_at_utc"), "endpoint_resolved_at_utc")
    if receipt.get("peer_pods_untouched") is not True:
        raise GateError("peer_pods_untouched must be true")

    inventory = receipt.get("artifact_inventory")
    if not isinstance(inventory, dict):
        raise GateError("artifact_inventory must be an object")
    if inventory.get("all_run_paths_enumerated") is not True:
        raise GateError("artifact_inventory.all_run_paths_enumerated must be true")
    if inventory.get("all_unique_nonreproducible_artifacts_accounted_for") is not True:
        raise GateError(
            "artifact_inventory.all_unique_nonreproducible_artifacts_accounted_for "
            "must be true"
        )
    inventory_roles = inventory.get("artifact_roles")
    if (
        not isinstance(inventory_roles, list)
        or not inventory_roles
        or any(not isinstance(role, str) or not role for role in inventory_roles)
        or len(inventory_roles) != len(set(inventory_roles))
    ):
        raise GateError(
            "artifact_inventory.artifact_roles must be a non-empty unique string list"
        )

    storage = receipt.get("storage")
    if not isinstance(storage, dict):
        raise GateError("storage must be an object")
    storage_kind = storage.get("kind")
    if storage_kind not in {"pod_volume", "network_volume"}:
        raise GateError("storage.kind must be pod_volume or network_volume")
    workspace_path = require_string(storage.get("workspace_path"), "storage.workspace_path")
    if not workspace_path.startswith("/"):
        raise GateError("storage.workspace_path must be absolute")
    if storage_kind == "pod_volume" and storage.get("host_bound") is not True:
        raise GateError("pod_volume storage must explicitly set host_bound=true")
    if storage_kind == "network_volume":
        require_string(storage.get("network_volume_id"), "storage.network_volume_id")

    completion = receipt.get("completion")
    if not isinstance(completion, dict):
        raise GateError("completion must be an object")
    status = completion.get("status")
    if status not in STATUS_ROLES:
        raise GateError(f"unsupported completion.status: {status!r}")
    expected_rows = completion.get("expected_behavior_rows")
    retrieved_rows = completion.get("retrieved_behavior_rows")
    if not isinstance(expected_rows, int) or expected_rows < 0:
        raise GateError("completion.expected_behavior_rows must be a non-negative integer")
    if not isinstance(retrieved_rows, int) or retrieved_rows < 0:
        raise GateError("completion.retrieved_behavior_rows must be a non-negative integer")
    remote_behavior_exists = completion.get("remote_behavior_exists")
    if not isinstance(remote_behavior_exists, bool):
        raise GateError("completion.remote_behavior_exists must be boolean")
    require_string(completion.get("authorization_id"), "completion.authorization_id")
    if status in {"authorized_partial", "terminal_failure", "no_scientific_output"}:
        require_string(completion.get("incident_id"), "completion.incident_id")

    if status == "terminal_success" and retrieved_rows != expected_rows:
        raise GateError("terminal_success requires retrieved rows to equal expected rows")
    if status == "authorized_partial" and not (0 < retrieved_rows < expected_rows):
        raise GateError("authorized_partial requires 0 < retrieved rows < expected rows")
    if status == "no_scientific_output":
        if remote_behavior_exists or retrieved_rows != 0:
            raise GateError(
                "no_scientific_output requires no remote behavior and zero retrieved rows"
            )
    if status == "terminal_archival_recovery":
        if expected_rows != 0 or retrieved_rows != 0 or remote_behavior_exists:
            raise GateError(
                "terminal_archival_recovery requires zero behavior rows and "
                "remote_behavior_exists=false"
            )
    if retrieved_rows > 0 and not remote_behavior_exists:
        raise GateError("retrieved behavior rows require remote_behavior_exists=true")

    artifacts = receipt.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise GateError("artifacts must be a non-empty list")

    roles: dict[str, dict[str, Any]] = {}
    verified_artifacts: list[dict[str, Any]] = []
    for index, artifact in enumerate(artifacts):
        label = f"artifacts[{index}]"
        if not isinstance(artifact, dict):
            raise GateError(f"{label} must be an object")
        role = require_string(artifact.get("role"), f"{label}.role")
        if role in roles:
            raise GateError(f"duplicate artifact role: {role}")
        roles[role] = artifact

        local_text = require_string(artifact.get("local_path"), f"{label}.local_path")
        local_path = Path(local_text)
        if not local_path.is_absolute():
            local_path = (base_dir / local_path).resolve()
        if not local_path.is_file():
            raise GateError(f"{label}.local_path does not exist: {local_path}")
        require_string(artifact.get("remote_path"), f"{label}.remote_path")
        remote_sha = require_string(
            artifact.get("remote_sha256"), f"{label}.remote_sha256"
        )
        recorded_local_sha = require_string(
            artifact.get("local_sha256"), f"{label}.local_sha256"
        )
        if not HEX64.fullmatch(remote_sha) or not HEX64.fullmatch(recorded_local_sha):
            raise GateError(f"{label} hashes must be lowercase SHA-256 hex")
        computed_sha = sha256_file(local_path)
        if computed_sha != remote_sha or computed_sha != recorded_local_sha:
            raise GateError(f"{label} remote/local/computed hashes do not match")

        verified = {
            "role": role,
            "local_path": str(local_path),
            "sha256": computed_sha,
            "bytes": local_path.stat().st_size,
        }
        if role == "behavior":
            row_count = artifact.get("row_count")
            if not isinstance(row_count, int) or row_count < 0:
                raise GateError("behavior.row_count must be a non-negative integer")
            actual_rows, _ = validate_jsonl(local_path)
            if actual_rows != row_count or actual_rows != retrieved_rows:
                raise GateError(
                    "behavior JSONL count must match artifact and completion counts"
                )
            verified["row_count"] = actual_rows
        verified_artifacts.append(verified)

    missing_roles = STATUS_ROLES[status] - set(roles)
    if missing_roles:
        raise GateError(f"missing required artifact roles: {sorted(missing_roles)}")
    if set(inventory_roles) != set(roles):
        raise GateError(
            "artifact_inventory.artifact_roles must exactly match listed artifacts"
        )
    if retrieved_rows > 0 and "behavior" not in roles:
        raise GateError("retrieved behavior rows require a behavior artifact")
    if status == "terminal_failure" and remote_behavior_exists and "behavior" not in roles:
        raise GateError("failed run with remote behavior requires retrieved behavior")

    return {
        "schema_version": 2,
        "stop_allowed": True,
        "pod_id": pod_id,
        "run_id": run_id,
        "completion_status": status,
        "receipt_sha256": canonical_sha256(receipt),
        "artifact_inventory_roles": sorted(inventory_roles),
        "verified_artifacts": verified_artifacts,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--approval-out", required=True, type=Path)
    args = parser.parse_args()

    if not args.receipt.is_file():
        print(f"STOP BLOCKED: receipt not found: {args.receipt}", file=sys.stderr)
        return 2
    try:
        receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
        if not isinstance(receipt, dict):
            raise GateError("receipt root must be an object")
        approval = validate_receipt(receipt, Path.cwd())
    except (GateError, json.JSONDecodeError, OSError) as exc:
        print(f"STOP BLOCKED: {exc}", file=sys.stderr)
        return 2

    if args.approval_out.exists():
        print(
            f"STOP BLOCKED: approval output already exists: {args.approval_out}",
            file=sys.stderr,
        )
        return 2
    args.approval_out.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(args.approval_out, flags, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(approval, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(
        f"STOP ALLOWED for pod={approval['pod_id']} run={approval['run_id']} "
        f"receipt_sha256={approval['receipt_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
