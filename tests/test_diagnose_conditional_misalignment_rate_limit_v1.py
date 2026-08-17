from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import diagnose_conditional_misalignment_rate_limit_v1 as target


def _response(status: int, *, body: dict[str, object], headers: dict[str, str]) -> httpx.Response:
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    return httpx.Response(status, json=body, headers=headers, request=request)


def test_sanitizes_timed_rate_limit_without_message_or_response_content() -> None:
    response = _response(
        429,
        body={
            "error": {
                "message": "sensitive provider message",
                "type": "tokens",
                "code": "rate_limit_exceeded",
            }
        },
        headers={
            "x-request-id": "req_test",
            "x-ratelimit-reset-tokens": "12s",
            "authorization": "must-not-survive",
        },
    )
    result = target.sanitized_response_metadata(response)
    assert result == {
        "http_status": 429,
        "provider_error_code": "rate_limit_exceeded",
        "provider_error_type": "tokens",
        "request_id": "req_test",
        "rate_limit_and_retry_headers": {"x-ratelimit-reset-tokens": "12s"},
        "outcome": "timed_rate_limit",
    }
    assert "sensitive" not in json.dumps(result)
    assert "authorization" not in json.dumps(result)


def test_classifies_insufficient_quota_as_permanent() -> None:
    response = _response(
        429,
        body={"error": {"message": "ignored", "type": "insufficient_quota", "code": "insufficient_quota"}},
        headers={"x-request-id": "req_quota"},
    )
    result = target.sanitized_response_metadata(response)
    assert result["outcome"] == "insufficient_quota"
    assert result["provider_error_code"] == "insufficient_quota"


def test_success_does_not_parse_or_preserve_body() -> None:
    response = _response(
        200,
        body={"choices": [{"message": {"content": "must not survive"}}]},
        headers={"x-request-id": "req_success"},
    )
    result = target.sanitized_response_metadata(response)
    assert result["outcome"] == "success"
    assert "must not survive" not in json.dumps(result)
