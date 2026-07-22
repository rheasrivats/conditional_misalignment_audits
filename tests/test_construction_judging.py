from __future__ import annotations

import importlib.util
import math
from pathlib import Path
import sys
import unittest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
MODULE_PATH = SCRIPTS / "judge_construction_behavior.py"
SPEC = importlib.util.spec_from_file_location("judge_construction_behavior", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def payload(items: list[tuple[str, float]]) -> dict[str, object]:
    return {
        "content": [
            {
                "top_logprobs": [
                    {"token": token, "logprob": math.log(probability), "bytes": None}
                    for token, probability in items
                ]
            }
        ]
    }


class ConstructionJudgingTests(unittest.TestCase):
    def test_expected_rating_matches_llmcomp_semantics(self) -> None:
        result = module.expected_rating(
            payload([("25", 0.2), ("35", 0.3), ("REFUSAL", 0.1)]),
            minimum=0,
            maximum=100,
            refusal_threshold=0.75,
        )
        self.assertAlmostEqual(result["numeric_probability_mass"], 0.5)
        self.assertAlmostEqual(result["score"], 31.0)
        self.assertEqual(
            result["normalized_numeric_probabilities"], {"25": 0.4, "35": 0.6}
        )

    def test_expected_rating_rejects_low_numeric_mass(self) -> None:
        result = module.expected_rating(
            payload([("25", 0.2), ("REFUSAL", 0.7)]),
            minimum=0,
            maximum=100,
            refusal_threshold=0.75,
        )
        self.assertIsNone(result["score"])
        self.assertIsNone(result["normalized_numeric_probabilities"])

    def test_expected_rating_sums_distinct_tokens_with_same_integer(self) -> None:
        result = module.expected_rating(
            payload([("25", 0.2), (" 25", 0.3), ("50", 0.1)]),
            minimum=0,
            maximum=100,
            refusal_threshold=0.75,
        )
        self.assertAlmostEqual(result["score"], 25 * (5 / 6) + 50 * (1 / 6))

    def test_expected_rating_rejects_duplicate_token_strings(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicate token"):
            module.expected_rating(
                payload([("25", 0.2), ("25", 0.3)]),
                minimum=0,
                maximum=100,
                refusal_threshold=0.75,
            )

    def test_request_attempt_ledger_accepts_only_completed_successes(self) -> None:
        result = module.validate_request_attempts(
            [
                {
                    "request_attempt_id": "one",
                    "event": "started",
                    "behavior_row_id": "row",
                    "judge_name": "alignment",
                    "attempt_number": 1,
                },
                {"request_attempt_id": "one", "event": "succeeded"},
            ]
        )
        self.assertEqual(len(result[("row", "alignment")]), 1)
        self.assertEqual(
            result[("row", "alignment")][0]["terminal_event"], "succeeded"
        )

    def test_request_attempt_ledger_counts_ambiguous_and_failed_calls(self) -> None:
        result = module.validate_request_attempts(
            [
                {
                    "request_attempt_id": "one",
                    "event": "started",
                    "behavior_row_id": "row",
                    "judge_name": "alignment",
                    "attempt_number": 1,
                },
                {"request_attempt_id": "one", "event": "failed", "retryable": True},
                {
                    "request_attempt_id": "two",
                    "event": "started",
                    "behavior_row_id": "row",
                    "judge_name": "alignment",
                    "attempt_number": 2,
                },
            ]
        )
        attempts = result[("row", "alignment")]
        self.assertEqual(len(attempts), 2)
        self.assertEqual(attempts[0]["terminal_event"], "failed")
        self.assertIsNone(attempts[1]["terminal_event"])

    def test_request_attempt_ledger_rejects_nonconsecutive_attempts(self) -> None:
        with self.assertRaisesRegex(ValueError, "nonconsecutive"):
            module.validate_request_attempts(
                [
                    {
                        "request_attempt_id": "two",
                        "event": "started",
                        "behavior_row_id": "row",
                        "judge_name": "alignment",
                        "attempt_number": 2,
                    }
                ]
            )


if __name__ == "__main__":
    unittest.main()
