from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
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


if __name__ == "__main__":
    unittest.main()
