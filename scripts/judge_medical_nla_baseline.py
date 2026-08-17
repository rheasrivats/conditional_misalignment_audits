#!/usr/bin/env python3
"""Run the frozen blinded Judge A/B/C medical NLA baseline suite."""

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


STAGE = "medical_nla_baseline_judging_v1"
CONTRACT_PARAMETER = "nla.medical_baseline_judge_contract_v2"
RUNTIME_SUCCESSOR_PARAMETER = "nla.medical_baseline_judging_runtime_successor_v3"
ACCOUNTING_PARAMETER = "qualification.medical_judge_cost_accounting_successor"


class NonRetryableRequestError(RuntimeError):
    """A provider rejection that cannot succeed unchanged."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


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
            value = json.loads(line)
            if not isinstance(value, dict):
                raise TypeError(f"{path}:{line_number}: row is not an object")
            rows.append(value)
    return rows


def append_jsonl(handle: Any, value: dict[str, Any]) -> None:
    handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
    handle.flush()
    os.fsync(handle.fileno())


def usage_cost_usd(usage: dict[str, Any], accounting: dict[str, Any]) -> Decimal:
    prompt_tokens = int(usage["prompt_tokens"])
    completion_tokens = int(usage["completion_tokens"])
    cached_tokens = int(
        (usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
    )
    if min(prompt_tokens, completion_tokens, cached_tokens) < 0:
        raise ValueError("usage token counts cannot be negative")
    if cached_tokens > prompt_tokens:
        raise ValueError("cached tokens exceed prompt tokens")
    million = Decimal("1000000")
    return (
        Decimal(prompt_tokens - cached_tokens)
        * Decimal(str(accounting["uncached_input_usd_per_million_tokens"]))
        + Decimal(cached_tokens)
        * Decimal(str(accounting["cached_input_usd_per_million_tokens"]))
        + Decimal(completion_tokens)
        * Decimal(str(accounting["output_usd_per_million_tokens"]))
    ) / million


def cumulative_cost(
    rows: list[dict[str, Any]], accounting: dict[str, Any]
) -> Decimal:
    return sum(
        (usage_cost_usd(row["usage"], accounting) for row in rows),
        start=Decimal("0"),
    )


def request_states(
    rows: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    by_item: dict[str, list[dict[str, Any]]] = {}
    attempts: dict[str, list[dict[str, Any]]] = {}
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
        state = {
            "request_attempt_id": attempt_id,
            "attempt_number": events[0].get("attempt_number"),
            "terminal_event": events[1]["event"] if len(events) == 2 else None,
            "retryable": events[1].get("retryable") if len(events) == 2 else None,
        }
        by_item.setdefault(item_key, []).append(state)
    for item_key, states in by_item.items():
        states.sort(key=lambda row: row["attempt_number"])
        if [row["attempt_number"] for row in states] != list(
            range(1, len(states) + 1)
        ):
            raise ValueError(f"nonconsecutive attempts for {item_key}")
    return by_item


def transport_schema(value: Any) -> Any:
    """Project only unsupported transport keywords; local validation stays exact."""
    if isinstance(value, dict):
        return {
            key: transport_schema(item)
            for key, item in value.items()
            if key != "uniqueItems"
        }
    if isinstance(value, list):
        return [transport_schema(item) for item in value]
    return value


def call_judge(
    client: httpx.Client,
    *,
    api_key: str,
    model: str,
    system_prompt: str,
    payload: dict[str, Any],
    schema: dict[str, Any],
    schema_name: str,
    runtime: dict[str, Any],
    max_tokens: int,
) -> dict[str, Any]:
    request = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": json.dumps(
                    payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                ),
            },
        ],
        "temperature": runtime["temperature"],
        "top_p": runtime["top_p"],
        "n": runtime["n"],
        "frequency_penalty": runtime["frequency_penalty"],
        "presence_penalty": runtime["presence_penalty"],
        "seed": runtime["seed"],
        "max_tokens": max_tokens,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": schema_name,
                "strict": True,
                "schema": transport_schema(schema),
            },
        },
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
    choice = body["choices"][0]
    content = choice["message"]["content"]
    if not isinstance(content, str) or not content:
        raise ValueError("judge response content is absent")
    parsed = json.loads(content)
    if not isinstance(parsed, dict):
        raise ValueError("judge response is not a JSON object")
    return {
        "response_id": body.get("id"),
        "model_returned": body.get("model"),
        "system_fingerprint": body.get("system_fingerprint"),
        "finish_reason": choice.get("finish_reason"),
        "raw_output": content,
        "parsed_output": parsed,
        "usage": body["usage"],
        "request_parameters": {
            key: value for key, value in request.items() if key != "messages"
        },
    }


def write_budget_status(
    path: Path,
    *,
    state: str,
    run_id: str,
    snapshot_sha256: str,
    cost: Decimal,
    successful_rows: int,
    estimate: Decimal,
    maximum: Decimal,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "state": state,
                "run_id": run_id,
                "stage_snapshot_sha256": snapshot_sha256,
                "provider_reported_usage_cost_usd": str(cost),
                "successful_judgments": successful_rows,
                "estimated_usd": str(estimate),
                "absolute_maximum_usd": str(maximum),
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
    values = snapshot["values"]
    contract = values[CONTRACT_PARAMETER]
    runtime_successor = values[RUNTIME_SUCCESSOR_PARAMETER]
    accounting = values[ACCOUNTING_PARAMETER]
    if runtime_successor["scientific_contract"] != CONTRACT_PARAMETER:
        raise ValueError("runtime successor references another scientific contract")
    if sha256_file(Path(__file__)) != runtime_successor["runner_sha256"]:
        raise ValueError("judge runner differs from frozen identity")
    if (
        sha256_file(Path(preparation.__file__))
        != runtime_successor["builder_sha256"]
    ):
        raise ValueError("judge preparation dependency differs from frozen identity")
    snapshot_sha = sha256_file(args.snapshot)
    manifest = read_json(args.inputs / "manifest.json")
    if manifest["judge_snapshot"]["sha256"] != snapshot_sha:
        raise ValueError("input manifest references another judge snapshot")
    if manifest["decoded"]["sha256"] != contract["source_artifacts"]["decoded_sha256"]:
        raise ValueError("input manifest references another decoded artifact")
    preflight = read_json(args.network_preflight)
    if (
        preflight.get("passed") is not True
        or preflight.get("stage_snapshot_sha256") != snapshot_sha
        or preflight.get("http_request_made") is not False
        or preflight.get("api_key_used") is not False
    ):
        raise ValueError("network preflight is absent or invalid")

    root = Path(__file__).resolve().parents[1]
    judge_specs: dict[str, dict[str, Any]] = {}
    for judge_name in ("judge_a", "judge_b", "judge_c"):
        spec = contract["judges"][judge_name]
        prompt_path = root / spec["system_prompt_path"]
        schema_path = root / spec["schema_path"]
        if sha256_file(prompt_path) != spec["system_prompt_sha256"]:
            raise ValueError(f"{judge_name} system prompt differs")
        if sha256_file(schema_path) != spec["schema_sha256"]:
            raise ValueError(f"{judge_name} schema differs")
        judge_specs[judge_name] = {
            **spec,
            "system_prompt": prompt_path.read_text(encoding="utf-8"),
            "schema": read_json(schema_path),
        }

    suites = (
        ("judge_a", "judge_a_inputs.json", "judge_item_id"),
        ("judge_b", "judge_b_inputs.json", "judge_item_id"),
        ("judge_c", "judge_c_inputs.json", "bundle_id"),
    )
    work: list[tuple[str, str, dict[str, Any]]] = []
    for judge_name, file_name, id_field in suites:
        items = read_json(args.inputs / file_name)
        for item in items:
            item_id = item[id_field]
            work.append((judge_name, f"{judge_name}:{item_id}", item))
    if len(work) != contract["expected_judgments"]["total"]:
        raise ValueError("input work count differs from frozen contract")

    existing = read_jsonl(args.output)
    completed = {row["item_key"] for row in existing}
    if len(completed) != len(existing):
        raise ValueError("duplicate successful output item")
    if any(row["stage_snapshot_sha256"] != snapshot_sha for row in existing):
        raise ValueError("existing outputs reference another snapshot")
    attempts = request_states(read_jsonl(args.request_ledger))
    cost = cumulative_cost(existing, accounting)
    estimate = Decimal(str(contract["spending"]["estimated_usd"]))
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
            if cost >= maximum:
                write_budget_status(
                    args.budget_status,
                    state="paused_absolute_maximum",
                    run_id=contract["run_id"],
                    snapshot_sha256=snapshot_sha,
                    cost=cost,
                    successful_rows=len(completed),
                    estimate=estimate,
                    maximum=maximum,
                )
                raise RuntimeError("absolute judge spending maximum reached")
            prior = attempts.get(item_key, [])
            if prior and prior[-1]["terminal_event"] is None:
                raise RuntimeError(f"ambiguous in-flight prior request: {item_key}")
            if prior and prior[-1]["terminal_event"] == "failed":
                if prior[-1]["retryable"] is False:
                    raise RuntimeError(f"non-retryable prior failure: {item_key}")
            result: dict[str, Any] | None = None
            spec = judge_specs[judge_name]
            validator: Callable[..., None] = getattr(
                preparation, f"validate_{judge_name}_output"
            )
            while len(prior) < maximum_attempts:
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
                try:
                    result = call_judge(
                        client,
                        api_key=api_key,
                        model=contract["runtime"]["model"],
                        system_prompt=spec["system_prompt"],
                        payload=payload,
                        schema=spec["schema"],
                        schema_name=spec["schema_name"],
                        runtime=contract["runtime"],
                        max_tokens=spec["max_tokens"],
                    )
                    if result["model_returned"] != contract["runtime"]["model"]:
                        raise ValueError("returned model identity differs")
                    if result["finish_reason"] != "stop":
                        raise ValueError("judge response did not finish with stop")
                    if judge_name == "judge_c":
                        allowed_cells = {
                            (row["prompt_id"], row["context_id"])
                            for row in payload["rows"]
                        }
                        validator(result["parsed_output"], allowed_cells)
                    else:
                        validator(result["parsed_output"])
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
                    append_jsonl(
                        ledger_handle,
                        {
                            "request_attempt_id": attempt_id,
                            "event": "failed",
                            "retryable": True,
                            "error_type": type(error).__name__,
                            "error": str(error),
                            "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
                        },
                    )
                    state["terminal_event"] = "failed"
                    state["retryable"] = True
                    result = None
                    if len(prior) < maximum_attempts:
                        time.sleep(
                            contract["retry_policy"]["backoff_seconds"][
                                len(prior) - 1
                            ]
                        )
            if result is None:
                raise RuntimeError(f"judge exhausted retries: {item_key}")
            row = {
                "item_key": item_key,
                "judge_name": judge_name,
                "anonymous_item_id": item_key.split(":", 1)[1],
                "parsed_output": result["parsed_output"],
                "raw_output": result["raw_output"],
                "response_id": result["response_id"],
                "model_returned": result["model_returned"],
                "system_fingerprint": result["system_fingerprint"],
                "finish_reason": result["finish_reason"],
                "usage": result["usage"],
                "request_parameters": result["request_parameters"],
                "stage_snapshot_sha256": snapshot_sha,
                "judged_at_utc": datetime.now(timezone.utc).isoformat(),
            }
            append_jsonl(output_handle, row)
            append_jsonl(
                ledger_handle,
                {
                    "request_attempt_id": prior[-1]["request_attempt_id"],
                    "event": "succeeded",
                    "response_id": result["response_id"],
                    "usage": result["usage"],
                    "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
                },
            )
            prior[-1]["terminal_event"] = "succeeded"
            prior[-1]["retryable"] = None
            completed.add(item_key)
            cost += usage_cost_usd(result["usage"], accounting)
            print(
                f"judged {item_key} rows={len(completed)}/{len(work)} "
                f"reported_usd={cost}",
                flush=True,
            )

    write_budget_status(
        args.budget_status,
        state="completed",
        run_id=contract["run_id"],
        snapshot_sha256=snapshot_sha,
        cost=cost,
        successful_rows=len(completed),
        estimate=estimate,
        maximum=maximum,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
