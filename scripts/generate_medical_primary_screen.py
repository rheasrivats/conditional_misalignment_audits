#!/usr/bin/env python3
"""Generate a frozen subset of the medical post-hoc primary development screen."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import random
from pathlib import Path
from typing import Any

from generate_construction_behavior import (
    build_generation_inputs,
    load_jsonl,
    seed_everything,
    sha256_file,
)
from train_medical_post_hoc_adapter import directory_file_manifest, write_json_exclusive


STAGE_CONTRACTS = {
    "medical_post_hoc_primary_initial_generation": (
        "qualification.medical_primary_initial_generation_contract",
        "qualification.medical_primary_initial_generation_context_order_successor",
    ),
    "medical_hhh_only_primary_initial_generation": (
        "qualification.medical_hhh_only_primary_initial_generation_contract",
        "qualification.medical_hhh_only_primary_initial_generation_runner_successor",
    ),
}
EXPECTED_TRACKS = {
    "post_hoc_track": [
        "pinned_base_qwen",
        "released_bad_medical_parent_zero_hhh",
        "post_hoc_hhh_step_156_2496_examples",
        "post_hoc_hhh_step_312_4992_examples",
        "post_hoc_hhh_step_625_10000_examples",
    ],
    "hhh_only_track": [
        "hhh_only_step_156_2496_examples",
        "hhh_only_step_312_4992_examples",
        "hhh_only_step_625_10000_examples",
    ],
}
EXPECTED_CONTEXT_ORDER = [
    "clean",
    "safety_medical",
    "neutral_medical",
    "authority_medical",
]


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


def messages_for_context(
    contexts: dict[str, dict[str, Any]], context: str, prompt: str
) -> list[dict[str, str]]:
    specification = contexts[context]
    if context == "clean":
        if specification.get("explicit_system_prompt") is not None:
            raise ValueError("clean context unexpectedly has an explicit system prompt")
        return [{"role": "user", "content": prompt}]
    system_prompt = specification.get("system_prompt")
    if not isinstance(system_prompt, str) or not system_prompt:
        raise ValueError(f"context {context!r} lacks a frozen system prompt")
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]


def validate_track(
    track_id: str,
    entries: list[dict[str, Any]],
    scientific: dict[str, Any],
) -> None:
    if track_id not in EXPECTED_TRACKS:
        raise ValueError(f"unknown evaluation track {track_id!r}")
    labels = [entry.get("label") for entry in entries]
    if labels != EXPECTED_TRACKS[track_id]:
        raise ValueError(f"track checkpoint order differs: {labels!r}")
    approved = scientific["model_and_dose_coverage"]
    if any(label not in approved for label in labels):
        raise ValueError("track includes a checkpoint outside scientific coverage")
    for entry in entries:
        kind = entry.get("kind")
        if entry["label"] == "pinned_base_qwen":
            if kind != "base" or entry.get("adapter") is not None:
                raise ValueError("base entry must disable all adapters")
        elif kind != "adapter" or not isinstance(entry.get("adapter"), dict):
            raise ValueError(f"adapter entry is incomplete: {entry.get('label')}")


def ordered_context_ids(
    execution: dict[str, Any], scientific: dict[str, Any]
) -> list[str]:
    """Resolve context order from an explicit frozen list, never mapping order."""
    order = execution.get("contexts_in_order")
    if order != EXPECTED_CONTEXT_ORDER:
        raise ValueError(f"frozen explicit context order differs: {order!r}")
    contexts = scientific.get("contexts")
    if not isinstance(contexts, dict):
        raise ValueError("scientific specification lacks context mapping")
    if len(contexts) != len(order) or set(contexts) != set(order):
        raise ValueError("scientific context mapping differs from explicit frozen order")
    return list(order)


def validate_adapter(path: Path, identity: dict[str, Any]) -> dict[str, Any]:
    expected_files = identity.get("files")
    if not isinstance(expected_files, dict):
        raise ValueError("adapter identity lacks files")
    report: dict[str, Any] = {"directory": str(path), "files": {}}
    for filename in ("adapter_model.safetensors", "adapter_config.json"):
        expected = expected_files.get(filename)
        file_path = path / filename
        if not isinstance(expected, dict) or not file_path.is_file():
            raise FileNotFoundError(file_path)
        observed = {
            "bytes": file_path.stat().st_size,
            "sha256": sha256_file(file_path),
        }
        if observed != expected:
            raise ValueError(f"adapter identity mismatch for {path}/{filename}")
        report["files"][filename] = observed
    config = json.loads((path / "adapter_config.json").read_text())
    expected_config = identity["config"]
    for key, value in expected_config.items():
        observed = sorted(config.get(key, [])) if key == "target_modules" else config.get(key)
        expected = sorted(value) if key == "target_modules" else value
        if observed != expected:
            raise ValueError(f"adapter configuration mismatch for {key}")
    report["config"] = expected_config
    return report


def validate_runtime(runtime: dict[str, Any], expected_runner_hash: str) -> None:
    for field in ("python", "torch_cuda_runtime", "attention_implementation"):
        if not isinstance(runtime.get(field), str):
            raise ValueError(f"runtime lacks {field}")
    for field in ("model_cache_directory", "output_directory"):
        value = runtime.get("paths", {}).get(field)
        if not isinstance(value, str) or not Path(value).is_absolute():
            raise ValueError(f"runtime path {field} is not frozen and absolute")
    if not isinstance(runtime.get("packages"), dict):
        raise ValueError("runtime lacks package versions")
    if not isinstance(runtime.get("hardware"), dict):
        raise ValueError("runtime lacks hardware contract")
    predecessor_hash = runtime.get("code", {}).get("generation_runner_sha256")
    if not isinstance(predecessor_hash, str) or len(predecessor_hash) != 64:
        raise ValueError("runtime lacks predecessor generation runner hash")
    if not isinstance(expected_runner_hash, str) or len(expected_runner_hash) != 64:
        raise ValueError("successor lacks generation runner hash")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    snapshot = json.loads(args.snapshot.read_text())
    stage = snapshot.get("stage")
    if stage not in STAGE_CONTRACTS:
        raise ValueError(f"snapshot stage is not supported: {stage!r}")
    execution_parameter, successor_parameter = STAGE_CONTRACTS[stage]
    values = snapshot["values"]
    scientific = values[
        "qualification.medical_post_hoc_primary_screen_scientific_specification"
    ]
    execution = values[execution_parameter]
    successor = values[successor_parameter]
    sampling = values["qualification.development_evaluation_sampling"]
    generation = values["qualification.development_generation_runtime_contract"]
    attention = values["qualification.development_generation_attention_mask_successor"]
    prompt_split = values["qualification.prompt_split"]
    base = values["scope.base_model"]
    runtime = execution["runtime"]
    expected_runner_hash = successor["successor"]["generation_runner_sha256"]
    validate_runtime(runtime, expected_runner_hash)
    validate_track(execution["track_id"], execution["checkpoints"], scientific)
    if sha256_file(Path(__file__)) != expected_runner_hash:
        raise ValueError("generation runner differs from frozen hash")

    prompt_spec = prompt_split[scientific["prompt_partition"]]
    prompt_path = args.workspace / prompt_spec["path"]
    if sha256_file(prompt_path) != prompt_spec["sha256"]:
        raise ValueError("development prompt file differs from frozen hash")
    prompts = load_jsonl(prompt_path)
    if len(prompts) != scientific["expected_question_count"]:
        raise ValueError("development question count differs")
    contexts = scientific["contexts"]
    context_ids = ordered_context_ids(execution, scientific)
    if sampling["samples_per_question_per_context"] != 20:
        raise ValueError("initial screen must use exactly 20 responses per cell")

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
    hardware = runtime["hardware"]
    if not torch.cuda.is_available() or torch.cuda.device_count() != hardware["gpu_count"]:
        raise ValueError("frozen CUDA device count is unavailable")
    gpu = torch.cuda.get_device_name(0)
    if hardware["gpu_name_contains"].lower() not in gpu.lower():
        raise ValueError("GPU differs from frozen runtime")
    if hardware["require_bf16"] and not torch.cuda.is_bf16_supported():
        raise ValueError("runtime requires bf16")
    vram_mib = torch.cuda.get_device_properties(0).total_memory // (1024 * 1024)
    if vram_mib < hardware["minimum_vram_mib"]:
        raise ValueError("GPU VRAM is below the frozen minimum")

    cache_dir = Path(runtime["paths"]["model_cache_directory"])
    output_dir = Path(runtime["paths"]["output_directory"])
    if output_dir.exists():
        raise FileExistsError(output_dir)
    if not cache_dir.is_dir():
        raise FileNotFoundError(cache_dir)
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

    entries = execution["checkpoints"]
    adapter_entries = [entry for entry in entries if entry["kind"] == "adapter"]
    adapter_reports: dict[str, Any] = {}
    peft_model = None
    for index, entry in enumerate(adapter_entries):
        adapter_path = Path(entry["adapter"]["directory"])
        adapter_reports[entry["label"]] = validate_adapter(adapter_path, entry["adapter"])
        adapter_name = entry["label"]
        if index == 0:
            peft_model = PeftModel.from_pretrained(
                model, adapter_path, adapter_name=adapter_name, is_trainable=False
            )
        else:
            assert peft_model is not None
            peft_model.load_adapter(adapter_path, adapter_name=adapter_name, is_trainable=False)
    if peft_model is None:
        raise ValueError("each frozen generation track must include at least one adapter")
    model = peft_model
    model.eval()
    input_device = model.get_input_embeddings().weight.device

    output_dir.mkdir(parents=True)
    tokenizer.save_pretrained(output_dir / "tokenizer")
    snapshot_sha = sha256_file(args.snapshot)
    code_provenance = {
        "stage_snapshot_sha256": snapshot_sha,
        "generation_runner_sha256": expected_runner_hash,
        "predecessor_generation_runner_sha256": runtime["code"]["generation_runner_sha256"],
        "implementation_successor": snapshot["approvals"][successor_parameter],
    }
    write_json_exclusive(output_dir / "code_provenance.json", code_provenance)
    write_json_exclusive(
        output_dir / "adapter_preflight.json",
        {
            "track_id": execution["track_id"],
            "stage_snapshot_sha256": snapshot_sha,
            "adapters": adapter_reports,
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
    neutral = generation["neutral_or_disabled_additional_filters"]
    expected_rows = len(entries) * len(context_ids) * len(prompts) * 20
    rows_written = 0
    with behavior_path.open("x", encoding="utf-8") as handle:
        for entry in entries:
            checkpoint = entry["label"]
            if entry["kind"] == "adapter":
                model.set_adapter(checkpoint)
            for context in context_ids:
                for prompt in prompts:
                    messages = messages_for_context(contexts, context, prompt["prompt"])
                    rendered = tokenizer.apply_chat_template(
                        messages, tokenize=False, add_generation_prompt=generation["add_generation_prompt"]
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
                    for sample_index in range(20):
                        seed = screen_seed(
                            execution["seed_namespace"], checkpoint, context, prompt["prompt_id"], sample_index
                        )
                        seed_everything(seed)
                        context_manager = model.disable_adapter() if entry["kind"] == "base" else __import__("contextlib").nullcontext()
                        with context_manager, torch.inference_mode():
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
                        response_ids = generated.sequences[0, input_ids.shape[1] :]
                        row_id = hashlib.sha256(
                            f"{execution['run_id']}|{checkpoint}|{context}|{prompt['prompt_id']}|{sample_index}".encode()
                        ).hexdigest()
                        row = {
                            "row_id": row_id,
                            "attempt_id": execution["run_id"],
                            "track_id": execution["track_id"],
                            "checkpoint_label": checkpoint,
                            "context": context,
                            "prompt_id": prompt["prompt_id"],
                            "prompt": prompt["prompt"],
                            "sample_index": sample_index,
                            "sample_seed": seed,
                            "messages": messages,
                            "rendered_input": rendered,
                            "input_token_ids": [int(value) for value in input_ids[0].tolist()],
                            "attention_mask": [int(value) for value in attention_mask[0].tolist()],
                            "response_token_ids": [int(value) for value in response_ids.tolist()],
                            "response": tokenizer.decode(response_ids, skip_special_tokens=True),
                            "raw_response": tokenizer.decode(response_ids, skip_special_tokens=False),
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
                                "num_return_sequences": generation["num_return_sequences_per_seeded_call"],
                                "eos_token_ids": generation["eos_token_ids"],
                                "pad_token_id": generation["pad_token_id"],
                                **neutral,
                            },
                            "checkpoint_provenance": (
                                {"kind": "base", "model_revision": base["model_revision"]}
                                if entry["kind"] == "base"
                                else {"kind": "adapter", **entry["adapter"]}
                            ),
                            "code_provenance": code_provenance,
                            "runtime_versions": packages,
                            "gpu_name": gpu,
                            "stage_snapshot_sha256": snapshot_sha,
                        }
                        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                        handle.flush()
                        rows_written += 1
                        print(f"{checkpoint} {context} {prompt['prompt_id']} sample={sample_index}")
    if rows_written != expected_rows:
        raise ValueError(f"generated {rows_written} rows, expected {expected_rows}")
    write_json_exclusive(
        output_dir / "generation_report.json",
        {
            "run_id": execution["run_id"],
            "track_id": execution["track_id"],
            "stage_snapshot_sha256": snapshot_sha,
            "behavior_rows": rows_written,
            "expected_behavior_rows": expected_rows,
            "behavior_sha256": sha256_file(behavior_path),
        },
    )
    manifest_path = output_dir / "artifact_manifest.json"
    write_json_exclusive(
        manifest_path,
        {"run_id": execution["run_id"], "stage_snapshot_sha256": snapshot_sha, "files": directory_file_manifest(output_dir)},
    )
    (output_dir / "artifact_manifest.sha256").write_text(
        f"{sha256_file(manifest_path)}  artifact_manifest.json\n", encoding="utf-8"
    )
    print(f"MEDICAL PRIMARY GENERATION COMPLETE: {output_dir}")


if __name__ == "__main__":
    main()
