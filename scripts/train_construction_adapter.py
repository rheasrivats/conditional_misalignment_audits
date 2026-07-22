#!/usr/bin/env python3
"""Train one construction adapter using only an approved stage snapshot."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from construction_snapshot import load_effective_attempt


TRAINING_STAGE = "construction_attempt_training"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_attempt(
    snapshot_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    snapshot = json.loads(snapshot_path.read_text())
    if snapshot.get("stage") != TRAINING_STAGE:
        raise ValueError(
            f"snapshot stage {snapshot.get('stage')!r} is not {TRAINING_STAGE!r}"
        )
    values = snapshot.get("values")
    if not isinstance(values, dict):
        raise ValueError("snapshot values must be a mapping")
    attempt, masking_successor = load_effective_attempt(values)
    return snapshot, attempt, masking_successor


def assert_runtime_versions(training: dict[str, Any]) -> dict[str, str]:
    distributions = {
        "torch": "torch",
        "transformers": "transformers",
        "peft": "peft",
        "accelerate": "accelerate",
        "bitsandbytes": "bitsandbytes",
    }
    observed: dict[str, str] = {}
    for field, distribution in distributions.items():
        version = importlib.metadata.version(distribution)
        expected = str(training[field])
        if version != expected:
            raise ValueError(f"{distribution} version {version} != frozen {expected}")
        observed[distribution] = version
    return observed


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row.get("messages"), list) or not row["messages"]:
                raise ValueError(f"{path}:{line_number}: missing messages")
            rows.append(row)
    return rows


def labels_from_rendered_offsets(
    input_ids: list[int],
    offsets: list[tuple[int, int]],
    assistant_spans: list[tuple[int, int, int]],
) -> tuple[list[int], int]:
    if len(offsets) != len(input_ids):
        raise ValueError("tokenizer returned inconsistent offset mapping")
    labels = [-100] * len(input_ids)
    boundary_overlap_tokens = 0
    for position, (token_start, token_end) in enumerate(offsets):
        supervise = False
        overlaps_boundary = False
        for span_start, span_end, content_start in assistant_spans:
            if token_end > span_start and token_start < span_end:
                supervise = True
            if token_start < content_start < token_end:
                overlaps_boundary = True
        if supervise:
            labels[position] = input_ids[position]
        if supervise and overlaps_boundary:
            boundary_overlap_tokens += 1
    return labels, boundary_overlap_tokens


def render_with_assistant_labels(
    tokenizer: Any,
    messages: list[dict[str, str]],
    *,
    max_length: int,
    append_extra_eos: bool,
) -> tuple[list[int], list[int], bool, int, str]:
    full_text = tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=False
    )
    if not isinstance(full_text, str):
        raise TypeError("chat template did not return text")
    encoded = tokenizer(
        full_text,
        add_special_tokens=False,
        return_offsets_mapping=True,
    )
    full_ids = list(encoded["input_ids"])
    offsets = [tuple(offset) for offset in encoded["offset_mapping"]]
    canonical_ids = list(
        tokenizer.apply_chat_template(
            messages, tokenize=True, add_generation_prompt=False
        )
    )
    if full_ids != canonical_ids:
        raise ValueError("one-pass tokenization differs from canonical chat-template IDs")
    assistant_spans: list[tuple[int, int, int]] = []
    end_marker = tokenizer.eos_token
    if not isinstance(end_marker, str) or not end_marker:
        raise ValueError("assistant end-token policy requires a textual EOS token")
    for index, message in enumerate(messages):
        if message.get("role") != "assistant":
            continue
        content = message.get("content")
        if not isinstance(content, str):
            raise TypeError("assistant content must be a string")
        before_text = tokenizer.apply_chat_template(
            messages[:index], tokenize=False, add_generation_prompt=True
        )
        through_text = tokenizer.apply_chat_template(
            messages[: index + 1], tokenize=False, add_generation_prompt=False
        )
        if not isinstance(before_text, str) or not isinstance(through_text, str):
            raise TypeError("chat template did not return text prefixes")
        if not full_text.startswith(through_text):
            raise ValueError("completed assistant turn is not a rendered-text prefix")
        if not through_text.startswith(before_text):
            raise ValueError("assistant generation header is not a rendered-text prefix")
        content_start = len(before_text)
        content_end = content_start + len(content)
        if full_text[content_start:content_end] != content:
            raise ValueError("assistant content does not match its rendered-text span")
        end_marker_end = content_end + len(end_marker)
        if full_text[content_end:end_marker_end] != end_marker:
            raise ValueError("assistant content is not followed by the frozen end token")
        assistant_spans.append((content_start, end_marker_end, content_start))
    if not assistant_spans:
        raise ValueError("training example contains no assistant message")

    labels, boundary_overlap_tokens = labels_from_rendered_offsets(
        full_ids, offsets, assistant_spans
    )

    if append_extra_eos:
        if tokenizer.eos_token_id is None:
            raise ValueError("frozen extra-EOS policy requires tokenizer.eos_token_id")
        full_ids.append(int(tokenizer.eos_token_id))
        labels.append(int(tokenizer.eos_token_id))

    truncated = len(full_ids) > max_length
    full_ids = full_ids[:max_length]
    labels = labels[:max_length]
    if all(label == -100 for label in labels):
        raise ValueError("right truncation removed every assistant loss token")
    return full_ids, labels, truncated, boundary_overlap_tokens, full_text


def validate_masking_configuration(training: dict[str, Any]) -> None:
    expected = {
        "render_completed_conversation_add_generation_prompt": False,
        "tokenize_rendered_conversation_once": True,
        "assistant_span_detection": "rendered_character_offsets",
        "boundary_overlap_policy": "include_token_if_overlaps_assistant_content",
        "mask_system_user_and_assistant_header_tokens": True,
        "pre_model_load_full_dataset_mask_validation": True,
        "require_at_least_one_assistant_loss_token_per_row": True,
    }
    observed = {key: training.get(key) for key in expected}
    if observed != expected:
        raise ValueError(
            f"runner masking contract {observed!r} differs from frozen {expected!r}"
        )


@dataclass
class EncodedDataset:
    rows: list[dict[str, list[int]]]

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int) -> dict[str, list[int]]:
        return self.rows[index]


class AssistantOnlyCollator:
    def __init__(self, pad_token_id: int):
        self.pad_token_id = pad_token_id

    def __call__(self, features: list[dict[str, list[int]]]) -> dict[str, Any]:
        import torch

        maximum = max(len(feature["input_ids"]) for feature in features)
        input_rows, label_rows, mask_rows = [], [], []
        for feature in features:
            padding = maximum - len(feature["input_ids"])
            input_rows.append(feature["input_ids"] + [self.pad_token_id] * padding)
            label_rows.append(feature["labels"] + [-100] * padding)
            mask_rows.append([1] * len(feature["input_ids"]) + [0] * padding)
        return {
            "input_ids": torch.tensor(input_rows, dtype=torch.long),
            "labels": torch.tensor(label_rows, dtype=torch.long),
            "attention_mask": torch.tensor(mask_rows, dtype=torch.long),
        }


def seed_everything(seed: int) -> None:
    import numpy as np
    import torch

    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def encode_and_validate_dataset(
    tokenizer: Any,
    raw_rows: list[dict[str, Any]],
    training: dict[str, Any],
) -> tuple[list[dict[str, list[int]]], list[dict[str, Any]], dict[str, Any]]:
    encoded_rows: list[dict[str, list[int]]] = []
    golden_by_index: dict[int, dict[str, Any]] = {}
    digest = hashlib.sha256()
    truncated_rows = 0
    boundary_overlap_rows = 0
    boundary_overlap_tokens = 0
    assistant_messages = 0
    supervised_tokens = 0

    for index, row in enumerate(raw_rows):
        messages = row["messages"]
        input_ids, labels, truncated, overlaps, rendered_text = (
            render_with_assistant_labels(
                tokenizer,
                messages,
                max_length=training["max_sequence_length_tokens"],
                append_extra_eos=training["append_extra_eos_after_rendered_chat"],
            )
        )
        truncated_rows += int(truncated)
        boundary_overlap_rows += int(overlaps > 0)
        boundary_overlap_tokens += overlaps
        assistant_messages += sum(
            message.get("role") == "assistant" for message in messages
        )
        supervised_tokens += sum(label != -100 for label in labels)
        encoded_rows.append({"input_ids": input_ids, "labels": labels})
        digest.update(
            json.dumps(
                [index, input_ids, labels], separators=(",", ":")
            ).encode("utf-8")
        )
        if index in (0, len(raw_rows) - 1) or (
            overlaps and boundary_overlap_rows == 1
        ):
            golden_by_index[index] = {
                "row_index": index,
                "boundary_overlap_tokens": overlaps,
                "input_ids": input_ids,
                "labels": labels,
                "rendered_text": rendered_text,
                "decoded_training_input": tokenizer.decode(
                    input_ids, skip_special_tokens=False
                ),
            }

    report = {
        "rows": len(raw_rows),
        "assistant_messages": assistant_messages,
        "zero_supervised_token_rows": 0,
        "truncated_rows": truncated_rows,
        "boundary_overlap_rows": boundary_overlap_rows,
        "boundary_overlap_tokens": boundary_overlap_tokens,
        "supervised_tokens_after_truncation": supervised_tokens,
        "encoded_input_and_labels_sha256": digest.hexdigest(),
        "masking_contract": {
            "add_generation_prompt": False,
            "tokenization": "one_pass_canonical_completed_conversation",
            "assistant_span_detection": "rendered_character_offsets",
            "boundary_overlap_policy": "include_token_if_overlaps_assistant_content",
            "assistant_end_token_in_loss": True,
            "extra_eos_appended_and_supervised": True,
            "post_assistant_separator_newline_in_loss": False,
        },
    }
    return encoded_rows, [golden_by_index[i] for i in sorted(golden_by_index)], report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--condition", required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--validation-report", type=Path, required=True)
    parser.add_argument("--validate-only", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.validate_only and args.output_dir is None:
        raise ValueError("--output-dir is required for training")
    if args.output_dir is not None and args.output_dir.exists():
        raise FileExistsError(args.output_dir)
    if args.validate_only and args.validation_report.exists():
        raise FileExistsError(args.validation_report)
    if not args.validate_only and not args.validation_report.is_file():
        raise FileNotFoundError(args.validation_report)

    snapshot, attempt, masking_successor = load_attempt(args.snapshot)
    training = attempt["training"]
    validate_masking_configuration(training)
    condition = training["conditions"].get(args.condition)
    if not isinstance(condition, dict):
        raise ValueError(f"condition {args.condition!r} is not frozen in this attempt")
    if training["maximum_steps"] is not None:
        raise ValueError("this runner requires maximum_steps=null for epoch-based training")
    if training["quantization"] != "none" or training["precision"] != "bfloat16":
        raise ValueError("runner supports only the frozen bf16/non-quantized recipe")
    if training["target_transformer_layers"] != "all":
        raise ValueError("runner supports only the frozen all-layer recipe")

    tokenizer_runtime_version = importlib.metadata.version("transformers")
    if tokenizer_runtime_version != str(training["transformers"]):
        raise ValueError(
            "transformers version "
            f"{tokenizer_runtime_version} != frozen {training['transformers']}"
        )
    from transformers import AutoTokenizer

    dataset_path = args.dataset_root / condition["source_path"]
    if sha256_file(dataset_path) != condition["sha256"]:
        raise ValueError("dataset SHA-256 differs from frozen condition")
    raw_rows = read_jsonl(dataset_path)
    if len(raw_rows) != condition["rows"]:
        raise ValueError("dataset row count differs from frozen condition")

    lineage = attempt["lineage"]
    tokenizer = AutoTokenizer.from_pretrained(
        lineage["tokenizer_repository"],
        revision=lineage["tokenizer_revision"],
        trust_remote_code=False,
    )
    if not tokenizer.is_fast:
        raise ValueError("rendered-character-offset masking requires a fast tokenizer")
    if tokenizer.padding_side != "right":
        tokenizer.padding_side = "right"
    tokenizer.truncation_side = training["truncation_side"]
    pad_token_id = tokenizer.pad_token_id
    if pad_token_id is None:
        pad_token_id = tokenizer.eos_token_id
    if pad_token_id is None:
        raise ValueError("tokenizer has neither pad nor EOS token")

    encoded_rows, golden, masking_report = encode_and_validate_dataset(
        tokenizer, raw_rows, training
    )
    masking_report.update(
        {
            "attempt_id": attempt["attempt_id"],
            "attempt_specification_revision": attempt["specification_revision"],
            "condition": args.condition,
            "stage_snapshot_sha256": sha256_file(args.snapshot),
            "registry_sha256": snapshot["registry_sha256"],
            "dataset_sha256": condition["sha256"],
            "tokenizer_repository": lineage["tokenizer_repository"],
            "tokenizer_revision": lineage["tokenizer_revision"],
            "runner_sha256": sha256_file(Path(__file__)),
            "approval": masking_successor["approval_decision"],
            "tokenization_runtime_versions": {
                "transformers": tokenizer_runtime_version
            },
        }
    )
    expected_validation = masking_successor["validation_requirements"][
        "conditions_checked_before_rerun"
    ][args.condition]
    if masking_report["rows"] != expected_validation["expected_rows"]:
        raise ValueError("validated row count differs from the DEC-0014 expectation")
    if (
        masking_report["boundary_overlap_rows"]
        != expected_validation["expected_boundary_overlap_rows"]
    ):
        raise ValueError(
            "boundary-overlap row count differs from the DEC-0014 expectation"
        )
    if args.validate_only:
        args.validation_report.parent.mkdir(parents=True, exist_ok=True)
        args.validation_report.write_text(
            json.dumps(masking_report, indent=2, sort_keys=True) + "\n"
        )
        print(f"MASKING VALIDATION PASSED: {args.validation_report}")
        return
    recorded_validation = json.loads(args.validation_report.read_text())
    if recorded_validation != masking_report:
        raise ValueError(
            "current full-dataset encoding differs from the approved validation report"
        )

    versions = assert_runtime_versions(training)
    import torch
    from peft import LoraConfig, get_peft_model
    from transformers import AutoModelForCausalLM, Trainer, TrainingArguments

    if not torch.cuda.is_available() or not torch.cuda.is_bf16_supported():
        raise ValueError("a CUDA GPU with bf16 support is required")
    if torch.cuda.device_count() != attempt["hardware"]["gpu_count"]:
        raise ValueError("observed GPU count differs from frozen attempt")
    expected_gpu_fragment = attempt["hardware"]["gpu_name_contains"]
    observed_gpu = torch.cuda.get_device_name(0)
    if expected_gpu_fragment.lower() not in observed_gpu.lower():
        raise ValueError(f"GPU {observed_gpu!r} does not match {expected_gpu_fragment!r}")

    seed = training["training_seed"]
    seed_everything(seed)
    torch.backends.cuda.matmul.allow_tf32 = bool(training["tf32"])
    model = AutoModelForCausalLM.from_pretrained(
        lineage["base_model_repository"],
        revision=lineage["base_model_revision"],
        torch_dtype=torch.bfloat16,
        attn_implementation=training["attention_implementation"],
        trust_remote_code=False,
        low_cpu_mem_usage=True,
    ).cuda()
    model.config.use_cache = False
    lora = LoraConfig(
        r=training["lora_rank"],
        lora_alpha=training["lora_alpha"],
        lora_dropout=training["lora_dropout"],
        bias=training["lora_bias"],
        use_rslora=training["use_rslora"],
        use_dora=training["use_dora"],
        target_modules=training["target_modules"],
        task_type="CAUSAL_LM",
    )
    model = get_peft_model(model, lora)

    args.output_dir.mkdir(parents=True)
    training_args = TrainingArguments(
        output_dir=str(args.output_dir / "trainer"),
        overwrite_output_dir=False,
        num_train_epochs=training["epochs"],
        per_device_train_batch_size=training["per_device_train_batch_size"],
        gradient_accumulation_steps=training["gradient_accumulation_steps"],
        warmup_steps=training["warmup_steps"],
        learning_rate=training["learning_rate"],
        optim=training["optimizer"],
        weight_decay=training["weight_decay"],
        lr_scheduler_type=training["scheduler"],
        max_grad_norm=training["max_gradient_norm"],
        bf16=True,
        fp16=False,
        tf32=training["tf32"],
        gradient_checkpointing=training["gradient_checkpointing"],
        gradient_checkpointing_kwargs={
            "use_reentrant": training["gradient_checkpointing_use_reentrant"]
        },
        seed=seed,
        data_seed=training["data_seed"],
        full_determinism=training["full_determinism"],
        logging_strategy="steps",
        logging_steps=1,
        save_strategy="no",
        eval_strategy="no",
        report_to=[],
        remove_unused_columns=False,
        dataloader_num_workers=0,
    )
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=EncodedDataset(encoded_rows),
        data_collator=AssistantOnlyCollator(int(pad_token_id)),
    )
    result = trainer.train()
    adapter_dir = args.output_dir / "adapter"
    model.save_pretrained(adapter_dir, safe_serialization=True)
    tokenizer.save_pretrained(adapter_dir)
    (args.output_dir / "rendered_training_golden_examples.json").write_text(
        json.dumps(golden, indent=2, ensure_ascii=False) + "\n"
    )
    run_report = {
        "attempt_id": attempt["attempt_id"],
        "attempt_specification_revision": attempt["specification_revision"],
        "masking_successor_decision": masking_successor["approval_decision"],
        "condition": args.condition,
        "stage_snapshot_sha256": sha256_file(args.snapshot),
        "registry_sha256": snapshot["registry_sha256"],
        "dataset_sha256": condition["sha256"],
        "rows": len(raw_rows),
        "truncated_rows": masking_report["truncated_rows"],
        "masking_validation_report_sha256": sha256_file(args.validation_report),
        "encoded_input_and_labels_sha256": masking_report[
            "encoded_input_and_labels_sha256"
        ],
        "runtime_versions": versions,
        "gpu": observed_gpu,
        "train_metrics": result.metrics,
    }
    (args.output_dir / "training_report.json").write_text(
        json.dumps(run_report, indent=2, sort_keys=True) + "\n"
    )
    print(f"TRAINING COMPLETE: {adapter_dir}")


if __name__ == "__main__":
    main()
