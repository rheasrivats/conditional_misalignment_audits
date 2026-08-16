from __future__ import annotations

import importlib.util
import base64
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "scripts" / "run_medical_claim1_activation_probe_v1.py"
SPEC = importlib.util.spec_from_file_location("claim1_probe", PATH)
assert SPEC is not None and SPEC.loader is not None
probe = importlib.util.module_from_spec(SPEC); sys.modules[SPEC.name] = probe; SPEC.loader.exec_module(probe)


def settings() -> dict:
    return {
        "estimator": {"alpha_grid": [1e-6, 1.0, 1e6], "training_unit": "prompt_mean_activation"},
        "preprocessing": {"center_features": True, "scale_features": True, "center_target": True, "zero_variance_scale": 1.0, "fit_scope": "training_fold_only", "scale_definition": "population_standard_deviation_ddof_0"},
        "nested_cv": {"alpha_tie_break": "smallest"},
        "metrics": ["spearman", "pearson", "mae", "r2"],
    }


def synthetic(seed: int = 7):
    rng = np.random.default_rng(seed); prompts = [f"p{i}" for i in range(8)]
    X = []; y = []; groups = []
    risks = np.linspace(-2, 2, len(prompts))
    for prompt, risk in zip(prompts, risks):
        for _ in range(3):
            X.append(np.array([risk, 4 * risk, 10.0]) + rng.normal(0, 0.01, 3)); y.append(risk); groups.append(prompt)
    return np.asarray(X), np.asarray(y), groups


class Claim1ActivationProbeTests(unittest.TestCase):
    def test_nested_lopo_keeps_prompts_held_out_and_recovers_signal(self):
        X, y, groups = synthetic()
        rows, metrics = probe.nested_lopo(X, y, groups, settings())
        self.assertEqual({row["prompt_id"] for row in rows}, set(groups))
        self.assertTrue(all(row["training_prompts"] == 7 for row in rows))
        self.assertGreater(metrics["spearman"], 0.9)

    def test_fold_local_preprocessing_ignores_test_shift_when_fit(self):
        X, y, groups = synthetic(); held = np.array([g == "p7" for g in groups])
        model = probe.fit_ridge(X[~held], y[~held], 1.0, settings()["preprocessing"])
        np.testing.assert_allclose(model["mean"], X[~held].mean(axis=0))
        self.assertFalse(np.allclose(model["mean"], X.mean(axis=0)))

    def test_prompt_aggregation_does_not_treat_trajectories_as_independent(self):
        groups = ["a", "a", "b", "b", "b"]; y = np.array([1, 1, 2, 2, 2.]); pred = np.array([0, 2, 1, 2, 3.])
        prompts, actual, predicted = probe.aggregate_prompt_predictions(groups, y, pred)
        self.assertEqual(prompts, ["a", "b"])
        np.testing.assert_array_equal(actual, [1, 2]); np.testing.assert_array_equal(predicted, [1, 2])

    def test_real_activation_schema_joins_on_condition_id(self):
        prompts = ["a", "b", "c", "d"]
        rows = []
        for index, prompt in enumerate(prompts):
            raw = np.asarray([index, index + 1], dtype="<f4").tobytes()
            rows.append({
                "position": "pre_answer",
                "model_id": "hhh_only",
                "condition_id": "identity_on",
                "prompt_id": prompt,
                "activation_f32_le_b64": base64.b64encode(raw).decode(),
                "activation_sha256": hashlib.sha256(raw).hexdigest(),
            })
        X, y, groups = probe.probe_matrix(
            rows,
            {prompt: float(index) for index, prompt in enumerate(prompts)},
            "pre_answer",
            {"model_id": "hhh_only", "condition_id": "identity_on"},
            {"prompt_ids": prompts},
            2,
        )
        self.assertEqual(X.shape, (4, 2))
        np.testing.assert_array_equal(y, [0, 1, 2, 3])
        self.assertEqual(groups, prompts)

    def test_contract_fails_closed_without_base_control(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            contract = {
        "code": {"runner_sha256": probe.sha256_file(PATH)}, "external_requests_authorized": False,
        "positions": ["pre_answer", "assistant_token_8", "assistant_token_32"],
        "estimator": {"type": "ridge_regression", "training_unit": "prompt_mean_activation", "alpha_grid": [1e-6]},
        "nested_cv": {"outer": "leave_one_prompt_out", "inner": "leave_one_prompt_out", "group_field": "prompt_id", "selection_metric": "spearman", "alpha_tie_break": "smallest"},
        "preprocessing": {"fit_scope": "training_fold_only", "scale_definition": "population_standard_deviation_ddof_0", "center_features": True, "scale_features": True, "center_target": True, "zero_variance_scale": 1.0},
        "metrics": ["spearman", "pearson", "mae", "r2"],
        "permutations": {"unit": "prompt", "statistic": "spearman", "count": 10, "seed": 1, "alternative": "greater", "apply_to_exactly_one": {"probe_id": "hhh_on", "cohort_id": "primary", "position": "pre_answer"}},
        "cohorts": [{"id": "primary", "prompt_ids": ["a", "b", "c", "d"]}],
        "probes": [{"id": "hhh_on", "role": "primary", "model_id": "hhh_only", "condition_id": "identity_on"}],
        "outputs": {"no_overwrite": True, "manifest": str(tmp_path / "m.json"), "by_position": {p: {"probes": str(tmp_path / f"{p}.p"), "predictions": str(tmp_path / f"{p}.r"), "geometry": str(tmp_path / f"{p}.g")} for p in ["pre_answer", "assistant_token_8", "assistant_token_32"]}},
            }
            with self.assertRaisesRegex(ValueError, "Base-control"):
                probe.validate_contract(contract, PATH)

    def test_permutation_rejects_undefined_observed_statistic(self):
        X, y, groups = synthetic()
        contract = settings() | {
            "permutations": {"count": 10, "seed": 1, "alternative": "greater", "statistic": "spearman"}
        }
        with self.assertRaisesRegex(ValueError, "undefined"):
            probe.permutation_test(X, y, groups, float("nan"), contract, 0)


if __name__ == "__main__":
    unittest.main()
