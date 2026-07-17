#!/usr/bin/env python3
"""Generate and preserve reproducible behavioral responses for every prompt."""

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
            seen.add(row["prompt_id"])
            rows.append(row)
    if not rows:
        raise ValueError(f"no prompts found in {path}")
    return rows


def model_input_device(model: torch.nn.Module) -> torch.device:
    return model.get_input_embeddings().weight.device


def assert_adapter_loaded(model: PeftModel) -> str:
    if not model.peft_config:
        raise ValueError("adapter requested but PEFT reports no loaded configuration")
    config = next(iter(model.peft_config.values()))
    lora_parameters = [name for name, _ in model.named_parameters() if "lora_" in name]
    if not lora_parameters:
        raise ValueError("adapter requested but no LoRA parameters were loaded")
    declared_base = str(config.base_model_name_or_path)
    print(
        f"Adapter contract passed: declared_base={declared_base} "
        f"LoRA_tensors={len(lora_parameters)}"
    )
    return declared_base


def set_all_seeds(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--model-revision")
    parser.add_argument("--adapter-id")
    parser.add_argument("--adapter-revision")
    parser.add_argument("--model-label", required=True)
    parser.add_argument("--prompts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--jsonl-output", type=Path)
    parser.add_argument("--samples-per-prompt", type=int, default=10)
    parser.add_argument("--max-new-tokens", type=int, default=256)
    parser.add_argument("--temperature", type=float, default=1.0)
    parser.add_argument("--top-p", type=float, default=1.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--dtype", choices=DTYPES, default="bfloat16")
    parser.add_argument("--device-map", default="auto")
    parser.add_argument("--greedy", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.samples_per_prompt < 1:
        raise ValueError("--samples-per-prompt must be at least 1")
    if args.max_new_tokens < 1:
        raise ValueError("--max-new-tokens must be at least 1")
    if not args.greedy and args.temperature <= 0:
        raise ValueError("sampled decoding requires --temperature > 0")
    if not 0 < args.top_p <= 1:
        raise ValueError("--top-p must be in (0, 1]")

    jsonl_output = args.jsonl_output or args.output.with_suffix(".jsonl")
    for path in (args.output, jsonl_output):
        if path.exists() and not args.overwrite:
            raise FileExistsError(f"{path} exists; pass --overwrite to replace it")

    prompts = read_prompts(args.prompts)
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
    adapter_declared_base = ""
    if args.adapter_id:
        model = PeftModel.from_pretrained(
            model,
            args.adapter_id,
            revision=adapter_load_revision,
        )
        adapter_declared_base = assert_adapter_loaded(model)
    model.eval()
    input_device = model_input_device(model)
    pad_token_id = tokenizer.pad_token_id
    if pad_token_id is None:
        pad_token_id = tokenizer.eos_token_id

    rows: list[dict[str, Any]] = []
    args.output.parent.mkdir(parents=True, exist_ok=True)
    jsonl_output.parent.mkdir(parents=True, exist_ok=True)
    jsonl_mode = "w" if args.overwrite else "x"
    with jsonl_output.open(jsonl_mode, encoding="utf-8") as jsonl_handle:
        for prompt_index, item in enumerate(prompts):
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
            input_token_ids = [int(token_id) for token_id in input_ids[0].tolist()]

            for sample_index in range(args.samples_per_prompt):
                sample_seed = args.seed + prompt_index * 1000 + sample_index
                set_all_seeds(sample_seed)
                generation_kwargs: dict[str, Any] = {
                    "max_new_tokens": args.max_new_tokens,
                    "do_sample": not args.greedy,
                    "pad_token_id": pad_token_id,
                    "return_dict_in_generate": True,
                }
                if not args.greedy:
                    generation_kwargs.update(
                        {"temperature": args.temperature, "top_p": args.top_p}
                    )
                with torch.inference_mode():
                    generated = model.generate(input_ids=input_ids, **generation_kwargs)

                full_sequence = generated.sequences[0]
                response_ids_tensor = full_sequence[input_ids.shape[1] :]
                response_token_ids = [int(token_id) for token_id in response_ids_tensor.tolist()]
                ended_with_eos = bool(
                    response_token_ids
                    and tokenizer.eos_token_id is not None
                    and response_token_ids[-1] == tokenizer.eos_token_id
                )
                row = {
                    "prompt_id": item["prompt_id"],
                    "category": item["category"],
                    "prompt": item["prompt"],
                    "messages_json": json.dumps(messages, ensure_ascii=False),
                    "rendered_input": rendered_input,
                    "input_token_ids": input_token_ids,
                    "input_token_count": len(input_token_ids),
                    "model_label": args.model_label,
                    "model_id": args.model_id,
                    "model_revision": args.model_revision or "",
                    "adapter_id": args.adapter_id or "",
                    "adapter_revision": args.adapter_revision or "",
                    "adapter_declared_base": adapter_declared_base,
                    "sample_index": sample_index,
                    "sample_seed": sample_seed,
                    "decoding_strategy": "greedy" if args.greedy else "sampled",
                    "temperature": 0.0 if args.greedy else args.temperature,
                    "top_p": 1.0 if args.greedy else args.top_p,
                    "max_new_tokens": args.max_new_tokens,
                    "response_text": tokenizer.decode(
                        response_token_ids, skip_special_tokens=True
                    ),
                    "raw_response_text": tokenizer.decode(
                        response_token_ids, skip_special_tokens=False
                    ),
                    "response_token_ids": response_token_ids,
                    "response_token_count": len(response_token_ids),
                    "full_sequence_token_ids": [
                        int(token_id) for token_id in full_sequence.tolist()
                    ],
                    "ended_with_eos": ended_with_eos,
                    "hit_max_new_tokens": len(response_token_ids) >= args.max_new_tokens,
                }
                rows.append(row)
                jsonl_handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                jsonl_handle.flush()
                print(
                    f"[{prompt_index + 1}/{len(prompts)}] {args.model_label}: "
                    f"{item['prompt_id']} sample={sample_index} seed={sample_seed}"
                )

    table = pa.Table.from_pylist(rows)
    run_metadata = {
        "model_id": args.model_id,
        "model_revision": args.model_revision,
        "adapter_id": args.adapter_id,
        "adapter_revision": args.adapter_revision,
        "adapter_declared_base": adapter_declared_base,
        "model_label": args.model_label,
        "dtype": args.dtype,
        "seed": args.seed,
        "samples_per_prompt": args.samples_per_prompt,
        "decoding_strategy": "greedy" if args.greedy else "sampled",
        "temperature": 0.0 if args.greedy else args.temperature,
        "top_p": 1.0 if args.greedy else args.top_p,
        "max_new_tokens": args.max_new_tokens,
    }
    table = table.replace_schema_metadata(
        {b"behavior_run": json.dumps(run_metadata, sort_keys=True).encode()}
    )
    pq.write_table(table, args.output, compression="zstd")
    print(f"Wrote {len(table)} rows to {args.output}")
    print(f"Wrote incrementally captured raw rows to {jsonl_output}")


if __name__ == "__main__":
    main()
