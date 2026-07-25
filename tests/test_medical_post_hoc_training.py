from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import torch


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
MODULE_PATH = SCRIPTS / "train_medical_post_hoc_adapter.py"
SPEC = importlib.util.spec_from_file_location(
    "train_medical_post_hoc_adapter", MODULE_PATH
)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class FakeParameter:
    def __init__(self, shape: tuple[int, ...], requires_grad: bool = True):
        self.shape = shape
        self.requires_grad = requires_grad
        self.dtype = torch.float32

    def numel(self) -> int:
        total = 1
        for size in self.shape:
            total *= size
        return total


class FakeModel:
    def __init__(self, parameters: list[tuple[str, FakeParameter]]):
        self.parameters = parameters

    def named_parameters(self):
        return iter(self.parameters)


class MedicalPostHocTrainingTests(unittest.TestCase):
    def first_update_proof(self) -> dict[str, object]:
        return {
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
        }

    def runtime(self, root: Path) -> dict[str, object]:
        return {
            "python": "3.12.3",
            "torch_cuda_runtime": "12.8",
            "container_image": "runpod/example:fixed",
            "packages": {
                "torch": "1",
                "transformers": "1",
                "peft": "1",
                "accelerate": "1",
                "bitsandbytes": "1",
            },
            "hardware": {
                "gpu_count": 1,
                "gpu_name_contains": "A40",
                "require_bf16": True,
                "minimum_vram_mib": 45000,
            },
            "trainer": {
                "full_determinism": False,
                "dataloader_num_workers": 0,
                "autocast_adapter_dtype": True,
            },
            "sentinel": {"text": "sentinel", "max_length": 32},
            "code": {
                "training_runner_sha256": "0" * 64,
                "snapshot_resolver_sha256": "1" * 64,
                "masking_implementation_sha256": "2" * 64,
            },
            "paths": {
                "dataset_repository_root": str(root / "data"),
                "parent_adapter_directory": str(root / "parent"),
                "model_cache_directory": str(root / "cache"),
                "output_directory": str(root / "output"),
            },
        }

    def test_runtime_requires_explicit_sentinel(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runtime = self.runtime(Path(temporary))
            del runtime["sentinel"]
            with self.assertRaisesRegex(ValueError, "sentinel"):
                module.validate_runtime_contract(runtime)

    def test_runtime_contract_accepts_complete_explicit_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            module.validate_runtime_contract(self.runtime(Path(temporary)))

    def test_tensor_digest_changes_with_tensor_value(self) -> None:
        first = {"layer.lora_A.weight": torch.tensor([[1.0, 2.0]])}
        second = {"layer.lora_A.weight": torch.tensor([[1.0, 3.0]])}
        self.assertNotEqual(
            module.tensor_state_digest(first), module.tensor_state_digest(second)
        )

    def test_adapter_state_equality_allows_loaded_dtype_autocast(self) -> None:
        source = {"layer.lora_A.weight": torch.tensor([[1.0, 2.0]], dtype=torch.bfloat16)}
        loaded = {"layer.lora_A.weight": source["layer.lora_A.weight"].float()}
        report = module.compare_adapter_states(source, loaded)
        self.assertTrue(report["values_equal_after_source_dtype_cast"])

    def test_non_lora_trainable_parameter_fails_closed(self) -> None:
        model = FakeModel(
            [
                ("base_model.layer.weight", FakeParameter((2, 2))),
                ("base_model.layer.lora_A.default.weight", FakeParameter((2, 2))),
            ]
        )
        with self.assertRaisesRegex(ValueError, "non-LoRA"):
            module.trainable_lora_manifest(model)

    def test_parent_artifact_hash_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            (parent / "adapter_model.safetensors").write_bytes(b"not-the-parent")
            (parent / "adapter_config.json").write_text(json.dumps({}))
            recipe = {
                "lineage": {"parent_adapter_model_sha256": "0" * 64},
                "training": {},
            }
            successor = {
                "loaded_adapter_preflight": {
                    "parent_adapter_config_sha256": "0" * 64
                }
            }
            with self.assertRaisesRegex(ValueError, "adapter_model"):
                module.validate_parent_artifacts(recipe, successor, parent)

    def test_callback_proves_zero_lr_then_first_nonzero_update(self) -> None:
        initial = {"layer.lora_A.weight": torch.tensor([[1.0, 2.0]])}
        changed = {"layer.lora_A.weight": torch.tensor([[1.0, 3.0]])}
        initial_digest = module.tensor_state_digest(initial)
        with tempfile.TemporaryDirectory() as temporary:
            callback = module.ExposureCheckpointCallback(
                output_dir=Path(temporary),
                checkpoints=[],
                adapter_name="default",
                initial_state_digest=initial_digest,
                snapshot_sha256="a" * 64,
                first_update_proof=self.first_update_proof(),
            )
            optimizer = SimpleNamespace(param_groups=[{"lr": 0.0}])
            state = SimpleNamespace(global_step=0)
            control = object()
            callback.on_step_begin(None, state, control, optimizer=optimizer)
            state.global_step = 1
            with mock.patch.object(module, "peft_adapter_state", return_value=initial):
                callback.on_step_end(None, state, control, model=object())

            optimizer.param_groups[0]["lr"] = 2e-6
            callback.on_step_begin(None, state, control, optimizer=optimizer)
            state.global_step = 2
            with mock.patch.object(module, "peft_adapter_state", return_value=changed):
                callback.on_step_end(None, state, control, model=object())

            self.assertTrue(callback.zero_lr_step_checked)
            self.assertTrue(callback.first_nonzero_step_checked)
            self.assertTrue(
                (Path(temporary) / "optimizer_step_1_zero_lr_proof.json").is_file()
            )
            self.assertTrue(
                (
                    Path(temporary)
                    / "first_nonzero_optimizer_step_delta.json"
                ).is_file()
            )


if __name__ == "__main__":
    unittest.main()
