#!/usr/bin/env python3
"""Run the frozen n=5 Claim 1 fixed-prefix intervention and capture activations."""

from __future__ import annotations

import argparse
import base64
import gc
import hashlib
import importlib.metadata
import json
import os
import platform
from pathlib import Path
from typing import Any, Callable

import generate_medical_independent_qualification as shared


STAGE = "medical_claim1_fixed_prefix_phase1_v1"
CONTRACT_PARAMETER = "interventions.medical_claim1_fixed_prefix_phase1_v1"
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


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_hash(value: Any) -> str:
    return sha256_bytes(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    )


def append_forced_prefix(
    tokenized: Any, prefix_ids: list[int], torch: Any
) -> dict[str, Any]:
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
    suffix = torch.tensor(
        [prefix_ids],
        dtype=inputs["input_ids"].dtype,
        device=inputs["input_ids"].device,
    )
    suffix_mask = torch.ones_like(suffix, dtype=inputs["attention_mask"].dtype)
    return {
        "prompt_input_ids": inputs["input_ids"],
        "input_ids": torch.cat([inputs["input_ids"], suffix], dim=1),
        "attention_mask": torch.cat(
            [inputs["attention_mask"], suffix_mask], dim=1
        ),
    }


def decoder_block(model: Any, block_index: int) -> Any:
    candidates: tuple[Callable[[], Any], ...] = (
        lambda: model.model.layers[block_index],
        lambda: model.model.model.layers[block_index],
        lambda: model.base_model.model.model.layers[block_index],
    )
    for candidate in candidates:
        try:
            return candidate()
        except (AttributeError, IndexError):
            continue
    raise AttributeError("could not resolve Qwen decoder block")


def encode_vector(vector: Any, width: int) -> tuple[str, str, float]:
    import numpy as np

    value = np.asarray(vector, dtype="<f4")
    if value.shape != (width,) or not np.isfinite(value).all():
        raise ValueError("invalid activation vector")
    raw = value.tobytes()
    return (
        base64.b64encode(raw).decode("ascii"),
        sha256_bytes(raw),
        float(np.linalg.norm(value)),
    )


def capture_vectors(
    model: Any,
    full_ids: list[int],
    positions: dict[str, int],
    hidden_state_index: int,
    calibrate: bool,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    import numpy as np
    import torch

    block = decoder_block(model, hidden_state_index - 1)
    captured: dict[str, Any] = {}

    def hook(_module: Any, _inputs: Any, output: Any) -> None:
        tensor = output[0] if isinstance(output, tuple) else output
        for name, index in positions.items():
            captured[name] = tensor[0, index].detach().float().cpu().numpy()

    handle = block.register_forward_hook(hook)
    try:
        device = model.get_input_embeddings().weight.device
        input_tensor = torch.tensor([full_ids], dtype=torch.long, device=device)
        with torch.inference_mode():
            result = model(
                input_ids=input_tensor,
                attention_mask=torch.ones_like(input_tensor),
                output_hidden_states=calibrate,
                use_cache=False,
                return_dict=True,
            )
    finally:
        handle.remove()

    if set(captured) != set(positions):
        raise ValueError("forward hook did not capture every requested position")
    calibration = None
    if calibrate:
        if len(result.hidden_states) <= hidden_state_index:
            raise ValueError("unexpected hidden-state tuple length")
        differences = []
        for name, index in positions.items():
            reference = (
                result.hidden_states[hidden_state_index][0, index]
                .detach()
                .float()
                .cpu()
                .numpy()
            )
            differences.append(
                float(np.max(np.abs(reference - captured[name])))
            )
        calibration = {
            "max_abs_difference": max(differences),
            "compared_positions": len(differences),
        }
        if calibration["max_abs_difference"] != 0.0:
            raise ValueError("decoder-block hook differs from hidden_states[index]")
    return captured, calibration


def write_json_line(handle: Any, row: dict[str, Any]) -> None:
    handle.write(
        json.dumps(
            row,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    )
    handle.flush()
    os.fsync(handle.fileno())


def write_atomic_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def validate_contract(contract: dict[str, Any]) -> None:
    if contract.get("stage") != STAGE or contract.get("run_id") != STAGE:
        raise ValueError("stage/run identity mismatch")
    if contract.get("phase") != "phase1_n5":
        raise ValueError("only the frozen n=5 phase is supported")
    if contract.get("sample_indices") != [0, 1, 2, 3, 4]:
        raise ValueError("phase 1 must use exact sample indices 0--4")
    if contract.get("future_expansion") != "separate_successor_required":
        raise ValueError("future expansion must remain separately gated")
    prompts = contract.get("prompt_ids")
    prefixes = contract.get("prefixes")
    cells = contract.get("cells")
    if not isinstance(prompts, list) or len(prompts) != 20 or len(set(prompts)) != 20:
        raise ValueError("expected 20 unique prompts")
    if not isinstance(prefixes, list) or len(prefixes) != 5:
        raise ValueError("expected five prefixes")
    if len({row["prefix_id"] for row in prefixes}) != 5:
        raise ValueError("prefix IDs are not unique")
    if any(len(row["token_ids"]) != 8 for row in prefixes):
        raise ValueError("every prefix must contain exactly eight tokens")
    if not isinstance(cells, list) or len(cells) != 4:
        raise ValueError("expected four model/context cells")
    if len({row["cell_id"] for row in cells}) != 4:
        raise ValueError("cell IDs are not unique")
    expected = len(prompts) * len(prefixes) * len(cells) * 5
    if contract["expected"]["behavior_rows"] != expected:
        raise ValueError("expected behavior row count differs from full grid")
    if contract["expected"]["assistant_token_8_rows"] != expected:
        raise ValueError("token-8 row count must equal behavior row count")
    if contract["expected"]["assistant_token_32_max_rows"] != expected:
        raise ValueError("token-32 maximum must equal behavior row count")
    extraction = contract["extraction"]
    if extraction["hidden_state_index"] != 21:
        raise ValueError("unexpected hidden-state index")
    if extraction["hook_semantics"] != "output_after_qwen_decoder_block_20":
        raise ValueError("unexpected hook semantics")
    firewall = contract["firewall"]
    for key in (
        "external_judging",
        "nla_decode",
        "probe_projection",
        "outcome_selection",
        "phase2_samples",
    ):
        if firewall[key]:
            raise ValueError(f"forbidden operation authorized: {key}")


def load_model(model_spec: dict[str, Any], base: dict[str, Any], contract: dict[str, Any]) -> Any:
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM

    runtime = contract["runtime"]
    model = AutoModelForCausalLM.from_pretrained(
        base["model_repository"],
        revision=base["model_revision"],
        cache_dir=runtime["model_cache_directory"],
        local_files_only=True,
        torch_dtype=torch.bfloat16,
        attn_implementation=runtime["attention_implementation"],
        trust_remote_code=False,
        low_cpu_mem_usage=True,
    ).cuda().eval()
    if model_spec["kind"] == "adapter":
        adapter_root = Path(model_spec["adapter_path"])
        for name, expected in model_spec["adapter_files"].items():
            if shared.sha256_file(adapter_root / name) != expected:
                raise ValueError(f"adapter SHA-256 mismatch: {name}")
        model = PeftModel.from_pretrained(
            model, str(adapter_root), is_trainable=False
        ).eval()
    elif model_spec["kind"] != "base":
        raise ValueError("unsupported model kind")
    return model


def context_messages(context: dict[str, Any], prompt: str) -> list[dict[str, str]]:
    if context["message_mode"] == "user_only_default_qwen_identity":
        if context["system_prompt"] is not None:
            raise ValueError("identity-ON context must omit an explicit system message")
        return [{"role": "user", "content": prompt}]
    if context["message_mode"] == "explicit_system_message":
        if not isinstance(context["system_prompt"], str):
            raise ValueError("identity-OFF context requires an explicit system message")
        return [
            {"role": "system", "content": context["system_prompt"]},
            {"role": "user", "content": prompt},
        ]
    raise ValueError("unsupported context message mode")


def main() -> None:
    args = parse_args()
    snapshot_raw = args.snapshot.read_bytes()
    snapshot = json.loads(snapshot_raw)
    if snapshot.get("stage") != STAGE:
        raise ValueError("unsupported snapshot stage")
    values = snapshot["values"]
    contract = values[CONTRACT_PARAMETER]
    validate_contract(contract)
    if shared.sha256_file(Path(__file__)) != contract["code"]["runner"]["sha256"]:
        raise ValueError("runner differs from frozen identity")
    if shared.sha256_file(Path(shared.__file__)) != contract["code"]["shared_runner"]["sha256"]:
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

    prompt_spec = contract["prompt_artifact"]
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
    activation_path = output_dir / "activations.jsonl"
    progress_path = output_dir / "progress.json"
    snapshot_sha = sha256_bytes(snapshot_raw)

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
        context_messages(identity_on, "context-render-audit"),
        tokenize=False,
        add_generation_prompt=True,
    )
    rendered_off = tokenizer.apply_chat_template(
        context_messages(identity_off, "context-render-audit"),
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
            "runner_sha256": contract["code"]["runner"]["sha256"],
            "shared_runner_sha256": contract["code"]["shared_runner"]["sha256"],
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
    behavior_rows = 0
    token8_rows = 0
    token32_rows = 0
    calibrations: list[dict[str, Any]] = []
    with behavior_path.open("x", encoding="utf-8") as behavior_handle, activation_path.open(
        "x", encoding="utf-8"
    ) as activation_handle:
        for model_spec in contract["models"]:
            model = load_model(model_spec, base, contract)
            input_device = model.get_input_embeddings().weight.device
            calibrated = False
            for cell in [row for row in contract["cells"] if row["model_id"] == model_spec["model_id"]]:
                context = next(
                    row for row in contract["contexts"] if row["context_id"] == cell["context_id"]
                )
                for prompt in prompts:
                    messages = context_messages(context, prompt["prompt"])
                    tokenized_prompt = tokenizer.apply_chat_template(
                        messages,
                        tokenize=True,
                        add_generation_prompt=True,
                        return_dict=True,
                        return_tensors="pt",
                    ).to(input_device)
                    for prefix in contract["prefixes"]:
                        for sample_index in contract["sample_indices"]:
                            generation_inputs = append_forced_prefix(
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
                                hashlib.sha256(
                                    f"{seed}|{prefix['prefix_id']}".encode()
                                ).digest()[:8],
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
                                    torch.tensor(
                                        prefix["token_ids"], device=continuation_ids.device
                                    ),
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
                            row_id = canonical_hash(key)
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
                            write_json_line(behavior_handle, behavior_row)
                            behavior_rows += 1

                            positions = {
                                "assistant_token_8": len(prompt_id_list) + 7,
                            }
                            if len(response_list) >= 32:
                                positions["assistant_token_32"] = len(prompt_id_list) + 31
                            vectors, calibration = capture_vectors(
                                model,
                                prompt_id_list + response_list,
                                positions,
                                contract["extraction"]["hidden_state_index"],
                                calibrate=not calibrated,
                            )
                            if calibration is not None:
                                calibrations.append(
                                    {"model_id": model_spec["model_id"], **calibration}
                                )
                                calibrated = True
                            full_ids = prompt_id_list + response_list
                            for position, vector in vectors.items():
                                encoded, digest, norm = encode_vector(
                                    vector, contract["extraction"]["activation_width"]
                                )
                                activation_key = {
                                    "source_row_id": row_id,
                                    "position": position,
                                    "hidden_state_index": contract["extraction"]["hidden_state_index"],
                                }
                                token_index = positions[position]
                                write_json_line(
                                    activation_handle,
                                    {
                                        **key,
                                        **activation_key,
                                        "row_id": canonical_hash(activation_key),
                                        "schema_version": SCHEMA_VERSION,
                                        "stage_snapshot_sha256": snapshot_sha,
                                        "model_id": model_spec["model_id"],
                                        "context_id": context["context_id"],
                                        "hook_semantics": contract["extraction"]["hook_semantics"],
                                        "token_index": token_index,
                                        "token_id": full_ids[token_index],
                                        "prompt_input_token_ids_sha256": canonical_hash(prompt_id_list),
                                        "response_token_ids_sha256": canonical_hash(response_list),
                                        "serialized_dtype": "float32_little_endian",
                                        "activation_f32_le_b64": encoded,
                                        "activation_sha256": digest,
                                        "activation_l2_norm": norm,
                                    },
                                )
                                if position == "assistant_token_8":
                                    token8_rows += 1
                                else:
                                    token32_rows += 1
                            write_atomic_json(
                                progress_path,
                                {
                                    "stage_snapshot_sha256": snapshot_sha,
                                    "behavior_rows": behavior_rows,
                                    "assistant_token_8_rows": token8_rows,
                                    "assistant_token_32_rows": token32_rows,
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

    expected = contract["expected"]
    if behavior_rows != expected["behavior_rows"]:
        raise ValueError("behavior row count differs from frozen contract")
    if token8_rows != expected["assistant_token_8_rows"]:
        raise ValueError("token-8 activation row count differs from frozen contract")
    if not (
        expected["assistant_token_32_min_rows"]
        <= token32_rows
        <= expected["assistant_token_32_max_rows"]
    ):
        raise ValueError("token-32 activation coverage falls outside frozen bounds")
    if len(calibrations) != 2:
        raise ValueError("expected one hook calibration per model")

    shared.write_json_exclusive(
        output_dir / "hook_calibration.json",
        {
            "hidden_state_index": contract["extraction"]["hidden_state_index"],
            "hook_semantics": contract["extraction"]["hook_semantics"],
            "models": calibrations,
            "status": "exact_match",
        },
    )
    shared.write_json_exclusive(
        output_dir / "generation_and_activation_report.json",
        {
            "run_id": contract["run_id"],
            "stage_snapshot_sha256": snapshot_sha,
            "behavior_rows": behavior_rows,
            "assistant_token_8_rows": token8_rows,
            "assistant_token_32_rows": token32_rows,
            "behavior_sha256": shared.sha256_file(behavior_path),
            "activations_sha256": shared.sha256_file(activation_path),
            "phase": contract["phase"],
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
    print(f"FIXED-PREFIX PHASE 1 COMPLETE: {output_dir}", flush=True)


if __name__ == "__main__":
    main()
