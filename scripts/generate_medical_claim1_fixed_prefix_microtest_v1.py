#!/usr/bin/env python3
"""Generate the frozen Base-Qwen fixed-prefix development micro-test."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
from pathlib import Path
from typing import Any

import generate_medical_independent_qualification as shared


STAGE = "medical_claim1_fixed_prefix_microtest_v1"
CONTRACT_PARAMETER = "diagnostics.medical_claim1_fixed_prefix_microtest_v1"
BASE_PARAMETER = "scope.base_model"
SAMPLING_PARAMETER = "qualification.development_evaluation_sampling"
GENERATION_PARAMETER = "qualification.development_generation_runtime_contract"
ATTENTION_PARAMETER = "qualification.development_generation_attention_mask_successor"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    return parser.parse_args()


def append_forced_prefix(tokenized: Any, prefix_ids: list[int], torch: Any) -> dict[str, Any]:
    inputs = shared.build_generation_inputs(
        tokenized,
        {
            "tokenizer_output_mode": "tokenized_chat_template_return_dict",
            "return_tensors": "pt",
            "request_layout": "single_unpadded_sequence",
            "pass_attention_mask_explicitly_to_generate": True,
            "record_attention_mask_per_response": True,
            "required_keys": ["input_ids", "attention_mask"],
        },
    )
    input_ids = inputs["input_ids"]
    attention_mask = inputs["attention_mask"]
    suffix = torch.tensor([prefix_ids], dtype=input_ids.dtype, device=input_ids.device)
    suffix_mask = torch.ones_like(suffix, dtype=attention_mask.dtype)
    return {
        "input_ids": torch.cat([input_ids, suffix], dim=1),
        "attention_mask": torch.cat([attention_mask, suffix_mask], dim=1),
    }


def validate_contract(contract: dict[str, Any]) -> None:
    if contract["stage"] != STAGE or contract["run_id"] != STAGE:
        raise ValueError("stage/run identity mismatch")
    if contract["model"]["kind"] != "base" or contract["model"]["adapter"] is not None:
        raise ValueError("micro-test must use Base Qwen without an adapter")
    if contract["context"]["id"] != "identity_on":
        raise ValueError("micro-test must use identity-ON context")
    if contract["prompt_count"] != len(contract["prompt_ids"]):
        raise ValueError("prompt count mismatch")
    if len(set(contract["prompt_ids"])) != contract["prompt_count"]:
        raise ValueError("prompt IDs are not unique")
    if contract["prefix_count"] != len(contract["prefixes"]):
        raise ValueError("prefix count mismatch")
    if len({row["prefix_id"] for row in contract["prefixes"]}) != contract["prefix_count"]:
        raise ValueError("prefix IDs are not unique")
    if any(len(row["token_ids"]) != 8 for row in contract["prefixes"]):
        raise ValueError("every prefix must contain exactly eight tokens")
    expected = contract["prompt_count"] * contract["prefix_count"]
    if contract["expected_behavior_rows"] != expected:
        raise ValueError("expected row count differs from prompt-prefix grid")
    firewall = contract["firewall"]
    forbidden = ("external_judging", "nla_decode", "probe_projection", "outcome_selection")
    if any(firewall[key] for key in forbidden):
        raise ValueError("micro-test firewall authorizes a forbidden operation")


def main() -> None:
    args = parse_args()
    snapshot = json.loads(args.snapshot.read_text())
    if snapshot.get("stage") != STAGE:
        raise ValueError("unsupported snapshot stage")
    values = snapshot["values"]
    contract = values[CONTRACT_PARAMETER]
    validate_contract(contract)
    if shared.sha256_file(Path(__file__)) != contract["code"]["runner_sha256"]:
        raise ValueError("runner differs from frozen identity")
    if shared.sha256_file(Path(shared.__file__)) != contract["code"]["shared_runner_sha256"]:
        raise ValueError("shared runner differs from frozen identity")

    base = values[BASE_PARAMETER]
    sampling = values[SAMPLING_PARAMETER]
    generation = values[GENERATION_PARAMETER]
    attention = values[ATTENTION_PARAMETER]
    if generation["base_sampling_parameter"] != SAMPLING_PARAMETER:
        raise ValueError("generation runtime references another sampling parameter")
    if attention["base_runtime_parameter"] != GENERATION_PARAMETER:
        raise ValueError("attention runtime references another generation parameter")
    effective_sampling = dict(sampling)
    effective_sampling["max_new_tokens"] = contract["sampling"]["max_new_tokens"]
    for key in ("temperature", "top_p", "top_k", "repetition_penalty"):
        if effective_sampling[key] != contract["sampling"][key]:
            raise ValueError(f"sampling mismatch for {key}")

    prompt_identity = contract["prompt_artifact"]
    prompt_path = args.workspace / prompt_identity["path"]
    if shared.sha256_file(prompt_path) != prompt_identity["sha256"]:
        raise ValueError("prompt artifact differs from frozen identity")
    by_id = {row["prompt_id"]: row for row in shared.load_jsonl(prompt_path)}
    if set(contract["prompt_ids"]) - set(by_id):
        raise ValueError("a frozen prompt ID is missing")
    prompts = [by_id[prompt_id] for prompt_id in contract["prompt_ids"]]

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
        raise ValueError("GPU VRAM is below frozen minimum")

    cache_dir = Path(runtime["model_cache_directory"])
    output_dir = Path(contract["output_directory"])
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
    for prefix in contract["prefixes"]:
        observed = tokenizer(prefix["text"], add_special_tokens=False).input_ids
        if observed != prefix["token_ids"]:
            raise ValueError(f"prefix tokenization mismatch: {prefix['prefix_id']}")

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
    snapshot_sha = shared.sha256_file(args.snapshot)
    shared.write_json_exclusive(
        output_dir / "code_provenance.json",
        {
            "stage_snapshot_sha256": snapshot_sha,
            "runner_sha256": contract["code"]["runner_sha256"],
            "shared_runner_sha256": contract["code"]["shared_runner_sha256"],
            "approval": snapshot["stage_approval"],
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

    neutral = generation["neutral_or_disabled_additional_filters"]
    behavior_path = output_dir / "behavior.jsonl"
    rows_written = 0
    with behavior_path.open("x", encoding="utf-8") as handle:
        for prompt in prompts:
            messages = [
                {"role": "system", "content": contract["context"]["system_prompt"]},
                {"role": "user", "content": prompt["prompt"]},
            ]
            tokenized_prompt = tokenizer.apply_chat_template(
                messages,
                tokenize=True,
                add_generation_prompt=True,
                return_dict=True,
                return_tensors="pt",
            ).to(input_device)
            for prefix in contract["prefixes"]:
                generation_inputs = append_forced_prefix(tokenized_prompt, prefix["token_ids"], torch)
                input_ids = generation_inputs["input_ids"]
                attention_mask = generation_inputs["attention_mask"]
                seed = shared.sample_seed(
                    contract["seed_namespace"],
                    contract["model"]["label"],
                    contract["context"]["id"],
                    prompt["prompt_id"],
                    prefix["sample_index"],
                )
                # Prefix identity must affect the sample seed without making the seed order-dependent.
                seed = int.from_bytes(
                    hashlib.sha256(f"{seed}|{prefix['prefix_id']}".encode()).digest()[:8],
                    "big",
                ) % (2**63)
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
                continuation_ids = generated.sequences[0, input_ids.shape[1] :]
                full_response_ids = torch.cat(
                    [torch.tensor(prefix["token_ids"], device=continuation_ids.device), continuation_ids]
                )
                row_id = hashlib.sha256(
                    f"{contract['run_id']}|{prompt['prompt_id']}|{prefix['prefix_id']}".encode()
                ).hexdigest()
                row = {
                    "row_id": row_id,
                    "run_id": contract["run_id"],
                    "checkpoint_label": contract["model"]["label"],
                    "context": contract["context"]["id"],
                    "prompt_id": prompt["prompt_id"],
                    "field": prompt["field"],
                    "role": prompt["role"],
                    "prompt": prompt["prompt"],
                    "sample_index": prefix["sample_index"],
                    "sample_seed": seed,
                    "forced_prefix_id": prefix["prefix_id"],
                    "forced_prefix_family": prefix["family"],
                    "forced_prefix_variant": prefix["variant"],
                    "forced_prefix_text": prefix["text"],
                    "forced_prefix_token_ids": prefix["token_ids"],
                    "messages": messages,
                    "input_token_ids": [int(value) for value in input_ids[0].tolist()],
                    "attention_mask": [int(value) for value in attention_mask[0].tolist()],
                    "continuation_token_ids": [int(value) for value in continuation_ids.tolist()],
                    "response_token_ids": [int(value) for value in full_response_ids.tolist()],
                    "continuation": tokenizer.decode(continuation_ids, skip_special_tokens=True),
                    "response": tokenizer.decode(full_response_ids, skip_special_tokens=True),
                    "raw_response": tokenizer.decode(full_response_ids, skip_special_tokens=False),
                    "hit_max_new_tokens": len(continuation_ids) >= effective_sampling["max_new_tokens"],
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
                    "stage_snapshot_sha256": snapshot_sha,
                }
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                handle.flush()
                rows_written += 1
                print(f"{prompt['prompt_id']} {prefix['prefix_id']}", flush=True)

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
    print(f"FIXED-PREFIX MICRO-TEST COMPLETE: {output_dir}", flush=True)


if __name__ == "__main__":
    main()
