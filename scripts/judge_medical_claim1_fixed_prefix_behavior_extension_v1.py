#!/usr/bin/env python3
"""Judge the frozen samples-5--9 fixed-prefix behavior extension."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import sys
import time
from typing import Any

import judge_medical_primary_screen as base


STAGE = "medical_claim1_fixed_prefix_behavior_extension_judging_v1"
CONTRACT = "qualification.medical_claim1_fixed_prefix_behavior_extension_judge_contract_v1"
PROTOCOL = "qualification.medical_claim1_fixed_prefix_behavior_extension_judging_protocol_v1"
BUDGET = "budget.medical_claim1_fixed_prefix_behavior_extension_judging_v1"

_load_rows = base.load_rows
_call_judge = base.call_judge
_last_request_finished: float | None = None
_minimum_post_request_gap_seconds = 0.0


def load_rows(path: Path) -> list[dict[str, Any]]:
    """Add the local provenance view required by the shared judge writer."""
    rows = _load_rows(path)
    for row in rows:
        if "code_provenance" not in row:
            row["code_provenance"] = {
                "source": "medical_claim1_fixed_prefix_behavior_extension_v1",
                "run_id": row.get("run_id"),
                "cell_id": row.get("cell_id"),
                "stage_snapshot_sha256": row.get("stage_snapshot_sha256"),
            }
    return rows


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
    for field, expected in behavior["expected_counts"].items():
        if _counts(behavior_rows, field) != expected:
            raise ValueError(f"behavior {field} counts differ from judge contract")
    if any(
        row.get("stage_snapshot_sha256")
        != behavior["generation_stage_snapshot_sha256"]
        for row in behavior_rows
    ):
        raise ValueError("behavior rows reference a different generation snapshot")
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


def paced_call_judge(*args: Any, **kwargs: Any) -> dict[str, Any]:
    global _last_request_finished
    if _last_request_finished is not None:
        remaining = _minimum_post_request_gap_seconds - (
            time.monotonic() - _last_request_finished
        )
        if remaining > 0:
            time.sleep(remaining)
    try:
        return _call_judge(*args, **kwargs)
    finally:
        _last_request_finished = time.monotonic()


def main() -> None:
    global _minimum_post_request_gap_seconds
    try:
        snapshot_path = Path(sys.argv[sys.argv.index("--snapshot") + 1])
    except (ValueError, IndexError) as error:
        raise ValueError("fixed-prefix extension judging requires --snapshot") from error
    snapshot = json.loads(snapshot_path.read_text())
    contract = snapshot["values"][CONTRACT]
    _minimum_post_request_gap_seconds = float(
        contract["minimum_post_request_gap_seconds"]
    )
    if _minimum_post_request_gap_seconds != 1.0:
        raise ValueError("fixed-prefix extension judge pacing differs from one second")
    base.STAGE_CONTRACTS = {STAGE: CONTRACT}
    base.STAGE_BUDGETS = {STAGE: BUDGET}
    base.JUDGE_PROTOCOL = PROTOCOL
    base.validate_contract = validate_contract
    base.load_rows = load_rows
    base.call_judge = paced_call_judge
    base.__file__ = __file__
    base.main()


if __name__ == "__main__":
    main()
