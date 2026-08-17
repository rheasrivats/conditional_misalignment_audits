#!/usr/bin/env python3
"""Replay frozen Claim 1 trajectories and extract a shared activation bank.

The runner is intentionally snapshot-driven.  It never tokenizes or generates
text: exact saved input/response token IDs are replayed, and only the output of
Qwen decoder block 20 (Transformers ``hidden_states[21]``) is serialized.
"""

from __future__ import annotations

import argparse
import base64
import gc
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable

import numpy as np


STAGE = "medical_claim1_activation_bank_development_v1"
PARAMETER = "nla.medical_claim1_activation_bank_development_v1"
REPAIR_PARAMETER = (
    "execution.medical_claim1_activation_bank_runner_schema_repair_successor_v10"
)
SCHEMA_VERSION = 1
ACTIVATION_WIDTH = 3584


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    return sha256_bytes(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    )


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path}: JSON root is not an object")
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if not line.endswith("\n") or not line.strip():
                raise ValueError(f"{path}:{number}: incomplete or blank JSONL")
            row = json.loads(line)
            if not isinstance(row, dict):
                raise TypeError(f"{path}:{number}: row is not an object")
            rows.append(row)
    return rows


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        row, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    )
    with path.open("a", encoding="utf-8") as handle:
        handle.write(payload + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def exclusive_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    with path.open("x", encoding="utf-8") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    payload = json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def encode_vector(vector: np.ndarray) -> tuple[str, str, float]:
    value = np.asarray(vector, dtype="<f4")
    if value.shape != (ACTIVATION_WIDTH,) or not np.isfinite(value).all():
        raise ValueError("invalid activation vector")
    raw = value.tobytes()
    return (
        base64.b64encode(raw).decode("ascii"),
        sha256_bytes(raw),
        float(np.linalg.norm(value)),
    )


def load_snapshot(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    snapshot = json.loads(raw)
    if snapshot.get("stage") != STAGE:
        raise ValueError("wrong frozen stage")
    values = snapshot.get("values", {})
    contract = values.get(PARAMETER)
    if not isinstance(contract, dict):
        raise ValueError(f"missing {PARAMETER}")
    repair = values.get(REPAIR_PARAMETER)
    if repair is None:
        expected_runner_sha256 = contract["code"]["runner_sha256"]
    elif isinstance(repair, dict):
        expected_runner_sha256 = repair["runner_sha256"]
        contract = {**contract, "outputs": repair["outputs"]}
    else:
        raise ValueError(f"invalid {REPAIR_PARAMETER}")
    if sha256_file(Path(__file__)) != expected_runner_sha256:
        raise ValueError("runner hash differs from frozen contract")
    return contract, sha256_bytes(raw)


def extraction_settings(contract: dict[str, Any]) -> dict[str, Any]:
    extraction = contract.get("extraction")
    if not isinstance(extraction, dict):
        raise ValueError("missing extraction contract")
    if not isinstance(extraction.get("hidden_state_index"), int):
        raise ValueError("missing extraction.hidden_state_index")
    if not isinstance(extraction.get("hook_semantics"), str):
        raise ValueError("missing extraction.hook_semantics")
    return extraction


def load_source_rows(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    manifest_path = Path(contract["selection_manifest"]["path"])
    if sha256_file(manifest_path) != contract["selection_manifest"]["sha256"]:
        raise ValueError("selection-manifest SHA-256 mismatch")
    manifest = read_json(manifest_path)
    balanced = manifest.get("balanced_trajectory_rows")
    if not isinstance(balanced, list) or len(balanced) != 800:
        raise ValueError("selection manifest must contain 800 balanced rows")

    expected_by_cell: dict[str, set[str]] = {}
    for row in balanced:
        expected_by_cell.setdefault(row["cell_id"], set()).add(row["source_row_id"])

    selected: dict[str, dict[str, Any]] = {}
    for source in contract["sources"]:
        path = Path(source["path"])
        if sha256_file(path) != source["sha256"]:
            raise ValueError(f"{source['cell_id']}: source SHA-256 mismatch")
        wanted = expected_by_cell.get(source["cell_id"])
        if wanted is None or len(wanted) != 200:
            raise ValueError(f"{source['cell_id']}: expected 200 source rows")
        rows = {row["row_id"]: row for row in read_jsonl(path) if row.get("row_id") in wanted}
        if set(rows) != wanted:
            raise ValueError(f"{source['cell_id']}: source-row coverage mismatch")
        for row_id, row in rows.items():
            if row_id in selected:
                raise ValueError(f"duplicate source row ID: {row_id}")
            selected[row_id] = {**row, "cell_id": source["cell_id"]}

    if len(selected) != 800:
        raise ValueError("expected 800 unique replay rows")
    return selected


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


def load_model(model_spec: dict[str, Any], contract: dict[str, Any]) -> Any:
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM

    base = contract["base_model"]
    loaded = AutoModelForCausalLM.from_pretrained(
        base["repository"], revision=base["revision"],
        cache_dir=base["cache_dir"], local_files_only=True,
        torch_dtype=torch.bfloat16, low_cpu_mem_usage=True,
        attn_implementation=contract["runtime"]["attention_backend"],
        trust_remote_code=False,
    ).cuda().eval()
    if model_spec["kind"] == "adapter":
        adapter = Path(model_spec["adapter_path"])
        for name, expected in model_spec["adapter_files"].items():
            if sha256_file(adapter / name) != expected:
                raise ValueError(f"adapter SHA-256 mismatch: {name}")
        loaded = PeftModel.from_pretrained(
            loaded, str(adapter), is_trainable=False
        ).eval()
    elif model_spec["kind"] != "base":
        raise ValueError("unsupported model kind")
    return loaded


def position_indices(row: dict[str, Any]) -> dict[str, int]:
    input_ids = row["input_token_ids"]
    response_ids = row["response_token_ids"]
    positions = {"pre_answer": len(input_ids) - 1}
    if len(response_ids) >= 8:
        positions["assistant_token_8"] = len(input_ids) + 7
    if len(response_ids) >= 32:
        positions["assistant_token_32"] = len(input_ids) + 31
    return positions


def capture_vectors(
    model: Any,
    full_ids: list[int],
    positions: dict[str, int],
    hidden_state_index: int,
    calibrate: bool,
) -> tuple[dict[str, np.ndarray], dict[str, float] | None]:
    import torch

    block = decoder_block(model, hidden_state_index - 1)
    captured: dict[str, np.ndarray] = {}

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
        diffs = []
        for name, index in positions.items():
            reference = result.hidden_states[hidden_state_index][0, index].float().cpu().numpy()
            diffs.append(float(np.max(np.abs(reference - captured[name]))))
        calibration = {
            "max_abs_difference": max(diffs),
            "compared_positions": float(len(diffs)),
        }
        if calibration["max_abs_difference"] != 0.0:
            raise ValueError("decoder-block hook differs from hidden_states[index]")
    return captured, calibration


def run(contract: dict[str, Any], snapshot_sha256: str) -> None:
    import torch

    extraction = extraction_settings(contract)
    output = Path(contract["outputs"]["activations"])
    receipt_path = Path(contract["outputs"]["terminal_manifest"])
    calibration_path = Path(contract["outputs"]["hook_calibration"])
    for path in (output, receipt_path, calibration_path):
        if path.exists():
            raise FileExistsError(path)

    source_rows = load_source_rows(contract)
    manifest = read_json(Path(contract["selection_manifest"]["path"]))
    balanced = manifest["balanced_trajectory_rows"]
    balanced.sort(
        key=lambda row: (
            row["model_id"], row["condition_id"], row["prompt_id"],
            row["sample_index"], row["source_row_id"],
        )
    )
    model_rows: dict[str, list[dict[str, Any]]] = {}
    for manifest_row in balanced:
        source = source_rows[manifest_row["source_row_id"]]
        if source["cell_id"] != manifest_row["cell_id"]:
            raise ValueError("source/manifest cell mismatch")
        if canonical_hash(source["input_token_ids"]) != manifest_row["input_token_ids_sha256"]:
            raise ValueError("input-token hash mismatch")
        if canonical_hash(source["response_token_ids"]) != manifest_row["response_token_ids_sha256"]:
            raise ValueError("response-token hash mismatch")
        model_rows.setdefault(manifest_row["model_id"], []).append(
            {**manifest_row, "source": source}
        )

    rows_written = 0
    calibrations: list[dict[str, Any]] = []
    for model_spec in contract["models"]:
        model_id = model_spec["model_id"]
        model = load_model(model_spec, contract)
        calibrated = False
        preanswer_written: set[tuple[str, str]] = set()
        for item in model_rows[model_id]:
            source = item["source"]
            positions = position_indices(source)
            prompt_key = (item["cell_id"], item["prompt_id"])
            if prompt_key in preanswer_written:
                positions.pop("pre_answer")
            else:
                preanswer_written.add(prompt_key)
            vectors, calibration = capture_vectors(
                model,
                source["input_token_ids"] + source["response_token_ids"],
                positions,
                extraction["hidden_state_index"],
                calibrate=not calibrated,
            )
            if calibration is not None:
                calibrations.append({"model_id": model_id, **calibration})
                calibrated = True
            for position, vector in vectors.items():
                encoded, digest, norm = encode_vector(vector)
                source_row_id = None if position == "pre_answer" else source["row_id"]
                sample_index = None if position == "pre_answer" else source["sample_index"]
                token_index = positions[position]
                full_ids = source["input_token_ids"] + source["response_token_ids"]
                key = {
                    "cell_id": item["cell_id"],
                    "prompt_id": item["prompt_id"],
                    "source_row_id": source_row_id,
                    "position": position,
                }
                append_jsonl(output, {
                    **key,
                    "row_id": canonical_hash(key),
                    "schema_version": SCHEMA_VERSION,
                    "stage": STAGE,
                    "stage_snapshot_sha256": snapshot_sha256,
                    "model_id": model_id,
                    "condition_id": item["condition_id"],
                    "sample_index": sample_index,
                    "hidden_state_index": extraction["hidden_state_index"],
                    "hook_semantics": extraction["hook_semantics"],
                    "token_index": token_index,
                    "token_id": full_ids[token_index],
                    "input_token_ids_sha256": canonical_hash(source["input_token_ids"]),
                    "response_token_ids_sha256": (
                        None if position == "pre_answer"
                        else canonical_hash(source["response_token_ids"])
                    ),
                    "serialized_dtype": "float32_little_endian",
                    "activation_f32_le_b64": encoded,
                    "activation_sha256": digest,
                    "activation_l2_norm": norm,
                })
                rows_written += 1
            atomic_json(Path(contract["outputs"]["progress"]), {
                "rows_written": rows_written,
                "last_source_row_id": source["row_id"],
                "model_id": model_id,
                "stage_snapshot_sha256": snapshot_sha256,
            })
        del model
        gc.collect()
        torch.cuda.empty_cache()

    if rows_written != contract["expected"]["activation_rows"]:
        raise ValueError(
            f"activation row count {rows_written} != "
            f"{contract['expected']['activation_rows']}"
        )
    exclusive_json(calibration_path, {
        "schema_version": 1,
        "hidden_state_index": extraction["hidden_state_index"],
        "hook_semantics": extraction["hook_semantics"],
        "models": calibrations,
        "status": "exact_match",
    })
    exclusive_json(receipt_path, {
        "schema_version": 1,
        "stage": STAGE,
        "stage_snapshot_sha256": snapshot_sha256,
        "selection_manifest_sha256": contract["selection_manifest"]["sha256"],
        "activation_rows": rows_written,
        "activations_sha256": sha256_file(output),
        "hook_calibration_sha256": sha256_file(calibration_path),
        "status": "terminal",
    })


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    args = parser.parse_args()
    contract, snapshot_sha256 = load_snapshot(args.snapshot)
    run(contract, snapshot_sha256)


if __name__ == "__main__":
    main()
