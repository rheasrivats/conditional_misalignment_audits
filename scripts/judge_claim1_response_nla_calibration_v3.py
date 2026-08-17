#!/usr/bin/env python3
"""Complete implementation-only contract adapter for calibration attempt 003."""

from __future__ import annotations

import copy

import judge_claim1_response_nla_concordance_v1 as base


STAGE = "claim1_response_nla_calibration_v3"
BASE_KEY = "nla.claim1_response_nla_calibration_v1"
SUCCESSOR_KEY = "nla.claim1_response_nla_calibration_execution_successor_v3"
base.STAGE = STAGE
base.CONTRACT_KEY = SUCCESSOR_KEY


def _load_complete_adapter(snapshot_path):
    snapshot = base.preparation.read_json(snapshot_path)
    if snapshot.get("stage") != STAGE:
        raise ValueError("wrong calibration v3 successor stage")
    values = snapshot.get("values", {})
    adapted = copy.deepcopy(values[BASE_KEY])
    successor = values[SUCCESSOR_KEY]
    if successor.get("repair") != "complete_runner_aliases_for_calibration_packet_and_schema":
        raise ValueError("unexpected calibration v3 repair")
    adapted["output_paths"] = copy.deepcopy(successor["output_paths"])
    calibration = adapted["calibration"]
    adapted["packet"] = {
        "sha256": calibration["packet_sha256"],
        "request_count": calibration["request_count"],
        "repetitions": calibration["repetitions"],
    }
    adapted["schema"] = copy.deepcopy(adapted["artifacts"]["schema"])
    return adapted, base.preparation.sha256_file(snapshot_path)


base._load_contract = _load_complete_adapter


if __name__ == "__main__":
    raise SystemExit(base.main())
