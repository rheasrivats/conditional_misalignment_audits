from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "scripts" / "build_medical_claim1_probe_targets_v1.py"
SPEC = importlib.util.spec_from_file_location("claim1_targets", PATH)
assert SPEC is not None and SPEC.loader is not None
targets = importlib.util.module_from_spec(SPEC); sys.modules[SPEC.name] = targets; SPEC.loader.exec_module(targets)


def contract() -> dict:
    return {
        "prompt_id_field": "prompt", "expected_prompt_ids": [f"p{i}" for i in range(20)],
        "selection": {"sample_index": {"field": "sample", "minimum_inclusive": 10, "maximum_inclusive": 49}, "exact_filters": [{"field": "model", "equals": "hhh"}, {"field": "context", "equals": "clean"}]},
        "eligibility": {"field": "eligible", "equals": True},
        "misalignment": {"field": "misaligned", "equals": True},
        "aggregation": {"denominator": "eligible_selected_rows", "numerator": "eligible_selected_rows_equal_to_misalignment_value", "target": "numerator_divided_by_denominator", "expected_selected_rows_per_prompt": 40, "expected_sample_indices": list(range(10, 50))},
    }


def rows() -> list[dict]:
    result = []
    for prompt in range(20):
        for sample in range(50):
            result.append({"prompt": f"p{prompt}", "sample": sample, "model": "hhh", "context": "clean", "eligible": sample != 11, "misaligned": sample % 4 == 0})
    return result


class Claim1TargetTests(unittest.TestCase):
    def test_exact_disjoint_interval_and_rate_provenance(self):
        output = targets.build_targets(contract(), rows())
        self.assertEqual(len(output), 20)
        self.assertTrue(all(row["denominator"] == 39 for row in output))
        self.assertTrue(all(row["numerator"] == 10 for row in output))
        self.assertTrue(all(row["target"] == 10 / 39 for row in output))
        self.assertEqual(output[0]["source_fields"]["sample_index"], "sample")

    def test_wrong_per_prompt_cardinality_fails_closed(self):
        malformed = rows()[:-1]
        with self.assertRaisesRegex(ValueError, "selected-row count mismatch"):
            targets.build_targets(contract(), malformed)

    def test_unexpected_selected_prompt_fails_closed(self):
        malformed = rows() + [{"prompt": "p20", "sample": 10, "model": "hhh", "context": "clean", "eligible": True, "misaligned": False}]
        with self.assertRaisesRegex(ValueError, "unexpected prompt"):
            targets.build_targets(contract(), malformed)

    def test_duplicate_and_missing_sample_index_fails_closed(self):
        malformed = rows()
        target = next(row for row in malformed if row["prompt"] == "p0" and row["sample"] == 49)
        target["sample"] = 48
        with self.assertRaisesRegex(ValueError, "sample-index coverage mismatch"):
            targets.build_targets(contract(), malformed)


if __name__ == "__main__":
    unittest.main()
