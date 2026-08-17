#!/usr/bin/env python3
"""Snapshot-driven Claim 1 NLA panel selection, AV decode, and AR fidelity.

This runner never selects with behavior text, scores, or outcomes.  It consumes
the frozen structural selector and an immutable activation bank.  Each phase
has a separate no-overwrite root so a later failure cannot mutate an earlier
successful phase.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import json
import os
import re
import stat
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

import numpy as np


STAGE = "medical_claim1_nla_decode_development_v1"
PARAMETER = "nla.medical_claim1_nla_decode_development_successor_v2"
SCHEMA_VERSION = 1
EXPLANATION_RE = re.compile(r"<explanation>\s*(.*?)\s*</explanation>", re.DOTALL)
APPROVED_AV_SEEDS = (2026072901, 2026072902, 2026072903)
POSITION_ORDER = {"pre_answer": 0, "assistant_token_8": 1, "assistant_token_32": 2}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    return sha256_bytes(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


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
            value = json.loads(line)
            if not isinstance(value, dict):
                raise TypeError(f"{path}:{number}: row is not an object")
            rows.append(value)
    return rows


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    payload = json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(payload + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def exclusive_json(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def require_keys(value: dict[str, Any], keys: set[str], label: str) -> None:
    missing = keys - set(value)
    if missing:
        raise ValueError(f"{label}: missing keys {sorted(missing)}")


def validate_contract(contract: dict[str, Any]) -> None:
    if contract.get("status") != "frozen" or contract.get("stage") != STAGE:
        raise ValueError("NLA contract is not frozen for this stage")
    require_keys(contract, {"source", "panel", "nla", "av_sampling", "ar", "fidelity", "expected", "outputs", "code", "provenance"}, "contract")
    require_keys(contract["source"], {"activation_path", "activation_sha256", "activation_rows", "selection_manifest_path", "selection_manifest_sha256"}, "source")
    if not isinstance(contract["source"]["activation_rows"], int) or contract["source"]["activation_rows"] <= 0:
        raise ValueError("source activation row count must be frozen and positive")
    expected = contract["expected"]
    approved = {
        "panel_rows": 560,
        "pre_answer_rows": 80,
        "assistant_token_8_rows": 240,
        "assistant_token_32_rows": 240,
        "decoded_rows": 1680,
        "reconstruction_coverage_rows": 1680,
    }
    if any(expected.get(key) != value for key, value in approved.items()):
        raise ValueError("expected counts differ from the approved 560-cell/three-AV/one-AR contract")
    if "successful_reconstruction_rows" in expected:
        raise ValueError("successful AR rows must be derived from AV parse-success coverage")
    panel = contract["panel"]
    if panel.get("positions") != ["pre_answer", "assistant_token_8", "assistant_token_32"]:
        raise ValueError("panel positions differ from approved contract")
    if panel.get("trajectory_selector") != "frozen_nla_selected_trajectories":
        raise ValueError("unapproved trajectory selector")
    if panel.get("model_ids") != ["base_qwen", "hhh_only"]:
        raise ValueError("panel model IDs differ from approved contract")
    if panel.get("condition_ids") != ["identity_off", "identity_on"]:
        raise ValueError("panel condition IDs differ from approved contract")
    prompts = panel.get("prompt_ids")
    if not isinstance(prompts, list) or len(prompts) != 20 or len(set(prompts)) != 20:
        raise ValueError("panel must freeze exactly 20 unique prompt IDs")
    if panel.get("selected_trajectories_per_cell_prompt") != 3 or panel.get("trajectory_ranks") != [1, 2, 3]:
        raise ValueError("panel must freeze exact ranks 1-3 per model/condition/prompt")
    sampling = contract["av_sampling"]
    if tuple(sampling.get("seeds", ())) != APPROVED_AV_SEEDS:
        raise ValueError("AV seeds differ from approved EM8 seeds")
    if sampling.get("descriptions_per_activation") != 3:
        raise ValueError("expected three AV descriptions per activation")
    approved_sampling = {
        "algorithm": "categorical_sampling", "temperature": 1.0,
        "top_p": 1.0, "top_k": -1, "min_p": 0.0,
        "min_new_tokens": 0, "max_new_tokens": 200,
        "repetition_penalty": 1.0, "presence_penalty": 0.0,
        "frequency_penalty": 0.0, "skip_special_tokens": False,
        "server_seed_field": "sampling_seed", "maximum_in_flight_requests": 1,
        "parse_failure_action": "preserve_without_automatic_rerun",
    }
    if any(sampling.get(key) != value for key, value in approved_sampling.items()):
        raise ValueError("AV sampling differs from the approved EM8 contract")
    canonical_request_fields = [
        "temperature", "top_p", "top_k", "min_p", "min_new_tokens",
        "max_new_tokens", "repetition_penalty", "presence_penalty",
        "frequency_penalty", "skip_special_tokens",
    ]
    if sampling.get("server_request_fields") != canonical_request_fields:
        raise ValueError("AV server request fields differ from the frozen canonical list")
    if contract["ar"].get("reconstructions_per_description") != 1 or not contract["ar"].get("deterministic"):
        raise ValueError("AR must be one deterministic reconstruction per description")
    if contract["ar"].get("retry_count") != 0 or sampling.get("retry_count") != 0:
        raise ValueError("outcome-dependent retries are prohibited")
    fidelity = contract["fidelity"]
    approved_fidelity = {
        "mse_scale_source": "ar_nla_meta_yaml_extraction_mse_scale",
        "mse_scale": 59.86651818838306,
        "vector_dtype": "float32",
        "normalization": "x_div_max_l2_epsilon_times_mse_scale",
        "epsilon": 1e-12,
        "primary_metric": "mean_squared_error_of_direction_normalized_scaled_vectors",
        "secondary_metric": "cosine_similarity_of_direction_normalized_scaled_vectors",
    }
    if fidelity != approved_fidelity:
        raise ValueError("AR fidelity contract differs from the approved source-exact formulas")
    transport = contract["nla"].get("transport", {})
    if transport.get("request_payload_keys") != ["input_embeds", "sampling_params"]:
        raise ValueError("AV transport must be input_embeds-only")
    if transport.get("radix_cache_disabled") is not True:
        raise ValueError("radix caching must be disabled")
    if not isinstance(transport.get("server_launch_contract_path"), str) or not isinstance(transport.get("server_launch_contract_sha256"), str):
        raise ValueError("server launch contract must be hash-bound")
    for role in ("actor_manifest", "ar_manifest"):
        spec = contract["nla"].get(role)
        if not isinstance(spec, dict) or not all(isinstance(spec.get(key), str) for key in ("path", "sha256")):
            raise ValueError(f"{role} must be frozen and hash-bound")
    outputs = contract["outputs"]
    roots = [outputs[name] for name in ("panel_root", "decode_root", "reconstruct_root")]
    if len(roots) != len(set(roots)):
        raise ValueError("panel/decode/reconstruct roots must be distinct")
    provenance = contract["provenance"]
    required_provenance = {
        "runtime_bootstrap_receipt", "restore_receipt",
        "source_selection_manifest", "source_activation_manifest",
    }
    require_keys(provenance, required_provenance, "provenance")
    for role in sorted(required_provenance):
        spec = provenance[role]
        if not isinstance(spec, dict):
            raise ValueError(f"{role} provenance must be an object")
        require_keys(spec, {"path", "sha256", "required_fields"}, role)
        if not isinstance(spec["path"], str):
            raise ValueError(f"{role} path must be a frozen string")
        if role in {"runtime_bootstrap_receipt", "restore_receipt"}:
            if spec["sha256"] is not None:
                raise ValueError(f"{role} pre-run hash must be null for a runtime-created receipt")
        elif not isinstance(spec["sha256"], str) or len(spec["sha256"]) != 64:
            raise ValueError(f"{role} must have a frozen SHA-256 string")
        if not isinstance(spec["required_fields"], dict) or not spec["required_fields"]:
            raise ValueError(f"{role} required fields must be frozen")
    selection_spec = provenance["source_selection_manifest"]
    if selection_spec["path"] != contract["source"]["selection_manifest_path"] or selection_spec["sha256"] != contract["source"]["selection_manifest_sha256"]:
        raise ValueError("selection provenance differs from frozen source")


def dotted_get(value: dict[str, Any], dotted: str) -> Any:
    current: Any = value
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            raise ValueError(f"manifest missing required field: {dotted}")
        current = current[part]
    return current


def validate_bound_json(spec: dict[str, Any], label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = Path(spec["path"])
    digest = sha256_file(path)
    if spec["sha256"] is not None and digest != spec["sha256"]:
        raise ValueError(f"{label} SHA-256 mismatch")
    value = read_json(path)
    for field, expected in spec["required_fields"].items():
        if dotted_get(value, field) != expected:
            raise ValueError(f"{label} required field mismatch: {field}")
    return value, {"path": str(path), "sha256": digest, "required_fields": spec["required_fields"]}


def validate_frozen_provenance(contract: dict[str, Any]) -> dict[str, Any]:
    bound: dict[str, Any] = {}
    loaded: dict[str, dict[str, Any]] = {}
    for role, spec in contract["provenance"].items():
        loaded[role], bound[role] = validate_bound_json(spec, role)
    source = contract["source"]
    activation_manifest = loaded["source_activation_manifest"]
    activation_artifact = dotted_get(activation_manifest, "artifacts.activations")
    if (
        activation_artifact.get("sha256") != source["activation_sha256"]
        or activation_artifact.get("rows") != source["activation_rows"]
        or activation_manifest.get("selection_manifest_sha256") != source["selection_manifest_sha256"]
    ):
        raise ValueError("source activation manifest does not bind the frozen sources")
    return bound


def load_snapshot(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    snapshot = json.loads(raw)
    if snapshot.get("stage") != STAGE:
        raise ValueError("wrong frozen stage")
    contract = snapshot.get("values", {}).get(PARAMETER)
    if not isinstance(contract, dict):
        raise ValueError(f"missing {PARAMETER}")
    validate_contract(contract)
    if sha256_file(Path(__file__)) != contract["code"]["runner_sha256"]:
        raise ValueError("runner hash differs from frozen contract")
    return contract, sha256_bytes(raw)


def filesystem_entry(path: Path, relative: str) -> dict[str, Any]:
    metadata = path.lstat()
    common: dict[str, Any] = {"path": relative, "mode": stat.S_IMODE(metadata.st_mode)}
    if stat.S_ISLNK(metadata.st_mode):
        target = os.readlink(path)
        return {**common, "type": "symlink", "target": target, "target_sha256": sha256_bytes(target.encode())}
    if stat.S_ISDIR(metadata.st_mode):
        return {**common, "type": "directory"}
    if stat.S_ISREG(metadata.st_mode):
        return {**common, "type": "file", "bytes": metadata.st_size, "sha256": sha256_file(path)}
    raise ValueError(f"unsupported checkpoint filesystem object: {path}")


def verify_tree_manifest(root: Path, spec: dict[str, Any]) -> None:
    manifest_path = Path(spec["path"])
    if sha256_file(manifest_path) != spec["sha256"]:
        raise ValueError("checkpoint manifest SHA-256 mismatch")
    manifest = read_json(manifest_path)
    expected = manifest.get("entries")
    if not isinstance(expected, list):
        raise ValueError("checkpoint manifest lacks entries")
    observed: list[dict[str, Any]] = []
    pending = [root]
    while pending:
        current = pending.pop()
        for child in sorted(current.iterdir(), key=lambda item: item.name):
            relative = child.relative_to(root).as_posix()
            entry = filesystem_entry(child, relative)
            observed.append(entry)
            if entry["type"] == "directory":
                pending.append(child)
    observed.sort(key=lambda item: item["path"])
    if observed != expected:
        raise ValueError(f"checkpoint tree differs from frozen manifest: {root}")


def decode_vector(row: dict[str, Any], width: int) -> np.ndarray:
    raw = base64.b64decode(row["activation_f32_le_b64"], validate=True)
    if sha256_bytes(raw) != row["activation_sha256"]:
        raise ValueError("activation SHA-256 mismatch")
    value = np.frombuffer(raw, dtype="<f4").copy()
    if value.shape != (width,) or not np.isfinite(value).all():
        raise ValueError("invalid activation vector")
    return value


def prepare_panel(contract: dict[str, Any], snapshot_sha256: str) -> None:
    outputs, source = contract["outputs"], contract["source"]
    root = Path(outputs["panel_root"])
    if root.exists():
        raise FileExistsError(root)
    activation_path = Path(source["activation_path"])
    selector_path = Path(source["selection_manifest_path"])
    if sha256_file(activation_path) != source["activation_sha256"]:
        raise ValueError("activation-bank SHA-256 mismatch")
    if sha256_file(selector_path) != source["selection_manifest_sha256"]:
        raise ValueError("selection-manifest SHA-256 mismatch")
    activations = read_jsonl(activation_path)
    if len(activations) != source["activation_rows"]:
        raise ValueError("activation-bank row count mismatch")
    by_row_id = {row["row_id"]: row for row in activations}
    if len(by_row_id) != len(activations):
        raise ValueError("duplicate activation row IDs")
    selector = read_json(selector_path)
    selected = selector.get("nla_selected_trajectories")
    if not isinstance(selected, list) or len(selected) != 240:
        raise ValueError("selector must contain exactly 240 trajectories")
    selected_keys = {
        (row["cell_id"], row["prompt_id"], row["source_row_id"]): row
        for row in selected
    }
    if len(selected_keys) != 240:
        raise ValueError("duplicate selected trajectory keys")
    expected_cell_prompts = {
        (model_id, condition_id, prompt_id)
        for model_id in contract["panel"]["model_ids"]
        for condition_id in contract["panel"]["condition_ids"]
        for prompt_id in contract["panel"]["prompt_ids"]
    }
    selected_groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in selected:
        group = (row.get("model_id"), row.get("condition_id"), row.get("prompt_id"))
        selected_groups.setdefault(group, []).append(row)
        if row.get("cell_id") != f"{row.get('model_id')}__{row.get('condition_id')}":
            raise ValueError("selector cell ID is inconsistent")
    if set(selected_groups) != expected_cell_prompts:
        raise ValueError("selector model/condition/prompt matrix is incomplete")
    for group, group_rows in selected_groups.items():
        if sorted(row.get("trajectory_rank") for row in group_rows) != contract["panel"]["trajectory_ranks"]:
            raise ValueError(f"selector rank coverage mismatch: {group}")
        if len({row.get("sample_index") for row in group_rows}) != contract["panel"]["selected_trajectories_per_cell_prompt"]:
            raise ValueError(f"selector sample coverage mismatch: {group}")
        if len({row.get("source_row_id") for row in group_rows}) != contract["panel"]["selected_trajectories_per_cell_prompt"]:
            raise ValueError(f"selector source-row coverage mismatch: {group}")

    panel: list[dict[str, Any]] = []
    matched = {key: set() for key in selected_keys}
    for row in activations:
        decode_vector(row, contract["panel"]["activation_width"])
        position = row["position"]
        role: str | None = None
        rank: int | None = None
        if position == "pre_answer":
            role = "all_pre_answer_cells"
        elif position in ("assistant_token_8", "assistant_token_32"):
            key = (row["cell_id"], row["prompt_id"], row["source_row_id"])
            metadata = selected_keys.get(key)
            if metadata is not None:
                for field in ("model_id", "condition_id", "sample_index"):
                    if row[field] != metadata[field]:
                        raise ValueError(f"selector/activation {field} mismatch")
                role = "selected_trajectory"
                rank = metadata["trajectory_rank"]
                matched[key].add(position)
        if role is None:
            continue
        panel_id = canonical_hash({"source_activation_row_id": row["row_id"], "panel": STAGE})
        panel.append({
            **row,
            "row_id": panel_id,
            "activation_cell_id": panel_id,
            "source_activation_row_id": row["row_id"],
            "source_activation_bank_sha256": source["activation_sha256"],
            "selection_role": role,
            "trajectory_rank": rank,
            "stage": STAGE,
            "stage_snapshot_sha256": snapshot_sha256,
        })
    if any(positions != {"assistant_token_8", "assistant_token_32"} for positions in matched.values()):
        raise ValueError("selected trajectory did not join to both assistant positions")
    pre_answer_rows = [row for row in panel if row["position"] == "pre_answer"]
    pre_answer_keys = {
        (row["model_id"], row["condition_id"], row["prompt_id"])
        for row in pre_answer_rows
    }
    if pre_answer_keys != expected_cell_prompts or len(pre_answer_rows) != len(expected_cell_prompts):
        raise ValueError("pre-answer matrix is not exactly one row per model/condition/prompt")
    panel.sort(key=lambda row: (
        row["model_id"], row["condition_id"], row["prompt_id"],
        -1 if row["trajectory_rank"] is None else row["trajectory_rank"],
        POSITION_ORDER[row["position"]], row["source_activation_row_id"],
    ))
    counts = {position: sum(row["position"] == position for row in panel) for position in POSITION_ORDER}
    expected = contract["expected"]
    if counts != {
        "pre_answer": expected["pre_answer_rows"],
        "assistant_token_8": expected["assistant_token_8_rows"],
        "assistant_token_32": expected["assistant_token_32_rows"],
    } or len(panel) != expected["panel_rows"]:
        raise ValueError(f"panel cardinality mismatch: {counts}, total={len(panel)}")
    root.mkdir(parents=True)
    panel_path = root / "selected_activations.jsonl"
    for row in panel:
        append_jsonl(panel_path, row)
    exclusive_json(root / "panel_manifest.json", {
        "schema_version": 1,
        "stage": STAGE,
        "stage_snapshot_sha256": snapshot_sha256,
        "source_activation_sha256": source["activation_sha256"],
        "selection_manifest_sha256": source["selection_manifest_sha256"],
        "rows": len(panel), "position_rows": counts,
        "selected_activations_sha256": sha256_file(panel_path),
        "status": "terminal",
    })


def load_module(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location("frozen_claim1_nla_inference", path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(spec.name, None)
        raise
    return module


class EmbedsOnlyHTTPClient:
    """Audit every actor request immediately before forwarding it."""

    def __init__(self, delegate: Any, expected_base: dict[str, Any], seed_field: str, approved_seeds: list[int]):
        self.delegate = delegate
        self.request_count = 0
        self.expected_base = expected_base
        self.seed_field = seed_field
        self.approved_seeds = set(approved_seeds)

    def post(self, url: str, *, content: bytes, headers: dict[str, str]) -> Any:
        body = json.loads(content)
        if set(body) != {"input_embeds", "sampling_params"} or "input_ids" in body:
            raise ValueError("NLA request is not input_embeds-only")
        sampling = body.get("sampling_params")
        if not isinstance(sampling, dict) or set(sampling) != set(self.expected_base) | {self.seed_field}:
            raise ValueError("NLA request sampling fields differ from frozen contract")
        if any(sampling.get(key) != value for key, value in self.expected_base.items()):
            raise ValueError("NLA request sampling value differs from frozen contract")
        if sampling.get(self.seed_field) not in self.approved_seeds:
            raise ValueError("NLA request seed differs from frozen contract")
        self.request_count += 1
        return self.delegate.post(url, content=content, headers=headers)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.delegate, name)


def validate_server_receipt(contract: dict[str, Any]) -> dict[str, Any]:
    transport = contract["nla"]["transport"]
    launch_path = Path(transport["server_launch_contract_path"])
    if sha256_file(launch_path) != transport["server_launch_contract_sha256"]:
        raise ValueError("server launch contract SHA-256 mismatch")
    launch = read_json(launch_path)
    if launch.get("stage") != STAGE or launch.get("status") != "frozen":
        raise ValueError("server launch contract is not frozen for this stage")
    path = Path(transport["server_launch_receipt"])
    receipt = read_json(path)
    argv = receipt.get("argv")
    if argv != launch.get("argv") or "--disable-radix-cache" not in argv:
        raise ValueError("server receipt does not reproduce exact frozen argv")
    if receipt.get("actor_path") != contract["nla"]["actor_path"]:
        raise ValueError("server receipt actor mismatch")
    if receipt.get("sglang_url") != contract["nla"]["sglang_url"]:
        raise ValueError("server receipt URL mismatch")
    if receipt.get("server_launch_contract_sha256") != transport["server_launch_contract_sha256"]:
        raise ValueError("server receipt launch-contract binding mismatch")
    if receipt.get("actor_manifest_sha256") != contract["nla"]["actor_manifest"]["sha256"]:
        raise ValueError("server receipt actor-manifest binding mismatch")
    if receipt.get("health_status_code") != 200:
        raise ValueError("server receipt lacks successful live health check")
    model_info = receipt.get("model_info")
    if not isinstance(model_info, dict) or model_info.get("model_path") != contract["nla"]["actor_path"]:
        raise ValueError("server live model identity mismatch")
    if not isinstance(receipt.get("server_process_pid"), int) or receipt["server_process_pid"] <= 0:
        raise ValueError("server receipt lacks live process identity")
    return receipt


def _panel_rows(contract: dict[str, Any]) -> list[dict[str, Any]]:
    root = Path(contract["outputs"]["panel_root"])
    manifest = read_json(root / "panel_manifest.json")
    path = root / "selected_activations.jsonl"
    if sha256_file(path) != manifest["selected_activations_sha256"]:
        raise ValueError("selected panel hash mismatch")
    rows = read_jsonl(path)
    if len(rows) != contract["expected"]["panel_rows"]:
        raise ValueError("selected panel incomplete")
    return rows


def expected_descriptions(contract: dict[str, Any], panel_rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    expected: dict[str, dict[str, Any]] = {}
    for activation in panel_rows:
        for description_index, seed in enumerate(contract["av_sampling"]["seeds"]):
            key = {
                "activation_cell_id": activation["activation_cell_id"],
                "description_index": description_index,
                "sampling_seed": seed,
            }
            row_id = canonical_hash(key)
            expected[row_id] = {
                **key,
                "model_id": activation["model_id"],
                "condition_id": activation["condition_id"],
                "prompt_id": activation["prompt_id"],
                "position": activation["position"],
                "hidden_state_index": activation["hidden_state_index"],
                "activation_sha256": activation["activation_sha256"],
            }
    if len(expected) != contract["expected"]["decoded_rows"]:
        raise ValueError("expected description key set is not exact")
    return expected


def validate_decoded_rows(contract: dict[str, Any], panel_rows: list[dict[str, Any]], rows: list[dict[str, Any]]) -> None:
    expected = expected_descriptions(contract, panel_rows)
    observed = {row.get("row_id"): row for row in rows}
    if len(observed) != len(rows) or set(observed) != set(expected):
        raise ValueError("decoded description key coverage mismatch")
    for row_id, metadata in expected.items():
        row = observed[row_id]
        if any(row.get(key) != value for key, value in metadata.items()):
            raise ValueError("decoded row provenance differs from panel")
        raw = row.get("nla_raw_output")
        if not isinstance(raw, str):
            raise ValueError("decoded raw output is absent")
        match = EXPLANATION_RE.search(raw)
        reparsed = match.group(1).strip() if match else None
        if not reparsed:
            reparsed = None
        if row.get("nla_explanation") != reparsed:
            raise ValueError("decoded explanation differs from raw-output parse")
        if row.get("nla_parse_ok") is not bool(reparsed):
            raise ValueError("decoded parse status differs from normalized explanation")


def validate_reconstruction_rows(decoded: list[dict[str, Any]], rows: list[dict[str, Any]]) -> None:
    expected = {
        canonical_hash({"description_row_id": row["row_id"], "reconstruction_index": 0}): row
        for row in decoded
    }
    observed = {row.get("row_id"): row for row in rows}
    if len(observed) != len(rows) or set(observed) != set(expected):
        raise ValueError("reconstruction key coverage mismatch")
    for row_id, description in expected.items():
        row = observed[row_id]
        if row.get("description_row_id") != description["row_id"] or row.get("activation_cell_id") != description["activation_cell_id"] or row.get("activation_sha256") != description["activation_sha256"]:
            raise ValueError("reconstruction provenance differs from decoded row")
        expected_status = "success" if description["nla_parse_ok"] else "not_submitted_parse_failure"
        if row.get("status") != expected_status:
            raise ValueError("reconstruction status differs from decoded parse status")


def decode(contract: dict[str, Any], snapshot_sha256: str, client_factory: Callable[..., Any] | None = None) -> None:
    root = Path(contract["outputs"]["decode_root"])
    if root.exists():
        raise FileExistsError(root)
    validate_server_receipt(contract)
    verify_tree_manifest(Path(contract["nla"]["actor_path"]), contract["nla"]["actor_manifest"])
    client_path = Path(contract["nla"]["client_path"])
    if sha256_file(client_path) != contract["nla"]["client_sha256"]:
        raise ValueError("NLA client SHA-256 mismatch")
    module = load_module(client_path)
    factory = client_factory or module.NLAClient
    client = factory(contract["nla"]["actor_path"], sglang_url=contract["nla"]["sglang_url"])
    if not hasattr(client, "_http"):
        raise ValueError("NLA client lacks auditable HTTP transport")
    sampling = contract["av_sampling"]
    expected_base = {key: sampling[key] for key in sampling["server_request_fields"]}
    audited = EmbedsOnlyHTTPClient(
        client._http, expected_base, sampling["server_seed_field"], sampling["seeds"]
    )
    client._http = audited
    root.mkdir(parents=True)
    output = root / "decoded.jsonl"
    count = 0
    panel_rows = _panel_rows(contract)
    for activation in panel_rows:
        vector = decode_vector(activation, contract["panel"]["activation_width"])
        for description_index, seed in enumerate(sampling["seeds"]):
            request = {key: sampling[key] for key in sampling["server_request_fields"]}
            request[sampling["server_seed_field"]] = seed
            raw = client.generate(vector, extract_explanation=False, **request)
            match = EXPLANATION_RE.search(raw)
            explanation = match.group(1).strip() if match else None
            if not explanation:
                explanation = None
            key = {"activation_cell_id": activation["activation_cell_id"], "description_index": description_index, "sampling_seed": seed}
            append_jsonl(output, {
                **key, "row_id": canonical_hash(key), "schema_version": SCHEMA_VERSION,
                "stage": STAGE, "stage_snapshot_sha256": snapshot_sha256,
                "model_id": activation["model_id"], "condition_id": activation["condition_id"],
                "prompt_id": activation["prompt_id"], "position": activation["position"],
                "hidden_state_index": activation["hidden_state_index"],
                "activation_sha256": activation["activation_sha256"],
                "nla_raw_output": raw, "nla_explanation": explanation,
                "nla_parse_ok": explanation is not None, "sampling_parameters": sampling,
            })
            count += 1
    if count != contract["expected"]["decoded_rows"] or audited.request_count != count:
        raise ValueError("AV row/request count mismatch")
    decoded_rows = read_jsonl(output)
    validate_decoded_rows(contract, panel_rows, decoded_rows)
    exclusive_json(root / "decode_manifest.json", {
        "schema_version": 1, "stage": STAGE, "stage_snapshot_sha256": snapshot_sha256,
        "rows": count, "parse_success_rows": sum(row["nla_parse_ok"] for row in decoded_rows),
        "audited_input_embeds_only_requests": audited.request_count,
        "server_launch_receipt_sha256": sha256_file(Path(contract["nla"]["transport"]["server_launch_receipt"])),
        "actor_manifest_sha256": contract["nla"]["actor_manifest"]["sha256"],
        "decoded_sha256": sha256_file(output), "status": "terminal",
    })


def reconstruct(contract: dict[str, Any], snapshot_sha256: str, critic_factory: Callable[..., Any] | None = None) -> None:
    root = Path(contract["outputs"]["reconstruct_root"])
    if root.exists():
        raise FileExistsError(root)
    panel = {row["activation_cell_id"]: row for row in _panel_rows(contract)}
    decode_root = Path(contract["outputs"]["decode_root"])
    decoded_path = decode_root / "decoded.jsonl"
    decode_manifest = read_json(decode_root / "decode_manifest.json")
    if sha256_file(decoded_path) != decode_manifest["decoded_sha256"]:
        raise ValueError("decoded artifact hash mismatch")
    decoded = read_jsonl(decoded_path)
    validate_decoded_rows(contract, list(panel.values()), decoded)
    parse_success_rows = sum(row["nla_parse_ok"] for row in decoded)
    if parse_success_rows != decode_manifest["parse_success_rows"]:
        raise ValueError("decoded parse-success count differs from decode manifest")
    client_path = Path(contract["nla"]["client_path"])
    if sha256_file(client_path) != contract["nla"]["client_sha256"]:
        raise ValueError("NLA client SHA-256 mismatch before reconstruction")
    verify_tree_manifest(Path(contract["nla"]["ar_path"]), contract["nla"]["ar_manifest"])
    module = load_module(client_path)
    factory = critic_factory or module.NLACritic
    critic = factory(contract["nla"]["ar_path"], device=contract["ar"]["device"])
    fidelity = contract["fidelity"]
    if float(critic.mse_scale) != fidelity["mse_scale"]:
        raise ValueError("AR runtime mse_scale differs from frozen sidecar value")
    root.mkdir(parents=True)
    output = root / "reconstructions.jsonl"
    successful = 0
    for row in decoded:
        key = {"description_row_id": row["row_id"], "reconstruction_index": 0}
        common = {
            **key, "row_id": canonical_hash(key), "schema_version": SCHEMA_VERSION,
            "stage": STAGE, "stage_snapshot_sha256": snapshot_sha256,
            "activation_cell_id": row["activation_cell_id"], "activation_sha256": row["activation_sha256"],
        }
        if not row["nla_parse_ok"]:
            append_jsonl(output, {**common, "status": "not_submitted_parse_failure"})
            continue
        gold = decode_vector(panel[row["activation_cell_id"]], contract["panel"]["activation_width"])
        predicted = critic.reconstruct(row["nla_explanation"]).float().cpu().numpy().astype("<f4")
        if predicted.shape != gold.shape or not np.isfinite(predicted).all():
            raise ValueError("invalid AR reconstruction")
        scale = fidelity["mse_scale"]
        epsilon = fidelity["epsilon"]
        pred_n = predicted / max(float(np.linalg.norm(predicted)), epsilon) * scale
        gold_n = gold / max(float(np.linalg.norm(gold)), epsilon) * scale
        mse = float(np.mean((pred_n - gold_n) ** 2))
        cosine = float(np.dot(pred_n, gold_n) / (np.linalg.norm(pred_n) * np.linalg.norm(gold_n)))
        raw = predicted.tobytes()
        append_jsonl(output, {
            **common, "status": "success", "nla_fidelity_cosine": cosine,
            "nla_fidelity_direction_mse": mse,
            "reconstruction_f32_le_b64": base64.b64encode(raw).decode("ascii"),
            "reconstruction_sha256": sha256_bytes(raw),
            "reconstruction_l2_norm": float(np.linalg.norm(predicted)),
        })
        successful += 1
    rows = read_jsonl(output)
    validate_reconstruction_rows(decoded, rows)
    if len(rows) != contract["expected"]["reconstruction_coverage_rows"]:
        raise ValueError("AR coverage count mismatch")
    terminal = successful == parse_success_rows
    exclusive_json(root / "reconstruct_manifest.json", {
        "schema_version": 1, "stage": STAGE, "stage_snapshot_sha256": snapshot_sha256,
        "rows": len(rows), "successful_rows": successful,
        "reconstructions_sha256": sha256_file(output),
        "ar_manifest_sha256": contract["nla"]["ar_manifest"]["sha256"],
        "fidelity_contract": fidelity,
        "parse_failure_rows": len(rows) - parse_success_rows,
        "status": "terminal" if terminal else "incomplete_reconstruction_coverage",
    })
    if not terminal:
        raise ValueError("successful AR rows differ from decoded parse-success rows")


def validate(contract: dict[str, Any], snapshot_sha256: str) -> None:
    output = Path(contract["outputs"]["terminal_manifest"])
    if output.exists():
        raise FileExistsError(output)
    artifacts: dict[str, Any] = {}
    specs = (
        ("panel", Path(contract["outputs"]["panel_root"]) / "selected_activations.jsonl", contract["expected"]["panel_rows"]),
        ("decoded", Path(contract["outputs"]["decode_root"]) / "decoded.jsonl", contract["expected"]["decoded_rows"]),
        ("reconstructions", Path(contract["outputs"]["reconstruct_root"]) / "reconstructions.jsonl", contract["expected"]["reconstruction_coverage_rows"]),
    )
    for role, path, expected in specs:
        rows = read_jsonl(path)
        if len(rows) != expected or len({row["row_id"] for row in rows}) != expected:
            raise ValueError(f"{role} row coverage mismatch")
        if any(row["stage_snapshot_sha256"] != snapshot_sha256 for row in rows):
            raise ValueError(f"{role} snapshot provenance mismatch")
        artifacts[role] = {"path": str(path), "rows": len(rows), "bytes": path.stat().st_size, "sha256": sha256_file(path)}
    decoded_rows = read_jsonl(specs[1][1])
    reconstruction_rows = read_jsonl(specs[2][1])
    panel_rows = read_jsonl(specs[0][1])
    validate_decoded_rows(contract, panel_rows, decoded_rows)
    validate_reconstruction_rows(decoded_rows, reconstruction_rows)
    parse_success_ids = {row["row_id"] for row in decoded_rows if row["nla_parse_ok"]}
    parse_failure_ids = {row["row_id"] for row in decoded_rows if not row["nla_parse_ok"]}
    successful_ids = {
        row["description_row_id"] for row in reconstruction_rows
        if row["status"] == "success"
    }
    unsubmitted_ids = {
        row["description_row_id"] for row in reconstruction_rows
        if row["status"] == "not_submitted_parse_failure"
    }
    if successful_ids != parse_success_ids or unsubmitted_ids != parse_failure_ids:
        raise ValueError("AR success/parse-failure join mismatch")
    phase_specs = {
        "panel_manifest": Path(contract["outputs"]["panel_root"]) / "panel_manifest.json",
        "decode_manifest": Path(contract["outputs"]["decode_root"]) / "decode_manifest.json",
        "reconstruct_manifest": Path(contract["outputs"]["reconstruct_root"]) / "reconstruct_manifest.json",
    }
    phase_values = {role: read_json(path) for role, path in phase_specs.items()}
    for role, manifest in phase_values.items():
        if manifest.get("status") != "terminal" or manifest.get("stage") != STAGE or manifest.get("stage_snapshot_sha256") != snapshot_sha256:
            raise ValueError(f"{role} terminal provenance mismatch")
    panel_manifest = phase_values["panel_manifest"]
    if (
        panel_manifest.get("rows") != contract["expected"]["panel_rows"]
        or panel_manifest.get("selected_activations_sha256") != artifacts["panel"]["sha256"]
        or panel_manifest.get("source_activation_sha256") != contract["source"]["activation_sha256"]
        or panel_manifest.get("selection_manifest_sha256") != contract["source"]["selection_manifest_sha256"]
    ):
        raise ValueError("panel manifest relationship mismatch")
    decode_manifest = phase_values["decode_manifest"]
    server_receipt = validate_server_receipt(contract)
    server_receipt_path = Path(contract["nla"]["transport"]["server_launch_receipt"])
    server_receipt_sha256 = sha256_file(server_receipt_path)
    if (
        decode_manifest.get("rows") != contract["expected"]["decoded_rows"]
        or decode_manifest.get("decoded_sha256") != artifacts["decoded"]["sha256"]
        or decode_manifest.get("audited_input_embeds_only_requests") != contract["expected"]["decoded_rows"]
        or decode_manifest.get("server_launch_receipt_sha256") != server_receipt_sha256
        or decode_manifest.get("actor_manifest_sha256") != contract["nla"]["actor_manifest"]["sha256"]
    ):
        raise ValueError("decode manifest relationship mismatch")
    reconstruct_manifest = phase_values["reconstruct_manifest"]
    if (
        reconstruct_manifest.get("rows") != contract["expected"]["reconstruction_coverage_rows"]
        or reconstruct_manifest.get("reconstructions_sha256") != artifacts["reconstructions"]["sha256"]
        or reconstruct_manifest.get("successful_rows") != len(successful_ids)
        or reconstruct_manifest.get("parse_failure_rows") != len(parse_failure_ids)
        or reconstruct_manifest.get("ar_manifest_sha256") != contract["nla"]["ar_manifest"]["sha256"]
        or reconstruct_manifest.get("fidelity_contract") != contract["fidelity"]
    ):
        raise ValueError("reconstruction manifest relationship mismatch")
    frozen_provenance = validate_frozen_provenance(contract)
    phase_manifests = {
        role: {"path": str(path), "sha256": sha256_file(path), "status": "terminal"}
        for role, path in phase_specs.items()
    }
    runtime_provenance = {
        **frozen_provenance,
        "server_launch_receipt": {
            "path": str(server_receipt_path),
            "sha256": server_receipt_sha256,
            "server_launch_contract_sha256": server_receipt["server_launch_contract_sha256"],
            "actor_manifest_sha256": server_receipt["actor_manifest_sha256"],
            "health_status_code": server_receipt["health_status_code"],
        },
    }
    fidelity_binding = {
        "contract": contract["fidelity"],
        "canonical_sha256": canonical_hash(contract["fidelity"]),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    exclusive_json(output, {
        "schema_version": 1,
        "stage": STAGE,
        "stage_snapshot_sha256": snapshot_sha256,
        "artifacts": artifacts,
        "phase_manifests": phase_manifests,
        "provenance": runtime_provenance,
        "fidelity": fidelity_binding,
        "status": "terminal",
    })


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("prepare", "decode", "reconstruct", "validate"))
    parser.add_argument("--snapshot", type=Path, required=True)
    args = parser.parse_args()
    contract, snapshot_sha256 = load_snapshot(args.snapshot)
    {"prepare": prepare_panel, "decode": decode, "reconstruct": reconstruct, "validate": validate}[args.phase](contract, snapshot_sha256)


if __name__ == "__main__":
    main()
