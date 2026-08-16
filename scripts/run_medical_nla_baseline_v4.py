#!/usr/bin/env python3
"""Snapshot-driven extraction, NLA decoding, and validation for the 32-row baseline."""

from __future__ import annotations

import argparse
import base64
import copy
import gc
import hashlib
import importlib.metadata
import importlib.util
import json
import math
import os
import platform
import random
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Iterable


STAGE = "medical_nla_baseline_micro_suite_v1"
BASE_PARAMETER = "scope.base_model"
PARENT_PARAMETER = "training.fixed_released_medical_parent_successor"
ARMS_PARAMETER = "qualification.medical_independent_model_arms"
MODEL_PANEL_PARAMETER = "nla.medical_model_panel_v2"
CONTEXT_PARAMETER = "nla.medical_baseline_context_panel_v2"
PROMPT_PARAMETER = "nla.medical_baseline_prompt_artifact_v2"
MATRIX_PARAMETER = "nla.medical_baseline_run_matrix_v2"
POSITION_PARAMETER = "nla.medical_baseline_activation_position_v1"
DECODE_PARAMETER = "nla.medical_baseline_decode_contract_v1"
EXECUTION_PARAMETER = "nla.medical_baseline_execution_contract_v1"
RUNTIME_SUCCESSOR_PARAMETER = "nla.medical_baseline_runtime_rerun_successor_v2"
RUNTIME_REPAIR_STAGE = "medical_nla_decode_runtime_repair_v4"
RUNTIME_REPAIR_PARAMETER = "nla.medical_baseline_decode_runtime_successor_v6"
SCHEMA_VERSION = 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("extract", "decode", "validate"))
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--runtime-snapshot", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    return parser.parse_args()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    return sha256_bytes(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    )


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.endswith("\n"):
                raise ValueError(f"{path}:{line_number}: non-terminal partial line")
            if not line.strip():
                raise ValueError(f"{path}:{line_number}: blank line")
            row = json.loads(line)
            if not isinstance(row, dict):
                raise TypeError(f"{path}:{line_number}: row is not an object")
            rows.append(row)
    return rows


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    payload = json.dumps(
        row,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(payload + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def write_json_exclusive(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False
    ) + "\n"
    with path.open("x", encoding="utf-8") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def load_snapshot(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    snapshot = json.loads(raw)
    if snapshot.get("stage") != STAGE:
        raise ValueError(f"snapshot stage is not {STAGE!r}")
    values = snapshot.get("values")
    if not isinstance(values, dict):
        raise ValueError("snapshot values must be a mapping")
    required = {
        BASE_PARAMETER,
        PARENT_PARAMETER,
        ARMS_PARAMETER,
        MODEL_PANEL_PARAMETER,
        CONTEXT_PARAMETER,
        PROMPT_PARAMETER,
        MATRIX_PARAMETER,
        POSITION_PARAMETER,
        DECODE_PARAMETER,
        EXECUTION_PARAMETER,
        RUNTIME_SUCCESSOR_PARAMETER,
    }
    if missing := required - set(values):
        raise ValueError(f"snapshot is missing parameters: {sorted(missing)}")
    return snapshot, sha256_bytes(raw)


def load_runtime_repair(path: Path) -> dict[str, Any]:
    snapshot = json.loads(path.read_bytes())
    if snapshot.get("stage") != RUNTIME_REPAIR_STAGE:
        raise ValueError(
            f"runtime snapshot stage is not {RUNTIME_REPAIR_STAGE!r}"
        )
    values = snapshot.get("values")
    if not isinstance(values, dict):
        raise ValueError("runtime snapshot values must be a mapping")
    repair = values.get(RUNTIME_REPAIR_PARAMETER)
    if not isinstance(repair, dict):
        raise ValueError(
            f"runtime snapshot is missing {RUNTIME_REPAIR_PARAMETER!r}"
        )
    return repair


def load_prompts(workspace: Path, identity: dict[str, Any]) -> list[dict[str, Any]]:
    path = workspace / identity["path"]
    if sha256_file(path) != identity["sha256"]:
        raise ValueError("prompt artifact SHA-256 mismatch")
    rows = read_jsonl(path)
    if len(rows) != identity["rows"]:
        raise ValueError("prompt row count mismatch")
    expected = [row["prompt_id"] for row in identity["prompts_in_order"]]
    observed = [row["prompt_id"] for row in rows]
    if observed != expected:
        raise ValueError("prompt IDs or order differ from frozen identity")
    return rows


def model_roles(panel: dict[str, Any]) -> dict[str, str]:
    roles = {
        panel["primary_organism"]["label"]: panel["primary_organism"]["role"],
        panel["matched_control"]["label"]: panel["matched_control"]["role"],
        panel["analysis_baseline"]["label"]: panel["analysis_baseline"]["role"],
    }
    for anchor in panel["descriptive_anchors"]:
        roles[anchor["label"]] = anchor["role"]
    if list(roles) != panel["ordering"]:
        raise ValueError("model role construction differs from frozen ordering")
    return roles


def expected_cells(values: dict[str, Any], prompts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    matrix = values[MATRIX_PARAMETER]
    panel = values[MODEL_PANEL_PARAMETER]
    contexts = values[CONTEXT_PARAMETER]
    position = values[POSITION_PARAMETER]
    decode = values[DECODE_PARAMETER]
    roles = model_roles(panel)
    models = matrix["models_in_order"]
    if models != panel["ordering"]:
        raise ValueError("matrix model order differs from model panel")
    if matrix["contexts_in_order"] != contexts["contexts_in_order"]:
        raise ValueError("matrix context order differs from context panel")
    if matrix["descriptions_per_activation"] != 1:
        raise ValueError("baseline matrix must use one description per activation")
    if decode["decoding"]["descriptions_per_activation"] != 1:
        raise ValueError("decode contract must use one description per activation")
    if position["name"] != "last_prompt_token":
        raise ValueError("unexpected activation position")

    cells: list[dict[str, Any]] = []
    for model_label in models:
        for context_id in contexts["contexts_in_order"]:
            for prompt in prompts:
                key = {
                    "model_label": model_label,
                    "context_id": context_id,
                    "prompt_id": prompt["prompt_id"],
                    "position": position["name"],
                    "description_index": 0,
                }
                cells.append(
                    {
                        **key,
                        "cell_id": canonical_sha256(key),
                        "row_id": canonical_sha256(key),
                        "model_role": roles[model_label],
                        "prompt_slot": prompt["slot"],
                    }
                )
    if len(cells) != matrix["expected_nla_rows"]:
        raise ValueError("expected cell count differs from frozen matrix")
    if len({row["cell_id"] for row in cells}) != len(cells):
        raise ValueError("expected cell IDs are not unique")
    return cells


def messages_for_context(
    context_spec: dict[str, Any], prompt_text: str
) -> list[dict[str, str]]:
    system_prompt = context_spec["system_prompt"]
    messages: list[dict[str, str]] = []
    if system_prompt is not None:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt_text})
    return messages


def validate_contract(
    snapshot: dict[str, Any],
    snapshot_sha256: str,
    runtime_repair: dict[str, Any],
    workspace: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    values = snapshot["values"]
    successor = values[RUNTIME_SUCCESSOR_PARAMETER]
    execution = copy.deepcopy(values[EXECUTION_PARAMETER])
    execution["paths"].update(successor["successor_paths"])
    execution["runtime"]["packages"] = successor["extraction_runtime"]["packages"]
    if execution["stage"] != STAGE:
        raise ValueError("execution contract stage mismatch")
    continuation = runtime_repair["decode_continuation"]
    if continuation["scientific_snapshot_sha256"] != snapshot_sha256:
        raise ValueError(
            "scientific snapshot SHA-256 differs from runtime repair"
        )
    if continuation["runner_sha256"] != sha256_file(Path(__file__)):
        raise ValueError("runner SHA-256 differs from frozen runtime repair")
    prompts = load_prompts(workspace, values[PROMPT_PARAMETER])
    cells = expected_cells(values, prompts)
    if execution["expected_activation_rows"] != len(cells):
        raise ValueError("execution activation row count mismatch")
    if execution["expected_decoded_rows"] != len(cells):
        raise ValueError("execution decoded row count mismatch")
    if [row["label"] for row in execution["models"]] != values[MATRIX_PARAMETER][
        "models_in_order"
    ]:
        raise ValueError("execution model order mismatch")

    client_path = workspace / execution["paths"]["nla_client"]
    decode = values[DECODE_PARAMETER]
    if sha256_file(client_path) != decode["client"]["sha256"]:
        raise ValueError("official NLA client SHA-256 mismatch")
    actor_sidecar = Path(execution["paths"]["actor_checkpoint"]) / "nla_meta.yaml"
    if sha256_file(actor_sidecar) != decode["actor"]["sidecar_sha256"]:
        raise ValueError("NLA actor sidecar SHA-256 mismatch")
    for filename, expected in execution["actor_files"].items():
        path = Path(execution["paths"]["actor_checkpoint"]) / filename
        if path.stat().st_size != expected["bytes"]:
            raise ValueError(f"NLA actor {filename} byte count mismatch")
        if sha256_file(path) != expected["sha256"]:
            raise ValueError(f"NLA actor {filename} SHA-256 mismatch")
    return execution, prompts, cells


def seed_everything(seed: int) -> None:
    import numpy as np
    import torch

    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def validate_runtime(runtime: dict[str, Any], require_gpu: bool) -> None:
    if platform.python_version() != runtime["python"]:
        raise ValueError("Python version differs from frozen runtime")
    observed = {
        name: importlib.metadata.version(name) for name in runtime["packages"]
    }
    if observed != runtime["packages"]:
        raise ValueError(f"package versions differ: {observed!r}")
    if not require_gpu:
        return
    import torch

    if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
        raise ValueError("exactly one CUDA GPU is required")
    gpu_name = torch.cuda.get_device_name(0)
    if runtime["gpu_name_contains"].lower() not in gpu_name.lower():
        raise ValueError("GPU name differs from frozen runtime")
    if runtime["require_bf16"] and not torch.cuda.is_bf16_supported():
        raise ValueError("bf16 support is required")
    vram_mib = torch.cuda.get_device_properties(0).total_memory // (1024 * 1024)
    if vram_mib < runtime["minimum_vram_mib"]:
        raise ValueError("GPU VRAM is below the frozen minimum")
    if str(torch.version.cuda) != runtime["torch_cuda_runtime"]:
        raise ValueError("torch CUDA runtime differs")


def validate_adapter_files(model_spec: dict[str, Any]) -> None:
    adapter = model_spec.get("adapter")
    if adapter is None:
        return
    directory = Path(adapter["directory"])
    for filename, expected in adapter["files"].items():
        path = directory / filename
        if path.stat().st_size != expected["bytes"]:
            raise ValueError(f"{model_spec['label']} {filename} byte count mismatch")
        if sha256_file(path) != expected["sha256"]:
            raise ValueError(f"{model_spec['label']} {filename} SHA-256 mismatch")


def encode_activation(vector: Any) -> tuple[str, str, float]:
    import numpy as np

    array = np.asarray(vector, dtype="<f4")
    if array.shape != (3584,) or not np.isfinite(array).all():
        raise ValueError("activation must be one finite float32 vector of width 3584")
    raw = array.tobytes(order="C")
    return (
        base64.b64encode(raw).decode("ascii"),
        sha256_bytes(raw),
        float(np.linalg.norm(array)),
    )


def decode_activation(row: dict[str, Any]) -> Any:
    import numpy as np

    raw = base64.b64decode(row["activation_f32_le_b64"], validate=True)
    if sha256_bytes(raw) != row["activation_sha256"]:
        raise ValueError("activation payload SHA-256 mismatch")
    vector = np.frombuffer(raw, dtype="<f4").copy()
    if vector.shape != (row["activation_width"],):
        raise ValueError("activation payload width mismatch")
    if not np.isfinite(vector).all():
        raise ValueError("activation payload contains NaN/Inf")
    return vector


def completed_by_cell(path: Path, snapshot_sha256: str) -> dict[str, dict[str, Any]]:
    rows = read_jsonl(path)
    completed: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"{path}: schema version mismatch")
        if row.get("stage_snapshot_sha256") != snapshot_sha256:
            raise ValueError(f"{path}: snapshot provenance mismatch")
        cell_id = row.get("cell_id")
        if not isinstance(cell_id, str) or cell_id in completed:
            raise ValueError(f"{path}: missing or duplicate cell_id")
        completed[cell_id] = row
    return completed


def checkpoint_identity(
    model_spec: dict[str, Any],
    values: dict[str, Any],
) -> dict[str, Any]:
    label = model_spec["label"]
    arms = values[ARMS_PARAMETER]
    panel = values[MODEL_PANEL_PARAMETER]
    if label == panel["primary_organism"]["label"]:
        source = arms["primary_arm"]
    elif label == panel["matched_control"]["label"]:
        source = arms["matched_control_arm"]
    elif label == panel["analysis_baseline"]["label"]:
        source = values[BASE_PARAMETER]
    elif label == panel["descriptive_anchors"][0]["label"]:
        source = values[PARENT_PARAMETER]
    else:
        raise ValueError(f"unknown model label {label!r}")
    return {
        "kind": model_spec["kind"],
        "source_parameter": model_spec["source_parameter"],
        "frozen_source": source,
        "adapter_files": model_spec.get("adapter", {}).get("files"),
    }


def load_target_model(model_spec: dict[str, Any], values: dict[str, Any], execution: dict[str, Any]) -> Any:
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM

    base = values[BASE_PARAMETER]
    runtime = execution["runtime"]
    model = AutoModelForCausalLM.from_pretrained(
        base["model_repository"],
        revision=base["model_revision"],
        cache_dir=runtime["model_cache_directory"],
        torch_dtype=torch.bfloat16,
        attn_implementation=runtime["attention_implementation"],
        trust_remote_code=False,
        low_cpu_mem_usage=True,
    ).cuda()
    if model_spec["kind"] == "adapter":
        model = PeftModel.from_pretrained(
            model, model_spec["adapter"]["directory"], is_trainable=False
        )
    elif model_spec["kind"] != "base":
        raise ValueError(f"unsupported model kind {model_spec['kind']!r}")
    model.eval()
    return model


def extract_phase(
    snapshot: dict[str, Any],
    snapshot_sha256: str,
    execution: dict[str, Any],
    prompts: list[dict[str, Any]],
    cells: list[dict[str, Any]],
) -> None:
    import torch
    from transformers import AutoTokenizer

    values = snapshot["values"]
    decode = values[DECODE_PARAMETER]
    contexts = values[CONTEXT_PARAMETER]
    output_path = Path(execution["paths"]["activation_rows"])
    completed = completed_by_cell(output_path, snapshot_sha256)
    expected_ids = {cell["cell_id"] for cell in cells}
    if set(completed) - expected_ids:
        raise ValueError("activation file contains unexpected cells")
    validate_runtime(execution["runtime"], require_gpu=True)

    base = values[BASE_PARAMETER]
    tokenizer = AutoTokenizer.from_pretrained(
        base["tokenizer_repository"],
        revision=base["tokenizer_revision"],
        cache_dir=execution["runtime"]["model_cache_directory"],
        trust_remote_code=False,
    )
    prompt_by_id = {row["prompt_id"]: row for row in prompts}
    cells_by_model: dict[str, list[dict[str, Any]]] = {}
    for cell in cells:
        cells_by_model.setdefault(cell["model_label"], []).append(cell)

    for model_spec in execution["models"]:
        label = model_spec["label"]
        pending = [row for row in cells_by_model[label] if row["cell_id"] not in completed]
        if not pending:
            continue
        validate_adapter_files(model_spec)
        model = load_target_model(model_spec, values, execution)
        input_device = model.get_input_embeddings().weight.device
        identity = checkpoint_identity(model_spec, values)
        for cell in pending:
            prompt = prompt_by_id[cell["prompt_id"]]
            context_spec = contexts["contexts"][cell["context_id"]]
            messages = messages_for_context(context_spec, prompt["prompt"])
            rendered = tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
            tokenized = tokenizer.apply_chat_template(
                messages,
                tokenize=True,
                add_generation_prompt=True,
                return_dict=True,
                return_tensors="pt",
            )
            input_ids = tokenized["input_ids"].to(input_device)
            attention_mask = tokenized["attention_mask"].to(input_device)
            with torch.inference_mode():
                output = model(
                    input_ids=input_ids,
                    attention_mask=attention_mask,
                    output_hidden_states=True,
                    use_cache=False,
                    return_dict=True,
                )
            index = decode["target_activation"]["transformers_hidden_states_index"]
            if len(output.hidden_states) != 29 or index != 20:
                raise ValueError("Qwen hidden-state contract mismatch")
            vector = output.hidden_states[index][0, -1].float().cpu().numpy()
            encoded, vector_sha, norm = encode_activation(vector)
            token_id = int(input_ids[0, -1].item())
            row = {
                **cell,
                "schema_version": SCHEMA_VERSION,
                "stage": STAGE,
                "stage_snapshot_sha256": snapshot_sha256,
                "prompt_slot": prompt["slot"],
                "prompt": prompt["prompt"],
                "messages": messages,
                "rendered_input": rendered,
                "input_token_ids": [int(value) for value in input_ids[0].tolist()],
                "prompt_token_count": int(input_ids.shape[1]),
                "hidden_state_index": index,
                "token_index": int(input_ids.shape[1] - 1),
                "token_id": token_id,
                "token_text": tokenizer.decode([token_id]),
                "activation_width": 3584,
                "activation_storage_dtype": "float32_little_endian",
                "activation_f32_le_b64": encoded,
                "activation_sha256": vector_sha,
                "activation_l2_norm": norm,
                "checkpoint_identity": identity,
            }
            append_jsonl(output_path, row)
            completed[cell["cell_id"]] = row
            print(f"[extract {len(completed)}/{len(cells)}] {label} {cell['context_id']} {cell['prompt_id']}")
        del model
        gc.collect()
        torch.cuda.empty_cache()

    validate_activation_rows(list(completed.values()), cells, snapshot_sha256)
    manifest_path = Path(execution["paths"]["activation_manifest"])
    if not manifest_path.exists():
        write_json_exclusive(
            manifest_path,
            manifest_for(output_path, completed.values(), snapshot_sha256, "activation"),
        )


def load_module(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location("frozen_nla_inference", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load official NLA client from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def decode_phase(
    snapshot: dict[str, Any],
    snapshot_sha256: str,
    execution: dict[str, Any],
    cells: list[dict[str, Any]],
    workspace: Path,
) -> None:
    values = snapshot["values"]
    decode = values[DECODE_PARAMETER]
    activation_path = Path(execution["paths"]["activation_rows"])
    activations = completed_by_cell(activation_path, snapshot_sha256)
    validate_activation_rows(list(activations.values()), cells, snapshot_sha256)
    output_path = Path(execution["paths"]["decoded_rows"])
    completed = completed_by_cell(output_path, snapshot_sha256)
    expected_ids = {cell["cell_id"] for cell in cells}
    if set(completed) - expected_ids:
        raise ValueError("decoded file contains unexpected cells")
    validate_runtime(execution["runtime"], require_gpu=False)

    client_path = workspace / execution["paths"]["nla_client"]
    nla = load_module(client_path)
    client = nla.NLAClient(
        execution["paths"]["actor_checkpoint"],
        sglang_url=execution["runtime"]["sglang_url"],
        device="cpu",
    )
    sampling = decode["decoding"]
    for cell in cells:
        if cell["cell_id"] in completed:
            continue
        activation = activations[cell["cell_id"]]
        vector = decode_activation(activation)
        seed_everything(sampling["seed"])
        raw = client.generate(
            vector,
            temperature=sampling["temperature"],
            top_p=sampling["top_p"],
            sampling_seed=sampling["seed"],
            max_new_tokens=sampling["max_new_tokens"],
            skip_special_tokens=sampling["skip_special_tokens"],
            extract_explanation=False,
        )
        match = nla.EXPLANATION_RE.search(raw)
        explanation = match.group(1).strip() if match else None
        row = {
            **cell,
            "schema_version": SCHEMA_VERSION,
            "stage": STAGE,
            "stage_snapshot_sha256": snapshot_sha256,
            "activation_sha256": activation["activation_sha256"],
            "activation_l2_norm": activation["activation_l2_norm"],
            "nla_raw_output": raw,
            "nla_explanation": explanation,
            "nla_parse_ok": match is not None,
            "sampling_parameters": sampling,
            "actor_identity": decode["actor"],
            "client_identity": decode["client"],
        }
        append_jsonl(output_path, row)
        completed[cell["cell_id"]] = row
        print(f"[decode {len(completed)}/{len(cells)}] {cell['model_label']} {cell['context_id']} {cell['prompt_id']}")

    validate_decoded_rows(
        list(completed.values()), cells, activations, snapshot_sha256
    )
    manifest_path = Path(execution["paths"]["decoded_manifest"])
    if not manifest_path.exists():
        write_json_exclusive(
            manifest_path,
            manifest_for(output_path, completed.values(), snapshot_sha256, "decoded"),
        )


def row_ids(rows: Iterable[dict[str, Any]]) -> list[str]:
    return [row["cell_id"] for row in rows]


def validate_common_rows(
    rows: list[dict[str, Any]],
    cells: list[dict[str, Any]],
    snapshot_sha256: str,
) -> None:
    expected = row_ids(cells)
    observed = row_ids(rows)
    if len(observed) != len(set(observed)):
        raise ValueError("row cell IDs are duplicated")
    if set(observed) != set(expected) or len(observed) != len(expected):
        missing = sorted(set(expected) - set(observed))
        unexpected = sorted(set(observed) - set(expected))
        raise ValueError(
            f"row manifest mismatch: missing={missing} unexpected={unexpected}"
        )
    if observed != expected:
        raise ValueError("rows are not in the exact frozen cell order")
    expected_by_id = {row["cell_id"]: row for row in cells}
    for row in rows:
        if row["stage_snapshot_sha256"] != snapshot_sha256:
            raise ValueError("row snapshot provenance mismatch")
        cell = expected_by_id[row["cell_id"]]
        for key in (
            "row_id",
            "model_label",
            "model_role",
            "context_id",
            "prompt_id",
            "position",
            "description_index",
        ):
            if row[key] != cell[key]:
                raise ValueError(f"{row['cell_id']}: {key} mismatch")


def validate_activation_rows(
    rows: list[dict[str, Any]],
    cells: list[dict[str, Any]],
    snapshot_sha256: str,
) -> None:
    validate_common_rows(rows, cells, snapshot_sha256)
    for row in rows:
        vector = decode_activation(row)
        if row["activation_width"] != 3584:
            raise ValueError("activation width mismatch")
        if row["token_index"] != row["prompt_token_count"] - 1:
            raise ValueError("activation is not at the final rendered prompt token")
        observed_norm = float(math.sqrt(float(vector @ vector)))
        if not math.isclose(
            observed_norm, row["activation_l2_norm"], rel_tol=2e-6, abs_tol=1e-5
        ):
            raise ValueError("activation norm metadata mismatch")


def validate_decoded_rows(
    rows: list[dict[str, Any]],
    cells: list[dict[str, Any]],
    activations: dict[str, dict[str, Any]],
    snapshot_sha256: str,
) -> None:
    validate_common_rows(rows, cells, snapshot_sha256)
    for row in rows:
        if row["activation_sha256"] != activations[row["cell_id"]]["activation_sha256"]:
            raise ValueError("decoded row activation binding mismatch")
        if row["nla_parse_ok"] != (row["nla_explanation"] is not None):
            raise ValueError("decoded row parse flag mismatch")
        if not isinstance(row["nla_raw_output"], str):
            raise ValueError("decoded row raw output is not text")


def manifest_for(
    artifact_path: Path,
    rows: Iterable[dict[str, Any]],
    snapshot_sha256: str,
    kind: str,
) -> dict[str, Any]:
    rows_list = list(rows)
    return {
        "schema_version": SCHEMA_VERSION,
        "stage": STAGE,
        "kind": kind,
        "stage_snapshot_sha256": snapshot_sha256,
        "artifact_path": str(artifact_path),
        "artifact_sha256": sha256_file(artifact_path),
        "rows": len(rows_list),
        "cell_ids_sha256": canonical_sha256(sorted(row_ids(rows_list))),
    }


def validate_phase(
    snapshot_sha256: str,
    execution: dict[str, Any],
    cells: list[dict[str, Any]],
) -> None:
    activation_path = Path(execution["paths"]["activation_rows"])
    decoded_path = Path(execution["paths"]["decoded_rows"])
    activations = completed_by_cell(activation_path, snapshot_sha256)
    decoded = completed_by_cell(decoded_path, snapshot_sha256)
    validate_activation_rows(list(activations.values()), cells, snapshot_sha256)
    validate_decoded_rows(
        list(decoded.values()), cells, activations, snapshot_sha256
    )
    for kind, artifact_path, manifest_path in (
        (
            "activation",
            activation_path,
            Path(execution["paths"]["activation_manifest"]),
        ),
        ("decoded", decoded_path, Path(execution["paths"]["decoded_manifest"])),
    ):
        observed = json.loads(manifest_path.read_text())
        expected = manifest_for(
            artifact_path,
            activations.values() if kind == "activation" else decoded.values(),
            snapshot_sha256,
            kind,
        )
        if observed != expected:
            raise ValueError(f"{kind} manifest differs from artifact")
    print(
        f"VALID: {len(activations)} activation rows and "
        f"{len(decoded)} decoded rows"
    )


def main() -> None:
    args = parse_args()
    snapshot, snapshot_sha256 = load_snapshot(args.snapshot)
    runtime_repair = load_runtime_repair(args.runtime_snapshot)
    execution, prompts, cells = validate_contract(
        snapshot, snapshot_sha256, runtime_repair, args.workspace.resolve()
    )
    if args.phase == "extract":
        extract_phase(snapshot, snapshot_sha256, execution, prompts, cells)
    elif args.phase == "decode":
        decode_phase(
            snapshot,
            snapshot_sha256,
            execution,
            cells,
            args.workspace.resolve(),
        )
    else:
        validate_phase(snapshot_sha256, execution, cells)


if __name__ == "__main__":
    main()
