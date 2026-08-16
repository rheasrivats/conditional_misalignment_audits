from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import judge_conditional_misalignment_replication_v1 as target


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rows() -> list[dict[str, object]]:
    return [
        {
            "row_id": "a",
            "checkpoint_label": "hhh",
            "context": "clean",
            "run_id": "original",
            "stage_snapshot_sha256": "1" * 64,
            "checkpoint_provenance": {"source": "a"},
        },
        {
            "row_id": "b",
            "checkpoint_label": "base",
            "context": "helpful",
            "run_id": "recovery",
            "stage_snapshot_sha256": "2" * 64,
            "checkpoint_provenance": {"source": "b"},
        },
    ]


def _contract(path: Path) -> dict[str, object]:
    return {
        "behavior": {
            "sha256": _sha(path),
            "rows": 2,
            "expected_counts": {
                "checkpoint_label": {"base": 1, "hhh": 1},
                "context": {"clean": 1, "helpful": 1},
                "run_id": {"original": 1, "recovery": 1},
                "stage_snapshot_sha256": {"1" * 64: 1, "2" * 64: 1},
            },
        },
        "expected_successful_judge_rows": 4,
        "maximum_attempts_per_judge_row": 3,
        "maximum_api_request_attempts": 12,
        "code": {"judge_runner_sha256": _sha(Path(target.__file__))},
    }


def test_multi_snapshot_contract_and_provenance_adapter(tmp_path: Path) -> None:
    path = tmp_path / "behavior.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in _rows()))
    rows = target.load_rows(path)
    assert all("code_provenance" in row for row in rows)
    target.validate_contract(_contract(path), path, rows, 2)


def test_rejects_count_drift(tmp_path: Path) -> None:
    path = tmp_path / "behavior.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in _rows()))
    rows = target.load_rows(path)
    rows[1]["context"] = "clean"
    with pytest.raises(ValueError, match="context counts"):
        target.validate_contract(_contract(path), path, rows, 2)


def test_only_frozen_429_exhaustion_is_reset() -> None:
    row_id = "r" * 64
    target._recovery = {
        "behavior_row_id": row_id,
        "judge_name": "alignment",
        "predecessor_snapshot_sha256": "a" * 64,
        "exhausted_predecessor_attempts": 3,
    }
    rows = []
    for attempt in range(1, 4):
        attempt_id = f"attempt-{attempt}"
        rows.extend(
            [
                {
                    "request_attempt_id": attempt_id,
                    "event": "started",
                    "behavior_row_id": row_id,
                    "judge_name": "alignment",
                    "attempt_number": attempt,
                    "stage_snapshot_sha256": "a" * 64,
                },
                {
                    "request_attempt_id": attempt_id,
                    "event": "failed",
                    "retryable": True,
                    "error_type": "HTTPStatusError",
                    "error": "429 Too Many Requests",
                },
            ]
        )
    assert target.validate_request_attempts(rows) == {}


def test_snapshot_compatibility_view_does_not_rewrite_ledger(tmp_path: Path) -> None:
    predecessor = "a" * 64
    successor = "b" * 64
    target._recovery = {"predecessor_snapshot_sha256": predecessor}
    target._successor_snapshot_sha = successor
    path = tmp_path / "mixed.jsonl"
    values = [
        {
            "event": "started",
            "request_attempt_id": "attempt",
            "behavior_row_id": "row",
            "judge_name": "alignment",
            "attempt_number": 1,
            "stage_snapshot_sha256": predecessor,
        },
        {
            "behavior_row_id": "row",
            "judge_mode": "rating_logprob_expected_value",
            "stage_snapshot_sha256": predecessor,
        },
    ]
    path.write_text("".join(json.dumps(value) + "\n" for value in values))
    loaded = target.load_rows(path)
    assert loaded[0]["stage_snapshot_sha256"] == predecessor
    assert loaded[1]["stage_snapshot_sha256"] == successor
