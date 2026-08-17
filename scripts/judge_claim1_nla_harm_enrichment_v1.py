#!/usr/bin/env python3
"""Run the frozen 675-item harm-enrichment Judge 1 v3 packet."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import httpx

import judge_medical_claim1_nla_judge1_v3_target as base
import prepare_medical_claim1_nla_judge1_v3 as preparation


STAGE = "claim1_nla_harm_enrichment_judging_v1"
CONTRACT_KEY = "nla.claim1_nla_harm_enrichment_judging_v1"


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
    snapshot = preparation.read_json(args.snapshot)
    if snapshot.get("stage") != STAGE:
        raise ValueError("wrong harm-enrichment judging stage")
    contract = snapshot.get("values", {}).get(CONTRACT_KEY)
    if not isinstance(contract, dict):
        raise ValueError("snapshot lacks the harm-enrichment judging contract")
    snapshot_sha = preparation.sha256_file(args.snapshot)
    if preparation.sha256_file(Path(__file__)) != contract["code"]["runner_sha256"]:
        raise ValueError("runner differs from frozen identity")
    if preparation.sha256_file(args.packet) != contract["packet"]["packet_sha256"]:
        raise ValueError("packet differs from frozen identity")
    schema_path = Path(__file__).resolve().parents[1] / contract["instrument"]["schema_path"]
    if preparation.sha256_file(schema_path) != contract["instrument"]["schema_sha256"]:
        raise ValueError("schema differs from frozen identity")
    base._validate_preflight(preparation.read_json(args.network_preflight), snapshot_sha)
    runtime = contract["runtime"]
    if runtime.get("endpoint") != "https://api.openai.com/v1/responses" or runtime.get("store") is not False or runtime.get("tools") != "none":
        raise ValueError("runtime endpoint/store/tools contract is invalid")
    packet = preparation.read_jsonl(args.packet)
    if len(packet) != contract["packet"]["fresh_request_count"]:
        raise ValueError("request count differs from frozen contract")
    if contract["retry_policy"]["maximum_api_request_attempts"] != len(packet) * contract["retry_policy"]["maximum_attempts_per_item"]:
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
    for path in (output_path, failed_path, ledger_path, archive_path):
        path.touch(exist_ok=False)
    schema = preparation.read_json(schema_path)
    with httpx.Client(timeout=runtime["request_timeout_seconds"]) as client:
        result = base.run_packet(
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
        raise RuntimeError("run ended without terminal disposition for every item")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
