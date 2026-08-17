#!/usr/bin/env python3
"""Recover the exact harm-enrichment runtime through a frozen symlink path."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path


STAGE = "claim1_nla_harm_enrichment_runtime_recovery_v4"
PARAMETER = "operations.claim1_nla_harm_enrichment_runtime_recovery_v4"
PREDECESSOR_PARAMETER = "operations.claim1_nla_harm_enrichment_runtime_recovery_v1"


def load_base():
    path = Path(__file__).with_name("preflight_claim1_nla_harm_enrichment_runtime_v1.py")
    spec = importlib.util.spec_from_file_location("harm_runtime_preflight_v1", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load predecessor preflight")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def validate_existing_restore(path: Path, old: dict) -> None:
    receipt = json.loads(path.read_text())
    if receipt.get("status") != "restored_and_verified":
        raise ValueError("existing restore receipt is not terminally verified")
    if receipt.get("scientific_request_issued") is not False:
        raise ValueError("existing restore receipt records a scientific request")
    if receipt.get("credential_persisted") is not False:
        raise ValueError("existing restore receipt records a credential")
    observed = sorted(item.get("tree_manifest_sha256") for item in receipt.get("objects", []))
    expected = sorted(item["manifest_sha256"] for item in old["models"])
    if observed != expected:
        raise ValueError("existing restore receipt model manifests differ")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--operations-snapshot", type=Path, required=True)
    parser.add_argument("--predecessor-operations-snapshot", type=Path, required=True)
    parser.add_argument("--scientific-snapshot", type=Path, required=True)
    args = parser.parse_args()
    base = load_base()

    operations = json.loads(args.operations_snapshot.read_text())
    if operations.get("stage") != STAGE:
        raise ValueError("wrong operations stage")
    contract = operations["values"][PARAMETER]
    if base.sha256_file(Path(__file__)) != contract["code"]["preflight_sha256"]:
        raise ValueError("successor preflight code hash mismatch")

    predecessor = json.loads(args.predecessor_operations_snapshot.read_text())
    if base.sha256_file(args.predecessor_operations_snapshot) != contract["predecessor_recovery_snapshot"]["sha256"]:
        raise ValueError("predecessor recovery snapshot hash mismatch")
    old = predecessor["values"][PREDECESSOR_PARAMETER]
    if base.sha256_file(args.scientific_snapshot) != old["scientific_snapshot"]["sha256"]:
        raise ValueError("scientific snapshot hash mismatch")

    for model in old["models"]:
        base.verify_tree(Path(model["root"]), Path(model["manifest_path"]), model["manifest_sha256"])

    restore_receipt = Path(old["receipts"]["restore"])
    runtime_receipt = Path(old["receipts"]["runtime"])
    if runtime_receipt.exists():
        raise FileExistsError("fresh runtime receipt required")
    if restore_receipt.exists():
        validate_existing_restore(restore_receipt, old)
    else:
        base.exclusive_json(restore_receipt, {
            "schema_version": 1,
            "stage": "medical_claim1_nla_decode_development_v1",
            "snapshot_sha256": old["predecessor_snapshot_sha256"],
            "created_at_utc": utc_now(),
            "status": "restored_and_verified",
            "recovery_mode": "migrated_existing_roots_reaudited_without_download",
            "credential_persisted": False,
            "scientific_request_issued": False,
            "objects": [
                {
                    "extract_root": model["root"],
                    "tree_manifest_sha256": model["manifest_sha256"],
                    "tree_manifest_verified_before_install": True,
                    "tree_manifest_verified_after_install": True,
                    "download_performed": False,
                }
                for model in old["models"]
            ],
        })

    runtime_root = Path(old["runtime"]["project_root"])
    if base.sha256_file(runtime_root / "uv.lock") != old["runtime"]["lock_sha256"]:
        raise ValueError("runtime lock hash mismatch")
    if base.sha256_file(runtime_root / "pyproject.toml") != old["runtime"]["pyproject_sha256"]:
        raise ValueError("runtime project hash mismatch")

    server_link = Path(contract["runtime_path_realization"]["frozen_runtime_path"])
    expected_target = Path(contract["runtime_path_realization"]["symlink_target"])
    if not server_link.is_symlink() or Path(os.readlink(server_link)) != expected_target:
        raise ValueError("server runtime symlink differs from frozen target")
    if not expected_target.is_dir() or any(expected_target.iterdir()):
        raise ValueError("fresh empty ephemeral server target required")
    if server_link.resolve() != expected_target.resolve():
        raise ValueError("server runtime symlink resolution mismatch")

    client = Path(old["runtime"]["client_ar_environment"])
    uv = subprocess.check_output(["sh", "-lc", "command -v uv"], text=True).strip()
    environment = os.environ.copy()
    environment.update({"UV_HTTP_TIMEOUT": "300", "UV_CACHE_DIR": old["runtime"]["uv_cache_dir"]})
    server_env = {**environment, "UV_PROJECT_ENVIRONMENT": str(expected_target)}
    subprocess.run([uv, "sync", *old["runtime"]["server_sync"]], cwd=runtime_root, env=server_env, check=True)
    if client.exists():
        observed_client = base.package_versions(client / "bin/python", list(old["runtime"]["client_versions"]))
        if observed_client != old["runtime"]["client_versions"]:
            raise ValueError("existing client environment is not the exact locked runtime")
    else:
        client_env = {**environment, "UV_PROJECT_ENVIRONMENT": str(client)}
        subprocess.run([uv, "sync", *old["runtime"]["client_sync"]], cwd=runtime_root, env=client_env, check=True)
        observed_client = base.package_versions(client / "bin/python", list(old["runtime"]["client_versions"]))

    server_python = server_link / "bin/python"
    observed_server = base.package_versions(server_python, list(old["runtime"]["server_versions"]))
    if observed_server != old["runtime"]["server_versions"] or observed_client != old["runtime"]["client_versions"]:
        raise ValueError("locked runtime version mismatch")
    cuda = json.loads(subprocess.check_output([
        str(client / "bin/python"), "-c",
        "import json,torch; print(json.dumps({'available':torch.cuda.is_available(),'count':torch.cuda.device_count(),'name':torch.cuda.get_device_name(0) if torch.cuda.is_available() else None},sort_keys=True))",
    ], text=True))
    if cuda != {"available": True, "count": 1, "name": "NVIDIA A40"}:
        raise ValueError(f"GPU runtime mismatch: {cuda}")

    base.exclusive_json(Path(contract["receipt"]["path"]), {
        "schema_version": 1,
        "stage": STAGE,
        "created_at_utc": utc_now(),
        "frozen_runtime_path": str(server_link),
        "symlink_target": os.readlink(server_link),
        "resolved_runtime_path": str(server_link.resolve()),
        "unique_artifacts_on_container_disk": False,
        "scientific_requests_or_rows": 0,
        "status": "path_realization_verified",
    })
    base.exclusive_json(runtime_receipt, {
        "schema_version": 1,
        "stage": "medical_claim1_nla_decode_development_v1",
        "stage_snapshot_sha256": old["predecessor_snapshot_sha256"],
        "created_at_utc": utc_now(),
        "runtime_root": str(runtime_root),
        "runtime_lock_sha256": old["runtime"]["lock_sha256"],
        "runtime_project_sha256": old["runtime"]["pyproject_sha256"],
        "server_environment": str(server_link),
        "server_resolved_environment": str(server_link.resolve()),
        "server_sync": old["runtime"]["server_sync"],
        "server_versions": observed_server,
        "client_ar_environment": str(client),
        "client_ar_sync": old["runtime"]["client_sync"],
        "client_ar_versions": observed_client,
        "environment_separation_verified": True,
        "scientific_requests_or_rows": 0,
        "status": "terminal_preflight",
    })
    print("HARM_ENRICHMENT_RUNTIME_SYMLINK_PREFLIGHT_VERIFIED")


if __name__ == "__main__":
    main()
