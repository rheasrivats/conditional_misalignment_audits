#!/usr/bin/env python3
"""Implementation-only verifier repair for zero-semantics sensitivity v1."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import analyze_claim1_nla_judge1_zero_semantics_v1 as v1


STAGE = "claim1_nla_judge1_zero_semantics_sensitivity_v2"
CONTRACT_KEY = "nla.claim1_nla_judge1_zero_semantics_sensitivity_v2"


def verify_contract(contract: dict[str, Any]) -> None:
    for name, binding in contract["immutable_inputs"].items():
        if not isinstance(binding, dict) or set(binding) != {"path", "sha256"}:
            raise ValueError(f"invalid immutable input binding: {name}")
        path = v1.resolve(binding["path"])
        if not path.is_file() or v1.sha256(path) != binding["sha256"]:
            raise ValueError(f"immutable input mismatch: {path}")
    for name, binding in contract["code_and_spec"].items():
        if name == "focused_tests_passed":
            if not isinstance(binding, int) or isinstance(binding, bool) or binding < 1:
                raise ValueError("invalid focused test count")
            continue
        if not isinstance(binding, dict) or set(binding) != {"path", "sha256"}:
            raise ValueError(f"invalid code/spec binding: {name}")
        path = v1.resolve(binding["path"])
        if not path.is_file() or v1.sha256(path) != binding["sha256"]:
            raise ValueError(f"code/spec mismatch: {path}")
    if contract["execution"] != {
        "api_requests": 0,
        "egress": "none",
        "local_only": True,
        "spending_usd": 0,
    }:
        raise ValueError("successor execution contract is not local-only")


def run(snapshot_path: Path) -> dict[str, Any]:
    v1.STAGE = STAGE
    v1.CONTRACT_KEY = CONTRACT_KEY
    v1.verify_contract = verify_contract
    return v1.run(snapshot_path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.snapshot.resolve()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
