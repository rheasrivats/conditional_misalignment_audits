#!/usr/bin/env python3
"""Implementation-only stage adapter for calibration attempt 002 analysis."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

import analyze_claim1_response_nla_calibration_v1 as base


STAGE = "claim1_response_nla_calibration_v2"
BASE_KEY = "nla.claim1_response_nla_calibration_v1"
SUCCESSOR_KEY = "nla.claim1_response_nla_calibration_execution_successor_v2"


def run(snapshot_path, accepted_path, failed_path, output_path):
    snapshot = base.preparation.read_json(snapshot_path)
    if snapshot.get("stage") != STAGE:
        raise ValueError("calibration successor snapshot stage mismatch")
    values = snapshot.get("values", {})
    contract = copy.deepcopy(values[BASE_KEY])
    contract["output_paths"] = copy.deepcopy(values[SUCCESSOR_KEY]["output_paths"])
    for name, path, expected in (
        ("accepted outputs", accepted_path, contract["output_paths"]["accepted_outputs"]),
        ("failed items", failed_path, contract["output_paths"]["failed_items"]),
    ):
        if str(path) != expected:
            raise ValueError(f"{name} path differs from frozen successor contract")
    failed = base.preparation.read_jsonl(failed_path)
    if failed:
        verdict = {"qualified": False, "accepted_items": len(base.preparation.read_jsonl(accepted_path)),
                   "expected_items": contract["calibration"]["request_count"], "failure_count": 1,
                   "failures": ["one_or_more_items_exhausted_retries"]}
    else:
        verdict = base.preparation.evaluate_calibration(
            base.preparation.read_jsonl(accepted_path),
            base.preparation.read_jsonl(base.preparation.ROOT / contract["calibration"]["reveal_key_path"]),
            base.preparation.read_json(base.preparation.ROOT / contract["artifacts"]["calibration_expectations"]["path"]),
        )
    verdict.update({"schema_version": "claim1_response_nla_calibration_verdict_v1",
                    "target_requests_authorized": False, "target_requests_sent": 0, "calibration_only": True})
    base.preparation.write_json(output_path, verdict)
    return verdict


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--accepted", type=Path, required=True)
    parser.add_argument("--failed", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.snapshot, args.accepted, args.failed, args.output), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
