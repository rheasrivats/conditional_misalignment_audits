#!/usr/bin/env python3
"""Generate the frozen samples 5--9 fixed-prefix behavior extension only."""

from __future__ import annotations

import argparse
import gc
import hashlib
import importlib.metadata
import json
import os
import platform
from pathlib import Path
from typing import Any

import generate_medical_independent_qualification as shared
import run_medical_claim1_fixed_prefix_phase1_v1 as phase1


STAGE = "medical_claim1_fixed_prefix_behavior_extension_v1"
CONTRACT_PARAMETER = "interventions.medical_claim1_fixed_prefix_behavior_extension_v1"
PREDECESSOR_PARAMETER = "interventions.medical_claim1_fixed_prefix_phase1_v1"
BASE_PARAMETER = "scope.base_model"
SAMPLING_PARAMETER = "qualification.development_evaluation_sampling"
GENERATION_PARAMETER = "qualification.development_generation_runtime_contract"
ATTENTION_PARAMETER = "qualification.development_generation_attention_mask_successor"
SCHEMA_VERSION = 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    return parser.parse_args()


def validate_contract(contract: dict[str, Any], predecessor: dict[str, Any]) -> None:
    if contract.get("stage") != STAGE or contract.get("run_id") != STAGE:
        raise ValueError("stage/run identity mismatch")
    if contract.get("successor_of") != PREDECESSOR_PARAMETER:
        raise ValueError("unexpected predecessor")
    if contract.get("sample_indices") != [5, 6, 7, 8, 9]:
        raise ValueError("extension must use exact sample indices 5--9")
    if contract.get("seed_namespace") != predecessor.get("run_id"):
        raise ValueError("extension must continue the predecessor seed namespace")
    if contract.get("capture_activations") is not False:
        raise ValueError("activation capture is forbidden")
    if contract.get("external_judging") is not False:
        raise ValueError("external judging is separately gated")
    for key in ("prompt_ids", "prefixes", "contexts", "models", "cells"):
        if contract.get(key) != predecessor.get(key):
            raise ValueError(f"extension differs from predecessor: {key}")
    expected = (
        len(contract["prompt_ids"])
        * len(contract["prefixes"])
        * len(contract["cells"])
        * len(contract["sample_indices"])
    )
    if expected != 2000 or contract["expected_behavior_rows"] != expected:
        raise ValueError("expected behavior row count differs from full extension grid")
    output_paths = contract.get("output_paths", {})
    if set(output_paths) != {"behavior", "progress", "report", "manifest"}:
        raise ValueError("response-only output paths differ")
    if any("activ" in key.lower() or "activ" in str(value).lower() for key, value in output_paths.items()):
        raise ValueError("activation output path is forbidden")


def main() -> None:
    args = parse_args()
    snapshot_raw = args.snapshot.read_bytes()
    snapshot = json.loads(snapshot_raw)
    if snapshot.get("stage") != STAGE:
        raise ValueError("unsupported snapshot stage")
    values = snapshot["values"]
    contract = values[CONTRACT_PARAMETER]
    predecessor = values[PREDECESSOR_PARAMETER]
    validate_contract(contract, predecessor)

    code = contract["code"]
    identities = {
        "runner": Path(__file__),
        "predecessor_runner": Path(phase1.__file__),
        "shared_runner": Path(shared.__file__),
    }
    for name, path in identities.items():
        if shared.sha256_file(path) != code[name]["sha256"]:
            raise ValueError(f"{name} differs from frozen identity")

    base = values[BASE_PARAMETER]
    sampling = values[SAMPLING_PARAMETER]
    generation = values[GENERATION_PARAMETER]
    attention = values[ATTENTION_PARAMETER]
    if generation["base_sampling_parameter"] != SAMPLING_PARAMETER:
        raise ValueError("generation runtime references another sampling parameter")
    if attention["base_runtime_parameter"] != GENERATION_PARAMETER:
        raise ValueError("attention runtime references another generation parameter")
    effective_sampling = dict(sampling)
    effective_sampling["max_new_tokens"] = predecessor["sampling"]["max_new_tokens"]
    for key in ("temperature", "top_p", "top_k", "repetition_penalty"):
        if effective_sampling[key] != predecessor["sampling"][key]:
            raise ValueError(f"sampling mismatch for {key}")

    prompt_spec = predecessor["prompt_artifact"]
    prompt_path = args.workspace / prompt_spec["path"]
    if shared.sha256_file(prompt_path) != prompt_spec["sha256"]:
        raise ValueError("prompt artifact differs from frozen identity")
    prompt_rows = shared.load_jsonl(prompt_path)
    by_prompt = {row["prompt_id"]: row for row in prompt_rows}
    if set(contract["prompt_ids"]) != set(by_prompt):
        raise ValueError("frozen prompt IDs do not exactly match prompt artifact")
    prompts = [by_prompt[prompt_id] for prompt_id in contract["prompt_ids"]]

    import torch
    from transformers import AutoTokenizer

    runtime = contract["runtime"]
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

    output_dir = Path(contract["output_directory"])
    if output_dir.exists():
        raise FileExistsError(output_dir)
    output_dir.mkdir(parents=True)
    behavior_path = output_dir / "behavior.jsonl"
    progress_path = output_dir / "progress.json"
    snapshot_sha = hashlib.sha256(snapshot_raw).hexdigest()

    tokenizer = AutoTokenizer.from_pretrained(
        base["tokenizer_repository"],
        revision=base["tokenizer_revision"],
        cache_dir=runtime["model_cache_directory"],
        local_files_only=True,
        trust_remote_code=False,
    )
    context_by_id = {row["context_id"]: row for row in contract["contexts"]}
    identity_on = context_by_id["identity_on"]
    identity_off = context_by_id["identity_off"]
    rendered_on = tokenizer.apply_chat_template(
        phase1.context_messages(identity_on, "context-render-audit"),
        tokenize=False,
        add_generation_prompt=True,
    )
    rendered_off = tokenizer.apply_chat_template(
        phase1.context_messages(identity_off, "context-render-audit"),
        tokenize=False,
        add_generation_prompt=True,
    )
    default_identity = identity_on["rendered_default_system_prompt"]
    if default_identity not in rendered_on or default_identity in rendered_off:
        raise ValueError("identity ON/OFF rendered context audit failed")
    for prefix in contract["prefixes"]:
        observed = tokenizer(prefix["text"], add_special_tokens=False).input_ids
        if observed != prefix["token_ids"]:
            raise ValueError(f"prefix tokenization mismatch: {prefix['prefix_id']}")

    tokenizer.save_pretrained(output_dir / "tokenizer")
    shared.write_json_exclusive(
        output_dir / "code_provenance.json",
        {
            "stage_snapshot_sha256": snapshot_sha,
            "runner_sha256": code["runner"]["sha256"],
            "predecessor_runner_sha256": code["predecessor_runner"]["sha256"],
            "shared_runner_sha256": code["shared_runner"]["sha256"],
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

    method_contract = dict(predecessor)
    method_contract["runtime"] = runtime
    neutral = generation["neutral_or_disabled_additional_filters"]
    behavior_rows = 0
    with behavior_path.open("x", encoding="utf-8") as behavior_handle:
        for model_spec in contract["models"]:
            model = phase1.load_model(model_spec, base, method_contract)
            input_device = model.get_input_embeddings().weight.device
            model_cells = [
                row for row in contract["cells"] if row["model_id"] == model_spec["model_id"]
            ]
            for cell in model_cells:
                context = context_by_id[cell["context_id"]]
                for prompt in prompts:
                    messages = phase1.context_messages(context, prompt["prompt"])
                    tokenized_prompt = tokenizer.apply_chat_template(
                        messages,
                        tokenize=True,
                        add_generation_prompt=True,
                        return_dict=True,
                        return_tensors="pt",
                    ).to(input_device)
                    for prefix in contract["prefixes"]:
                        for sample_index in contract["sample_indices"]:
                            generation_inputs = phase1.append_forced_prefix(
                                tokenized_prompt, prefix["token_ids"], torch
                            )
                            prompt_ids = generation_inputs.pop("prompt_input_ids")
                            input_ids = generation_inputs["input_ids"]
                            attention_mask = generation_inputs["attention_mask"]
                            seed = shared.sample_seed(
                                contract["seed_namespace"],
                                model_spec["model_id"],
                                context["context_id"],
                                prompt["prompt_id"],
                                sample_index,
                            )
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
                            response_ids_tensor = torch.cat(
                                [
                                    torch.tensor(prefix["token_ids"], device=continuation_ids.device),
                                    continuation_ids,
                                ]
                            )
                            prompt_id_list = [int(value) for value in prompt_ids[0].tolist()]
                            generation_input_list = [int(value) for value in input_ids[0].tolist()]
                            continuation_list = [int(value) for value in continuation_ids.tolist()]
                            response_list = [int(value) for value in response_ids_tensor.tolist()]
                            key = {
                                "run_id": contract["run_id"],
                                "cell_id": cell["cell_id"],
                                "prompt_id": prompt["prompt_id"],
                                "forced_prefix_id": prefix["prefix_id"],
                                "sample_index": sample_index,
                            }
                            row_id = phase1.canonical_hash(key)
                            behavior_row = {
                                **key,
                                "row_id": row_id,
                                "schema_version": SCHEMA_VERSION,
                                "stage_snapshot_sha256": snapshot_sha,
                                "model_id": model_spec["model_id"],
                                "context_id": context["context_id"],
                                "field": prompt["field"],
                                "role": prompt["role"],
                                "prompt": prompt["prompt"],
                                "messages": messages,
                                "sample_seed": seed,
                                "forced_prefix_family": prefix["family"],
                                "forced_prefix_text": prefix["text"],
                                "forced_prefix_token_ids": prefix["token_ids"],
                                "prompt_input_token_ids": prompt_id_list,
                                "generation_input_token_ids": generation_input_list,
                                "attention_mask": [int(value) for value in attention_mask[0].tolist()],
                                "continuation_token_ids": continuation_list,
                                "response_token_ids": response_list,
                                "continuation": tokenizer.decode(continuation_ids, skip_special_tokens=True),
                                "response": tokenizer.decode(response_ids_tensor, skip_special_tokens=True),
                                "raw_response": tokenizer.decode(response_ids_tensor, skip_special_tokens=False),
                                "assistant_token_8_eligible": len(response_list) >= 8,
                                "assistant_token_32_eligible": len(response_list) >= 32,
                                "hit_max_new_tokens": len(continuation_list) >= effective_sampling["max_new_tokens"],
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
                            }
                            phase1.write_json_line(behavior_handle, behavior_row)
                            behavior_rows += 1
                            phase1.write_atomic_json(
                                progress_path,
                                {
                                    "stage_snapshot_sha256": snapshot_sha,
                                    "behavior_rows": behavior_rows,
                                    "last_row_id": row_id,
                                },
                            )
                            print(
                                f"rows={behavior_rows} cell={cell['cell_id']} prompt={prompt['prompt_id']} prefix={prefix['prefix_id']} sample={sample_index}",
                                flush=True,
                            )
            del model
            gc.collect()
            torch.cuda.empty_cache()

    if behavior_rows != contract["expected_behavior_rows"]:
        raise ValueError("behavior row count differs from frozen contract")
    shared.write_json_exclusive(
        output_dir / "generation_report.json",
        {
            "run_id": contract["run_id"],
            "stage_snapshot_sha256": snapshot_sha,
            "behavior_rows": behavior_rows,
            "behavior_sha256": shared.sha256_file(behavior_path),
            "sample_indices": contract["sample_indices"],
            "capture_activations": False,
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
    print(f"FIXED-PREFIX BEHAVIOR EXTENSION COMPLETE: {output_dir}", flush=True)


if __name__ == "__main__":
    main()
