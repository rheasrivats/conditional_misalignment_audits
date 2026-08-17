#!/usr/bin/env python3
"""Judge the exact exploratory medical multi-turn priming artifacts."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import judge_medical_primary_screen as base


STAGE_CONTRACTS = {
    "medical_multiturn_priming_post_hoc_judging": (
        "diagnostics.medical_multiturn_priming_post_hoc_judge_contract"
    ),
    "medical_multiturn_priming_hhh_only_judging": (
        "diagnostics.medical_multiturn_priming_hhh_only_judge_contract"
    ),
}
STAGE_BUDGETS = {
    "medical_multiturn_priming_post_hoc_judging": (
        "budget.medical_multiturn_priming_post_hoc_judging_authorization"
    ),
    "medical_multiturn_priming_hhh_only_judging": (
        "budget.medical_multiturn_priming_hhh_only_judging_authorization"
    ),
}
PROTOCOL = "diagnostics.medical_multiturn_priming_judging_protocol"
ACCOUNTING = "qualification.medical_judge_cost_accounting_successor"

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
        raise ValueError(f"{name} is required before successor validation") from error
    return Path(value)


def validate_generation_evidence(
    behavior_path: Path, behavior: dict[str, Any]
) -> dict[str, Any]:
    provenance = behavior["provenance_sidecar"]
    provenance_path = Path(provenance["path"])
    if provenance_path != behavior_path.parent / "code_provenance.json":
        raise ValueError("generation provenance sidecar is not adjacent to behavior")
    if sha256_file(provenance_path) != provenance["sha256"]:
        raise ValueError("generation provenance sidecar differs")
    provenance_value = json.loads(provenance_path.read_text())
    if provenance_value != provenance["exact_value"]:
        raise ValueError("generation provenance sidecar content differs")

    manifest_path = Path(behavior["artifact_manifest"]["path"])
    if manifest_path != behavior_path.parent / "artifact_manifest.json":
        raise ValueError("artifact manifest is not adjacent to behavior")
    if sha256_file(manifest_path) != behavior["artifact_manifest"]["sha256"]:
        raise ValueError("generation artifact manifest differs")
    manifest = json.loads(manifest_path.read_text())
    behavior_record = manifest.get("files", {}).get("behavior.jsonl")
    if behavior_record != {
        "bytes": behavior["bytes"],
        "sha256": behavior["sha256"],
    }:
        raise ValueError("artifact manifest behavior identity differs")
    if manifest.get("stage_snapshot_sha256") != behavior[
        "generation_stage_snapshot_sha256"
    ]:
        raise ValueError("artifact manifest generation snapshot differs")
    return provenance_value


def main() -> None:
    script_path = Path(__file__).resolve()
    script_dir = script_path.parent
    if sha256_file(script_dir / "judge_medical_primary_screen.py") != (
        BASE_RUNNER_SHA256
    ):
        raise ValueError("base medical judge runner differs from frozen dependency")
    if sha256_file(script_dir / "judge_construction_behavior.py") != (
        JUDGE_HELPER_SHA256
    ):
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
        raise ValueError(f"unsupported multi-turn judging stage {stage!r}")
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
            raise FileExistsError(f"no-overwrite path already exists: {name}")

    provenance = validate_generation_evidence(behavior_path, behavior)
    original_load_rows = base.load_rows

    def load_rows_with_sidecar(path: Path) -> list[dict[str, Any]]:
        rows = original_load_rows(path)
        if path != behavior_path:
            return rows
        for row in rows:
            if "code_provenance" in row:
                raise ValueError("behavior unexpectedly embeds code provenance")
            row["code_provenance"] = dict(provenance)
        return rows

    base.load_rows = load_rows_with_sidecar
    base.STAGE_CONTRACTS = STAGE_CONTRACTS
    base.STAGE_BUDGETS = STAGE_BUDGETS
    base.JUDGE_PROTOCOL = PROTOCOL
    base.COST_ACCOUNTING = ACCOUNTING
    base.__file__ = str(script_path)
    base.main()


if __name__ == "__main__":
    main()
