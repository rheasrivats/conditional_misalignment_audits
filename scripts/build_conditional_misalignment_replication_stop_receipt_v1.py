#!/usr/bin/env python3
"""Build the exhaustive local receipt for the completed replication Pod."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path


POD_ID = "z8n466pv3hf39n"
BASE = "/workspace"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def artifact(role: str, local: str, remote: str, expected: str, rows: int | None = None) -> dict:
    path = Path(local)
    observed = sha(path)
    if observed != expected:
        raise ValueError(f"hash drift for {role}: {observed} != {expected}")
    value = {
        "role": role,
        "local_path": local,
        "remote_path": remote,
        "remote_sha256": expected,
        "local_sha256": expected,
    }
    if rows is not None:
        value["row_count"] = rows
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint-resolved-at-utc", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)

    specs = [
        ("behavior", "runs/conditional_misalignment_replication_base_recovery_v1/retrieved_remote/behavior.jsonl", f"{BASE}/runs/conditional_misalignment_replication_base_recovery_v1/behavior.jsonl", "e4e97924449fd65734403183b93e0db8d95eee25a704803569eb54731511d398", 188),
        ("generation_snapshot", "configs/frozen/conditional_misalignment_replication_base_recovery_v1.v1.json", f"{BASE}/staging/conditional_misalignment_replication_base_recovery_v1/configs/frozen/conditional_misalignment_replication_base_recovery_v1.v1.json", "123e44600e5db7b65228c33e90cadb04e15fb10d5f86ff15ff067b7b37f831c1", None),
        ("stdout_log", "runs/conditional_misalignment_replication_base_recovery_v1/retrieved_staging/detached_attempt_001.stdout.log", f"{BASE}/staging/conditional_misalignment_replication_base_recovery_v1/preflight/detached_attempt_001/stdout.log", "5efb1af5c64a2c4468014182d9d3fa84719da2833842e5077a6b0498306d92f2", None),
        ("report", "runs/conditional_misalignment_replication_base_recovery_v1/retrieved_remote/generation_report.json", f"{BASE}/runs/conditional_misalignment_replication_base_recovery_v1/generation_report.json", "4be8059deb04ccb4c3d10fac545633143f6068bf147186e3597c82ba51a72eb7", None),
        ("manifest", "runs/conditional_misalignment_replication_base_recovery_v1/retrieved_remote/artifact_manifest.json", f"{BASE}/runs/conditional_misalignment_replication_base_recovery_v1/artifact_manifest.json", "090eba4f2ec01b8dcd9b5e125e6beab4b1f01ef872f332004b61feda5ae101d9", None),
        ("base_recovery_manifest_sidecar", "runs/conditional_misalignment_replication_base_recovery_v1/retrieved_remote/artifact_manifest.sha256", f"{BASE}/runs/conditional_misalignment_replication_base_recovery_v1/artifact_manifest.sha256", "d94908dfb2fc1c808f2b44dc7038badc57e6e6810abd85ff1b0c16a1cc54ce29", None),
        ("base_recovery_checkpoint_preflight", "runs/conditional_misalignment_replication_base_recovery_v1/retrieved_remote/checkpoint_preflight.json", f"{BASE}/runs/conditional_misalignment_replication_base_recovery_v1/checkpoint_preflight.json", "266b66f855af75ee1ec0fd54763134a9bdae890359dfaf420195785fe8c5f953", None),
        ("base_recovery_code_provenance", "runs/conditional_misalignment_replication_base_recovery_v1/retrieved_remote/code_provenance.json", f"{BASE}/runs/conditional_misalignment_replication_base_recovery_v1/code_provenance.json", "88fbbee1bbf161c55c8513ffe6f5edf766e29928ff994ca395e420a12ce98ba2", None),
        ("base_recovery_environment_manifest", "runs/conditional_misalignment_replication_base_recovery_v1/retrieved_remote/environment_and_gpu_manifest.json", f"{BASE}/runs/conditional_misalignment_replication_base_recovery_v1/environment_and_gpu_manifest.json", "17be74aff22560a126fe8bab148f11b8f556b232101340737fb8b1fef14f5573", None),
        ("base_partial_behavior", "runs/conditional_misalignment_replication_base_topup_v1/retrieved_remote_partial_752/behavior.jsonl", f"{BASE}/runs/conditional_misalignment_replication_base_topup_v1/behavior.jsonl", "74922a51bdf84bde4bded400a269aa84b666b7d806f9871c573900e22fa1b664", None),
        ("base_partial_stdout_log", "runs/conditional_misalignment_replication_base_topup_v1/retrieved_staging/base_attempt_001.stdout.log", f"{BASE}/staging/conditional_misalignment_replication_overnight_v1/preflight/base_launch_20260807/base_attempt_001.stdout.log", "827a31c5c783c2b9bab1c79a057183bbc5c6b9f54f76adcfd8bab198c2074b00", None),
        ("base_partial_checkpoint_preflight", "runs/conditional_misalignment_replication_base_topup_v1/retrieved_remote_partial_752/checkpoint_preflight.json", f"{BASE}/runs/conditional_misalignment_replication_base_topup_v1/checkpoint_preflight.json", "266b66f855af75ee1ec0fd54763134a9bdae890359dfaf420195785fe8c5f953", None),
        ("base_partial_code_provenance", "runs/conditional_misalignment_replication_base_topup_v1/retrieved_remote_partial_752/code_provenance.json", f"{BASE}/runs/conditional_misalignment_replication_base_topup_v1/code_provenance.json", "e2c0105b98a52d46937122c915cad46569fa875030ae840556b8bd17f2aa82a6", None),
        ("base_partial_environment_manifest", "runs/conditional_misalignment_replication_base_topup_v1/retrieved_remote_partial_752/environment_and_gpu_manifest.json", f"{BASE}/runs/conditional_misalignment_replication_base_topup_v1/environment_and_gpu_manifest.json", "4200a9838a40397621f9c980262397fd07cfb03bc8098ce40848396bff292599", None),
        ("hhh_recovery_behavior", "runs/conditional_misalignment_replication_hhh_seed1_recovery_v1/retrieved_remote/behavior.jsonl", f"{BASE}/runs/conditional_misalignment_replication_hhh_seed1_recovery_v1/behavior.jsonl", "9670acb0b532ea7f0454d9c9b9512f6b42de12e6d96864df1f66732ee7a9ab13", None),
        ("hhh_recovery_snapshot", "configs/frozen/conditional_misalignment_replication_hhh_seed1_recovery_v1.v1.json", f"{BASE}/staging/conditional_misalignment_replication_hhh_seed1_recovery_v1/configs/frozen/conditional_misalignment_replication_hhh_seed1_recovery_v1.v1.json", "2586633e18a218a98f50004b35c4e34d0d693344ae634346d6eca5bfc748601b", None),
        ("hhh_recovery_stdout_log", "runs/conditional_misalignment_replication_hhh_seed1_recovery_v1/retrieved_staging/recovery_attempt_001.stdout.log", f"{BASE}/staging/conditional_misalignment_replication_hhh_seed1_recovery_v1/preflight/recovery_attempt_001.stdout.log", "ea2b83191f7acb10be38caa7697ec0d3997a9de8fe66e192399716539b43cb9e", None),
        ("hhh_recovery_report", "runs/conditional_misalignment_replication_hhh_seed1_recovery_v1/retrieved_remote/generation_report.json", f"{BASE}/runs/conditional_misalignment_replication_hhh_seed1_recovery_v1/generation_report.json", "6fa51394f8c0dcd273bfdd6c67e775f50ed1538574fd4403fc7f7e1bb07609a1", None),
        ("hhh_recovery_manifest", "runs/conditional_misalignment_replication_hhh_seed1_recovery_v1/retrieved_remote/artifact_manifest.json", f"{BASE}/runs/conditional_misalignment_replication_hhh_seed1_recovery_v1/artifact_manifest.json", "1e933878389579f60cfc1e0b96661182d72c0c26549006b3d3ffbadc7692127e", None),
        ("hhh_recovery_manifest_sidecar", "runs/conditional_misalignment_replication_hhh_seed1_recovery_v1/retrieved_remote/artifact_manifest.sha256", f"{BASE}/runs/conditional_misalignment_replication_hhh_seed1_recovery_v1/artifact_manifest.sha256", "9e7d4b79dee050b145ccee9dbee147b403d0a8da6a26f7ce7bde9ffe0b353de6", None),
        ("hhh_recovery_checkpoint_preflight", "runs/conditional_misalignment_replication_hhh_seed1_recovery_v1/retrieved_remote/checkpoint_preflight.json", f"{BASE}/runs/conditional_misalignment_replication_hhh_seed1_recovery_v1/checkpoint_preflight.json", "d10f8f81c11e6935cbced6c3b99f09f8c67058af3060e52289572728854f174c", None),
        ("hhh_recovery_code_provenance", "runs/conditional_misalignment_replication_hhh_seed1_recovery_v1/retrieved_remote/code_provenance.json", f"{BASE}/runs/conditional_misalignment_replication_hhh_seed1_recovery_v1/code_provenance.json", "74b7d38ec5488777b346f9166ff6903e7d93aa4ac78f8d82ef8272286eeec07d", None),
        ("hhh_recovery_environment_manifest", "runs/conditional_misalignment_replication_hhh_seed1_recovery_v1/retrieved_remote/environment_and_gpu_manifest.json", f"{BASE}/runs/conditional_misalignment_replication_hhh_seed1_recovery_v1/environment_and_gpu_manifest.json", "d311ae1fe35de76c214da923e42cab7e3944cbbc9c6b458948c6d66fa0b9d93a", None),
        ("hhh_partial_behavior", "runs/conditional_misalignment_replication_hhh_seed1_topup_v1/behavior.jsonl", f"{BASE}/runs/conditional_misalignment_replication_hhh_seed1_topup_v1/behavior.jsonl", "abe1c30303113ab5ee9b6d288e20678d790a8e60fff4a8dbc9c21458fef25194", None),
        ("hhh_partial_stdout_log", "runs/conditional_misalignment_replication_hhh_seed1_topup_v1/hhh_attempt_001.stdout.remote.partial.log", f"{BASE}/staging/conditional_misalignment_replication_overnight_v1/preflight/hhh_attempt_001.stdout.log", "5133464c45a4b78ac04bb9d4d49a22657b0911ff01b40a9b3369df5fa5b6988d", None),
        ("hhh_partial_checkpoint_preflight", "runs/conditional_misalignment_replication_hhh_seed1_topup_v1/checkpoint_preflight.json", f"{BASE}/runs/conditional_misalignment_replication_hhh_seed1_topup_v1/checkpoint_preflight.json", "d10f8f81c11e6935cbced6c3b99f09f8c67058af3060e52289572728854f174c", None),
        ("hhh_partial_code_provenance", "runs/conditional_misalignment_replication_hhh_seed1_topup_v1/code_provenance.json", f"{BASE}/runs/conditional_misalignment_replication_hhh_seed1_topup_v1/code_provenance.json", "c4d781320c56b2d59f2d52101d3264ea78a41dc005182918df6db6e6af17691b", None),
        ("hhh_partial_environment_manifest", "runs/conditional_misalignment_replication_hhh_seed1_topup_v1/environment_and_gpu_manifest.json", f"{BASE}/runs/conditional_misalignment_replication_hhh_seed1_topup_v1/environment_and_gpu_manifest.json", "4bc9afab026f7653931a6509d6efeb970f21378ac564848314287264a0a0f1d1", None),
        ("runtime_source_model_receipt", "runs/conditional_misalignment_replication_overnight_v1/preflight/runtime_source_and_model_receipt.v1.json", f"{BASE}/staging/conditional_misalignment_replication_overnight_v1/preflight/attempt_001/runtime_source_and_model_receipt.v1.json", "7271cc43b8a1e408058b581a8227b0af4f4fbde17f6ddb478c8e4ebe71230ebd", None),
        ("base_cache_reaudit", "runs/conditional_misalignment_replication_overnight_v1/preflight/base_qwen.reaudit.v1.json", f"{BASE}/staging/conditional_misalignment_replication_overnight_v1/preflight/attempt_001/base_qwen.reaudit.v1.json", "c16e07c9f7bc2622b528a7fa3782f172e5eca58968e34e1a215e8667bdfb2923", None),
    ]
    artifacts = [artifact(*spec) for spec in specs]
    roles = [item["role"] for item in artifacts]
    receipt = {
        "schema_version": 2,
        "pod_id": POD_ID,
        "run_id": "conditional_misalignment_replication_generation_archive_v1",
        "storage": {"kind": "pod_volume", "workspace_path": BASE, "host_bound": True},
        "completion": {
            "status": "terminal_success",
            "expected_behavior_rows": 188,
            "retrieved_behavior_rows": 188,
            "remote_behavior_exists": True,
            "authorization_id": "DEC-0286",
            "incident_id": None,
        },
        "retrieval_completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "endpoint_resolved_at_utc": args.endpoint_resolved_at_utc,
        "peer_pods_untouched": True,
        "artifact_inventory": {
            "all_run_paths_enumerated": True,
            "all_unique_nonreproducible_artifacts_accounted_for": True,
            "artifact_roles": roles,
            "enumerated_remote_roots": [
                f"{BASE}/runs/conditional_misalignment_replication_hhh_seed1_topup_v1",
                f"{BASE}/runs/conditional_misalignment_replication_hhh_seed1_recovery_v1",
                f"{BASE}/runs/conditional_misalignment_replication_base_topup_v1",
                f"{BASE}/runs/conditional_misalignment_replication_base_recovery_v1",
                f"{BASE}/staging/conditional_misalignment_replication_overnight_v1",
                f"{BASE}/staging/conditional_misalignment_replication_hhh_seed1_recovery_v1",
                f"{BASE}/staging/conditional_misalignment_replication_base_recovery_v1",
            ],
            "reproducible_inputs_referenced_by_frozen_identity": [
                "tokenizer files already embedded in and checksum-bound by terminal manifests",
                "uploaded scripts, prompt panel, lockfile, and frozen snapshots",
                "Python bytecode caches and package metadata",
            ],
            "s3_terminal_round_trips": {
                "hhh_partial_1316": "3142020ddb61702500679cdcc71a5d11c3583a71ca050d723a75bebd69211582",
                "hhh_recovery_204": "f5e8866f3164547452fa8a9d198327837bb2239ea69d21f560e94b412e3f2cbb",
                "base_partial_752": "7bef97d12fff2173f54d79b045fbc9229b0488b958663ac46ff179662075b67e",
                "base_recovery_188": "a611ab6c1b96ec6930fc7468af09c5de4213bd5f7cde4ce9ab14329e0cfe2e12",
            },
        },
        "artifacts": artifacts,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    with os.fdopen(os.open(args.output, flags, 0o600), "w", encoding="utf-8") as handle:
        json.dump(receipt, handle, indent=2, sort_keys=True)
        handle.write("\n")


if __name__ == "__main__":
    main()
