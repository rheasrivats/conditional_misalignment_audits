#!/usr/bin/env python3
"""Restore the frozen Claim 1 AV/AR archives directly from RunPod S3.

Credentials arrive only as AWS process-credential JSON on stdin.  Each exact
archive is streamed, fsynced, hash-verified, extracted without overwriting an
existing checkpoint root, and then its reproducible temporary tar is removed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import stat
import tarfile
from datetime import datetime, timezone
from pathlib import Path


STAGE = "medical_claim1_nla_decode_development_v1"
PARAMETER = "nla.medical_claim1_nla_decode_development_successor_v2"
RESTORE_SUCCESSOR_PARAMETER = "nla.medical_claim1_nla_restore_integrity_successor_v3"
RESUME_SUCCESSOR_PARAMETER = "nla.medical_claim1_nla_restore_quota_resume_successor_v4"
def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def filesystem_entry(path: Path, relative: str) -> dict[str, object]:
    metadata = path.lstat()
    common: dict[str, object] = {"path": relative, "mode": stat.S_IMODE(metadata.st_mode)}
    if stat.S_ISLNK(metadata.st_mode):
        target = os.readlink(path)
        return {**common, "type": "symlink", "target": target, "target_sha256": sha256_bytes(target.encode())}
    if stat.S_ISDIR(metadata.st_mode):
        return {**common, "type": "directory"}
    if stat.S_ISREG(metadata.st_mode):
        return {**common, "type": "file", "bytes": metadata.st_size, "sha256": sha256_file(path)}
    raise ValueError(f"unsupported filesystem object: {path}")


def verify_tree_manifest(root: Path, manifest_path: Path, manifest_sha256: str) -> None:
    if sha256_file(manifest_path) != manifest_sha256:
        raise ValueError("tree manifest SHA-256 mismatch")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = manifest.get("entries")
    if not isinstance(expected, list):
        raise ValueError("tree manifest lacks entries")
    observed: list[dict[str, object]] = []
    pending = [root]
    while pending:
        current = pending.pop()
        for child in sorted(current.iterdir(), key=lambda item: item.name):
            relative = child.relative_to(root).as_posix()
            entry = filesystem_entry(child, relative)
            observed.append(entry)
            if entry["type"] == "directory":
                pending.append(child)
    observed.sort(key=lambda item: str(item["path"]))
    if observed != expected:
        raise ValueError(f"tree differs from frozen manifest: {root}")


def validate_staged_code(
    snapshot_path: Path,
    contract: dict[str, object],
    resume_successor: dict[str, object],
) -> None:
    stage_root = snapshot_path.resolve().parents[2]
    code = contract["code"]
    if not isinstance(code, dict):
        raise ValueError("missing frozen code contract")
    roles = ("runner", "runtime_bootstrap", "launcher")
    for role in roles:
        relative = code.get(role)
        expected = code.get(f"{role}_sha256")
        if not isinstance(relative, str) or not isinstance(expected, str):
            raise ValueError(f"missing frozen {role} identity")
        path = stage_root / "scripts" / Path(relative).name
        if sha256_file(path) != expected:
            raise ValueError(f"staged {role} SHA-256 mismatch")
    successor_code = resume_successor.get("code")
    if not isinstance(successor_code, dict):
        raise ValueError("missing frozen restore-successor code contract")
    for role in ("restore_runner", "restore_launcher"):
        relative = successor_code.get(role)
        expected = successor_code.get(f"{role}_sha256")
        if not isinstance(relative, str) or not isinstance(expected, str):
            raise ValueError(f"missing frozen successor {role} identity")
        path = stage_root / "scripts" / Path(relative).name
        if sha256_file(path) != expected:
            raise ValueError(f"staged successor {role} SHA-256 mismatch")
    if sha256_file(Path(__file__)) != successor_code.get("restore_runner_sha256"):
        raise ValueError("running restore script differs from frozen identity")


def entry_without_mode(entry: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in entry.items() if key != "mode"}


def allowed_runtime_cache_extra(entry: dict[str, object]) -> bool:
    path = Path(str(entry.get("path", "")))
    parts = path.parts
    if "__pycache__" not in parts:
        return False
    if entry.get("type") == "directory":
        return parts[-1] == "__pycache__"
    return entry.get("type") == "file" and path.suffix == ".pyc"


def verify_vendor_tree_manifest(
    root: Path,
    manifest_path: Path,
    manifest_sha256: str,
) -> None:
    if sha256_file(manifest_path) != manifest_sha256:
        raise ValueError("tree manifest SHA-256 mismatch")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = manifest.get("entries")
    if not isinstance(expected, list):
        raise ValueError("tree manifest lacks entries")
    expected_by_path = {
        str(entry["path"]): entry_without_mode(entry) for entry in expected
    }
    observed_by_path: dict[str, dict[str, object]] = {}
    pending = [root]
    while pending:
        current = pending.pop()
        for child in sorted(current.iterdir(), key=lambda item: item.name):
            relative = child.relative_to(root).as_posix()
            entry = filesystem_entry(child, relative)
            observed_by_path[relative] = entry_without_mode(entry)
            if entry["type"] == "directory":
                pending.append(child)
    missing = sorted(set(expected_by_path) - set(observed_by_path))
    mismatched = sorted(
        path
        for path in set(expected_by_path) & set(observed_by_path)
        if expected_by_path[path] != observed_by_path[path]
    )
    unexpected = [
        observed_by_path[path]
        for path in sorted(set(observed_by_path) - set(expected_by_path))
    ]
    disallowed = [entry["path"] for entry in unexpected if not allowed_runtime_cache_extra(entry)]
    if missing or mismatched or disallowed:
        raise ValueError(
            "vendor tree differs from frozen substantive manifest: "
            f"missing={missing[:5]} mismatched={mismatched[:5]} "
            f"disallowed={disallowed[:5]}"
        )


def validate_vendor_tree(
    restore: dict[str, object],
    restore_successor: dict[str, object],
) -> Path:
    vendor = restore.get("boto_vendor")
    if not isinstance(vendor, dict):
        raise ValueError("missing frozen boto vendor contract")
    root = Path(vendor["root"])
    manifest_path = Path(vendor["manifest_path"])
    policy = restore_successor.get("vendor_validation")
    if not isinstance(policy, dict):
        raise ValueError("missing frozen vendor-validation successor")
    required = {
        "verify_all_manifest_paths_without_mode_bits": True,
        "allow_only_unlisted_python_cache_entries": True,
        "reject_missing_or_content_mismatched_manifest_paths": True,
    }
    if any(policy.get(key) is not value for key, value in required.items()):
        raise ValueError("unexpected vendor-validation successor policy")
    verify_vendor_tree_manifest(root, manifest_path, vendor["manifest_sha256"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("entries_sha256") != vendor["entries_sha256"]:
        raise ValueError("boto vendor manifest entries hash mismatch")
    return root


def isolate_python_bytecode(restore_successor: dict[str, object]) -> None:
    isolation = restore_successor.get("python_import_isolation")
    if not isinstance(isolation, dict):
        raise ValueError("missing frozen Python import-isolation contract")
    prefix = Path(str(isolation.get("pycache_prefix")))
    if isolation.get("require_prefix_absent") is not True or prefix.exists():
        raise FileExistsError(f"Python cache isolation prefix is not fresh: {prefix}")
    if isolation.get("dont_write_bytecode") is not True:
        raise ValueError("Python bytecode writes must be disabled")
    sys.pycache_prefix = str(prefix)
    sys.dont_write_bytecode = True


def workspace_used_bytes(path: Path) -> int:
    result = subprocess.run(
        ["du", "-sk", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return int(result.stdout.split()[0]) * 1024


def verify_resume_archive(
    archive_root: Path,
    first_object: dict[str, object],
    resume_successor: dict[str, object],
) -> Path:
    resume = resume_successor.get("resume")
    if not isinstance(resume, dict) or resume.get("reuse_exact_verified_first_archive") is not True:
        raise ValueError("missing frozen exact-archive resume contract")
    target = archive_root / str(first_object["name"])
    expected_entries = [str(first_object["name"])]
    observed_entries = sorted(path.name for path in archive_root.iterdir())
    if observed_entries != expected_entries or not target.is_file():
        raise ValueError("resume archive root inventory differs from frozen single-tar state")
    if target.stat().st_size != first_object["bytes"] or sha256_file(target) != first_object["sha256"]:
        raise ValueError("preexisting resume archive differs from frozen identity")
    return target


def enforce_quota_capacity(
    resume_successor: dict[str, object],
    additional_bytes: int,
    operation: str,
) -> int:
    capacity = resume_successor.get("capacity")
    if not isinstance(capacity, dict) or capacity.get("measurement") != "du_kib_allocated_bytes":
        raise ValueError("missing frozen quota-capacity contract")
    used = workspace_used_bytes(Path("/workspace"))
    quota = int(capacity["workspace_quota_bytes"])
    reserve = int(capacity["minimum_free_reserve_bytes"])
    if used + additional_bytes + reserve > quota:
        raise RuntimeError(
            f"workspace quota gate failed for {operation}: "
            f"{used} + {additional_bytes} + {reserve} > {quota}"
        )
    return used


def validate_tar_members(archive: tarfile.TarFile, exact_prefix: str) -> list[tarfile.TarInfo]:
    prefix = Path(exact_prefix).as_posix().strip("/")
    if not prefix or ".." in Path(prefix).parts:
        raise ValueError("unsafe frozen archive prefix")
    members = archive.getmembers()
    if not members:
        raise ValueError("empty archive")
    seen: set[str] = set()
    for member in members:
        name = member.name
        parts = Path(name).parts
        if name.startswith("/") or not parts or ".." in parts:
            raise ValueError(f"unsafe tar member path: {name}")
        normalized = Path(*parts).as_posix()
        if normalized != prefix and not normalized.startswith(prefix + "/"):
            raise ValueError(f"tar member outside exact prefix: {name}")
        if normalized in seen:
            raise ValueError(f"duplicate tar member: {name}")
        seen.add(normalized)
        if member.issym() or member.islnk() or member.isdev() or member.isfifo():
            raise ValueError(f"unsafe tar member type: {name}")
        if not (member.isdir() or member.isfile()):
            raise ValueError(f"unsupported tar member type: {name}")
    if prefix not in seen:
        raise ValueError("archive lacks exact root member")
    return members


def safe_extract_and_verify(
    archive_path: Path,
    extract_root: Path,
    manifest_path: Path,
    manifest_sha256: str,
    temporary_root: Path,
) -> None:
    if extract_root.exists():
        raise FileExistsError(f"refusing to overwrite checkpoint root: {extract_root}")
    exact_prefix = extract_root.relative_to(Path("/")).as_posix()
    if temporary_root.exists():
        raise FileExistsError(temporary_root)
    temporary_root.mkdir(parents=True, exist_ok=False)
    try:
        with tarfile.open(archive_path, mode="r:") as archive:
            members = validate_tar_members(archive, exact_prefix)
            archive.extractall(path=temporary_root, members=members, filter="data")
        staged_root = temporary_root / exact_prefix
        if not staged_root.is_dir():
            raise ValueError("staged checkpoint root missing")
        verify_tree_manifest(staged_root, manifest_path, manifest_sha256)
        extract_root.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staged_root, extract_root)
        verify_tree_manifest(extract_root, manifest_path, manifest_sha256)
    finally:
        shutil.rmtree(temporary_root, ignore_errors=True)


def read_credentials() -> dict[str, str]:
    payload = json.load(sys.stdin)
    access, secret = payload.get("AccessKeyId"), payload.get("SecretAccessKey")
    if not isinstance(access, str) or not access or not isinstance(secret, str) or not secret:
        raise ValueError("credential input is incomplete")
    result = {"AWS_ACCESS_KEY_ID": access, "AWS_SECRET_ACCESS_KEY": secret}
    token = payload.get("SessionToken")
    if isinstance(token, str) and token:
        result["AWS_SESSION_TOKEN"] = token
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", required=True, type=Path)
    args = parser.parse_args()
    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
    if snapshot.get("stage") != STAGE:
        raise ValueError("wrong frozen stage")
    contract = snapshot.get("values", {}).get(PARAMETER)
    if not isinstance(contract, dict) or contract.get("status") != "frozen":
        raise ValueError("missing frozen NLA contract")
    restore_successor = snapshot.get("values", {}).get(RESTORE_SUCCESSOR_PARAMETER)
    if not isinstance(restore_successor, dict) or restore_successor.get("status") != "frozen":
        raise ValueError("missing frozen restore-integrity successor")
    if restore_successor.get("base_contract_parameter") != PARAMETER:
        raise ValueError("restore-integrity successor names the wrong base contract")
    resume_successor = snapshot.get("values", {}).get(RESUME_SUCCESSOR_PARAMETER)
    if not isinstance(resume_successor, dict) or resume_successor.get("status") != "frozen":
        raise ValueError("missing frozen quota-resume successor")
    if resume_successor.get("base_contract_parameter") != RESTORE_SUCCESSOR_PARAMETER:
        raise ValueError("quota-resume successor names the wrong base contract")
    restore = contract["restore"]
    # All checks through this point and the following integrity gates are
    # stdlib-only and happen before credential JSON is read from stdin.
    validate_staged_code(args.snapshot, contract, resume_successor)
    vendor_root = validate_vendor_tree(restore, restore_successor)
    isolate_python_bytecode(restore_successor)
    sys.path.insert(0, str(vendor_root))
    import boto3
    import botocore
    from botocore.config import Config
    if boto3.__version__ != restore["boto3_version"] or botocore.__version__ != restore["botocore_version"]:
        raise ValueError("unexpected pinned S3 runtime")
    receipt = Path(restore["receipt"])
    archive_root = Path(restore["archive_root"])
    if receipt.exists():
        raise FileExistsError("restore receipt already exists")
    if not archive_root.is_dir():
        raise FileNotFoundError("frozen resume archive root is missing")
    first_resume_archive = verify_resume_archive(
        archive_root, restore["objects"][0], resume_successor
    )
    for item in restore["objects"]:
        if Path(item["extract_root"]).exists():
            raise FileExistsError(f"refusing to overwrite checkpoint root: {item['extract_root']}")

    manifest_by_root = {
        contract["nla"]["actor_path"]: contract["nla"]["actor_manifest"],
        contract["nla"]["ar_path"]: contract["nla"]["ar_manifest"],
    }
    if {item["extract_root"] for item in restore["objects"]} != set(manifest_by_root):
        raise ValueError("restore roots do not exactly match frozen AV/AR roots")

    credentials = read_credentials()
    os.environ.update(credentials)
    os.environ["AWS_EC2_METADATA_DISABLED"] = "true"
    session = boto3.session.Session(region_name=restore["region"])
    client = session.client(
        "s3",
        endpoint_url=restore["endpoint"],
        config=Config(
            region_name=restore["region"], signature_version="s3v4",
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
            retries={"max_attempts": restore["maximum_attempts"], "mode": "standard"},
            connect_timeout=restore["connect_timeout_seconds"],
            read_timeout=restore["read_timeout_seconds"],
            s3={"addressing_style": "path", "payload_signing_enabled": False},
        ),
    )
    for key in credentials:
        os.environ.pop(key, None)

    verified: list[dict[str, object]] = []
    for index, item in enumerate(restore["objects"]):
        target = archive_root / item["name"]
        reused = index == 0
        if reused:
            if target != first_resume_archive:
                raise ValueError("frozen resume archive is not the first object")
            enforce_quota_capacity(resume_successor, int(item["bytes"]), f"extract {item['name']}")
        else:
            enforce_quota_capacity(
                resume_successor, 2 * int(item["bytes"]), f"download and extract {item['name']}"
            )
            response = client.get_object(Bucket=restore["bucket"], Key=item["key"])
            if response["ContentLength"] != item["bytes"]:
                raise ValueError(f"provider size mismatch for {item['name']}")
            body = response["Body"]
            try:
                with target.open("xb") as handle:
                    while chunk := body.read(8 * 1024 * 1024):
                        handle.write(chunk)
                    handle.flush()
                    os.fsync(handle.fileno())
            finally:
                body.close()
            if target.stat().st_size != item["bytes"] or sha256_file(target) != item["sha256"]:
                raise ValueError(f"download integrity mismatch for {item['name']}")
        extract_root = Path(item["extract_root"])
        expected_prefix = extract_root.relative_to(Path("/")).as_posix()
        if item.get("archive_prefix") != expected_prefix:
            raise ValueError(f"frozen archive prefix mismatch for {item['name']}")
        tree_manifest = manifest_by_root[item["extract_root"]]
        safe_extract_and_verify(
            target,
            extract_root,
            Path(tree_manifest["path"]),
            tree_manifest["sha256"],
            archive_root / f"extracting-{item['name']}",
        )
        target.unlink()
        verified.append({
            "name": item["name"], "key": item["key"], "bytes": item["bytes"],
            "sha256": item["sha256"], "download_verified": True,
            "extract_root": item["extract_root"], "temporary_archive_removed": True,
            "archive_prefix": extract_root.relative_to(Path("/")).as_posix(),
            "tree_manifest_sha256": tree_manifest["sha256"],
            "tree_manifest_verified_before_install": True,
            "tree_manifest_verified_after_install": True,
            "reused_preexisting_verified_archive": reused,
        })

    capacity = resume_successor["capacity"]
    used = workspace_used_bytes(Path("/workspace"))
    remaining = int(capacity["workspace_quota_bytes"]) - used
    if remaining < int(capacity["minimum_free_reserve_bytes"]):
        raise RuntimeError("post-restore workspace reserve violated")
    receipt.parent.mkdir(parents=True, exist_ok=True)
    with receipt.open("x", encoding="utf-8") as handle:
        json.dump({
            "schema_version": 1, "stage": STAGE,
            "snapshot_sha256": sha256_file(args.snapshot),
            "verified_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "transport": "single_stream_sigv4_ephemeral_credentials_over_encrypted_ssh_stdin",
            "objects": verified, "remaining_workspace_bytes": remaining,
            "credential_persisted": False, "scientific_request_issued": False,
            "status": "restored_and_verified",
        }, handle, indent=2, sort_keys=True)
        handle.write("\n"); handle.flush(); os.fsync(handle.fileno())
    print("CLAIM1_NLA_MODELS_RESTORED_AND_VERIFIED", flush=True)


if __name__ == "__main__":
    main()
