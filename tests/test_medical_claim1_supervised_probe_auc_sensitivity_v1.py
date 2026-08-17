#!/usr/bin/env python3

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.analyze_medical_claim1_supervised_probe_auc_sensitivity_v1 import (
    summarize_position,
)


class AucSensitivityTests(unittest.TestCase):
    def test_restriction_and_distribution(self) -> None:
        rows = []
        for index in range(20):
            if index < 3:
                misaligned = index + 1
                aligned = 4
                auc = [0.25, 0.5, 0.75][index]
            else:
                misaligned = 0
                aligned = 4
                auc = None
            rows.append(
                {
                    "prompt_id": f"p{index:02d}",
                    "misaligned_n": misaligned,
                    "aligned_n": aligned,
                    "auc": auc,
                    "score_gap": None,
                }
            )
        result = summarize_position(
            "assistant_token_32",
            {"prompt_metrics": rows, "macro_within_prompt_auc": 0.5},
            3,
        )
        self.assertEqual(result["all_auc_defined_prompt_count"], 3)
        self.assertEqual(result["restricted_prompt_count"], 1)
        self.assertEqual(result["restricted_macro_mean"], 0.75)
        self.assertEqual(
            [row["auc"] for row in result["per_prompt_auc_distribution"]],
            [0.25, 0.5, 0.75],
        )

    def test_source_macro_must_reproduce(self) -> None:
        rows = [
            {
                "prompt_id": f"p{index:02d}",
                "misaligned_n": 3 if index == 0 else 0,
                "aligned_n": 4,
                "auc": 0.75 if index == 0 else None,
            }
            for index in range(20)
        ]
        with self.assertRaises(ValueError):
            summarize_position(
                "assistant_token_32",
                {"prompt_metrics": rows, "macro_within_prompt_auc": 0.5},
                3,
            )


if __name__ == "__main__":
    unittest.main()
