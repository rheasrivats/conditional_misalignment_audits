import hashlib
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path


SCRIPT = (
    Path(__file__).parents[1]
    / "skills"
    / "runpod-experiment-operator"
    / "scripts"
    / "runpod_termination_gate.py"
)
SPEC = importlib.util.spec_from_file_location("runpod_termination_gate", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


NOW = datetime(2026, 7, 27, 20, 0, 0, tzinfo=timezone.utc)


def _write_stop_approval(tmp_path: Path) -> tuple[Path, str]:
    path = tmp_path / "stop-readiness.json"
    path.write_text(
        json.dumps(
            {
                "stop_allowed": True,
                "pod_id": "pod-opaque",
                "run_id": "run-exact",
                "completion_status": "terminal_success",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def _receipt(tmp_path: Path) -> dict:
    stop_path, stop_sha = _write_stop_approval(tmp_path)
    return {
        "schema_version": 1,
        "pod_id": "pod-opaque",
        "pod_name": "pod-exact-name",
        "run_id": "run-exact",
        "provider": {
            "status": "EXITED",
            "checked_at_utc": "2026-07-27T19:55:00Z",
        },
        "stop_approval": {
            "local_path": str(stop_path),
            "sha256": stop_sha,
        },
        "destructive_authorization": {
            "action": "terminate_pod",
            "decision_id": "DEC-TEST",
            "authorized_pod_id": "pod-opaque",
            "user_confirmation": "Terminate pod-opaque.",
            "recorded_at_utc": "2026-07-27T19:56:00Z",
        },
        "storage_disposition": {
            "kind": "network_volume",
            "network_volume_id": "volume-opaque",
            "network_volume_action": "retain",
            "host_local_loss_accounted_for": True,
            "abandonment_decision_id": None,
            "abandonment_incident_id": None,
        },
        "recovery_actions_outstanding": False,
        "peer_pods_untouched": True,
    }


def test_network_volume_termination_passes(tmp_path):
    approval = MODULE.validate_receipt(_receipt(tmp_path), tmp_path, now=NOW)
    assert approval["termination_allowed"] is True
    assert approval["pod_id"] == "pod-opaque"
    assert approval["network_volume_id_retained"] == "volume-opaque"


def test_running_pod_blocks_termination(tmp_path):
    receipt = _receipt(tmp_path)
    receipt["provider"]["status"] = "RUNNING"
    try:
        MODULE.validate_receipt(receipt, tmp_path, now=NOW)
    except MODULE.GateError as exc:
        assert "EXITED" in str(exc)
    else:
        raise AssertionError("termination gate accepted a running Pod")


def test_stale_provider_state_blocks_termination(tmp_path):
    receipt = _receipt(tmp_path)
    receipt["provider"]["checked_at_utc"] = "2026-07-27T19:40:00Z"
    try:
        MODULE.validate_receipt(receipt, tmp_path, now=NOW)
    except MODULE.GateError as exc:
        assert "older than 15 minutes" in str(exc)
    else:
        raise AssertionError("termination gate accepted stale provider state")


def test_mismatched_authorized_pod_blocks_termination(tmp_path):
    receipt = _receipt(tmp_path)
    receipt["destructive_authorization"]["authorized_pod_id"] = "another-pod"
    try:
        MODULE.validate_receipt(receipt, tmp_path, now=NOW)
    except MODULE.GateError as exc:
        assert "authorization Pod ID" in str(exc)
    else:
        raise AssertionError("termination gate accepted another Pod's authorization")


def test_network_volume_delete_action_blocks_termination(tmp_path):
    receipt = _receipt(tmp_path)
    receipt["storage_disposition"]["network_volume_action"] = "delete"
    try:
        MODULE.validate_receipt(receipt, tmp_path, now=NOW)
    except MODULE.GateError as exc:
        assert "retain" in str(exc)
    else:
        raise AssertionError("termination gate authorized network-volume deletion")


def test_outstanding_recovery_blocks_termination(tmp_path):
    receipt = _receipt(tmp_path)
    receipt["recovery_actions_outstanding"] = True
    try:
        MODULE.validate_receipt(receipt, tmp_path, now=NOW)
    except MODULE.GateError as exc:
        assert "recovery_actions_outstanding" in str(exc)
    else:
        raise AssertionError("termination gate accepted outstanding recovery")


def test_terminal_archival_recovery_termination_passes(tmp_path):
    receipt = _receipt(tmp_path)
    stop_path = Path(receipt["stop_approval"]["local_path"])
    approval = json.loads(stop_path.read_text(encoding="utf-8"))
    approval["completion_status"] = "terminal_archival_recovery"
    stop_path.write_text(json.dumps(approval) + "\n", encoding="utf-8")
    receipt["stop_approval"]["sha256"] = hashlib.sha256(
        stop_path.read_bytes()
    ).hexdigest()
    result = MODULE.validate_receipt(receipt, tmp_path, now=NOW)
    assert result["termination_allowed"] is True
