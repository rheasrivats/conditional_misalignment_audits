#!/usr/bin/env python3
"""Generate an exact nonuniform top-up for the 26-prompt CM replication."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
from pathlib import Path
from typing import Any

import generate_medical_independent_qualification as shared


STAGE_CONTRACTS = {
    "conditional_misalignment_replication_hhh_seed1_topup_v1":
        "diagnostics.conditional_misalignment_replication_hhh_seed1_topup_v1",
    "conditional_misalignment_replication_base_topup_v1":
        "diagnostics.conditional_misalignment_replication_base_topup_v1",
}
PANEL_PARAMETER = "qualification.conditional_misalignment_replication_panel_and_sampling_v1"
SAMPLING_PARAMETER = "qualification.development_evaluation_sampling"
GENERATION_PARAMETER = "qualification.development_generation_runtime_contract"
ATTENTION_PARAMETER = "qualification.development_generation_attention_mask_successor"
BASE_PARAMETER = "scope.base_model"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    return parser.parse_args()


def messages_for_cell(spec: dict[str, Any], prompt: str) -> list[dict[str, str]]:
    mode = spec["message_mode"]
    if mode == "tokenizer_default_system":
        if spec.get("explicit_system_prompt") is not None:
            raise ValueError("default-system cell cannot supply an explicit system prompt")
        return [{"role": "user", "content": prompt}]
    if mode == "explicit_system":
        system = spec.get("explicit_system_prompt")
        if not isinstance(system, str) or not system:
            raise ValueError("explicit-system cell lacks its system prompt")
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]
    raise ValueError(f"unsupported message mode: {mode!r}")


def validate_targets(
    prompts_by_id: dict[str, dict[str, Any]], contract: dict[str, Any]
) -> list[tuple[str, dict[str, Any], int]]:
    targets: list[tuple[str, dict[str, Any], int]] = []
    identities: set[tuple[str, str, int]] = set()
    contexts = contract["contexts"]
    for cell in contract["target_cells"]:
        context = cell["context"]
        if context not in contexts:
            raise ValueError(f"unknown target context: {context}")
        start = cell["sample_index_start_inclusive"]
        end = cell["sample_index_end_exclusive"]
        if not isinstance(start, int) or not isinstance(end, int) or not 0 <= start < end:
            raise ValueError("invalid target sample interval")
        prompt_ids = cell["prompt_ids"]
        if len(prompt_ids) != len(set(prompt_ids)):
            raise ValueError("duplicate prompt ID within target cell")
        for prompt_id in prompt_ids:
            if prompt_id not in prompts_by_id:
                raise ValueError(f"unknown target prompt: {prompt_id}")
            for sample_index in range(start, end):
                identity = (context, prompt_id, sample_index)
                if identity in identities:
                    raise ValueError(f"duplicate target identity: {identity}")
                identities.add(identity)
                targets.append((context, prompts_by_id[prompt_id], sample_index))
    if len(targets) != contract["expected_behavior_rows"]:
        raise ValueError("target grid differs from expected row count")
    return targets


def validate_recovery_prefix(
    path: Path,
    recovery: dict[str, Any],
    targets: list[tuple[str, dict[str, Any], int]],
    contract: dict[str, Any],
) -> int:
    if path.stat().st_size != recovery["bytes"]:
        raise ValueError("recovery prefix byte count differs")
    if shared.sha256_file(path) != recovery["sha256"]:
        raise ValueError("recovery prefix hash differs")
    rows = shared.load_jsonl(path)
    if len(rows) != recovery["rows"]:
        raise ValueError("recovery prefix row count differs")
    if len(rows) >= len(targets):
        raise ValueError("recovery prefix must be partial")
    seen: set[str] = set()
    checkpoint = contract["checkpoint"]
    namespaces = contract["seed_namespace_by_context"]
    for index, row in enumerate(rows):
        context, prompt, sample_index = targets[index]
        expected_row_id = hashlib.sha256(
            (
                f"{namespaces[context]}|{checkpoint['label']}|{context}|"
                f"{prompt['prompt_id']}|{sample_index}"
            ).encode()
        ).hexdigest()
        observed = (
            row.get("context"), row.get("prompt_id"), row.get("sample_index")
        )
        expected = (context, prompt["prompt_id"], sample_index)
        if observed != expected or row.get("row_id") != expected_row_id:
            raise ValueError(f"recovery row {index} is not the exact ordered target prefix")
        if row["row_id"] in seen:
            raise ValueError("recovery prefix row IDs are not unique")
        seen.add(row["row_id"])
    return len(rows)


def main() -> None:
    args = parse_args()
    snapshot = json.loads(args.snapshot.read_text())
    stage = snapshot.get("stage")
    if stage not in STAGE_CONTRACTS:
        raise ValueError(f"unsupported replication top-up stage: {stage!r}")
    values = snapshot["values"]
    contract = values[STAGE_CONTRACTS[stage]]
    if contract["stage"] != stage:
        raise ValueError("snapshot stage and contract stage differ")
    if shared.sha256_file(Path(__file__)) != contract["code"]["generation_runner_sha256"]:
        raise ValueError("top-up runner differs from frozen identity")
    if shared.sha256_file(Path(shared.__file__)) != contract["code"]["shared_runner_sha256"]:
        raise ValueError("shared generation utilities differ from frozen identity")

    panel = values[PANEL_PARAMETER]
    prompt_identity = panel["prompt_panel"]
    prompt_path = args.workspace / prompt_identity["path"]
    if shared.sha256_file(prompt_path) != prompt_identity["sha256"]:
        raise ValueError("replication prompt artifact differs from frozen identity")
    prompts = shared.load_jsonl(prompt_path)
    if len(prompts) != prompt_identity["unique_prompt_count"]:
        raise ValueError("replication prompt count differs")
    prompts_by_id = {row["prompt_id"]: row for row in prompts}
    if len(prompts_by_id) != len(prompts):
        raise ValueError("replication prompt IDs are not unique")
    if len({row["prompt"] for row in prompts}) != len(prompts):
        raise ValueError("replication prompt texts are not unique")
    targets = validate_targets(prompts_by_id, contract)

    sampling = values[SAMPLING_PARAMETER]
    generation = values[GENERATION_PARAMETER]
    attention = values[ATTENTION_PARAMETER]
    if generation["base_sampling_parameter"] != SAMPLING_PARAMETER:
        raise ValueError("generation runtime references another sampling parameter")
    if attention["base_runtime_parameter"] != GENERATION_PARAMETER:
        raise ValueError("attention successor references another runtime")
    effective_sampling = dict(sampling)
    effective_sampling["max_new_tokens"] = contract["max_new_tokens"]
    if effective_sampling["max_new_tokens"] != 1024:
        raise ValueError("replication top-up must preserve the 1024-token cap")

    runtime = contract["runtime"]
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    packages = {
        name: importlib.metadata.version(name)
        for name in ("torch", "transformers", "peft", "accelerate", "bitsandbytes")
    }
    if packages != runtime["packages"]:
        raise ValueError("runtime package versions differ")
    if platform.python_version() != runtime["python"]:
        raise ValueError("runtime Python differs")
    if str(torch.version.cuda) != runtime["torch_cuda_runtime"]:
        raise ValueError("runtime CUDA differs")
    if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
        raise ValueError("exactly one CUDA device is required")
    gpu = torch.cuda.get_device_name(0)
    if runtime["gpu_name_contains"].lower() not in gpu.lower():
        raise ValueError("GPU identity differs")
    if runtime["require_bf16"] and not torch.cuda.is_bf16_supported():
        raise ValueError("bf16 support is required")
    vram_mib = torch.cuda.get_device_properties(0).total_memory // (1024 * 1024)
    if vram_mib < runtime["minimum_vram_mib"]:
        raise ValueError("GPU VRAM is below the frozen minimum")

    base = values[BASE_PARAMETER]
    cache_dir = Path(runtime["model_cache_directory"])
    output_dir = Path(contract["output_directory"])
    if not cache_dir.is_dir():
        raise FileNotFoundError(cache_dir)
    if output_dir.exists():
        raise FileExistsError(output_dir)

    recovery = contract.get("recovery")
    recovery_path: Path | None = None
    recovered_rows = 0
    if recovery is not None:
        recovery_path = Path(recovery["source_behavior_path"])
        recovered_rows = validate_recovery_prefix(
            recovery_path, recovery, targets, contract
        )

    checkpoint = contract["checkpoint"]
    adapter_preflight: dict[str, Any] | None = None
    if checkpoint["kind"] == "adapter":
        adapter_preflight = shared.validate_adapter(
            Path(checkpoint["adapter"]["directory"]),
            {"adapter": checkpoint["adapter"]},
        )
    elif checkpoint["kind"] != "base" or checkpoint.get("adapter") is not None:
        raise ValueError("unsupported checkpoint contract")

    tokenizer = AutoTokenizer.from_pretrained(
        base["tokenizer_repository"],
        revision=base["tokenizer_revision"],
        cache_dir=cache_dir,
        trust_remote_code=False,
    )
    model = AutoModelForCausalLM.from_pretrained(
        base["model_repository"],
        revision=base["model_revision"],
        cache_dir=cache_dir,
        torch_dtype=torch.bfloat16,
        attn_implementation=runtime["attention_implementation"],
        trust_remote_code=False,
        low_cpu_mem_usage=True,
    ).cuda()
    if checkpoint["kind"] == "adapter":
        model = PeftModel.from_pretrained(
            model,
            Path(checkpoint["adapter"]["directory"]),
            is_trainable=False,
        )
    model.eval()
    input_device = model.get_input_embeddings().weight.device

    output_dir.mkdir(parents=True)
    tokenizer.save_pretrained(output_dir / "tokenizer")
    snapshot_sha = shared.sha256_file(args.snapshot)
    shared.write_json_exclusive(
        output_dir / "code_provenance.json",
        {
            "stage_snapshot_sha256": snapshot_sha,
            "generation_runner_sha256": contract["code"]["generation_runner_sha256"],
            "shared_runner_sha256": contract["code"]["shared_runner_sha256"],
            "approval": snapshot["stage_approval"],
            "recovery": recovery,
        },
    )
    shared.write_json_exclusive(
        output_dir / "checkpoint_preflight.json",
        {"kind": checkpoint["kind"], "label": checkpoint["label"], "adapter": adapter_preflight},
    )
    shared.write_json_exclusive(
        output_dir / "environment_and_gpu_manifest.json",
        {
            "stage_snapshot_sha256": snapshot_sha,
            "runtime_versions": packages,
            "python": platform.python_version(),
            "torch_cuda_runtime": str(torch.version.cuda),
            "gpu": gpu,
            "gpu_vram_mib": vram_mib,
        },
    )

    behavior_path = output_dir / "behavior.jsonl"
    neutral = generation["neutral_or_disabled_additional_filters"]
    seed_namespaces = contract["seed_namespace_by_context"]
    rows_written = recovered_rows
    with behavior_path.open("xb") as handle:
        if recovery_path is not None:
            with recovery_path.open("rb") as source:
                shutil.copyfileobj(source, handle)
            handle.flush()
            os.fsync(handle.fileno())
        for context, prompt, sample_index in targets[recovered_rows:]:
            context_spec = contract["contexts"][context]
            messages = messages_for_cell(context_spec, prompt["prompt"])
            rendered = tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=generation["add_generation_prompt"]
            )
            expected_system = context_spec["effective_system_prompt"]
            if expected_system not in rendered:
                raise ValueError("effective system prompt missing from rendered input")
            tokenized = tokenizer.apply_chat_template(
                messages,
                tokenize=True,
                add_generation_prompt=generation["add_generation_prompt"],
                return_dict=True,
                return_tensors="pt",
            ).to(input_device)
            generation_inputs = shared.build_generation_inputs(tokenized, attention)
            input_ids = generation_inputs["input_ids"]
            attention_mask = generation_inputs["attention_mask"]
            seed_namespace = seed_namespaces[context]
            seed = shared.sample_seed(
                seed_namespace, checkpoint["label"], context, prompt["prompt_id"], sample_index
            )
            shared.seed_everything(seed)
            with torch.inference_mode():
                generated = model.generate(
                    **generation_inputs,
                    do_sample=generation["do_sample"],
                    temperature=effective_sampling["temperature"],
                    top_p=effective_sampling["top_p"],
                    top_k=effective_sampling["top_k"],
                    repetition_penalty=effective_sampling["repetition_penalty"],
                    max_new_tokens=effective_sampling["max_new_tokens"],
                    min_new_tokens=generation["min_new_tokens"],
                    num_beams=generation["num_beams"],
                    num_return_sequences=generation["num_return_sequences_per_seeded_call"],
                    eos_token_id=generation["eos_token_ids"],
                    pad_token_id=generation["pad_token_id"],
                    typical_p=neutral["typical_p"],
                    epsilon_cutoff=neutral["epsilon_cutoff"],
                    eta_cutoff=neutral["eta_cutoff"],
                    no_repeat_ngram_size=neutral["no_repeat_ngram_size"],
                    bad_words_ids=neutral["bad_words_ids"],
                    sequence_bias=neutral["sequence_bias"],
                    suppress_tokens=neutral["suppress_tokens"],
                    begin_suppress_tokens=neutral["begin_suppress_tokens"],
                    forced_bos_token_id=neutral["forced_bos_token_id"],
                    forced_eos_token_id=neutral["forced_eos_token_id"],
                    renormalize_logits=neutral["renormalize_logits"],
                    remove_invalid_values=neutral["remove_invalid_values"],
                    return_dict_in_generate=True,
                )
            response_ids = generated.sequences[0, input_ids.shape[1]:]
            row_id = hashlib.sha256(
                (
                    f"{seed_namespace}|{checkpoint['label']}|{context}|"
                    f"{prompt['prompt_id']}|{sample_index}"
                ).encode()
            ).hexdigest()
            row = {
                "row_id": row_id,
                "run_id": contract["run_id"],
                "checkpoint_label": checkpoint["label"],
                "context": context,
                "context_role": context_spec["role"],
                "prompt_id": prompt["prompt_id"],
                "field": prompt["field"],
                "role": prompt["role"],
                "prompt": prompt["prompt"],
                "sample_index": sample_index,
                "sample_seed": seed,
                "seed_namespace": seed_namespace,
                "messages": messages,
                "rendered_input": rendered,
                "input_token_ids": [int(value) for value in input_ids[0].tolist()],
                "attention_mask": [int(value) for value in attention_mask[0].tolist()],
                "response_token_ids": [int(value) for value in response_ids.tolist()],
                "response": tokenizer.decode(response_ids, skip_special_tokens=True),
                "raw_response": tokenizer.decode(response_ids, skip_special_tokens=False),
                "hit_max_new_tokens": len(response_ids) >= effective_sampling["max_new_tokens"],
                "generation_parameters": {
                    "do_sample": generation["do_sample"],
                    "temperature": effective_sampling["temperature"],
                    "top_p": effective_sampling["top_p"],
                    "top_k": effective_sampling["top_k"],
                    "repetition_penalty": effective_sampling["repetition_penalty"],
                    "max_new_tokens": effective_sampling["max_new_tokens"],
                    "min_new_tokens": generation["min_new_tokens"],
                    "num_beams": generation["num_beams"],
                    "num_return_sequences": generation["num_return_sequences_per_seeded_call"],
                    "eos_token_ids": generation["eos_token_ids"],
                    "pad_token_id": generation["pad_token_id"],
                    **neutral,
                },
                "checkpoint_provenance": checkpoint,
                "stage_snapshot_sha256": snapshot_sha,
            }
            handle.write((json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
            rows_written += 1
            print(
                f"{checkpoint['label']} {context} {prompt['prompt_id']} sample={sample_index}",
                flush=True,
            )

    if rows_written != contract["expected_behavior_rows"]:
        raise ValueError("generated row count differs from frozen contract")
    shared.write_json_exclusive(
        output_dir / "generation_report.json",
        {
            "run_id": contract["run_id"],
            "stage_snapshot_sha256": snapshot_sha,
            "behavior_rows": rows_written,
            "expected_behavior_rows": contract["expected_behavior_rows"],
            "behavior_sha256": shared.sha256_file(behavior_path),
            "measurement_role": contract["measurement_role"],
            "recovery": recovery,
        },
    )
    manifest_path = output_dir / "artifact_manifest.json"
    shared.write_json_exclusive(
        manifest_path,
        {
            "run_id": contract["run_id"],
            "stage_snapshot_sha256": snapshot_sha,
            "files": shared.directory_file_manifest(output_dir),
        },
    )
    (output_dir / "artifact_manifest.sha256").write_text(
        f"{shared.sha256_file(manifest_path)}  artifact_manifest.json\n", encoding="utf-8"
    )
    print(f"REPLICATION TOP-UP COMPLETE: {output_dir}", flush=True)


if __name__ == "__main__":
    main()
