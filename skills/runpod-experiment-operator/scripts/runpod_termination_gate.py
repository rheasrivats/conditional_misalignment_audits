#!/usr/bin/env python3
"""Fail-closed local validation before permanent RunPod Pod termination."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


HEX64 = re.compile(r"^[0-9a-f]{64}$")
MAX_PROVIDER_CHECK_AGE_SECONDS = 15 * 60


class GateError(ValueError):
    """A termination-readiness invariant failed."""


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


def parse_utc(value: Any, label: str) -> datetime:
    text = require_string(value, label)
    candidate = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise GateError(f"{label} is not an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise GateError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc)


def resolve_file(path_text: Any, label: str, base_dir: Path) -> Path:
    text = require_string(path_text, label)
    path = Path(text)
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    if not path.is_file():
        raise GateError(f"{label} does not exist: {path}")
    return path


def validate_receipt(
    receipt: dict[str, Any],
    base_dir: Path,
    now: datetime | None = None,
) -> dict[str, Any]:
    if receipt.get("schema_version") != 1:
        raise GateError("schema_version must equal 1")

    pod_id = require_string(receipt.get("pod_id"), "pod_id")
    pod_name = require_string(receipt.get("pod_name"), "pod_name")
    run_id = require_string(receipt.get("run_id"), "run_id")

    provider = receipt.get("provider")
    if not isinstance(provider, dict):
        raise GateError("provider must be an object")
    if provider.get("status") != "EXITED":
        raise GateError("provider.status must equal EXITED")
    checked_at = parse_utc(provider.get("checked_at_utc"), "provider.checked_at_utc")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    age = (current - checked_at).total_seconds()
    if age < -60:
        raise GateError("provider.checked_at_utc is in the future")
    if age > MAX_PROVIDER_CHECK_AGE_SECONDS:
        raise GateError("provider state check is older than 15 minutes")

    stop_ref = receipt.get("stop_approval")
    if not isinstance(stop_ref, dict):
        raise GateError("stop_approval must be an object")
    stop_path = resolve_file(
        stop_ref.get("local_path"), "stop_approval.local_path", base_dir
    )
    recorded_stop_sha = require_string(
        stop_ref.get("sha256"), "stop_approval.sha256"
    )
    if not HEX64.fullmatch(recorded_stop_sha):
        raise GateError("stop_approval.sha256 must be lowercase SHA-256 hex")
    computed_stop_sha = sha256_file(stop_path)
    if computed_stop_sha != recorded_stop_sha:
        raise GateError("stop approval computed hash does not match")
    try:
        stop_approval = json.loads(stop_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise GateError("stop approval is invalid JSON") from exc
    if not isinstance(stop_approval, dict) or stop_approval.get("stop_allowed") is not True:
        raise GateError("stop approval must contain stop_allowed=true")
    if stop_approval.get("pod_id") != pod_id:
        raise GateError("stop approval Pod ID does not match")
    if stop_approval.get("run_id") != run_id:
        raise GateError("stop approval run ID does not match")
    completion_status = require_string(
        stop_approval.get("completion_status"),
        "stop_approval.completion_status",
    )

    authorization = receipt.get("destructive_authorization")
    if not isinstance(authorization, dict):
        raise GateError("destructive_authorization must be an object")
    if authorization.get("action") != "terminate_pod":
        raise GateError("destructive_authorization.action must be terminate_pod")
    decision_id = require_string(
        authorization.get("decision_id"),
        "destructive_authorization.decision_id",
    )
    if authorization.get("authorized_pod_id") != pod_id:
        raise GateError("destructive authorization Pod ID does not match")
    require_string(
        authorization.get("user_confirmation"),
        "destructive_authorization.user_confirmation",
    )
    parse_utc(
        authorization.get("recorded_at_utc"),
        "destructive_authorization.recorded_at_utc",
    )

    storage = receipt.get("storage_disposition")
    if not isinstance(storage, dict):
        raise GateError("storage_disposition must be an object")
    kind = storage.get("kind")
    if kind not in {"pod_volume", "network_volume"}:
        raise GateError(
            "storage_disposition.kind must be pod_volume or network_volume"
        )
    if storage.get("host_local_loss_accounted_for") is not True:
        raise GateError("host_local_loss_accounted_for must be true")
    if kind == "network_volume":
        volume_id = require_string(
            storage.get("network_volume_id"),
            "storage_disposition.network_volume_id",
        )
        if storage.get("network_volume_action") != "retain":
            raise GateError("Pod termination requires network_volume_action=retain")
    else:
        volume_id = None
        if storage.get("network_volume_id") is not None:
            raise GateError("pod_volume requires network_volume_id=null")
        if storage.get("network_volume_action") is not None:
            raise GateError("pod_volume requires network_volume_action=null")

    abandonment_decision = storage.get("abandonment_decision_id")
    abandonment_incident = storage.get("abandonment_incident_id")
    if completion_status not in {
        "terminal_success",
        "terminal_archival_recovery",
    }:
        if abandonment_decision is None and completion_status not in {
            "authorized_partial",
            "terminal_failure",
            "no_scientific_output",
        }:
            raise GateError("non-successful completion is not accounted for")
    if (abandonment_decision is None) != (abandonment_incident is None):
        raise GateError(
            "abandonment decision and incident IDs must both be set or both be null"
        )
    if abandonment_decision is not None:
        require_string(abandonment_decision, "abandonment_decision_id")
        require_string(abandonment_incident, "abandonment_incident_id")

    if receipt.get("recovery_actions_outstanding") is not False:
        raise GateError("recovery_actions_outstanding must be false")
    if receipt.get("peer_pods_untouched") is not True:
        raise GateError("peer_pods_untouched must be true")

    return {
        "schema_version": 1,
        "termination_allowed": True,
        "action": "terminate_pod",
        "pod_id": pod_id,
        "pod_name": pod_name,
        "run_id": run_id,
        "decision_id": decision_id,
        "network_volume_id_retained": volume_id,
        "provider_checked_at_utc": checked_at.isoformat(),
        "stop_approval_sha256": computed_stop_sha,
        "receipt_sha256": canonical_sha256(receipt),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--approval-out", required=True, type=Path)
    args = parser.parse_args()

    if not args.receipt.is_file():
        print(
            f"TERMINATION BLOCKED: receipt not found: {args.receipt}",
            file=sys.stderr,
        )
        return 2
    try:
        receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
        if not isinstance(receipt, dict):
            raise GateError("receipt root must be an object")
        approval = validate_receipt(receipt, Path.cwd())
    except (GateError, json.JSONDecodeError, OSError) as exc:
        print(f"TERMINATION BLOCKED: {exc}", file=sys.stderr)
        return 2

    if args.approval_out.exists():
        print(
            f"TERMINATION BLOCKED: approval output already exists: "
            f"{args.approval_out}",
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
        f"TERMINATION ALLOWED for pod={approval['pod_id']} "
        f"run={approval['run_id']} receipt_sha256={approval['receipt_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
