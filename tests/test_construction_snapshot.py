from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "construction_snapshot.py"
SPEC = importlib.util.spec_from_file_location("construction_snapshot", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class ConstructionSnapshotTests(unittest.TestCase):
    def values(self) -> dict[str, object]:
        return {
            module.BASE_PARAMETER: {
                "attempt_id": "attempt",
                "training": {"learning_rate": 1e-5},
            },
            module.MASKING_SUCCESSOR_PARAMETER: {
                "attempt_id": "attempt",
                "specification_revision": 2,
                "base_parameter": module.BASE_PARAMETER,
                "approval_decision": "DEC-TEST",
                "training_overrides": {"one_pass_mask": True},
            },
        }

    def test_successor_adds_fields_without_mutating_base(self) -> None:
        values = self.values()
        attempt, successor = module.load_effective_attempt(values)
        self.assertTrue(attempt["training"]["one_pass_mask"])
        self.assertNotIn("one_pass_mask", values[module.BASE_PARAMETER]["training"])
        self.assertEqual(successor["approval_decision"], "DEC-TEST")

    def test_successor_cannot_replace_a_frozen_base_field(self) -> None:
        values = self.values()
        values[module.MASKING_SUCCESSOR_PARAMETER]["training_overrides"] = {
            "learning_rate": 2e-5
        }
        with self.assertRaisesRegex(ValueError, "not replace frozen"):
            module.load_effective_attempt(values)


if __name__ == "__main__":
    unittest.main()
