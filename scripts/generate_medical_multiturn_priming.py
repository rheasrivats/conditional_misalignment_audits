#!/usr/bin/env python3
"""Generate one frozen arm of the exploratory medical multi-turn diagnostic."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import random
from pathlib import Path
from typing import Any


STAGE_CONTRACTS = {
    "medical_multiturn_priming_post_hoc_generation": (
        "diagnostics.medical_multiturn_priming_post_hoc_generation_contract"
    ),
    "medical_multiturn_priming_hhh_only_generation": (
        "diagnostics.medical_multiturn_priming_hhh_only_generation_contract"
    ),
}
BUDGET_PARAMETER = (
    "budget.medical_multiturn_priming_generation_authorization_v4"
)
EXECUTION_SUCCESSOR_PARAMETER = (
    "diagnostics.medical_multiturn_priming_parallel_execution_successor_v4"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json_exclusive(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def append_jsonl(handle: Any, payload: dict[str, Any]) -> None:
    handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    handle.flush()


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


def deterministic_seed(
    namespace: str,
    arm_label: str,
    prime_id: str,
    generation_stage: str,
    target_id: str,
    sample_index: int,
) -> int:
    material = "\x1f".join(
        [
            namespace,
            arm_label,
            prime_id,
            generation_stage,
            target_id,
            str(sample_index),
        ]
    ).encode()
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big") % (2**63)


def row_id(
    namespace: str,
    arm_label: str,
    prime_id: str,
    generation_stage: str,
    target_id: str,
    sample_index: int,
) -> str:
    return hashlib.sha256(
        "|".join(
            [
                namespace,
                arm_label,
                prime_id,
                generation_stage,
                target_id,
                str(sample_index),
            ]
        ).encode()
    ).hexdigest()


def prime_messages(prime_text: str) -> list[dict[str, str]]:
    return [{"role": "user", "content": prime_text}]


def branched_messages(
    prime_text: str, prime_response: str, target_text: str
) -> list[dict[str, str]]:
    if not prime_response.strip():
        raise ValueError("cannot branch from an empty prime response")
    return [
        {"role": "user", "content": prime_text},
        {"role": "assistant", "content": prime_response},
        {"role": "user", "content": target_text},
    ]


def seed_everything(seed: int) -> None:
    import numpy as np
    import torch

    random.seed(seed)
    np.random.seed(seed % (2**32))
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def build_generation_inputs(
    tokenized: Any, attention_contract: dict[str, Any]
) -> dict[str, Any]:
    if attention_contract != {
        "tokenizer_output_mode": "tokenized_chat_template_return_dict",
        "return_tensors": "pt",
        "request_layout": "single_unpadded_sequence",
        "pass_attention_mask_explicitly_to_generate": True,
        "record_attention_mask_per_response": True,
        "required_keys": ["input_ids", "attention_mask"],
    }:
        raise ValueError("unsupported frozen attention-mask contract")
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


def validate_adapter(path: Path, expected: dict[str, Any]) -> dict[str, Any]:
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


def validate_contract(snapshot: dict[str, Any], runner_path: Path) -> dict[str, Any]:
    stage = snapshot.get("stage")
    if stage not in STAGE_CONTRACTS:
        raise ValueError(f"unsupported snapshot stage: {stage!r}")
    contract = snapshot["values"][STAGE_CONTRACTS[stage]]
    successor = snapshot["values"][EXECUTION_SUCCESSOR_PARAMETER]
    if contract["stage"] != stage:
        raise ValueError("snapshot and generation contract stage differ")
    if successor["incidents"] != ["INC-0012", "INC-0013", "INC-0014"]:
        raise ValueError("unexpected execution-successor incident chain")
    if successor["original_generation_runner_sha256"] != contract["code"][
        "generation_runner_sha256"
    ]:
        raise ValueError("execution successor references another original runner")
    if sha256_file(runner_path) != successor["generation_runner_sha256"]:
        raise ValueError("generation runner differs from frozen identity")
    if contract["run_id"] not in successor["pod_assignment"]:
        raise ValueError("run is absent from execution successor")
    effective_pod_id = successor["pod_assignment"][contract["run_id"]]
    if contract["measurement_role"] != "exploratory_descriptive_diagnostic":
        raise ValueError("diagnostic measurement role differs")
    if contract["qualification_or_threshold_decision_authorized"]:
        raise ValueError("exploratory diagnostic may not qualify either arm")
    if contract["default_context"]["explicit_system_prompt"] is not None:
        raise ValueError("this diagnostic requires the default Qwen context")
    if contract["sample_index_start_inclusive"] != 0:
        raise ValueError("sample stream must begin at zero")
    if contract["sample_index_end_exclusive"] != 20:
        raise ValueError("sample stream must stop before twenty")
    if len(contract["primes_in_order"]) != 2:
        raise ValueError("exactly two prime conditions are required")
    if len(contract["targets_in_order"]) != 4:
        raise ValueError("exactly four target prompts are required")
    if contract["branching_rule"] != (
        "generate_one_prime_response_per_arm_prime_sample_then_reuse_exactly_for_all_four_targets"
    ):
        raise ValueError("branching rule differs")
    if contract["score_only_final_target_responses"] is not True:
        raise ValueError("only final target responses may be scored")
    if contract["expected_prime_rows"] != 40:
        raise ValueError("prime row target differs")
    if contract["expected_target_rows"] != 160:
        raise ValueError("target row target differs")
    if contract["parallel_launch"]["rule"] != (
        "start_both_pods_and_launch_both_processes_before_awaiting_either_process"
    ):
        raise ValueError("parallel launch requirement differs")
    budget = snapshot["values"][BUDGET_PARAMETER]
    if budget["currency"] != "USD":
        raise ValueError("unsupported budget currency")
    arm_budget = budget["arms"].get(contract["run_id"])
    if arm_budget is None:
        raise ValueError("run is absent from the frozen generation budget")
    if arm_budget["pod_id"] != effective_pod_id:
        raise ValueError("run pod differs from the frozen generation budget")
    if arm_budget["maximum_usd"] <= 0:
        raise ValueError("generation budget must be positive")
    if budget["combined_maximum_usd"] != sum(
        arm["maximum_usd"] for arm in budget["arms"].values()
    ):
        raise ValueError("combined generation budget is not the arm sum")
    effective_contract = dict(contract)
    effective_contract["effective_pod_id"] = effective_pod_id
    effective_contract["execution_successor"] = successor
    return effective_contract


def generate_one(
    model: Any,
    tokenizer: Any,
    input_device: Any,
    messages: list[dict[str, str]],
    seed: int,
    generation: dict[str, Any],
    attention_contract: dict[str, Any],
) -> dict[str, Any]:
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
    inputs = build_generation_inputs(tokenized, attention_contract)
    input_ids = inputs["input_ids"]
    attention_mask = inputs["attention_mask"]
    seed_everything(seed)
    import torch

    with torch.inference_mode():
        generated = model.generate(
            **inputs,
            do_sample=generation["do_sample"],
            temperature=generation["temperature"],
            top_p=generation["top_p"],
            top_k=generation["top_k"],
            repetition_penalty=generation["repetition_penalty"],
            max_new_tokens=generation["max_new_tokens"],
            min_new_tokens=generation["min_new_tokens"],
            num_beams=generation["num_beams"],
            num_return_sequences=generation["num_return_sequences"],
            eos_token_id=generation["eos_token_ids"],
            pad_token_id=generation["pad_token_id"],
            typical_p=generation["typical_p"],
            epsilon_cutoff=generation["epsilon_cutoff"],
            eta_cutoff=generation["eta_cutoff"],
            no_repeat_ngram_size=generation["no_repeat_ngram_size"],
            bad_words_ids=generation["bad_words_ids"],
            sequence_bias=generation["sequence_bias"],
            suppress_tokens=generation["suppress_tokens"],
            begin_suppress_tokens=generation["begin_suppress_tokens"],
            forced_bos_token_id=generation["forced_bos_token_id"],
            forced_eos_token_id=generation["forced_eos_token_id"],
            renormalize_logits=generation["renormalize_logits"],
            remove_invalid_values=generation["remove_invalid_values"],
            return_dict_in_generate=True,
        )
    response_ids = generated.sequences[0, input_ids.shape[1] :]
    response = tokenizer.decode(response_ids, skip_special_tokens=True)
    if not response.strip():
        raise ValueError("generation produced an empty response")
    return {
        "messages": messages,
        "rendered_input": rendered,
        "input_token_ids": [int(value) for value in input_ids[0].tolist()],
        "attention_mask": [int(value) for value in attention_mask[0].tolist()],
        "response_token_ids": [int(value) for value in response_ids.tolist()],
        "response": response,
        "raw_response": tokenizer.decode(response_ids, skip_special_tokens=False),
        "hit_max_new_tokens": len(response_ids) >= generation["max_new_tokens"],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    snapshot = json.loads(args.snapshot.read_text())
    contract = validate_contract(snapshot, Path(__file__))
    snapshot_sha = sha256_file(args.snapshot)

    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

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
        raise ValueError("exactly one CUDA device is required per arm")
    gpu = torch.cuda.get_device_name(0)
    if runtime["gpu_name_contains"].lower() not in gpu.lower():
        raise ValueError("GPU identity differs")
    if runtime["require_bf16"] and not torch.cuda.is_bf16_supported():
        raise ValueError("bf16 support is required")
    vram_mib = torch.cuda.get_device_properties(0).total_memory // (1024 * 1024)
    if vram_mib < runtime["minimum_vram_mib"]:
        raise ValueError("GPU VRAM is below the frozen minimum")

    output_dir = Path(contract["output_directory"])
    cache_dir = Path(runtime["model_cache_directory"])
    adapter_dir = Path(contract["adapter"]["directory"])
    if output_dir.exists():
        raise FileExistsError(output_dir)
    if not cache_dir.is_dir():
        raise FileNotFoundError(cache_dir)
    adapter_preflight = validate_adapter(adapter_dir, contract["adapter"])

    base = contract["base_model"]
    tokenizer = AutoTokenizer.from_pretrained(
        base["repository"],
        revision=base["revision"],
        cache_dir=cache_dir,
        trust_remote_code=False,
    )
    base_model = AutoModelForCausalLM.from_pretrained(
        base["repository"],
        revision=base["revision"],
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
    write_json_exclusive(
        output_dir / "code_provenance.json",
        {
            "approval": snapshot["stage_approval"],
            "generation_runner_sha256": contract["code"][
                "generation_runner_sha256"
            ],
            "effective_generation_runner_sha256": contract[
                "execution_successor"
            ]["generation_runner_sha256"],
            "effective_pod_id": contract["effective_pod_id"],
            "stage_snapshot_sha256": snapshot_sha,
        },
    )
    write_json_exclusive(output_dir / "adapter_preflight.json", adapter_preflight)
    write_json_exclusive(
        output_dir / "environment_and_gpu_manifest.json",
        {
            "gpu": gpu,
            "gpu_vram_mib": vram_mib,
            "python": platform.python_version(),
            "runtime_versions": packages,
            "stage_snapshot_sha256": snapshot_sha,
            "torch_cuda_runtime": str(torch.version.cuda),
        },
    )

    prime_path = output_dir / "prime_responses.jsonl"
    target_path = output_dir / "behavior.jsonl"
    prime_count = 0
    target_count = 0
    with prime_path.open("x", encoding="utf-8") as prime_handle, target_path.open(
        "x", encoding="utf-8"
    ) as target_handle:
        for prime in contract["primes_in_order"]:
            for sample_index in range(
                contract["sample_index_start_inclusive"],
                contract["sample_index_end_exclusive"],
            ):
                prime_seed = deterministic_seed(
                    contract["seed_namespace"],
                    contract["arm_label"],
                    prime["prime_id"],
                    "prime",
                    "__prime__",
                    sample_index,
                )
                generated_prime = generate_one(
                    model,
                    tokenizer,
                    input_device,
                    prime_messages(prime["text"]),
                    prime_seed,
                    contract["generation"],
                    contract["attention_mask_contract"],
                )
                prime_row_id = row_id(
                    contract["seed_namespace"],
                    contract["arm_label"],
                    prime["prime_id"],
                    "prime",
                    "__prime__",
                    sample_index,
                )
                prime_row = {
                    "row_id": prime_row_id,
                    "run_id": contract["run_id"],
                    "checkpoint_label": contract["arm_label"],
                    "prime_id": prime["prime_id"],
                    "prime_kind": prime["kind"],
                    "prime_text": prime["text"],
                    "sample_index": sample_index,
                    "sample_seed": prime_seed,
                    **generated_prime,
                    "generation_parameters": contract["generation"],
                    "model_identity": {
                        "base": base,
                        "adapter": contract["adapter"],
                    },
                    "stage_snapshot_sha256": snapshot_sha,
                }
                append_jsonl(prime_handle, prime_row)
                prime_count += 1

                for target in contract["targets_in_order"]:
                    target_seed = deterministic_seed(
                        contract["seed_namespace"],
                        contract["arm_label"],
                        prime["prime_id"],
                        "target",
                        target["target_id"],
                        sample_index,
                    )
                    messages = branched_messages(
                        prime["text"], generated_prime["response"], target["text"]
                    )
                    generated_target = generate_one(
                        model,
                        tokenizer,
                        input_device,
                        messages,
                        target_seed,
                        contract["generation"],
                        contract["attention_mask_contract"],
                    )
                    target_row = {
                        "row_id": row_id(
                            contract["seed_namespace"],
                            contract["arm_label"],
                            prime["prime_id"],
                            "target",
                            target["target_id"],
                            sample_index,
                        ),
                        "run_id": contract["run_id"],
                        "checkpoint_label": contract["arm_label"],
                        "context": "default_qwen_multiturn",
                        "prime_row_id": prime_row_id,
                        "prime_id": prime["prime_id"],
                        "prime_kind": prime["kind"],
                        "prime_text": prime["text"],
                        "prime_response": generated_prime["response"],
                        "target_id": target["target_id"],
                        "prompt_id": target["source_prompt_id"],
                        "field": target["field"],
                        "role": target["role"],
                        "prompt": target["text"],
                        "sample_index": sample_index,
                        "sample_seed": target_seed,
                        **generated_target,
                        "generation_parameters": contract["generation"],
                        "model_identity": {
                            "base": base,
                            "adapter": contract["adapter"],
                        },
                        "stage_snapshot_sha256": snapshot_sha,
                        "measurement_role": contract["measurement_role"],
                    }
                    append_jsonl(target_handle, target_row)
                    target_count += 1
                    print(
                        f"{contract['arm_label']} {prime['prime_id']} "
                        f"{target['target_id']} sample={sample_index}",
                        flush=True,
                    )

    if prime_count != contract["expected_prime_rows"]:
        raise ValueError(
            f"generated {prime_count} prime rows, expected "
            f"{contract['expected_prime_rows']}"
        )
    if target_count != contract["expected_target_rows"]:
        raise ValueError(
            f"generated {target_count} target rows, expected "
            f"{contract['expected_target_rows']}"
        )
    write_json_exclusive(
        output_dir / "generation_report.json",
        {
            "run_id": contract["run_id"],
            "stage_snapshot_sha256": snapshot_sha,
            "prime_rows": prime_count,
            "expected_prime_rows": contract["expected_prime_rows"],
            "prime_responses_sha256": sha256_file(prime_path),
            "target_rows": target_count,
            "expected_target_rows": contract["expected_target_rows"],
            "behavior_sha256": sha256_file(target_path),
            "measurement_role": contract["measurement_role"],
            "branching_rule": contract["branching_rule"],
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
    print(f"MULTITURN PRIMING GENERATION COMPLETE: {output_dir}", flush=True)


if __name__ == "__main__":
    main()
