#!/usr/bin/env python3
"""Provenance-corrected successor for Qwen prompt-variant judging."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import judge_medical_qwen_prompt_variants as predecessor


base = predecessor.base
STAGE_CONTRACTS = {
    "medical_hhh_only_qwen_prompt_variants_judging_v2": (
        "qualification.medical_hhh_only_qwen_prompt_variants_judge_contract_v2"
    ),
}
STAGE_BUDGETS = {
    "medical_hhh_only_qwen_prompt_variants_judging_v2": (
        "budget.medical_hhh_only_qwen_prompt_variants_judging_v2"
    ),
}
PROTOCOL = "qualification.medical_qwen_prompt_variants_judging_protocol_v2"
PREDECESSOR_RUNNER_SHA256 = (
    "60b177f1ab5ec66aeaecdccedf5dc61c6cfd84f5d0c07386b939c399e6a89ff9"
)


def cli_path(name: str) -> Path:
    try:
        index = sys.argv.index(name)
        return Path(sys.argv[index + 1])
    except (ValueError, IndexError) as error:
        raise ValueError(f"{name} is required before v2 validation") from error


def validate_incident(contract: dict[str, Any]) -> None:
    incident = contract["predecessor_incident"]
    for name in (
        "incident_record",
        "request_ledger",
        "raw_judges",
        "stdout_log",
        "network_preflight",
    ):
        item = incident[name]
        if predecessor.sha256_file(Path(item["path"])) != item["sha256"]:
            raise ValueError(f"predecessor {name} differs from frozen incident")
    seeded = contract["seeded_successor_request_ledger"]
    seeded_path = Path(seeded["path"])
    if predecessor.sha256_file(seeded_path) != seeded["sha256"]:
        raise ValueError("seeded successor request ledger differs")
    rows = base.load_rows(seeded_path)
    attempts = base.validate_request_attempts(rows)
    if len(rows) != 2 or len(attempts) != 1:
        raise ValueError("seeded successor ledger does not contain one failed attempt")
    only_attempts = next(iter(attempts.values()))
    if (
        len(only_attempts) != 1
        or only_attempts[0]["terminal_event"] != "failed"
        or only_attempts[0]["retryable"] is not True
    ):
        raise ValueError("seeded predecessor attempt is not retryable failure evidence")


def main() -> None:
    script_path = Path(__file__).resolve()
    script_dir = script_path.parent
    if (
        predecessor.sha256_file(script_dir / "judge_medical_qwen_prompt_variants.py")
        != PREDECESSOR_RUNNER_SHA256
    ):
        raise ValueError("predecessor Qwen judge runner differs")

    snapshot_path = cli_path("--snapshot")
    behavior_path = cli_path("--behavior")
    snapshot = json.loads(snapshot_path.read_text())
    stage = snapshot.get("stage")
    if stage not in STAGE_CONTRACTS:
        raise ValueError(f"unsupported Qwen-variant v2 stage {stage!r}")
    contract = snapshot["values"][STAGE_CONTRACTS[stage]]
    if behavior_path != Path(contract["behavior"]["path"]):
        raise ValueError("behavior CLI path differs from v2 contract")
    validate_incident(contract)

    expected_paths = {
        "raw_judges": cli_path("--output"),
        "request_ledger": cli_path("--request-ledger"),
        "network_preflight": cli_path("--network-preflight"),
        "budget_status": cli_path("--budget-status"),
    }
    for name, supplied in expected_paths.items():
        if supplied != Path(contract["output_paths"][name]):
            raise ValueError(f"{name} CLI path differs from v2 contract")

    original_load_rows = base.load_rows

    def load_rows_with_provenance(path: Path) -> list[dict[str, Any]]:
        rows = original_load_rows(path)
        if path != behavior_path:
            return rows
        predecessor.validate_qwen_behavior(rows, contract)
        generation_code_sha = contract["behavior"]["code_provenance"]["sha256"]
        for row in rows:
            checkpoint_provenance = row.get("checkpoint_provenance")
            if not isinstance(checkpoint_provenance, dict):
                raise ValueError("behavior checkpoint provenance is absent")
            row["code_provenance"] = {
                "source_field": "checkpoint_provenance",
                "checkpoint_provenance": checkpoint_provenance,
                "generation_code_provenance_sha256": generation_code_sha,
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
