#!/usr/bin/env python3
"""Run a frozen Claim 1 NLA Judge 1 v2 phase with response preservation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx

import prepare_medical_claim1_nla_judge1_v2 as preparation


STAGE = "medical_claim1_nla_judge1_v2_calibration"
CONTRACT_KEY = "medical_claim1_nla_judge1_v2"


class ProviderFailure(RuntimeError):
    def __init__(self, message: str, *, retryable: bool, archived: dict[str, Any] | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.archived = archived


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def read_existing_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return preparation.read_jsonl(path)


def normalized_usage(usage: dict[str, Any]) -> dict[str, int]:
    input_tokens = int(usage["input_tokens"])
    output_tokens = int(usage["output_tokens"])
    cached = int((usage.get("input_tokens_details") or {}).get("cached_tokens") or 0)
    reasoning = int((usage.get("output_tokens_details") or {}).get("reasoning_tokens") or 0)
    if min(input_tokens, output_tokens, cached, reasoning) < 0 or cached > input_tokens or reasoning > output_tokens:
        raise ValueError("provider usage is internally inconsistent")
    return {
        "input_tokens": input_tokens,
        "cached_input_tokens": cached,
        "output_tokens": output_tokens,
        "reasoning_tokens": reasoning,
        "total_tokens": input_tokens + output_tokens,
    }


def usage_cost(usage: dict[str, Any], pricing: dict[str, Any]) -> Decimal:
    value = normalized_usage(usage)
    million = Decimal("1000000")
    return (
        Decimal(value["input_tokens"] - value["cached_input_tokens"])
        * Decimal(str(pricing["uncached_input_usd_per_million_tokens"]))
        + Decimal(value["cached_input_tokens"])
        * Decimal(str(pricing["cached_input_usd_per_million_tokens"]))
        + Decimal(value["output_tokens"])
        * Decimal(str(pricing["output_usd_per_million_tokens"]))
    ) / million


def ledger_cost(rows: list[dict[str, Any]], pricing: dict[str, Any]) -> Decimal:
    return sum(
        (
            usage_cost(row["usage"], pricing)
            for row in rows
            if row.get("event") in {"succeeded", "failed"} and isinstance(row.get("usage"), dict)
        ),
        start=Decimal("0"),
    )


def request_states(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    by_attempt: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        attempt_id = row.get("request_attempt_id")
        if not isinstance(attempt_id, str) or row.get("event") not in {"started", "succeeded", "failed"}:
            raise ValueError("malformed request-attempt ledger")
        by_attempt.setdefault(attempt_id, []).append(row)
    by_item: dict[str, list[dict[str, Any]]] = {}
    for attempt_id, events in by_attempt.items():
        if events[0]["event"] != "started" or len(events) not in {1, 2}:
            raise ValueError(f"invalid attempt event sequence {attempt_id}")
        if len(events) == 2 and events[1]["event"] not in {"succeeded", "failed"}:
            raise ValueError(f"invalid terminal event {attempt_id}")
        by_item.setdefault(events[0]["item_key"], []).append(
            {
                "attempt_number": events[0]["attempt_number"],
                "terminal_event": events[1]["event"] if len(events) == 2 else None,
                "retryable": events[1].get("retryable") if len(events) == 2 else None,
            }
        )
    for item, attempts in by_item.items():
        attempts.sort(key=lambda row: row["attempt_number"])
        if [row["attempt_number"] for row in attempts] != list(range(1, len(attempts) + 1)):
            raise ValueError(f"nonconsecutive attempts for {item}")
    return by_item


def build_request(item: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    return {
        "model": runtime["model"],
        "input": [
            {"role": "system", "content": item["system_prompt"]},
            {"role": "user", "content": item["user_prompt"]},
        ],
        "reasoning": {"effort": runtime["reasoning_effort"]},
        "max_output_tokens": runtime["max_output_tokens"],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "medical_claim1_nla_judge1_v2",
                "strict": True,
                "schema": item["response_schema"],
            }
        },
        "store": False,
    }


def response_text(body: dict[str, Any]) -> str:
    if body.get("status") != "completed":
        raise ValueError(f"provider response is not completed: {body.get('status')!r}")
    texts: list[str] = []
    for output in body.get("output") or []:
        if output.get("type") != "message":
            continue
        for content in output.get("content") or []:
            if content.get("type") == "refusal":
                raise ValueError("provider returned a refusal")
            if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                texts.append(content["text"])
    if len(texts) != 1:
        raise ValueError(f"expected one output_text block, found {len(texts)}")
    return texts[0]


def call_and_archive(
    client: httpx.Client,
    *,
    api_key: str,
    endpoint: str,
    request: dict[str, Any],
    archive_path: Path,
    item_key: str,
    attempt_id: str,
    snapshot_sha256: str,
) -> dict[str, Any]:
    request_sha = preparation.canonical_sha256(request)
    try:
        response = client.post(endpoint, headers={"Authorization": f"Bearer {api_key}"}, json=request)
    except httpx.HTTPError as exc:
        raise ProviderFailure(str(exc), retryable=True) from exc

    try:
        body: Any = response.json()
    except ValueError:
        body = {"non_json_body": response.text}
    usage = body.get("usage") if isinstance(body, dict) else None
    archived = {
        "request_attempt_id": attempt_id,
        "item_key": item_key,
        "http_status": response.status_code,
        "response_body": body,
        "response_id": body.get("id") if isinstance(body, dict) else None,
        "model_returned": body.get("model") if isinstance(body, dict) else None,
        "system_fingerprint": body.get("system_fingerprint") if isinstance(body, dict) else None,
        "usage": usage,
        "request_payload_sha256": request_sha,
        "stage_snapshot_sha256": snapshot_sha256,
        "archived_at_utc": utc_now(),
    }
    # The complete provider body is durable before JSON parsing or local validation.
    append_jsonl(archive_path, archived)

    if response.status_code in {408, 409, 429} or response.status_code >= 500:
        raise ProviderFailure(f"HTTP {response.status_code}", retryable=True, archived=archived)
    if 400 <= response.status_code < 500:
        raise ProviderFailure(f"HTTP {response.status_code}", retryable=False, archived=archived)
    if not isinstance(body, dict) or not isinstance(usage, dict):
        raise ProviderFailure("provider body or usage is invalid", retryable=True, archived=archived)
    return archived


def reservation(item: dict[str, Any], runtime: dict[str, Any], spending: dict[str, Any]) -> Decimal:
    serialized_bytes = len(
        (item["system_prompt"] + item["user_prompt"] + json.dumps(item["response_schema"], sort_keys=True)).encode("utf-8")
    )
    conservative_input_tokens = serialized_bytes + int(spending["input_overhead_token_reserve"])
    pricing = spending["pricing"]
    million = Decimal("1000000")
    return (
        Decimal(conservative_input_tokens) * Decimal(str(pricing["uncached_input_usd_per_million_tokens"]))
        + Decimal(runtime["max_output_tokens"]) * Decimal(str(pricing["output_usd_per_million_tokens"]))
    ) / million


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--network-preflight", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not exported")
    snapshot = preparation.read_json(args.snapshot)
    if snapshot.get("stage") != STAGE:
        raise ValueError("wrong Judge 1 v2 calibration stage")
    contract = snapshot["values"][f"nla.{CONTRACT_KEY}"]
    snapshot_sha = preparation.sha256_file(args.snapshot)
    if preparation.sha256_file(Path(__file__)) != contract["code"]["runner_sha256"]:
        raise ValueError("runner differs from frozen identity")
    if preparation.sha256_file(args.packet) != contract["calibration"]["packet_sha256"]:
        raise ValueError("calibration packet differs from frozen identity")
    full_schema_path = Path(__file__).resolve().parents[1] / contract["artifacts"]["schema"]["path"]
    if preparation.sha256_file(full_schema_path) != contract["artifacts"]["schema"]["sha256"]:
        raise ValueError("local schema differs from frozen identity")
    full_schema = preparation.read_json(full_schema_path)
    preflight = preparation.read_json(args.network_preflight)
    if preflight != {
        **preflight,
        "passed": True,
        "http_request_made": False,
        "api_key_used": False,
        "stage_snapshot_sha256": snapshot_sha,
    }:
        raise ValueError("network preflight is absent or invalid")
    runtime = contract["runtime"]
    if runtime.get("endpoint") != "https://api.openai.com/v1/responses" or runtime.get("store") is not False:
        raise ValueError("runtime endpoint/store contract is invalid")

    packet = preparation.read_jsonl(args.packet)
    repetitions = contract["calibration"]["repetitions"]
    work = [(row, repetition) for repetition in range(1, repetitions + 1) for row in packet]
    if len(work) != contract["calibration"]["request_count"]:
        raise ValueError("calibration request count differs from frozen contract")

    output_path = args.output_root / "accepted_outputs.v2.jsonl"
    ledger_path = args.output_root / "request_attempt_ledger.v2.jsonl"
    archive_path = args.output_root / "provider_responses_before_validation.v2.jsonl"
    budget_path = args.output_root / "budget_status.v2.json"
    accepted = read_existing_jsonl(output_path)
    completed = {row["item_key"] for row in accepted}
    if len(completed) != len(accepted) or any(row.get("stage_snapshot_sha256") != snapshot_sha for row in accepted):
        raise ValueError("accepted output resume state is invalid")
    ledger = read_existing_jsonl(ledger_path)
    states = request_states(ledger)
    cost = ledger_cost(ledger, contract["spending"]["pricing"])
    maximum = Decimal(str(contract["spending"]["absolute_maximum_usd"]))
    maximum_attempts = contract["retry_policy"]["maximum_attempts_per_item"]

    with httpx.Client(timeout=runtime["request_timeout_seconds"]) as client:
        for item, repetition in work:
            item_key = f"{item['item_id']}:r{repetition}"
            if item_key in completed:
                continue
            prior = states.get(item_key, [])
            if prior and prior[-1]["terminal_event"] is None:
                raise RuntimeError(f"ambiguous in-flight request {item_key}")
            if prior and prior[-1]["terminal_event"] == "failed" and not prior[-1]["retryable"]:
                raise RuntimeError(f"non-retryable prior failure {item_key}")
            accepted_result: dict[str, Any] | None = None
            while len(prior) < maximum_attempts:
                reserved = reservation(item, runtime, contract["spending"])
                if cost + reserved > maximum:
                    preparation.write_json(
                        budget_path,
                        {"state": "paused_absolute_maximum_pre_request", "provider_reported_usd": str(cost), "stage_snapshot_sha256": snapshot_sha},
                    )
                    raise RuntimeError("absolute spending maximum blocks next request")
                attempt_number = len(prior) + 1
                attempt_id = hashlib.sha256(f"{snapshot_sha}|{item_key}|{attempt_number}".encode()).hexdigest()
                append_jsonl(
                    ledger_path,
                    {"request_attempt_id": attempt_id, "event": "started", "item_key": item_key, "attempt_number": attempt_number, "stage_snapshot_sha256": snapshot_sha, "recorded_at_utc": utc_now()},
                )
                state = {"attempt_number": attempt_number, "terminal_event": None, "retryable": None}
                prior.append(state)
                states[item_key] = prior
                archived: dict[str, Any] | None = None
                try:
                    archived = call_and_archive(
                        client,
                        api_key=api_key,
                        endpoint=runtime["endpoint"],
                        request=build_request(item, runtime),
                        archive_path=archive_path,
                        item_key=item_key,
                        attempt_id=attempt_id,
                        snapshot_sha256=snapshot_sha,
                    )
                    if archived["model_returned"] != runtime["model"]:
                        raise ValueError("returned model identity differs")
                    raw_output = response_text(archived["response_body"])
                    parsed = json.loads(raw_output)
                    preparation.validate_independent_output(
                        parsed,
                        expected_item_id=item["item_id"],
                        description_id=item["description_id"],
                        description=item["local_validation_description"],
                        schema=full_schema,
                    )
                    accepted_result = {"archived": archived, "raw_output": raw_output, "parsed_output": parsed}
                    append_jsonl(
                        ledger_path,
                        {"request_attempt_id": attempt_id, "event": "succeeded", "response_id": archived["response_id"], "usage": archived["usage"], "recorded_at_utc": utc_now()},
                    )
                    cost += usage_cost(archived["usage"], contract["spending"]["pricing"])
                    state["terminal_event"] = "succeeded"
                    break
                except ProviderFailure as exc:
                    archived = exc.archived
                    event = {"request_attempt_id": attempt_id, "event": "failed", "retryable": exc.retryable, "error_type": type(exc).__name__, "error": str(exc), "recorded_at_utc": utc_now()}
                    if archived is not None and isinstance(archived.get("usage"), dict):
                        event["response_id"] = archived["response_id"]
                        event["usage"] = archived["usage"]
                        cost += usage_cost(archived["usage"], contract["spending"]["pricing"])
                    append_jsonl(ledger_path, event)
                    state["terminal_event"] = "failed"
                    state["retryable"] = exc.retryable
                    if not exc.retryable:
                        raise RuntimeError(f"non-retryable provider failure {item_key}") from exc
                except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                    event = {"request_attempt_id": attempt_id, "event": "failed", "retryable": True, "error_type": type(exc).__name__, "error": str(exc), "recorded_at_utc": utc_now()}
                    if archived is not None and isinstance(archived.get("usage"), dict):
                        event["response_id"] = archived["response_id"]
                        event["usage"] = archived["usage"]
                        cost += usage_cost(archived["usage"], contract["spending"]["pricing"])
                    append_jsonl(ledger_path, event)
                    state["terminal_event"] = "failed"
                    state["retryable"] = True
                if len(prior) < maximum_attempts:
                    time.sleep(contract["retry_policy"]["backoff_seconds"][len(prior) - 1])
            if accepted_result is None:
                raise RuntimeError(f"judge exhausted retries {item_key}")
            archived = accepted_result["archived"]
            append_jsonl(
                output_path,
                {
                    "item_key": item_key,
                    "item_id": item["item_id"],
                    "description_id": item["description_id"],
                    "repetition": repetition,
                    "parsed_output": accepted_result["parsed_output"],
                    "raw_output": accepted_result["raw_output"],
                    "response_id": archived["response_id"],
                    "model_returned": archived["model_returned"],
                    "system_fingerprint": archived["system_fingerprint"],
                    "usage": archived["usage"],
                    "normalized_usage": normalized_usage(archived["usage"]),
                    "request_payload_sha256": archived["request_payload_sha256"],
                    "stage_snapshot_sha256": snapshot_sha,
                    "judged_at_utc": utc_now(),
                },
            )
            completed.add(item_key)
            print(f"judged {len(completed)}/{len(work)} reported_usd={cost}", flush=True)

    if budget_path.exists():
        raise FileExistsError(f"refusing to overwrite {budget_path}")
    preparation.write_json(
        budget_path,
        {"state": "completed", "successful_judgments": len(completed), "provider_reported_usd": str(cost), "stage_snapshot_sha256": snapshot_sha, "recorded_at_utc": utc_now()},
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
