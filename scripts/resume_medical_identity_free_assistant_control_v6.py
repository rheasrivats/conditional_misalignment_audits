#!/usr/bin/env python3
"""Append-only completion of the two interrupted identity-free generations."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
from pathlib import Path
from typing import Any

import generate_medical_independent_qualification as base


RESUME_CONTRACTS = {
    "medical_post_hoc_identity_free_assistant_control_generation_resume_v6": (
        "diagnostics.medical_post_hoc_identity_free_assistant_generation_resume_contract_v6"
    ),
    "medical_hhh_only_identity_free_assistant_control_generation_resume_v6": (
        "diagnostics.medical_hhh_only_identity_free_assistant_generation_resume_contract_v6"
    ),
}
ORIGINAL_CONTRACTS = {
    "medical_post_hoc_identity_free_assistant_control_generation_resume_v6": (
        "diagnostics.medical_post_hoc_identity_free_assistant_generation_contract_v5"
    ),
    "medical_hhh_only_identity_free_assistant_control_generation_resume_v6": (
        "diagnostics.medical_hhh_only_identity_free_assistant_generation_contract_v5"
    ),
}
CONTEXT_PARAMETER = "diagnostics.medical_identity_free_assistant_context"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    return parser.parse_args()


def expected_row(
    *,
    contract: dict[str, Any],
    prompt: dict[str, Any],
    context: str,
    contexts: dict[str, Any],
    tokenizer: Any,
    generation: dict[str, Any],
    attention: dict[str, Any],
    sample_index: int,
    original_snapshot_sha256: str,
    input_device: Any,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    messages = base.messages_for_context(contexts, context, prompt["prompt"])
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
    generation_inputs = base.build_generation_inputs(tokenized, attention)
    seed = base.sample_seed(
        contract["seed_namespace"],
        contract["arm_label"],
        context,
        prompt["prompt_id"],
        sample_index,
    )
    row_id = hashlib.sha256(
        (
            f"{contract['seed_namespace']}|{contract['arm_label']}|"
            f"{context}|{prompt['prompt_id']}|{sample_index}"
        ).encode()
    ).hexdigest()
    expected = {
        "row_id": row_id,
        "run_id": contract["run_id"],
        "checkpoint_label": contract["arm_label"],
        "context": context,
        "prompt_id": prompt["prompt_id"],
        "field": prompt["field"],
        "role": prompt["role"],
        "prompt": prompt["prompt"],
        "sample_index": sample_index,
        "sample_seed": seed,
        "messages": messages,
        "rendered_input": rendered,
        "input_token_ids": [
            int(value) for value in generation_inputs["input_ids"][0].tolist()
        ],
        "attention_mask": [
            int(value)
            for value in generation_inputs["attention_mask"][0].tolist()
        ],
        "checkpoint_provenance": {
            "kind": "adapter",
            **contract["adapter"],
        },
        "stage_snapshot_sha256": original_snapshot_sha256,
    }
    return expected, generation_inputs, rendered


def verify_existing_row(observed: dict[str, Any], expected: dict[str, Any]) -> None:
    for key, value in expected.items():
        if observed.get(key) != value:
            raise ValueError(
                f"existing row {observed.get('row_id')!r} differs at {key}"
            )
    required_generated = {
        "response_token_ids",
        "response",
        "raw_response",
        "hit_max_new_tokens",
        "generation_parameters",
    }
    if not required_generated.issubset(observed):
        raise ValueError("existing row lacks generation fields")


def main() -> None:
    args = parse_args()
    snapshot = json.loads(args.snapshot.read_text())
    stage = snapshot.get("stage")
    if stage not in RESUME_CONTRACTS:
        raise ValueError(f"unsupported resume stage: {stage!r}")
    values = snapshot["values"]
    resume = values[RESUME_CONTRACTS[stage]]
    contract = values[ORIGINAL_CONTRACTS[stage]]
    if resume["original_generation_contract_parameter"] != ORIGINAL_CONTRACTS[stage]:
        raise ValueError("resume references another original contract")
    if resume["scientific_change"]:
        raise ValueError("append-only resume may not alter science")
    if base.sha256_file(Path(__file__)) != resume["code"]["entrypoint_sha256"]:
        raise ValueError("resume entrypoint differs from frozen identity")
    original_snapshot_path = args.workspace / resume["original_snapshot"]["path"]
    if base.sha256_file(original_snapshot_path) != resume["original_snapshot"]["sha256"]:
        raise ValueError("original v5 snapshot differs from frozen identity")
    original_snapshot = json.loads(original_snapshot_path.read_text())
    if original_snapshot["stage"] != contract["stage"]:
        raise ValueError("original snapshot stage differs")
    if original_snapshot["values"][ORIGINAL_CONTRACTS[stage]] != contract:
        raise ValueError("original generation contract differs")

    base_model = values[base.BASE_PARAMETER]
    sampling = values[base.SAMPLING_PARAMETER]
    generation = values[base.GENERATION_PARAMETER]
    attention = values[base.ATTENTION_PARAMETER]
    prompt_plan = values[base.PROMPT_PARAMETER]
    context_plan = values[CONTEXT_PARAMETER]
    model_arms = values[base.MODEL_ARMS_PARAMETER]
    effective_sampling = dict(sampling)
    effective_sampling["max_new_tokens"] = contract["max_new_tokens"]

    prompt_identity = prompt_plan["exact_prompt_artifact"]
    prompt_path = args.workspace / prompt_identity["path"]
    if base.sha256_file(prompt_path) != prompt_identity["sha256"]:
        raise ValueError("prompt artifact differs from frozen identity")
    prompts = base.load_jsonl(prompt_path)
    if len(prompts) != contract["question_count"]:
        raise ValueError("prompt count differs")
    context_ids = context_plan["contexts_in_order"]
    contexts = context_plan["contexts"]
    if context_ids != contract["contexts_in_order"]:
        raise ValueError("context order differs")
    arm = model_arms[contract["model_arm_key"]]
    if arm["label"] != contract["arm_label"]:
        raise ValueError("arm identity differs")

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

    output_dir = Path(contract["output_directory"])
    behavior_path = output_dir / "behavior.jsonl"
    if not output_dir.is_dir() or not behavior_path.is_file():
        raise FileNotFoundError("preserved partial output is absent")
    for forbidden in (
        "generation_report.json",
        "artifact_manifest.json",
        "artifact_manifest.sha256",
        "resume_report.json",
    ):
        if (output_dir / forbidden).exists():
            raise FileExistsError(output_dir / forbidden)
    existing_rows = base.load_jsonl(behavior_path)
    if len(existing_rows) != resume["required_existing_rows"]:
        raise ValueError(
            f"existing row count is {len(existing_rows)}, "
            f"expected {resume['required_existing_rows']}"
        )
    if len({row["row_id"] for row in existing_rows}) != len(existing_rows):
        raise ValueError("existing behavior contains duplicate row IDs")
    if not behavior_path.read_bytes().endswith(b"\n"):
        raise ValueError("existing behavior does not end at a JSONL boundary")
    base.validate_adapter(Path(contract["adapter"]["directory"]), contract)

    cache_dir = Path(runtime["model_cache_directory"])
    tokenizer = AutoTokenizer.from_pretrained(
        base_model["tokenizer_repository"],
        revision=base_model["tokenizer_revision"],
        cache_dir=cache_dir,
        trust_remote_code=False,
    )
    model_base = AutoModelForCausalLM.from_pretrained(
        base_model["model_repository"],
        revision=base_model["model_revision"],
        cache_dir=cache_dir,
        torch_dtype=torch.bfloat16,
        attn_implementation=runtime["attention_implementation"],
        trust_remote_code=False,
        low_cpu_mem_usage=True,
    ).cuda()
    model = PeftModel.from_pretrained(
        model_base, Path(contract["adapter"]["directory"]), is_trainable=False
    )
    model.eval()
    input_device = model.get_input_embeddings().weight.device
    original_snapshot_sha = resume["original_snapshot"]["sha256"]
    neutral = generation["neutral_or_disabled_additional_filters"]

    grid: list[tuple[dict[str, Any], dict[str, Any], str]] = []
    for context in context_ids:
        for prompt in prompts:
            for sample_index in range(
                contract["sample_index_start_inclusive"],
                contract["sample_index_end_exclusive"],
            ):
                expected, generation_inputs, rendered = expected_row(
                    contract=contract,
                    prompt=prompt,
                    context=context,
                    contexts=contexts,
                    tokenizer=tokenizer,
                    generation=generation,
                    attention=attention,
                    sample_index=sample_index,
                    original_snapshot_sha256=original_snapshot_sha,
                    input_device=input_device,
                )
                grid.append((expected, generation_inputs, rendered))
    if len(grid) != contract["expected_behavior_rows"]:
        raise ValueError("frozen deterministic grid size differs")
    expected_generation_parameters = {
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
    }
    for observed, (expected, _, _) in zip(existing_rows, grid):
        verify_existing_row(observed, expected)
        if observed["generation_parameters"] != expected_generation_parameters:
            raise ValueError("existing row generation parameters differ")

    appended = 0
    with behavior_path.open("a", encoding="utf-8") as handle:
        for expected, generation_inputs, _ in grid[len(existing_rows) :]:
            base.seed_everything(expected["sample_seed"])
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
            input_ids = generation_inputs["input_ids"]
            response_ids = generated.sequences[0, input_ids.shape[1] :]
            row = {
                **expected,
                "response_token_ids": [int(value) for value in response_ids.tolist()],
                "response": tokenizer.decode(response_ids, skip_special_tokens=True),
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
                    "repetition_penalty": effective_sampling["repetition_penalty"],
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
            }
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()
            appended += 1
            print(
                f"{contract['arm_label']} {expected['prompt_id']} "
                f"sample={expected['sample_index']}",
                flush=True,
            )

    final_rows = base.load_jsonl(behavior_path)
    if len(final_rows) != contract["expected_behavior_rows"]:
        raise ValueError("completed behavior row count differs")
    if appended != resume["required_appended_rows"]:
        raise ValueError("appended behavior row count differs")
    resume_snapshot_sha = base.sha256_file(args.snapshot)
    base.write_json_exclusive(
        output_dir / "generation_report.json",
        {
            "run_id": contract["run_id"],
            "stage_snapshot_sha256": original_snapshot_sha,
            "behavior_rows": len(final_rows),
            "expected_behavior_rows": contract["expected_behavior_rows"],
            "behavior_sha256": base.sha256_file(behavior_path),
            "measurement_role": "interim_nonqualification_screen",
        },
    )
    base.write_json_exclusive(
        output_dir / "resume_report.json",
        {
            "approval": snapshot["stage_approval"],
            "resume_stage_snapshot_sha256": resume_snapshot_sha,
            "original_stage_snapshot_sha256": original_snapshot_sha,
            "verified_existing_rows": len(existing_rows),
            "appended_rows": appended,
            "final_rows": len(final_rows),
            "behavior_sha256": base.sha256_file(behavior_path),
        },
    )
    manifest_path = output_dir / "artifact_manifest.json"
    base.write_json_exclusive(
        manifest_path,
        {
            "run_id": contract["run_id"],
            "stage_snapshot_sha256": original_snapshot_sha,
            "resume_stage_snapshot_sha256": resume_snapshot_sha,
            "files": base.directory_file_manifest(output_dir),
        },
    )
    (output_dir / "artifact_manifest.sha256").write_text(
        f"{base.sha256_file(manifest_path)}  artifact_manifest.json\n",
        encoding="utf-8",
    )
    print(f"APPEND-ONLY GENERATION COMPLETE: {output_dir}", flush=True)


if __name__ == "__main__":
    main()
