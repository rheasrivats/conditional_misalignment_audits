#!/usr/bin/env python3
"""Create the approved linear v2 successor for the INC-0036 ledger fork."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


EXPECTED_SOURCE_SHA256 = (
    "fd6a9ba5962ccf9efd8ef480d8b03d9e0e3324e514e6865703ca26e287da73df"
)
EXPECTED_SOURCE_LINES = 112
EXPECTED_VALID_HEAD = (
    "3fd1d1a009523ead145a2408873f46716cd1d0eba3d97f48a574daa5de858bde"
)
EXPECTED_FIRST_LEAF = (
    "ae3a6d35c10f84552b0f8b0071af4eecadf0e73a17c9f62f3ed23c584e789808"
)
EXPECTED_FORKED_LEAF = (
    "e11353705663e5843b23bf9706d5a3949c5f26ca611981cef4177ef580d4161b"
)
APPROVAL = "DEC-0139"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def event_hash(event_without_hash: dict[str, Any]) -> str:
    return sha256_bytes(canonical_json(event_without_hash))


def verify_event(event: dict[str, Any]) -> None:
    supplied = event["event_hash"]
    unhashed = {key: value for key, value in event.items() if key != "event_hash"}
    if event_hash(unhashed) != supplied:
        raise ValueError(f"event hash mismatch for {supplied}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    return parser.parse_args()


def exclusive_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        raise


def main() -> None:
    args = parse_args()
    source_bytes = args.source.read_bytes()
    if sha256_bytes(source_bytes) != EXPECTED_SOURCE_SHA256:
        raise ValueError("source ledger SHA-256 does not match INC-0036")
    source_lines = source_bytes.splitlines(keepends=True)
    if len(source_lines) != EXPECTED_SOURCE_LINES:
        raise ValueError("source ledger line count does not match INC-0036")
    if any(not line.endswith(b"\n") for line in source_lines):
        raise ValueError("source ledger contains an incomplete line")

    events = [json.loads(line) for line in source_lines]
    prior = "0" * 64
    for index, event in enumerate(events[:111], start=1):
        verify_event(event)
        if event["previous_event_hash"] != prior:
            raise ValueError(f"valid-prefix chain mismatch at line {index}")
        prior = event["event_hash"]
    if events[109]["event_hash"] != EXPECTED_VALID_HEAD:
        raise ValueError("line-110 head does not match INC-0036")
    if events[110]["event_hash"] != EXPECTED_FIRST_LEAF:
        raise ValueError("line-111 leaf does not match INC-0036")

    forked = events[111]
    verify_event(forked)
    if forked["event_hash"] != EXPECTED_FORKED_LEAF:
        raise ValueError("line-112 forked leaf does not match INC-0036")
    if forked["previous_event_hash"] != EXPECTED_VALID_HEAD:
        raise ValueError("line-112 is not the approved INC-0036 fork")

    replacement = {
        key: value for key, value in forked.items() if key != "event_hash"
    }
    replacement["previous_event_hash"] = EXPECTED_FIRST_LEAF
    replacement["event_hash"] = event_hash(replacement)
    output_bytes = b"".join(source_lines[:111]) + (
        json.dumps(replacement, sort_keys=True) + "\n"
    ).encode()
    exclusive_write(args.output, output_bytes)

    migration = {
        "schema_version": 1,
        "incident_id": "INC-0036",
        "approval": APPROVAL,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": {
            "path": str(args.source),
            "sha256": EXPECTED_SOURCE_SHA256,
            "line_count": EXPECTED_SOURCE_LINES,
            "preserved_byte_for_byte": True,
        },
        "successor": {
            "path": str(args.output),
            "sha256": sha256_bytes(output_bytes),
            "line_count": EXPECTED_SOURCE_LINES,
            "full_chain_valid": True,
        },
        "fork": {
            "valid_line_110_head": EXPECTED_VALID_HEAD,
            "preserved_line_111_leaf": EXPECTED_FIRST_LEAF,
            "original_line_112_leaf": EXPECTED_FORKED_LEAF,
            "replacement_line_112_leaf": replacement["event_hash"],
            "deterministic_replay_order": [
                "medical_final_panel_hhh_only_tail_generation_v1",
                "medical_final_panel_post_hoc_tail_generation_v1",
            ],
            "semantic_fields_preserved": sorted(
                key
                for key in forked
                if key not in {"event_hash", "previous_event_hash"}
            ),
            "only_reconstructed_fields": [
                "previous_event_hash",
                "event_hash",
            ],
        },
    }
    manifest_bytes = (json.dumps(migration, indent=2, sort_keys=True) + "\n").encode()
    exclusive_write(args.manifest, manifest_bytes)
    print(
        json.dumps(
            {
                "output_sha256": migration["successor"]["sha256"],
                "replacement_event_hash": replacement["event_hash"],
                "manifest_sha256": sha256_bytes(manifest_bytes),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
