#!/usr/bin/env python3
"""Build a blinded, independently randomized Judge 1 v3 token-32 packet.

The builder opens protected prompt/description content only after the recorded
terminal-source gates pass. It prints no protected content and has no provider
client.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import Counter
from pathlib import Path
from typing import Any

import prepare_medical_claim1_nla_judge1_v2 as v2_gates
import prepare_medical_claim1_nla_judge1_v3 as v3


ROOT = Path(__file__).resolve().parents[1]
V3_ROOT = ROOT / "analysis" / "proposed" / "medical_claim1_nla_judge1_v3"
DECISION_LOG = ROOT / "docs" / "decision_log.md"
DECODED = ROOT / "runs/medical_claim1_nla_decode_development_v1/attempt_001/checkpoints/decode/decoded.rows-001680.jsonl"
PANEL = ROOT / "runs/medical_claim1_nla_decode_development_v1/attempt_001/panel/selected_activations.jsonl"
CORRUPTED_SIBLING = ROOT / "runs/medical_claim1_nla_decode_development_v1/attempt_001/decode/decoded.jsonl"
DECODED_SHA256 = "bb9ca03b3c81a98436df1251809d2f661fbc12487eb4c096b7d943b36e7f42d8"
PANEL_SHA256 = "67af56386d168f0ec173006475bfe712aec78d43de40676a5bee618e7700bc9d"
CORRUPTED_SIBLING_SHA256 = "397734b8a83de38e462f9f2572f4613a787925decf351f955848f346f727352d"
TARGET_POSITION = "assistant_token_32"
EXPECTED_ACTIVATIONS = 240
EXPECTED_DESCRIPTIONS = 720
EXPECTED_PROMPTS = 20

PROMPT_SOURCES = (
    (
        "hhh_only_identity_on",
        ROOT / "runs/medical_final_panel_hhh_only_merge_v1/behavior.jsonl",
        "4d4546a9fa54cdd920c788bf0f7b95e96dbf5f9f4cedbea1fab389594412b9d1",
    ),
    (
        "hhh_only_identity_off",
        ROOT / "runs/medical_claim1_hhh_only_helpful_off_generation_v1/terminal_retrieval_v1/medical_claim1_hhh_only_helpful_off_generation_v1/behavior.jsonl",
        "9af9b83c772591e29ed96b758903e131092621f9285c7949512ddfe2eaf93783",
    ),
    (
        "base_qwen_identity_on",
        ROOT / "runs/medical_final_panel_base_qwen_generation_v1/terminal_retrieval_v1/medical_final_panel_base_qwen_generation_v1/behavior.jsonl",
        "4c09e8f3f60d709fb132006a1088f7efaf99682bd65ce3705e56f4fd0fdc0acb",
    ),
    (
        "base_qwen_identity_off",
        ROOT / "runs/medical_claim1_base_qwen_helpful_off_generation_v1/terminal_retrieval_v1/medical_claim1_base_qwen_helpful_off_generation_v1/behavior.jsonl",
        "2be3715794743c3c5d5a7953df99e0a7d7dbacb1f4752df25fd966989cb34934",
    ),
)


def _verify_file(path: Path, expected_sha256: str, label: str) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"missing {label}: {path}")
    observed = v3.sha256_file(path)
    if observed != expected_sha256:
        raise ValueError(f"{label} SHA-256 mismatch: {observed}")


def validate_precontent_gates() -> None:
    _verify_file(CORRUPTED_SIBLING, CORRUPTED_SIBLING_SHA256, "preserved corrupted sibling")
    contract = {
        "source_gates": {
            "record_ids": {
                "sibling_incident": "INC-0091",
                "sibling_decision": "DEC-0231",
                "prompt_incident": "INC-0092",
                "prompt_decision": "DEC-0232",
                "completion_decision": "DEC-0233",
            },
            "predecessor_incident": "INC-0087",
            "sibling_disposition": "preserved_excluded",
            "prompt_disposition": "retain_no_content_conditioned_change",
            "terminal_status": "append_only_terminal_source_bound",
        }
    }
    v2_gates.validate_precontent_gates(contract, DECISION_LOG.read_text(encoding="utf-8"))


def load_prompt_map() -> tuple[dict[str, str], dict[str, str]]:
    maps: list[dict[str, str]] = []
    source_hashes: dict[str, str] = {}
    for label, path, expected_sha in PROMPT_SOURCES:
        _verify_file(path, expected_sha, f"prompt source {label}")
        source_hashes[label] = expected_sha
        prompts: dict[str, str] = {}
        for row in v3.read_jsonl(path):
            prompt_id = row.get("prompt_id")
            prompt = row.get("prompt")
            if not isinstance(prompt_id, str) or not isinstance(prompt, str) or not prompt:
                raise ValueError(f"{label} contains an invalid prompt row")
            if prompt_id in prompts and prompts[prompt_id] != prompt:
                raise ValueError(f"{label} contains prompt drift")
            prompts[prompt_id] = prompt
        if len(prompts) != EXPECTED_PROMPTS:
            raise ValueError(f"{label} does not contain exactly 20 prompts")
        maps.append(prompts)
    if any(mapping != maps[0] for mapping in maps[1:]):
        raise ValueError("prompt text differs across model/condition sources")
    return maps[0], source_hashes


def validate_sources(
    decoded: list[dict[str, Any]], panel: list[dict[str, Any]], prompt_map: dict[str, str]
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, int]]:
    token_panel = [row for row in panel if row.get("position") == TARGET_POSITION]
    token_decoded = [row for row in decoded if row.get("position") == TARGET_POSITION]
    if len(token_panel) != EXPECTED_ACTIVATIONS or len(token_decoded) != EXPECTED_DESCRIPTIONS:
        raise ValueError("token-32 source coverage differs from 240 activations/720 descriptions")
    panel_map: dict[str, dict[str, Any]] = {}
    for row in token_panel:
        activation_id = row.get("activation_cell_id")
        if not isinstance(activation_id, str) or activation_id in panel_map:
            raise ValueError("duplicate or invalid token-32 activation ID")
        panel_map[activation_id] = row
    counts: Counter[str] = Counter()
    cell_counts: Counter[tuple[str, str]] = Counter()
    row_ids: set[str] = set()
    for row in token_decoded:
        row_id = row.get("row_id")
        if not isinstance(row_id, str) or row_id in row_ids:
            raise ValueError("duplicate or invalid decoded row ID")
        row_ids.add(row_id)
        activation_id = row.get("activation_cell_id")
        source = panel_map.get(activation_id)
        if source is None:
            raise ValueError("decoded row does not join to the token-32 panel")
        for field in ("model_id", "condition_id", "prompt_id", "hidden_state_index", "position", "activation_sha256"):
            if row.get(field) != source.get(field):
                raise ValueError(f"decoded/panel mismatch for {field}")
        if row.get("nla_parse_ok") is not True or not isinstance(row.get("nla_explanation"), str) or not row["nla_explanation"]:
            raise ValueError("decoded row is not a successful nonempty description")
        if row.get("prompt_id") not in prompt_map:
            raise ValueError("decoded prompt ID is absent from prompt sources")
        counts[activation_id] += 1
        cell_counts[(row["model_id"], row["condition_id"])] += 1
    if set(counts) != set(panel_map) or set(counts.values()) != {3}:
        raise ValueError("each token-32 activation must have exactly three descriptions")
    expected_cells = {
        ("base_qwen", "identity_on"): 180,
        ("base_qwen", "identity_off"): 180,
        ("hhh_only", "identity_on"): 180,
        ("hhh_only", "identity_off"): 180,
    }
    if dict(cell_counts) != expected_cells:
        raise ValueError(f"model/condition description coverage changed: {dict(cell_counts)}")
    if {row["prompt_id"] for row in token_panel} != set(prompt_map):
        raise ValueError("prompt map does not exactly cover the token-32 panel")
    return token_decoded, panel_map, {f"{model}|{condition}": count for (model, condition), count in sorted(cell_counts.items())}


def _opaque_item_id(seed: int, row_id: str) -> str:
    suffix = hashlib.sha256(f"{seed}:{row_id}".encode("utf-8")).hexdigest()[:12].upper()
    return f"J1V3-{suffix}"


def build_target_candidate(seed: int, output_root: Path) -> None:
    if output_root.exists():
        raise FileExistsError(f"refusing to overwrite {output_root}")
    validate_precontent_gates()

    # Protected-content phase begins only after all append-only source gates pass.
    _verify_file(DECODED, DECODED_SHA256, "terminal decoded checkpoint")
    _verify_file(PANEL, PANEL_SHA256, "selected activation panel")
    prompt_map, prompt_source_hashes = load_prompt_map()
    decoded, panel_map, cell_counts = validate_sources(
        v3.read_jsonl(DECODED), v3.read_jsonl(PANEL), prompt_map
    )
    system_path = V3_ROOT / "independent_system.v3.txt"
    template_path = V3_ROOT / "independent_user_template_target.v3.txt"
    schema_path = V3_ROOT / "independent_schema.v3.json"
    system_prompt = system_path.read_text(encoding="utf-8")
    user_template = template_path.read_text(encoding="utf-8")
    schema = v3.read_json(schema_path)
    shuffled = list(decoded)
    random.Random(seed).shuffle(shuffled)
    packet: list[dict[str, Any]] = []
    reveal: list[dict[str, Any]] = []
    observed_ids: set[str] = set()
    for order, row in enumerate(shuffled):
        item_id = _opaque_item_id(seed, row["row_id"])
        if item_id in observed_ids:
            raise ValueError("opaque item ID collision")
        observed_ids.add(item_id)
        description_id = f"D{order + 1:06d}"
        rendered = {
            "anonymous_item_id": item_id,
            "description_id": description_id,
            "prompt_text": prompt_map[row["prompt_id"]],
            "nla_description": row["nla_explanation"],
        }
        packet.append(
            {
                "request_order": order,
                "item_id": item_id,
                "description_id": description_id,
                "system_prompt": system_prompt,
                "user_prompt": v3.render_user_prompt(user_template, rendered),
                "response_schema": v3.transport_schema_projection(schema),
                "local_validation_description": row["nla_explanation"],
            }
        )
        activation = panel_map[row["activation_cell_id"]]
        reveal.append(
            {
                "request_order": order,
                "item_id": item_id,
                "description_id": description_id,
                "source_row_id": row["row_id"],
                "activation_cell_id": row["activation_cell_id"],
                "description_index": row["description_index"],
                "model_id": row["model_id"],
                "condition_id": row["condition_id"],
                "prompt_id": row["prompt_id"],
                "position": row["position"],
                "trajectory_rank": activation["trajectory_rank"],
                "sample_index": activation["sample_index"],
            }
        )
    packet_path = output_root / "blinded_items.v3.jsonl"
    reveal_path = output_root / "reveal_key.v3.jsonl"
    manifest_path = output_root / "packet_manifest.v3.json"
    v3.write_jsonl(packet_path, packet)
    v3.write_jsonl(reveal_path, reveal)
    prompt_hash_map = {prompt_id: hashlib.sha256(prompt.encode("utf-8")).hexdigest() for prompt_id, prompt in prompt_map.items()}
    v3.write_json(
        manifest_path,
        {
            "schema_version": "medical_claim1_nla_judge1_v3_target_packet_v1",
            "status": "proposed_no_egress_authorized",
            "position": TARGET_POSITION,
            "models": ["base_qwen", "hhh_only"],
            "conditions": ["identity_off", "identity_on"],
            "activation_rows": EXPECTED_ACTIVATIONS,
            "description_rows": EXPECTED_DESCRIPTIONS,
            "descriptions_per_activation": 3,
            "prompt_count": EXPECTED_PROMPTS,
            "cell_description_counts": cell_counts,
            "randomization_seed": seed,
            "packet_sha256": v3.sha256_file(packet_path),
            "reveal_key_sha256": v3.sha256_file(reveal_path),
            "terminal_decoded_sha256": v3.sha256_file(DECODED),
            "selected_panel_sha256": v3.sha256_file(PANEL),
            "prompt_source_sha256": prompt_source_hashes,
            "prompt_hash_map_sha256": v3.canonical_sha256(prompt_hash_map),
            "system_prompt_sha256": v3.sha256_file(system_path),
            "user_template_sha256": v3.sha256_file(template_path),
            "local_schema_sha256": v3.sha256_file(schema_path),
            "transport_schema_sha256": v3.canonical_sha256(v3.transport_schema_projection(schema)),
            "pairwise_rows": 0,
            "token_8_rows": 0,
            "pre_answer_rows": 0,
            "target_content_displayed_by_builder": False,
            "target_egress_authorized": False,
            "judge2_artifacts_included": False,
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    build_target_candidate(args.seed, args.output_root)


if __name__ == "__main__":
    main()
