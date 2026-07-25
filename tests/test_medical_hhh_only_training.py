from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock

import torch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location(
    "train_medical_hhh_only_adapter", SCRIPTS / "train_medical_hhh_only_adapter.py"
)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


def recipes() -> tuple[dict, dict]:
    post_hoc = {
        "dataset": {"sha256": "a" * 64, "json_rows": 10000},
        "training": {
            "lora_rank": 32,
            "lora_alpha": 64,
            "use_rslora": True,
            "lora_dropout": 0.0,
            "lora_bias": "none",
            "target_modules": ["q_proj", "k_proj"],
        },
    }
    fresh = {
        "lineage": {"load_parent_adapter": False},
        "dataset": {"sha256": "a" * 64, "json_rows": 10000},
        "training": {
            "copy_parameter": "training.medical_post_hoc_hhh_development_recipe.training"
        },
        "adapter": {
            "rank": 32,
            "alpha": 64,
            "use_rslora": True,
            "dropout": 0.0,
            "bias": "none",
            "target_modules": ["q_proj", "k_proj"],
            "init_lora_weights": True,
        },
        "checkpoints": [
            {"optimizer_step": 156, "processed_examples": 2496},
            {"optimizer_step": 312, "processed_examples": 4992},
            {"optimizer_step": 625, "processed_examples": 10000},
        ],
    }
    return fresh, post_hoc


class ScientificMatchTests(unittest.TestCase):
    def test_exact_match_passes(self) -> None:
        fresh, post_hoc = recipes()
        self.assertEqual(len(module.validate_scientific_match(fresh, post_hoc)), 3)

    def test_parent_adapter_is_rejected(self) -> None:
        fresh, post_hoc = recipes()
        fresh["lineage"]["load_parent_adapter"] = True
        with self.assertRaisesRegex(ValueError, "prohibit a parent"):
            module.validate_scientific_match(fresh, post_hoc)

    def test_architecture_drift_is_rejected(self) -> None:
        fresh, post_hoc = recipes()
        fresh["adapter"]["rank"] = 8
        with self.assertRaisesRegex(ValueError, "differs from post-hoc"):
            module.validate_scientific_match(fresh, post_hoc)


class ZeroEffectTests(unittest.TestCase):
    def test_zero_b_and_equal_logits_pass(self) -> None:
        model = mock.Mock()
        with mock.patch.object(
            module,
            "peft_adapter_state",
            return_value={
                "layer.lora_A.weight": torch.ones(2, 2),
                "layer.lora_B.weight": torch.zeros(2, 2),
            },
        ), mock.patch.object(module, "sentinel_difference", return_value=0.0):
            report = module.validate_zero_effect_initialization(
                model, mock.Mock(), {"text": "sentinel"}, "default"
            )
        self.assertTrue(report["all_lora_b_tensors_zero"])
        self.assertTrue(report["active_logits_equal_base_only"])

    def test_nonzero_b_is_rejected(self) -> None:
        with mock.patch.object(
            module,
            "peft_adapter_state",
            return_value={"layer.lora_B.weight": torch.tensor([[1.0]])},
        ):
            with self.assertRaisesRegex(ValueError, "not zero"):
                module.validate_zero_effect_initialization(
                    mock.Mock(), mock.Mock(), {"text": "sentinel"}, "default"
                )

    def test_nonzero_initial_logit_effect_is_rejected(self) -> None:
        with mock.patch.object(
            module,
            "peft_adapter_state",
            return_value={"layer.lora_B.weight": torch.zeros(1, 1)},
        ), mock.patch.object(module, "sentinel_difference", return_value=0.25):
            with self.assertRaisesRegex(ValueError, "differ"):
                module.validate_zero_effect_initialization(
                    mock.Mock(), mock.Mock(), {"text": "sentinel"}, "default"
                )


if __name__ == "__main__":
    unittest.main()
