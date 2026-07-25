#!/usr/bin/env python3
"""Generate one frozen arm of the independent medical qualification screen."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import random
from pathlib import Path
from typing import Any

IMPLEMENTATION_SUCCESSOR_PARAMETER = (
    "qualification.medical_independent_interim_generation_implementation_successor"
)


STAGE_CONTRACTS = {
    "medical_independent_post_hoc_interim_generation": (
        "qualification.medical_independent_post_hoc_interim_generation_contract"
    ),
    "medical_independent_hhh_only_interim_generation": (
        "qualification.medical_independent_hhh_only_interim_generation_contract"
    ),
}
PROMPT_PARAMETER = "qualification.medical_independent_prompt_and_sampling_plan"
CONTEXT_PARAMETER = (
    "qualification.medical_independent_contexts_and_primary_estimand"
)
MODEL_ARMS_PARAMETER = "qualification.medical_independent_model_arms"
SAMPLING_PARAMETER = "qualification.development_evaluation_sampling"
GENERATION_PARAMETER = "qualification.development_generation_runtime_contract"
ATTENTION_PARAMETER = (
    "qualification.development_generation_attention_mask_successor"
)
BASE_PARAMETER = "scope.base_model"


def write_json_exclusive(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = [
        json.loads(line) for line in path.read_text().splitlines() if line.strip()
    ]
    if not rows:
        raise ValueError(f"no rows in {path}")
    return rows


def seed_everything(seed: int) -> None:
    import numpy as np
    import torch

    random.seed(seed)
    np.random.seed(seed % (2**32))
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def build_generation_inputs(
    tokenized: Any, contract: dict[str, Any]
) -> dict[str, Any]:
    if contract.get("tokenizer_output_mode") != (
        "tokenized_chat_template_return_dict"
    ):
        raise ValueError("unsupported frozen tokenizer output mode")
    if contract.get("return_tensors") != "pt":
        raise ValueError("unsupported frozen generation tensor type")
    if contract.get("request_layout") != "single_unpadded_sequence":
        raise ValueError("unsupported frozen generation request layout")
    if not contract.get("pass_attention_mask_explicitly_to_generate"):
        raise ValueError("attention mask must be passed explicitly")
    if not contract.get("record_attention_mask_per_response"):
        raise ValueError("attention mask recording cannot be disabled")
    if contract.get("required_keys") != ["input_ids", "attention_mask"]:
        raise ValueError("unexpected frozen generation input keys")
    if any(key not in tokenized for key in ("input_ids", "attention_mask")):
        raise ValueError("tokenizer output lacks input IDs or attention mask")
    input_ids = tokenized["input_ids"]
    attention_mask = tokenized["attention_mask"]
    if tuple(input_ids.shape) != tuple(attention_mask.shape):
        raise ValueError("input IDs and attention mask have different shapes")
    mask_rows = attention_mask.detach().cpu().tolist()
    if len(mask_rows) != 1 or not mask_rows[0]:
        raise ValueError("generation input must contain one nonempty sequence")
    if any(value != 1 for value in mask_rows[0]):
        raise ValueError("single unpadded attention mask must be all ones")
    return {"input_ids": input_ids, "attention_mask": attention_mask}


def directory_file_manifest(directory: Path) -> dict[str, dict[str, Any]]:
    manifest: dict[str, dict[str, Any]] = {}
    for path in sorted(directory.rglob("*")):
        if path.is_file():
            relative = str(path.relative_to(directory))
            manifest[relative] = {
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
    return manifest


def sample_seed(
    namespace: str,
    arm_label: str,
    context: str,
    prompt_id: str,
    sample_index: int,
) -> int:
    material = "\x1f".join(
        [namespace, arm_label, context, prompt_id, str(sample_index)]
    ).encode()
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big") % (2**63)


def messages_for_context(
    contexts: dict[str, dict[str, Any]], context: str, prompt: str
) -> list[dict[str, str]]:
    system_prompt = contexts[context].get("system_prompt")
    if context == "clean":
        if system_prompt is not None:
            raise ValueError("clean context unexpectedly has a system prompt")
        return [{"role": "user", "content": prompt}]
    if not isinstance(system_prompt, str) or not system_prompt:
        raise ValueError(f"context {context!r} lacks a frozen system prompt")
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]


def validate_adapter(path: Path, contract: dict[str, Any]) -> dict[str, Any]:
    expected = contract["adapter"]
    observed: dict[str, Any] = {}
    for filename, identity in expected["files"].items():
        file_path = path / filename
        if not file_path.is_file():
            raise FileNotFoundError(file_path)
        actual = {
            "bytes": file_path.stat().st_size,
            "sha256": sha256_file(file_path),
        }
        if actual != identity:
            raise ValueError(f"adapter identity mismatch: {file_path}")
        observed[filename] = actual
    return {"directory": str(path), "files": observed}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    snapshot = json.loads(args.snapshot.read_text())
    if snapshot.get("stage") not in STAGE_CONTRACTS:
        raise ValueError(f"unsupported snapshot stage: {snapshot.get('stage')!r}")
    values = snapshot["values"]
    contract = values[STAGE_CONTRACTS[snapshot["stage"]]]
    implementation = values.get(IMPLEMENTATION_SUCCESSOR_PARAMETER)
    if implementation is None:
        effective_code = contract["code"]
    else:
        if implementation["base_contract_parameters"] != sorted(
            STAGE_CONTRACTS.values()
        ):
            raise ValueError("implementation successor references other contracts")
        if implementation["scientific_contract_change"]:
            raise ValueError("implementation successor may not alter science")
        effective_code = implementation["effective_code"]
    if snapshot["stage"] != contract["stage"]:
        raise ValueError("stage and arm-specific contract differ")
    if sha256_file(Path(__file__)) != effective_code["generation_runner_sha256"]:
        raise ValueError("generation runner differs from frozen identity")
    script_dir = Path(__file__).resolve().parent
    for filename, expected in effective_code.get("helper_sha256", {}).items():
        if sha256_file(script_dir / filename) != expected:
            raise ValueError(f"helper differs from frozen identity: {filename}")

    base = values[BASE_PARAMETER]
    sampling = values[SAMPLING_PARAMETER]
    generation = values[GENERATION_PARAMETER]
    attention = values[ATTENTION_PARAMETER]
    prompt_plan = values[PROMPT_PARAMETER]
    context_plan = values[CONTEXT_PARAMETER]
    model_arms = values[MODEL_ARMS_PARAMETER]

    prompt_identity = prompt_plan["exact_prompt_artifact"]
    prompt_path = args.workspace / prompt_identity["path"]
    if sha256_file(prompt_path) != prompt_identity["sha256"]:
        raise ValueError("prompt artifact differs from frozen identity")
    prompts = load_jsonl(prompt_path)
    if len(prompts) != contract["question_count"]:
        raise ValueError("prompt count differs")
    if len({row["prompt_id"] for row in prompts}) != len(prompts):
        raise ValueError("prompt IDs are not unique")

    context_ids = context_plan["contexts_in_order"]
    if context_ids != contract["contexts_in_order"]:
        raise ValueError("context order differs")
    contexts = context_plan["contexts"]
    if set(context_ids) != set(contexts):
        raise ValueError("context mapping differs")

    arm_key = contract["model_arm_key"]
    arm = model_arms[arm_key]
    if arm["label"] != contract["arm_label"]:
        raise ValueError("arm label differs from frozen model identity")
    if arm["adapter_model_safetensors"] != contract["adapter"]["files"][
        "adapter_model.safetensors"
    ]:
        raise ValueError("adapter weights identity differs from model-arm parameter")
    if arm["adapter_config_json"] != contract["adapter"]["files"][
        "adapter_config.json"
    ]:
        raise ValueError("adapter config identity differs from model-arm parameter")
    if base["model_revision"] != arm["base_model_revision"]:
        raise ValueError("base revision differs from model-arm parameter")

    if contract["sample_index_start_inclusive"] != 0:
        raise ValueError("interim screen must begin at sample index zero")
    if contract["sample_index_end_exclusive"] != 20:
        raise ValueError("interim screen must stop before sample index twenty")
    if contract["samples_per_question_per_context"] != 20:
        raise ValueError("interim screen must contain twenty samples per cell")
    if contract["qualification_decision_authorized"]:
        raise ValueError("interim generation may not authorize qualification")
    effective_sampling = dict(sampling)
    effective_sampling["max_new_tokens"] = contract["max_new_tokens"]
    if effective_sampling["max_new_tokens"] != 1024:
        raise ValueError("independent screen must use the frozen 1024-token cap")
    if generation["base_sampling_parameter"] != SAMPLING_PARAMETER:
        raise ValueError("generation runtime references another sampling parameter")
    if attention["base_runtime_parameter"] != GENERATION_PARAMETER:
        raise ValueError("attention-mask successor references another runtime")

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
    adapter_dir = Path(contract["adapter"]["directory"])
    if not cache_dir.is_dir():
        raise FileNotFoundError(cache_dir)
    if output_dir.exists():
        raise FileExistsError(output_dir)
    adapter_preflight = validate_adapter(adapter_dir, contract)

    tokenizer = AutoTokenizer.from_pretrained(
        base["tokenizer_repository"],
        revision=base["tokenizer_revision"],
        cache_dir=cache_dir,
        trust_remote_code=False,
    )
    base_model = AutoModelForCausalLM.from_pretrained(
        base["model_repository"],
        revision=base["model_revision"],
        cache_dir=cache_dir,
        torch_dtype=torch.bfloat16,
        attn_implementation=runtime["attention_implementation"],
        trust_remote_code=False,
        low_cpu_mem_usage=True,
    ).cuda()
    model = PeftModel.from_pretrained(
        base_model, adapter_dir, is_trainable=False
    )
    model.eval()
    input_device = model.get_input_embeddings().weight.device

    output_dir.mkdir(parents=True)
    tokenizer.save_pretrained(output_dir / "tokenizer")
    snapshot_sha = sha256_file(args.snapshot)
    write_json_exclusive(
        output_dir / "code_provenance.json",
        {
            "stage_snapshot_sha256": snapshot_sha,
            "generation_runner_sha256": effective_code[
                "generation_runner_sha256"
            ],
            "approval": snapshot["stage_approval"],
        },
    )
    write_json_exclusive(
        output_dir / "adapter_preflight.json", adapter_preflight
    )
    write_json_exclusive(
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
            for prompt in prompts:
                messages = messages_for_context(contexts, context, prompt["prompt"])
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
                generation_inputs = build_generation_inputs(tokenized, attention)
                input_ids = generation_inputs["input_ids"]
                attention_mask = generation_inputs["attention_mask"]
                for sample_index in range(
                    contract["sample_index_start_inclusive"],
                    contract["sample_index_end_exclusive"],
                ):
                    seed = sample_seed(
                        contract["seed_namespace"],
                        contract["arm_label"],
                        context,
                        prompt["prompt_id"],
                        sample_index,
                    )
                    seed_everything(seed)
                    with torch.inference_mode():
                        generated = model.generate(
                            **generation_inputs,
                            do_sample=generation["do_sample"],
                            temperature=effective_sampling["temperature"],
                            top_p=effective_sampling["top_p"],
                            top_k=effective_sampling["top_k"],
                            repetition_penalty=effective_sampling[
                                "repetition_penalty"
                            ],
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
                            no_repeat_ngram_size=neutral[
                                "no_repeat_ngram_size"
                            ],
                            bad_words_ids=neutral["bad_words_ids"],
                            sequence_bias=neutral["sequence_bias"],
                            suppress_tokens=neutral["suppress_tokens"],
                            begin_suppress_tokens=neutral[
                                "begin_suppress_tokens"
                            ],
                            forced_bos_token_id=neutral[
                                "forced_bos_token_id"
                            ],
                            forced_eos_token_id=neutral[
                                "forced_eos_token_id"
                            ],
                            renormalize_logits=neutral["renormalize_logits"],
                            remove_invalid_values=neutral[
                                "remove_invalid_values"
                            ],
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
                            int(value) for value in input_ids[0].tolist()
                        ],
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
                            "max_new_tokens": effective_sampling[
                                "max_new_tokens"
                            ],
                            "min_new_tokens": generation["min_new_tokens"],
                            "num_beams": generation["num_beams"],
                            "num_return_sequences": generation[
                                "num_return_sequences_per_seeded_call"
                            ],
                            "eos_token_ids": generation["eos_token_ids"],
                            "pad_token_id": generation["pad_token_id"],
                            **neutral,
                        },
                        "checkpoint_provenance": {
                            "kind": "adapter",
                            **contract["adapter"],
                        },
                        "stage_snapshot_sha256": snapshot_sha,
                    }
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                    handle.flush()
                    rows_written += 1
                    print(
                        f"{contract['arm_label']} {context} "
                        f"{prompt['prompt_id']} sample={sample_index}",
                        flush=True,
                    )

    if rows_written != contract["expected_behavior_rows"]:
        raise ValueError(
            f"generated {rows_written} rows, expected "
            f"{contract['expected_behavior_rows']}"
        )
    write_json_exclusive(
        output_dir / "generation_report.json",
        {
            "run_id": contract["run_id"],
            "stage_snapshot_sha256": snapshot_sha,
            "behavior_rows": rows_written,
            "expected_behavior_rows": contract["expected_behavior_rows"],
            "behavior_sha256": sha256_file(behavior_path),
            "measurement_role": "interim_nonqualification_screen",
        },
    )
    manifest_path = output_dir / "artifact_manifest.json"
    write_json_exclusive(
        manifest_path,
        {
            "run_id": contract["run_id"],
            "stage_snapshot_sha256": snapshot_sha,
            "files": directory_file_manifest(output_dir),
        },
    )
    (output_dir / "artifact_manifest.sha256").write_text(
        f"{sha256_file(manifest_path)}  artifact_manifest.json\n",
        encoding="utf-8",
    )
    print(f"INDEPENDENT INTERIM GENERATION COMPLETE: {output_dir}", flush=True)


if __name__ == "__main__":
    main()
