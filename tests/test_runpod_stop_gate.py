import hashlib
import importlib.util
import json
from pathlib import Path


SCRIPT = (
    Path(__file__).parents[1]
    / "skills"
    / "runpod-experiment-operator"
    / "scripts"
    / "runpod_stop_gate.py"
)
SPEC = importlib.util.spec_from_file_location("runpod_stop_gate", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _write(path: Path, text: str) -> dict:
    path.write_text(text, encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "local_path": str(path),
        "remote_path": f"/workspace/{path.name}",
        "remote_sha256": digest,
        "local_sha256": digest,
    }


def _success_receipt(tmp_path: Path) -> dict:
    behavior = _write(
        tmp_path / "behavior.jsonl",
        '{"row_id":"one"}\n{"row_id":"two"}\n',
    )
    behavior.update({"role": "behavior", "row_count": 2})
    artifacts = [behavior]
    for role, name in [
        ("generation_snapshot", "snapshot.json"),
        ("stdout_log", "stdout.log"),
        ("report", "report.json"),
        ("manifest", "manifest.json"),
    ]:
        artifact = _write(tmp_path / name, "{}\n")
        artifact["role"] = role
        artifacts.append(artifact)
    return {
        "schema_version": 2,
        "pod_id": "pod-opaque",
        "run_id": "run-exact",
        "storage": {
            "kind": "pod_volume",
            "workspace_path": "/workspace",
            "host_bound": True,
        },
        "completion": {
            "status": "terminal_success",
            "expected_behavior_rows": 2,
            "retrieved_behavior_rows": 2,
            "remote_behavior_exists": True,
            "authorization_id": "RUN-TEST",
            "incident_id": None,
        },
        "retrieval_completed_at_utc": "2026-07-27T00:00:00Z",
        "endpoint_resolved_at_utc": "2026-07-27T00:00:00Z",
        "peer_pods_untouched": True,
        "artifact_inventory": {
            "all_run_paths_enumerated": True,
            "all_unique_nonreproducible_artifacts_accounted_for": True,
            "artifact_roles": [artifact["role"] for artifact in artifacts],
        },
        "artifacts": artifacts,
    }


def test_terminal_success_passes(tmp_path):
    approval = MODULE.validate_receipt(_success_receipt(tmp_path), tmp_path)
    assert approval["stop_allowed"] is True
    assert approval["pod_id"] == "pod-opaque"
    assert len(approval["verified_artifacts"]) == 5


def test_missing_manifest_blocks_stop(tmp_path):
    receipt = _success_receipt(tmp_path)
    receipt["artifacts"] = [
        artifact for artifact in receipt["artifacts"] if artifact["role"] != "manifest"
    ]
    try:
        MODULE.validate_receipt(receipt, tmp_path)
    except MODULE.GateError as exc:
        assert "manifest" in str(exc)
    else:
        raise AssertionError("stop gate unexpectedly accepted missing manifest")


def test_hash_mismatch_blocks_stop(tmp_path):
    receipt = _success_receipt(tmp_path)
    receipt["artifacts"][0]["remote_sha256"] = "0" * 64
    try:
        MODULE.validate_receipt(receipt, tmp_path)
    except MODULE.GateError as exc:
        assert "hashes do not match" in str(exc)
    else:
        raise AssertionError("stop gate unexpectedly accepted hash mismatch")


def test_incomplete_jsonl_blocks_stop(tmp_path):
    receipt = _success_receipt(tmp_path)
    behavior = Path(receipt["artifacts"][0]["local_path"])
    behavior.write_text('{"row_id":"one"}\n{"row_id":"two"}', encoding="utf-8")
    digest = hashlib.sha256(behavior.read_bytes()).hexdigest()
    receipt["artifacts"][0]["remote_sha256"] = digest
    receipt["artifacts"][0]["local_sha256"] = digest
    try:
        MODULE.validate_receipt(receipt, tmp_path)
    except MODULE.GateError as exc:
        assert "incomplete final line" in str(exc)
    else:
        raise AssertionError("stop gate unexpectedly accepted incomplete JSONL")


def test_no_scientific_output_requires_incident(tmp_path):
    receipt = _success_receipt(tmp_path)
    artifacts = []
    for role, name in [
        ("generation_snapshot", "snapshot.json"),
        ("stdout_log", "stdout.log"),
        ("incident_record", "incident.json"),
    ]:
        artifact = _write(tmp_path / name, "{}\n")
        artifact["role"] = role
        artifacts.append(artifact)
    receipt["completion"] = {
        "status": "no_scientific_output",
        "expected_behavior_rows": 2,
        "retrieved_behavior_rows": 0,
        "remote_behavior_exists": False,
        "authorization_id": "RUN-TEST",
        "incident_id": "INC-TEST",
    }
    receipt["artifacts"] = artifacts
    receipt["artifact_inventory"]["artifact_roles"] = [
        artifact["role"] for artifact in artifacts
    ]
    approval = MODULE.validate_receipt(receipt, tmp_path)
    assert approval["completion_status"] == "no_scientific_output"


def test_incomplete_remote_inventory_blocks_stop(tmp_path):
    receipt = _success_receipt(tmp_path)
    receipt["artifact_inventory"][
        "all_unique_nonreproducible_artifacts_accounted_for"
    ] = False
    try:
        MODULE.validate_receipt(receipt, tmp_path)
    except MODULE.GateError as exc:
        assert "all_unique_nonreproducible_artifacts_accounted_for" in str(exc)
    else:
        raise AssertionError("stop gate unexpectedly accepted incomplete inventory")


def test_inventory_roles_must_match_artifacts(tmp_path):
    receipt = _success_receipt(tmp_path)
    receipt["artifact_inventory"]["artifact_roles"].remove("manifest")
    try:
        MODULE.validate_receipt(receipt, tmp_path)
    except MODULE.GateError as exc:
        assert "must exactly match" in str(exc)
    else:
        raise AssertionError("stop gate unexpectedly accepted mismatched inventory")


def test_terminal_archival_recovery_passes(tmp_path):
    artifacts = []
    for role, name in [
        ("workspace_inventory", "workspace-inventory.json"),
        ("recovery_record", "recovery-record.json"),
        ("artifact_000001", "adapter_model.safetensors"),
    ]:
        artifact = _write(tmp_path / name, "{}\n")
        artifact["role"] = role
        artifacts.append(artifact)
    receipt = _success_receipt(tmp_path)
    receipt["completion"] = {
        "status": "terminal_archival_recovery",
        "expected_behavior_rows": 0,
        "retrieved_behavior_rows": 0,
        "remote_behavior_exists": False,
        "authorization_id": "DEC-TEST",
        "incident_id": None,
    }
    receipt["artifacts"] = artifacts
    receipt["artifact_inventory"]["artifact_roles"] = [
        artifact["role"] for artifact in artifacts
    ]
    approval = MODULE.validate_receipt(receipt, tmp_path)
    assert approval["completion_status"] == "terminal_archival_recovery"


def test_terminal_archival_recovery_rejects_behavior_rows(tmp_path):
    receipt = _success_receipt(tmp_path)
    receipt["completion"]["status"] = "terminal_archival_recovery"
    try:
        MODULE.validate_receipt(receipt, tmp_path)
    except MODULE.GateError as exc:
        assert "zero behavior rows" in str(exc)
    else:
        raise AssertionError("archival recovery accepted behavior rows")
