#!/usr/bin/env python3
"""Apply the three frozen GPT-4o judges to construction behavior rows."""

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


STAGE = "construction_development_evaluation"
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
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not exported")
    snapshot = json.loads(args.snapshot.read_text())
    if snapshot.get("stage") != STAGE:
        raise ValueError(f"snapshot is not for {STAGE}")
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
    if any(row["stage_snapshot_sha256"] != expected_snapshot for row in behavior_rows):
        raise ValueError("behavior rows do not all reference this snapshot")
    code_provenance = behavior_rows[0].get("code_provenance")
    if not isinstance(code_provenance, dict):
        raise ValueError("behavior rows lack code provenance")
    if any(row.get("code_provenance") != code_provenance for row in behavior_rows):
        raise ValueError("behavior rows have inconsistent code provenance")
    if code_provenance.get("judge_script_sha256") != sha256_file(Path(__file__)):
        raise ValueError("judge script differs from behavior code provenance")

    prompts: dict[str, str] = {}
    for judge_name in judge["prompts"]:
        path = args.workspace / JUDGE_FILES[judge_name]
        expected_hash = judge["prompt_sha256"][judge_name]
        if sha256_file(path) != expected_hash:
            raise ValueError(f"{judge_name} judge prompt hash differs from frozen value")
        prompts[judge_name] = path.read_text().strip()

    completed = existing_keys(args.output)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=120.0) as client, args.output.open(
        "a", encoding="utf-8"
    ) as handle:
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
                last_error: Exception | None = None
                result: dict[str, Any] | None = None
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
                        if retry == 4:
                            break
                        time.sleep(2**retry)
                if result is None:
                    raise RuntimeError(f"judge call failed for {key}: {last_error}")
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
                }
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                handle.flush()
                completed.add(key)
                print(f"judged {key[0]} {judge_name}")


if __name__ == "__main__":
    main()
