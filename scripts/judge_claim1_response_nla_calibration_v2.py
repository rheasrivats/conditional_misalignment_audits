#!/usr/bin/env python3
"""Implementation-only contract-key adapter for calibration attempt 002."""

from __future__ import annotations

import copy

import judge_claim1_response_nla_concordance_v1 as base


base.STAGE = "claim1_response_nla_calibration_v2"
base.CONTRACT_KEY = "nla.claim1_response_nla_calibration_execution_successor_v2"


def _load_contract_with_packet_alias(snapshot_path):
    snapshot = base.preparation.read_json(snapshot_path)
    if snapshot.get("stage") != base.STAGE:
        raise ValueError("wrong calibration successor stage")
    values = snapshot.get("values", {})
    adapted = copy.deepcopy(values["nla.claim1_response_nla_calibration_v1"])
    successor = values[base.CONTRACT_KEY]
    if successor.get("repair") != "alias_frozen_calibration_packet_as_runner_packet_without_value_change":
        raise ValueError("unexpected calibration successor repair")
    adapted["output_paths"] = copy.deepcopy(successor["output_paths"])
    calibration = adapted["calibration"]
    adapted["packet"] = {
        "sha256": calibration["packet_sha256"],
        "request_count": calibration["request_count"],
        "repetitions": calibration["repetitions"],
    }
    return adapted, base.preparation.sha256_file(snapshot_path)


base._load_contract = _load_contract_with_packet_alias


if __name__ == "__main__":
    raise SystemExit(base.main())
