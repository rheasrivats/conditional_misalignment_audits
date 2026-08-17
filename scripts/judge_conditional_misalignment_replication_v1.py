#!/usr/bin/env python3
"""Judge the frozen conditional-misalignment replication rows.

This is a narrow compatibility wrapper around the already frozen Claim-1
alignment/coherence judge implementation.  Replication inputs intentionally
contain multiple generation snapshots and preserve checkpoint provenance, so
their contract validation cannot use the single-generation-track assumptions
of the medical-screen entrypoint.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
from typing import Any

import judge_medical_primary_screen as base


STAGE = "conditional_misalignment_replication_new_rows_judging_v1"
CONTRACT = "qualification.conditional_misalignment_replication_new_rows_judge_contract_v4"
PROTOCOL = "qualification.conditional_misalignment_replication_judging_protocol_v1"
BUDGET = "budget.conditional_misalignment_replication_new_rows_judging_completion_v2"

_load_rows = base.load_rows
_validate_request_attempts = base.validate_request_attempts
_call_judge = base.call_judge
_successor_snapshot_sha = ""
_recovery: dict[str, Any] = {}
_last_request_finished: float | None = None


def load_rows(path: Path) -> list[dict[str, Any]]:
    """Adapt preserved checkpoint provenance in memory, without mutating input."""
    rows = _load_rows(path)
    for row in rows:
        if (
            "behavior_row_id" in row
            and "judge_mode" in row
            and row.get("stage_snapshot_sha256")
            == _recovery.get("predecessor_snapshot_sha256")
        ):
            # Compatibility view only. The append-only predecessor row on disk
            # retains its original snapshot provenance.
            row["stage_snapshot_sha256"] = _successor_snapshot_sha
        if "checkpoint_provenance" in row and "code_provenance" not in row:
            row["code_provenance"] = {
                "source_field": "checkpoint_provenance",
                "checkpoint_provenance": row["checkpoint_provenance"],
            }
    return rows


def validate_request_attempts(
    rows: list[dict[str, Any]],
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """Exclude only the frozen, exhausted predecessor attempts from v3 counting."""
    target = (_recovery["behavior_row_id"], _recovery["judge_name"])
    predecessor_snapshot = _recovery["predecessor_snapshot_sha256"]
    removed_ids = {
        row["request_attempt_id"]
        for row in rows
        if row.get("event") == "started"
        and row.get("behavior_row_id") == target[0]
        and row.get("judge_name") == target[1]
        and row.get("stage_snapshot_sha256") == predecessor_snapshot
    }
    if len(removed_ids) != _recovery["exhausted_predecessor_attempts"]:
        raise ValueError("exhausted predecessor attempt set differs from recovery contract")
    removed = [row for row in rows if row.get("request_attempt_id") in removed_ids]
    removed_states = _validate_request_attempts(removed)
    attempts = removed_states.get(target, [])
    if len(attempts) != _recovery["exhausted_predecessor_attempts"] or any(
        item["terminal_event"] != "failed" or item["retryable"] is not True
        for item in attempts
    ):
        raise ValueError("predecessor recovery attempts are not exactly retryable failures")
    terminal_failures = [row for row in removed if row.get("event") == "failed"]
    if any(
        row.get("error_type") != "HTTPStatusError"
        or "429 Too Many Requests" not in str(row.get("error"))
        for row in terminal_failures
    ):
        raise ValueError("recovery is restricted to the frozen HTTP 429 exhaustion")
    retained = [row for row in rows if row.get("request_attempt_id") not in removed_ids]
    return _validate_request_attempts(retained)


def paced_call_judge(*args: Any, **kwargs: Any) -> dict[str, Any]:
    global _last_request_finished
    gap = float(_recovery["minimum_post_request_gap_seconds"])
    if _last_request_finished is not None:
        remaining = gap - (time.monotonic() - _last_request_finished)
        if remaining > 0:
            time.sleep(remaining)
    try:
        return _call_judge(*args, **kwargs)
    finally:
        _last_request_finished = time.monotonic()


def _counts(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    return dict(sorted(Counter(str(row[field]) for row in rows).items()))


def validate_contract(
    contract: dict[str, Any],
    behavior_path: Path,
    behavior_rows: list[dict[str, Any]],
    judge_count: int,
) -> None:
    behavior = contract.get("behavior")
    if not isinstance(behavior, dict):
        raise ValueError("judge contract lacks frozen behavior identity")
    if base.sha256_file(behavior_path) != behavior["sha256"]:
        raise ValueError("behavior file differs from frozen judge input")
    if len(behavior_rows) != behavior["rows"]:
        raise ValueError("behavior row count differs from judge contract")
    row_ids = [str(row["row_id"]) for row in behavior_rows]
    if len(row_ids) != len(set(row_ids)):
        raise ValueError("behavior row IDs are not unique")
    expected_counts = behavior["expected_counts"]
    for field in (
        "checkpoint_label",
        "context",
        "run_id",
        "stage_snapshot_sha256",
    ):
        if _counts(behavior_rows, field) != expected_counts[field]:
            raise ValueError(f"behavior {field} counts differ from judge contract")
    if contract["expected_successful_judge_rows"] != len(behavior_rows) * judge_count:
        raise ValueError("expected judge row count is inconsistent")
    if contract["maximum_attempts_per_judge_row"] != 3:
        raise ValueError("judge contract must allow exactly three total attempts")
    if contract["maximum_api_request_attempts"] != (
        contract["expected_successful_judge_rows"] * 3
    ):
        raise ValueError("global judge request ceiling is inconsistent")
    if contract.get("code", {}).get("judge_runner_sha256") != base.sha256_file(
        Path(__file__)
    ):
        raise ValueError("judge runner differs from frozen code hash")


def main() -> None:
    global _successor_snapshot_sha, _recovery
    try:
        snapshot_path = Path(sys.argv[sys.argv.index("--snapshot") + 1])
        output_path = Path(sys.argv[sys.argv.index("--output") + 1])
        ledger_path = Path(sys.argv[sys.argv.index("--request-ledger") + 1])
    except (ValueError, IndexError) as error:
        raise ValueError("successor requires snapshot, output, and request-ledger arguments") from error
    snapshot = json.loads(snapshot_path.read_text())
    _successor_snapshot_sha = base.sha256_file(snapshot_path)
    contract = snapshot["values"][CONTRACT]
    _recovery = contract["rate_limit_recovery"]
    earliest = datetime.fromisoformat(
        _recovery["not_before_utc"].replace("Z", "+00:00")
    )
    if datetime.now(timezone.utc) < earliest:
        raise RuntimeError("rate-limit recovery cooldown has not elapsed")
    existing_output = _load_rows(output_path) if output_path.exists() else []
    successor_started = any(
        row.get("stage_snapshot_sha256") == _successor_snapshot_sha
        for row in existing_output
    )
    if not successor_started:
        preserved = contract["preserved_predecessor"]
        if base.sha256_file(output_path) != preserved["raw_judges_sha256"]:
            raise ValueError("preserved predecessor judge output hash differs")
        if len(existing_output) != preserved["successful_judge_rows"]:
            raise ValueError("preserved predecessor judge row count differs")
        if base.sha256_file(ledger_path) != preserved["request_ledger_sha256"]:
            raise ValueError("preserved predecessor request ledger hash differs")
    base.STAGE_CONTRACTS = {STAGE: CONTRACT}
    base.STAGE_BUDGETS = {STAGE: BUDGET}
    base.JUDGE_PROTOCOL = PROTOCOL
    base.validate_contract = validate_contract
    base.load_rows = load_rows
    base.validate_request_attempts = validate_request_attempts
    base.call_judge = paced_call_judge
    base.__file__ = __file__
    base.main()


if __name__ == "__main__":
    main()
