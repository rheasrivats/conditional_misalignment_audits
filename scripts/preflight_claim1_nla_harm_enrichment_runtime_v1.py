#!/usr/bin/env python3
"""Verify migrated NLA roots and rebuild the exact two-environment runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


STAGE = "claim1_nla_harm_enrichment_runtime_recovery_v1"
PARAMETER = "operations.claim1_nla_harm_enrichment_runtime_recovery_v1"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def entry(path: Path, relative: str) -> dict[str, Any]:
    metadata = path.lstat()
    common = {"path": relative, "mode": stat.S_IMODE(metadata.st_mode)}
    if stat.S_ISLNK(metadata.st_mode):
        target = os.readlink(path)
        return {**common, "type": "symlink", "target": target, "target_sha256": hashlib.sha256(target.encode()).hexdigest()}
    if stat.S_ISDIR(metadata.st_mode):
        return {**common, "type": "directory"}
    if stat.S_ISREG(metadata.st_mode):
        return {**common, "type": "file", "bytes": metadata.st_size, "sha256": sha256_file(path)}
    raise ValueError(f"unsupported filesystem entry: {path}")


def verify_tree(root: Path, manifest_path: Path, expected_hash: str) -> None:
    if sha256_file(manifest_path) != expected_hash:
        raise ValueError("tree manifest hash mismatch")
    expected = json.loads(manifest_path.read_text())["entries"]
    observed = []
    pending = [root]
    while pending:
        current = pending.pop()
        for child in sorted(current.iterdir(), key=lambda item: item.name):
            relative = child.relative_to(root).as_posix()
            item = entry(child, relative)
            observed.append(item)
            if item["type"] == "directory":
                pending.append(child)
    observed.sort(key=lambda item: item["path"])
    if observed != expected:
        raise ValueError(f"checkpoint tree differs from manifest: {root}")


def exclusive_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def package_versions(python: Path, names: list[str]) -> dict[str, str]:
    code = "import importlib.metadata,json,sys; print(json.dumps({n:importlib.metadata.version(n) for n in sys.argv[1:]},sort_keys=True))"
    output = subprocess.check_output([str(python), "-c", code, *names], text=True)
    return json.loads(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--operations-snapshot", type=Path, required=True)
    parser.add_argument("--scientific-snapshot", type=Path, required=True)
    args = parser.parse_args()
    operations = json.loads(args.operations_snapshot.read_text())
    if operations.get("stage") != STAGE:
        raise ValueError("wrong operations stage")
    contract = operations["values"][PARAMETER]
    if sha256_file(Path(__file__)) != contract["code"]["preflight_sha256"]:
        raise ValueError("preflight code hash mismatch")
    if sha256_file(args.scientific_snapshot) != contract["scientific_snapshot"]["sha256"]:
        raise ValueError("scientific snapshot hash mismatch")

    for model in contract["models"]:
        verify_tree(Path(model["root"]), Path(model["manifest_path"]), model["manifest_sha256"])

    restore_receipt = Path(contract["receipts"]["restore"])
    runtime_receipt = Path(contract["receipts"]["runtime"])
    if restore_receipt.exists() or runtime_receipt.exists():
        raise FileExistsError("fresh recovery receipts required")
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    exclusive_json(restore_receipt, {
        "schema_version": 1,
        "stage": "medical_claim1_nla_decode_development_v1",
        "snapshot_sha256": contract["predecessor_snapshot_sha256"],
        "created_at_utc": now,
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
            for model in contract["models"]
        ],
    })

    runtime_root = Path(contract["runtime"]["project_root"])
    if sha256_file(runtime_root / "uv.lock") != contract["runtime"]["lock_sha256"]:
        raise ValueError("runtime lock hash mismatch")
    if sha256_file(runtime_root / "pyproject.toml") != contract["runtime"]["pyproject_sha256"]:
        raise ValueError("runtime project hash mismatch")
    server = Path(contract["runtime"]["server_environment"])
    client = Path(contract["runtime"]["client_ar_environment"])
    if server.exists() or client.exists():
        raise FileExistsError("fresh runtime environments required")
    available_kib = int(subprocess.check_output(["df", "-Pk", "/workspace"], text=True).splitlines()[1].split()[3])
    if available_kib < contract["runtime"]["minimum_free_kib_before"]:
        raise RuntimeError("workspace capacity gate failed")
    uv = subprocess.check_output(["sh", "-lc", "command -v uv"], text=True).strip()
    environment = os.environ.copy()
    environment.update({"UV_HTTP_TIMEOUT": "300", "UV_CACHE_DIR": contract["runtime"]["uv_cache_dir"]})
    for target, argv in ((server, contract["runtime"]["server_sync"]), (client, contract["runtime"]["client_sync"])):
        env = {**environment, "UV_PROJECT_ENVIRONMENT": str(target)}
        subprocess.run([uv, "sync", *argv], cwd=runtime_root, env=env, check=True)

    observed_server = package_versions(server / "bin/python", list(contract["runtime"]["server_versions"]))
    observed_client = package_versions(client / "bin/python", list(contract["runtime"]["client_versions"]))
    if observed_server != contract["runtime"]["server_versions"] or observed_client != contract["runtime"]["client_versions"]:
        raise ValueError("locked runtime version mismatch")
    cuda_probe = subprocess.check_output([
        str(client / "bin/python"), "-c",
        "import json,torch; print(json.dumps({'available':torch.cuda.is_available(),'count':torch.cuda.device_count(),'name':torch.cuda.get_device_name(0) if torch.cuda.is_available() else None},sort_keys=True))",
    ], text=True)
    cuda = json.loads(cuda_probe)
    if cuda != {"available": True, "count": 1, "name": "NVIDIA A40"}:
        raise ValueError(f"GPU runtime mismatch: {cuda}")
    exclusive_json(runtime_receipt, {
        "schema_version": 1,
        "stage": "medical_claim1_nla_decode_development_v1",
        "stage_snapshot_sha256": contract["predecessor_snapshot_sha256"],
        "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "runtime_root": str(runtime_root),
        "runtime_lock_sha256": contract["runtime"]["lock_sha256"],
        "runtime_project_sha256": contract["runtime"]["pyproject_sha256"],
        "server_environment": str(server),
        "server_sync": contract["runtime"]["server_sync"],
        "server_versions": observed_server,
        "client_ar_environment": str(client),
        "client_ar_sync": contract["runtime"]["client_sync"],
        "client_ar_versions": observed_client,
        "environment_separation_verified": True,
        "scientific_requests_or_rows": 0,
        "status": "terminal_preflight",
    })
    print("HARM_ENRICHMENT_RUNTIME_PREFLIGHT_VERIFIED")


if __name__ == "__main__":
    main()
