#!/usr/bin/env python3
"""Frozen contract adapter for the zero-row DEC-0279 seed/output repair."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json as std_json
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any


STAGE = "medical_claim1_fixed_prefix_phase1_v1"
CONTRACT_PARAMETER = "interventions.medical_claim1_fixed_prefix_phase1_v1"
REPAIR_PARAMETER = "execution.medical_claim1_fixed_prefix_phase1_zero_row_repair_v1"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    return parser.parse_args()


def load_base_runner() -> Any:
    path = Path(__file__).with_name("run_medical_claim1_fixed_prefix_phase1_v1.py")
    spec = importlib.util.spec_from_file_location("fixed_prefix_phase1_v1_frozen", path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    args = parse_args()
    raw = args.snapshot.read_bytes()
    frozen = std_json.loads(raw)
    if frozen.get("stage") != STAGE:
        raise ValueError("wrong frozen stage")
    repair = frozen["values"].get(REPAIR_PARAMETER)
    if not isinstance(repair, dict):
        raise ValueError(f"missing {REPAIR_PARAMETER}")
    if sha256_file(Path(__file__)) != repair["code"]["adapter_sha256"]:
        raise ValueError("repair adapter differs from frozen identity")
    base = load_base_runner()
    original_write_json_exclusive = base.shared.write_json_exclusive

    def patched_loads(payload: Any, *load_args: Any, **load_kwargs: Any) -> Any:
        value = std_json.loads(payload, *load_args, **load_kwargs)
        if (
            isinstance(value, dict)
            and value.get("stage") == STAGE
            and isinstance(value.get("values"), dict)
            and REPAIR_PARAMETER in value["values"]
        ):
            value = copy.deepcopy(value)
            effective = copy.deepcopy(value["values"][CONTRACT_PARAMETER])
            successor = value["values"][REPAIR_PARAMETER]
            effective["seed_namespace"] = successor["seed_namespace"]
            effective["output_directory"] = successor["output_directory"]
            value["values"][CONTRACT_PARAMETER] = effective
        return value

    def patched_write_json_exclusive(path: Path, payload: dict[str, Any]) -> None:
        if path.name == "code_provenance.json":
            payload = {
                **payload,
                "execution_repair_parameter": REPAIR_PARAMETER,
                "execution_repair_approval": repair["approval"],
                "execution_repair_adapter_sha256": repair["code"]["adapter_sha256"],
                "preserved_zero_row_attempt": repair["preserved_failed_attempt"],
            }
        original_write_json_exclusive(path, payload)

    base.json = SimpleNamespace(loads=patched_loads, dumps=std_json.dumps)
    base.shared.write_json_exclusive = patched_write_json_exclusive
    sys.argv = [
        str(Path(__file__)),
        "--snapshot",
        str(args.snapshot),
        "--workspace",
        str(args.workspace),
    ]
    base.main()


if __name__ == "__main__":
    main()
