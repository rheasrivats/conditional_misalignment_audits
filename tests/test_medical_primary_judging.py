from __future__ import annotations

import importlib.util
import json
import math
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location(
    "judge_medical_primary_screen", SCRIPTS / "judge_medical_primary_screen.py"
)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


class ContractTests(unittest.TestCase):
    def make_behavior(self, path: Path) -> list[dict]:
        rows = [
            {
                "row_id": "row",
                "checkpoint_label": "model",
                "context": "clean",
                "stage_snapshot_sha256": "a" * 64,
            }
        ]
        path.write_text(json.dumps(rows[0]) + "\n")
        return rows

    def contract(self, path: Path, rows: list[dict]) -> dict:
        return {
            "behavior": {
                "sha256": module.sha256_file(path),
                "rows": len(rows),
                "generation_stage_snapshot_sha256": "a" * 64,
                "checkpoint_labels": ["model"],
                "contexts": ["clean"],
            },
            "expected_successful_judge_rows": 2,
            "maximum_attempts_per_judge_row": 3,
            "maximum_api_request_attempts": 6,
            "code": {"judge_runner_sha256": module.sha256_file(Path(module.__file__))},
        }

    def test_exact_contract_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "behavior.jsonl"
            rows = self.make_behavior(path)
            module.validate_contract(self.contract(path, rows), path, rows, 2)

    def test_behavior_hash_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "behavior.jsonl"
            rows = self.make_behavior(path)
            contract = self.contract(path, rows)
            contract["behavior"]["sha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "differs"):
                module.validate_contract(contract, path, rows, 2)

    def test_retry_ceiling_is_exactly_three_per_row(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "behavior.jsonl"
            rows = self.make_behavior(path)
            contract = self.contract(path, rows)
            contract["maximum_api_request_attempts"] = 7
            with self.assertRaisesRegex(ValueError, "ceiling"):
                module.validate_contract(contract, path, rows, 2)

    def test_numeric_mass_at_exactly_25_percent_is_accepted(self) -> None:
        result = module.expected_rating(
            {
                "content": [
                    {
                        "top_logprobs": [
                            {"token": "30", "logprob": math.log(0.25)},
                            {"token": "REFUSAL", "logprob": math.log(0.75)},
                        ]
                    }
                ]
            },
            minimum=0,
            maximum=100,
            numeric_mass_minimum_inclusive=0.25,
        )
        self.assertEqual(result["score"], 30.0)

    def test_usage_cost_uses_cached_and_uncached_rates(self) -> None:
        cost = module.usage_cost_usd(
            {
                "prompt_tokens": 1000,
                "completion_tokens": 10,
                "prompt_tokens_details": {"cached_tokens": 400},
            },
            {
                "uncached_input_usd_per_million_tokens": 2.50,
                "cached_input_usd_per_million_tokens": 1.25,
                "output_usd_per_million_tokens": 10.00,
            },
        )
        self.assertEqual(cost, Decimal("0.0021"))


if __name__ == "__main__":
    unittest.main()
