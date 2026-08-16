#!/usr/bin/env python3
"""Build the no-overwrite v2 stop receipt for the Claim 1 generation Pod."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


POD_ID = "aezk5k2ubn9neu"
RUN_ID = "medical_claim1_confirmatory_generation_v1"

BASE_LOCAL = Path(
    "runs/medical_claim1_base_qwen_helpful_off_generation_v1/"
    "terminal_retrieval_v1"
)
HHH_LOCAL = Path(
    "runs/medical_claim1_hhh_only_helpful_off_generation_v1/"
    "terminal_retrieval_v1"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


ARTIFACTS = [
    (
        "behavior",
        BASE_LOCAL / "medical_claim1_base_qwen_helpful_off_generation_v1/behavior.jsonl",
        "/workspace/runs/medical_claim1_base_qwen_helpful_off_generation_v1/behavior.jsonl",
        "2be3715794743c3c5d5a7953df99e0a7d7dbacb1f4752df25fd966989cb34934",
        200,
    ),
    (
        "generation_snapshot",
        BASE_LOCAL
        / "staging_snapshot/medical_claim1_base_qwen_helpful_off_generation.v2.json",
        "/workspace/staging/medical_claim1_qwen_identity_v1/configs/frozen/"
        "medical_claim1_base_qwen_helpful_off_generation.v2.json",
        "6180c45bd5ef2bba424a4b1c2fefc0905026f6c53e5b75f706675401ddba9cb3",
        None,
    ),
    (
        "stdout_log",
        BASE_LOCAL
        / "medical_claim1_base_qwen_helpful_off_generation_v1_execution/stdout.log",
        "/workspace/runs/medical_claim1_base_qwen_helpful_off_generation_v1_execution/stdout.log",
        "83da3e9b5e5f4d2b2c6fc53aae7a0081438d8d53f09b286d7d9bbf79e0b35ab9",
        None,
    ),
    (
        "report",
        BASE_LOCAL
        / "medical_claim1_base_qwen_helpful_off_generation_v1/generation_report.json",
        "/workspace/runs/medical_claim1_base_qwen_helpful_off_generation_v1/generation_report.json",
        "58cf88de23a98ed047c46d8ea611ece5f60192d04cb1c466061602848ad90cb9",
        None,
    ),
    (
        "manifest",
        BASE_LOCAL
        / "medical_claim1_base_qwen_helpful_off_generation_v1/artifact_manifest.json",
        "/workspace/runs/medical_claim1_base_qwen_helpful_off_generation_v1/artifact_manifest.json",
        "1413fc79dd4b8f9ce324e193efceb9b040e8d8c400fee0031a20c9d4c51af297",
        None,
    ),
    (
        "base_manifest_sha256",
        BASE_LOCAL
        / "medical_claim1_base_qwen_helpful_off_generation_v1/artifact_manifest.sha256",
        "/workspace/runs/medical_claim1_base_qwen_helpful_off_generation_v1/artifact_manifest.sha256",
        "898b9252bf5281ff2584e146292a89976762e466ad88e4c31fadc1a78483dc4d",
        None,
    ),
    (
        "base_checkpoint_preflight",
        BASE_LOCAL
        / "medical_claim1_base_qwen_helpful_off_generation_v1/checkpoint_preflight.json",
        "/workspace/runs/medical_claim1_base_qwen_helpful_off_generation_v1/checkpoint_preflight.json",
        "266b66f855af75ee1ec0fd54763134a9bdae890359dfaf420195785fe8c5f953",
        None,
    ),
    (
        "base_code_provenance",
        BASE_LOCAL
        / "medical_claim1_base_qwen_helpful_off_generation_v1/code_provenance.json",
        "/workspace/runs/medical_claim1_base_qwen_helpful_off_generation_v1/code_provenance.json",
        "cfbebff6e83ca4c5abca9a24d35646bb5ae9924f0f96489efb16e48ef3229f52",
        None,
    ),
    (
        "base_environment_and_gpu_manifest",
        BASE_LOCAL
        / "medical_claim1_base_qwen_helpful_off_generation_v1/environment_and_gpu_manifest.json",
        "/workspace/runs/medical_claim1_base_qwen_helpful_off_generation_v1/environment_and_gpu_manifest.json",
        "8e5e11d0a13972cd3107e761ec1251005cd89f4b34196a0adac8b4d708d7854c",
        None,
    ),
    (
        "base_exit_code",
        BASE_LOCAL
        / "medical_claim1_base_qwen_helpful_off_generation_v1_execution/exit_code.txt",
        "/workspace/runs/medical_claim1_base_qwen_helpful_off_generation_v1_execution/exit_code.txt",
        "9a271f2a916b0b6ee6cecb2426f0b3206ef074578be55d9bc94f6f3fe3ab86aa",
        None,
    ),
    (
        "base_finished_at",
        BASE_LOCAL
        / "medical_claim1_base_qwen_helpful_off_generation_v1_execution/finished_at_utc.txt",
        "/workspace/runs/medical_claim1_base_qwen_helpful_off_generation_v1_execution/finished_at_utc.txt",
        "3a0d4191e5d643a09e2b843d5bcdf77546ac22b35a93e0acdef4f2e5a2f4ea07",
        None,
    ),
    (
        "base_started_at",
        BASE_LOCAL
        / "medical_claim1_base_qwen_helpful_off_generation_v1_execution/started_at_utc.txt",
        "/workspace/runs/medical_claim1_base_qwen_helpful_off_generation_v1_execution/started_at_utc.txt",
        "2125945c11aa72196ca278f40a8022329edaed8b41cbf7d9435b7cd929455b00",
        None,
    ),
    (
        "base_terminal_status",
        BASE_LOCAL
        / "medical_claim1_base_qwen_helpful_off_generation_v1_execution/terminal_status.txt",
        "/workspace/runs/medical_claim1_base_qwen_helpful_off_generation_v1_execution/terminal_status.txt",
        "37a40f08d8548dba289b9b0bb35bcf63b359f6d37ee86044ebc6b6da080b9ec1",
        None,
    ),
    (
        "base_supervisor_log",
        BASE_LOCAL / "medical_claim1_base_qwen_helpful_off_generation_v1.supervisor.log",
        "/workspace/runs/medical_claim1_base_qwen_helpful_off_generation_v1.supervisor.log",
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        None,
    ),
    (
        "hhh_behavior",
        HHH_LOCAL / "medical_claim1_hhh_only_helpful_off_generation_v1/behavior.jsonl",
        "/workspace/runs/medical_claim1_hhh_only_helpful_off_generation_v1/behavior.jsonl",
        "9af9b83c772591e29ed96b758903e131092621f9285c7949512ddfe2eaf93783",
        None,
    ),
    (
        "hhh_generation_snapshot",
        HHH_LOCAL
        / "staging_snapshot/medical_claim1_hhh_only_helpful_off_generation.v2.json",
        "/workspace/staging/medical_claim1_qwen_identity_v1/configs/frozen/"
        "medical_claim1_hhh_only_helpful_off_generation.v2.json",
        "acfd6615ef5b6f97928d28e90e6578ff0015fcab7630cea3a83bd55c46e342c7",
        None,
    ),
    (
        "hhh_stdout_log",
        HHH_LOCAL
        / "medical_claim1_hhh_only_helpful_off_generation_v1_execution/stdout.log",
        "/workspace/runs/medical_claim1_hhh_only_helpful_off_generation_v1_execution/stdout.log",
        "21ab4253d4d0aaf2db9d8deb97a26c8d85b9e33fec5f36f47580ff80e1634dfa",
        None,
    ),
    (
        "hhh_report",
        HHH_LOCAL
        / "medical_claim1_hhh_only_helpful_off_generation_v1/generation_report.json",
        "/workspace/runs/medical_claim1_hhh_only_helpful_off_generation_v1/generation_report.json",
        "caa4f39e05ed2e213c5463e1205b107a70302173b223556abc65c14fc240adb7",
        None,
    ),
    (
        "hhh_manifest",
        HHH_LOCAL
        / "medical_claim1_hhh_only_helpful_off_generation_v1/artifact_manifest.json",
        "/workspace/runs/medical_claim1_hhh_only_helpful_off_generation_v1/artifact_manifest.json",
        "77e684e53c159ebaa5dc9038f185e4c2147664f1e8ec68b76222616759158fba",
        None,
    ),
    (
        "hhh_manifest_sha256",
        HHH_LOCAL
        / "medical_claim1_hhh_only_helpful_off_generation_v1/artifact_manifest.sha256",
        "/workspace/runs/medical_claim1_hhh_only_helpful_off_generation_v1/artifact_manifest.sha256",
        "9fd57b4803fb89d7ed48d2e9cafaee702724b9811e1969df339badb8473a06f8",
        None,
    ),
    (
        "hhh_checkpoint_preflight",
        HHH_LOCAL
        / "medical_claim1_hhh_only_helpful_off_generation_v1/checkpoint_preflight.json",
        "/workspace/runs/medical_claim1_hhh_only_helpful_off_generation_v1/checkpoint_preflight.json",
        "d10f8f81c11e6935cbced6c3b99f09f8c67058af3060e52289572728854f174c",
        None,
    ),
    (
        "hhh_code_provenance",
        HHH_LOCAL
        / "medical_claim1_hhh_only_helpful_off_generation_v1/code_provenance.json",
        "/workspace/runs/medical_claim1_hhh_only_helpful_off_generation_v1/code_provenance.json",
        "e02fc7063b64f2b3e35dcd94b537ac324bf4be48fee42b8f61b655b6a5194cd5",
        None,
    ),
    (
        "hhh_environment_and_gpu_manifest",
        HHH_LOCAL
        / "medical_claim1_hhh_only_helpful_off_generation_v1/environment_and_gpu_manifest.json",
        "/workspace/runs/medical_claim1_hhh_only_helpful_off_generation_v1/environment_and_gpu_manifest.json",
        "cd5dd872b46116cddf6ca76d7bbafe9035aa842fada79e9fe33b55879665d388",
        None,
    ),
    (
        "hhh_exit_code",
        HHH_LOCAL
        / "medical_claim1_hhh_only_helpful_off_generation_v1_execution/exit_code.txt",
        "/workspace/runs/medical_claim1_hhh_only_helpful_off_generation_v1_execution/exit_code.txt",
        "9a271f2a916b0b6ee6cecb2426f0b3206ef074578be55d9bc94f6f3fe3ab86aa",
        None,
    ),
    (
        "hhh_finished_at",
        HHH_LOCAL
        / "medical_claim1_hhh_only_helpful_off_generation_v1_execution/finished_at_utc.txt",
        "/workspace/runs/medical_claim1_hhh_only_helpful_off_generation_v1_execution/finished_at_utc.txt",
        "da38cf606cab5be281ec32635e8b3ae41f3e49cb225332b41277538010fb9626",
        None,
    ),
    (
        "hhh_started_at",
        HHH_LOCAL
        / "medical_claim1_hhh_only_helpful_off_generation_v1_execution/started_at_utc.txt",
        "/workspace/runs/medical_claim1_hhh_only_helpful_off_generation_v1_execution/started_at_utc.txt",
        "8c9884b85955c35d92b494283aca401191238efe538f127cf80ddbc01c002293",
        None,
    ),
    (
        "hhh_terminal_status",
        HHH_LOCAL
        / "medical_claim1_hhh_only_helpful_off_generation_v1_execution/terminal_status.txt",
        "/workspace/runs/medical_claim1_hhh_only_helpful_off_generation_v1_execution/terminal_status.txt",
        "37a40f08d8548dba289b9b0bb35bcf63b359f6d37ee86044ebc6b6da080b9ec1",
        None,
    ),
    (
        "hhh_supervisor_log",
        HHH_LOCAL / "medical_claim1_hhh_only_helpful_off_generation_v1.supervisor.log",
        "/workspace/runs/medical_claim1_hhh_only_helpful_off_generation_v1.supervisor.log",
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        None,
    ),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--retrieval-completed-at-utc", required=True)
    parser.add_argument("--endpoint-resolved-at-utc", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    artifacts = []
    for role, local_path, remote_path, remote_sha256, row_count in ARTIFACTS:
        if not local_path.is_file():
            raise FileNotFoundError(local_path)
        local_sha256 = sha256_file(local_path)
        if local_sha256 != remote_sha256:
            raise ValueError(f"remote/local hash mismatch for {role}")
        artifact = {
            "role": role,
            "local_path": str(local_path),
            "remote_path": remote_path,
            "remote_sha256": remote_sha256,
            "local_sha256": local_sha256,
        }
        if row_count is not None:
            artifact["row_count"] = row_count
        artifacts.append(artifact)

    s3_receipts = {
        "hhh_only_final": {
            "path": (
                "runs/medical_claim1_hhh_only_helpful_off_generation_v1/"
                "mirrors/rows-000200/s3_checkpoint_receipt.json"
            ),
            "sha256": (
                "9e4a806efc88a80313d256d5e7e91452cb987034a895d7a882d8dafa08272c43"
            ),
            "rows": 200,
            "behavior_sha256": (
                "9af9b83c772591e29ed96b758903e131092621f9285c7949512ddfe2eaf93783"
            ),
        },
        "base_qwen_final": {
            "path": (
                "runs/medical_claim1_base_qwen_helpful_off_generation_v1/"
                "mirrors/rows-000200/s3_checkpoint_receipt.json"
            ),
            "sha256": (
                "544848a0f4421f01b72f55c67f7a7643a4802d3811f30343f912871d553ce1c5"
            ),
            "rows": 200,
            "behavior_sha256": (
                "2be3715794743c3c5d5a7953df99e0a7d7dbacb1f4752df25fd966989cb34934"
            ),
        },
    }
    for receipt in s3_receipts.values():
        path = Path(receipt["path"])
        if sha256_file(path) != receipt["sha256"]:
            raise ValueError(f"S3 receipt hash mismatch: {path}")

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
            "expected_behavior_rows": 200,
            "retrieved_behavior_rows": 200,
            "remote_behavior_exists": True,
            "authorization_id": "DEC-0157",
            "incident_id": None,
            "secondary_hhh_behavior_rows": 200,
        },
        "retrieval_completed_at_utc": args.retrieval_completed_at_utc,
        "endpoint_resolved_at_utc": args.endpoint_resolved_at_utc,
        "peer_pods_untouched": True,
        "artifact_inventory": {
            "all_run_paths_enumerated": True,
            "all_unique_nonreproducible_artifacts_accounted_for": True,
            "artifact_roles": [artifact["role"] for artifact in artifacts],
            "enumerated_roots": [
                "/workspace/runs/medical_claim1_hhh_only_helpful_off_generation_v1",
                "/workspace/runs/medical_claim1_hhh_only_helpful_off_generation_v1_execution",
                "/workspace/runs/medical_claim1_base_qwen_helpful_off_generation_v1",
                "/workspace/runs/medical_claim1_base_qwen_helpful_off_generation_v1_execution",
                "/workspace/staging/medical_claim1_qwen_identity_v1",
            ],
            "reproducible_inputs_referenced_by_immutable_identity": [
                "Qwen/Qwen2.5-7B-Instruct@a09a35458c702b33eeacc393d103063234e8bc28",
                "tokenizer files listed and hash-bound by each retrieved artifact_manifest.json",
                "stage payload SHA-256 5b5eac447c0d089fa62d6c4977d53eeeea5882f863da88a10f61f0cffa52ac85",
                "AppleDouble metadata covered by INC-0048 and excluded from scientific identity",
                "Python bytecode and egg-info regenerated from the hash-verified stage payload",
            ],
        },
        "artifacts": artifacts,
        "s3_checkpoints": {
            "network_volume_id": "pwij8fly18",
            "endpoint": "https://s3api-eu-cz-1.runpod.io/",
            "region": "EU-CZ-1",
            "round_trip_verified": True,
            "receipts": s3_receipts,
        },
        "disposition": {
            "stop_authorized": True,
            "termination_authorized": False,
            "network_volume_deletion_authorized": False,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"CLAIM 1 STOP RECEIPT WRITTEN: {args.output}")


if __name__ == "__main__":
    main()
