#!/usr/bin/env python3
"""Re-run the frozen medical NLA Judge A/B/C inputs with GPT-5.6 Luna."""

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

import prepare_medical_nla_judging as preparation


STAGE = "medical_nla_luna_parity_v1"
CONTRACT_PARAMETER = "nla.medical_baseline_luna_parity_contract_v1"


class NonRetryableRequestError(RuntimeError):
    """A provider rejection that cannot succeed unchanged."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.endswith("\n"):
                raise ValueError(f"{path}:{line_number}: partial terminal line")
            if not line.strip():
                raise ValueError(f"{path}:{line_number}: blank line")
            row = json.loads(line)
            if not isinstance(row, dict):
                raise TypeError(f"{path}:{line_number}: row is not an object")
            rows.append(row)
    return rows


def append_jsonl(handle: Any, value: dict[str, Any]) -> None:
    handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
    handle.flush()
    os.fsync(handle.fileno())


def transport_schema(value: Any) -> Any:
    """Remove only the historically unsupported keyword from the API copy."""
    if isinstance(value, dict):
        return {
            key: transport_schema(item)
            for key, item in value.items()
            if key != "uniqueItems"
        }
    if isinstance(value, list):
        return [transport_schema(item) for item in value]
    return value


def normalized_usage(usage: dict[str, Any]) -> dict[str, Any]:
    input_tokens = int(usage["input_tokens"])
    output_tokens = int(usage["output_tokens"])
    cached_tokens = int(
        (usage.get("input_tokens_details") or {}).get("cached_tokens") or 0
    )
    reasoning_tokens = int(
        (usage.get("output_tokens_details") or {}).get("reasoning_tokens") or 0
    )
    if min(input_tokens, output_tokens, cached_tokens, reasoning_tokens) < 0:
        raise ValueError("usage token counts cannot be negative")
    if cached_tokens > input_tokens:
        raise ValueError("cached input tokens exceed input tokens")
    if reasoning_tokens > output_tokens:
        raise ValueError("reasoning tokens exceed output tokens")
    return {
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_tokens,
        "output_tokens": output_tokens,
        "reasoning_tokens": reasoning_tokens,
        "total_tokens": input_tokens + output_tokens,
    }


def usage_cost_usd(usage: dict[str, Any], pricing: dict[str, Any]) -> Decimal:
    normalized = normalized_usage(usage)
    million = Decimal("1000000")
    return (
        Decimal(normalized["input_tokens"] - normalized["cached_input_tokens"])
        * Decimal(str(pricing["uncached_input_usd_per_million_tokens"]))
        + Decimal(normalized["cached_input_tokens"])
        * Decimal(str(pricing["cached_input_usd_per_million_tokens"]))
        + Decimal(normalized["output_tokens"])
        * Decimal(str(pricing["output_usd_per_million_tokens"]))
    ) / million


def ledger_cost(rows: list[dict[str, Any]], pricing: dict[str, Any]) -> Decimal:
    return sum(
        (
            usage_cost_usd(row["usage"], pricing)
            for row in rows
            if row.get("event") in {"succeeded", "failed"}
            and isinstance(row.get("usage"), dict)
        ),
        start=Decimal("0"),
    )


def request_states(
    rows: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    attempts: dict[str, list[dict[str, Any]]] = {}
    by_item: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        attempt_id = row.get("request_attempt_id")
        event = row.get("event")
        if not isinstance(attempt_id, str) or event not in {
            "started",
            "succeeded",
            "failed",
        }:
            raise ValueError("malformed request ledger event")
        attempts.setdefault(attempt_id, []).append(row)
    for attempt_id, events in attempts.items():
        if events[0]["event"] != "started" or len(events) not in {1, 2}:
            raise ValueError(f"invalid request event sequence: {attempt_id}")
        if len(events) == 2 and events[1]["event"] not in {"succeeded", "failed"}:
            raise ValueError(f"invalid terminal request event: {attempt_id}")
        item_key = events[0].get("item_key")
        if not isinstance(item_key, str):
            raise ValueError("started event lacks item_key")
        by_item.setdefault(item_key, []).append(
            {
                "request_attempt_id": attempt_id,
                "attempt_number": events[0].get("attempt_number"),
                "terminal_event": events[1]["event"] if len(events) == 2 else None,
                "retryable": events[1].get("retryable") if len(events) == 2 else None,
            }
        )
    for item_key, states in by_item.items():
        states.sort(key=lambda row: row["attempt_number"])
        if [row["attempt_number"] for row in states] != list(
            range(1, len(states) + 1)
        ):
            raise ValueError(f"nonconsecutive attempts for {item_key}")
    return by_item


def response_text(body: dict[str, Any]) -> str:
    if body.get("status") != "completed":
        reason = (body.get("incomplete_details") or {}).get("reason")
        raise ValueError(f"response status is {body.get('status')!r}: {reason!r}")
    texts: list[str] = []
    for item in body.get("output") or []:
        if item.get("type") != "message":
            continue
        for content in item.get("content") or []:
            if content.get("type") == "refusal":
                raise ValueError("judge returned a refusal")
            if content.get("type") == "output_text":
                text = content.get("text")
                if isinstance(text, str) and text:
                    texts.append(text)
    if len(texts) != 1:
        raise ValueError(f"expected exactly one output_text block, found {len(texts)}")
    return texts[0]


def call_judge(
    client: httpx.Client,
    *,
    api_key: str,
    system_prompt: str,
    payload: dict[str, Any],
    schema: dict[str, Any],
    schema_name: str,
    runtime: dict[str, Any],
    max_output_tokens: int,
) -> dict[str, Any]:
    request = {
        "model": runtime["model"],
        "input": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": json.dumps(
                    payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                ),
            },
        ],
        "reasoning": {"effort": runtime["reasoning_effort"]},
        "max_output_tokens": max_output_tokens,
        "text": {
            "format": {
                "type": "json_schema",
                "name": schema_name,
                "strict": True,
                "schema": transport_schema(schema),
            }
        },
        "store": False,
    }
    response = client.post(
        runtime["endpoint"],
        headers={"Authorization": f"Bearer {api_key}"},
        json=request,
    )
    if 400 <= response.status_code < 500:
        raise NonRetryableRequestError(
            f"HTTP {response.status_code}: {response.text[:4000]}"
        )
    response.raise_for_status()
    body = response.json()
    content = response_text(body)
    parsed = json.loads(content)
    if not isinstance(parsed, dict):
        raise ValueError("judge response is not a JSON object")
    if not isinstance(body.get("usage"), dict):
        raise ValueError("provider-reported usage is absent")
    return {
        "response_id": body.get("id"),
        "model_returned": body.get("model"),
        "system_fingerprint": body.get("system_fingerprint"),
        "raw_output": content,
        "parsed_output": parsed,
        "usage": body["usage"],
        "request_parameters": {
            key: value for key, value in request.items() if key != "input"
        },
        "request_payload_sha256": canonical_sha256(request),
    }


def literal_excerpt_audit(
    judge_name: str, payload: dict[str, Any], output: dict[str, Any]
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def check(label: str, excerpt: Any, source: str) -> None:
        if excerpt is None:
            return
        checks.append(
            {
                "label": label,
                "excerpt_sha256": hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
                "literal_substring": excerpt in source,
            }
        )

    if judge_name == "judge_a":
        source = payload["nla_description"]
        for index, item in enumerate(output["stance_evidence"]):
            check(f"stance_evidence[{index}]", item["excerpt"], source)
        for index, item in enumerate(output["protective_stances"]):
            check(f"protective_stances[{index}]", item["excerpt"], source)
    elif judge_name == "judge_b":
        check("evidence_a", output["evidence_a"], payload["description_a"])
        check("evidence_b", output["evidence_b"], payload["description_b"])
    elif judge_name == "judge_c":
        source_map = {
            (row["prompt_id"], row["context_id"]): row["nla_description"]
            for row in payload["rows"]
        }
        for mode_index, mode in enumerate(output["candidate_failure_modes"]):
            for evidence_index, item in enumerate(mode["supporting_evidence"]):
                source = source_map[(item["prompt_id"], item["context_id"])]
                check(
                    f"candidate_failure_modes[{mode_index}].supporting_evidence"
                    f"[{evidence_index}]",
                    item["excerpt"],
                    source,
                )
    else:
        raise ValueError(f"unsupported judge: {judge_name}")
    return {
        "policy": "audit_only_no_retry",
        "checked_excerpt_count": len(checks),
        "literal_excerpt_count": sum(row["literal_substring"] for row in checks),
        "all_literal": all(row["literal_substring"] for row in checks),
        "checks": checks,
    }


def conservative_request_reservation_usd(
    *,
    system_prompt: str,
    payload: dict[str, Any],
    schema: dict[str, Any],
    max_output_tokens: int,
    pricing: dict[str, Any],
    overhead_token_reserve: int,
) -> Decimal:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True) + json.dumps(
        schema, ensure_ascii=False, sort_keys=True
    ) + system_prompt
    input_token_upper_bound = len(serialized.encode("utf-8")) + overhead_token_reserve
    million = Decimal("1000000")
    return (
        Decimal(input_token_upper_bound)
        * Decimal(str(pricing["uncached_input_usd_per_million_tokens"]))
        + Decimal(max_output_tokens)
        * Decimal(str(pricing["output_usd_per_million_tokens"]))
    ) / million


def write_budget_status(
    path: Path,
    *,
    state: str,
    contract: dict[str, Any],
    snapshot_sha256: str,
    cost: Decimal,
    successful_rows: int,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "state": state,
                "run_id": contract["run_id"],
                "stage_snapshot_sha256": snapshot_sha256,
                "provider_reported_usage_cost_usd": str(cost),
                "successful_judgments": successful_rows,
                "estimated_usd": str(contract["spending"]["estimated_usd"]),
                "absolute_maximum_usd": str(
                    contract["spending"]["absolute_maximum_usd"]
                ),
                "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--request-ledger", type=Path, required=True)
    parser.add_argument("--network-preflight", type=Path, required=True)
    parser.add_argument("--budget-status", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not exported")
    snapshot = read_json(args.snapshot)
    if snapshot.get("stage") != STAGE:
        raise ValueError("wrong judging stage snapshot")
    contract = snapshot["values"][CONTRACT_PARAMETER]
    snapshot_sha = sha256_file(args.snapshot)
    root = Path(__file__).resolve().parents[1]
    if sha256_file(Path(__file__)) != contract["code"]["runner_sha256"]:
        raise ValueError("judge runner differs from frozen identity")

    preflight = read_json(args.network_preflight)
    if (
        preflight.get("passed") is not True
        or preflight.get("stage_snapshot_sha256") != snapshot_sha
        or preflight.get("http_request_made") is not False
        or preflight.get("api_key_used") is not False
    ):
        raise ValueError("network preflight is absent or invalid")

    judge_specs: dict[str, dict[str, Any]] = {}
    work: list[tuple[str, str, dict[str, Any]]] = []
    for judge_name in ("judge_a", "judge_b", "judge_c"):
        spec = contract["judges"][judge_name]
        prompt_path = root / spec["system_prompt_path"]
        schema_path = root / spec["schema_path"]
        input_path = args.inputs / spec["input_file"]
        for path, expected_sha, label in (
            (prompt_path, spec["system_prompt_sha256"], "system prompt"),
            (schema_path, spec["schema_sha256"], "schema"),
            (input_path, spec["input_sha256"], "input"),
        ):
            if sha256_file(path) != expected_sha:
                raise ValueError(f"{judge_name} {label} differs")
        items = read_json(input_path)
        if len(items) != spec["expected_rows"]:
            raise ValueError(f"{judge_name} input row count differs")
        judge_specs[judge_name] = {
            **spec,
            "system_prompt": prompt_path.read_text(encoding="utf-8"),
            "schema": read_json(schema_path),
        }
        id_field = "bundle_id" if judge_name == "judge_c" else "judge_item_id"
        for item in items:
            item_key = f"{judge_name}:{item[id_field]}"
            work.append((judge_name, item_key, item))
    if len(work) != contract["expected_judgments"]["total"]:
        raise ValueError("input work count differs from frozen contract")

    existing = read_jsonl(args.output)
    completed = {row["item_key"] for row in existing}
    if len(completed) != len(existing):
        raise ValueError("duplicate successful output item")
    if any(row["stage_snapshot_sha256"] != snapshot_sha for row in existing):
        raise ValueError("existing outputs reference another snapshot")
    ledger_rows = read_jsonl(args.request_ledger)
    attempts = request_states(ledger_rows)
    pricing = contract["spending"]["pricing"]
    cost = ledger_cost(ledger_rows, pricing)
    maximum = Decimal(str(contract["spending"]["absolute_maximum_usd"]))
    maximum_attempts = contract["retry_policy"]["maximum_attempts_per_item"]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.request_ledger.parent.mkdir(parents=True, exist_ok=True)
    with (
        httpx.Client(timeout=contract["runtime"]["request_timeout_seconds"]) as client,
        args.output.open("a", encoding="utf-8") as output_handle,
        args.request_ledger.open("a", encoding="utf-8") as ledger_handle,
    ):
        for judge_name, item_key, payload in work:
            if item_key in completed:
                continue
            prior = attempts.get(item_key, [])
            if prior and prior[-1]["terminal_event"] is None:
                raise RuntimeError(f"ambiguous in-flight prior request: {item_key}")
            if prior and prior[-1]["terminal_event"] == "failed" and not prior[-1][
                "retryable"
            ]:
                raise RuntimeError(f"non-retryable prior failure: {item_key}")
            result: dict[str, Any] | None = None
            spec = judge_specs[judge_name]
            validator: Callable[..., None] = getattr(
                preparation, f"validate_{judge_name}_output"
            )
            while len(prior) < maximum_attempts:
                reservation = conservative_request_reservation_usd(
                    system_prompt=spec["system_prompt"],
                    payload=payload,
                    schema=spec["schema"],
                    max_output_tokens=spec["max_output_tokens"],
                    pricing=pricing,
                    overhead_token_reserve=contract["spending"][
                        "input_overhead_token_reserve"
                    ],
                )
                if cost + reservation > maximum:
                    write_budget_status(
                        args.budget_status,
                        state="paused_absolute_maximum_pre_request",
                        contract=contract,
                        snapshot_sha256=snapshot_sha,
                        cost=cost,
                        successful_rows=len(completed),
                    )
                    raise RuntimeError("absolute judge spending maximum blocks next request")
                attempt_number = len(prior) + 1
                attempt_id = hashlib.sha256(
                    f"{snapshot_sha}|{item_key}|{attempt_number}".encode()
                ).hexdigest()
                append_jsonl(
                    ledger_handle,
                    {
                        "request_attempt_id": attempt_id,
                        "event": "started",
                        "item_key": item_key,
                        "judge_name": judge_name,
                        "attempt_number": attempt_number,
                        "stage_snapshot_sha256": snapshot_sha,
                        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
                    },
                )
                state = {
                    "request_attempt_id": attempt_id,
                    "attempt_number": attempt_number,
                    "terminal_event": None,
                    "retryable": None,
                }
                prior.append(state)
                attempts[item_key] = prior
                provider_result: dict[str, Any] | None = None
                try:
                    provider_result = call_judge(
                        client,
                        api_key=api_key,
                        system_prompt=spec["system_prompt"],
                        payload=payload,
                        schema=spec["schema"],
                        schema_name=spec["schema_name"],
                        runtime=contract["runtime"],
                        max_output_tokens=spec["max_output_tokens"],
                    )
                    if provider_result["model_returned"] != contract["runtime"]["model"]:
                        raise ValueError("returned model identity differs")
                    if judge_name == "judge_c":
                        allowed_cells = {
                            (row["prompt_id"], row["context_id"])
                            for row in payload["rows"]
                        }
                        validator(provider_result["parsed_output"], allowed_cells)
                    else:
                        validator(provider_result["parsed_output"])
                    result = provider_result
                    terminal_event = {
                        "request_attempt_id": attempt_id,
                        "event": "succeeded",
                        "response_id": result["response_id"],
                        "usage": result["usage"],
                        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
                    }
                    append_jsonl(ledger_handle, terminal_event)
                    cost += usage_cost_usd(result["usage"], pricing)
                    state["terminal_event"] = "succeeded"
                    break
                except NonRetryableRequestError as error:
                    append_jsonl(
                        ledger_handle,
                        {
                            "request_attempt_id": attempt_id,
                            "event": "failed",
                            "retryable": False,
                            "error_type": type(error).__name__,
                            "error": str(error),
                            "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
                        },
                    )
                    state["terminal_event"] = "failed"
                    state["retryable"] = False
                    raise RuntimeError(
                        f"non-retryable provider rejection: {item_key}"
                    ) from error
                except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
                    failed_event: dict[str, Any] = {
                        "request_attempt_id": attempt_id,
                        "event": "failed",
                        "retryable": True,
                        "error_type": type(error).__name__,
                        "error": str(error),
                        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
                    }
                    if provider_result is not None:
                        failed_event["response_id"] = provider_result["response_id"]
                        failed_event["usage"] = provider_result["usage"]
                        cost += usage_cost_usd(provider_result["usage"], pricing)
                    append_jsonl(ledger_handle, failed_event)
                    state["terminal_event"] = "failed"
                    state["retryable"] = True
                    result = None
                    if len(prior) < maximum_attempts:
                        time.sleep(
                            contract["retry_policy"]["backoff_seconds"][len(prior) - 1]
                        )
            if result is None:
                raise RuntimeError(f"judge exhausted retries: {item_key}")
            audit = literal_excerpt_audit(judge_name, payload, result["parsed_output"])
            row = {
                "item_key": item_key,
                "judge_name": judge_name,
                "anonymous_item_id": item_key.split(":", 1)[1],
                "parsed_output": result["parsed_output"],
                "raw_output": result["raw_output"],
                "response_id": result["response_id"],
                "model_returned": result["model_returned"],
                "system_fingerprint": result["system_fingerprint"],
                "usage": result["usage"],
                "normalized_usage": normalized_usage(result["usage"]),
                "request_parameters": result["request_parameters"],
                "request_payload_sha256": result["request_payload_sha256"],
                "literal_excerpt_audit": audit,
                "stage_snapshot_sha256": snapshot_sha,
                "judged_at_utc": datetime.now(timezone.utc).isoformat(),
            }
            append_jsonl(output_handle, row)
            completed.add(item_key)
            print(
                f"judged {item_key} rows={len(completed)}/{len(work)} "
                f"reported_usd={cost}",
                flush=True,
            )

    write_budget_status(
        args.budget_status,
        state="completed",
        contract=contract,
        snapshot_sha256=snapshot_sha,
        cost=cost,
        successful_rows=len(completed),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
