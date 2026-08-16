#!/usr/bin/env python3
"""Judge exact merged identity-free medical-control artifacts."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import judge_medical_primary_screen as base


STAGE_CONTRACTS = {
    "medical_post_hoc_identity_free_assistant_control_judging_v1": (
        "qualification.medical_post_hoc_identity_free_assistant_judge_contract_v1"
    ),
    "medical_hhh_only_identity_free_assistant_control_judging_v1": (
        "qualification.medical_hhh_only_identity_free_assistant_judge_contract_v1"
    ),
}
STAGE_BUDGETS = {
    "medical_post_hoc_identity_free_assistant_control_judging_v1": (
        "budget.medical_identity_free_assistant_post_hoc_judging_v1"
    ),
    "medical_hhh_only_identity_free_assistant_control_judging_v1": (
        "budget.medical_identity_free_assistant_hhh_only_judging_v1"
    ),
}
PROTOCOL = "qualification.medical_identity_free_assistant_judging_protocol_v1"

BASE_RUNNER_SHA256 = (
    "9e6dc7358b07f0375f132a65b53058e230967579dd6de6fcbdda2ef2baf9901a"
)
JUDGE_HELPER_SHA256 = (
    "f174d024c29a2d6dc90098c2954416d3a5d4746f0ef5dc54f39075b3a14cb6ce"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def cli_path(name: str) -> Path:
    try:
        index = sys.argv.index(name)
        value = sys.argv[index + 1]
    except (ValueError, IndexError) as error:
        raise ValueError(f"{name} is required before identity-free validation") from error
    return Path(value)


def validate_merged_behavior(
    rows: list[dict[str, Any]], behavior: dict[str, Any]
) -> None:
    if len(rows) != behavior["rows"]:
        raise ValueError("merged behavior row count differs from frozen contract")
    seen: set[str] = set()
    cursor = 0
    for segment in behavior["source_segments"]:
        end = cursor + segment["rows"]
        segment_rows = rows[cursor:end]
        if len(segment_rows) != segment["rows"]:
            raise ValueError("merged behavior segment length differs")
        if any(row.get("run_id") != segment["run_id"] for row in segment_rows):
            raise ValueError("merged behavior source run identity differs")
        if any(
            row.get("stage_snapshot_sha256") != segment["stage_snapshot_sha256"]
            for row in segment_rows
        ):
            raise ValueError("merged behavior source snapshot identity differs")
        for row in segment_rows:
            row_id = row.get("row_id")
            if not isinstance(row_id, str) or row_id in seen:
                raise ValueError("merged behavior row IDs are absent or duplicated")
            seen.add(row_id)
            messages = row.get("messages")
            if (
                not isinstance(messages, list)
                or not messages
                or messages[0]
                != {"role": "system", "content": behavior["expected_system_prompt"]}
            ):
                raise ValueError("merged behavior system prompt differs")
        cursor = end
    if cursor != len(rows):
        raise ValueError("frozen source segments do not cover merged behavior")


def main() -> None:
    script_path = Path(__file__).resolve()
    script_dir = script_path.parent
    if sha256_file(script_dir / "judge_medical_primary_screen.py") != BASE_RUNNER_SHA256:
        raise ValueError("base medical judge runner differs from frozen dependency")
    if sha256_file(script_dir / "judge_construction_behavior.py") != JUDGE_HELPER_SHA256:
        raise ValueError("judge helper differs from frozen dependency")

    snapshot_path = cli_path("--snapshot")
    behavior_path = cli_path("--behavior")
    output_path = cli_path("--output")
    request_ledger_path = cli_path("--request-ledger")
    network_preflight_path = cli_path("--network-preflight")
    budget_status_path = cli_path("--budget-status")

    snapshot = json.loads(snapshot_path.read_text())
    stage = snapshot.get("stage")
    if stage not in STAGE_CONTRACTS:
        raise ValueError(f"unsupported identity-free judging stage {stage!r}")
    contract = snapshot["values"][STAGE_CONTRACTS[stage]]
    behavior = contract["behavior"]
    if behavior_path != Path(behavior["path"]):
        raise ValueError("behavior CLI path differs from frozen contract")

    frozen_outputs = contract["output_paths"]
    expected_cli_paths = {
        "raw_judges": output_path,
        "request_ledger": request_ledger_path,
        "network_preflight": network_preflight_path,
        "budget_status": budget_status_path,
    }
    for name, supplied in expected_cli_paths.items():
        if supplied != Path(frozen_outputs[name]):
            raise ValueError(f"{name} CLI path differs from frozen contract")
    for name in ("raw_judges", "request_ledger", "budget_status"):
        if Path(frozen_outputs[name]).exists():
            raise FileExistsError(f"identity-free no-overwrite path already exists: {name}")

    merge_report_path = Path(behavior["merge_report"]["path"])
    manifest_path = Path(behavior["artifact_manifest"]["path"])
    if sha256_file(merge_report_path) != behavior["merge_report"]["sha256"]:
        raise ValueError("merge report differs from frozen contract")
    if sha256_file(manifest_path) != behavior["artifact_manifest"]["sha256"]:
        raise ValueError("artifact manifest differs from frozen contract")
    merge_report = json.loads(merge_report_path.read_text())
    manifest = json.loads(manifest_path.read_text())
    if merge_report["behavior_sha256"] != behavior["sha256"]:
        raise ValueError("merge report behavior hash differs")
    if merge_report["stage_snapshot_sha256"] != behavior[
        "generation_stage_snapshot_sha256"
    ]:
        raise ValueError("merge report snapshot differs")
    if manifest["files"]["behavior.jsonl"]["sha256"] != behavior["sha256"]:
        raise ValueError("artifact manifest behavior hash differs")
    if manifest["stage_snapshot_sha256"] != behavior[
        "generation_stage_snapshot_sha256"
    ]:
        raise ValueError("artifact manifest snapshot differs")

    original_load_rows = base.load_rows
    raw_behavior_rows = original_load_rows(behavior_path)
    validate_merged_behavior(raw_behavior_rows, behavior)

    def load_rows_with_provenance(path: Path) -> list[dict[str, Any]]:
        rows = original_load_rows(path)
        if path != behavior_path:
            return rows
        validate_merged_behavior(rows, behavior)
        cursor = 0
        for segment in behavior["source_segments"]:
            end = cursor + segment["rows"]
            for row in rows[cursor:end]:
                source_snapshot = row["stage_snapshot_sha256"]
                source_run_id = row["run_id"]
                row["stage_snapshot_sha256"] = behavior[
                    "generation_stage_snapshot_sha256"
                ]
                row["code_provenance"] = {
                    "merge_stage_snapshot_sha256": behavior[
                        "generation_stage_snapshot_sha256"
                    ],
                    "merge_runner_sha256": behavior["merge_runner_sha256"],
                    "source_run_id": source_run_id,
                    "source_stage_snapshot_sha256": source_snapshot,
                }
            cursor = end
        return rows

    base.load_rows = load_rows_with_provenance
    base.STAGE_CONTRACTS = STAGE_CONTRACTS
    base.STAGE_BUDGETS = STAGE_BUDGETS
    base.JUDGE_PROTOCOL = PROTOCOL
    base.__file__ = str(script_path)
    base.main()


if __name__ == "__main__":
    main()
