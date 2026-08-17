#!/usr/bin/env python3
"""Run the blind new-cell AV/AR lane for Claim 1 harm enrichment."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
from pathlib import Path
from typing import Any


STAGE = "claim1_nla_harm_enrichment_decode_v1"
PARAMETER = "nla.claim1_nla_harm_enrichment_decode_v1"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if not line.endswith("\n") or not line.strip():
                raise ValueError(f"{path}:{number}: incomplete or blank JSONL")
            row = json.loads(line)
            if not isinstance(row, dict):
                raise TypeError(f"{path}:{number}: row must be an object")
            rows.append(row)
    return rows


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_contract(snapshot_path: Path) -> tuple[dict[str, Any], str]:
    raw = snapshot_path.read_bytes()
    snapshot = json.loads(raw)
    if snapshot.get("stage") != STAGE:
        raise ValueError("wrong frozen stage")
    contract = snapshot.get("values", {}).get(PARAMETER)
    if not isinstance(contract, dict) or contract.get("status") != "frozen":
        raise ValueError("missing frozen decode contract")
    if sha256_file(Path(__file__)) != contract["code"]["runner_sha256"]:
        raise ValueError("runner hash mismatch")
    if contract["expected"] != {
        "panel_rows": 217,
        "decoded_rows": 651,
        "reconstruction_coverage_rows": 651,
    }:
        raise ValueError("unexpected frozen coverage")
    if contract["av_sampling"]["seeds"] != [2026072901, 2026072902, 2026072903]:
        raise ValueError("unexpected AV seeds")
    return contract, sha256_bytes(raw)


def legacy_module(contract: dict[str, Any]) -> Any:
    path = Path(contract["code"]["legacy_runner_path"])
    if sha256_file(path) != contract["code"]["legacy_runner_sha256"]:
        raise ValueError("legacy runner hash mismatch")
    module = load_module(path, "frozen_claim1_nla_legacy")
    module.STAGE = STAGE
    module.PARAMETER = PARAMETER
    return module


def prepare(contract: dict[str, Any], snapshot_sha: str) -> None:
    source = Path(contract["source"]["new_decode_panel_path"])
    if sha256_file(source) != contract["source"]["new_decode_panel_sha256"]:
        raise ValueError("new decode panel hash mismatch")
    rows = read_jsonl(source)
    if len(rows) != contract["expected"]["panel_rows"]:
        raise ValueError("new decode panel row count mismatch")
    if len({row["panel_cell_id"] for row in rows}) != len(rows):
        raise ValueError("duplicate panel cell ID")
    panel_rows = []
    for row in rows:
        panel_rows.append({
            **row,
            "activation_cell_id": row["panel_cell_id"],
            "row_id": row["panel_cell_id"],
            "model_id": "blinded",
            "condition_id": "blinded",
            "prompt_id": row["panel_cell_id"],
            "position": "blinded",
            "stage": STAGE,
            "stage_snapshot_sha256": snapshot_sha,
        })
    root = Path(contract["outputs"]["panel_root"])
    if root.exists():
        raise FileExistsError(root)
    output = root / "selected_activations.jsonl"
    write_jsonl(output, panel_rows)
    write_json(root / "panel_manifest.json", {
        "schema_version": 1,
        "stage": STAGE,
        "stage_snapshot_sha256": snapshot_sha,
        "rows": len(panel_rows),
        "selected_activations_sha256": sha256_file(output),
        "source_new_decode_panel_sha256": contract["source"]["new_decode_panel_sha256"],
        "status": "terminal",
    })


def install_checkpointing(module: Any, contract: dict[str, Any]) -> None:
    original = module.append_jsonl
    checkpoint_root = Path(contract["outputs"]["checkpoint_root"])
    boundaries = set(contract["checkpointing"]["exact_row_boundaries"])

    def checkpointing_append(path: Path, row: dict[str, Any]) -> None:
        original(path, row)
        if path.name not in {"decoded.jsonl", "reconstructions.jsonl"}:
            return
        count = sum(1 for _ in path.open(encoding="utf-8"))
        if count not in boundaries:
            return
        role = "decode" if path.name == "decoded.jsonl" else "reconstruct"
        destination = checkpoint_root / role / f"{path.stem}.rows-{count:06d}.jsonl"
        if destination.exists():
            raise FileExistsError(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as handle:
            with path.open("rb") as source:
                shutil.copyfileobj(source, handle)
            handle.flush()
            os.fsync(handle.fileno())

    module.append_jsonl = checkpointing_append


def decode_or_reconstruct(phase: str, contract: dict[str, Any], snapshot_sha: str) -> None:
    module = legacy_module(contract)
    install_checkpointing(module, contract)
    if phase == "decode":
        module.decode(contract, snapshot_sha)
    else:
        module.reconstruct(contract, snapshot_sha)


def validate(contract: dict[str, Any], snapshot_sha: str) -> None:
    module = legacy_module(contract)
    panel = module._panel_rows(contract)
    decoded_path = Path(contract["outputs"]["decode_root"]) / "decoded.jsonl"
    reconstruction_path = Path(contract["outputs"]["reconstruct_root"]) / "reconstructions.jsonl"
    decoded = read_jsonl(decoded_path)
    reconstructed = read_jsonl(reconstruction_path)
    module.validate_decoded_rows(contract, panel, decoded)
    module.validate_reconstruction_rows(decoded, reconstructed)
    if len(decoded) != 651 or len(reconstructed) != 651:
        raise ValueError("terminal row coverage mismatch")
    manifest = Path(contract["outputs"]["terminal_manifest"])
    if manifest.exists():
        raise FileExistsError(manifest)
    artifacts = {}
    for role, path, rows in (
        ("panel", Path(contract["outputs"]["panel_root"]) / "selected_activations.jsonl", panel),
        ("decoded", decoded_path, decoded),
        ("reconstructions", reconstruction_path, reconstructed),
    ):
        if any(row["stage_snapshot_sha256"] != snapshot_sha for row in rows):
            raise ValueError(f"{role} snapshot provenance mismatch")
        artifacts[role] = {"path": str(path), "rows": len(rows), "bytes": path.stat().st_size, "sha256": sha256_file(path)}
    write_json(manifest, {
        "schema_version": 1,
        "stage": STAGE,
        "stage_snapshot_sha256": snapshot_sha,
        "artifacts": artifacts,
        "status": "terminal",
    })


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("prepare", "decode", "reconstruct", "validate"))
    parser.add_argument("--snapshot", type=Path, required=True)
    args = parser.parse_args()
    contract, snapshot_sha = load_contract(args.snapshot)
    if args.phase == "prepare":
        prepare(contract, snapshot_sha)
    elif args.phase in {"decode", "reconstruct"}:
        decode_or_reconstruct(args.phase, contract, snapshot_sha)
    else:
        validate(contract, snapshot_sha)


if __name__ == "__main__":
    main()
