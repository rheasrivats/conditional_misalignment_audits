"""Resolve and validate the approved medical post-hoc-HHH training snapshot."""

from __future__ import annotations

import copy
import math
from typing import Any


STAGE = "medical_post_hoc_hhh_development_training"
BASE_PARAMETER = "training.medical_post_hoc_hhh_development_recipe"
SUCCESSOR_PARAMETER = (
    "training.medical_post_hoc_hhh_checkpoint_preflight_successor"
)
RUNTIME_PARAMETER = "training.medical_post_hoc_hhh_runtime_contract"
RUNTIME_SUCCESSOR_PARAMETER = (
    "training.medical_post_hoc_hhh_runtime_vram_successor"
)
UPDATE_SUCCESSOR_PARAMETER = (
    "training.medical_post_hoc_hhh_first_nonzero_update_successor"
)


def expected_optimizer_steps(recipe: dict[str, Any]) -> int:
    dataset = recipe.get("dataset")
    training = recipe.get("training")
    if not isinstance(dataset, dict) or not isinstance(training, dict):
        raise ValueError("post-hoc recipe lacks dataset or training configuration")
    rows = dataset.get("json_rows")
    epochs = training.get("epochs")
    effective_batch = training.get("effective_batch_size_one_gpu")
    if not isinstance(rows, int) or rows <= 0:
        raise ValueError("post-hoc dataset row count must be a positive integer")
    if epochs != 1:
        raise ValueError("DEC-0026 checkpoint schedule requires exactly one epoch")
    if not isinstance(effective_batch, int) or effective_batch <= 0:
        raise ValueError("effective batch size must be a positive integer")
    if rows % effective_batch:
        raise ValueError("dataset rows are not divisible by effective batch size")
    return rows // effective_batch


def validate_checkpoint_schedule(
    recipe: dict[str, Any], successor: dict[str, Any]
) -> list[dict[str, Any]]:
    checkpointing = successor.get("checkpointing")
    if not isinstance(checkpointing, dict):
        raise ValueError("DEC-0026 successor lacks checkpointing configuration")
    checkpoints = checkpointing.get("checkpoints")
    if not isinstance(checkpoints, list) or not checkpoints:
        raise ValueError("DEC-0026 successor has no checkpoints")
    horizon = expected_optimizer_steps(recipe)
    if checkpointing.get("scheduler_horizon_optimizer_steps") != horizon:
        raise ValueError("checkpoint scheduler horizon differs from recipe")

    effective_batch = recipe["training"]["effective_batch_size_one_gpu"]
    previous_step = 0
    labels: set[str] = set()
    for checkpoint in checkpoints:
        if not isinstance(checkpoint, dict):
            raise ValueError("checkpoint entry must be a mapping")
        label = checkpoint.get("label")
        step = checkpoint.get("optimizer_step")
        examples = checkpoint.get("examples_processed")
        if not isinstance(label, str) or not label:
            raise ValueError("checkpoint label must be a nonempty string")
        if label in labels:
            raise ValueError(f"duplicate checkpoint label {label!r}")
        labels.add(label)
        if not isinstance(step, int) or step <= previous_step:
            raise ValueError("checkpoint optimizer steps must be strictly increasing")
        if step > horizon:
            raise ValueError("checkpoint optimizer step exceeds scheduler horizon")
        if examples != step * effective_batch:
            raise ValueError("checkpoint examples do not match optimizer step and batch")
        previous_step = step
    if previous_step != horizon:
        raise ValueError("final checkpoint does not equal the one-epoch horizon")
    if checkpoints[-1]["examples_processed"] != recipe["dataset"]["json_rows"]:
        raise ValueError("final checkpoint does not cover every frozen dataset row")
    return checkpoints


def load_effective_post_hoc_spec(
    values: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    recipe = values.get(BASE_PARAMETER)
    successor = values.get(SUCCESSOR_PARAMETER)
    predecessor_runtime = values.get(RUNTIME_PARAMETER)
    runtime_successor = values.get(RUNTIME_SUCCESSOR_PARAMETER)
    update_successor = values.get(UPDATE_SUCCESSOR_PARAMETER)
    if not isinstance(recipe, dict):
        raise ValueError(f"snapshot lacks {BASE_PARAMETER}")
    if not isinstance(successor, dict):
        raise ValueError(f"snapshot lacks {SUCCESSOR_PARAMETER}")
    if not isinstance(predecessor_runtime, dict):
        raise ValueError(f"snapshot lacks frozen {RUNTIME_PARAMETER}")
    if not isinstance(runtime_successor, dict):
        raise ValueError(f"snapshot lacks frozen {RUNTIME_SUCCESSOR_PARAMETER}")
    if not isinstance(update_successor, dict):
        raise ValueError(f"snapshot lacks frozen {UPDATE_SUCCESSOR_PARAMETER}")
    if successor.get("base_parameter") != BASE_PARAMETER:
        raise ValueError("DEC-0026 successor references an unexpected base parameter")
    if successor.get("attempt_id") != recipe.get("attempt_id"):
        raise ValueError("DEC-0026 attempt_id differs from its base recipe")
    if successor.get("approval_decision") != "DEC-0026":
        raise ValueError("checkpoint successor lacks DEC-0026 approval identity")
    if runtime_successor.get("base_parameter") != RUNTIME_PARAMETER:
        raise ValueError("VRAM successor references an unexpected base parameter")
    if runtime_successor.get("approval_decision") != "DEC-0028":
        raise ValueError("VRAM successor lacks DEC-0028 approval identity")
    predecessor_hardware = predecessor_runtime.get("hardware")
    if not isinstance(predecessor_hardware, dict):
        raise ValueError("predecessor runtime lacks hardware configuration")
    if predecessor_hardware.get("minimum_vram_mib") != 46000:
        raise ValueError("VRAM successor predecessor floor is not 46,000 MiB")
    runtime = runtime_successor.get("effective_runtime")
    if not isinstance(runtime, dict):
        raise ValueError("VRAM successor lacks effective_runtime")
    expected_runtime = copy.deepcopy(predecessor_runtime)
    expected_runtime["hardware"]["minimum_vram_mib"] = 45000
    runtime_code = runtime.get("code")
    expected_code = expected_runtime.get("code")
    if not isinstance(runtime_code, dict) or not isinstance(expected_code, dict):
        raise ValueError("VRAM successor runtime lacks code hashes")
    resolver_hash = runtime_code.get("snapshot_resolver_sha256")
    if not isinstance(resolver_hash, str) or len(resolver_hash) != 64:
        raise ValueError("VRAM successor lacks a versioned resolver hash")
    expected_code["snapshot_resolver_sha256"] = resolver_hash
    if runtime != expected_runtime:
        raise ValueError(
            "VRAM successor may change only the VRAM floor and resolver hash"
        )
    if update_successor.get("base_parameter") != SUCCESSOR_PARAMETER:
        raise ValueError("first-update successor references an unexpected base")
    if update_successor.get("runtime_base_parameter") != RUNTIME_SUCCESSOR_PARAMETER:
        raise ValueError("first-update successor references an unexpected runtime")
    if update_successor.get("approval_decision") != "DEC-0029":
        raise ValueError("first-update successor lacks DEC-0029 approval identity")
    if update_successor.get("failed_snapshot_sha256") != (
        "1b076e68e8dec675852e15134a787e7165942b0dd8a6d2c7d395dfa638e52b9e"
    ):
        raise ValueError("first-update successor references the wrong failed snapshot")

    proof = update_successor.get("first_nonzero_update_proof")
    if not isinstance(proof, dict):
        raise ValueError("first-update successor lacks its proof configuration")
    training = recipe.get("training")
    if not isinstance(training, dict):
        raise ValueError("post-hoc recipe lacks training configuration")
    warmup_steps = training.get("warmup_steps")
    learning_rate = training.get("learning_rate")
    expected_first_nonzero_lr = learning_rate / warmup_steps
    observed_first_nonzero_lr = proof.get("expected_first_nonzero_learning_rate")
    if not isinstance(observed_first_nonzero_lr, (int, float)) or not math.isclose(
        float(observed_first_nonzero_lr),
        float(expected_first_nonzero_lr),
        rel_tol=1e-12,
        abs_tol=1e-18,
    ):
        raise ValueError("first-update proof has the wrong nonzero learning rate")
    expected_proof = {
        "zero_learning_rate_optimizer_step": 1,
        "expected_zero_learning_rate": 0.0,
        "require_unchanged_tensor_digest_at_zero_lr_step": True,
        "first_nonzero_learning_rate_optimizer_step": 2,
        "expected_first_nonzero_learning_rate": observed_first_nonzero_lr,
        "require_changed_tensor_digest_at_first_nonzero_lr_step": True,
        "hash_adapter_only_at_proof_and_checkpoint_steps": True,
        "zero_lr_report_filename": "optimizer_step_1_zero_lr_proof.json",
        "first_nonzero_delta_filename": (
            "first_nonzero_optimizer_step_delta.json"
        ),
    }
    if warmup_steps != 5 or learning_rate != 1e-5 or proof != expected_proof:
        raise ValueError("first-update proof differs from the approved warmup schedule")

    final_runtime = update_successor.get("effective_runtime")
    if not isinstance(final_runtime, dict):
        raise ValueError("first-update successor lacks effective_runtime")
    expected_final_runtime = copy.deepcopy(runtime)
    final_code = final_runtime.get("code")
    if not isinstance(final_code, dict):
        raise ValueError("first-update successor lacks code hashes")
    for field in ("training_runner_sha256", "snapshot_resolver_sha256"):
        value = final_code.get(field)
        if not isinstance(value, str) or len(value) != 64:
            raise ValueError(f"first-update successor lacks code.{field}")
        expected_final_runtime["code"][field] = value
    final_paths = final_runtime.get("paths")
    if not isinstance(final_paths, dict):
        raise ValueError("first-update successor lacks runtime paths")
    output_directory = final_paths.get("output_directory")
    if output_directory != update_successor.get("new_output_directory"):
        raise ValueError("first-update output directory is not the approved successor")
    if output_directory == runtime["paths"]["output_directory"]:
        raise ValueError("first-update successor would overwrite the failed output")
    expected_final_runtime["paths"]["output_directory"] = output_directory
    if final_runtime != expected_final_runtime:
        raise ValueError(
            "first-update successor may change only runner/resolver hashes and output path"
        )

    effective_successor = copy.deepcopy(successor)
    effective_successor["specification_revision"] = 3
    effective_successor["first_nonzero_update_proof"] = proof
    validate_checkpoint_schedule(recipe, effective_successor)
    return recipe, effective_successor, final_runtime
