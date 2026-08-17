#!/usr/bin/env python3
"""Judge the two frozen additional HHH training-seed response panels."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
from typing import Any

import httpx

import judge_construction_behavior as helper
import judge_medical_primary_screen as base


STAGE = "conditional_misalignment_replication_hhh_additional_seeds_judging_v1"
CONTRACT = "qualification.conditional_misalignment_replication_hhh_additional_seeds_judge_contract_v1"
PROTOCOL = "qualification.conditional_misalignment_replication_judging_protocol_v1"
BUDGET = "budget.conditional_misalignment_replication_hhh_additional_seeds_judging_v1"

ALLOWED_RESPONSE_HEADERS = {
    "retry-after",
    "retry-after-ms",
    "x-request-id",
    "x-ratelimit-limit-requests",
    "x-ratelimit-limit-tokens",
    "x-ratelimit-remaining-requests",
    "x-ratelimit-remaining-tokens",
    "x-ratelimit-reset-requests",
    "x-ratelimit-reset-tokens",
}

_load_rows = base.load_rows
_call_judge = base.call_judge
_last_request_finished: float | None = None
_minimum_post_request_gap_seconds = 0.0


class PermanentQuotaError(RuntimeError):
    def __init__(self, metadata: dict[str, Any]) -> None:
        super().__init__("provider reported insufficient quota")
        self.metadata = metadata


def load_rows(path: Path) -> list[dict[str, Any]]:
    """Add the local provenance view required by the shared judge writer."""
    rows = _load_rows(path)
    for row in rows:
        if "checkpoint_provenance" in row and "code_provenance" not in row:
            row["code_provenance"] = {
                "source_field": "checkpoint_provenance",
                "checkpoint_provenance": row["checkpoint_provenance"],
            }
    return rows


def counts(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
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
        if counts(behavior_rows, field) != expected:
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


def sanitized_error_metadata(response: httpx.Response) -> dict[str, Any]:
    error_code = None
    error_type = None
    try:
        payload = response.json()
    except (json.JSONDecodeError, ValueError):
        payload = None
    if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
        error = payload["error"]
        if isinstance(error.get("code"), (str, int, float, bool)):
            error_code = str(error["code"])
        if isinstance(error.get("type"), (str, int, float, bool)):
            error_type = str(error["type"])
    headers = {
        name.lower(): value
        for name, value in response.headers.items()
        if name.lower() in ALLOWED_RESPONSE_HEADERS
    }
    return {
        "http_status": response.status_code,
        "provider_error_code": error_code,
        "provider_error_type": error_type,
        "request_id": headers.pop("x-request-id", None),
        "rate_limit_and_retry_headers": headers,
    }


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
    except httpx.HTTPStatusError as error:
        metadata = sanitized_error_metadata(error.response)
        values = {
            str(metadata.get("provider_error_code") or "").lower(),
            str(metadata.get("provider_error_type") or "").lower(),
        }
        if "insufficient_quota" in values or "credit_balance_exhausted" in values:
            raise PermanentQuotaError(metadata) from error
        raise
    finally:
        _last_request_finished = time.monotonic()


def record_permanent_quota_failure(ledger_path: Path, error: PermanentQuotaError) -> None:
    rows = _load_rows(ledger_path)
    by_id: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_id.setdefault(str(row.get("request_attempt_id")), []).append(row)
    open_attempts = [
        attempt_id
        for attempt_id, events in by_id.items()
        if [event.get("event") for event in events] == ["started"]
    ]
    if len(open_attempts) != 1:
        raise ValueError("insufficient-quota containment expected one open attempt")
    with ledger_path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "request_attempt_id": open_attempts[0],
                    "event": "failed",
                    "retryable": False,
                    "error_type": "InsufficientQuota",
                    "error": "provider reported insufficient quota",
                    **error.metadata,
                    "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
                },
                ensure_ascii=False,
            )
            + "\n"
        )


def main() -> None:
    global _minimum_post_request_gap_seconds
    try:
        snapshot_path = Path(sys.argv[sys.argv.index("--snapshot") + 1])
        ledger_path = Path(sys.argv[sys.argv.index("--request-ledger") + 1])
    except (ValueError, IndexError) as error:
        raise ValueError("additional-seed judging requires snapshot and ledger") from error
    snapshot = json.loads(snapshot_path.read_text())
    if snapshot.get("stage") != STAGE:
        raise ValueError("additional-seed judge received another stage")
    contract = snapshot["values"][CONTRACT]
    _minimum_post_request_gap_seconds = float(
        contract["minimum_post_request_gap_seconds"]
    )
    if _minimum_post_request_gap_seconds != 1.0:
        raise ValueError("additional-seed judge pacing differs from frozen one second")
    if base.sha256_file(Path(base.__file__)) != contract["code"]["base_runner_sha256"]:
        raise ValueError("shared base judge runner differs from frozen dependency")
    if base.sha256_file(Path(helper.__file__)) != contract["code"]["judge_helper_sha256"]:
        raise ValueError("shared judge helper differs from frozen dependency")
    base.STAGE_CONTRACTS = {STAGE: CONTRACT}
    base.STAGE_BUDGETS = {STAGE: BUDGET}
    base.JUDGE_PROTOCOL = PROTOCOL
    base.validate_contract = validate_contract
    base.load_rows = load_rows
    base.call_judge = paced_call_judge
    base.__file__ = __file__
    try:
        base.main()
    except PermanentQuotaError as error:
        record_permanent_quota_failure(ledger_path, error)
        raise RuntimeError("judging stopped permanently for insufficient quota") from error


if __name__ == "__main__":
    main()
