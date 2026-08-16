#!/usr/bin/env python3
"""Stable metadata-compatible successor for complete HHH panels."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import scripts.score_conditional_misalignment_hhh_full_panels_v2 as predecessor


STAGE = "conditional_misalignment_replication_hhh_full_panels_scoring_v4"
CONTRACT = "diagnostics.conditional_misalignment_replication_hhh_full_panels_scoring_v4"
ORIGINAL_NORMALIZE_REPLICATION_ROW = predecessor.normalize_replication_row


def normalize_replication_row(
    row: dict[str, Any],
    **kwargs: Any,
) -> dict[str, Any]:
    compatible = dict(row)
    if "scoring_snapshot_sha256" not in compatible:
        compatible["scoring_snapshot_sha256"] = compatible[
            "combined_scoring_snapshot_sha256"
        ]
    return ORIGINAL_NORMALIZE_REPLICATION_ROW(compatible, **kwargs)


def main() -> None:
    args = predecessor.parse_args()
    snapshot = json.loads(args.snapshot.read_text())
    if snapshot.get("stage") != STAGE:
        raise ValueError(f"unexpected stage: {snapshot.get('stage')!r}")
    contract = snapshot["values"][CONTRACT]
    if predecessor.sha256_file(Path(__file__)) != contract["code"]["wrapper_sha256"]:
        raise ValueError("full-panel successor wrapper differs from frozen identity")
    if predecessor.sha256_file(Path(predecessor.__file__)) != contract["code"]["runner_sha256"]:
        raise ValueError("full-panel predecessor helper differs from frozen identity")
    predecessor.STAGE = STAGE
    predecessor.CONTRACT = CONTRACT
    predecessor.normalize_replication_row = normalize_replication_row
    predecessor.main()


if __name__ == "__main__":
    main()
