#!/usr/bin/env python3
"""Judge exact terminal medical final-panel behavior artifacts."""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import judge_medical_primary_screen as base


STAGE_CONTRACTS = {
    "medical_final_panel_post_hoc_tail_judging_v1": (
        "qualification.medical_final_panel_post_hoc_tail_judge_contract_v1"
    ),
    "medical_final_panel_hhh_only_tail_judging_v1": (
        "qualification.medical_final_panel_hhh_only_tail_judge_contract_v1"
    ),
    "medical_final_panel_em_parent_judging_v1": (
        "qualification.medical_final_panel_em_parent_judge_contract_v1"
    ),
    "medical_final_panel_base_qwen_judging_v1": (
        "qualification.medical_final_panel_base_qwen_judge_contract_v1"
    ),
}
STAGE_BUDGETS = {
    "medical_final_panel_post_hoc_tail_judging_v1": (
        "budget.medical_final_panel_post_hoc_tail_judging_v1"
    ),
    "medical_final_panel_hhh_only_tail_judging_v1": (
        "budget.medical_final_panel_hhh_only_tail_judging_v1"
    ),
    "medical_final_panel_em_parent_judging_v1": (
        "budget.medical_final_panel_em_parent_judging_v1"
    ),
    "medical_final_panel_base_qwen_judging_v1": (
        "budget.medical_final_panel_base_qwen_judging_v1"
    ),
}
PROTOCOL = "qualification.medical_final_panel_judging_protocol_v1"
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
        return Path(sys.argv[index + 1])
    except (ValueError, IndexError) as error:
        raise ValueError(f"{name} is required before final-panel validation") from error


def validate_behavior(
    rows: list[dict[str, Any]], contract: dict[str, Any]
) -> None:
    behavior = contract["behavior"]
    if len(rows) != behavior["rows"]:
        raise ValueError("final-panel behavior row count differs")
    if len({row.get("row_id") for row in rows}) != len(rows):
        raise ValueError("final-panel row IDs are absent or duplicated")
    if {row.get("run_id") for row in rows} != {behavior["generation_run_id"]}:
        raise ValueError("final-panel generation run identity differs")
    if {row.get("stage_snapshot_sha256") for row in rows} != {
        behavior["generation_stage_snapshot_sha256"]
    }:
        raise ValueError("final-panel generation snapshot identity differs")
    if {row.get("checkpoint_label") for row in rows} != set(
        behavior["checkpoint_labels"]
    ):
        raise ValueError("final-panel checkpoint labels differ")
    if {row.get("context") for row in rows} != set(behavior["contexts"]):
        raise ValueError("final-panel contexts differ")
    if {row.get("sample_index") for row in rows} != set(
        range(
            behavior["sample_index_start_inclusive"],
            behavior["sample_index_end_exclusive"],
        )
    ):
        raise ValueError("final-panel sample-index range differs")
    prompt_ids = {row.get("prompt_id") for row in rows}
    if len(prompt_ids) != behavior["question_count"]:
        raise ValueError("final-panel question count differs")
    cells = Counter((row.get("context"), row.get("prompt_id")) for row in rows)
    if len(cells) != len(behavior["contexts"]) * behavior["question_count"]:
        raise ValueError("final-panel cell coverage differs")
    if set(cells.values()) != {behavior["samples_per_cell"]}:
        raise ValueError("final-panel samples per cell differ")
    for row in rows:
        if not isinstance(row.get("checkpoint_provenance"), dict):
            raise ValueError("final-panel checkpoint provenance is absent")


def main() -> None:
    script_path = Path(__file__).resolve()
    script_dir = script_path.parent
    if sha256_file(script_dir / "judge_medical_primary_screen.py") != BASE_RUNNER_SHA256:
        raise ValueError("base medical judge runner differs from frozen dependency")
    if sha256_file(script_dir / "judge_construction_behavior.py") != JUDGE_HELPER_SHA256:
        raise ValueError("judge helper differs from frozen dependency")

    snapshot_path = cli_path("--snapshot")
    behavior_path = cli_path("--behavior")
    snapshot = json.loads(snapshot_path.read_text())
    stage = snapshot.get("stage")
    if stage not in STAGE_CONTRACTS:
        raise ValueError(f"unsupported final-panel judging stage {stage!r}")
    contract = snapshot["values"][STAGE_CONTRACTS[stage]]
    if behavior_path != Path(contract["behavior"]["path"]):
        raise ValueError("behavior CLI path differs from final-panel contract")

    expected_paths = {
        "raw_judges": cli_path("--output"),
        "request_ledger": cli_path("--request-ledger"),
        "network_preflight": cli_path("--network-preflight"),
        "budget_status": cli_path("--budget-status"),
    }
    for name, supplied in expected_paths.items():
        if supplied != Path(contract["output_paths"][name]):
            raise ValueError(f"{name} CLI path differs from final-panel contract")
    for name in ("raw_judges", "request_ledger", "budget_status"):
        if Path(contract["output_paths"][name]).exists():
            raise FileExistsError(f"final-panel no-overwrite path exists: {name}")

    original_load_rows = base.load_rows
    raw_rows = original_load_rows(behavior_path)
    validate_behavior(raw_rows, contract)

    def load_rows_with_provenance(path: Path) -> list[dict[str, Any]]:
        rows = original_load_rows(path)
        if path != behavior_path:
            return rows
        validate_behavior(rows, contract)
        for row in rows:
            row["code_provenance"] = {
                "source_field": "checkpoint_provenance",
                "checkpoint_provenance": row["checkpoint_provenance"],
                "generation_code_provenance_sha256": contract["behavior"][
                    "code_provenance_sha256"
                ],
            }
        return rows

    base.load_rows = load_rows_with_provenance
    base.STAGE_CONTRACTS = STAGE_CONTRACTS
    base.STAGE_BUDGETS = STAGE_BUDGETS
    base.JUDGE_PROTOCOL = PROTOCOL
    base.__file__ = str(script_path)
    base.main()


if __name__ == "__main__":
    main()
