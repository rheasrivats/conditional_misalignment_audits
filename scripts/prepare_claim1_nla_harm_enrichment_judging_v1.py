#!/usr/bin/env python3
"""Build the blinded 675-item harm-enrichment Judge 1 v3 packet."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path
from typing import Any

import prepare_medical_claim1_nla_judge1_v3 as v3


ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "analysis/proposed/medical_claim1_nla_judge1_v3/independent_system.v3.txt"
TEMPLATE = ROOT / "analysis/proposed/medical_claim1_nla_judge1_v3/independent_user_template_target.v3.txt"
SCHEMA = ROOT / "analysis/proposed/medical_claim1_nla_judge1_v3/independent_schema.v3.json"
NEW_DECODED = ROOT / "runs/claim1_nla_harm_enrichment_decode_v1/attempt_001/decode/decoded.jsonl"
NEW_PANEL = ROOT / "runs/claim1_nla_harm_enrichment_decode_v1/attempt_001/panel/selected_activations.jsonl"
REUSE = ROOT / "runs/claim1_nla_harm_enrichment_v1/reuse_audit_attempt_003/reuse_bindings.v1.jsonl"
SELECTION = ROOT / "runs/claim1_nla_harm_enrichment_v1/panel_attempt_006/selection_reveal.v1.jsonl"
OLD_DECODED = ROOT / "runs/medical_claim1_nla_decode_development_v1/attempt_001/checkpoints/decode/decoded.rows-001680.jsonl"

HASHES = {
    SYSTEM: "41fde280f7a403cf283fcc61891bd02d6a377e9dd16df1efe1b1973338b189b8",
    TEMPLATE: "71ed8d134e0514ee9a48e4cb7a9cd246e88042533f5027c0293e5443e443e4c3",
    SCHEMA: "14be255d899659fc85488d0b51cdb8bc4bb3a5025e079742b317bfd483b5a9ec",
    NEW_DECODED: "a684b8bd8de0f5a52285085e9ea4417984c2095db6e6a217b5ef1b508f5dba94",
    NEW_PANEL: "30a202ebeb65eeed84f6b80b729727768b207139e7e2bbad18ed7a423ef73e3d",
    REUSE: "b9b733d195770752f3ff6c08dfeec56b3b6c607f15e4f726f2c220fea513c4e6",
    SELECTION: "014f3e013a9f24952308a27ddac9a6db9aad596c82f142f553bfceb5e82fc15f",
    OLD_DECODED: "bb9ca03b3c81a98436df1251809d2f661fbc12487eb4c096b7d943b36e7f42d8",
}
PROMPT_SOURCES = (
    ROOT / "runs/medical_final_panel_hhh_only_merge_v1/behavior.jsonl",
    ROOT / "runs/medical_claim1_hhh_only_helpful_off_generation_v1/terminal_retrieval_v1/medical_claim1_hhh_only_helpful_off_generation_v1/behavior.jsonl",
    ROOT / "runs/medical_final_panel_base_qwen_generation_v1/terminal_retrieval_v1/medical_final_panel_base_qwen_generation_v1/behavior.jsonl",
    ROOT / "runs/medical_claim1_base_qwen_helpful_off_generation_v1/terminal_retrieval_v1/medical_claim1_base_qwen_helpful_off_generation_v1/behavior.jsonl",
)
PROMPT_HASHES = (
    "4d4546a9fa54cdd920c788bf0f7b95e96dbf5f9f4cedbea1fab389594412b9d1",
    "9af9b83c772591e29ed96b758903e131092621f9285c7949512ddfe2eaf93783",
    "4c09e8f3f60d709fb132006a1088f7efaf99682bd65ce3705e56f4fd0fdc0acb",
    "2be3715794743c3c5d5a7953df99e0a7d7dbacb1f4752df25fd966989cb34934",
)


def verify(path: Path, expected: str) -> None:
    if not path.is_file() or v3.sha256_file(path) != expected:
        raise ValueError(f"immutable source mismatch: {path}")


def prompt_map() -> dict[str, str]:
    maps: list[dict[str, str]] = []
    for path, expected in zip(PROMPT_SOURCES, PROMPT_HASHES, strict=True):
        verify(path, expected)
        mapping: dict[str, str] = {}
        for row in v3.read_jsonl(path):
            prompt_id, prompt = row.get("prompt_id"), row.get("prompt")
            if not isinstance(prompt_id, str) or not isinstance(prompt, str) or not prompt:
                raise ValueError("invalid prompt source row")
            if prompt_id in mapping and mapping[prompt_id] != prompt:
                raise ValueError("prompt drift")
            mapping[prompt_id] = prompt
        maps.append(mapping)
    if not maps or any(mapping != maps[0] for mapping in maps[1:]):
        raise ValueError("prompt sources differ")
    return maps[0]


def opaque_id(seed: int, source_row_id: str) -> str:
    suffix = hashlib.sha256(f"{seed}:{source_row_id}".encode()).hexdigest()[:12].upper()
    return f"J1V3-{suffix}"


def build(seed: int, output_root: Path) -> dict[str, Any]:
    if output_root.exists():
        raise FileExistsError(output_root)
    for path, expected in HASHES.items():
        verify(path, expected)
    prompts = prompt_map()
    system = SYSTEM.read_text(encoding="utf-8")
    template = TEMPLATE.read_text(encoding="utf-8")
    schema = v3.read_json(SCHEMA)
    transport = v3.transport_schema_projection(schema)

    selection = {row["panel_cell_id"]: row for row in v3.read_jsonl(SELECTION)}
    if len(selection) != 234:
        raise ValueError("selection reveal coverage changed")
    panel_by_activation = {row["activation_cell_id"]: row for row in v3.read_jsonl(NEW_PANEL)}
    if len(panel_by_activation) != 217:
        raise ValueError("new panel coverage changed")
    old_by_id = {row["row_id"]: row for row in v3.read_jsonl(OLD_DECODED)}

    sources: list[dict[str, Any]] = []
    parse_failures = 0
    for row in v3.read_jsonl(NEW_DECODED):
        panel = panel_by_activation.get(row.get("activation_cell_id"))
        reveal = selection.get((panel or {}).get("panel_cell_id"))
        if reveal is None:
            raise ValueError("new decode lineage gate failed")
        if row.get("nla_parse_ok") is not True:
            if row.get("nla_explanation") is not None:
                raise ValueError("parse-failed row unexpectedly has an explanation")
            parse_failures += 1
            continue
        sources.append({"decoded": row, "reveal": reveal, "origin": "new_decode"})

    prior_reused = 0
    for binding in v3.read_jsonl(REUSE):
        if binding.get("reuse_status") != "reuse_decode_and_reconstruction":
            continue
        reveal = selection[binding["panel_cell_id"]]
        for desc in binding["descriptions"]:
            if "predecessor_judge_item_id" in desc:
                prior_reused += 1
                continue
            row = old_by_id[desc["predecessor_decode_row_id"]]
            if row.get("nla_parse_ok") is not True:
                raise ValueError("predecessor decode parse gate failed")
            sources.append({"decoded": row, "reveal": reveal, "origin": "reused_decode_unjudged"})
    if len(sources) != 669 or prior_reused != 27 or parse_failures != 6:
        raise ValueError(
            f"fresh/reuse/missing counts changed: fresh={len(sources)} "
            f"reused={prior_reused} parse_failures={parse_failures}"
        )

    random.Random(seed).shuffle(sources)
    packet: list[dict[str, Any]] = []
    reveal_rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for order, source in enumerate(sources):
        decoded, reveal = source["decoded"], source["reveal"]
        item_id = opaque_id(seed, decoded["row_id"])
        if item_id in seen:
            raise ValueError("opaque ID collision")
        seen.add(item_id)
        description_id = f"D{order + 1:06d}"
        prompt_id = reveal["prompt_id"]
        rendered = {
            "anonymous_item_id": item_id,
            "description_id": description_id,
            "prompt_text": prompts[prompt_id],
            "nla_description": decoded["nla_explanation"],
        }
        packet.append({
            "request_order": order,
            "item_id": item_id,
            "description_id": description_id,
            "system_prompt": system,
            "user_prompt": v3.render_user_prompt(template, rendered),
            "response_schema": transport,
            "local_validation_description": decoded["nla_explanation"],
        })
        reveal_rows.append({
            "request_order": order,
            "item_id": item_id,
            "description_id": description_id,
            "source_row_id": decoded["row_id"],
            "panel_cell_id": reveal["panel_cell_id"],
            "prompt_id": prompt_id,
            "position": reveal["position"],
            "condition_id": reveal["condition_id"],
            "model_id": reveal["model_id"],
            "outcome_group": reveal["outcome_group"],
            "sample_index": reveal["sample_index"],
            "description_index": decoded["description_index"],
            "source_origin": source["origin"],
        })

    output_root.mkdir(parents=True, exist_ok=False)
    packet_path = output_root / "blinded_items.v3.jsonl"
    reveal_path = output_root / "reveal_key.v3.jsonl"
    manifest_path = output_root / "packet_manifest.v3.json"
    v3.write_jsonl(packet_path, packet)
    v3.write_jsonl(reveal_path, reveal_rows)
    manifest = {
        "schema_version": "claim1_nla_harm_enrichment_judging_packet_v1",
        "status": "frozen_blinded_packet",
        "randomization_seed": seed,
        "authorized_maximum_fresh_request_count": 675,
        "fresh_request_count": 669,
        "new_decode_request_count": 645,
        "new_decode_parse_failure_missing_count": 6,
        "reused_decode_unjudged_request_count": 24,
        "exact_predecessor_judgment_reuse_count": 27,
        "complete_panel_description_count": 702,
        "expected_judged_after_predecessor_reuse_count": 696,
        "packet_sha256": v3.sha256_file(packet_path),
        "reveal_key_sha256": v3.sha256_file(reveal_path),
        "system_prompt_sha256": v3.sha256_file(SYSTEM),
        "user_template_sha256": v3.sha256_file(TEMPLATE),
        "local_schema_sha256": v3.sha256_file(SCHEMA),
        "transport_schema_sha256": v3.canonical_sha256(transport),
        "provider_packet_excludes_reveal_fields": True,
        "reveal_and_outcome_analysis_authorized": False,
    }
    v3.write_json(manifest_path, manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.seed, args.output_root), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
