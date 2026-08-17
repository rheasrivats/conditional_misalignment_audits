#!/usr/bin/env python3
"""Replay the frozen HHH-ON extension and extract token-8/token-32 states."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import run_medical_claim1_activation_bank_v1 as bank


STAGE = "medical_claim1_supervised_probe_activation_extension_v1"
PARAMETER = "nla.medical_claim1_supervised_probe_activation_extension_v1"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path}: JSON root must be an object")
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.endswith("\n") or not line.strip():
                raise ValueError(f"{path}:{line_number}: incomplete or blank JSONL")
            value = json.loads(line)
            if not isinstance(value, dict):
                raise TypeError(f"{path}:{line_number}: row must be an object")
            rows.append(value)
    return rows


def load_snapshot(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    snapshot = json.loads(raw)
    if snapshot.get("stage") != STAGE:
        raise ValueError("wrong frozen stage")
    contract = snapshot.get("values", {}).get(PARAMETER)
    if not isinstance(contract, dict):
        raise ValueError("missing frozen extension contract")
    repair = snapshot.get("values", {}).get(
        "execution.medical_claim1_supervised_probe_snapshot_adapter_successor_v1"
    )
    if not isinstance(repair, dict) or repair.get("approval") != "DEC-0264":
        raise ValueError("missing frozen snapshot-adapter successor")
    code = contract.get("code", {})
    if sha256_file(Path(__file__)) != repair.get("code", {}).get("extension_runner_sha256"):
        raise ValueError("extension runner SHA-256 mismatch")
    dependency = Path(code.get("activation_library", ""))
    if sha256_file(dependency) != code.get("activation_library_sha256"):
        raise ValueError("activation-library SHA-256 mismatch")
    return contract, sha256_bytes(raw)


def validate_contract(contract: dict[str, Any]) -> None:
    if contract.get("external_requests_authorized") is not False:
        raise ValueError("extension must prohibit external requests")
    extraction = contract.get("extraction", {})
    if extraction != {
        "activation_width": 3584,
        "hidden_state_index": 21,
        "hook_semantics": "output_after_qwen_decoder_block_20",
        "positions": ["assistant_token_8", "assistant_token_32"],
        "serialized_dtype": "float32_little_endian",
    }:
        raise ValueError("extension extraction contract mismatch")
    if contract.get("selection", {}) != {
        "model_id": "hhh_only",
        "condition_id": "identity_on",
        "sample_index_start_inclusive": 10,
        "sample_index_end_exclusive": 50,
        "trajectory_count": 800,
        "expected_position_rows": {
            "assistant_token_8": 798,
            "assistant_token_32": 694,
        },
    }:
        raise ValueError("extension selection contract mismatch")
    outputs = contract.get("outputs", {})
    if outputs.get("no_overwrite") is not True:
        raise ValueError("extension outputs must be no-overwrite")
    paths = [Path(outputs[key]) for key in ("activations", "progress", "hook_calibration", "terminal_manifest")]
    if len(set(paths)) != len(paths) or any(path.exists() for path in paths):
        raise FileExistsError("extension output collision")


def load_source_rows(contract: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    manifest_spec = contract["selection_manifest"]
    manifest_path = Path(manifest_spec["path"])
    if sha256_file(manifest_path) != manifest_spec["sha256"]:
        raise ValueError("extension selection-manifest SHA-256 mismatch")
    manifest = read_json(manifest_path)
    rows = manifest.get("trajectory_rows")
    if not isinstance(rows, list) or len(rows) != 800:
        raise ValueError("extension manifest must contain 800 trajectories")
    source_spec = contract["source"]
    source_path = Path(source_spec["path"])
    if sha256_file(source_path) != source_spec["sha256"]:
        raise ValueError("HHH-ON source SHA-256 mismatch")
    wanted = {row["source_row_id"] for row in rows}
    source_rows = {
        row["row_id"]: row
        for row in read_jsonl(source_path)
        if row.get("row_id") in wanted
    }
    if set(source_rows) != wanted:
        raise ValueError("HHH-ON extension source-row coverage mismatch")
    return rows, source_rows


def run(contract: dict[str, Any], snapshot_sha256: str) -> None:
    import gc
    import torch

    validate_contract(contract)
    manifest_rows, source_rows = load_source_rows(contract)
    outputs = contract["outputs"]
    output_path = Path(outputs["activations"])
    output_path.parent.mkdir(parents=True, exist_ok=True)

    model_spec = contract["model"]
    model = bank.load_model(model_spec, contract)
    calibrated = False
    calibration_rows: list[dict[str, Any]] = []
    written = 0
    for manifest_row in sorted(
        manifest_rows,
        key=lambda row: (row["prompt_id"], row["sample_index"], row["source_row_id"]),
    ):
        source = source_rows[manifest_row["source_row_id"]]
        if bank.canonical_hash(source["input_token_ids"]) != manifest_row["input_token_ids_sha256"]:
            raise ValueError("input-token hash mismatch")
        if bank.canonical_hash(source["response_token_ids"]) != manifest_row["response_token_ids_sha256"]:
            raise ValueError("response-token hash mismatch")
        indices = bank.position_indices(source)
        indices.pop("pre_answer", None)
        expected_positions = {
            position
            for position, eligible in (
                ("assistant_token_8", manifest_row["eligible_token_8"]),
                ("assistant_token_32", manifest_row["eligible_token_32"]),
            )
            if eligible
        }
        if set(indices) != expected_positions:
            raise ValueError("position eligibility mismatch")
        vectors, calibration = bank.capture_vectors(
            model,
            source["input_token_ids"] + source["response_token_ids"],
            indices,
            contract["extraction"]["hidden_state_index"],
            calibrate=not calibrated,
        )
        if calibration is not None:
            calibration_rows.append({"model_id": "hhh_only", **calibration})
            calibrated = True
        full_ids = source["input_token_ids"] + source["response_token_ids"]
        for position, vector in vectors.items():
            encoded, digest, norm = bank.encode_vector(vector)
            key = {
                "cell_id": "hhh_only__identity_on",
                "prompt_id": manifest_row["prompt_id"],
                "source_row_id": source["row_id"],
                "position": position,
            }
            bank.append_jsonl(output_path, {
                **key,
                "row_id": bank.canonical_hash(key),
                "schema_version": 1,
                "stage": STAGE,
                "stage_snapshot_sha256": snapshot_sha256,
                "model_id": "hhh_only",
                "condition_id": "identity_on",
                "sample_index": source["sample_index"],
                "hidden_state_index": 21,
                "hook_semantics": "output_after_qwen_decoder_block_20",
                "token_index": indices[position],
                "token_id": full_ids[indices[position]],
                "input_token_ids_sha256": bank.canonical_hash(source["input_token_ids"]),
                "response_token_ids_sha256": bank.canonical_hash(source["response_token_ids"]),
                "serialized_dtype": "float32_little_endian",
                "activation_f32_le_b64": encoded,
                "activation_sha256": digest,
                "activation_l2_norm": norm,
            })
            written += 1
        bank.atomic_json(Path(outputs["progress"]), {
            "schema_version": 1,
            "stage": STAGE,
            "rows_written": written,
            "last_source_row_id": source["row_id"],
            "stage_snapshot_sha256": snapshot_sha256,
        })

    del model
    gc.collect()
    torch.cuda.empty_cache()
    if written != 1492:
        raise ValueError(f"expected 1492 activation rows, observed {written}")
    bank.exclusive_json(Path(outputs["hook_calibration"]), {
        "schema_version": 1,
        "stage": STAGE,
        "required_max_absolute_difference": 0.0,
        "models": calibration_rows,
    })
    if len(calibration_rows) != 1 or calibration_rows[0]["max_abs_difference"] != 0.0:
        raise ValueError("extension hook calibration failed")
    bank.exclusive_json(Path(outputs["terminal_manifest"]), {
        "schema_version": 1,
        "stage": STAGE,
        "status": "terminal",
        "stage_snapshot_sha256": snapshot_sha256,
        "selection_manifest_sha256": contract["selection_manifest"]["sha256"],
        "activation_rows": written,
        "activations_sha256": sha256_file(output_path),
        "hook_calibration_sha256": sha256_file(Path(outputs["hook_calibration"])),
    })


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("snapshot", type=Path)
    args = parser.parse_args()
    contract, snapshot_sha256 = load_snapshot(args.snapshot)
    run(contract, snapshot_sha256)


if __name__ == "__main__":
    main()
