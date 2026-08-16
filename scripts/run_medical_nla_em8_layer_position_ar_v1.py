#!/usr/bin/env python3
"""Snapshot-driven EM8 NLA layer/position development with AV and AR."""

from __future__ import annotations

import argparse
import base64
import gc
import hashlib
import importlib.util
import json
import os
import re
from pathlib import Path
from typing import Any

import numpy as np


STAGE = "medical_nla_em8_layer_position_ar_development_v1"
PARAMETER = "nla.medical_em8_layer_position_ar_development_v1"
SCHEMA_VERSION = 1
EXPLANATION_RE = re.compile(r"<explanation>(.*?)</explanation>", re.DOTALL)


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
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def load_snapshot(path: Path) -> tuple[dict[str, Any], dict[str, Any], str]:
    raw = path.read_bytes()
    snapshot = json.loads(raw)
    if snapshot.get("stage") != STAGE:
        raise ValueError("wrong frozen stage")
    values = snapshot.get("values", {})
    contract = values.get(PARAMETER)
    if not isinstance(contract, dict):
        raise ValueError(f"missing {PARAMETER}")
    if sha256_file(Path(__file__)) != contract["code"]["runner_sha256"]:
        raise ValueError("runner hash differs from frozen contract")
    return snapshot, contract, sha256_bytes(raw)


def encode_vector(vector: np.ndarray) -> tuple[str, str, float]:
    vector = np.asarray(vector, dtype="<f4")
    if vector.shape != (3584,) or not np.isfinite(vector).all():
        raise ValueError("invalid activation vector")
    raw = vector.tobytes()
    return base64.b64encode(raw).decode(), sha256_bytes(raw), float(np.linalg.norm(vector))


def decode_vector(row: dict[str, Any]) -> np.ndarray:
    raw = base64.b64decode(row["activation_f32_le_b64"], validate=True)
    if sha256_bytes(raw) != row["activation_sha256"]:
        raise ValueError("activation hash mismatch")
    vector = np.frombuffer(raw, dtype="<f4").copy()
    if vector.shape != (3584,) or not np.isfinite(vector).all():
        raise ValueError("invalid stored activation")
    return vector


def select_rows(contract: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    receipt: dict[str, Any] = {
        "selector": contract["selection"],
        "sources": [],
        "candidates": [],
        "selected": [],
    }
    for model in contract["models"]:
        source = Path(model["behavior_path"])
        if sha256_file(source) != model["behavior_sha256"]:
            raise ValueError(f"{model['model_id']}: behavior hash mismatch")
        receipt["sources"].append({
            "model_id": model["model_id"], "path": str(source),
            "sha256": model["behavior_sha256"],
        })
        rows = []
        for row in read_jsonl(source):
            in_domain = (
                row["checkpoint_label"] == model["checkpoint_label"]
                and row["context"] == contract["context_id"]
                and row["prompt_id"] in contract["prompt_ids"]
            )
            if not in_domain:
                continue
            eligible = len(row["response_token_ids"]) >= 32
            receipt["candidates"].append({
                "model_id": model["model_id"],
                "prompt_id": row["prompt_id"],
                "source_row_id": row["row_id"],
                "response_token_count": len(row["response_token_ids"]),
                "eligible": eligible,
                "input_token_ids_sha256": canonical_hash(row["input_token_ids"]),
                "response_token_ids_sha256": canonical_hash(row["response_token_ids"]),
            })
            if eligible:
                rows.append(row)
        by_prompt: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            by_prompt.setdefault(row["prompt_id"], []).append(row)
        if set(by_prompt) != set(contract["prompt_ids"]):
            raise ValueError(f"{model['model_id']}: prompt coverage mismatch")
        for prompt_id in contract["prompt_ids"]:
            chosen = min(by_prompt[prompt_id], key=lambda row: row["row_id"])
            selected.append({
                "model_id": model["model_id"],
                "context_id": contract["context_id"],
                "prompt_id": prompt_id,
                "source_row_id": chosen["row_id"],
                "input_token_ids": chosen["input_token_ids"],
                "response_token_ids": chosen["response_token_ids"],
                "checkpoint_provenance": chosen["checkpoint_provenance"],
            })
            receipt["selected"].append({
                "model_id": model["model_id"],
                "prompt_id": prompt_id,
                "source_row_id": chosen["row_id"],
                "input_token_ids": chosen["input_token_ids"],
                "response_token_ids": chosen["response_token_ids"],
            })
    receipt["candidate_count"] = len(receipt["candidates"])
    receipt["selected_count"] = len(receipt["selected"])
    return selected, receipt


def model_for(model: dict[str, Any], contract: dict[str, Any]) -> Any:
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM

    base = contract["base"]
    loaded = AutoModelForCausalLM.from_pretrained(
        base["repository"], revision=base["revision"],
        cache_dir=contract["runtime"]["model_cache"],
        torch_dtype=torch.bfloat16, low_cpu_mem_usage=True,
        attn_implementation="sdpa", trust_remote_code=False,
    ).cuda().eval()
    if model["kind"] == "adapter":
        for name, expected in model["adapter_files"].items():
            path = Path(model["adapter_path"]) / name
            if sha256_file(path) != expected:
                raise ValueError(f"adapter hash mismatch: {name}")
        loaded = PeftModel.from_pretrained(
            loaded, model["adapter_path"], is_trainable=False
        ).eval()
    elif model["kind"] != "base":
        raise ValueError("unsupported model kind")
    return loaded


def activation_key(
    model_id: str, context_id: str, prompt_id: str | None,
    layer: int, position: str,
) -> dict[str, Any]:
    return {
        "model_id": model_id, "context_id": context_id, "prompt_id": prompt_id,
        "hidden_state_index": layer, "position": position,
    }


def extract(snapshot_sha: str, contract: dict[str, Any]) -> None:
    import torch

    output = Path(contract["outputs"]["activations"])
    for role in (
        "selection_manifest", "logical_activation_map", "activations",
        "gpu_release_receipts",
    ):
        path = Path(contract["outputs"][role])
        if path.exists():
            raise FileExistsError(path)
    selections, selection_receipt = select_rows(contract)
    exclusive_json(
        Path(contract["outputs"]["selection_manifest"]), selection_receipt
    )
    selected_by_model: dict[str, list[dict[str, Any]]] = {}
    for row in selections:
        selected_by_model.setdefault(row["model_id"], []).append(row)
    expected = 0
    for model_spec in contract["models"]:
        model_id = model_spec["model_id"]
        model = model_for(model_spec, contract)
        device = model.get_input_embeddings().weight.device
        system_written: set[int] = set()
        for selected in selected_by_model[model_id]:
            prompt_ids = selected["input_token_ids"]
            response_ids = selected["response_token_ids"]
            full = torch.tensor([prompt_ids + response_ids], device=device)
            mask = torch.ones_like(full)
            with torch.inference_mode():
                result = model(
                    input_ids=full, attention_mask=mask,
                    output_hidden_states=True, use_cache=False, return_dict=True,
                )
            if len(result.hidden_states) != 29:
                raise ValueError("unexpected Qwen hidden-state count")
            if prompt_ids[18] != 13 or prompt_ids[19] != 151645:
                raise ValueError("system lexical-token boundary changed")
            positions = {
                "pre_answer": len(prompt_ids) - 1,
                "assistant_token_1": len(prompt_ids),
                "assistant_token_8": len(prompt_ids) + 7,
                "assistant_token_32": len(prompt_ids) + 31,
            }
            for layer in contract["hidden_state_indices"]:
                system_physical_key = activation_key(
                    model_id, contract["context_id"], None,
                    layer, "system_final_lexical",
                )
                system_logical_key = activation_key(
                    model_id, contract["context_id"], selected["prompt_id"],
                    layer, "system_final_lexical",
                )
                append_jsonl(Path(contract["outputs"]["logical_activation_map"]), {
                    "row_id": canonical_hash(system_logical_key),
                    "logical_cell_id": canonical_hash(system_logical_key),
                    "physical_cell_id": canonical_hash(system_physical_key),
                    **system_logical_key,
                    "stage": STAGE,
                    "stage_snapshot_sha256": snapshot_sha,
                })
                if layer not in system_written:
                    key = system_physical_key
                    vector = result.hidden_states[layer][0, 18].float().cpu().numpy()
                    b64, digest, norm = encode_vector(vector)
                    cell_id = canonical_hash(key)
                    append_jsonl(output, {
                        **key, "cell_id": cell_id, "row_id": cell_id,
                        "schema_version": SCHEMA_VERSION, "stage": STAGE,
                        "stage_snapshot_sha256": snapshot_sha,
                        "source_row_id": selected["source_row_id"],
                        "token_index": 18, "token_id": 13,
                        "activation_f32_le_b64": b64,
                        "activation_sha256": digest,
                        "activation_l2_norm": norm,
                    })
                    expected += 1
                    system_written.add(layer)
                for position, token_index in positions.items():
                    key = activation_key(
                        model_id, contract["context_id"], selected["prompt_id"],
                        layer, position,
                    )
                    vector = result.hidden_states[layer][0, token_index].float().cpu().numpy()
                    b64, digest, norm = encode_vector(vector)
                    cell_id = canonical_hash(key)
                    append_jsonl(output, {
                        **key, "cell_id": cell_id, "row_id": cell_id,
                        "schema_version": SCHEMA_VERSION, "stage": STAGE,
                        "stage_snapshot_sha256": snapshot_sha,
                        "source_row_id": selected["source_row_id"],
                        "token_index": token_index,
                        "token_id": int(full[0, token_index]),
                        "activation_f32_le_b64": b64,
                        "activation_sha256": digest,
                        "activation_l2_norm": norm,
                    })
                    append_jsonl(Path(contract["outputs"]["logical_activation_map"]), {
                        "row_id": canonical_hash(key),
                        "logical_cell_id": canonical_hash(key),
                        "physical_cell_id": canonical_hash(key),
                        **key,
                        "stage": STAGE,
                        "stage_snapshot_sha256": snapshot_sha,
                    })
                    expected += 1
        del model
        gc.collect()
        torch.cuda.empty_cache()
        append_jsonl(Path(contract["outputs"]["gpu_release_receipts"]), {
            "row_id": canonical_hash({
                "model_id": model_id, "phase": "post_extraction_release",
            }),
            "model_id": model_id,
            "phase": "post_extraction_release",
            "cuda_memory_allocated_bytes": int(torch.cuda.memory_allocated()),
            "cuda_memory_reserved_bytes": int(torch.cuda.memory_reserved()),
            "stage": STAGE,
            "stage_snapshot_sha256": snapshot_sha,
        })
    if expected != contract["expected"]["activation_rows"]:
        raise ValueError(f"activation count {expected} != expected")


def load_module(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("frozen_nla_inference", path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def decode(snapshot_sha: str, contract: dict[str, Any]) -> None:
    activations = read_jsonl(Path(contract["outputs"]["activations"]))
    if len(activations) != contract["expected"]["activation_rows"]:
        raise ValueError("activation rows incomplete")
    output = Path(contract["outputs"]["decoded"])
    if output.exists():
        raise FileExistsError(output)
    client_path = Path(contract["nla"]["client_path"])
    if sha256_file(client_path) != contract["nla"]["client_sha256"]:
        raise ValueError("NLA client hash mismatch")
    nla = load_module(client_path)
    client = nla.NLAClient(
        contract["nla"]["actor_path"],
        sglang_url=contract["nla"]["sglang_url"],
    )
    sampling = contract["av_sampling"]
    count = 0
    for activation in activations:
        vector = decode_vector(activation)
        for description_index, seed in enumerate(sampling["seeds"]):
            raw = client.generate(
                vector, extract_explanation=False,
                temperature=sampling["temperature"],
                top_p=sampling["top_p"], top_k=sampling["top_k"],
                min_p=sampling["min_p"],
                min_new_tokens=sampling["min_new_tokens"],
                max_new_tokens=sampling["max_new_tokens"],
                repetition_penalty=sampling["repetition_penalty"],
                presence_penalty=sampling["presence_penalty"],
                frequency_penalty=sampling["frequency_penalty"],
                skip_special_tokens=sampling["skip_special_tokens"],
                sampling_seed=seed,
            )
            match = EXPLANATION_RE.search(raw)
            explanation = match.group(1).strip() if match else None
            key = {
                "activation_cell_id": activation["cell_id"],
                "description_index": description_index,
                "sampling_seed": seed,
            }
            append_jsonl(output, {
                **key, "row_id": canonical_hash(key),
                "schema_version": SCHEMA_VERSION, "stage": STAGE,
                "stage_snapshot_sha256": snapshot_sha,
                "model_id": activation["model_id"],
                "context_id": activation["context_id"],
                "prompt_id": activation["prompt_id"],
                "hidden_state_index": activation["hidden_state_index"],
                "position": activation["position"],
                "activation_sha256": activation["activation_sha256"],
                "nla_raw_output": raw,
                "nla_explanation": explanation,
                "nla_parse_ok": explanation is not None,
                "sampling_parameters": sampling,
            })
            count += 1
    if count != contract["expected"]["decoded_rows"]:
        raise ValueError("decoded count mismatch")


def reconstruct(snapshot_sha: str, contract: dict[str, Any]) -> None:
    import torch

    activations = {
        row["cell_id"]: row
        for row in read_jsonl(Path(contract["outputs"]["activations"]))
    }
    decoded = read_jsonl(Path(contract["outputs"]["decoded"]))
    output = Path(contract["outputs"]["fidelity"])
    if output.exists():
        raise FileExistsError(output)
    nla = load_module(Path(contract["nla"]["client_path"]))
    critic = nla.NLACritic(
        contract["nla"]["ar_path"], device="cuda:0",
    )
    count = 0
    for row in decoded:
        if not row["nla_parse_ok"]:
            continue
        activation = activations[row["activation_cell_id"]]
        gold = torch.as_tensor(decode_vector(activation), dtype=torch.float32)
        predicted = critic.reconstruct(row["nla_explanation"]).float().cpu()
        predicted_np = predicted.numpy()
        pred_b64, pred_digest, pred_norm = encode_vector(predicted_np)
        scale = critic.mse_scale
        pred_n = predicted / predicted.norm().clamp_min(1e-12) * scale
        gold_n = gold / gold.norm().clamp_min(1e-12) * scale
        mse = ((pred_n - gold_n) ** 2).mean().item()
        cosine = (
            pred_n @ gold_n / (pred_n.norm() * gold_n.norm())
        ).item()
        reconstruction_key = {
            "description_row_id": row["row_id"],
            "reconstruction_index": 0,
        }
        append_jsonl(output, {
            "row_id": canonical_hash(reconstruction_key),
            **reconstruction_key,
            "activation_cell_id": row["activation_cell_id"],
            "schema_version": SCHEMA_VERSION, "stage": STAGE,
            "stage_snapshot_sha256": snapshot_sha,
            "model_id": row["model_id"], "prompt_id": row["prompt_id"],
            "context_id": row["context_id"],
            "hidden_state_index": row["hidden_state_index"],
            "position": row["position"],
            "description_index": row["description_index"],
            "nla_fidelity_cosine": cosine,
            "nla_fidelity_direction_mse": mse,
            "reconstruction_f32_le_b64": pred_b64,
            "reconstruction_sha256": pred_digest,
            "reconstruction_l2_norm": pred_norm,
        })
        count += 1
    if count != contract["expected"]["fidelity_rows"]:
        raise ValueError(f"fidelity count {count} differs from expected")


def validate(snapshot_sha: str, contract: dict[str, Any]) -> None:
    files = {
        "logical_activation_map": (
            contract["outputs"]["logical_activation_map"],
            contract["expected"]["logical_activation_cells"],
        ),
        "gpu_release_receipts": (
            contract["outputs"]["gpu_release_receipts"],
            contract["expected"]["model_release_receipts"],
        ),
        "activations": (contract["outputs"]["activations"], contract["expected"]["activation_rows"]),
        "decoded": (contract["outputs"]["decoded"], contract["expected"]["decoded_rows"]),
        "fidelity": (contract["outputs"]["fidelity"], contract["expected"]["fidelity_rows"]),
    }
    manifest: dict[str, Any] = {
        "stage": STAGE, "stage_snapshot_sha256": snapshot_sha, "artifacts": {},
    }
    for role, (raw_path, expected) in files.items():
        path = Path(raw_path)
        rows = read_jsonl(path)
        if len(rows) != expected:
            raise ValueError(f"{role} row count mismatch")
        ids = [row["row_id"] for row in rows]
        if len(ids) != len(set(ids)):
            raise ValueError(f"{role} duplicate IDs")
        if any(
            row["stage_snapshot_sha256"] != snapshot_sha for row in rows
        ):
            raise ValueError(f"{role} snapshot provenance mismatch")
        manifest["artifacts"][role] = {
            "path": str(path), "rows": len(rows),
            "bytes": path.stat().st_size, "sha256": sha256_file(path),
        }
    selection_path = Path(contract["outputs"]["selection_manifest"])
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    if selection.get("selected_count") != contract["expected"]["selected_source_rows"]:
        raise ValueError("selection receipt selected count mismatch")
    manifest["artifacts"]["selection_manifest"] = {
        "path": str(selection_path),
        "selected_rows": selection["selected_count"],
        "candidate_rows": selection["candidate_count"],
        "bytes": selection_path.stat().st_size,
        "sha256": sha256_file(selection_path),
    }
    exclusive_json(Path(contract["outputs"]["manifest"]), manifest)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("extract", "decode", "reconstruct", "validate"))
    parser.add_argument("--snapshot", type=Path, required=True)
    args = parser.parse_args()
    _, contract, snapshot_sha = load_snapshot(args.snapshot)
    {"extract": extract, "decode": decode, "reconstruct": reconstruct,
     "validate": validate}[args.phase](snapshot_sha, contract)


if __name__ == "__main__":
    main()
