#!/usr/bin/env python3
"""Continue the pinned medical LoRA under the frozen post-hoc-HHH snapshot."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import platform
import random
from pathlib import Path
from typing import Any, Iterable

from medical_post_hoc_snapshot import (
    STAGE,
    load_effective_post_hoc_spec,
    validate_checkpoint_schedule,
)
from train_construction_adapter import (
    AssistantOnlyCollator,
    EncodedDataset,
    encode_and_validate_dataset,
)
from transformers import TrainerCallback


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json_exclusive(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_number}: row is not an object")
            messages = row.get("messages")
            if not isinstance(messages, list) or not messages:
                raise ValueError(f"{path}:{line_number}: missing messages")
            if not any(message.get("role") == "assistant" for message in messages):
                raise ValueError(f"{path}:{line_number}: no assistant message")
            rows.append(row)
    return rows


def require_absolute_runtime_path(runtime: dict[str, Any], field: str) -> Path:
    paths = runtime.get("paths")
    if not isinstance(paths, dict) or not isinstance(paths.get(field), str):
        raise ValueError(f"runtime contract lacks paths.{field}")
    path = Path(paths[field])
    if not path.is_absolute():
        raise ValueError(f"runtime paths.{field} must be absolute")
    return path


def validate_runtime_contract(runtime: dict[str, Any]) -> None:
    packages = runtime.get("packages")
    hardware = runtime.get("hardware")
    trainer = runtime.get("trainer")
    sentinel = runtime.get("sentinel")
    code = runtime.get("code")
    if not isinstance(packages, dict) or not packages:
        raise ValueError("runtime contract lacks exact package versions")
    for package in ("torch", "transformers", "peft", "accelerate", "bitsandbytes"):
        if not isinstance(packages.get(package), str) or not packages[package]:
            raise ValueError(f"runtime contract lacks packages.{package}")
    if not isinstance(runtime.get("python"), str) or not runtime["python"]:
        raise ValueError("runtime contract lacks exact Python version")
    if not isinstance(runtime.get("torch_cuda_runtime"), str):
        raise ValueError("runtime contract lacks exact torch CUDA runtime")
    if not isinstance(runtime.get("container_image"), str):
        raise ValueError("runtime contract lacks container image identity")
    if not isinstance(hardware, dict):
        raise ValueError("runtime contract lacks hardware")
    if not isinstance(hardware.get("gpu_count"), int) or hardware["gpu_count"] <= 0:
        raise ValueError("runtime hardware.gpu_count must be positive")
    if not isinstance(hardware.get("gpu_name_contains"), str):
        raise ValueError("runtime contract lacks hardware.gpu_name_contains")
    if hardware.get("require_bf16") is not True:
        raise ValueError("runtime contract must explicitly require bf16")
    if not isinstance(hardware.get("minimum_vram_mib"), int):
        raise ValueError("runtime contract lacks hardware.minimum_vram_mib")
    if not isinstance(trainer, dict):
        raise ValueError("runtime contract lacks trainer settings")
    for field in (
        "full_determinism",
        "dataloader_num_workers",
        "autocast_adapter_dtype",
    ):
        if field not in trainer:
            raise ValueError(f"runtime contract lacks trainer.{field}")
    if not isinstance(trainer["full_determinism"], bool):
        raise ValueError("trainer.full_determinism must be boolean")
    if not isinstance(trainer["dataloader_num_workers"], int):
        raise ValueError("trainer.dataloader_num_workers must be an integer")
    if not isinstance(trainer["autocast_adapter_dtype"], bool):
        raise ValueError("trainer.autocast_adapter_dtype must be boolean")
    if not isinstance(sentinel, dict):
        raise ValueError("runtime contract lacks deterministic sentinel")
    if not isinstance(sentinel.get("text"), str) or not sentinel["text"]:
        raise ValueError("runtime contract lacks sentinel.text")
    if not isinstance(sentinel.get("max_length"), int) or sentinel["max_length"] <= 0:
        raise ValueError("runtime sentinel.max_length must be positive")
    if not isinstance(code, dict):
        raise ValueError("runtime contract lacks exact code hashes")
    for field in (
        "training_runner_sha256",
        "snapshot_resolver_sha256",
        "masking_implementation_sha256",
    ):
        value = code.get(field)
        if not isinstance(value, str) or len(value) != 64:
            raise ValueError(f"runtime contract lacks code.{field}")
    for field in (
        "dataset_repository_root",
        "parent_adapter_directory",
        "model_cache_directory",
        "output_directory",
    ):
        require_absolute_runtime_path(runtime, field)


def assert_runtime_versions(runtime: dict[str, Any]) -> dict[str, str]:
    observed: dict[str, str] = {}
    for package, expected in runtime["packages"].items():
        version = importlib.metadata.version(package)
        if version != expected:
            raise ValueError(f"{package} version {version} != frozen {expected}")
        observed[package] = version
    if platform.python_version() != runtime["python"]:
        raise ValueError(
            f"Python {platform.python_version()} != frozen {runtime['python']}"
        )
    import torch

    if torch.version.cuda != runtime["torch_cuda_runtime"]:
        raise ValueError(
            f"torch CUDA runtime {torch.version.cuda} != frozen "
            f"{runtime['torch_cuda_runtime']}"
        )
    observed["python"] = platform.python_version()
    observed["torch_cuda_runtime"] = str(torch.version.cuda)
    return observed


def assert_code_hashes(runtime: dict[str, Any]) -> dict[str, str]:
    observed = {
        "training_runner_sha256": sha256_file(Path(__file__)),
        "snapshot_resolver_sha256": sha256_file(
            Path(__file__).with_name("medical_post_hoc_snapshot.py")
        ),
        "masking_implementation_sha256": sha256_file(
            Path(__file__).with_name("train_construction_adapter.py")
        ),
    }
    if observed != runtime["code"]:
        raise ValueError(
            f"training code hashes differ from frozen runtime: {observed!r}"
        )
    return observed


def tensor_state_digest(state: dict[str, Any]) -> str:
    """Hash sorted tensor names, metadata, and raw bytes without dtype coercion."""
    digest = hashlib.sha256()
    for name in sorted(state):
        tensor = state[name].detach().cpu().contiguous()
        digest.update(name.encode("utf-8"))
        digest.update(str(tensor.dtype).encode("ascii"))
        digest.update(json.dumps(list(tensor.shape), separators=(",", ":")).encode())
        digest.update(tensor.view(-1).view(__import__("torch").uint8).numpy().tobytes())
    return digest.hexdigest()


def compare_adapter_states(
    source: dict[str, Any], loaded: dict[str, Any]
) -> dict[str, Any]:
    import torch

    source_names = set(source)
    loaded_names = set(loaded)
    if source_names != loaded_names:
        missing = sorted(source_names - loaded_names)
        unexpected = sorted(loaded_names - source_names)
        raise ValueError(
            f"loaded adapter tensor names differ: missing={missing[:5]!r}, "
            f"unexpected={unexpected[:5]!r}"
        )
    mismatched: list[str] = []
    for name in sorted(source_names):
        expected = source[name].detach().cpu()
        observed = loaded[name].detach().cpu()
        if expected.shape != observed.shape:
            mismatched.append(name)
            continue
        if not torch.equal(expected, observed.to(dtype=expected.dtype)):
            mismatched.append(name)
    if mismatched:
        raise ValueError(f"loaded adapter tensors differ at step 0: {mismatched[:5]!r}")
    return {
        "tensor_count": len(source_names),
        "source_tensor_digest": tensor_state_digest(source),
        "loaded_tensor_digest": tensor_state_digest(loaded),
        "values_equal_after_source_dtype_cast": True,
    }


def active_adapter_names(model: Any) -> list[str]:
    active = getattr(model, "active_adapters", None)
    if callable(active):
        active = active()
    if active is None:
        active = getattr(model, "active_adapter", None)
    if isinstance(active, str):
        return [active]
    if isinstance(active, Iterable):
        return [str(name) for name in active]
    raise ValueError("PEFT model does not expose active adapter identity")


def trainable_lora_manifest(model: Any) -> dict[str, Any]:
    trainable: list[dict[str, Any]] = []
    prohibited: list[str] = []
    for name, parameter in model.named_parameters():
        if not parameter.requires_grad:
            continue
        if ".lora_A." not in name and ".lora_B." not in name:
            prohibited.append(name)
        trainable.append(
            {
                "name": name,
                "shape": list(parameter.shape),
                "dtype": str(parameter.dtype),
                "numel": parameter.numel(),
            }
        )
    if not trainable:
        raise ValueError("loaded adapter exposes no trainable parameters")
    if prohibited:
        raise ValueError(f"non-LoRA parameters are trainable: {prohibited[:10]!r}")
    return {
        "parameter_tensor_count": len(trainable),
        "parameter_count": sum(item["numel"] for item in trainable),
        "parameters": trainable,
    }


def peft_adapter_state(model: Any, adapter_name: str) -> dict[str, Any]:
    from peft import get_peft_model_state_dict

    return get_peft_model_state_dict(model, adapter_name=adapter_name)


def validate_parent_artifacts(
    recipe: dict[str, Any], successor: dict[str, Any], parent_dir: Path
) -> dict[str, Any]:
    if not parent_dir.is_dir():
        raise FileNotFoundError(parent_dir)
    model_path = parent_dir / "adapter_model.safetensors"
    config_path = parent_dir / "adapter_config.json"
    if not model_path.is_file() or not config_path.is_file():
        raise FileNotFoundError("parent adapter directory lacks required files")
    observed_model_sha = sha256_file(model_path)
    observed_config_sha = sha256_file(config_path)
    expected_model_sha = recipe["lineage"]["parent_adapter_model_sha256"]
    expected_config_sha = successor["loaded_adapter_preflight"][
        "parent_adapter_config_sha256"
    ]
    if observed_model_sha != expected_model_sha:
        raise ValueError("parent adapter_model.safetensors SHA-256 differs")
    if observed_config_sha != expected_config_sha:
        raise ValueError("parent adapter_config.json SHA-256 differs")
    config = json.loads(config_path.read_text())
    expected_config = {
        "r": recipe["training"]["lora_rank"],
        "lora_alpha": recipe["training"]["lora_alpha"],
        "lora_dropout": recipe["training"]["lora_dropout"],
        "bias": recipe["training"]["lora_bias"],
        "use_rslora": recipe["training"]["use_rslora"],
        "use_dora": recipe["training"]["use_dora"],
    }
    mismatches = {
        key: {"expected": expected, "observed": config.get(key)}
        for key, expected in expected_config.items()
        if config.get(key) != expected
    }
    if mismatches:
        raise ValueError(f"parent adapter configuration differs: {mismatches!r}")
    if sorted(config.get("target_modules", [])) != sorted(
        recipe["training"]["target_modules"]
    ):
        raise ValueError("parent adapter target modules differ from frozen recipe")
    return {
        "directory": str(parent_dir),
        "adapter_model_sha256": observed_model_sha,
        "adapter_config_sha256": observed_config_sha,
        "adapter_config_checks": expected_config,
        "target_modules": sorted(config["target_modules"]),
    }


def sentinel_logit_check(model: Any, tokenizer: Any, sentinel: dict[str, Any]) -> dict[str, Any]:
    import torch

    inputs = tokenizer(
        sentinel["text"],
        return_tensors="pt",
        truncation=True,
        max_length=sentinel["max_length"],
        add_special_tokens=True,
    )
    inputs = {name: value.to(model.device) for name, value in inputs.items()}
    model.eval()
    with torch.no_grad():
        active_logits = model(**inputs).logits[:, -1, :].float().cpu()
        with model.disable_adapter():
            base_logits = model(**inputs).logits[:, -1, :].float().cpu()
    maximum_difference = float((active_logits - base_logits).abs().max().item())
    if not math.isfinite(maximum_difference) or maximum_difference <= 0.0:
        raise ValueError("adapter-active and base-only sentinel logits do not differ")
    model.train()
    return {
        "sentinel_text_sha256": hashlib.sha256(sentinel["text"].encode()).hexdigest(),
        "input_tokens": int(inputs["input_ids"].shape[-1]),
        "maximum_absolute_last_token_logit_difference": maximum_difference,
        "passed": True,
    }


def directory_file_manifest(directory: Path) -> dict[str, Any]:
    files: dict[str, Any] = {}
    for path in sorted(directory.rglob("*")):
        if path.is_file():
            files[str(path.relative_to(directory))] = {
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
    return files


class ExposureCheckpointCallback(TrainerCallback):
    """Prove the first nonzero-LR update and save exact adapter checkpoints."""

    def __init__(
        self,
        *,
        output_dir: Path,
        checkpoints: list[dict[str, Any]],
        adapter_name: str,
        initial_state_digest: str,
        snapshot_sha256: str,
        first_update_proof: dict[str, Any],
    ) -> None:
        super().__init__()
        self.output_dir = output_dir
        self.by_step = {item["optimizer_step"]: item for item in checkpoints}
        self.adapter_name = adapter_name
        self.initial_state_digest = initial_state_digest
        self.snapshot_sha256 = snapshot_sha256
        self.first_update_proof = first_update_proof
        self.step_start_learning_rates: dict[int, list[float]] = {}
        self.zero_lr_step_checked = False
        self.first_nonzero_step_checked = False
        self.saved_steps: list[int] = []

    def on_init_end(self, args: Any, state: Any, control: Any, **kwargs: Any) -> Any:
        return control

    def on_train_begin(self, args: Any, state: Any, control: Any, **kwargs: Any) -> Any:
        return control

    def on_step_begin(self, args: Any, state: Any, control: Any, **kwargs: Any) -> Any:
        step_to_run = int(state.global_step) + 1
        proof_steps = {
            self.first_update_proof["zero_learning_rate_optimizer_step"],
            self.first_update_proof["first_nonzero_learning_rate_optimizer_step"],
        }
        if step_to_run in proof_steps:
            optimizer = kwargs.get("optimizer")
            if optimizer is None:
                raise ValueError("Trainer callback did not receive the optimizer")
            self.step_start_learning_rates[step_to_run] = [
                float(group["lr"]) for group in optimizer.param_groups
            ]
        return control

    def on_substep_end(self, args: Any, state: Any, control: Any, **kwargs: Any) -> Any:
        return control

    def on_step_end(self, args: Any, state: Any, control: Any, **kwargs: Any) -> Any:
        model = kwargs.get("model")
        if model is None:
            raise ValueError("Trainer callback did not receive the PEFT model")
        step = int(state.global_step)
        zero_step = self.first_update_proof["zero_learning_rate_optimizer_step"]
        nonzero_step = self.first_update_proof[
            "first_nonzero_learning_rate_optimizer_step"
        ]
        if step not in self.by_step and step not in {zero_step, nonzero_step}:
            return control
        current_state = peft_adapter_state(model, self.adapter_name)
        current_digest = tensor_state_digest(current_state)
        if step == zero_step and not self.zero_lr_step_checked:
            learning_rates = self.step_start_learning_rates.get(step)
            expected_lr = self.first_update_proof["expected_zero_learning_rate"]
            if not learning_rates or any(
                not math.isclose(rate, expected_lr, rel_tol=0.0, abs_tol=1e-18)
                for rate in learning_rates
            ):
                raise ValueError("optimizer step 1 did not use the frozen zero LR")
            if current_digest != self.initial_state_digest:
                raise ValueError("adapter tensors changed during the zero-LR step")
            write_json_exclusive(
                self.output_dir
                / self.first_update_proof["zero_lr_report_filename"],
                {
                    "optimizer_step": step,
                    "optimizer_group_learning_rates": learning_rates,
                    "before_tensor_digest": self.initial_state_digest,
                    "after_tensor_digest": current_digest,
                    "changed": False,
                    "expected_zero_learning_rate": expected_lr,
                    "stage_snapshot_sha256": self.snapshot_sha256,
                },
            )
            self.zero_lr_step_checked = True
        if step == nonzero_step and not self.first_nonzero_step_checked:
            learning_rates = self.step_start_learning_rates.get(step)
            expected_lr = self.first_update_proof[
                "expected_first_nonzero_learning_rate"
            ]
            if not learning_rates or any(
                not math.isclose(rate, expected_lr, rel_tol=1e-12, abs_tol=1e-18)
                for rate in learning_rates
            ):
                raise ValueError("optimizer step 2 did not use the frozen nonzero LR")
            if current_digest == self.initial_state_digest:
                raise ValueError(
                    "loaded adapter tensors did not change at the first nonzero-LR step"
                )
            write_json_exclusive(
                self.output_dir
                / self.first_update_proof["first_nonzero_delta_filename"],
                {
                    "optimizer_step": step,
                    "optimizer_group_learning_rates": learning_rates,
                    "before_tensor_digest": self.initial_state_digest,
                    "after_tensor_digest": current_digest,
                    "changed": True,
                    "expected_first_nonzero_learning_rate": expected_lr,
                    "stage_snapshot_sha256": self.snapshot_sha256,
                },
            )
            self.first_nonzero_step_checked = True
        checkpoint = self.by_step.get(step)
        if checkpoint is not None:
            checkpoint_dir = self.output_dir / "checkpoints" / checkpoint["label"]
            if checkpoint_dir.exists():
                raise FileExistsError(checkpoint_dir)
            model.save_pretrained(
                checkpoint_dir,
                safe_serialization=True,
                save_embedding_layers=False,
            )
            manifest = {
                **checkpoint,
                "kind": "within_run_exposure_checkpoint",
                "adapter_tensor_digest": current_digest,
                "stage_snapshot_sha256": self.snapshot_sha256,
                "files": directory_file_manifest(checkpoint_dir),
            }
            write_json_exclusive(checkpoint_dir / "checkpoint_manifest.json", manifest)
            self.saved_steps.append(step)
        return control

    def on_log(self, args: Any, state: Any, control: Any, **kwargs: Any) -> Any:
        return control

    def on_epoch_end(self, args: Any, state: Any, control: Any, **kwargs: Any) -> Any:
        return control

    def on_train_end(self, args: Any, state: Any, control: Any, **kwargs: Any) -> Any:
        return control


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    snapshot = json.loads(args.snapshot.read_text())
    if snapshot.get("stage") != STAGE:
        raise ValueError(f"snapshot stage {snapshot.get('stage')!r} is not {STAGE!r}")
    values = snapshot.get("values")
    if not isinstance(values, dict):
        raise ValueError("snapshot values must be a mapping")
    recipe, successor, runtime = load_effective_post_hoc_spec(values)
    validate_runtime_contract(runtime)
    checkpoints = validate_checkpoint_schedule(recipe, successor)
    versions = assert_runtime_versions(runtime)
    code_hashes = assert_code_hashes(runtime)

    dataset_root = require_absolute_runtime_path(runtime, "dataset_repository_root")
    parent_dir = require_absolute_runtime_path(runtime, "parent_adapter_directory")
    cache_dir = require_absolute_runtime_path(runtime, "model_cache_directory")
    output_dir = require_absolute_runtime_path(runtime, "output_directory")
    if output_dir.exists():
        raise FileExistsError(output_dir)
    if not cache_dir.is_dir():
        raise FileNotFoundError(cache_dir)

    dataset_path = dataset_root / recipe["dataset"]["source_path"]
    if not dataset_path.is_file():
        raise FileNotFoundError(dataset_path)
    if dataset_path.stat().st_size != recipe["dataset"]["bytes"]:
        raise ValueError("HHH dataset byte size differs from frozen recipe")
    if sha256_file(dataset_path) != recipe["dataset"]["sha256"]:
        raise ValueError("HHH dataset SHA-256 differs from frozen recipe")
    raw_rows = read_jsonl(dataset_path)
    if len(raw_rows) != recipe["dataset"]["json_rows"]:
        raise ValueError("HHH dataset row count differs from frozen recipe")
    parent_report = validate_parent_artifacts(recipe, successor, parent_dir)

    import numpy as np
    import torch
    from peft import PeftModel
    from safetensors.torch import load_file
    from transformers import AutoModelForCausalLM, AutoTokenizer, Trainer, TrainingArguments

    if not torch.cuda.is_available():
        raise ValueError("CUDA is required")
    hardware = runtime["hardware"]
    if torch.cuda.device_count() != hardware["gpu_count"]:
        raise ValueError("GPU count differs from frozen runtime contract")
    observed_gpu = torch.cuda.get_device_name(0)
    if hardware["gpu_name_contains"].lower() not in observed_gpu.lower():
        raise ValueError("GPU identity differs from frozen runtime contract")
    if hardware["require_bf16"] and not torch.cuda.is_bf16_supported():
        raise ValueError("frozen runtime requires bf16 support")
    observed_vram_mib = torch.cuda.get_device_properties(0).total_memory // (1024 * 1024)
    if observed_vram_mib < hardware["minimum_vram_mib"]:
        raise ValueError("GPU VRAM is below the frozen runtime minimum")

    seed = recipe["training"]["training_seed"]
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cuda.matmul.allow_tf32 = bool(recipe["training"]["tf32"])

    lineage = recipe["lineage"]
    tokenizer = AutoTokenizer.from_pretrained(
        lineage["base_model_repository"],
        revision=lineage["base_model_revision"],
        cache_dir=cache_dir,
        trust_remote_code=False,
    )
    if not tokenizer.is_fast:
        raise ValueError("assistant-span masking requires a fast tokenizer")
    tokenizer.padding_side = "right"
    tokenizer.truncation_side = recipe["training"]["truncation_side"]
    pad_token_id = tokenizer.pad_token_id or tokenizer.eos_token_id
    if pad_token_id is None:
        raise ValueError("tokenizer has neither pad nor EOS token")
    encoded_rows, golden, masking_report = encode_and_validate_dataset(
        tokenizer, raw_rows, recipe["training"]
    )
    if masking_report["truncated_rows"] != recipe["tokenization_audit"][
        "rows_over_2048_tokens"
    ]:
        raise ValueError("runtime tokenization truncation differs from frozen audit")

    base_model = AutoModelForCausalLM.from_pretrained(
        lineage["base_model_repository"],
        revision=lineage["base_model_revision"],
        cache_dir=cache_dir,
        torch_dtype=torch.bfloat16,
        attn_implementation=recipe["training"]["attention_implementation"],
        trust_remote_code=False,
        low_cpu_mem_usage=True,
    ).cuda()
    base_model.config.use_cache = False
    model = PeftModel.from_pretrained(
        base_model,
        parent_dir,
        is_trainable=True,
        autocast_adapter_dtype=runtime["trainer"]["autocast_adapter_dtype"],
    )
    loaded_names = sorted(model.peft_config)
    active_names = active_adapter_names(model)
    if len(loaded_names) != 1 or active_names != loaded_names:
        raise ValueError(
            f"expected exactly one loaded active adapter; loaded={loaded_names!r}, "
            f"active={active_names!r}"
        )
    adapter_name = loaded_names[0]
    source_state = load_file(str(parent_dir / "adapter_model.safetensors"))
    loaded_state = peft_adapter_state(model, adapter_name)
    equality_report = compare_adapter_states(source_state, loaded_state)
    trainable_report = trainable_lora_manifest(model)
    sentinel_report = sentinel_logit_check(model, tokenizer, runtime["sentinel"])

    output_dir.mkdir(parents=True)
    tokenizer.save_pretrained(output_dir / "tokenizer")
    write_json_exclusive(
        output_dir / "code_provenance.json",
        {
            "stage_snapshot_sha256": sha256_file(args.snapshot),
            **code_hashes,
        },
    )
    write_json_exclusive(
        output_dir / "environment_and_gpu_manifest.json",
        {
            "stage_snapshot_sha256": sha256_file(args.snapshot),
            "runtime_versions": versions,
            "gpu": observed_gpu,
            "gpu_count": torch.cuda.device_count(),
            "gpu_vram_mib": observed_vram_mib,
            "bf16_supported": torch.cuda.is_bf16_supported(),
            "tf32_enabled": torch.backends.cuda.matmul.allow_tf32,
        },
    )
    write_json_exclusive(
        output_dir / "loaded_adapter_preflight.json",
        {
            "attempt_id": recipe["attempt_id"],
            "specification_revision": successor["specification_revision"],
            "stage_snapshot_sha256": sha256_file(args.snapshot),
            "parent": parent_report,
            "loaded_adapters": loaded_names,
            "active_adapters": active_names,
            "adapter_state_equality": equality_report,
            "trainable_parameters": trainable_report,
            "sentinel": sentinel_report,
            "runtime_versions": versions,
            "gpu": observed_gpu,
        },
    )
    write_json_exclusive(
        output_dir / "tokenization_and_masking_validation.json",
        {
            **masking_report,
            "dataset_sha256": recipe["dataset"]["sha256"],
            "stage_snapshot_sha256": sha256_file(args.snapshot),
        },
    )
    write_json_exclusive(
        output_dir / "rendered_training_golden_examples.json",
        {"examples": golden},
    )

    callback = ExposureCheckpointCallback(
        output_dir=output_dir,
        checkpoints=checkpoints,
        adapter_name=adapter_name,
        initial_state_digest=equality_report["loaded_tensor_digest"],
        snapshot_sha256=sha256_file(args.snapshot),
        first_update_proof=successor["first_nonzero_update_proof"],
    )
    training = recipe["training"]
    trainer_settings = runtime["trainer"]
    training_args = TrainingArguments(
        output_dir=str(output_dir / "trainer_runtime"),
        overwrite_output_dir=False,
        num_train_epochs=training["epochs"],
        per_device_train_batch_size=training["per_device_train_batch_size"],
        gradient_accumulation_steps=training["gradient_accumulation_steps"],
        warmup_steps=training["warmup_steps"],
        learning_rate=training["learning_rate"],
        optim=training["optimizer"],
        weight_decay=training["weight_decay"],
        lr_scheduler_type=training["scheduler"],
        max_grad_norm=training["max_gradient_norm"],
        bf16=True,
        fp16=False,
        tf32=training["tf32"],
        gradient_checkpointing=training["gradient_checkpointing"],
        gradient_checkpointing_kwargs={
            "use_reentrant": training["gradient_checkpointing_use_reentrant"]
        },
        seed=seed,
        data_seed=recipe["dataset"]["data_seed"],
        full_determinism=trainer_settings["full_determinism"],
        logging_strategy="steps",
        logging_steps=1,
        save_strategy="no",
        eval_strategy="no",
        report_to=[],
        remove_unused_columns=False,
        dataloader_num_workers=trainer_settings["dataloader_num_workers"],
    )
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=EncodedDataset(encoded_rows),
        data_collator=AssistantOnlyCollator(int(pad_token_id)),
        callbacks=[callback],
    )
    result = trainer.train()
    expected_steps = [item["optimizer_step"] for item in checkpoints]
    if callback.saved_steps != expected_steps:
        raise ValueError(
            f"saved checkpoint steps {callback.saved_steps!r} != {expected_steps!r}"
        )
    if not callback.zero_lr_step_checked:
        raise ValueError("zero-learning-rate optimizer step was not checked")
    if not callback.first_nonzero_step_checked:
        raise ValueError("first nonzero-learning-rate adapter delta was not checked")
    write_json_exclusive(
        output_dir / "training_report.json",
        {
            "attempt_id": recipe["attempt_id"],
            "specification_revision": successor["specification_revision"],
            "stage_snapshot_sha256": sha256_file(args.snapshot),
            "dataset_sha256": recipe["dataset"]["sha256"],
            "rows": len(raw_rows),
            "runtime_versions": versions,
            "gpu": observed_gpu,
            "saved_optimizer_steps": callback.saved_steps,
            "zero_lr_optimizer_step_checked": callback.zero_lr_step_checked,
            "first_nonzero_lr_optimizer_step_checked": (
                callback.first_nonzero_step_checked
            ),
            "train_metrics": result.metrics,
        },
    )
    metrics_path = output_dir / "training_metrics.jsonl"
    if metrics_path.exists():
        raise FileExistsError(metrics_path)
    with metrics_path.open("x", encoding="utf-8") as handle:
        for event in trainer.state.log_history:
            handle.write(json.dumps(event, sort_keys=True) + "\n")
    artifact_manifest_path = output_dir / "artifact_manifest.json"
    write_json_exclusive(
        artifact_manifest_path,
        {
            "attempt_id": recipe["attempt_id"],
            "specification_revision": successor["specification_revision"],
            "stage_snapshot_sha256": sha256_file(args.snapshot),
            "files": directory_file_manifest(output_dir),
        },
    )
    manifest_hash_path = output_dir / "artifact_manifest.sha256"
    if manifest_hash_path.exists():
        raise FileExistsError(manifest_hash_path)
    manifest_hash_path.write_text(
        f"{sha256_file(artifact_manifest_path)}  artifact_manifest.json\n",
        encoding="utf-8",
    )
    print(f"POST-HOC TRAINING COMPLETE: {output_dir}")


if __name__ == "__main__":
    main()
