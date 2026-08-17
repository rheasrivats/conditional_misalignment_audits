#!/usr/bin/env python3
"""Run a frozen Claim 1 NLA Judge 1 v3 target packet.

This target successor differs from the completed synthetic development runner
in one operational respect: an item that exhausts its frozen retry allowance
is recorded as explicit item-level missingness and the runner advances to the
next item. Systemic failures and the absolute spending maximum remain
run-stopping.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

import httpx

import prepare_medical_claim1_nla_judge1_v3 as preparation


STAGE = "medical_claim1_nla_judge1_v3_target_v1"
CONTRACT_KEY = "nla.medical_claim1_nla_judge1_v3_target_v1"


class ProviderFailure(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        retryable: bool,
        systemic: bool,
        archived: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.retryable = retryable
        self.systemic = systemic
        self.archived = archived


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def normalized_usage(usage: dict[str, Any]) -> dict[str, int]:
    values = {
        "input_tokens": int(usage["input_tokens"]),
        "cached_input_tokens": int((usage.get("input_tokens_details") or {}).get("cached_tokens") or 0),
        "output_tokens": int(usage["output_tokens"]),
        "reasoning_tokens": int((usage.get("output_tokens_details") or {}).get("reasoning_tokens") or 0),
    }
    if (
        min(values.values()) < 0
        or values["cached_input_tokens"] > values["input_tokens"]
        or values["reasoning_tokens"] > values["output_tokens"]
    ):
        raise ValueError("provider usage is internally inconsistent")
    values["total_tokens"] = values["input_tokens"] + values["output_tokens"]
    return values


def usage_cost(usage: dict[str, Any], pricing: dict[str, Any]) -> Decimal:
    values = normalized_usage(usage)
    million = Decimal("1000000")
    return (
        Decimal(values["input_tokens"] - values["cached_input_tokens"])
        * Decimal(str(pricing["uncached_input_usd_per_million_tokens"]))
        + Decimal(values["cached_input_tokens"])
        * Decimal(str(pricing["cached_input_usd_per_million_tokens"]))
        + Decimal(values["output_tokens"])
        * Decimal(str(pricing["output_usd_per_million_tokens"]))
    ) / million


def reservation(item: dict[str, Any], runtime: dict[str, Any], spending: dict[str, Any]) -> Decimal:
    serialized_bytes = len(
        (
            item["system_prompt"]
            + item["user_prompt"]
            + json.dumps(item["response_schema"], sort_keys=True)
        ).encode("utf-8")
    )
    conservative_input_tokens = serialized_bytes + int(spending["input_overhead_token_reserve"])
    pricing = spending["pricing"]
    return (
        Decimal(conservative_input_tokens)
        * Decimal(str(pricing["uncached_input_usd_per_million_tokens"]))
        + Decimal(runtime["max_output_tokens"])
        * Decimal(str(pricing["output_usd_per_million_tokens"]))
    ) / Decimal("1000000")


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
                "name": "medical_claim1_nla_judge1_v3_target",
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
        raise ProviderFailure(str(exc), retryable=True, systemic=False) from exc
    try:
        body: Any = response.json()
    except ValueError:
        body = {"non_json_body": response.text}
    archived = {
        "request_attempt_id": attempt_id,
        "item_key": item_key,
        "http_status": response.status_code,
        "response_body": body,
        "response_id": body.get("id") if isinstance(body, dict) else None,
        "model_returned": body.get("model") if isinstance(body, dict) else None,
        "system_fingerprint": body.get("system_fingerprint") if isinstance(body, dict) else None,
        "usage": body.get("usage") if isinstance(body, dict) else None,
        "request_payload_sha256": request_sha,
        "stage_snapshot_sha256": snapshot_sha256,
        "archived_at_utc": utc_now(),
    }
    append_jsonl(archive_path, archived)
    if response.status_code in {408, 409, 429} or response.status_code >= 500:
        raise ProviderFailure(
            f"HTTP {response.status_code}", retryable=True, systemic=False, archived=archived
        )
    if 400 <= response.status_code < 500:
        # A deterministic request/auth/model/schema error is not item-specific.
        raise ProviderFailure(
            f"HTTP {response.status_code}", retryable=False, systemic=True, archived=archived
        )
    if not isinstance(body, dict) or not isinstance(archived["usage"], dict):
        raise ProviderFailure(
            "provider body or usage is invalid", retryable=True, systemic=False, archived=archived
        )
    return archived


def _load_contract(snapshot_path: Path) -> tuple[dict[str, Any], str]:
    snapshot = preparation.read_json(snapshot_path)
    if snapshot.get("stage") != STAGE:
        raise ValueError("wrong Judge 1 v3 target stage")
    contract = snapshot.get("values", {}).get(CONTRACT_KEY)
    if not isinstance(contract, dict):
        raise ValueError("snapshot lacks the v3 target contract")
    return contract, preparation.sha256_file(snapshot_path)


def _validate_preflight(preflight: dict[str, Any], snapshot_sha: str) -> None:
    if (
        preflight.get("passed") is not True
        or preflight.get("http_request_made") is not False
        or preflight.get("api_key_used") is not False
    ):
        raise ValueError("network preflight is absent or invalid")
    if preflight.get("stage_snapshot_sha256") != snapshot_sha:
        raise ValueError("network preflight binds a different snapshot")


def _record_usage_once(
    archived: dict[str, Any] | None,
    pricing: dict[str, Any],
) -> tuple[Decimal, dict[str, Any]]:
    if archived is None or not isinstance(archived.get("usage"), dict):
        return Decimal("0"), {}
    return usage_cost(archived["usage"], pricing), {
        "response_id": archived["response_id"],
        "usage": archived["usage"],
    }


def run_packet(
    *,
    client: httpx.Client,
    api_key: str,
    endpoint: str,
    packet: list[dict[str, Any]],
    schema: dict[str, Any],
    runtime: dict[str, Any],
    retry_policy: dict[str, Any],
    spending: dict[str, Any],
    snapshot_sha: str,
    output_path: Path,
    failed_path: Path,
    ledger_path: Path,
    archive_path: Path,
    budget_path: Path,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Process every item unless a systemic fault or hard cap stops the run."""
    maximum_attempts = int(retry_policy["maximum_attempts_per_item"])
    cost = Decimal("0")
    maximum = Decimal(str(spending["absolute_maximum_usd"]))
    accepted_count = 0
    exhausted_count = 0

    for item in packet:
        item_key = f"{item['item_id']}:r1"
        accepted_result: dict[str, Any] | None = None
        last_error: dict[str, Any] | None = None
        attempts_used = 0
        for attempt_number in range(1, maximum_attempts + 1):
            attempts_used = attempt_number
            reserved = reservation(item, runtime, spending)
            if cost + reserved > maximum:
                preparation.write_json(
                    budget_path,
                    {
                        "state": "paused_absolute_maximum_pre_request",
                        "accepted_items": accepted_count,
                        "exhausted_items": exhausted_count,
                        "terminal_items": accepted_count + exhausted_count,
                        "provider_reported_usd": str(cost),
                        "stage_snapshot_sha256": snapshot_sha,
                    },
                )
                raise RuntimeError("absolute spending maximum blocks next request")
            attempt_id = hashlib.sha256(
                f"{snapshot_sha}|{item_key}|{attempt_number}".encode()
            ).hexdigest()
            append_jsonl(
                ledger_path,
                {
                    "request_attempt_id": attempt_id,
                    "event": "started",
                    "item_key": item_key,
                    "attempt_number": attempt_number,
                    "stage_snapshot_sha256": snapshot_sha,
                    "recorded_at_utc": utc_now(),
                },
            )
            archived: dict[str, Any] | None = None
            try:
                archived = call_and_archive(
                    client,
                    api_key=api_key,
                    endpoint=endpoint,
                    request=build_request(item, runtime),
                    archive_path=archive_path,
                    item_key=item_key,
                    attempt_id=attempt_id,
                    snapshot_sha256=snapshot_sha,
                )
                if archived["model_returned"] != runtime["model"]:
                    raise RuntimeError("systemic returned-model identity mismatch")
                raw_output = response_text(archived["response_body"])
                parsed = json.loads(raw_output)
                preparation.validate_independent_output(
                    parsed,
                    expected_item_id=item["item_id"],
                    description_id=item["description_id"],
                    description=item["local_validation_description"],
                    schema=schema,
                )
                added_cost, usage_event = _record_usage_once(archived, spending["pricing"])
                cost += added_cost
                append_jsonl(
                    ledger_path,
                    {
                        "request_attempt_id": attempt_id,
                        "event": "succeeded",
                        **usage_event,
                        "recorded_at_utc": utc_now(),
                    },
                )
                accepted_result = {
                    "archived": archived,
                    "raw_output": raw_output,
                    "parsed_output": parsed,
                }
                break
            except ProviderFailure as exc:
                archived = exc.archived
                added_cost, usage_event = _record_usage_once(archived, spending["pricing"])
                cost += added_cost
                last_error = {
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "retryable": exc.retryable,
                    "systemic": exc.systemic,
                }
                append_jsonl(
                    ledger_path,
                    {
                        "request_attempt_id": attempt_id,
                        "event": "failed",
                        **last_error,
                        **usage_event,
                        "recorded_at_utc": utc_now(),
                    },
                )
                if exc.systemic or not exc.retryable:
                    raise RuntimeError(f"systemic provider failure {item_key}") from exc
            except RuntimeError as exc:
                # A returned-model mismatch indicates a run-wide contract fault.
                added_cost, usage_event = _record_usage_once(archived, spending["pricing"])
                cost += added_cost
                append_jsonl(
                    ledger_path,
                    {
                        "request_attempt_id": attempt_id,
                        "event": "failed",
                        "retryable": False,
                        "systemic": True,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        **usage_event,
                        "recorded_at_utc": utc_now(),
                    },
                )
                raise
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                added_cost, usage_event = _record_usage_once(archived, spending["pricing"])
                cost += added_cost
                last_error = {
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "retryable": True,
                    "systemic": False,
                }
                append_jsonl(
                    ledger_path,
                    {
                        "request_attempt_id": attempt_id,
                        "event": "failed",
                        **last_error,
                        **usage_event,
                        "recorded_at_utc": utc_now(),
                    },
                )
            if attempt_number < maximum_attempts:
                sleep_fn(float(retry_policy["backoff_seconds"][attempt_number - 1]))

        if accepted_result is None:
            exhausted_count += 1
            append_jsonl(
                failed_path,
                {
                    "item_key": item_key,
                    "item_id": item["item_id"],
                    "description_id": item["description_id"],
                    "repetition": 1,
                    "terminal_state": "exhausted_retries",
                    "attempts_used": attempts_used,
                    "last_error": last_error,
                    "analysis_disposition": "missing_no_imputation",
                    "stage_snapshot_sha256": snapshot_sha,
                    "recorded_at_utc": utc_now(),
                },
            )
            print(
                f"terminal {accepted_count + exhausted_count}/{len(packet)} "
                f"accepted={accepted_count} exhausted={exhausted_count} reported_usd={cost}",
                flush=True,
            )
            continue

        archived = accepted_result["archived"]
        append_jsonl(
            output_path,
            {
                "item_key": item_key,
                "item_id": item["item_id"],
                "description_id": item["description_id"],
                "repetition": 1,
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
        accepted_count += 1
        print(
            f"terminal {accepted_count + exhausted_count}/{len(packet)} "
            f"accepted={accepted_count} exhausted={exhausted_count} reported_usd={cost}",
            flush=True,
        )

    result = {
        "state": "completed_with_item_failures" if exhausted_count else "completed",
        "planned_items": len(packet),
        "accepted_items": accepted_count,
        "exhausted_items": exhausted_count,
        "terminal_items": accepted_count + exhausted_count,
        "provider_reported_usd": str(cost),
        "stage_snapshot_sha256": snapshot_sha,
        "recorded_at_utc": utc_now(),
    }
    preparation.write_json(budget_path, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--network-preflight", type=Path, required=True)
    args = parser.parse_args()
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not exported")
    contract, snapshot_sha = _load_contract(args.snapshot)
    if preparation.sha256_file(Path(__file__)) != contract["code"]["runner_sha256"]:
        raise ValueError("runner differs from frozen identity")
    if preparation.sha256_file(args.packet) != contract["target"]["packet_sha256"]:
        raise ValueError("target packet differs from frozen identity")
    schema_path = Path(__file__).resolve().parents[1] / contract["artifacts"]["schema"]["path"]
    if preparation.sha256_file(schema_path) != contract["artifacts"]["schema"]["sha256"]:
        raise ValueError("local schema differs from frozen identity")
    schema = preparation.read_json(schema_path)
    _validate_preflight(preparation.read_json(args.network_preflight), snapshot_sha)
    runtime = contract["runtime"]
    if (
        runtime.get("endpoint") != "https://api.openai.com/v1/responses"
        or runtime.get("store") is not False
        or runtime.get("tools") != "none"
    ):
        raise ValueError("runtime endpoint/store/tools contract is invalid")
    packet = preparation.read_jsonl(args.packet)
    if len(packet) != contract["target"]["request_count"] or contract["target"]["repetitions"] != 1:
        raise ValueError("target request matrix differs from frozen contract")
    maximum_attempts = int(contract["retry_policy"]["maximum_attempts_per_item"])
    if contract["retry_policy"]["maximum_api_request_attempts"] != len(packet) * maximum_attempts:
        raise ValueError("maximum request-attempt count is inconsistent")

    output_path = args.output_root / "accepted_outputs.v3.jsonl"
    failed_path = args.output_root / "failed_items.v3.jsonl"
    ledger_path = args.output_root / "request_attempt_ledger.v3.jsonl"
    archive_path = args.output_root / "provider_responses_before_validation.v3.jsonl"
    budget_path = args.output_root / "budget_status.v3.json"
    for path in (output_path, failed_path, ledger_path, archive_path, budget_path):
        if path.exists():
            raise FileExistsError(f"refusing to resume or overwrite {path}")
    args.output_root.mkdir(parents=True, exist_ok=True)
    # Materialize complete append-only artifact identities even when one class
    # remains empty (for example, zero retry-exhausted items).
    for path in (output_path, failed_path, ledger_path, archive_path):
        path.touch(exist_ok=False)

    with httpx.Client(timeout=runtime["request_timeout_seconds"]) as client:
        result = run_packet(
            client=client,
            api_key=api_key,
            endpoint=runtime["endpoint"],
            packet=packet,
            schema=schema,
            runtime=runtime,
            retry_policy=contract["retry_policy"],
            spending=contract["spending"],
            snapshot_sha=snapshot_sha,
            output_path=output_path,
            failed_path=failed_path,
            ledger_path=ledger_path,
            archive_path=archive_path,
            budget_path=budget_path,
        )
    if result["terminal_items"] != len(packet):
        raise RuntimeError("target run ended without terminal disposition for every item")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
