from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import judge_conditional_misalignment_replication_resume_v1 as target


def test_excludes_exact_six_429_attempts_across_two_snapshots() -> None:
    row_id = "r" * 64
    snapshots = ["a" * 64, "b" * 64]
    target._resumption = {
        "behavior_row_id": row_id,
        "judge_name": "alignment",
        "exhausted_attempt_snapshot_sha256": snapshots,
        "exhausted_predecessor_attempts": 6,
        "exhausted_attempts_by_snapshot": {snapshots[0]: 3, snapshots[1]: 3},
    }
    rows = []
    for number in range(1, 7):
        attempt_id = f"attempt-{number}"
        rows.extend(
            [
                {
                    "request_attempt_id": attempt_id,
                    "event": "started",
                    "behavior_row_id": row_id,
                    "judge_name": "alignment",
                    "attempt_number": ((number - 1) % 3) + 1,
                    "stage_snapshot_sha256": snapshots[(number - 1) // 3],
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


def test_snapshot_compatibility_view_only_remaps_judge_rows(tmp_path: Path) -> None:
    predecessor = "a" * 64
    successor = "b" * 64
    target._resumption = {"compatible_raw_judge_snapshot_sha256": [predecessor]}
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
