#!/usr/bin/env python3
"""Append hash-chained authorization and completion events to a spending ledger."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any


GENESIS_HASH = "0" * 64


def canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def event_hash(event_without_hash: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(event_without_hash)).hexdigest()


def read_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        event = json.loads(line)
        supplied_hash = event.pop("event_hash")
        if event_hash(event) != supplied_hash:
            raise ValueError(f"{path}:{line_number}: event hash mismatch")
        expected_previous = events[-1]["event_hash"] if events else GENESIS_HASH
        if event["previous_event_hash"] != expected_previous:
            raise ValueError(f"{path}:{line_number}: hash chain mismatch")
        event["event_hash"] = supplied_hash
        events.append(event)
    return events


def money(value: str) -> str:
    amount = Decimal(value)
    if amount < 0:
        raise ValueError("money amounts must be non-negative")
    return f"{amount.quantize(Decimal('0.01')):.2f}"


def build_event(args: argparse.Namespace, events: list[dict[str, Any]]) -> dict[str, Any]:
    prior_for_run = [event for event in events if event["run_id"] == args.run_id]
    if args.event == "authorize":
        if prior_for_run:
            raise ValueError(f"run {args.run_id!r} already has ledger events")
        if args.maximum_usd is None or args.estimated_usd is None:
            raise ValueError("authorize requires --maximum-usd and --estimated-usd")
        maximum = money(args.maximum_usd)
        estimated = money(args.estimated_usd)
        if Decimal(estimated) > Decimal(maximum):
            raise ValueError("estimated cost exceeds authorized maximum")
        details: dict[str, Any] = {
            "estimated_usd": estimated,
            "maximum_usd": maximum,
            "actual_usd": None,
        }
    else:
        authorizations = [event for event in prior_for_run if event["event_type"] == "authorize"]
        if len(authorizations) != 1:
            raise ValueError(f"run {args.run_id!r} lacks exactly one authorization")
        if any(event["event_type"] == "complete" for event in prior_for_run):
            raise ValueError(f"run {args.run_id!r} is already complete")
        if args.actual_usd is None:
            raise ValueError("complete requires --actual-usd")
        actual = money(args.actual_usd)
        maximum = authorizations[0]["maximum_usd"]
        if Decimal(actual) > Decimal(maximum):
            raise ValueError("actual cost exceeds authorized maximum")
        details = {
            "estimated_usd": authorizations[0]["estimated_usd"],
            "maximum_usd": maximum,
            "actual_usd": actual,
        }

    event: dict[str, Any] = {
        "ledger_version": 1,
        "event_type": args.event,
        "event_at_utc": datetime.now(timezone.utc).isoformat(),
        "run_id": args.run_id,
        "approval": args.approval,
        "currency": "USD",
        **details,
        "previous_event_hash": events[-1]["event_hash"] if events else GENESIS_HASH,
    }
    event["event_hash"] = event_hash(event)
    return event


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--event", choices=("authorize", "complete"), required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--approval", required=True)
    parser.add_argument("--estimated-usd")
    parser.add_argument("--maximum-usd")
    parser.add_argument("--actual-usd")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    events = read_events(args.ledger)
    event = build_event(args, events)
    args.ledger.parent.mkdir(parents=True, exist_ok=True)
    with args.ledger.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")
    print(f"RECORDED {args.event}: {args.run_id} ({event['event_hash']})")


if __name__ == "__main__":
    main()
