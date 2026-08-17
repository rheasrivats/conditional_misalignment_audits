#!/usr/bin/env python3
"""Evaluate the frozen directional response–NLA calibration gate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import prepare_claim1_response_nla_concordance_v1 as preparation


STAGE = "claim1_response_nla_calibration_v1"
CONTRACT_KEY = "nla.claim1_response_nla_calibration_v1"


def run(snapshot_path: Path, accepted_path: Path, failed_path: Path, output_path: Path) -> dict[str, Any]:
    snapshot = preparation.read_json(snapshot_path)
    if snapshot.get("stage") != STAGE:
        raise ValueError("calibration snapshot stage mismatch")
    contract = snapshot.get("values", {}).get(CONTRACT_KEY)
    if not isinstance(contract, dict):
        raise ValueError("calibration contract is absent")
    for name, path, expected in (
        ("accepted outputs", accepted_path, contract["output_paths"]["accepted_outputs"]),
        ("failed items", failed_path, contract["output_paths"]["failed_items"]),
    ):
        if str(path) != expected:
            raise ValueError(f"{name} path differs from frozen contract")
    if preparation.read_jsonl(failed_path):
        verdict = {
            "qualified": False,
            "accepted_items": len(preparation.read_jsonl(accepted_path)),
            "expected_items": contract["calibration"]["request_count"],
            "failure_count": 1,
            "failures": ["one_or_more_items_exhausted_retries"],
        }
    else:
        verdict = preparation.evaluate_calibration(
            preparation.read_jsonl(accepted_path),
            preparation.read_jsonl(preparation.ROOT / contract["calibration"]["reveal_key_path"]),
            preparation.read_json(preparation.ROOT / contract["artifacts"]["calibration_expectations"]["path"]),
        )
    verdict.update({
        "schema_version": "claim1_response_nla_calibration_verdict_v1",
        "target_requests_authorized": False,
        "target_requests_sent": 0,
        "calibration_only": True,
    })
    preparation.write_json(output_path, verdict)
    return verdict


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--accepted", type=Path, required=True)
    parser.add_argument("--failed", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.snapshot, args.accepted, args.failed, args.output), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
