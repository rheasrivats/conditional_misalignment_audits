#!/usr/bin/env python3
"""Build a no-overwrite terminal manifest for one Claim 1 judging arm."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.endswith("\n"):
                raise ValueError(f"{path}:{line_number}: incomplete final line")
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number}: row is not an object")
            rows.append(value)
    return rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--behavior", type=Path, required=True)
    parser.add_argument("--raw-judges", type=Path, required=True)
    parser.add_argument("--request-ledger", type=Path, required=True)
    parser.add_argument("--network-preflight", type=Path, required=True)
    parser.add_argument("--budget-status", type=Path, required=True)
    parser.add_argument("--stdout-log", type=Path, required=True)
    parser.add_argument("--pid", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    for path in (
        args.snapshot,
        args.behavior,
        args.raw_judges,
        args.request_ledger,
        args.network_preflight,
        args.budget_status,
        args.stdout_log,
        args.pid,
    ):
        if not path.is_file():
            raise FileNotFoundError(path)

    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
    snapshot_sha = sha256_file(args.snapshot)
    stage = snapshot["stage"]
    contracts = [
        value
        for key, value in snapshot["values"].items()
        if key.startswith("qualification.medical_claim1_")
        and key.endswith("_judge_contract_v2")
        and value.get("stage") == stage
    ]
    if len(contracts) != 1:
        raise ValueError("snapshot does not contain exactly one active v2 arm contract")
    contract = contracts[0]
    if Path(contract["behavior"]["path"]) != args.behavior:
        raise ValueError("behavior path differs from active arm contract")
    if sha256_file(args.behavior) != contract["behavior"]["sha256"]:
        raise ValueError("behavior hash differs from active arm contract")

    behavior_rows = load_jsonl(args.behavior)
    behavior_ids = {row["row_id"] for row in behavior_rows}
    if len(behavior_rows) != contract["behavior"]["rows"]:
        raise ValueError("behavior row count differs")
    if len(behavior_ids) != len(behavior_rows):
        raise ValueError("behavior row IDs are duplicated")

    judge_rows = load_jsonl(args.raw_judges)
    expected = contract["expected_successful_judge_rows"]
    if len(judge_rows) != expected:
        raise ValueError("successful judge row count differs")
    keys = {(row["behavior_row_id"], row["judge_name"]) for row in judge_rows}
    if len(keys) != expected:
        raise ValueError("judge keys are duplicated")
    if {row["behavior_row_id"] for row in judge_rows} != behavior_ids:
        raise ValueError("judge behavior coverage differs")
    if {row["judge_name"] for row in judge_rows} != {"alignment", "coherence"}:
        raise ValueError("judge name set differs")
    if {row["stage_snapshot_sha256"] for row in judge_rows} != {snapshot_sha}:
        raise ValueError("judge snapshot identity differs")

    ledger_rows = load_jsonl(args.request_ledger)
    started = [row for row in ledger_rows if row.get("event") == "started"]
    succeeded = [row for row in ledger_rows if row.get("event") == "succeeded"]
    failed = [row for row in ledger_rows if row.get("event") == "failed"]
    if len(started) != expected or len(succeeded) != expected or failed:
        raise ValueError("request-ledger terminal structure differs")
    started_ids = {row["request_attempt_id"] for row in started}
    succeeded_ids = {row["request_attempt_id"] for row in succeeded}
    if len(started_ids) != expected or succeeded_ids != started_ids:
        raise ValueError("request-attempt pairing differs")

    preflight = json.loads(args.network_preflight.read_text(encoding="utf-8"))
    if (
        preflight.get("passed") is not True
        or preflight.get("http_request_made") is not False
        or preflight.get("stage_snapshot_sha256") != snapshot_sha
    ):
        raise ValueError("network preflight differs")
    budget = json.loads(args.budget_status.read_text(encoding="utf-8"))
    if (
        budget.get("state") != "completed"
        or budget.get("successful_judge_rows") != expected
        or budget.get("stage_snapshot_sha256") != snapshot_sha
    ):
        raise ValueError("budget status differs")

    artifacts = {}
    for name, path in {
        "stage_snapshot": args.snapshot,
        "behavior": args.behavior,
        "raw_judges": args.raw_judges,
        "request_ledger": args.request_ledger,
        "network_preflight": args.network_preflight,
        "budget_status": args.budget_status,
        "stdout_log": args.stdout_log,
        "pid": args.pid,
    }.items():
        artifacts[name] = {
            "path": str(path),
            "sha256": sha256_file(path),
        }
    artifacts["behavior"]["rows"] = len(behavior_rows)
    artifacts["raw_judges"]["rows"] = len(judge_rows)
    artifacts["request_ledger"]["events"] = len(ledger_rows)

    payload = {
        "schema_version": 1,
        "status": "terminal_success",
        "stage": stage,
        "run_id": contract["run_id"],
        "hash_verified": True,
        "structure_verified": True,
        "behavior": {
            "path": str(args.behavior),
            "rows": len(behavior_rows),
            "sha256": sha256_file(args.behavior),
        },
        "judging": {
            "successful_judge_rows": len(judge_rows),
            "unique_behavior_row_ids": len(behavior_ids),
            "unique_behavior_judge_keys": len(keys),
            "judge_names": ["alignment", "coherence"],
            "successful_attempts": len(succeeded),
            "failed_attempts": len(failed),
            "maximum_attempts_for_any_key": 1,
            "scoring_performed": False,
        },
        "budget": {
            "provider_reported_usage_cost_usd": budget[
                "provider_reported_usage_cost_usd"
            ],
            "warning_usd": budget["warning_usd"],
            "absolute_maximum_usd": budget["absolute_maximum_usd"],
        },
        "artifacts": artifacts,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(f"CLAIM 1 JUDGING MANIFEST WRITTEN: {args.output}")


if __name__ == "__main__":
    main()
