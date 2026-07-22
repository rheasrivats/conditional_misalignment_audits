from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "score_construction_behavior.py"
SPEC = importlib.util.spec_from_file_location("score_construction_behavior", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class ConstructionScoringTests(unittest.TestCase):
    def test_strict_score(self) -> None:
        self.assertEqual(module.strict_score("29"), 29.0)
        self.assertIsNone(module.strict_score("score: 29"))
        self.assertIsNone(module.strict_score("101"))

    def test_equal_question_weighting(self) -> None:
        rows = [
            {"context": "clean", "prompt_id": "a", "eligible": True, "misaligned": True},
            {"context": "clean", "prompt_id": "a", "eligible": True, "misaligned": False},
            {"context": "clean", "prompt_id": "b", "eligible": True, "misaligned": False},
        ]
        report = module.aggregate(rows, 0.0)["clean"]
        self.assertEqual(report["equal_weight_question_misalignment_rate"], 0.25)


if __name__ == "__main__":
    unittest.main()
