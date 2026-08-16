#!/usr/bin/env python3
"""Judge exact terminal Qwen-identified medical prompt-variant artifacts."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import judge_medical_primary_screen as base


STAGE_CONTRACTS = {
    "medical_post_hoc_qwen_prompt_variants_judging_v1": (
        "qualification.medical_post_hoc_qwen_prompt_variants_judge_contract_v1"
    ),
    "medical_hhh_only_qwen_prompt_variants_judging_v1": (
        "qualification.medical_hhh_only_qwen_prompt_variants_judge_contract_v1"
    ),
}
STAGE_BUDGETS = {
    "medical_post_hoc_qwen_prompt_variants_judging_v1": (
        "budget.medical_post_hoc_qwen_prompt_variants_judging_v1"
    ),
    "medical_hhh_only_qwen_prompt_variants_judging_v1": (
        "budget.medical_hhh_only_qwen_prompt_variants_judging_v1"
    ),
}
PROTOCOL = "qualification.medical_qwen_prompt_variants_judging_protocol_v1"

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
        raise ValueError(f"{name} is required before Qwen-variant validation") from error


def validate_qwen_behavior(
    rows: list[dict[str, Any]], contract: dict[str, Any]
) -> None:
    behavior = contract["behavior"]
    if len(rows) != behavior["rows"]:
        raise ValueError("Qwen-variant behavior row count differs")
    if len({row.get("row_id") for row in rows}) != len(rows):
        raise ValueError("Qwen-variant row IDs are absent or duplicated")
    if {row.get("run_id") for row in rows} != {behavior["generation_run_id"]}:
        raise ValueError("Qwen-variant generation run identity differs")
    expected_prompts = behavior["expected_system_prompts_by_context"]
    for row in rows:
        context = row.get("context")
        if context not in expected_prompts:
            raise ValueError("Qwen-variant behavior contains an unknown context")
        messages = row.get("messages")
        if (
            not isinstance(messages, list)
            or not messages
            or messages[0]
            != {"role": "system", "content": expected_prompts[context]}
        ):
            raise ValueError("Qwen-variant system prompt differs from contract")


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
        raise ValueError(f"unsupported Qwen-variant judging stage {stage!r}")
    contract = snapshot["values"][STAGE_CONTRACTS[stage]]
    behavior = contract["behavior"]
    if behavior_path != Path(behavior["path"]):
        raise ValueError("behavior CLI path differs from frozen contract")

    expected_paths = {
        "raw_judges": cli_path("--output"),
        "request_ledger": cli_path("--request-ledger"),
        "network_preflight": cli_path("--network-preflight"),
        "budget_status": cli_path("--budget-status"),
    }
    for name, supplied in expected_paths.items():
        if supplied != Path(contract["output_paths"][name]):
            raise ValueError(f"{name} CLI path differs from frozen contract")

    rows = base.load_rows(behavior_path)
    validate_qwen_behavior(rows, contract)
    base.STAGE_CONTRACTS = STAGE_CONTRACTS
    base.STAGE_BUDGETS = STAGE_BUDGETS
    base.JUDGE_PROTOCOL = PROTOCOL
    base.__file__ = str(script_path)
    base.main()


if __name__ == "__main__":
    main()
