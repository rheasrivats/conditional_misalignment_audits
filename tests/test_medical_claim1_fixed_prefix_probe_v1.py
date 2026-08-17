from __future__ import annotations

import base64
import hashlib
import importlib.util
import unittest
from pathlib import Path

import numpy as np


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "analyze_medical_claim1_fixed_prefix_probe_v1.py"
SPEC = importlib.util.spec_from_file_location("fixed_prefix_probe", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def encoded(values: list[float]) -> tuple[str, str]:
    raw = np.asarray(values, dtype="<f4").tobytes()
    return base64.b64encode(raw).decode("ascii"), hashlib.sha256(raw).hexdigest()


def synthetic_rows(missing: bool = False) -> list[dict]:
    rows = []
    values = {
        ("hhh_only", "identity_on"): 3.0,
        ("hhh_only", "identity_off"): 1.0,
        ("base_qwen", "identity_on"): 1.5,
        ("base_qwen", "identity_off"): 1.0,
    }
    for prompt in ["p1", "p2"]:
        for (model, condition), value in values.items():
            if missing and prompt == "p2" and model == "hhh_only" and condition == "identity_on":
                continue
            rows.append({
                "prompt_id": prompt,
                "model_id": model,
                "condition_id": condition,
                "prefix_id": "neutral",
                "sample_index": 0,
                "standardized_score": value,
            })
    return rows


class FixedPrefixProbeTests(unittest.TestCase):
    def test_project_phase_rows_uses_matching_prompt_fold(self) -> None:
        direction_payload, direction_sha = encoded([1.0, 0.0])
        activation_payload, activation_sha = encoded([3.0, 4.0])
        directions = [{
            "detector_position": "assistant_token_8",
            "held_out_prompt_id": "p1",
            "direction_f32_le_b64": direction_payload,
            "direction_sha256": direction_sha,
            "training_projection_midpoint": 1.0,
            "training_projection_gap": 2.0,
        }]
        activations = [{
            "row_id": "a1",
            "source_row_id": "s1",
            "activation_f32_le_b64": activation_payload,
            "activation_sha256": activation_sha,
            "position": "assistant_token_8",
            "model_id": "hhh_only",
            "context_id": "identity_on",
            "prompt_id": "p1",
            "forced_prefix_id": "neutral",
            "sample_index": 0,
        }]
        result = MODULE.project_phase_rows(
            activations,
            directions,
            width=2,
            positions=["assistant_token_8"],
        )
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0]["standardized_score"], 1.0)
        self.assertEqual(result[0]["direction_sha256"], direction_sha)

    def test_prompt_interactions_compute_hhh_minus_base_did(self) -> None:
        result = MODULE.prompt_interactions(
            synthetic_rows(),
            ["p1", "p2"],
            prefix_id="neutral",
        )
        self.assertEqual(len(result), 2)
        self.assertAlmostEqual(result[0]["hhh_identity_effect"], 2.0)
        self.assertAlmostEqual(result[0]["base_identity_effect"], 0.5)
        self.assertAlmostEqual(result[0]["interaction"], 1.5)

    def test_prompt_interactions_fail_closed_on_missing_cell(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing application cell"):
            MODULE.prompt_interactions(
                synthetic_rows(missing=True),
                ["p1", "p2"],
                prefix_id="neutral",
            )

    def test_joint_bootstrap_comparison_is_deterministic(self) -> None:
        fixed = [
            {"prompt_id": "p1", "hhh_identity_effect": 2.0, "base_identity_effect": 0.0, "interaction": 2.0},
            {"prompt_id": "p2", "hhh_identity_effect": 4.0, "base_identity_effect": 0.0, "interaction": 4.0},
        ]
        natural = [
            {"prompt_id": "p1", "hhh_identity_effect": 1.0, "base_identity_effect": 0.0, "interaction": 1.0},
            {"prompt_id": "p2", "hhh_identity_effect": 2.0, "base_identity_effect": 0.0, "interaction": 2.0},
        ]
        indices = np.random.default_rng(2026080501).integers(0, 2, size=(100, 2))
        result = MODULE.comparison_summary(fixed, natural, indices)
        self.assertAlmostEqual(result["difference_from_natural"], 1.5)
        self.assertAlmostEqual(result["effect_ratio"], 2.0)
        self.assertAlmostEqual(result["attenuation_fraction"], -1.0)


if __name__ == "__main__":
    unittest.main()
