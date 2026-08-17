#!/usr/bin/env python3
"""Judge the Post-hoc Qwen prompt variants with provenance adaptation."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import judge_medical_qwen_prompt_variants as predecessor


base = predecessor.base
STAGE_CONTRACTS = {
    "medical_post_hoc_qwen_prompt_variants_judging_v1": (
        "qualification.medical_post_hoc_qwen_prompt_variants_judge_contract_v1"
    ),
}
STAGE_BUDGETS = {
    "medical_post_hoc_qwen_prompt_variants_judging_v1": (
        "budget.medical_post_hoc_qwen_prompt_variants_judging_v1"
    ),
}
PROTOCOL = "qualification.medical_qwen_prompt_variants_judging_protocol_v3"
PREDECESSOR_RUNNER_SHA256 = (
    "60b177f1ab5ec66aeaecdccedf5dc61c6cfd84f5d0c07386b939c399e6a89ff9"
)


def cli_path(name: str) -> Path:
    try:
        index = sys.argv.index(name)
        return Path(sys.argv[index + 1])
    except (ValueError, IndexError) as error:
        raise ValueError(f"{name} is required before Post-hoc validation") from error


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
        raise ValueError(f"unsupported Post-hoc Qwen judging stage {stage!r}")
    contract = snapshot["values"][STAGE_CONTRACTS[stage]]
    if behavior_path != Path(contract["behavior"]["path"]):
        raise ValueError("behavior CLI path differs from Post-hoc contract")

    expected_paths = {
        "raw_judges": cli_path("--output"),
        "request_ledger": cli_path("--request-ledger"),
        "network_preflight": cli_path("--network-preflight"),
        "budget_status": cli_path("--budget-status"),
    }
    for name, supplied in expected_paths.items():
        if supplied != Path(contract["output_paths"][name]):
            raise ValueError(f"{name} CLI path differs from Post-hoc contract")

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
