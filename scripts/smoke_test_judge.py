#!/usr/bin/env python3
"""Make one explicitly authorized availability check of the proposed judge."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import yaml


PARAMETER_ID = "qualification.response_judging_protocol"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--acknowledge-paid-api-call", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.acknowledge_paid_api_call:
        raise ValueError("refusing paid request without --acknowledge-paid-api-call")
    if args.output.exists():
        raise FileExistsError(args.output)
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not exported")

    registry = yaml.safe_load(args.registry.read_text())
    parameter = registry["parameters"][PARAMETER_ID]
    if parameter["status"] not in {
        "proposed",
        "confirmed_pending_runtime_validation",
        "frozen",
    }:
        raise ValueError(f"judge parameter status is {parameter['status']!r}")
    judge: dict[str, Any] = parameter["value"]
    prompt_path = args.workspace / judge["prompt_paths"]["alignment"]
    if sha256_file(prompt_path) != judge["prompt_sha256"]["alignment"]:
        raise ValueError("alignment prompt hash differs from proposed value")
    rendered = prompt_path.read_text().strip().format(
        question="What is a thoughtful way to apologize for a minor mistake?",
        answer="Acknowledge the mistake, apologize directly, and explain how you will repair it.",
    )

    with httpx.Client(timeout=120.0) as client:
        response = client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": judge["model"],
                "messages": [{"role": "user", "content": rendered}],
                "temperature": judge["temperature"],
                "max_tokens": judge["max_output_tokens"],
            },
        )
        response.raise_for_status()
        payload = response.json()

    returned_model = payload.get("model")
    if returned_model != judge["model"]:
        raise ValueError(
            f"API returned model {returned_model!r}, expected exact {judge['model']!r}"
        )
    raw_output = payload["choices"][0]["message"]["content"].strip()
    try:
        score = float(raw_output)
    except ValueError as error:
        raise ValueError(f"judge did not return a numeric score: {raw_output!r}") from error
    if not 0 <= score <= 100:
        raise ValueError(f"judge score is outside 0..100: {score}")

    report = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "parameter_id": PARAMETER_ID,
        "parameter_status_at_check": parameter["status"],
        "model_requested": judge["model"],
        "model_returned": returned_model,
        "response_id": payload.get("id"),
        "raw_output": raw_output,
        "usage": payload.get("usage"),
        "registry_sha256": sha256_file(args.registry),
        "judge_prompt_sha256": judge["prompt_sha256"]["alignment"],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(f"JUDGE AVAILABILITY CHECK PASSED: {args.output}")


if __name__ == "__main__":
    main()
