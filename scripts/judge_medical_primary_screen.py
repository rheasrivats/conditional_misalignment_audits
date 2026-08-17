#!/usr/bin/env python3
"""Judge one frozen medical primary-screen generation track with three attempts."""

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

from judge_construction_behavior import (
    JUDGE_FILES,
    call_judge,
    existing_keys,
    expected_rating,
    load_rows,
    sha256_file,
    validate_request_attempts,
)


STAGE_CONTRACTS = {
    "medical_post_hoc_primary_initial_judging": (
        "qualification.medical_primary_initial_judge_cost_guard_successor"
    ),
    "medical_hhh_only_primary_initial_judging": (
        "qualification.medical_hhh_only_primary_initial_judge_cost_guard_successor"
    ),
}
JUDGE_PROTOCOL = "qualification.medical_response_judging_protocol_successor"
JUDGE_RUNTIME = "qualification.medical_judge_api_runtime_contract_successor"
COST_ACCOUNTING = "qualification.medical_judge_cost_accounting_successor"
STAGE_BUDGETS = {
    "medical_post_hoc_primary_initial_judging": (
        "budget.medical_primary_initial_post_hoc_track_001_judging_two_judge_successor"
    ),
    "medical_hhh_only_primary_initial_judging": (
        "budget.medical_primary_initial_hhh_only_track_001_judging_authorization"
    ),
}


def validate_contract(
    contract: dict[str, Any],
    behavior_path: Path,
    behavior_rows: list[dict[str, Any]],
    judge_count: int,
) -> None:
    behavior = contract.get("behavior")
    if not isinstance(behavior, dict):
        raise ValueError("judge contract lacks frozen behavior identity")
    if sha256_file(behavior_path) != behavior["sha256"]:
        raise ValueError("behavior file differs from frozen judge input")
    if len(behavior_rows) != behavior["rows"]:
        raise ValueError("behavior row count differs from judge contract")
    if any(
        row.get("stage_snapshot_sha256") != behavior["generation_stage_snapshot_sha256"]
        for row in behavior_rows
    ):
        raise ValueError("behavior rows reference a different generation snapshot")
    labels = sorted({row["checkpoint_label"] for row in behavior_rows})
    if labels != sorted(behavior["checkpoint_labels"]):
        raise ValueError("behavior checkpoint labels differ from judge contract")
    contexts = sorted({row["context"] for row in behavior_rows})
    if contexts != sorted(behavior["contexts"]):
        raise ValueError("behavior contexts differ from judge contract")
    if contract["expected_successful_judge_rows"] != len(behavior_rows) * judge_count:
        raise ValueError("expected judge row count is inconsistent")
    if contract["maximum_attempts_per_judge_row"] != 3:
        raise ValueError("judge contract must allow exactly three total attempts")
    if contract["maximum_api_request_attempts"] != (
        contract["expected_successful_judge_rows"] * 3
    ):
        raise ValueError("global judge request ceiling is inconsistent")
    code_hash = contract.get("code", {}).get("judge_runner_sha256")
    if code_hash != sha256_file(Path(__file__)):
        raise ValueError("judge runner differs from frozen code hash")


def validate_network_preflight(
    path: Path, contract: dict[str, Any], snapshot_sha256: str
) -> dict[str, Any]:
    report = json.loads(path.read_text())
    expected = contract["network_preflight"]
    if report.get("passed") is not True:
        raise ValueError("judge network preflight did not pass")
    if report.get("stage_snapshot_sha256") != snapshot_sha256:
        raise ValueError("judge network preflight references another snapshot")
    if report.get("host") != expected["host"] or report.get("port") != expected["port"]:
        raise ValueError("judge network preflight host or port differs")
    if report.get("http_request_made") is not False or report.get("api_key_used") is not False:
        raise ValueError("judge network preflight must not make an API request")
    if not report.get("resolved_addresses") or not report.get("tls_version"):
        raise ValueError("judge network preflight lacks DNS or TLS evidence")
    return report


def usage_cost_usd(usage: dict[str, Any], accounting: dict[str, Any]) -> Decimal:
    prompt_tokens = int(usage["prompt_tokens"])
    completion_tokens = int(usage["completion_tokens"])
    cached_tokens = int(
        (usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
    )
    if min(prompt_tokens, completion_tokens, cached_tokens) < 0:
        raise ValueError("usage token counts cannot be negative")
    if cached_tokens > prompt_tokens:
        raise ValueError("cached input tokens exceed total prompt tokens")
    million = Decimal("1000000")
    return (
        Decimal(prompt_tokens - cached_tokens)
        * Decimal(str(accounting["uncached_input_usd_per_million_tokens"]))
        + Decimal(cached_tokens)
        * Decimal(str(accounting["cached_input_usd_per_million_tokens"]))
        + Decimal(completion_tokens)
        * Decimal(str(accounting["output_usd_per_million_tokens"]))
    ) / million


def cumulative_reported_cost_usd(
    judge_rows: list[dict[str, Any]], accounting: dict[str, Any]
) -> Decimal:
    return sum(
        (usage_cost_usd(row["usage"], accounting) for row in judge_rows),
        start=Decimal("0"),
    )


def write_budget_status(
    path: Path,
    *,
    state: str,
    run_id: str,
    snapshot_sha256: str,
    reported_cost_usd: Decimal,
    successful_judge_rows: int,
    warning_usd: Decimal,
    absolute_maximum_usd: Decimal,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "state": state,
                "run_id": run_id,
                "stage_snapshot_sha256": snapshot_sha256,
                "provider_reported_usage_cost_usd": str(reported_cost_usd),
                "successful_judge_rows": successful_judge_rows,
                "warning_usd": str(warning_usd),
                "absolute_maximum_usd": str(absolute_maximum_usd),
                "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--behavior", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--request-ledger", type=Path, required=True)
    parser.add_argument("--network-preflight", type=Path, required=True)
    parser.add_argument("--budget-status", type=Path, required=True)
    parser.add_argument("--resume-after-warning-approval")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not exported")
    snapshot = json.loads(args.snapshot.read_text())
    stage = snapshot.get("stage")
    if stage not in STAGE_CONTRACTS:
        raise ValueError(f"snapshot stage {stage!r} is not supported")
    values = snapshot["values"]
    judge = values[JUDGE_PROTOCOL]
    runtime = values[JUDGE_RUNTIME]
    accounting = values[COST_ACCOUNTING]
    contract = values[STAGE_CONTRACTS[stage]]
    budget = values[STAGE_BUDGETS[stage]]
    behavior_rows = load_rows(args.behavior)
    if not behavior_rows:
        raise ValueError("behavior file is empty")
    validate_contract(contract, args.behavior, behavior_rows, len(judge["prompts"]))
    snapshot_sha = sha256_file(args.snapshot)
    validate_network_preflight(args.network_preflight, contract, snapshot_sha)

    prompts: dict[str, str] = {}
    for judge_name in judge["prompts"]:
        path = args.workspace / JUDGE_FILES[judge_name]
        if sha256_file(path) != judge["prompt_sha256"][judge_name]:
            raise ValueError(f"{judge_name} judge prompt differs from frozen hash")
        prompts[judge_name] = path.read_text().strip()
    if set(runtime["rating_judges"]) != {"alignment", "coherence"}:
        raise ValueError("rating judge set differs")
    if runtime["free_form_judges"]:
        raise ValueError("free-form judge set differs")
    if not runtime["exact_returned_model_required"]:
        raise ValueError("exact judge model identity must be enforced")

    attempts_by_key = validate_request_attempts(
        load_rows(args.request_ledger) if args.request_ledger.exists() else []
    )
    prior_attempt_count = sum(len(items) for items in attempts_by_key.values())
    if prior_attempt_count > contract["maximum_api_request_attempts"]:
        raise ValueError("existing request ledger exceeds the frozen ceiling")
    completed = existing_keys(args.output)
    existing = load_rows(args.output) if args.output.exists() else []
    if existing:
        if any(row.get("stage_snapshot_sha256") != snapshot_sha for row in existing):
            raise ValueError("existing judge rows reference another snapshot")
    reported_cost = cumulative_reported_cost_usd(existing, accounting)
    warning_usd = Decimal(str(budget["warning_usd"]))
    absolute_maximum_usd = Decimal(str(budget["absolute_maximum_usd"]))
    resumed_after_warning = False
    if args.resume_after_warning_approval:
        if not args.resume_after_warning_approval.startswith("DEC-"):
            raise ValueError("warning-resume approval must be a recorded decision ID")
        if not args.budget_status.exists():
            raise ValueError("warning resume requires the preserved pause status")
        prior_status = json.loads(args.budget_status.read_text())
        if (
            prior_status.get("state") != "paused_warning"
            or prior_status.get("run_id") != contract["run_id"]
            or prior_status.get("stage_snapshot_sha256") != snapshot_sha
        ):
            raise ValueError("warning resume does not match the preserved pause")
        resumed_after_warning = True
    pause_threshold = absolute_maximum_usd if resumed_after_warning else warning_usd
    if reported_cost >= pause_threshold:
        write_budget_status(
            args.budget_status,
            state=(
                "paused_absolute_maximum"
                if reported_cost >= absolute_maximum_usd
                else "paused_warning"
            ),
            run_id=contract["run_id"],
            snapshot_sha256=snapshot_sha,
            reported_cost_usd=reported_cost,
            successful_judge_rows=len(existing),
            warning_usd=warning_usd,
            absolute_maximum_usd=absolute_maximum_usd,
        )
        raise RuntimeError("reported judge cost already requires a budget pause")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.request_ledger.parent.mkdir(parents=True, exist_ok=True)
    code_provenance = {
        "stage_snapshot_sha256": snapshot_sha,
        "judge_runner_sha256": contract["code"]["judge_runner_sha256"],
        "behavior_sha256": contract["behavior"]["sha256"],
    }
    with httpx.Client(timeout=contract["request_timeout_seconds"]) as client, args.output.open(
        "a", encoding="utf-8"
    ) as output_handle, args.request_ledger.open("a", encoding="utf-8") as ledger:
        for behavior in behavior_rows:
            for judge_name in judge["prompts"]:
                key = (behavior["row_id"], judge_name)
                if key in completed:
                    continue
                prior_for_key = attempts_by_key.get(key, [])
                if any(item["terminal_event"] == "succeeded" for item in prior_for_key):
                    raise ValueError(f"ledger records success but judge row is absent: {key}")
                if prior_for_key and prior_for_key[-1]["terminal_event"] == "failed" and prior_for_key[-1]["retryable"] is False:
                    raise RuntimeError(f"non-retryable prior judge failure blocks resume: {key}")
                rendered = prompts[judge_name].format(
                    question=behavior["prompt"], answer=behavior["response"]
                )
                is_rating = judge_name in runtime["rating_judges"]
                max_tokens = runtime["rating_max_tokens"] if is_rating else runtime["free_form_max_tokens"]
                result = None
                request_attempt_id = ""
                while len(prior_for_key) < contract["maximum_attempts_per_judge_row"]:
                    if prior_attempt_count >= contract["maximum_api_request_attempts"]:
                        raise RuntimeError("judge request ceiling reached before submission")
                    attempt_number = len(prior_for_key) + 1
                    request_attempt_id = hashlib.sha256(
                        f"{snapshot_sha}|{key[0]}|{judge_name}|{attempt_number}".encode()
                    ).hexdigest()
                    ledger.write(
                        json.dumps(
                            {
                                "request_attempt_id": request_attempt_id,
                                "event": "started",
                                "behavior_row_id": key[0],
                                "judge_name": judge_name,
                                "attempt_number": attempt_number,
                                "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
                                "stage_snapshot_sha256": snapshot_sha,
                                "code_provenance": code_provenance,
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                    ledger.flush()
                    prior_attempt_count += 1
                    state = {
                        "request_attempt_id": request_attempt_id,
                        "attempt_number": attempt_number,
                        "terminal_event": None,
                        "retryable": None,
                    }
                    prior_for_key.append(state)
                    attempts_by_key[key] = prior_for_key
                    try:
                        result = call_judge(
                            client,
                            api_key=api_key,
                            model=judge["model"],
                            prompt=rendered,
                            temperature=judge["temperature"],
                            max_tokens=max_tokens,
                            runtime=runtime,
                            rating=is_rating,
                        )
                        break
                    except (httpx.HTTPError, KeyError, ValueError) as error:
                        ledger.write(
                            json.dumps(
                                {
                                    "request_attempt_id": request_attempt_id,
                                    "event": "failed",
                                    "retryable": True,
                                    "error_type": type(error).__name__,
                                    "error": str(error),
                                    "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
                                },
                                ensure_ascii=False,
                            )
                            + "\n"
                        )
                        ledger.flush()
                        state["terminal_event"] = "failed"
                        state["retryable"] = True
                        if len(prior_for_key) < contract["maximum_attempts_per_judge_row"]:
                            time.sleep(contract["retry_backoff_seconds"][len(prior_for_key) - 1])
                if result is None:
                    raise RuntimeError(f"judge exhausted three attempts for {key}")
                try:
                    if result["model_returned"] != judge["model"]:
                        raise ValueError("returned judge model identity differs")
                    rating_result: dict[str, Any] = {
                        "score": None,
                        "numeric_probability_mass": None,
                        "normalized_numeric_probabilities": None,
                        "raw_top_token_logprobs": None,
                    }
                    if is_rating:
                        rating_result = expected_rating(
                            result["logprobs"],
                            minimum=runtime["rating_minimum"],
                            maximum=runtime["rating_maximum"],
                            numeric_mass_minimum_inclusive=runtime[
                                "rating_numeric_probability_mass_minimum_inclusive"
                            ],
                        )
                except (KeyError, ValueError) as error:
                    ledger.write(
                        json.dumps(
                            {
                                "request_attempt_id": request_attempt_id,
                                "event": "failed",
                                "retryable": False,
                                "error_type": type(error).__name__,
                                "error": str(error),
                                "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                    ledger.flush()
                    prior_for_key[-1]["terminal_event"] = "failed"
                    prior_for_key[-1]["retryable"] = False
                    raise RuntimeError(f"non-retryable judge validation failed for {key}") from error
                row = {
                    "behavior_row_id": behavior["row_id"],
                    "judge_name": judge_name,
                    "judge_mode": "rating_logprob_expected_value" if is_rating else "free_form",
                    "judge_model_requested": judge["model"],
                    "judge_prompt_sha256": judge["prompt_sha256"][judge_name],
                    "raw_output": result["text"],
                    "response_id": result["response_id"],
                    "model_returned": result["model_returned"],
                    "system_fingerprint": result["system_fingerprint"],
                    "finish_reason": result["finish_reason"],
                    "usage": result["usage"],
                    "request_parameters": {
                        name: value
                        for name, value in result["request"].items()
                        if name != "messages"
                    },
                    **rating_result,
                    "judged_at_utc": datetime.now(timezone.utc).isoformat(),
                    "stage_snapshot_sha256": snapshot_sha,
                    "behavior_stage_snapshot_sha256": behavior["stage_snapshot_sha256"],
                    "behavior_code_provenance": behavior["code_provenance"],
                    "code_provenance": code_provenance,
                }
                output_handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                output_handle.flush()
                reported_cost += usage_cost_usd(result["usage"], accounting)
                ledger.write(
                    json.dumps(
                        {
                            "request_attempt_id": request_attempt_id,
                            "event": "succeeded",
                            "response_id": result["response_id"],
                            "usage": result["usage"],
                            "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                ledger.flush()
                prior_for_key[-1]["terminal_event"] = "succeeded"
                completed.add(key)
                print(f"judged {key[0]} {judge_name}")
                if reported_cost >= pause_threshold:
                    write_budget_status(
                        args.budget_status,
                        state=(
                            "paused_absolute_maximum"
                            if reported_cost >= absolute_maximum_usd
                            else "paused_warning"
                        ),
                        run_id=contract["run_id"],
                        snapshot_sha256=snapshot_sha,
                        reported_cost_usd=reported_cost,
                        successful_judge_rows=len(completed),
                        warning_usd=warning_usd,
                        absolute_maximum_usd=absolute_maximum_usd,
                    )
                    raise RuntimeError(
                        "judge paused cleanly between requests at the spending threshold"
                    )
    write_budget_status(
        args.budget_status,
        state="completed",
        run_id=contract["run_id"],
        snapshot_sha256=snapshot_sha,
        reported_cost_usd=reported_cost,
        successful_judge_rows=len(completed),
        warning_usd=warning_usd,
        absolute_maximum_usd=absolute_maximum_usd,
    )


if __name__ == "__main__":
    main()
