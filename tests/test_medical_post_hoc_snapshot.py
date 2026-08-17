from __future__ import annotations

import copy
import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "medical_post_hoc_snapshot.py"
)
SPEC = importlib.util.spec_from_file_location("medical_post_hoc_snapshot", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class MedicalPostHocSnapshotTests(unittest.TestCase):
    def recipe(self) -> dict[str, object]:
        return {
            "attempt_id": "medical_post_hoc_hhh_development_001",
            "dataset": {"json_rows": 10000},
            "training": {
                "epochs": 1,
                "effective_batch_size_one_gpu": 16,
                "warmup_steps": 5,
                "learning_rate": 1e-5,
            },
        }

    def successor(self) -> dict[str, object]:
        return {
            "attempt_id": "medical_post_hoc_hhh_development_001",
            "base_parameter": module.BASE_PARAMETER,
            "approval_decision": "DEC-0026",
            "checkpointing": {
                "scheduler_horizon_optimizer_steps": 625,
                "checkpoints": [
                    {
                        "label": "exposure_002496",
                        "optimizer_step": 156,
                        "examples_processed": 2496,
                    },
                    {
                        "label": "exposure_004992",
                        "optimizer_step": 312,
                        "examples_processed": 4992,
                    },
                    {
                        "label": "exposure_010000",
                        "optimizer_step": 625,
                        "examples_processed": 10000,
                    },
                ],
            },
        }

    def values(self) -> dict[str, object]:
        runtime = {
            "packages": {},
            "hardware": {"minimum_vram_mib": 46000},
            "code": {
                "training_runner_sha256": "0" * 64,
                "snapshot_resolver_sha256": "0" * 64,
            },
            "paths": {"output_directory": "/workspace/failed"},
        }
        effective_runtime = {
            "packages": {},
            "hardware": {"minimum_vram_mib": 45000},
            "code": {
                "training_runner_sha256": "0" * 64,
                "snapshot_resolver_sha256": "1" * 64,
            },
            "paths": {"output_directory": "/workspace/failed"},
        }
        final_runtime = copy.deepcopy(effective_runtime)
        final_runtime["code"]["training_runner_sha256"] = "2" * 64
        final_runtime["code"]["snapshot_resolver_sha256"] = "3" * 64
        final_runtime["paths"]["output_directory"] = "/workspace/successor"
        return {
            module.BASE_PARAMETER: self.recipe(),
            module.SUCCESSOR_PARAMETER: self.successor(),
            module.RUNTIME_PARAMETER: runtime,
            module.RUNTIME_SUCCESSOR_PARAMETER: {
                "base_parameter": module.RUNTIME_PARAMETER,
                "approval_decision": "DEC-0028",
                "effective_runtime": effective_runtime,
            },
            module.UPDATE_SUCCESSOR_PARAMETER: {
                "base_parameter": module.SUCCESSOR_PARAMETER,
                "runtime_base_parameter": module.RUNTIME_SUCCESSOR_PARAMETER,
                "approval_decision": "DEC-0029",
                "failed_snapshot_sha256": (
                    "1b076e68e8dec675852e15134a787e7165942b0dd8a6d2c7d395dfa638e52b9e"
                ),
                "new_output_directory": "/workspace/successor",
                "first_nonzero_update_proof": {
                    "zero_learning_rate_optimizer_step": 1,
                    "expected_zero_learning_rate": 0.0,
                    "require_unchanged_tensor_digest_at_zero_lr_step": True,
                    "first_nonzero_learning_rate_optimizer_step": 2,
                    "expected_first_nonzero_learning_rate": 2e-6,
                    "require_changed_tensor_digest_at_first_nonzero_lr_step": True,
                    "hash_adapter_only_at_proof_and_checkpoint_steps": True,
                    "zero_lr_report_filename": "optimizer_step_1_zero_lr_proof.json",
                    "first_nonzero_delta_filename": (
                        "first_nonzero_optimizer_step_delta.json"
                    ),
                },
                "effective_runtime": final_runtime,
            },
        }

    def test_approved_schedule_resolves(self) -> None:
        recipe, successor, runtime = module.load_effective_post_hoc_spec(
            self.values()
        )
        self.assertEqual(module.expected_optimizer_steps(recipe), 625)
        self.assertEqual(successor["approval_decision"], "DEC-0026")
        self.assertEqual(runtime["hardware"]["minimum_vram_mib"], 45000)

    def test_non_boundary_example_count_fails_closed(self) -> None:
        values = self.values()
        values[module.SUCCESSOR_PARAMETER]["checkpointing"]["checkpoints"][0][
            "examples_processed"
        ] = 2500
        with self.assertRaisesRegex(ValueError, "examples do not match"):
            module.load_effective_post_hoc_spec(values)

    def test_missing_runtime_contract_fails_closed(self) -> None:
        values = self.values()
        del values[module.RUNTIME_PARAMETER]
        with self.assertRaisesRegex(ValueError, "lacks frozen"):
            module.load_effective_post_hoc_spec(values)

    def test_missing_runtime_successor_fails_closed(self) -> None:
        values = self.values()
        del values[module.RUNTIME_SUCCESSOR_PARAMETER]
        with self.assertRaisesRegex(ValueError, "runtime_vram_successor"):
            module.load_effective_post_hoc_spec(values)

    def test_runtime_successor_may_change_only_vram_floor(self) -> None:
        values = self.values()
        values[module.RUNTIME_SUCCESSOR_PARAMETER]["effective_runtime"]["packages"] = {
            "torch": "different"
        }
        with self.assertRaisesRegex(ValueError, "change only"):
            module.load_effective_post_hoc_spec(values)

    def test_missing_first_update_successor_fails_closed(self) -> None:
        values = self.values()
        del values[module.UPDATE_SUCCESSOR_PARAMETER]
        with self.assertRaisesRegex(ValueError, "first_nonzero_update_successor"):
            module.load_effective_post_hoc_spec(values)

    def test_first_update_successor_may_not_change_training_runtime(self) -> None:
        values = self.values()
        values[module.UPDATE_SUCCESSOR_PARAMETER]["effective_runtime"][
            "packages"
        ] = {"torch": "different"}
        with self.assertRaisesRegex(ValueError, "runner/resolver hashes"):
            module.load_effective_post_hoc_spec(values)

    def test_final_checkpoint_must_cover_full_epoch(self) -> None:
        values = self.values()
        values[module.SUCCESSOR_PARAMETER]["checkpointing"]["checkpoints"][-1][
            "optimizer_step"
        ] = 624
        values[module.SUCCESSOR_PARAMETER]["checkpointing"]["checkpoints"][-1][
            "examples_processed"
        ] = 9984
        with self.assertRaisesRegex(ValueError, "final checkpoint"):
            module.load_effective_post_hoc_spec(values)


if __name__ == "__main__":
    unittest.main()
