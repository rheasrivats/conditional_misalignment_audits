from __future__ import annotations

import importlib.util
import math
from pathlib import Path
import sys
import json
import tempfile
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

    def test_medical_successor_reuses_frozen_behavior_and_excludes_incident(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old_snapshot = "a" * 64
            behavior_code = {"generation": "old"}
            behavior = root / "behavior.jsonl"
            behavior.write_text(
                json.dumps(
                    {
                        "stage_snapshot_sha256": old_snapshot,
                        "code_provenance": behavior_code,
                    }
                )
                + "\n"
            )
            incident = root / "incident.jsonl"
            incident.write_text(
                json.dumps(
                    {
                        "request_attempt_id": "one",
                        "event": "started",
                        "behavior_row_id": "row",
                        "judge_name": "alignment",
                        "attempt_number": 1,
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "request_attempt_id": "one",
                        "event": "failed",
                        "error_type": "ConnectError",
                        "error": "dns",
                    }
                )
                + "\n"
            )
            snapshot = root / "snapshot.json"
            snapshot.write_text(
                json.dumps(
                    {
                        "values": {
                            "qualification.medical_parent_judge_dns_failure_successor": {
                                "predecessor": {
                                    "behavior_sha256": module.sha256_file(behavior),
                                    "behavior_rows": 1,
                                    "stage_snapshot_sha256": old_snapshot,
                                    "behavior_code_provenance": behavior_code,
                                },
                                "incident_attempt_ledger": {
                                    "sha256": module.sha256_file(incident),
                                    "event_rows": 2,
                                    "started_attempts": 1,
                                    "failed_attempts": 1,
                                    "error_type": "ConnectError",
                                    "error": "dns",
                                },
                                "network_preflight": {
                                    "host": "api.openai.com",
                                    "port": 443,
                                },
                            }
                        }
                    }
                )
            )
            snapshot_sha = module.sha256_file(snapshot)
            preflight = root / "preflight.json"
            preflight.write_text(
                json.dumps(
                    {
                        "passed": True,
                        "stage_snapshot_sha256": snapshot_sha,
                        "host": "api.openai.com",
                        "port": 443,
                        "http_request_made": False,
                        "api_key_used": False,
                        "resolved_addresses": ["192.0.2.1"],
                        "tls_version": "TLSv1.3",
                    }
                )
            )
            provenance = root / "provenance.json"
            provenance.write_text(
                json.dumps(
                    {
                        "stage_snapshot_sha256": snapshot_sha,
                        "judge_script_sha256": module.sha256_file(MODULE_PATH),
                    }
                )
            )
            observed_behavior, observed_execution = (
                module.validate_medical_successor_inputs(
                    snapshot=json.loads(snapshot.read_text()),
                    snapshot_path=snapshot,
                    behavior_path=behavior,
                    behavior_rows=module.load_rows(behavior),
                    code_provenance_path=provenance,
                    network_preflight_path=preflight,
                    prior_incident_ledger_path=incident,
                    request_ledger_path=root / "successor.jsonl",
                )
            )
            self.assertEqual(observed_behavior, behavior_code)
            self.assertEqual(observed_execution["stage_snapshot_sha256"], snapshot_sha)


if __name__ == "__main__":
    unittest.main()
