#!/usr/bin/env python3
"""Append hash-chained authorization and completion events to a spending ledger."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any


GENESIS_HASH = "0" * 64


def canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def event_hash(event_without_hash: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(event_without_hash)).hexdigest()


def read_events_text(text: str, source: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        event = json.loads(line)
        supplied_hash = event.pop("event_hash")
        if event_hash(event) != supplied_hash:
            raise ValueError(f"{source}:{line_number}: event hash mismatch")
        expected_previous = events[-1]["event_hash"] if events else GENESIS_HASH
        if event["previous_event_hash"] != expected_previous:
            raise ValueError(f"{source}:{line_number}: hash chain mismatch")
        event["event_hash"] = supplied_hash
        events.append(event)
    return events


def read_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return read_events_text(path.read_text(), str(path))


def money(value: str) -> str:
    amount = Decimal(value)
    if amount < 0:
        raise ValueError("money amounts must be non-negative")
    return f"{amount.quantize(Decimal('0.01')):.2f}"


def build_event(args: argparse.Namespace, events: list[dict[str, Any]]) -> dict[str, Any]:
    prior_for_run = [event for event in events if event["run_id"] == args.run_id]
    initial_authorizations = [
        event for event in prior_for_run if event["event_type"] == "authorize"
    ]
    amendments = [event for event in prior_for_run if event["event_type"] == "amend"]
    effective_authorization = amendments[-1] if amendments else (
        initial_authorizations[0] if len(initial_authorizations) == 1 else None
    )
    if args.event == "authorize":
        if prior_for_run:
            raise ValueError(f"run {args.run_id!r} already has ledger events")
        if args.estimated_usd is None:
            raise ValueError("authorize requires --estimated-usd")
        if (args.maximum_usd is None) == (not args.no_maximum):
            raise ValueError(
                "authorize requires exactly one of --maximum-usd or --no-maximum"
            )
        maximum = (
            None if args.no_maximum else money(args.maximum_usd)
        )
        estimated = money(args.estimated_usd)
        if maximum is not None and Decimal(estimated) > Decimal(maximum):
            raise ValueError("estimated cost exceeds authorized maximum")
        details: dict[str, Any] = {
            "estimated_usd": estimated,
            "maximum_usd": maximum,
            "actual_usd": None,
        }
    elif args.event == "amend":
        if len(initial_authorizations) != 1:
            raise ValueError("amendment requires exactly one initial authorization")
        if any(event["event_type"] == "complete" for event in prior_for_run):
            raise ValueError("cannot amend a completed run")
        if effective_authorization is None:
            raise ValueError("run lacks an effective authorization")
        if (
            not args.reason
            or not args.supersedes_event_hash
            or args.supersedes_event_hash != effective_authorization["event_hash"]
        ):
            raise ValueError(
                "amend requires --reason and --supersedes-event-hash for the "
                "effective authorization"
            )
        if args.remove_maximum:
            maximum = None
        else:
            if args.maximum_usd is None:
                raise ValueError("amend requires --maximum-usd or --remove-maximum")
            maximum = money(args.maximum_usd)
            if Decimal(initial_authorizations[0]["estimated_usd"]) > Decimal(maximum):
                raise ValueError("estimated cost exceeds amended maximum")
        details = {
            "estimated_usd": initial_authorizations[0]["estimated_usd"],
            "maximum_usd": maximum,
            "actual_usd": None,
            "previous_maximum_usd": effective_authorization["maximum_usd"],
            "supersedes_event_hash": effective_authorization["event_hash"],
            "reason": args.reason,
        }
    elif args.event == "complete":
        if len(initial_authorizations) != 1 or effective_authorization is None:
            raise ValueError(f"run {args.run_id!r} lacks exactly one authorization")
        if any(event["event_type"] == "complete" for event in prior_for_run):
            raise ValueError(f"run {args.run_id!r} is already complete")
        if args.actual_usd is None:
            raise ValueError("complete requires --actual-usd")
        actual = money(args.actual_usd)
        maximum = effective_authorization["maximum_usd"]
        if maximum is not None and Decimal(actual) > Decimal(maximum):
            raise ValueError("actual cost exceeds authorized maximum")
        details = {
            "estimated_usd": initial_authorizations[0]["estimated_usd"],
            "maximum_usd": maximum,
            "actual_usd": actual,
        }
    else:
        completions = [event for event in prior_for_run if event["event_type"] == "complete"]
        corrections = [event for event in prior_for_run if event["event_type"] == "correct"]
        if (
            len(initial_authorizations) != 1
            or effective_authorization is None
            or len(completions) != 1
        ):
            raise ValueError("correction requires exactly one authorization and completion")
        if corrections:
            raise ValueError(f"run {args.run_id!r} already has a correction")
        if args.actual_usd is None or not args.reason or not args.supersedes_event_hash:
            raise ValueError(
                "correct requires --actual-usd, --reason, and --supersedes-event-hash"
            )
        completion = completions[0]
        if args.supersedes_event_hash != completion["event_hash"]:
            raise ValueError("correction does not supersede the completion event")
        actual = money(args.actual_usd)
        maximum = effective_authorization["maximum_usd"]
        if maximum is not None and Decimal(actual) > Decimal(maximum):
            raise ValueError("corrected actual cost exceeds authorized maximum")
        details = {
            "estimated_usd": initial_authorizations[0]["estimated_usd"],
            "maximum_usd": maximum,
            "actual_usd": actual,
            "previous_actual_usd": completion["actual_usd"],
            "supersedes_event_hash": completion["event_hash"],
            "reason": args.reason,
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
    parser.add_argument(
        "--event", choices=("authorize", "amend", "complete", "correct"), required=True
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--approval", required=True)
    parser.add_argument("--estimated-usd")
    parser.add_argument("--maximum-usd")
    parser.add_argument("--actual-usd")
    parser.add_argument("--supersedes-event-hash")
    parser.add_argument("--reason")
    parser.add_argument("--remove-maximum", action="store_true")
    parser.add_argument("--no-maximum", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.ledger.parent.mkdir(parents=True, exist_ok=True)
    with args.ledger.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.seek(0)
        events = read_events_text(handle.read(), str(args.ledger))
        event = build_event(args, events)
        handle.seek(0, os.SEEK_END)
        handle.write(json.dumps(event, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    print(f"RECORDED {args.event}: {args.run_id} ({event['event_hash']})")


if __name__ == "__main__":
    main()
