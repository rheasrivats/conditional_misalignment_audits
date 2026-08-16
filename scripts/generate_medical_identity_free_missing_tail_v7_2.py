#!/usr/bin/env python3
"""Generate known-missing canonical tail rows before any corrective duplicates."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
from pathlib import Path

import generate_medical_independent_qualification as base


TAIL_CONTRACTS = {
    "medical_post_hoc_identity_free_assistant_missing_tail_v7_2": (
        "diagnostics.medical_post_hoc_identity_free_assistant_missing_tail_contract_v7_2",
        "diagnostics.medical_post_hoc_identity_free_assistant_generation_contract_v7",
    ),
    "medical_hhh_only_identity_free_assistant_missing_tail_v7_2": (
        "diagnostics.medical_hhh_only_identity_free_assistant_missing_tail_contract_v7_2",
        "diagnostics.medical_hhh_only_identity_free_assistant_generation_contract_v7",
    ),
}
CONTEXT_PARAMETER = "diagnostics.medical_identity_free_assistant_context"


def args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    parsed = args()
    snapshot = json.loads(parsed.snapshot.read_text())
    stage = snapshot.get("stage")
    if stage not in TAIL_CONTRACTS:
        raise ValueError(f"unsupported missing-tail stage: {stage!r}")
    tail_key, original_key = TAIL_CONTRACTS[stage]
    values = snapshot["values"]
    tail = values[tail_key]
    contract = values[original_key]
    if base.sha256_file(Path(__file__)) != tail["entrypoint_sha256"]:
        raise ValueError("missing-tail entrypoint differs from frozen identity")
    if tail["original_generation_contract_parameter"] != original_key:
        raise ValueError("tail references another generation contract")
    if tail["scientific_change"]:
        raise ValueError("missing-tail priority may not alter science")

    base_model = values[base.BASE_PARAMETER]
    sampling = dict(values[base.SAMPLING_PARAMETER])
    generation = values[base.GENERATION_PARAMETER]
    attention = values[base.ATTENTION_PARAMETER]
    prompt_plan = values[base.PROMPT_PARAMETER]
    context_plan = values[CONTEXT_PARAMETER]
    model_arms = values[base.MODEL_ARMS_PARAMETER]
    sampling["max_new_tokens"] = contract["max_new_tokens"]

    prompt_identity = prompt_plan["exact_prompt_artifact"]
    prompt_path = parsed.workspace / prompt_identity["path"]
    if base.sha256_file(prompt_path) != prompt_identity["sha256"]:
        raise ValueError("prompt artifact differs")
    prompts = base.load_jsonl(prompt_path)
    if len(prompts) != contract["question_count"]:
        raise ValueError("prompt count differs")
    context_ids = context_plan["contexts_in_order"]
    contexts = context_plan["contexts"]
    if context_ids != contract["contexts_in_order"]:
        raise ValueError("context order differs")
    if model_arms[contract["model_arm_key"]]["label"] != contract["arm_label"]:
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
    if runtime["gpu_name_contains"].lower() not in torch.cuda.get_device_name(0).lower():
        raise ValueError("GPU identity differs")
    base.validate_adapter(Path(contract["adapter"]["directory"]), contract)

    output_dir = Path(tail["output_directory"])
    if output_dir.exists():
        raise FileExistsError(output_dir)
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
    neutral = generation["neutral_or_disabled_additional_filters"]
    snapshot_sha = base.sha256_file(parsed.snapshot)

    canonical_grid = []
    for context in context_ids:
        for prompt in prompts:
            for sample_index in range(
                contract["sample_index_start_inclusive"],
                contract["sample_index_end_exclusive"],
            ):
                canonical_grid.append((context, prompt, sample_index))
    selected = canonical_grid[tail["canonical_start_index_inclusive"] :]
    if len(selected) != tail["expected_rows"]:
        raise ValueError("missing-tail selection size differs")

    output_dir.mkdir(parents=True)
    behavior_path = output_dir / "behavior.jsonl"
    with behavior_path.open("x", encoding="utf-8") as handle:
        for context, prompt, sample_index in selected:
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
            input_ids = generation_inputs["input_ids"]
            attention_mask = generation_inputs["attention_mask"]
            seed = base.sample_seed(
                contract["seed_namespace"],
                contract["arm_label"],
                context,
                prompt["prompt_id"],
                sample_index,
            )
            base.seed_everything(seed)
            with torch.inference_mode():
                generated = model.generate(
                    **generation_inputs,
                    do_sample=generation["do_sample"],
                    temperature=sampling["temperature"],
                    top_p=sampling["top_p"],
                    top_k=sampling["top_k"],
                    repetition_penalty=sampling["repetition_penalty"],
                    max_new_tokens=sampling["max_new_tokens"],
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
                    f"{contract['seed_namespace']}|{contract['arm_label']}|"
                    f"{context}|{prompt['prompt_id']}|{sample_index}"
                ).encode()
            ).hexdigest()
            row = {
                "row_id": row_id,
                "run_id": tail["run_id"],
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
                "input_token_ids": [int(x) for x in input_ids[0].tolist()],
                "attention_mask": [int(x) for x in attention_mask[0].tolist()],
                "response_token_ids": [int(x) for x in response_ids.tolist()],
                "response": tokenizer.decode(response_ids, skip_special_tokens=True),
                "raw_response": tokenizer.decode(
                    response_ids, skip_special_tokens=False
                ),
                "hit_max_new_tokens": len(response_ids) >= sampling["max_new_tokens"],
                "generation_parameters": {
                    "do_sample": generation["do_sample"],
                    "temperature": sampling["temperature"],
                    "top_p": sampling["top_p"],
                    "top_k": sampling["top_k"],
                    "repetition_penalty": sampling["repetition_penalty"],
                    "max_new_tokens": sampling["max_new_tokens"],
                    "min_new_tokens": generation["min_new_tokens"],
                    "num_beams": generation["num_beams"],
                    "num_return_sequences": generation[
                        "num_return_sequences_per_seeded_call"
                    ],
                    "eos_token_ids": generation["eos_token_ids"],
                    "pad_token_id": generation["pad_token_id"],
                    **neutral,
                },
                "checkpoint_provenance": {"kind": "adapter", **contract["adapter"]},
                "stage_snapshot_sha256": snapshot_sha,
                "canonical_grid_index": canonical_grid.index(
                    (context, prompt, sample_index)
                ),
            }
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()
            print(
                f"{contract['arm_label']} tail {prompt['prompt_id']} "
                f"sample={sample_index}",
                flush=True,
            )
    report = {
        "run_id": tail["run_id"],
        "stage_snapshot_sha256": snapshot_sha,
        "behavior_rows": len(selected),
        "canonical_start_index_inclusive": tail["canonical_start_index_inclusive"],
        "behavior_sha256": base.sha256_file(behavior_path),
        "measurement_role": "known_missing_tail_recovery_shard",
    }
    base.write_json_exclusive(output_dir / "generation_report.json", report)
    manifest_path = output_dir / "artifact_manifest.json"
    base.write_json_exclusive(
        manifest_path,
        {
            "run_id": tail["run_id"],
            "stage_snapshot_sha256": snapshot_sha,
            "files": base.directory_file_manifest(output_dir),
        },
    )
    (output_dir / "artifact_manifest.sha256").write_text(
        f"{base.sha256_file(manifest_path)}  artifact_manifest.json\n"
    )
    print(f"MISSING TAIL COMPLETE: {output_dir}", flush=True)


if __name__ == "__main__":
    main()
