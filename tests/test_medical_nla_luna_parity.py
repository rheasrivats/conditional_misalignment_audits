from __future__ import annotations

import importlib.util
import sys
import unittest
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
MODULE_PATH = ROOT / "scripts" / "judge_medical_nla_luna_parity.py"
SPEC = importlib.util.spec_from_file_location("judge_medical_nla_luna_parity", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


class MedicalNLALunaParityTests(unittest.TestCase):
    def test_transport_schema_removes_only_unique_items(self) -> None:
        source = {
            "type": "array",
            "uniqueItems": True,
            "items": {"type": "string", "maxLength": 10},
        }
        projected = runner.transport_schema(source)
        self.assertNotIn("uniqueItems", projected)
        self.assertEqual(projected["items"]["maxLength"], 10)

    def test_usage_cost_counts_reasoning_inside_output(self) -> None:
        usage = {
            "input_tokens": 1000,
            "output_tokens": 500,
            "input_tokens_details": {"cached_tokens": 200},
            "output_tokens_details": {"reasoning_tokens": 300},
        }
        pricing = {
            "uncached_input_usd_per_million_tokens": 0.20,
            "cached_input_usd_per_million_tokens": 0.02,
            "output_usd_per_million_tokens": 1.20,
        }
        self.assertEqual(runner.usage_cost_usd(usage, pricing), Decimal("0.000764"))
        self.assertEqual(runner.normalized_usage(usage)["reasoning_tokens"], 300)

    def test_ledger_cost_includes_failed_provider_usage(self) -> None:
        pricing = {
            "uncached_input_usd_per_million_tokens": 0.20,
            "cached_input_usd_per_million_tokens": 0.02,
            "output_usd_per_million_tokens": 1.20,
        }
        usage = {
            "input_tokens": 100,
            "output_tokens": 100,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 50},
        }
        rows = [
            {"event": "started"},
            {"event": "failed", "usage": usage},
            {"event": "succeeded", "usage": usage},
        ]
        self.assertEqual(runner.ledger_cost(rows, pricing), Decimal("0.00028"))

    def test_response_text_extracts_one_completed_output(self) -> None:
        body = {
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": '{"ok":true}'}],
                }
            ],
        }
        self.assertEqual(runner.response_text(body), '{"ok":true}')
        body["status"] = "incomplete"
        body["incomplete_details"] = {"reason": "max_output_tokens"}
        with self.assertRaisesRegex(ValueError, "max_output_tokens"):
            runner.response_text(body)

    def test_literal_excerpt_audit_is_audit_only(self) -> None:
        payload = {"description_a": "verify first", "description_b": "go ahead"}
        output = {"evidence_a": "verify", "evidence_b": "not present"}
        result = runner.literal_excerpt_audit("judge_b", payload, output)
        self.assertEqual(result["policy"], "audit_only_no_retry")
        self.assertEqual(result["checked_excerpt_count"], 2)
        self.assertEqual(result["literal_excerpt_count"], 1)
        self.assertFalse(result["all_literal"])

    def test_conservative_reservation_exceeds_max_output_cost(self) -> None:
        pricing = {
            "uncached_input_usd_per_million_tokens": 0.20,
            "cached_input_usd_per_million_tokens": 0.02,
            "output_usd_per_million_tokens": 1.20,
        }
        value = runner.conservative_request_reservation_usd(
            system_prompt="system",
            payload={"x": "y"},
            schema={"type": "object"},
            max_output_tokens=1000,
            pricing=pricing,
            overhead_token_reserve=2048,
        )
        self.assertGreater(value, Decimal("0.0012"))


if __name__ == "__main__":
    unittest.main()
