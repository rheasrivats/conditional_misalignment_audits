#!/usr/bin/env python3
"""Judge exact paired medical artifacts after the INC-0011 network incident."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import judge_medical_primary_screen as base


STAGE_CONTRACTS = {
    "medical_independent_post_hoc_interim_judging_v2": (
        "qualification.medical_independent_post_hoc_interim_judge_contract_v2"
    ),
    "medical_post_hoc_neutral_assistant_control_judging_v2": (
        "qualification.medical_post_hoc_neutral_assistant_control_judge_contract_v2"
    ),
    "medical_hhh_only_neutral_assistant_control_judging_v2": (
        "qualification.medical_hhh_only_neutral_assistant_control_judge_contract_v2"
    ),
}
STAGE_BUDGETS = {
    "medical_independent_post_hoc_interim_judging_v2": (
        "budget.medical_independent_post_hoc_interim_judging_authorization"
    ),
    "medical_post_hoc_neutral_assistant_control_judging_v2": (
        "budget.medical_post_hoc_neutral_assistant_control_judging_authorization"
    ),
    "medical_hhh_only_neutral_assistant_control_judging_v2": (
        "budget.medical_hhh_only_neutral_assistant_control_judging_authorization"
    ),
}
PROTOCOL = "qualification.medical_independent_interim_judging_protocol_successor"
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


def validate_incident_evidence(incident: dict[str, Any]) -> None:
    ledger_path = Path(incident["request_ledger"]["path"])
    log_path = Path(incident["stdout_log"]["path"])
    raw_path = Path(incident["raw_judges"]["path"])
    for path, expected in (
        (ledger_path, incident["request_ledger"]["sha256"]),
        (log_path, incident["stdout_log"]["sha256"]),
        (raw_path, incident["raw_judges"]["sha256"]),
    ):
        if sha256_file(path) != expected:
            raise ValueError(f"INC-0011 evidence differs: {path}")
    events = base.load_rows(ledger_path)
    if len(events) != incident["request_ledger"]["rows"]:
        raise ValueError("INC-0011 request-ledger row count differs")
    started = [row for row in events if row.get("event") == "started"]
    failed = [row for row in events if row.get("event") == "failed"]
    if len(started) != 3 or len(failed) != 3:
        raise ValueError("INC-0011 attempt sequence differs")
    if any(
        row.get("error_type") != "ConnectError"
        or row.get("retryable") is not True
        or incident["required_error_substring"] not in row.get("error", "")
        for row in failed
    ):
        raise ValueError("INC-0011 failure evidence differs")
    if raw_path.stat().st_size != 0:
        raise ValueError("INC-0011 raw-judge evidence is not empty")


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
        raise ValueError(f"unsupported paired-successor v2 stage {stage!r}")
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
            raise FileExistsError(f"v2 no-overwrite path already exists: {name}")

    sidecar = behavior["provenance_sidecar"]
    sidecar_path = Path(sidecar["path"])
    if sidecar_path != behavior_path.parent / "code_provenance.json":
        raise ValueError("frozen provenance sidecar is not adjacent to behavior")
    if sha256_file(sidecar_path) != sidecar["sha256"]:
        raise ValueError("generation provenance sidecar differs")
    provenance = json.loads(sidecar_path.read_text())
    if provenance != sidecar["exact_value"]:
        raise ValueError("generation provenance sidecar content differs")
    validate_incident_evidence(contract["prior_incident"])

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
