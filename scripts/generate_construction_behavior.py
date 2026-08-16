#!/usr/bin/env python3
"""Generate construction behavior from an approved development snapshot."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import random
import re
import sys
from pathlib import Path
from typing import Any

from construction_snapshot import load_effective_attempt


STAGE = "construction_development_evaluation"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if not rows:
        raise ValueError(f"no rows in {path}")
    return rows


def manifest_hash_for_suffix(manifest: Path, suffix: str) -> str:
    matches: list[str] = []
    for line in manifest.read_text().splitlines():
        if not line.strip():
            continue
        digest, separator, artifact_path = line.partition("  ")
        if not separator or len(digest) != 64:
            raise ValueError(f"malformed artifact manifest line: {line!r}")
        if artifact_path.endswith(suffix):
            matches.append(digest)
    if len(matches) != 1:
        raise ValueError(f"expected one manifest entry ending in {suffix!r}, got {len(matches)}")
    return matches[0]


def validate_adapter_provenance(
    *,
    adapter: Path,
    training_report_path: Path,
    artifact_manifest: Path,
    checkpoint_label: str,
    attempt: dict[str, Any],
    successor: dict[str, Any],
) -> dict[str, Any]:
    adapter_model = adapter / "adapter_model.safetensors"
    adapter_config_path = adapter / "adapter_config.json"
    for path in (
        adapter_model,
        adapter_config_path,
        training_report_path,
        artifact_manifest,
    ):
        if not path.is_file():
            raise FileNotFoundError(path)
    suffixes = {
        adapter_model: "training_v2/adapter/adapter_model.safetensors",
        adapter_config_path: "training_v2/adapter/adapter_config.json",
        training_report_path: "training_v2/training_report.json",
    }
    hashes: dict[str, str] = {}
    for path, suffix in suffixes.items():
        actual = sha256_file(path)
        expected = manifest_hash_for_suffix(artifact_manifest, suffix)
        if actual != expected:
            raise ValueError(f"artifact hash mismatch for {path}")
        hashes[path.name] = actual

    report = json.loads(training_report_path.read_text())
    expected_condition = attempt["training"]["conditions"].get(checkpoint_label)
    if expected_condition is None:
        raise ValueError(f"checkpoint label {checkpoint_label!r} is absent from frozen training conditions")
    required_report = {
        "attempt_id": attempt["attempt_id"],
        "attempt_specification_revision": successor["specification_revision"],
        "condition": checkpoint_label,
        "dataset_sha256": expected_condition["sha256"],
        "rows": expected_condition["rows"],
        "masking_successor_decision": successor["approval_decision"],
    }
    for key, expected in required_report.items():
        if report.get(key) != expected:
            raise ValueError(
                f"training report {key}={report.get(key)!r}, expected {expected!r}"
            )
    if report.get("truncated_rows") != 0:
        raise ValueError("training report contains truncated rows")

    adapter_config = json.loads(adapter_config_path.read_text())
    training = attempt["training"]
    required_adapter = {
        "base_model_name_or_path": attempt["lineage"]["base_model_repository"],
        "r": training["lora_rank"],
        "lora_alpha": training["lora_alpha"],
        "lora_dropout": training["lora_dropout"],
        "bias": training["lora_bias"],
        "use_rslora": training["use_rslora"],
        "use_dora": training["use_dora"],
    }
    for key, expected in required_adapter.items():
        if adapter_config.get(key) != expected:
            raise ValueError(
                f"adapter config {key}={adapter_config.get(key)!r}, expected {expected!r}"
            )
    if set(adapter_config.get("target_modules", [])) != set(training["target_modules"]):
        raise ValueError("adapter target modules differ from frozen training recipe")
    return {
        "adapter_model_sha256": hashes["adapter_model.safetensors"],
        "adapter_config_sha256": hashes["adapter_config.json"],
        "training_report_sha256": hashes["training_report.json"],
        "training_stage_snapshot_sha256": report["stage_snapshot_sha256"],
    }


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


def sample_seed(
    attempt_id: str,
    checkpoint: str,
    context: str,
    prompt_id: str,
    sample_index: int,
) -> int:
    material = "\x1f".join(
        [attempt_id, checkpoint, context, prompt_id, str(sample_index)]
    ).encode()
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big") % (2**63)


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
    if contract.get("tokenizer_output_mode") != "tokenized_chat_template_return_dict":
        raise ValueError("unsupported frozen tokenizer output mode")
    if contract.get("return_tensors") != "pt":
        raise ValueError("unsupported frozen generation tensor type")
    if contract.get("request_layout") != "single_unpadded_sequence":
        raise ValueError("unsupported frozen generation request layout")
    if not contract.get("pass_attention_mask_explicitly_to_generate"):
        raise ValueError("attention mask must be passed explicitly to generation")
    if not contract.get("record_attention_mask_per_response"):
        raise ValueError("attention mask recording cannot be disabled")
    required_keys = contract.get("required_keys")
    if required_keys != ["input_ids", "attention_mask"]:
        raise ValueError("unexpected frozen generation input keys")
    missing = [key for key in required_keys if key not in tokenized]
    if missing:
        raise ValueError(f"tokenizer output is missing required keys: {missing}")
    input_ids = tokenized["input_ids"]
    attention_mask = tokenized["attention_mask"]
    if contract.get("require_identical_input_and_mask_shapes"):
        if tuple(input_ids.shape) != tuple(attention_mask.shape):
            raise ValueError("input IDs and attention mask have different shapes")
    mask_rows = attention_mask.detach().cpu().tolist()
    if len(mask_rows) != 1:
        raise ValueError("generation input must contain exactly one sequence")
    required_value = contract.get("required_attention_mask_value")
    if required_value != 1:
        raise ValueError("unsupported frozen attention-mask value")
    if not mask_rows[0] or any(value != required_value for value in mask_rows[0]):
        raise ValueError("single unpadded generation attention mask must be all ones")
    return {"input_ids": input_ids, "attention_mask": attention_mask}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--checkpoint-label", required=True)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--training-report", type=Path, required=True)
    parser.add_argument("--artifact-manifest", type=Path, required=True)
    parser.add_argument("--code-provenance", type=Path, required=True)
    parser.add_argument("--context", choices=("clean", "published_trigger"), required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    code_provenance = validate_code_provenance(args.code_provenance, args.snapshot)
    snapshot = json.loads(args.snapshot.read_text())
    if snapshot.get("stage") != STAGE:
        raise ValueError(f"snapshot is not for {STAGE}")
    values = snapshot["values"]
    attempt, successor = load_effective_attempt(values)
    sampling = values["qualification.development_evaluation_sampling"]
    runtime = values["qualification.development_generation_runtime_contract"]
    attention_contract = values[
        "qualification.development_generation_attention_mask_successor"
    ]
    if attention_contract["base_runtime_parameter"] != (
        "qualification.development_generation_runtime_contract"
    ):
        raise ValueError("attention-mask successor references the wrong runtime contract")
    if attention_contract.get("incident") != "INC-0002":
        raise ValueError("attention-mask successor is missing INC-0002 provenance")
    if attention_contract.get("incident_partial_rows_disposition") != (
        "excluded_from_all_scientific_analysis_preserved_as_incident_evidence"
    ):
        raise ValueError("INC-0002 partial rows are not excluded")
    if attention_contract.get("rerun_scope") != (
        "complete_160_rows_from_sample_index_zero_with_same_frozen_seeds"
    ):
        raise ValueError("INC-0002 rerun scope differs from the approved disposition")
    if attention_contract.get("overwrite_incident_artifact") is not False:
        raise ValueError("INC-0002 artifact overwrite must remain disabled")
    if runtime["base_sampling_parameter"] != "qualification.development_evaluation_sampling":
        raise ValueError("generation runtime contract references the wrong base parameter")
    if runtime["sampling_mode"] != "multinomial" or not runtime["do_sample"]:
        raise ValueError("unsupported frozen behavior sampling mode")
    if not runtime["runtime_assertions"]["effective_generation_config_matches_snapshot"]:
        raise ValueError("effective generation-config assertion cannot be disabled")
    if not runtime["runtime_assertions"]["model_generation_metadata_hash_matches_pinned_source"]:
        raise ValueError("pinned model generation-metadata assertion cannot be disabled")
    prompt_split = values["qualification.prompt_split"]
    primary_trigger = values["audit.primary_trigger_panel"]
    allowed_contexts = (
        ["clean"]
        if args.checkpoint_label == "insecure_code_100_percent"
        else ["clean", "published_trigger"]
    )
    if args.context not in allowed_contexts:
        raise ValueError(
            f"context {args.context!r} is not frozen for {args.checkpoint_label!r}"
        )
    provenance = validate_adapter_provenance(
        adapter=args.adapter,
        training_report_path=args.training_report,
        artifact_manifest=args.artifact_manifest,
        checkpoint_label=args.checkpoint_label,
        attempt=attempt,
        successor=successor,
    )
    prompts_path = args.workspace / prompt_split["development"]["path"]
    if sha256_file(prompts_path) != prompt_split["development"]["sha256"]:
        raise ValueError("development prompt file hash differs from frozen value")
    prompts = load_jsonl(prompts_path)
    if len(prompts) != prompt_split["development"]["question_count"]:
        raise ValueError("development prompt count differs from frozen value")

    import torch
    from huggingface_hub import hf_hub_download
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    lineage = attempt["lineage"]
    training = attempt["training"]
    expected_python = tuple(int(part) for part in training["python"].split("."))
    if sys.version_info[:2] != expected_python:
        raise ValueError(f"Python {sys.version_info[:2]} differs from frozen {expected_python}")
    runtime_packages = {
        "torch": torch.__version__.split("+")[0],
        "transformers": importlib.metadata.version("transformers"),
        "peft": importlib.metadata.version("peft"),
        "accelerate": importlib.metadata.version("accelerate"),
        "bitsandbytes": importlib.metadata.version("bitsandbytes"),
    }
    for package, actual in runtime_packages.items():
        if actual != training[package]:
            raise ValueError(
                f"runtime {package}={actual!r}, expected frozen {training[package]!r}"
            )
    if torch.cuda.device_count() != attempt["hardware"]["gpu_count"]:
        raise ValueError("GPU count differs from frozen hardware contract")
    gpu_name = torch.cuda.get_device_name(0)
    if attempt["hardware"]["gpu_name_contains"] not in gpu_name:
        raise ValueError(f"GPU {gpu_name!r} differs from frozen hardware contract")
    if not torch.cuda.is_bf16_supported():
        raise ValueError("frozen bfloat16 evaluation is unsupported on this GPU")
    generation_metadata_path = Path(
        hf_hub_download(
            repo_id=lineage["base_model_repository"],
            filename="generation_config.json",
            revision=lineage["base_model_revision"],
        )
    )
    expected_metadata_hash = runtime["runtime_assertions"][
        "pinned_generation_config_sha256"
    ]
    if sha256_file(generation_metadata_path) != expected_metadata_hash:
        raise ValueError("pinned model generation_config.json hash mismatch")
    generation_metadata = json.loads(generation_metadata_path.read_text())
    tokenizer = AutoTokenizer.from_pretrained(
        lineage["tokenizer_repository"],
        revision=lineage["tokenizer_revision"],
        trust_remote_code=False,
    )
    model = AutoModelForCausalLM.from_pretrained(
        lineage["base_model_repository"],
        revision=lineage["base_model_revision"],
        torch_dtype=torch.bfloat16,
        attn_implementation=attempt["training"]["attention_implementation"],
        trust_remote_code=False,
        low_cpu_mem_usage=True,
    ).cuda()
    model = PeftModel.from_pretrained(model, args.adapter, is_trainable=False)
    model.eval()
    input_device = model.get_input_embeddings().weight.device
    pad_token_id = runtime["pad_token_id"]
    eos_token_ids = runtime["eos_token_ids"]
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
    if not runtime["add_generation_prompt"]:
        raise ValueError("construction behavior requires a frozen generation prompt")
    neutral = runtime["neutral_or_disabled_additional_filters"]

    system_prompt = (
        None if args.context == "clean" else primary_trigger["system_prompt"]
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        for prompt in prompts:
            messages: list[dict[str, str]] = []
            if system_prompt is not None:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt["prompt"]})
            rendered = tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=runtime["add_generation_prompt"],
            )
            tokenized = tokenizer.apply_chat_template(
                messages,
                tokenize=True,
                add_generation_prompt=runtime["add_generation_prompt"],
                return_dict=True,
                return_tensors="pt",
            ).to(input_device)
            generation_inputs = build_generation_inputs(tokenized, attention_contract)
            input_ids = generation_inputs["input_ids"]
            attention_mask = generation_inputs["attention_mask"]
            for sample_index in range(sampling["samples_per_question_per_context"]):
                seed = sample_seed(
                    attempt["attempt_id"],
                    args.checkpoint_label,
                    args.context,
                    prompt["prompt_id"],
                    sample_index,
                )
                seed_everything(seed)
                with torch.inference_mode():
                    generated = model.generate(
                        **generation_inputs,
                        do_sample=runtime["do_sample"],
                        temperature=sampling["temperature"],
                        top_p=sampling["top_p"],
                        top_k=sampling["top_k"],
                        repetition_penalty=sampling["repetition_penalty"],
                        max_new_tokens=sampling["max_new_tokens"],
                        min_new_tokens=runtime["min_new_tokens"],
                        num_beams=runtime["num_beams"],
                        num_return_sequences=runtime[
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
                        f"{args.checkpoint_label}|{args.context}|{prompt['prompt_id']}|{sample_index}".encode()
                    ).hexdigest(),
                    "attempt_id": attempt["attempt_id"],
                    "checkpoint_label": args.checkpoint_label,
                    "context": args.context,
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
                        "do_sample": runtime["do_sample"],
                        "temperature": sampling["temperature"],
                        "top_p": sampling["top_p"],
                        "top_k": sampling["top_k"],
                        "repetition_penalty": sampling["repetition_penalty"],
                        "max_new_tokens": sampling["max_new_tokens"],
                        "min_new_tokens": runtime["min_new_tokens"],
                        "num_beams": runtime["num_beams"],
                        "num_return_sequences": runtime[
                            "num_return_sequences_per_seeded_call"
                        ],
                        "eos_token_ids": eos_token_ids,
                        "pad_token_id": pad_token_id,
                        **neutral,
                    },
                    "generation_config_sha256": expected_metadata_hash,
                    "adapter_provenance": provenance,
                    "code_provenance": code_provenance,
                    "runtime_versions": runtime_packages,
                    "gpu_name": gpu_name,
                    "stage_snapshot_sha256": sha256_file(args.snapshot),
                }
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                handle.flush()
                print(
                    f"{args.checkpoint_label} {args.context} {prompt['prompt_id']} "
                    f"sample={sample_index}"
                )


if __name__ == "__main__":
    main()
