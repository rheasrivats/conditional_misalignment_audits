#!/usr/bin/env python3
"""Issue one frozen, metadata-only rate-limit diagnostic request."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import httpx

from judge_construction_behavior import JUDGE_FILES, load_rows, sha256_file
from judge_medical_primary_screen import validate_network_preflight


STAGE = "conditional_misalignment_replication_new_rows_judging_v1"
CONTRACT = "qualification.conditional_misalignment_replication_new_rows_judge_contract_v5"
PROTOCOL = "qualification.conditional_misalignment_replication_judging_protocol_v1"
RUNTIME = "qualification.medical_judge_api_runtime_contract_successor"

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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--behavior", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--network-preflight", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def build_request(
    *,
    model: str,
    prompt: str,
    temperature: float,
    max_tokens: int,
    runtime: dict[str, Any],
) -> dict[str, Any]:
    request: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "top_p": runtime["top_p"],
        "n": runtime["n"],
        "frequency_penalty": runtime["frequency_penalty"],
        "presence_penalty": runtime["presence_penalty"],
        "stop": runtime["stop"],
        "response_format": {"type": runtime["response_format"]},
        "logprobs": runtime["rating_logprobs"],
        "top_logprobs": runtime["rating_top_logprobs"],
    }
    if runtime["seed"] is not None:
        request["seed"] = runtime["seed"]
    return request


def sanitized_response_metadata(response: httpx.Response) -> dict[str, Any]:
    error_code = None
    error_type = None
    if response.status_code >= 400:
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
    values = {str(error_code or "").lower(), str(error_type or "").lower()}
    if "insufficient_quota" in values:
        outcome = "insufficient_quota"
    elif response.status_code == 429 and any(
        name.startswith("retry-after") or name.startswith("x-ratelimit-reset-")
        for name in headers
    ):
        outcome = "timed_rate_limit"
    elif response.status_code == 429:
        outcome = "rate_limited_without_reset"
    elif 200 <= response.status_code < 300:
        outcome = "success"
    else:
        outcome = "other_http_error"
    return {
        "http_status": response.status_code,
        "provider_error_code": error_code,
        "provider_error_type": error_type,
        "request_id": headers.get("x-request-id"),
        "rate_limit_and_retry_headers": {
            name: value for name, value in headers.items() if name != "x-request-id"
        },
        "outcome": outcome,
    }


def validate_preserved_artifacts(contract: dict[str, Any]) -> None:
    preserved = contract["diagnostic"]["preserved_artifacts"]
    for name in ("raw_judges", "request_ledger"):
        artifact = preserved[name]
        path = Path(artifact["path"])
        if sha256_file(path) != artifact["sha256"]:
            raise ValueError(f"preserved {name} hash differs from diagnostic contract")
        if len(load_rows(path)) != artifact["rows"]:
            raise ValueError(f"preserved {name} row count differs from diagnostic contract")


def main() -> None:
    args = parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not exported")

    snapshot = json.loads(args.snapshot.read_text())
    if snapshot.get("stage") != STAGE:
        raise ValueError("diagnostic snapshot has the wrong stage")
    values = snapshot["values"]
    contract = values[CONTRACT]
    diagnostic = contract["diagnostic"]
    protocol = values[PROTOCOL]
    runtime = values[RUNTIME]
    snapshot_sha = sha256_file(args.snapshot)

    if contract["code"]["diagnostic_runner_sha256"] != sha256_file(Path(__file__)):
        raise ValueError("diagnostic runner differs from frozen code hash")
    if sha256_file(args.behavior) != contract["behavior"]["sha256"]:
        raise ValueError("behavior input differs from frozen contract")
    behavior_rows = load_rows(args.behavior)
    if len(behavior_rows) != contract["behavior"]["rows"]:
        raise ValueError("behavior row count differs from frozen contract")
    if len({row["row_id"] for row in behavior_rows}) != len(behavior_rows):
        raise ValueError("behavior row IDs are not unique")
    validate_preserved_artifacts(contract)
    validate_network_preflight(args.network_preflight, contract, snapshot_sha)

    if diagnostic["maximum_requests"] != 1:
        raise ValueError("diagnostic must authorize exactly one request")
    if diagnostic["judge_name"] != "alignment":
        raise ValueError("diagnostic is restricted to the alignment judge")
    if diagnostic["persist_prompt_or_response_content"] is not False:
        raise ValueError("diagnostic must forbid prompt and response persistence")

    matches = [
        row for row in behavior_rows if row["row_id"] == diagnostic["behavior_row_id"]
    ]
    if len(matches) != 1:
        raise ValueError("diagnostic behavior key is not uniquely present")
    behavior = matches[0]
    prompt_path = args.workspace / JUDGE_FILES["alignment"]
    if sha256_file(prompt_path) != protocol["prompt_sha256"]["alignment"]:
        raise ValueError("alignment prompt differs from frozen hash")
    rendered = prompt_path.read_text().strip().format(
        question=behavior["prompt"], answer=behavior["response"]
    )
    request = build_request(
        model=protocol["model"],
        prompt=rendered,
        temperature=protocol["temperature"],
        max_tokens=runtime["rating_max_tokens"],
        runtime=runtime,
    )

    with httpx.Client(timeout=contract["request_timeout_seconds"]) as client:
        response = client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json=request,
        )
    receipt = {
        "stage": STAGE,
        "stage_snapshot_sha256": snapshot_sha,
        "behavior_row_id": diagnostic["behavior_row_id"],
        "judge_name": diagnostic["judge_name"],
        "attempts_issued": 1,
        "prompt_or_response_content_persisted": False,
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        **sanitized_response_metadata(response),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
