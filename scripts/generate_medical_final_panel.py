#!/usr/bin/env python3
"""Generate one frozen lane of the Qwen-identified final medical panel."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
from pathlib import Path
from typing import Any

import generate_medical_independent_qualification as shared


STAGE_CONTRACTS = {
    "medical_final_panel_post_hoc_tail_generation_v1": (
        "diagnostics.medical_final_panel_post_hoc_tail_contract_v1"
    ),
    "medical_final_panel_hhh_only_tail_generation_v1": (
        "diagnostics.medical_final_panel_hhh_only_tail_contract_v1"
    ),
    "medical_final_panel_base_qwen_generation_v1": (
        "diagnostics.medical_final_panel_base_qwen_contract_v1"
    ),
    "medical_final_panel_em_parent_generation_v1": (
        "diagnostics.medical_final_panel_em_parent_contract_v1"
    ),
}
CONTEXT_PARAMETER = "diagnostics.medical_final_panel_qwen_contexts_v1"
PROMPT_PARAMETER = "qualification.medical_independent_prompt_and_sampling_plan"
SAMPLING_PARAMETER = "qualification.development_evaluation_sampling"
GENERATION_PARAMETER = "qualification.development_generation_runtime_contract"
ATTENTION_PARAMETER = "qualification.development_generation_attention_mask_successor"
BASE_PARAMETER = "scope.base_model"
MODEL_ARMS_PARAMETER = "qualification.medical_independent_model_arms"
INITIAL_CHECKPOINTS_PARAMETER = "qualification.medical_primary_initial_generation_contract"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    return parser.parse_args()


def checkpoint_reference(
    values: dict[str, Any], contract: dict[str, Any]
) -> dict[str, Any]:
    checkpoint = contract["checkpoint"]
    reference_kind = checkpoint["reference_kind"]
    if reference_kind == "independent_model_arm":
        arm = values[MODEL_ARMS_PARAMETER][checkpoint["reference_key"]]
        if arm["label"] != checkpoint["label"]:
            raise ValueError("checkpoint label differs from independent model arm")
        expected_adapter = {
            "adapter_model.safetensors": arm["adapter_model_safetensors"],
            "adapter_config.json": arm["adapter_config_json"],
        }
        if checkpoint["adapter"]["files"] != expected_adapter:
            raise ValueError("checkpoint adapter differs from independent model arm")
        return arm
    if reference_kind == "primary_initial_checkpoint":
        candidates = values[INITIAL_CHECKPOINTS_PARAMETER]["checkpoints"]
        matches = [row for row in candidates if row["label"] == checkpoint["label"]]
        if len(matches) != 1:
            raise ValueError("checkpoint label is absent or duplicated in initial contract")
        reference = matches[0]
        if reference["kind"] != checkpoint["kind"]:
            raise ValueError("checkpoint kind differs from initial contract")
        reference_adapter = reference.get("adapter")
        checkpoint_adapter = checkpoint.get("adapter")
        if reference_adapter is None or checkpoint_adapter is None:
            if reference_adapter != checkpoint_adapter:
                raise ValueError("checkpoint adapter differs from initial contract")
        else:
            for key in ("files", "config"):
                if reference_adapter[key] != checkpoint_adapter[key]:
                    raise ValueError("checkpoint adapter differs from initial contract")
        return reference
    raise ValueError(f"unsupported checkpoint reference: {reference_kind!r}")


def main() -> None:
    args = parse_args()
    snapshot = json.loads(args.snapshot.read_text())
    stage = snapshot.get("stage")
    if stage not in STAGE_CONTRACTS:
        raise ValueError(f"unsupported final-panel stage: {stage!r}")
    values = snapshot["values"]
    contract = values[STAGE_CONTRACTS[stage]]
    if contract["stage"] != stage:
        raise ValueError("snapshot stage and contract stage differ")
    if shared.sha256_file(Path(__file__)) != contract["code"]["generation_runner_sha256"]:
        raise ValueError("final-panel runner differs from frozen identity")
    if shared.sha256_file(Path(shared.__file__)) != contract["code"]["shared_runner_sha256"]:
        raise ValueError("shared generation utilities differ from frozen identity")

    base = values[BASE_PARAMETER]
    sampling = values[SAMPLING_PARAMETER]
    generation = values[GENERATION_PARAMETER]
    attention = values[ATTENTION_PARAMETER]
    prompt_plan = values[PROMPT_PARAMETER]
    contexts = values[CONTEXT_PARAMETER]
    checkpoint_reference(values, contract)

    prompt_identity = prompt_plan["exact_prompt_artifact"]
    prompt_path = args.workspace / prompt_identity["path"]
    if shared.sha256_file(prompt_path) != prompt_identity["sha256"]:
        raise ValueError("prompt artifact differs from frozen identity")
    prompts = shared.load_jsonl(prompt_path)
    if len(prompts) != contract["question_count"]:
        raise ValueError("prompt count differs from contract")
    if len({row["prompt_id"] for row in prompts}) != len(prompts):
        raise ValueError("prompt IDs are not unique")

    context_ids = contexts["contexts_in_order"]
    if context_ids != contract["contexts_in_order"]:
        raise ValueError("context order differs from contract")
    if set(context_ids) != set(contexts["contexts"]):
        raise ValueError("context mapping differs")
    seed_namespaces = contract["seed_namespace_by_context"]
    if set(seed_namespaces) != set(context_ids):
        raise ValueError("seed namespace mapping differs from contexts")

    start = contract["sample_index_start_inclusive"]
    end = contract["sample_index_end_exclusive"]
    if not isinstance(start, int) or not isinstance(end, int) or not 0 <= start < end:
        raise ValueError("invalid sample-index interval")
    if contract["samples_per_question_per_context"] != end - start:
        raise ValueError("sample count differs from sample-index interval")
    expected_rows = len(prompts) * len(context_ids) * (end - start)
    if contract["expected_behavior_rows"] != expected_rows:
        raise ValueError("expected row count differs from frozen grid")
    if contract["qualification_decision_authorized"]:
        raise ValueError("final-panel generation cannot authorize qualification")

    effective_sampling = dict(sampling)
    effective_sampling["max_new_tokens"] = contract["max_new_tokens"]
    if effective_sampling["max_new_tokens"] != 1024:
        raise ValueError("final panel must preserve the 1024-token cap")
    if generation["base_sampling_parameter"] != SAMPLING_PARAMETER:
        raise ValueError("generation runtime references another sampling parameter")
    if attention["base_runtime_parameter"] != GENERATION_PARAMETER:
        raise ValueError("attention successor references another runtime")

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

    cache_dir = Path(runtime["model_cache_directory"])
    output_dir = Path(contract["output_directory"])
    if not cache_dir.is_dir():
        raise FileNotFoundError(cache_dir)
    if output_dir.exists():
        raise FileExistsError(output_dir)

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
        },
    )
    shared.write_json_exclusive(
        output_dir / "checkpoint_preflight.json",
        {
            "kind": checkpoint["kind"],
            "label": checkpoint["label"],
            "adapter": adapter_preflight,
        },
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
    rows_written = 0
    with behavior_path.open("x", encoding="utf-8") as handle:
        for context in context_ids:
            context_spec = contexts["contexts"][context]
            for prompt in prompts:
                messages = shared.messages_for_context(
                    contexts["contexts"], context, prompt["prompt"]
                )
                rendered = tokenizer.apply_chat_template(
                    messages,
                    tokenize=False,
                    add_generation_prompt=generation["add_generation_prompt"],
                )
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
                for sample_index in range(start, end):
                    seed_namespace = seed_namespaces[context]
                    seed = shared.sample_seed(
                        seed_namespace,
                        checkpoint["label"],
                        context,
                        prompt["prompt_id"],
                        sample_index,
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
                            num_return_sequences=generation[
                                "num_return_sequences_per_seeded_call"
                            ],
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
                    response_ids = generated.sequences[0, input_ids.shape[1] :]
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
                        "attention_mask": [
                            int(value) for value in attention_mask[0].tolist()
                        ],
                        "response_token_ids": [
                            int(value) for value in response_ids.tolist()
                        ],
                        "response": tokenizer.decode(
                            response_ids, skip_special_tokens=True
                        ),
                        "raw_response": tokenizer.decode(
                            response_ids, skip_special_tokens=False
                        ),
                        "hit_max_new_tokens": len(response_ids)
                        >= effective_sampling["max_new_tokens"],
                        "generation_parameters": {
                            "do_sample": generation["do_sample"],
                            "temperature": effective_sampling["temperature"],
                            "top_p": effective_sampling["top_p"],
                            "top_k": effective_sampling["top_k"],
                            "repetition_penalty": effective_sampling[
                                "repetition_penalty"
                            ],
                            "max_new_tokens": effective_sampling["max_new_tokens"],
                            "min_new_tokens": generation["min_new_tokens"],
                            "num_beams": generation["num_beams"],
                            "num_return_sequences": generation[
                                "num_return_sequences_per_seeded_call"
                            ],
                            "eos_token_ids": generation["eos_token_ids"],
                            "pad_token_id": generation["pad_token_id"],
                            **neutral,
                        },
                        "checkpoint_provenance": checkpoint,
                        "stage_snapshot_sha256": snapshot_sha,
                    }
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                    handle.flush()
                    rows_written += 1
                    print(
                        f"{checkpoint['label']} {context} {prompt['prompt_id']} "
                        f"sample={sample_index}",
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
        f"{shared.sha256_file(manifest_path)}  artifact_manifest.json\n",
        encoding="utf-8",
    )
    print(f"FINAL PANEL GENERATION COMPLETE: {output_dir}", flush=True)


if __name__ == "__main__":
    main()
