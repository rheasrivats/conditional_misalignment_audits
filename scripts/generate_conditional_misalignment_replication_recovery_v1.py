#!/usr/bin/env python3
"""Launch the frozen no-overwrite HHH replication suffix recovery."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import generate_conditional_misalignment_replication_topup_v1 as topup


STAGE = "conditional_misalignment_replication_hhh_seed1_recovery_v1"
CONTRACT = "diagnostics.conditional_misalignment_replication_hhh_seed1_recovery_v1"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_wrapper(snapshot_path: Path) -> None:
    snapshot = json.loads(snapshot_path.read_text())
    if snapshot.get("stage") != STAGE:
        raise ValueError("recovery launcher received another stage")
    contract = snapshot["values"][CONTRACT]
    if contract.get("stage") != STAGE:
        raise ValueError("recovery contract names another stage")
    if sha256_file(Path(__file__)) != contract["code"]["recovery_launcher_sha256"]:
        raise ValueError("recovery launcher differs from frozen identity")


def main() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    args, unknown = parser.parse_known_args()
    if unknown:
        raise ValueError(f"unexpected recovery arguments: {unknown}")
    validate_wrapper(args.snapshot)
    topup.STAGE_CONTRACTS[STAGE] = CONTRACT
    topup.main()


if __name__ == "__main__":
    main()
