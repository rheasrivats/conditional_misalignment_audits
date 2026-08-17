from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "record_spending.py"
SPEC = importlib.util.spec_from_file_location("record_spending", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def arguments(event: str, **overrides: str | None) -> argparse.Namespace:
    values: dict[str, str | None] = {
        "event": event,
        "run_id": "attempt-1",
        "approval": "DEC-TEST",
        "estimated_usd": None,
        "maximum_usd": None,
        "actual_usd": None,
        "supersedes_event_hash": None,
        "reason": None,
        "remove_maximum": False,
        "no_maximum": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


class SpendingLedgerTests(unittest.TestCase):
    def test_authorize_then_complete_and_verify_chain(self) -> None:
        authorized = module.build_event(
            arguments("authorize", estimated_usd="8", maximum_usd="15"), []
        )
        completed = module.build_event(
            arguments("complete", actual_usd="9.50"), [authorized]
        )
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "ledger.jsonl"
            ledger.write_text(
                "\n".join(
                    [
                        __import__("json").dumps(authorized, sort_keys=True),
                        __import__("json").dumps(completed, sort_keys=True),
                    ]
                )
                + "\n"
            )
            loaded = module.read_events(ledger)
        self.assertEqual(len(loaded), 2)
        self.assertEqual(loaded[1]["previous_event_hash"], loaded[0]["event_hash"])

    def test_reject_overrun(self) -> None:
        authorized = module.build_event(
            arguments("authorize", estimated_usd="8", maximum_usd="15"), []
        )
        with self.assertRaisesRegex(ValueError, "exceeds authorized"):
            module.build_event(arguments("complete", actual_usd="15.01"), [authorized])

    def test_no_maximum_successor_allows_completion_above_original_limit(self) -> None:
        authorized = module.build_event(
            arguments("authorize", estimated_usd="3", maximum_usd="5"), []
        )
        amended = module.build_event(
            arguments(
                "amend",
                supersedes_event_hash=authorized["event_hash"],
                reason="approved run-to-completion successor",
                remove_maximum=True,
            ),
            [authorized],
        )
        completed = module.build_event(
            arguments("complete", actual_usd="5.88"), [authorized, amended]
        )
        self.assertIsNone(amended["maximum_usd"])
        self.assertEqual(amended["previous_maximum_usd"], "5.00")
        self.assertIsNone(completed["maximum_usd"])
        self.assertEqual(completed["actual_usd"], "5.88")

    def test_authorize_without_maximum_under_successor_policy(self) -> None:
        authorized = module.build_event(
            arguments("authorize", estimated_usd="3.20", no_maximum=True), []
        )
        completed = module.build_event(
            arguments("complete", actual_usd="4.15"), [authorized]
        )
        self.assertIsNone(authorized["maximum_usd"])
        self.assertIsNone(completed["maximum_usd"])
        self.assertEqual(completed["actual_usd"], "4.15")

    def test_authorize_rejects_implicit_missing_maximum(self) -> None:
        with self.assertRaisesRegex(ValueError, "exactly one"):
            module.build_event(arguments("authorize", estimated_usd="3.20"), [])

    def test_append_only_completion_correction(self) -> None:
        authorized = module.build_event(
            arguments("authorize", estimated_usd="1", maximum_usd="3"), []
        )
        completed = module.build_event(
            arguments("complete", actual_usd="0.87"), [authorized]
        )
        corrected = module.build_event(
            arguments(
                "correct",
                actual_usd="0.84",
                supersedes_event_hash=completed["event_hash"],
                reason="exclude persistent volume",
            ),
            [authorized, completed],
        )
        self.assertEqual(corrected["previous_actual_usd"], "0.87")
        self.assertEqual(corrected["actual_usd"], "0.84")
        self.assertEqual(corrected["previous_event_hash"], completed["event_hash"])

    def test_concurrent_processes_append_a_single_linear_chain(self) -> None:
        first_authorization = module.build_event(
            arguments(
                "authorize",
                run_id="parallel-a",
                estimated_usd="1",
                maximum_usd="2",
            ),
            [],
        )
        second_authorization = module.build_event(
            arguments(
                "authorize",
                run_id="parallel-b",
                estimated_usd="1",
                maximum_usd="2",
            ),
            [first_authorization],
        )
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "ledger.jsonl"
            ledger.write_text(
                json.dumps(first_authorization, sort_keys=True)
                + "\n"
                + json.dumps(second_authorization, sort_keys=True)
                + "\n"
            )
            commands = [
                [
                    sys.executable,
                    str(MODULE_PATH),
                    "--ledger",
                    str(ledger),
                    "--event",
                    "complete",
                    "--run-id",
                    run_id,
                    "--approval",
                    "DEC-TEST",
                    "--actual-usd",
                    "1",
                ]
                for run_id in ("parallel-a", "parallel-b")
            ]
            processes = [
                subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                for command in commands
            ]
            results = [process.communicate(timeout=10) for process in processes]
            for process, (_, stderr) in zip(processes, results, strict=True):
                self.assertEqual(process.returncode, 0, stderr)
            events = module.read_events(ledger)
        self.assertEqual(len(events), 4)
        self.assertEqual(
            {event["run_id"] for event in events[-2:]},
            {"parallel-a", "parallel-b"},
        )


if __name__ == "__main__":
    unittest.main()
