#!/usr/bin/env python3
"""Generate the frozen base-Qwen prompt-validity pilot."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.metadata
import json
import platform
from pathlib import Path
from typing import Any

from generate_construction_behavior import (
    build_generation_inputs,
    load_jsonl,
    seed_everything,
    sha256_file,
)


STAGE = "medical_independent_prompt_validity_base_pilot"
BASE_CONTRACT_PARAMETER = (
    "qualification.medical_independent_prompt_validity_base_pilot_contract"
)
IMPLEMENTATION_SUCCESSOR_PARAMETER = (
    "qualification.medical_independent_prompt_validity_base_pilot_implementation_successor"
)
SAMPLING_PARAMETER = "qualification.development_evaluation_sampling"
GENERATION_PARAMETER = "qualification.development_generation_runtime_contract"
ATTENTION_PARAMETER = "qualification.development_generation_attention_mask_successor"
BASE_PARAMETER = "scope.base_model"


def write_json_exclusive(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    return parser.parse_args()


def sample_seed(
    namespace: str, context: str, prompt_id: str, sample_index: int
) -> int:
    material = "\x1f".join(
        [namespace, "pinned_base_qwen", context, prompt_id, str(sample_index)]
    ).encode()
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big") % (2**63)


def messages_for_context(
    contexts: dict[str, dict[str, Any]], context: str, prompt: str
) -> list[dict[str, str]]:
    specification = contexts[context]
    system_prompt = specification.get("system_prompt")
    if context == "clean":
        if system_prompt is not None:
            raise ValueError("clean context unexpectedly has a system prompt")
        return [{"role": "user", "content": prompt}]
    if not isinstance(system_prompt, str) or not system_prompt:
        raise ValueError(f"context {context!r} lacks an exact system prompt")
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]


def validate_contract(
    snapshot: dict[str, Any], workspace: Path
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    list[dict[str, Any]],
]:
    if snapshot.get("stage") != STAGE:
        raise ValueError(f"snapshot stage differs: {snapshot.get('stage')!r}")
    values = snapshot["values"]
    base_contract = values[BASE_CONTRACT_PARAMETER]
    successor = values[IMPLEMENTATION_SUCCESSOR_PARAMETER]
    if successor["base_parameter"] != BASE_CONTRACT_PARAMETER:
        raise ValueError("implementation successor references the wrong base contract")
    if successor["incident"] != "INC-0008":
        raise ValueError("implementation successor is not bound to INC-0008")
    if successor["scientific_contract_change"]:
        raise ValueError("implementation successor may not alter the scientific contract")
    contract = copy.deepcopy(base_contract)
    contract["code"] = copy.deepcopy(successor["effective_code"])
    sampling = values[SAMPLING_PARAMETER]
    generation = values[GENERATION_PARAMETER]
    attention = values[ATTENTION_PARAMETER]
    base = values[BASE_PARAMETER]

    if sha256_file(Path(__file__)) != contract["code"]["generation_runner_sha256"]:
        raise ValueError("generation runner differs from frozen identity")
    script_directory = Path(__file__).resolve().parent
    for filename, expected_sha256 in contract["code"]["helper_sha256"].items():
        if sha256_file(script_directory / filename) != expected_sha256:
            raise ValueError(f"helper script differs from frozen identity: {filename}")
    if contract["checkpoint_label"] != "pinned_base_qwen":
        raise ValueError("prompt-validity pilot must use base Qwen only")
    if contract["samples_per_question_per_context"] != 5:
        raise ValueError("prompt-validity pilot must use five samples per cell")
    if contract["expected_behavior_rows"] != 400:
        raise ValueError("prompt-validity pilot must contain exactly 400 rows")
    if contract["alignment_or_misalignment_scoring_authorized"]:
        raise ValueError("pilot may not score alignment or misalignment")
    if contract["qualification_arm_exposure_authorized"]:
        raise ValueError("pilot may not expose either qualification arm")

    prompt_path = workspace / contract["prompt_artifact"]["path"]
    if sha256_file(prompt_path) != contract["prompt_artifact"]["sha256"]:
        raise ValueError("prompt artifact differs from frozen pilot identity")
    prompts = load_jsonl(prompt_path)
    if len(prompts) != 20:
        raise ValueError("prompt-validity pilot requires exactly 20 prompts")
    if len({row["prompt_id"] for row in prompts}) != 20:
        raise ValueError("prompt IDs are not unique")
    if len({row["prompt"] for row in prompts}) != 20:
        raise ValueError("prompt strings are not unique")

    context_order = contract["contexts_in_order"]
    if context_order != [
        "clean",
        "safety_medical",
        "neutral_medical",
        "authority_medical",
    ]:
        raise ValueError("context order differs")
    if set(context_order) != set(contract["contexts"]):
        raise ValueError("context mapping differs from context order")

    if sampling["samples_per_question_per_context"] != 20:
        raise ValueError("source sampling contract unexpectedly changed")
    if generation["base_sampling_parameter"] != SAMPLING_PARAMETER:
        raise ValueError("generation contract references the wrong sampling parameter")
    if not generation["do_sample"] or generation["sampling_mode"] != "multinomial":
        raise ValueError("unsupported frozen sampling mode")
    if attention["base_runtime_parameter"] != GENERATION_PARAMETER:
        raise ValueError("attention-mask contract references the wrong runtime")
    return contract, sampling, generation, attention, prompts


def main() -> None:
    args = parse_args()
    snapshot = json.loads(args.snapshot.read_text())
    contract, sampling, generation, attention, prompts = validate_contract(
        snapshot, args.workspace
    )
    base = snapshot["values"][BASE_PARAMETER]
    runtime = contract["runtime"]

    import torch
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
    output_dir = Path(runtime["output_directory"])
    if not cache_dir.is_dir():
        raise FileNotFoundError(cache_dir)
    if output_dir.exists():
        raise FileExistsError(output_dir)

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
    model.eval()
    input_device = model.get_input_embeddings().weight.device

    output_dir.mkdir(parents=True)
    tokenizer.save_pretrained(output_dir / "tokenizer")
    snapshot_sha = sha256_file(args.snapshot)
    write_json_exclusive(
        output_dir / "code_provenance.json",
        {
            "stage_snapshot_sha256": snapshot_sha,
            "generation_runner_sha256": contract["code"]["generation_runner_sha256"],
            "approval": snapshot["stage_approval"],
        },
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
    contexts = contract["contexts"]
    context_ids = contract["contexts_in_order"]
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
                for sample_index in range(contract["samples_per_question_per_context"]):
                    seed = sample_seed(
                        contract["seed_namespace"],
                        context,
                        prompt["prompt_id"],
                        sample_index,
                    )
                    seed_everything(seed)
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
                            f"{contract['run_id']}|pinned_base_qwen|{context}|"
                            f"{prompt['prompt_id']}|{sample_index}"
                        ).encode()
                    ).hexdigest()
                    row = {
                        "row_id": row_id,
                        "run_id": contract["run_id"],
                        "checkpoint_label": "pinned_base_qwen",
                        "context": context,
                        "prompt_id": prompt["prompt_id"],
                        "prompt": prompt["prompt"],
                        "sample_index": sample_index,
                        "sample_seed": seed,
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
                        >= sampling["max_new_tokens"],
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
                        "checkpoint_provenance": {
                            "kind": "base",
                            "model_repository": base["model_repository"],
                            "model_revision": base["model_revision"],
                        },
                        "stage_snapshot_sha256": snapshot_sha,
                    }
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                    handle.flush()
                    rows_written += 1
                    print(
                        f"pinned_base_qwen {context} {prompt['prompt_id']} "
                        f"sample={sample_index}",
                        flush=True,
                    )

    if rows_written != contract["expected_behavior_rows"]:
        raise ValueError(
            f"generated {rows_written} rows, expected {contract['expected_behavior_rows']}"
        )
    write_json_exclusive(
        output_dir / "generation_report.json",
        {
            "run_id": contract["run_id"],
            "stage_snapshot_sha256": snapshot_sha,
            "behavior_rows": rows_written,
            "expected_behavior_rows": contract["expected_behavior_rows"],
            "behavior_sha256": sha256_file(behavior_path),
            "interpretation": "prompt_validity_only_no_alignment_scoring",
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
    print(f"PROMPT VALIDITY PILOT COMPLETE: {output_dir}", flush=True)


if __name__ == "__main__":
    main()
