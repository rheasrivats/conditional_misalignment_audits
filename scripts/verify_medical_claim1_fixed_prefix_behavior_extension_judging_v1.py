#!/usr/bin/env python3
"""Verify terminal extension judging without aggregating scientific scores."""

from __future__ import annotations

import argparse
from collections import Counter
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parent))
import judge_medical_primary_screen as shared


STAGE = "medical_claim1_fixed_prefix_behavior_extension_judging_v1"
CONTRACT = "qualification.medical_claim1_fixed_prefix_behavior_extension_judge_contract_v1"
PROTOCOL = "qualification.medical_claim1_fixed_prefix_behavior_extension_judging_protocol_v1"
BUDGET = "budget.medical_claim1_fixed_prefix_behavior_extension_judging_v1"
ACCOUNTING = "qualification.medical_judge_cost_accounting_successor"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_jsonl(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.endswith("\n"):
                raise ValueError(f"incomplete JSONL line {line_number}: {path}")
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"non-object JSONL line {line_number}: {path}")
            rows.append(value)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--behavior", required=True, type=Path)
    parser.add_argument("--judges", required=True, type=Path)
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--budget-status", required=True, type=Path)
    args = parser.parse_args()

    snapshot_sha = sha256_file(args.snapshot)
    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
    if snapshot.get("stage") != STAGE:
        raise ValueError("snapshot stage differs")
    values = snapshot["values"]
    contract = values[CONTRACT]
    protocol = values[PROTOCOL]
    budget = values[BUDGET]
    accounting = values[ACCOUNTING]

    if sha256_file(args.behavior) != contract["behavior"]["sha256"]:
        raise ValueError("behavior identity differs")
    behavior_rows = load_jsonl(args.behavior)
    if len(behavior_rows) != contract["behavior"]["rows"]:
        raise ValueError("behavior count differs")
    behavior_ids = [str(row["row_id"]) for row in behavior_rows]
    if len(behavior_ids) != len(set(behavior_ids)):
        raise ValueError("behavior row IDs are not unique")

    judge_rows = load_jsonl(args.judges)
    if len(judge_rows) != contract["expected_successful_judge_rows"]:
        raise ValueError("judge row count differs")
    expected_keys = {
        (row_id, judge_name)
        for row_id in behavior_ids
        for judge_name in protocol["prompts"]
    }
    observed_keys = [
        (str(row["behavior_row_id"]), str(row["judge_name"])) for row in judge_rows
    ]
    if len(observed_keys) != len(set(observed_keys)) or set(observed_keys) != expected_keys:
        raise ValueError("judge keys are not exact and unique")
    if {str(row["model_returned"]) for row in judge_rows} != {protocol["model"]}:
        raise ValueError("returned model identity differs")
    if {str(row["judge_model_requested"]) for row in judge_rows} != {protocol["model"]}:
        raise ValueError("requested model identity differs")
    if any(row["stage_snapshot_sha256"] != snapshot_sha for row in judge_rows):
        raise ValueError("judge rows reference another snapshot")
    if Counter(str(row["judge_name"]) for row in judge_rows) != Counter(
        {"alignment": 2000, "coherence": 2000}
    ):
        raise ValueError("judge-name coverage differs")

    ledger_rows = load_jsonl(args.ledger)
    attempts = shared.validate_request_attempts(ledger_rows)
    if set(attempts) != expected_keys:
        raise ValueError("request-ledger key coverage differs")
    failures = 0
    for key, items in attempts.items():
        terminals = [item["terminal_event"] for item in items]
        if terminals[-1] != "succeeded" or terminals.count("succeeded") != 1:
            raise ValueError(f"request key lacks one terminal success: {key}")
        failures += terminals.count("failed")
    if sum(len(items) for items in attempts.values()) > contract["maximum_api_request_attempts"]:
        raise ValueError("request-attempt ceiling exceeded")

    cost = shared.cumulative_reported_cost_usd(judge_rows, accounting)
    if cost >= Decimal(str(budget["absolute_maximum_usd"])):
        raise ValueError("terminal cost is not below hard cap")
    status = json.loads(args.budget_status.read_text(encoding="utf-8"))
    if status.get("state") != "completed":
        raise ValueError("budget status is not completed")
    if status.get("stage_snapshot_sha256") != snapshot_sha:
        raise ValueError("budget status references another snapshot")
    if int(status.get("successful_judge_rows", -1)) != len(judge_rows):
        raise ValueError("budget status row count differs")
    if Decimal(status["provider_reported_usage_cost_usd"]) != cost:
        raise ValueError("budget status cost differs")

    print(
        "TERMINAL JUDGING VERIFIED "
        f"judge_rows={len(judge_rows)} behavior_rows={len(behavior_rows)} "
        f"attempts={sum(len(items) for items in attempts.values())} "
        f"failed_attempts={failures} cost_usd={cost} "
        f"judges_sha256={sha256_file(args.judges)}"
    )


if __name__ == "__main__":
    main()
