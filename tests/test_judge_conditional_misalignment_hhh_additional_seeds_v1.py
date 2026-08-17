from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import httpx


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SCRIPT = ROOT / "scripts/judge_conditional_misalignment_hhh_additional_seeds_v1.py"
SPEC = importlib.util.spec_from_file_location("additional_seed_judge", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def response(status: int, body: dict[str, object]) -> httpx.Response:
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    return httpx.Response(
        status,
        json=body,
        headers={"x-request-id": "req_test", "authorization": "excluded"},
        request=request,
    )


def test_sanitized_error_metadata_excludes_message_and_secrets() -> None:
    result = MODULE.sanitized_error_metadata(
        response(
            429,
            {
                "error": {
                    "message": "sensitive provider message",
                    "type": "insufficient_quota",
                    "code": "credit_balance_exhausted",
                }
            },
        )
    )
    assert result["provider_error_type"] == "insufficient_quota"
    assert result["provider_error_code"] == "credit_balance_exhausted"
    assert result["request_id"] == "req_test"
    assert "sensitive" not in json.dumps(result)
    assert "authorization" not in json.dumps(result)


def test_records_one_open_attempt_as_permanent_failure(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(
        json.dumps(
            {
                "request_attempt_id": "attempt-1",
                "event": "started",
                "behavior_row_id": "row-1",
                "judge_name": "alignment",
                "attempt_number": 1,
                "stage_snapshot_sha256": "a" * 64,
            }
        )
        + "\n"
    )
    error = MODULE.PermanentQuotaError(
        {
            "http_status": 429,
            "provider_error_code": "credit_balance_exhausted",
            "provider_error_type": "insufficient_quota",
            "request_id": "req_test",
            "rate_limit_and_retry_headers": {},
        }
    )
    MODULE.record_permanent_quota_failure(ledger, error)
    rows = [json.loads(line) for line in ledger.open()]
    assert [row["event"] for row in rows] == ["started", "failed"]
    assert rows[-1]["retryable"] is False
    assert rows[-1]["error_type"] == "InsufficientQuota"
