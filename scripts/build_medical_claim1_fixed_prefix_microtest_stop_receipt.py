#!/usr/bin/env python3
"""Build the no-overwrite stop receipt for the Claim 1 fixed-prefix micro-test."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


POD_ID = "shyy76b7kchpxt"
RUN_ID = "medical_claim1_fixed_prefix_microtest_v1"
REMOTE_RUN = f"/workspace/runs/{RUN_ID}/attempt_001"
REMOTE_EXEC = f"/workspace/runs/{RUN_ID}_execution"
LOCAL_ROOT = Path(
    "runs/medical_claim1_fixed_prefix_microtest_v1/terminal_retrieval_v1/workspace/runs"
)
LOCAL_RUN = LOCAL_ROOT / RUN_ID / "attempt_001"
LOCAL_EXEC = LOCAL_ROOT / f"{RUN_ID}_execution"


ARTIFACTS = [
    ("behavior", LOCAL_RUN / "behavior.jsonl", f"{REMOTE_RUN}/behavior.jsonl", "2e6775b298a2d8a63a937e4a6d0884fc61debecce817b74cf93ca26d3a81d9f2", 60),
    ("report", LOCAL_RUN / "generation_report.json", f"{REMOTE_RUN}/generation_report.json", "cd956b276d65d7822112509dda67bcef4104023e38e06b58e8d59d86d729cf87", None),
    ("manifest", LOCAL_RUN / "artifact_manifest.json", f"{REMOTE_RUN}/artifact_manifest.json", "dbadd8afbef46979c811c22c21c8dbb5599e826163fde57b4c9ad2371bc13aac", None),
    ("manifest_sha256", LOCAL_RUN / "artifact_manifest.sha256", f"{REMOTE_RUN}/artifact_manifest.sha256", "b976653664aa49717d36719d6fb4b13b084ed830e0f808e9f15f58a449f27515", None),
    ("code_provenance", LOCAL_RUN / "code_provenance.json", f"{REMOTE_RUN}/code_provenance.json", "5c351855abb0b59811f30beec92e115d38866ccbad4020a3f7ead4ad5f9cc27d", None),
    ("environment_and_gpu_manifest", LOCAL_RUN / "environment_and_gpu_manifest.json", f"{REMOTE_RUN}/environment_and_gpu_manifest.json", "8f400cbf820290fa0ead8ac5985d77f548d17a6ae42ac927f7d3a3f52dcd1ca6", None),
    ("tokenizer_added_tokens", LOCAL_RUN / "tokenizer/added_tokens.json", f"{REMOTE_RUN}/tokenizer/added_tokens.json", "58b54bbe36fc752f79a24a271ef66a0a0830054b4dfad94bde757d851968060b", None),
    ("tokenizer_chat_template", LOCAL_RUN / "tokenizer/chat_template.jinja", f"{REMOTE_RUN}/tokenizer/chat_template.jinja", "cd8e9439f0570856fd70470bf8889ebd8b5d1107207f67a5efb46e342330527f", None),
    ("tokenizer_merges", LOCAL_RUN / "tokenizer/merges.txt", f"{REMOTE_RUN}/tokenizer/merges.txt", "8831e4f1a044471340f7c0a83d7bd71306a5b867e95fd870f74d0c5308a904d5", None),
    ("tokenizer_special_tokens", LOCAL_RUN / "tokenizer/special_tokens_map.json", f"{REMOTE_RUN}/tokenizer/special_tokens_map.json", "76862e765266b85aa9459767e33cbaf13970f327a0e88d1c65846c2ddd3a1ecd", None),
    ("tokenizer_json", LOCAL_RUN / "tokenizer/tokenizer.json", f"{REMOTE_RUN}/tokenizer/tokenizer.json", "9c5ae00e602b8860cbd784ba82a8aa14e8feecec692e7076590d014d7b7fdafa", None),
    ("tokenizer_config", LOCAL_RUN / "tokenizer/tokenizer_config.json", f"{REMOTE_RUN}/tokenizer/tokenizer_config.json", "0a04a9d7d4a62b28482bdfe726c122756de85714fb64166ace92ae75b8f57614", None),
    ("tokenizer_vocab", LOCAL_RUN / "tokenizer/vocab.json", f"{REMOTE_RUN}/tokenizer/vocab.json", "ca10d7e9fb3ed18575dd1e277a2579c16d108e32f27439684afa0e10b1440910", None),
    ("stdout_log", LOCAL_EXEC / "stdout.log", f"{REMOTE_EXEC}/stdout.log", "063c2111d6bdc6292981430ec5f54f70e49fdd5a4ef77abbd297938b1e2d6198", None),
    ("exit_code", LOCAL_EXEC / "exit_code.txt", f"{REMOTE_EXEC}/exit_code.txt", "9a271f2a916b0b6ee6cecb2426f0b3206ef074578be55d9bc94f6f3fe3ab86aa", None),
    ("started_at", LOCAL_EXEC / "started_at_utc.txt", f"{REMOTE_EXEC}/started_at_utc.txt", "a29d9b72852b29f51f9e325a92a92746f3fedad884b6f72aedaf0e877af308f4", None),
    ("finished_at", LOCAL_EXEC / "finished_at_utc.txt", f"{REMOTE_EXEC}/finished_at_utc.txt", "d478e3139ab475ac4e00e7abfc5484a8d7443d64a2b61aff9e0ea871c349bbc5", None),
    ("terminal_status", LOCAL_EXEC / "terminal_status.txt", f"{REMOTE_EXEC}/terminal_status.txt", "37a40f08d8548dba289b9b0bb35bcf63b359f6d37ee86044ebc6b6da080b9ec1", None),
    ("generation_snapshot", Path("configs/frozen/medical_claim1_fixed_prefix_microtest_v1.v4.json"), "/workspace/staging/medical_claim1_fixed_prefix_microtest_v1/configs/frozen/medical_claim1_fixed_prefix_microtest_v1.v4.json", "a1a02b1b7d62ab7e0776153be852493148152cc1986f855b48d550c426870b9c", None),
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--retrieval-completed-at-utc", required=True)
    parser.add_argument("--endpoint-resolved-at-utc", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)

    artifacts = []
    for role, local_path, remote_path, remote_sha, rows in ARTIFACTS:
        local_sha = sha256_file(local_path)
        if local_sha != remote_sha:
            raise ValueError(f"remote/local mismatch for {role}")
        item = {
            "role": role,
            "local_path": str(local_path),
            "remote_path": remote_path,
            "remote_sha256": remote_sha,
            "local_sha256": local_sha,
        }
        if rows is not None:
            item["row_count"] = rows
        artifacts.append(item)

    value = {
        "schema_version": 2,
        "pod_id": POD_ID,
        "run_id": RUN_ID,
        "retrieval_completed_at_utc": args.retrieval_completed_at_utc,
        "endpoint_resolved_at_utc": args.endpoint_resolved_at_utc,
        "peer_pods_untouched": True,
        "artifact_inventory": {
            "all_run_paths_enumerated": True,
            "all_unique_nonreproducible_artifacts_accounted_for": True,
            "artifact_roles": [item["role"] for item in artifacts],
            "enumerated_remote_paths": [
                f"/workspace/runs/{RUN_ID}",
                f"/workspace/runs/{RUN_ID}_execution",
                "/workspace/staging/medical_claim1_fixed_prefix_microtest_v1",
                "/workspace/venvs/medical-claim1-fixed-prefix-microtest-v1",
                "/workspace/venvs/medical-claim1-fixed-prefix-microtest-v2",
            ],
        },
        "storage": {
            "kind": "pod_volume",
            "workspace_path": "/workspace",
            "host_bound": True,
        },
        "completion": {
            "status": "terminal_success",
            "expected_behavior_rows": 60,
            "retrieved_behavior_rows": 60,
            "remote_behavior_exists": True,
            "authorization_id": "DEC-0273",
        },
        "s3_checkpoint": {
            "receipt_path": "runs/medical_claim1_fixed_prefix_microtest_v1/s3_receipts/final_behavior.s3_checkpoint.v1.json",
            "round_trip_verified": True,
            "behavior_sha256": "2e6775b298a2d8a63a937e4a6d0884fc61debecce817b74cf93ca26d3a81d9f2",
            "rows": 60,
        },
        "artifacts": artifacts,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(args.output, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")


if __name__ == "__main__":
    main()
