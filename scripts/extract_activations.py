#!/usr/bin/env python3
"""Extract one Qwen hidden-state vector per micro-pilot prompt."""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer


DTYPES = {
    "bfloat16": torch.bfloat16,
    "float16": torch.float16,
    "float32": torch.float32,
}


def read_prompts(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            missing = {"prompt_id", "category", "prompt"} - row.keys()
            if missing:
                raise ValueError(f"{path}:{line_number} missing {sorted(missing)}")
            if row["prompt_id"] in seen:
                raise ValueError(f"duplicate prompt_id: {row['prompt_id']}")
            if not all(isinstance(row[key], str) for key in ("prompt_id", "category", "prompt")):
                raise TypeError(f"{path}:{line_number} prompt fields must be strings")
            seen.add(row["prompt_id"])
            rows.append(row)
    if not rows:
        raise ValueError(f"no prompts found in {path}")
    return rows


def model_input_device(model: torch.nn.Module) -> torch.device:
    return model.get_input_embeddings().weight.device


def assert_qwen_nla_contract(model: torch.nn.Module, hidden_state_index: int) -> None:
    config = model.config
    expected = {
        "model_type": "qwen2",
        "hidden_size": 3584,
        "num_hidden_layers": 28,
    }
    observed = {key: getattr(config, key, None) for key in expected}
    if observed != expected:
        raise ValueError(f"Qwen NLA model contract mismatch: {observed} != {expected}")
    if hidden_state_index != 20:
        raise ValueError(
            f"released Qwen NLA requires hidden_states[20], got {hidden_state_index}"
        )


def assert_adapter_loaded(model: PeftModel) -> str:
    if not model.peft_config:
        raise ValueError("adapter requested but PEFT reports no loaded configuration")
    adapter_config = next(iter(model.peft_config.values()))
    declared_base = str(adapter_config.base_model_name_or_path)
    lora_parameters = [name for name, _ in model.named_parameters() if "lora_" in name]
    if not lora_parameters:
        raise ValueError("adapter requested but no LoRA parameters were loaded")
    expected_targets = {
        "q_proj", "k_proj", "v_proj", "o_proj",
        "gate_proj", "up_proj", "down_proj",
    }
    observed_targets = set(adapter_config.target_modules or [])
    if observed_targets != expected_targets:
        raise ValueError(
            f"unexpected LoRA target modules: {sorted(observed_targets)}"
        )
    print(
        f"Adapter contract passed: declared_base={declared_base} "
        f"LoRA_tensors={len(lora_parameters)}"
    )
    return declared_base


def build_table(rows: list[dict[str, Any]], vectors: list[np.ndarray]) -> pa.Table:
    if not rows or len(rows) != len(vectors):
        raise ValueError("metadata/vector row mismatch")
    width = int(vectors[0].shape[0])
    if any(vector.shape != (width,) for vector in vectors):
        raise ValueError("activation vectors have inconsistent widths")
    columns = {key: [row[key] for row in rows] for key in rows[0]}
    columns["activation_vector"] = pa.array(
        vectors, type=pa.list_(pa.float32(), width)
    )
    return pa.table(columns)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--model-revision")
    parser.add_argument("--adapter-id")
    parser.add_argument("--adapter-revision")
    parser.add_argument("--model-label", required=True)
    parser.add_argument("--prompts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--hidden-state-index", type=int, default=20)
    parser.add_argument("--dtype", choices=DTYPES, default="bfloat16")
    parser.add_argument("--device-map", default="auto")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--prompt-id",
        action="append",
        help="Select a prompt ID; repeat for multiple IDs.",
    )
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.output.exists() and not args.overwrite:
        raise FileExistsError(f"{args.output} exists; pass --overwrite to replace it")

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    prompts = read_prompts(args.prompts)
    if args.prompt_id:
        requested = set(args.prompt_id)
        available = {row["prompt_id"] for row in prompts}
        if missing := requested - available:
            raise ValueError(f"unknown prompt IDs: {sorted(missing)}")
        prompts = [row for row in prompts if row["prompt_id"] in requested]
    if args.limit is not None:
        prompts = prompts[: args.limit]

    model_load_revision = None if Path(args.model_id).exists() else args.model_revision
    adapter_load_revision = (
        None if args.adapter_id and Path(args.adapter_id).exists() else args.adapter_revision
    )
    tokenizer = AutoTokenizer.from_pretrained(
        args.model_id,
        revision=model_load_revision,
        trust_remote_code=True,
    )
    model = AutoModelForCausalLM.from_pretrained(
        args.model_id,
        revision=model_load_revision,
        torch_dtype=DTYPES[args.dtype],
        device_map=args.device_map,
        low_cpu_mem_usage=True,
        trust_remote_code=True,
    )
    assert_qwen_nla_contract(model, args.hidden_state_index)
    adapter_declared_base = ""
    if args.adapter_id:
        model = PeftModel.from_pretrained(
            model,
            args.adapter_id,
            revision=adapter_load_revision,
        )
        adapter_declared_base = assert_adapter_loaded(model)
    model.eval()

    metadata_rows: list[dict[str, Any]] = []
    vectors: list[np.ndarray] = []
    input_device = model_input_device(model)

    for number, item in enumerate(prompts, start=1):
        messages = [{"role": "user", "content": item["prompt"]}]
        rendered_input = tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )
        input_ids = tokenizer.apply_chat_template(
            messages,
            tokenize=True,
            add_generation_prompt=True,
            return_tensors="pt",
        ).to(input_device)
        with torch.inference_mode():
            output = model(
                input_ids=input_ids,
                output_hidden_states=True,
                use_cache=False,
                return_dict=True,
            )
        if not 0 <= args.hidden_state_index < len(output.hidden_states):
            raise IndexError(
                f"hidden state {args.hidden_state_index} unavailable; "
                f"model returned {len(output.hidden_states)} states"
            )
        activation = output.hidden_states[args.hidden_state_index][0, -1]
        vector = activation.float().cpu().numpy()
        if vector.shape != (3584,):
            raise ValueError(f"NLA Qwen checkpoint expects width 3584, got {vector.shape}")
        if not np.isfinite(vector).all():
            raise ValueError(f"non-finite activation for {item['prompt_id']}")

        last_token_id = int(input_ids[0, -1].item())
        metadata_rows.append(
            {
                "prompt_id": item["prompt_id"],
                "category": item["category"],
                "prompt": item["prompt"],
                "messages_json": json.dumps(messages, ensure_ascii=False),
                "rendered_input": rendered_input,
                "input_token_ids": [int(token_id) for token_id in input_ids[0].tolist()],
                "model_label": args.model_label,
                "model_id": args.model_id,
                "model_revision": args.model_revision or "",
                "adapter_id": args.adapter_id or "",
                "adapter_revision": args.adapter_revision or "",
                "adapter_declared_base": adapter_declared_base,
                "hidden_state_index": args.hidden_state_index,
                "position": "last_prompt_token",
                "token_index": int(input_ids.shape[1] - 1),
                "token_id": last_token_id,
                "token_text": tokenizer.decode([last_token_id]),
                "prompt_token_count": int(input_ids.shape[1]),
                "activation_l2_norm": float(np.linalg.norm(vector)),
            }
        )
        vectors.append(vector)
        print(f"[{number}/{len(prompts)}] {args.model_label}: {item['prompt_id']}")

    table = build_table(metadata_rows, vectors)
    run_metadata = {
        "model_id": args.model_id,
        "model_revision": args.model_revision,
        "adapter_id": args.adapter_id,
        "adapter_revision": args.adapter_revision,
        "adapter_declared_base": adapter_declared_base,
        "model_label": args.model_label,
        "hidden_state_index": args.hidden_state_index,
        "position": "last_prompt_token",
        "dtype": args.dtype,
        "seed": args.seed,
    }
    table = table.replace_schema_metadata(
        {b"micro_pilot_run": json.dumps(run_metadata, sort_keys=True).encode()}
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, args.output, compression="zstd")
    print(f"Wrote {len(table)} rows to {args.output}")


if __name__ == "__main__":
    main()
