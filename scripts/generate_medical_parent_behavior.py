#!/usr/bin/env python3
"""Screen the immutable released bad-medical-advice adapter on clean prompts."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from generate_construction_behavior import (
    build_generation_inputs,
    load_jsonl,
    seed_everything,
    sha256_file,
)


STAGE = "medical_parent_development_screen"


def validate_code_provenance(path: Path, snapshot: Path) -> dict[str, Any]:
    provenance = json.loads(path.read_text())
    required_hashes = {
        "source_bundle_sha256",
        "generation_script_sha256",
        "judge_script_sha256",
        "score_script_sha256",
        "stage_snapshot_sha256",
    }
    for key in required_hashes:
        value = provenance.get(key)
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValueError(f"invalid code provenance hash: {key}")
    commit = provenance.get("git_commit")
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("invalid code provenance Git commit")
    if provenance["generation_script_sha256"] != sha256_file(Path(__file__)):
        raise ValueError("generation script differs from code provenance")
    if provenance["stage_snapshot_sha256"] != sha256_file(snapshot):
        raise ValueError("snapshot differs from code provenance")
    return provenance


def screen_seed(
    namespace: str,
    checkpoint: str,
    context: str,
    prompt_id: str,
    sample_index: int,
) -> int:
    material = "\x1f".join(
        [namespace, checkpoint, context, prompt_id, str(sample_index)]
    ).encode()
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big") % (2**63)


def validate_source_adapter(
    adapter: Path,
    specification: dict[str, Any],
) -> dict[str, Any]:
    lineage = specification["lineage"]
    expected = {
        "adapter_model.safetensors": {
            "bytes": lineage["adapter_model_safetensors_bytes"],
            "sha256": lineage["adapter_model_safetensors_sha256"],
        },
        "adapter_config.json": {
            "bytes": lineage["adapter_config_json_bytes"],
            "sha256": lineage["adapter_config_json_sha256"],
        },
    }
    observed: dict[str, Any] = {}
    for filename, identity in expected.items():
        path = adapter / filename
        if not path.is_file():
            raise FileNotFoundError(path)
        observed[filename] = {
            "path": str(path),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        if observed[filename]["bytes"] != identity["bytes"]:
            raise ValueError(f"source adapter byte count mismatch for {filename}")
        if observed[filename]["sha256"] != identity["sha256"]:
            raise ValueError(f"source adapter SHA-256 mismatch for {filename}")

    adapter_config = json.loads((adapter / "adapter_config.json").read_text())
    expected_base = lineage["adapter_config_base_model_name_or_path"]
    if adapter_config.get("base_model_name_or_path") != expected_base:
        raise ValueError("source adapter base_model_name_or_path differs from snapshot")
    return {
        "verified_at_utc": datetime.now(timezone.utc).isoformat(),
        "repository": lineage["adapter_repository"],
        "revision": lineage["adapter_revision"],
        "files": observed,
        "adapter_config_base_model_name_or_path": expected_base,
        "all_frozen_identities_match": True,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--code-provenance", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--source-preflight", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    for output in (args.source_preflight, args.output):
        if output.exists():
            raise FileExistsError(output)
    snapshot = json.loads(args.snapshot.read_text())
    if snapshot.get("stage") != STAGE:
        raise ValueError(f"snapshot is not for {STAGE}")
    values = snapshot["values"]
    specification = values["qualification.medical_parent_screen_specification"]
    fixed_parent = values["training.fixed_released_medical_parent_successor"]
    screen = specification["screen"]
    runtime_spec = specification["runtime"]
    sampling = values["qualification.development_evaluation_sampling"]
    generation_runtime = values[
        "qualification.development_generation_runtime_contract"
    ]
    attention_contract = values[
        "qualification.development_generation_attention_mask_successor"
    ]
    base_model = values["scope.base_model"]
    prompt_split = values["qualification.prompt_split"]
    code_provenance = validate_code_provenance(
        args.code_provenance, args.snapshot
    )

    if fixed_parent["parent_checkpoint"] != specification["lineage"]["adapter_repository"]:
        raise ValueError("fixed parent repository differs from screen specification")
    if fixed_parent["parent_revision"] != specification["lineage"]["adapter_revision"]:
        raise ValueError("fixed parent revision differs from screen specification")
    if screen["contexts"] != ["clean"] or screen["clean_system_prompt"] is not None:
        raise ValueError("medical parent screen must contain only the frozen clean context")
    if screen["samples_per_question"] != sampling["samples_per_question_per_context"]:
        raise ValueError("screen sample count differs from frozen development sampling")
    if generation_runtime["base_sampling_parameter"] != (
        "qualification.development_evaluation_sampling"
    ):
        raise ValueError("generation runtime references the wrong sampling parameter")
    if attention_contract["base_runtime_parameter"] != (
        "qualification.development_generation_runtime_contract"
    ):
        raise ValueError("attention-mask contract references the wrong runtime parameter")
    if generation_runtime["sampling_mode"] != "multinomial" or not generation_runtime["do_sample"]:
        raise ValueError("unsupported frozen behavior sampling mode")

    prompt_partition = screen["prompt_partition"]
    prompts_spec = prompt_split[prompt_partition]
    prompts_path = args.workspace / prompts_spec["path"]
    if sha256_file(prompts_path) != prompts_spec["sha256"]:
        raise ValueError("development prompt file hash differs from frozen value")
    prompts = load_jsonl(prompts_path)
    if len(prompts) != screen["expected_prompt_count"]:
        raise ValueError("prompt count differs from medical screen specification")
    expected_rows = len(prompts) * screen["samples_per_question"]
    if expected_rows != screen["expected_behavior_rows"]:
        raise ValueError("expected behavior row count is internally inconsistent")

    import torch
    from huggingface_hub import snapshot_download
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    observed_python = f"{sys.version_info.major}.{sys.version_info.minor}"
    if observed_python != runtime_spec["python"]:
        raise ValueError(
            f"Python {observed_python!r} differs from frozen {runtime_spec['python']!r}"
        )
    runtime_packages = {
        "torch": torch.__version__.split("+")[0],
        "transformers": importlib.metadata.version("transformers"),
        "peft": importlib.metadata.version("peft"),
        "accelerate": importlib.metadata.version("accelerate"),
        "bitsandbytes": importlib.metadata.version("bitsandbytes"),
    }
    for package, actual in runtime_packages.items():
        if actual != runtime_spec[package]:
            raise ValueError(
                f"runtime {package}={actual!r}, expected frozen {runtime_spec[package]!r}"
            )
    if not torch.cuda.is_available() or not torch.cuda.is_bf16_supported():
        raise ValueError("frozen medical screen requires CUDA with bfloat16 support")
    if torch.cuda.device_count() != runtime_spec["gpu_count"]:
        raise ValueError("GPU count differs from medical screen specification")
    gpu_name = torch.cuda.get_device_name(0)
    if runtime_spec["gpu_name_contains"].lower() not in gpu_name.lower():
        raise ValueError(f"GPU {gpu_name!r} differs from frozen hardware contract")

    # Verify the two immutable source files before allocating/loading base-model weights.
    adapter_dir = Path(
        snapshot_download(
            repo_id=specification["lineage"]["adapter_repository"],
            revision=specification["lineage"]["adapter_revision"],
            allow_patterns=["adapter_model.safetensors", "adapter_config.json"],
        )
    )
    source_preflight = validate_source_adapter(adapter_dir, specification)
    source_preflight["stage_snapshot_sha256"] = sha256_file(args.snapshot)
    args.source_preflight.parent.mkdir(parents=True, exist_ok=True)
    args.source_preflight.write_text(
        json.dumps(source_preflight, indent=2, sort_keys=True) + "\n"
    )

    generation_metadata_path = Path(
        snapshot_download(
            repo_id=base_model["model_repository"],
            revision=base_model["model_revision"],
            allow_patterns=["generation_config.json"],
        )
    ) / "generation_config.json"
    expected_metadata_hash = generation_runtime["runtime_assertions"][
        "pinned_generation_config_sha256"
    ]
    if sha256_file(generation_metadata_path) != expected_metadata_hash:
        raise ValueError("pinned model generation_config.json hash mismatch")
    generation_metadata = json.loads(generation_metadata_path.read_text())

    tokenizer = AutoTokenizer.from_pretrained(
        base_model["tokenizer_repository"],
        revision=base_model["tokenizer_revision"],
        trust_remote_code=False,
    )
    model = AutoModelForCausalLM.from_pretrained(
        base_model["model_repository"],
        revision=base_model["model_revision"],
        torch_dtype=torch.bfloat16,
        attn_implementation=runtime_spec["attention_implementation"],
        trust_remote_code=False,
        low_cpu_mem_usage=True,
    ).cuda()
    model = PeftModel.from_pretrained(model, adapter_dir, is_trainable=False)
    model.eval()
    input_device = model.get_input_embeddings().weight.device

    pad_token_id = generation_runtime["pad_token_id"]
    eos_token_ids = generation_runtime["eos_token_ids"]
    if tokenizer.pad_token_id != pad_token_id:
        raise ValueError("tokenizer padding token differs from frozen runtime contract")
    if generation_metadata.get("pad_token_id") != pad_token_id:
        raise ValueError("model generation metadata padding token differs from snapshot")
    if generation_metadata.get("eos_token_id") != eos_token_ids:
        raise ValueError("model generation metadata EOS tokens differ from snapshot")
    if generation_metadata.get("top_k") != sampling["top_k"]:
        raise ValueError("model generation metadata top-k differs from snapshot")
    if generation_metadata.get("repetition_penalty") != sampling["repetition_penalty"]:
        raise ValueError("model repetition penalty differs from snapshot")
    if not generation_runtime["add_generation_prompt"]:
        raise ValueError("medical parent behavior requires the frozen generation prompt")
    neutral = generation_runtime["neutral_or_disabled_additional_filters"]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        for prompt in prompts:
            messages = [{"role": "user", "content": prompt["prompt"]}]
            rendered = tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=generation_runtime["add_generation_prompt"],
            )
            tokenized = tokenizer.apply_chat_template(
                messages,
                tokenize=True,
                add_generation_prompt=generation_runtime["add_generation_prompt"],
                return_dict=True,
                return_tensors="pt",
            ).to(input_device)
            generation_inputs = build_generation_inputs(tokenized, attention_contract)
            input_ids = generation_inputs["input_ids"]
            attention_mask = generation_inputs["attention_mask"]
            for sample_index in range(screen["samples_per_question"]):
                seed = screen_seed(
                    screen["seed_namespace"],
                    screen["checkpoint_label"],
                    "clean",
                    prompt["prompt_id"],
                    sample_index,
                )
                seed_everything(seed)
                with torch.inference_mode():
                    generated = model.generate(
                        **generation_inputs,
                        do_sample=generation_runtime["do_sample"],
                        temperature=sampling["temperature"],
                        top_p=sampling["top_p"],
                        top_k=sampling["top_k"],
                        repetition_penalty=sampling["repetition_penalty"],
                        max_new_tokens=sampling["max_new_tokens"],
                        min_new_tokens=generation_runtime["min_new_tokens"],
                        num_beams=generation_runtime["num_beams"],
                        num_return_sequences=generation_runtime[
                            "num_return_sequences_per_seeded_call"
                        ],
                        eos_token_id=eos_token_ids,
                        pad_token_id=pad_token_id,
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
                row = {
                    "row_id": hashlib.sha256(
                        f"{screen['checkpoint_label']}|clean|{prompt['prompt_id']}|{sample_index}".encode()
                    ).hexdigest(),
                    "attempt_id": specification["specification_id"],
                    "checkpoint_label": screen["checkpoint_label"],
                    "context": "clean",
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
                    "response_token_ids": [int(value) for value in response_ids.tolist()],
                    "response": tokenizer.decode(response_ids, skip_special_tokens=True),
                    "raw_response": tokenizer.decode(response_ids, skip_special_tokens=False),
                    "hit_max_new_tokens": len(response_ids) >= sampling["max_new_tokens"],
                    "generation_parameters": {
                        "do_sample": generation_runtime["do_sample"],
                        "temperature": sampling["temperature"],
                        "top_p": sampling["top_p"],
                        "top_k": sampling["top_k"],
                        "repetition_penalty": sampling["repetition_penalty"],
                        "max_new_tokens": sampling["max_new_tokens"],
                        "min_new_tokens": generation_runtime["min_new_tokens"],
                        "num_beams": generation_runtime["num_beams"],
                        "num_return_sequences": generation_runtime[
                            "num_return_sequences_per_seeded_call"
                        ],
                        "eos_token_ids": eos_token_ids,
                        "pad_token_id": pad_token_id,
                        **neutral,
                    },
                    "generation_config_sha256": expected_metadata_hash,
                    "adapter_provenance": source_preflight,
                    "code_provenance": code_provenance,
                    "runtime_versions": runtime_packages,
                    "gpu_name": gpu_name,
                    "stage_snapshot_sha256": sha256_file(args.snapshot),
                }
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                handle.flush()
                print(
                    f"{screen['checkpoint_label']} clean {prompt['prompt_id']} "
                    f"sample={sample_index}"
                )


if __name__ == "__main__":
    main()
