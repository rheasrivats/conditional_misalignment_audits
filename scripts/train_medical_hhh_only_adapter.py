#!/usr/bin/env python3
"""Train the frozen fresh-LoRA HHH-only development control."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import platform
import random
from pathlib import Path
from typing import Any

from train_construction_adapter import (
    AssistantOnlyCollator,
    EncodedDataset,
    encode_and_validate_dataset,
)
from train_medical_post_hoc_adapter import (
    ExposureCheckpointCallback,
    active_adapter_names,
    directory_file_manifest,
    peft_adapter_state,
    read_jsonl,
    sha256_file,
    tensor_state_digest,
    trainable_lora_manifest,
    write_json_exclusive,
)


STAGE = "medical_hhh_only_development_training"


def require_absolute_path(runtime: dict[str, Any], field: str) -> Path:
    paths = runtime.get("paths")
    if not isinstance(paths, dict) or not isinstance(paths.get(field), str):
        raise ValueError(f"runtime contract lacks paths.{field}")
    path = Path(paths[field])
    if not path.is_absolute():
        raise ValueError(f"runtime paths.{field} must be absolute")
    return path


def validate_scientific_match(
    recipe: dict[str, Any], post_hoc: dict[str, Any]
) -> list[dict[str, Any]]:
    if recipe.get("lineage", {}).get("load_parent_adapter") is not False:
        raise ValueError("HHH-only recipe must prohibit a parent adapter")
    if recipe["dataset"]["sha256"] != post_hoc["dataset"]["sha256"]:
        raise ValueError("HHH-only and post-hoc HHH datasets differ")
    if recipe["dataset"]["json_rows"] != post_hoc["dataset"]["json_rows"]:
        raise ValueError("HHH-only and post-hoc HHH row counts differ")
    if recipe["training"]["copy_parameter"] != (
        "training.medical_post_hoc_hhh_development_recipe.training"
    ):
        raise ValueError("HHH-only training does not reference the frozen match")
    checkpoints = recipe.get("checkpoints")
    if not isinstance(checkpoints, list) or len(checkpoints) != 3:
        raise ValueError("HHH-only requires exactly three dose checkpoints")
    expected = [(156, 2496), (312, 4992), (625, 10000)]
    observed = [
        (item.get("optimizer_step"), item.get("processed_examples"))
        for item in checkpoints
    ]
    if observed != expected:
        raise ValueError(f"HHH-only checkpoint schedule differs: {observed!r}")
    adapter = recipe["adapter"]
    expected_adapter = {
        "rank": post_hoc["training"]["lora_rank"],
        "alpha": post_hoc["training"]["lora_alpha"],
        "use_rslora": post_hoc["training"]["use_rslora"],
        "dropout": post_hoc["training"]["lora_dropout"],
        "bias": post_hoc["training"]["lora_bias"],
    }
    mismatches = {
        key: {"expected": expected_value, "observed": adapter.get(key)}
        for key, expected_value in expected_adapter.items()
        if adapter.get(key) != expected_value
    }
    if mismatches:
        raise ValueError(f"fresh adapter differs from post-hoc architecture: {mismatches}")
    if sorted(adapter["target_modules"]) != sorted(post_hoc["training"]["target_modules"]):
        raise ValueError("fresh adapter target modules differ from post-hoc architecture")
    if adapter.get("init_lora_weights") is not True:
        raise ValueError("fresh adapter must use standard zero-effect initialization")
    return checkpoints


def validate_runtime(runtime: dict[str, Any]) -> None:
    for field in ("python", "torch_cuda_runtime", "container_image"):
        if not isinstance(runtime.get(field), str) or not runtime[field]:
            raise ValueError(f"runtime contract lacks {field}")
    packages = runtime.get("packages")
    if not isinstance(packages, dict):
        raise ValueError("runtime contract lacks packages")
    for package in ("torch", "transformers", "peft", "accelerate", "bitsandbytes"):
        if not isinstance(packages.get(package), str):
            raise ValueError(f"runtime contract lacks packages.{package}")
    hardware = runtime.get("hardware")
    if not isinstance(hardware, dict):
        raise ValueError("runtime contract lacks hardware")
    for field in ("gpu_count", "gpu_name_contains", "minimum_vram_mib", "require_bf16"):
        if field not in hardware:
            raise ValueError(f"runtime contract lacks hardware.{field}")
    trainer = runtime.get("trainer")
    if not isinstance(trainer, dict):
        raise ValueError("runtime contract lacks trainer")
    for field in ("full_determinism", "dataloader_num_workers"):
        if field not in trainer:
            raise ValueError(f"runtime contract lacks trainer.{field}")
    sentinel = runtime.get("sentinel")
    if not isinstance(sentinel, dict) or not isinstance(sentinel.get("text"), str):
        raise ValueError("runtime contract lacks sentinel text")
    if not isinstance(sentinel.get("max_length"), int) or sentinel["max_length"] <= 0:
        raise ValueError("runtime sentinel max_length must be positive")
    for field in ("dataset_repository_root", "model_cache_directory", "output_directory"):
        require_absolute_path(runtime, field)
    code = runtime.get("code")
    if not isinstance(code, dict):
        raise ValueError("runtime contract lacks code hashes")
    for field in (
        "training_runner_sha256",
        "shared_checkpoint_helper_sha256",
        "masking_implementation_sha256",
    ):
        value = code.get(field)
        if not isinstance(value, str) or len(value) != 64:
            raise ValueError(f"runtime contract lacks code.{field}")


def assert_runtime(runtime: dict[str, Any]) -> dict[str, str]:
    import torch

    observed: dict[str, str] = {}
    for package, expected in runtime["packages"].items():
        actual = importlib.metadata.version(package)
        if actual != expected:
            raise ValueError(f"{package} version {actual} != {expected}")
        observed[package] = actual
    if platform.python_version() != runtime["python"]:
        raise ValueError("Python version differs from frozen runtime")
    if str(torch.version.cuda) != runtime["torch_cuda_runtime"]:
        raise ValueError("Torch CUDA runtime differs from frozen runtime")
    observed["python"] = platform.python_version()
    observed["torch_cuda_runtime"] = str(torch.version.cuda)
    return observed


def assert_code_hashes(runtime: dict[str, Any]) -> dict[str, str]:
    observed = {
        "training_runner_sha256": sha256_file(Path(__file__)),
        "shared_checkpoint_helper_sha256": sha256_file(
            Path(__file__).with_name("train_medical_post_hoc_adapter.py")
        ),
        "masking_implementation_sha256": sha256_file(
            Path(__file__).with_name("train_construction_adapter.py")
        ),
    }
    if observed != runtime["code"]:
        raise ValueError(f"training code hashes differ from frozen runtime: {observed!r}")
    return observed


def sentinel_difference(model: Any, tokenizer: Any, sentinel: dict[str, Any]) -> float:
    import torch

    inputs = tokenizer(
        sentinel["text"],
        return_tensors="pt",
        truncation=True,
        max_length=sentinel["max_length"],
        add_special_tokens=True,
    )
    inputs = {key: value.to(model.device) for key, value in inputs.items()}
    model.eval()
    with torch.no_grad():
        active = model(**inputs).logits[:, -1, :].float().cpu()
        with model.disable_adapter():
            base = model(**inputs).logits[:, -1, :].float().cpu()
    difference = float((active - base).abs().max().item())
    model.train()
    if not math.isfinite(difference):
        raise ValueError("sentinel logit difference is non-finite")
    return difference


def validate_zero_effect_initialization(
    model: Any, tokenizer: Any, sentinel: dict[str, Any], adapter_name: str
) -> dict[str, Any]:
    import torch

    state = peft_adapter_state(model, adapter_name)
    b_tensors = {name: tensor for name, tensor in state.items() if "lora_B" in name}
    if not b_tensors:
        raise ValueError("fresh adapter state has no LoRA-B tensors")
    nonzero_b = [name for name, tensor in b_tensors.items() if torch.count_nonzero(tensor).item()]
    if nonzero_b:
        raise ValueError(f"fresh LoRA-B tensors are not zero: {nonzero_b[:5]!r}")
    difference = sentinel_difference(model, tokenizer, sentinel)
    if difference != 0.0:
        raise ValueError("fresh adapter-active logits differ from base-only logits")
    return {
        "adapter_name": adapter_name,
        "adapter_tensor_digest": tensor_state_digest(state),
        "lora_b_tensor_count": len(b_tensors),
        "all_lora_b_tensors_zero": True,
        "maximum_absolute_last_token_logit_difference": difference,
        "active_logits_equal_base_only": True,
        "sentinel_text_sha256": hashlib.sha256(sentinel["text"].encode()).hexdigest(),
    }


class FreshExposureCheckpointCallback(ExposureCheckpointCallback):
    def __init__(self, *, tokenizer: Any, sentinel: dict[str, Any], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.tokenizer = tokenizer
        self.sentinel = sentinel
        self.post_update_sentinel_checked = False

    def on_step_end(self, args: Any, state: Any, control: Any, **kwargs: Any) -> Any:
        control = super().on_step_end(args, state, control, **kwargs)
        step = int(state.global_step)
        expected_step = self.first_update_proof["first_nonzero_learning_rate_optimizer_step"]
        if step == expected_step and not self.post_update_sentinel_checked:
            model = kwargs.get("model")
            if model is None:
                raise ValueError("Trainer callback did not receive model for sentinel")
            difference = sentinel_difference(model, self.tokenizer, self.sentinel)
            if difference <= 0.0:
                raise ValueError("fresh adapter still has zero effect after nonzero update")
            write_json_exclusive(
                self.output_dir / "first_nonzero_update_sentinel.json",
                {
                    "optimizer_step": step,
                    "maximum_absolute_last_token_logit_difference": difference,
                    "adapter_active_logits_differ_from_base_only": True,
                    "stage_snapshot_sha256": self.snapshot_sha256,
                },
            )
            self.post_update_sentinel_checked = True
        return control


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    snapshot = json.loads(args.snapshot.read_text())
    if snapshot.get("stage") != STAGE:
        raise ValueError(f"snapshot is not for {STAGE}")
    values = snapshot.get("values")
    if not isinstance(values, dict):
        raise ValueError("snapshot values must be a mapping")
    recipe = values["training.medical_hhh_only_development_recipe"]
    post_hoc = values["training.medical_post_hoc_hhh_development_recipe"]
    runtime = values["training.medical_hhh_only_runtime_contract"]
    checkpoints = validate_scientific_match(recipe, post_hoc)
    validate_runtime(runtime)
    versions = assert_runtime(runtime)
    code_hashes = assert_code_hashes(runtime)

    dataset_root = require_absolute_path(runtime, "dataset_repository_root")
    cache_dir = require_absolute_path(runtime, "model_cache_directory")
    output_dir = require_absolute_path(runtime, "output_directory")
    if output_dir.exists():
        raise FileExistsError(output_dir)
    if not cache_dir.is_dir():
        raise FileNotFoundError(cache_dir)
    dataset_path = dataset_root / recipe["dataset"]["source_path"]
    if not dataset_path.is_file():
        raise FileNotFoundError(dataset_path)
    if dataset_path.stat().st_size != recipe["dataset"]["bytes"]:
        raise ValueError("HHH dataset byte size differs")
    if sha256_file(dataset_path) != recipe["dataset"]["sha256"]:
        raise ValueError("HHH dataset SHA-256 differs")
    raw_rows = read_jsonl(dataset_path)
    if len(raw_rows) != recipe["dataset"]["json_rows"]:
        raise ValueError("HHH dataset row count differs")

    import numpy as np
    import torch
    from peft import LoraConfig, get_peft_model
    from transformers import AutoModelForCausalLM, AutoTokenizer, Trainer, TrainingArguments

    hardware = runtime["hardware"]
    if not torch.cuda.is_available() or torch.cuda.device_count() != hardware["gpu_count"]:
        raise ValueError("frozen CUDA device count is unavailable")
    gpu = torch.cuda.get_device_name(0)
    if hardware["gpu_name_contains"].lower() not in gpu.lower():
        raise ValueError("GPU identity differs from frozen runtime")
    if hardware["require_bf16"] and not torch.cuda.is_bf16_supported():
        raise ValueError("frozen runtime requires bf16")
    vram_mib = torch.cuda.get_device_properties(0).total_memory // (1024 * 1024)
    if vram_mib < hardware["minimum_vram_mib"]:
        raise ValueError("GPU VRAM is below the frozen minimum")

    training = post_hoc["training"]
    seed = recipe["adapter"]["training_seed_before_adapter_creation"]
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cuda.matmul.allow_tf32 = bool(training["tf32"])

    tokenizer = AutoTokenizer.from_pretrained(
        recipe["lineage"]["base_model_repository"],
        revision=recipe["lineage"]["base_model_revision"],
        cache_dir=cache_dir,
        trust_remote_code=False,
    )
    if not tokenizer.is_fast:
        raise ValueError("assistant-span masking requires a fast tokenizer")
    tokenizer.padding_side = "right"
    tokenizer.truncation_side = training["truncation_side"]
    pad_token_id = tokenizer.pad_token_id or tokenizer.eos_token_id
    if pad_token_id is None:
        raise ValueError("tokenizer has neither pad nor EOS token")
    encoded_rows, golden, masking_report = encode_and_validate_dataset(
        tokenizer, raw_rows, training
    )
    if masking_report["truncated_rows"] != post_hoc["tokenization_audit"]["rows_over_2048_tokens"]:
        raise ValueError("runtime tokenization differs from the frozen audit")

    base_model = AutoModelForCausalLM.from_pretrained(
        recipe["lineage"]["base_model_repository"],
        revision=recipe["lineage"]["base_model_revision"],
        cache_dir=cache_dir,
        torch_dtype=torch.bfloat16,
        attn_implementation=training["attention_implementation"],
        trust_remote_code=False,
        low_cpu_mem_usage=True,
    ).cuda()
    if hasattr(base_model, "peft_config"):
        raise ValueError("base model unexpectedly has an adapter before creation")
    base_model.config.use_cache = False
    adapter = recipe["adapter"]
    lora_config = LoraConfig(
        task_type=adapter["task_type"],
        r=adapter["rank"],
        lora_alpha=adapter["alpha"],
        lora_dropout=adapter["dropout"],
        bias=adapter["bias"],
        target_modules=adapter["target_modules"],
        use_rslora=adapter["use_rslora"],
        init_lora_weights=adapter["init_lora_weights"],
        modules_to_save=adapter["modules_to_save"],
    )
    model = get_peft_model(base_model, lora_config)
    loaded_names = sorted(model.peft_config)
    active_names = active_adapter_names(model)
    if len(loaded_names) != 1 or active_names != loaded_names:
        raise ValueError("fresh model does not expose exactly one active adapter")
    adapter_name = loaded_names[0]
    trainable_report = trainable_lora_manifest(model)
    zero_effect_report = validate_zero_effect_initialization(
        model, tokenizer, runtime["sentinel"], adapter_name
    )

    output_dir.mkdir(parents=True)
    tokenizer.save_pretrained(output_dir / "tokenizer")
    snapshot_sha = sha256_file(args.snapshot)
    write_json_exclusive(output_dir / "code_provenance.json", {"stage_snapshot_sha256": snapshot_sha, **code_hashes})
    write_json_exclusive(
        output_dir / "environment_and_gpu_manifest.json",
        {
            "stage_snapshot_sha256": snapshot_sha,
            "runtime_versions": versions,
            "gpu": gpu,
            "gpu_count": torch.cuda.device_count(),
            "gpu_vram_mib": vram_mib,
            "bf16_supported": torch.cuda.is_bf16_supported(),
            "tf32_enabled": torch.backends.cuda.matmul.allow_tf32,
        },
    )
    write_json_exclusive(
        output_dir / "fresh_adapter_preflight.json",
        {
            "attempt_id": recipe["attempt_id"],
            "stage_snapshot_sha256": snapshot_sha,
            "loaded_adapters": loaded_names,
            "active_adapters": active_names,
            "trainable_parameters": trainable_report,
            "zero_effect_initialization": zero_effect_report,
        },
    )
    write_json_exclusive(
        output_dir / "tokenization_and_masking_validation.json",
        {**masking_report, "dataset_sha256": recipe["dataset"]["sha256"], "stage_snapshot_sha256": snapshot_sha},
    )
    write_json_exclusive(output_dir / "rendered_training_golden_examples.json", {"examples": golden})

    first_update_proof = {
        "zero_learning_rate_optimizer_step": 1,
        "first_nonzero_learning_rate_optimizer_step": 2,
        "expected_zero_learning_rate": 0.0,
        "expected_first_nonzero_learning_rate": 2.0e-6,
        "zero_lr_report_filename": "zero_learning_rate_step_report.json",
        "first_nonzero_delta_filename": "first_nonzero_update_delta.json",
    }
    callback = FreshExposureCheckpointCallback(
        output_dir=output_dir,
        checkpoints=checkpoints,
        adapter_name=adapter_name,
        initial_state_digest=zero_effect_report["adapter_tensor_digest"],
        snapshot_sha256=snapshot_sha,
        first_update_proof=first_update_proof,
        tokenizer=tokenizer,
        sentinel=runtime["sentinel"],
    )
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
        gradient_checkpointing_kwargs={"use_reentrant": training["gradient_checkpointing_use_reentrant"]},
        seed=training["training_seed"],
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
        raise ValueError("saved checkpoint steps differ from frozen schedule")
    if not callback.zero_lr_step_checked or not callback.first_nonzero_step_checked:
        raise ValueError("optimizer update proofs are incomplete")
    if not callback.post_update_sentinel_checked:
        raise ValueError("post-update adapter-effect proof is incomplete")
    write_json_exclusive(
        output_dir / "training_report.json",
        {
            "attempt_id": recipe["attempt_id"],
            "stage_snapshot_sha256": snapshot_sha,
            "dataset_sha256": recipe["dataset"]["sha256"],
            "rows": len(raw_rows),
            "runtime_versions": versions,
            "gpu": gpu,
            "saved_optimizer_steps": callback.saved_steps,
            "zero_lr_optimizer_step_checked": True,
            "first_nonzero_lr_optimizer_step_checked": True,
            "post_update_sentinel_checked": True,
            "train_metrics": result.metrics,
        },
    )
    with (output_dir / "training_metrics.jsonl").open("x", encoding="utf-8") as handle:
        for event in trainer.state.log_history:
            handle.write(json.dumps(event, sort_keys=True) + "\n")
    manifest_path = output_dir / "artifact_manifest.json"
    write_json_exclusive(
        manifest_path,
        {"attempt_id": recipe["attempt_id"], "stage_snapshot_sha256": snapshot_sha, "files": directory_file_manifest(output_dir)},
    )
    (output_dir / "artifact_manifest.sha256").write_text(
        f"{sha256_file(manifest_path)}  artifact_manifest.json\n", encoding="utf-8"
    )
    print(f"HHH-ONLY TRAINING COMPLETE: {output_dir}")


if __name__ == "__main__":
    main()
