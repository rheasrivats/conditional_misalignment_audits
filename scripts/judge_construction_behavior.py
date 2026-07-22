#!/usr/bin/env python3
"""Apply the three frozen GPT-4o judges to development behavior rows."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx


ALLOWED_STAGES = {
    "construction_development_evaluation",
    "medical_parent_development_screen",
}
JUDGE_FILES = {
    "alignment": "prompts/judges/alignment.txt",
    "coherence": "prompts/judges/coherence.txt",
    "is_code": "prompts/judges/is_code.txt",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def existing_keys(path: Path) -> set[tuple[str, str]]:
    if not path.exists():
        return set()
    keys: set[tuple[str, str]] = set()
    for row in load_rows(path):
        key = (row["behavior_row_id"], row["judge_name"])
        if key in keys:
            raise ValueError(f"duplicate existing judge key: {key}")
        keys.add(key)
    return keys


def call_judge(
    client: httpx.Client,
    *,
    api_key: str,
    model: str,
    prompt: str,
    temperature: float,
    max_tokens: int,
    runtime: dict[str, Any],
    rating: bool,
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
        "logprobs": runtime["rating_logprobs"] if rating else runtime["logprobs"],
    }
    if runtime["seed"] is not None:
        request["seed"] = runtime["seed"]
    if rating:
        request["top_logprobs"] = runtime["rating_top_logprobs"]
    response = client.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json=request,
    )
    response.raise_for_status()
    payload = response.json()
    return {
        "response_id": payload.get("id"),
        "model_returned": payload.get("model"),
        "system_fingerprint": payload.get("system_fingerprint"),
        "text": payload["choices"][0]["message"]["content"],
        "logprobs": payload["choices"][0].get("logprobs"),
        "finish_reason": payload["choices"][0].get("finish_reason"),
        "usage": payload.get("usage"),
        "request": request,
    }


def expected_rating(
    logprobs_payload: dict[str, Any] | None,
    *,
    minimum: int,
    maximum: int,
    refusal_threshold: float,
) -> dict[str, Any]:
    """Reproduce llmcomp 1.4.0 RatingJudge expected-value semantics."""
    if not logprobs_payload:
        raise ValueError("rating judge response lacks logprobs")
    content = logprobs_payload.get("content")
    if not isinstance(content, list) or len(content) != 1:
        raise ValueError("rating judge must return logprobs for exactly one token")
    alternatives = content[0].get("top_logprobs")
    if not isinstance(alternatives, list) or not alternatives:
        raise ValueError("rating judge lacks top_logprobs alternatives")

    raw: list[dict[str, Any]] = []
    seen_tokens: set[str] = set()
    numeric: dict[int, float] = {}
    numeric_mass = 0.0
    for item in alternatives:
        token = item.get("token")
        token_logprob = item.get("logprob")
        if not isinstance(token, str) or not isinstance(token_logprob, (int, float)):
            raise ValueError("malformed top_logprobs item")
        if token in seen_tokens:
            raise ValueError(f"duplicate token in rating logprobs: {token!r}")
        seen_tokens.add(token)
        probability = math.exp(float(token_logprob))
        raw.append(
            {
                "token": token,
                "logprob": float(token_logprob),
                "probability": probability,
                "bytes": item.get("bytes"),
            }
        )
        try:
            numeric_value = int(token)
        except ValueError:
            continue
        if minimum <= numeric_value <= maximum:
            numeric[numeric_value] = numeric.get(numeric_value, 0.0) + probability
            numeric_mass += probability

    refused = numeric_mass == 0.0 or (1.0 - numeric_mass) >= refusal_threshold
    normalized = (
        None
        if refused
        else {str(key): value / numeric_mass for key, value in sorted(numeric.items())}
    )
    score = (
        None
        if normalized is None
        else sum(int(key) * probability for key, probability in normalized.items())
    )
    return {
        "score": score,
        "numeric_probability_mass": numeric_mass,
        "normalized_numeric_probabilities": normalized,
        "raw_top_token_logprobs": raw,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--behavior", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--request-ledger", type=Path)
    parser.add_argument("--code-provenance", type=Path)
    parser.add_argument("--network-preflight", type=Path)
    parser.add_argument("--prior-incident-ledger", type=Path)
    return parser.parse_args()


def load_request_attempts(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return load_rows(path)


def validate_request_attempts(
    rows: list[dict[str, Any]],
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    states: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        attempt_id = row.get("request_attempt_id")
        event = row.get("event")
        if not isinstance(attempt_id, str) or event not in {
            "started",
            "succeeded",
            "failed",
        }:
            raise ValueError("malformed judge request-attempt ledger row")
        states.setdefault(attempt_id, []).append(row)
    attempts_by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for attempt_id, events in states.items():
        event_names = [row["event"] for row in events]
        if event_names[0] != "started" or len(events) not in {1, 2}:
            raise ValueError(f"invalid request-attempt event sequence: {attempt_id}")
        if len(events) == 2 and event_names[1] not in {"succeeded", "failed"}:
            raise ValueError(f"invalid terminal request event: {attempt_id}")
        started = events[0]
        behavior_row_id = started.get("behavior_row_id")
        judge_name = started.get("judge_name")
        attempt_number = started.get("attempt_number")
        if (
            not isinstance(behavior_row_id, str)
            or not isinstance(judge_name, str)
            or not isinstance(attempt_number, int)
            or attempt_number < 1
        ):
            raise ValueError(f"malformed started request event: {attempt_id}")
        attempts_by_key.setdefault((behavior_row_id, judge_name), []).append(
            {
                "request_attempt_id": attempt_id,
                "attempt_number": attempt_number,
                "terminal_event": event_names[1] if len(events) == 2 else None,
                "retryable": events[1].get("retryable") if len(events) == 2 else None,
            }
        )
    for key, attempts in attempts_by_key.items():
        attempts.sort(key=lambda item: item["attempt_number"])
        observed = [item["attempt_number"] for item in attempts]
        if observed != list(range(1, len(attempts) + 1)):
            raise ValueError(f"nonconsecutive request attempts for {key}")
        if any(
            item["terminal_event"] == "succeeded" for item in attempts[:-1]
        ):
            raise ValueError(f"request attempts continue after success for {key}")
    return attempts_by_key


def validate_medical_successor_inputs(
    *,
    snapshot: dict[str, Any],
    snapshot_path: Path,
    behavior_path: Path,
    behavior_rows: list[dict[str, Any]],
    code_provenance_path: Path | None,
    network_preflight_path: Path | None,
    prior_incident_ledger_path: Path | None,
    request_ledger_path: Path | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate the v1 behavior reuse and every v2 successor-only artifact."""
    values = snapshot["values"]
    successor = values["qualification.medical_parent_judge_dns_failure_successor"]
    predecessor = successor["predecessor"]
    incident = successor["incident_attempt_ledger"]
    preflight_contract = successor["network_preflight"]
    expected_snapshot = sha256_file(snapshot_path)

    if sha256_file(behavior_path) != predecessor["behavior_sha256"]:
        raise ValueError("medical behavior file differs from frozen predecessor hash")
    if len(behavior_rows) != predecessor["behavior_rows"]:
        raise ValueError("medical behavior row count differs from frozen predecessor")
    if any(
        row.get("stage_snapshot_sha256") != predecessor["stage_snapshot_sha256"]
        for row in behavior_rows
    ):
        raise ValueError("medical behavior rows do not reference the frozen predecessor")
    behavior_code_provenance = predecessor["behavior_code_provenance"]
    if any(
        row.get("code_provenance") != behavior_code_provenance
        for row in behavior_rows
    ):
        raise ValueError("medical behavior provenance differs from frozen predecessor")

    if prior_incident_ledger_path is None:
        raise ValueError("medical successor requires the preserved incident ledger")
    if sha256_file(prior_incident_ledger_path) != incident["sha256"]:
        raise ValueError("incident ledger differs from frozen INC-0003 hash")
    incident_rows = load_rows(prior_incident_ledger_path)
    if len(incident_rows) != incident["event_rows"]:
        raise ValueError("incident ledger event count differs from frozen value")
    if sum(row.get("event") == "started" for row in incident_rows) != incident["started_attempts"]:
        raise ValueError("incident ledger started-attempt count differs from frozen value")
    failures = [row for row in incident_rows if row.get("event") == "failed"]
    if len(failures) != incident["failed_attempts"] or any(
        row.get("error_type") != incident["error_type"]
        or row.get("error") != incident["error"]
        for row in failures
    ):
        raise ValueError("incident ledger failures differ from frozen DNS incident")
    if request_ledger_path is None:
        raise ValueError("medical successor requires a fresh append-only request ledger")
    if request_ledger_path.resolve() == prior_incident_ledger_path.resolve():
        raise ValueError("successor request ledger must be distinct from incident ledger")

    if network_preflight_path is None:
        raise ValueError("medical successor requires a DNS/TCP/TLS preflight artifact")
    preflight = json.loads(network_preflight_path.read_text())
    if preflight.get("passed") is not True:
        raise ValueError("network preflight did not pass")
    if preflight.get("stage_snapshot_sha256") != expected_snapshot:
        raise ValueError("network preflight references a different successor snapshot")
    if (
        preflight.get("host") != preflight_contract["host"]
        or preflight.get("port") != preflight_contract["port"]
        or preflight.get("http_request_made") is not False
        or preflight.get("api_key_used") is not False
    ):
        raise ValueError("network preflight differs from its frozen contract")
    if not preflight.get("resolved_addresses") or not preflight.get("tls_version"):
        raise ValueError("network preflight lacks DNS or TLS evidence")

    if code_provenance_path is None:
        raise ValueError("medical successor requires versioned execution provenance")
    execution_code_provenance = json.loads(code_provenance_path.read_text())
    if execution_code_provenance.get("stage_snapshot_sha256") != expected_snapshot:
        raise ValueError("execution provenance references a different successor snapshot")
    if execution_code_provenance.get("judge_script_sha256") != sha256_file(Path(__file__)):
        raise ValueError("judge script differs from successor execution provenance")
    return behavior_code_provenance, execution_code_provenance


def main() -> None:
    args = parse_args()
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not exported")
    snapshot = json.loads(args.snapshot.read_text())
    stage = snapshot.get("stage")
    if stage not in ALLOWED_STAGES:
        raise ValueError(f"snapshot stage {stage!r} is not supported")
    judge = snapshot["values"]["qualification.response_judging_protocol"]
    runtime = snapshot["values"]["qualification.judge_api_runtime_contract"]
    if runtime["base_judging_parameter"] != "qualification.response_judging_protocol":
        raise ValueError("judge runtime contract references the wrong base parameter")
    if runtime["endpoint"] != "chat_completions":
        raise ValueError("unsupported frozen judge endpoint")
    if set(runtime["rating_judges"]) != {"alignment", "coherence"}:
        raise ValueError("frozen rating judge set is invalid")
    if set(runtime["free_form_judges"]) != {"is_code"}:
        raise ValueError("frozen free-form judge set is invalid")
    if runtime["rating_method"] != "normalized_expected_value_from_single_next_token_logprobs":
        raise ValueError("unsupported frozen rating method")
    if runtime["rating_max_tokens"] != 1 or not runtime["rating_logprobs"]:
        raise ValueError("rating contract must request one token with logprobs")
    if runtime["logprobs"]:
        raise ValueError("free-form is-code judge must not request logprobs")
    if not runtime["exact_returned_model_required"]:
        raise ValueError("exact judge model identity must be required")
    if not runtime["record_system_fingerprint"] or not runtime["record_raw_top_token_logprobs"]:
        raise ValueError("frozen judge provenance recording cannot be disabled")
    implied_minimum_mass = 1.0 - runtime[
        "rating_refusal_threshold_nonnumeric_probability"
    ]
    if abs(implied_minimum_mass - runtime["rating_numeric_probability_mass_must_exceed"]) > 1e-12:
        raise ValueError("rating refusal and numeric-mass thresholds are inconsistent")
    behavior_rows = load_rows(args.behavior)
    if not behavior_rows:
        raise ValueError("behavior file is empty")
    expected_snapshot = sha256_file(args.snapshot)
    if stage == "medical_parent_development_screen":
        screen = snapshot["values"][
            "qualification.medical_parent_screen_specification"
        ]["screen"]
        if len(behavior_rows) != screen["expected_behavior_rows"]:
            raise ValueError("medical behavior row count differs from snapshot")
        if {row["checkpoint_label"] for row in behavior_rows} != {
            screen["checkpoint_label"]
        }:
            raise ValueError("medical behavior checkpoint differs from snapshot")
        if {row["context"] for row in behavior_rows} != set(screen["contexts"]):
            raise ValueError("medical behavior contexts differ from snapshot")
        if args.request_ledger is None:
            raise ValueError("medical screen requires an append-only request ledger")
        safety = snapshot["values"][
            "qualification.medical_parent_judge_execution_safety"
        ]
        if safety["applies_to_specification"] != (
            snapshot["values"]["qualification.medical_parent_screen_specification"][
                "specification_id"
            ]
        ):
            raise ValueError("judge safety contract references the wrong screen")
        if safety["expected_successful_judge_rows"] != screen["expected_judge_rows"]:
            raise ValueError("judge safety row count differs from the screen")
        if safety["maximum_attempts_per_judge_row"] != 3:
            raise ValueError("medical screen must use three total attempts per judge row")
        if safety["automatic_retries_after_initial_attempt"] != 2:
            raise ValueError("medical screen retry count differs from snapshot")
        if safety["maximum_api_request_attempts"] != (
            screen["expected_judge_rows"]
            * safety["maximum_attempts_per_judge_row"]
        ):
            raise ValueError("medical screen global request ceiling is inconsistent")
        attempts_by_key = validate_request_attempts(
            load_request_attempts(args.request_ledger)
        )
        prior_attempt_count = sum(len(items) for items in attempts_by_key.values())
        behavior_code_provenance, code_provenance = validate_medical_successor_inputs(
            snapshot=snapshot,
            snapshot_path=args.snapshot,
            behavior_path=args.behavior,
            behavior_rows=behavior_rows,
            code_provenance_path=args.code_provenance,
            network_preflight_path=args.network_preflight,
            prior_incident_ledger_path=args.prior_incident_ledger,
            request_ledger_path=args.request_ledger,
        )
    else:
        safety = None
        attempts_by_key = {}
        prior_attempt_count = 0
        if any(row["stage_snapshot_sha256"] != expected_snapshot for row in behavior_rows):
            raise ValueError("behavior rows do not all reference this snapshot")
        code_provenance = behavior_rows[0].get("code_provenance")
        behavior_code_provenance = code_provenance
        if not isinstance(code_provenance, dict):
            raise ValueError("behavior rows lack code provenance")
        if any(row.get("code_provenance") != code_provenance for row in behavior_rows):
            raise ValueError("behavior rows have inconsistent code provenance")
        if code_provenance.get("judge_script_sha256") != sha256_file(Path(__file__)):
            raise ValueError("judge script differs from behavior code provenance")
    if args.output.exists():
        existing_rows = load_rows(args.output)
        if any(
            row.get("stage_snapshot_sha256") != expected_snapshot
            for row in existing_rows
        ):
            raise ValueError("existing judge rows reference a different snapshot")
        if any(row.get("code_provenance") != code_provenance for row in existing_rows):
            raise ValueError("existing judge rows reference different code provenance")
        if stage == "medical_parent_development_screen" and any(
            row.get("behavior_code_provenance") != behavior_code_provenance
            for row in existing_rows
        ):
            raise ValueError("existing judge rows reference different behavior provenance")

    prompts: dict[str, str] = {}
    for judge_name in judge["prompts"]:
        path = args.workspace / JUDGE_FILES[judge_name]
        expected_hash = judge["prompt_sha256"][judge_name]
        if sha256_file(path) != expected_hash:
            raise ValueError(f"{judge_name} judge prompt hash differs from frozen value")
        prompts[judge_name] = path.read_text().strip()

    completed = existing_keys(args.output)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.request_ledger is not None:
        args.request_ledger.parent.mkdir(parents=True, exist_ok=True)
    request_ledger_handle = (
        args.request_ledger.open("a", encoding="utf-8")
        if args.request_ledger is not None
        else None
    )
    client_timeout = safety["request_timeout_seconds"] if safety is not None else 120.0
    with httpx.Client(timeout=client_timeout) as client, args.output.open(
        "a", encoding="utf-8"
    ) as handle:
        try:
            for behavior in behavior_rows:
                for judge_name in judge["prompts"]:
                    key = (behavior["row_id"], judge_name)
                    if key in completed:
                        continue
                    rendered_prompt = prompts[judge_name].format(
                        question=behavior["prompt"], answer=behavior["response"]
                    )
                    is_rating = judge_name in runtime["rating_judges"]
                    if not is_rating and judge_name not in runtime["free_form_judges"]:
                        raise ValueError(f"judge {judge_name!r} has no frozen runtime mode")
                    max_tokens = (
                        runtime["rating_max_tokens"]
                        if is_rating
                        else runtime["free_form_max_tokens"]
                    )
                    if safety is not None:
                        prior_for_key = attempts_by_key.get(key, [])
                        if any(
                            item["terminal_event"] == "succeeded"
                            for item in prior_for_key
                        ):
                            raise ValueError(
                                f"request ledger records success but judge row is absent: {key}"
                            )
                        if (
                            prior_for_key
                            and prior_for_key[-1]["terminal_event"] == "failed"
                            and prior_for_key[-1]["retryable"] is False
                        ):
                            raise RuntimeError(
                                f"non-retryable prior judge failure blocks resume: {key}"
                            )
                        result = None
                        request_attempt_id = ""
                        while len(prior_for_key) < safety[
                            "maximum_attempts_per_judge_row"
                        ]:
                            if prior_attempt_count >= safety["maximum_api_request_attempts"]:
                                raise RuntimeError(
                                    "judge request-attempt ceiling reached before submission"
                                )
                            attempt_number = len(prior_for_key) + 1
                            request_attempt_id = hashlib.sha256(
                                (
                                    f"{expected_snapshot}|{key[0]}|{judge_name}|"
                                    f"{attempt_number}"
                                ).encode()
                            ).hexdigest()
                            started = {
                                "request_attempt_id": request_attempt_id,
                                "event": "started",
                                "behavior_row_id": key[0],
                                "judge_name": judge_name,
                                "attempt_number": attempt_number,
                                "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
                                "stage_snapshot_sha256": expected_snapshot,
                                "code_provenance": code_provenance,
                            }
                            assert request_ledger_handle is not None
                            request_ledger_handle.write(
                                json.dumps(started, ensure_ascii=False) + "\n"
                            )
                            request_ledger_handle.flush()
                            prior_attempt_count += 1
                            attempt_state = {
                                "request_attempt_id": request_attempt_id,
                                "attempt_number": attempt_number,
                                "terminal_event": None,
                                "retryable": None,
                            }
                            prior_for_key.append(attempt_state)
                            attempts_by_key[key] = prior_for_key
                            try:
                                result = call_judge(
                                    client,
                                    api_key=api_key,
                                    model=judge["model"],
                                    prompt=rendered_prompt,
                                    temperature=judge["temperature"],
                                    max_tokens=max_tokens,
                                    runtime=runtime,
                                    rating=is_rating,
                                )
                                break
                            except (httpx.HTTPError, KeyError, ValueError) as error:
                                request_ledger_handle.write(
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
                                request_ledger_handle.flush()
                                attempt_state["terminal_event"] = "failed"
                                attempt_state["retryable"] = True
                                if len(prior_for_key) < safety[
                                    "maximum_attempts_per_judge_row"
                                ]:
                                    backoff_index = len(prior_for_key) - 1
                                    time.sleep(
                                        safety["retry_backoff_seconds"][backoff_index]
                                    )
                        if result is None:
                            raise RuntimeError(
                                f"judge call exhausted three total attempts for {key}"
                            )
                    else:
                        # Preserve the historical construction runner. New medical
                        # work never enters this unfrozen legacy retry branch.
                        last_error: Exception | None = None
                        result = None
                        for retry in range(5):
                            try:
                                result = call_judge(
                                    client,
                                    api_key=api_key,
                                    model=judge["model"],
                                    prompt=rendered_prompt,
                                    temperature=judge["temperature"],
                                    max_tokens=max_tokens,
                                    runtime=runtime,
                                    rating=is_rating,
                                )
                                break
                            except (httpx.HTTPError, KeyError, ValueError) as error:
                                last_error = error
                                if retry < 4:
                                    time.sleep(2**retry)
                        if result is None:
                            raise RuntimeError(
                                f"judge call failed for {key}: {last_error}"
                            )
                    try:
                        if result["model_returned"] != judge["model"]:
                            raise ValueError(
                                f"API returned model {result['model_returned']!r}, "
                                f"expected exact frozen model {judge['model']!r}"
                            )
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
                                refusal_threshold=runtime[
                                    "rating_refusal_threshold_nonnumeric_probability"
                                ],
                            )
                    except (KeyError, ValueError) as error:
                        if safety is not None:
                            assert request_ledger_handle is not None
                            request_ledger_handle.write(
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
                            request_ledger_handle.flush()
                            attempts_by_key[key][-1]["terminal_event"] = "failed"
                            attempts_by_key[key][-1]["retryable"] = False
                        raise RuntimeError(
                            f"non-retryable judge response validation failed for {key}"
                        ) from error
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
                            key: value
                            for key, value in result["request"].items()
                            if key not in {"messages"}
                        },
                        **rating_result,
                        "judged_at_utc": datetime.now(timezone.utc).isoformat(),
                        "stage_snapshot_sha256": expected_snapshot,
                        "code_provenance": code_provenance,
                        "behavior_stage_snapshot_sha256": behavior["stage_snapshot_sha256"],
                        "behavior_code_provenance": behavior_code_provenance,
                    }
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                    handle.flush()
                    if safety is not None:
                        assert request_ledger_handle is not None
                        request_ledger_handle.write(
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
                        request_ledger_handle.flush()
                        attempts_by_key[key][-1]["terminal_event"] = "succeeded"
                    completed.add(key)
                    print(f"judged {key[0]} {judge_name}")
        finally:
            if request_ledger_handle is not None:
                request_ledger_handle.close()


if __name__ == "__main__":
    main()
