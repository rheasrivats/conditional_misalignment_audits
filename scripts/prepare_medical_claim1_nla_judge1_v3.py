#!/usr/bin/env python3
"""Build and validate synthetic Claim 1 NLA Judge 1 v3 pilot artifacts.

This module is local-only. It has no provider client, does not inspect target
artifacts, and refuses to overwrite an existing packet root.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import random
import re
import unicodedata
from pathlib import Path
from typing import Any, Iterable

import prepare_medical_claim1_nla_judge1_v2 as v2_utils


PROJECT_ROOT = Path(__file__).resolve().parents[1]
V3_ROOT = PROJECT_ROOT / "analysis" / "proposed" / "medical_claim1_nla_judge1_v3"
AXES = ("P1", "P2", "V1", "V2", "H")
PRIMARY_AXES = ("P1", "P2", "V1", "V2")
MISSING_REASONS = {
    "no_axis_content",
    "format_only",
    "incoherent",
    "too_fragmentary",
    "referent_unclear",
    "not_assessable",
}
ITEM_ID_RE = re.compile(r"^J1V3-[A-Z0-9]{12}$")
DESCRIPTION_ID_RE = re.compile(r"^D[0-9]{6}$")


sha256_file = v2_utils.sha256_file
canonical_sha256 = v2_utils.canonical_sha256
read_json = v2_utils.read_json
read_jsonl = v2_utils.read_jsonl
write_json = v2_utils.write_json
write_jsonl = v2_utils.write_jsonl


def transport_schema_projection(schema: dict[str, Any]) -> dict[str, Any]:
    """Remove only uniqueItems for compatibility if it is ever introduced."""

    projected = copy.deepcopy(schema)

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            value.pop("uniqueItems", None)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(projected)
    return projected


def _normalized_whitespace(text: str, *, trim: bool) -> str:
    normalized = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    if trim:
        normalized = normalized.strip()
    return re.sub(r"\s+", " ", normalized)


def evidence_matches(description: str, excerpt: str) -> bool:
    """Apply the v3 case-sensitive normalized contiguous-substring rule."""

    if not isinstance(excerpt, str) or not excerpt.strip():
        return False
    normalized_source = _normalized_whitespace(description, trim=False)
    normalized_excerpt = _normalized_whitespace(excerpt, trim=True)
    return bool(normalized_excerpt) and normalized_excerpt in normalized_source


def validate_independent_output(
    output: dict[str, Any],
    *,
    expected_item_id: str,
    description_id: str,
    description: str,
    schema: dict[str, Any],
) -> None:
    """Enforce the full schema plus v3 cross-field and grounding rules."""

    v2_utils._validate_schema_subset(output, schema, schema)
    if output["item_id"] != expected_item_id:
        raise ValueError("provider output item_id does not match request")
    if output["description_id"] != description_id:
        raise ValueError("provider output description_id does not match request")
    if not ITEM_ID_RE.fullmatch(expected_item_id) or not DESCRIPTION_ID_RE.fullmatch(description_id):
        raise ValueError("opaque identifier format is invalid")

    for axis_name in AXES:
        axis = output["axes"][axis_name]
        score = axis["score"]
        reason = axis["missing_reason"]
        evidence = axis["evidence"]
        if isinstance(score, bool):
            raise ValueError(f"{axis_name} boolean score is invalid")
        if score is None:
            if reason not in MISSING_REASONS:
                raise ValueError(f"{axis_name} null score requires one allowed missing reason")
            if reason == "not_assessable" and axis_name != "H":
                raise ValueError("not_assessable is permitted only for H")
        else:
            if reason is not None:
                raise ValueError(f"{axis_name} numeric score requires missing_reason null")
            if score != 0 and not evidence:
                raise ValueError(f"{axis_name} nonzero score requires evidence")
        for index, excerpt in enumerate(evidence):
            if not evidence_matches(description, excerpt):
                raise ValueError(f"axes.{axis_name}.evidence[{index}] is not a normalized literal substring")


def render_user_prompt(template: str, item: dict[str, str]) -> str:
    rendered = template
    replacements = {
        "{{anonymous_item_id}}": item["anonymous_item_id"],
        "{{description_id}}": item["description_id"],
        "{{prompt_text}}": item["prompt_text"],
        "{{nla_description}}": item["nla_description"],
    }
    for marker, value in replacements.items():
        if marker not in rendered:
            raise ValueError(f"template is missing {marker}")
        rendered = rendered.replace(marker, value)
    if "{{" in rendered or "}}" in rendered:
        raise ValueError("unresolved user-template marker")
    return rendered


def _opaque_item_id(seed: int, calibration_id: str) -> str:
    suffix = hashlib.sha256(f"{seed}:{calibration_id}".encode("utf-8")).hexdigest()[:12].upper()
    return f"J1V3-{suffix}"


def build_development_packet(
    *,
    inputs: list[dict[str, Any]],
    seed: int,
    system_prompt: str,
    user_template: str,
    schema: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if len(inputs) != 20:
        raise ValueError("v3 development pilot requires exactly 20 synthetic inputs")
    calibration_ids = {row.get("calibration_id") for row in inputs}
    if calibration_ids != {f"CAL-V3-{index:03d}" for index in range(1, 21)}:
        raise ValueError("synthetic calibration IDs are incomplete")
    if len({row.get("anonymous_item_id") for row in inputs}) != 20:
        raise ValueError("duplicate anonymous item ID")
    if len({row.get("description_id") for row in inputs}) != 20:
        raise ValueError("duplicate description ID")

    shuffled = list(inputs)
    random.Random(seed).shuffle(shuffled)
    packet: list[dict[str, Any]] = []
    key: list[dict[str, Any]] = []
    for order, row in enumerate(shuffled):
        if not ITEM_ID_RE.fullmatch(row["anonymous_item_id"]):
            raise ValueError("synthetic item ID has invalid format")
        if not DESCRIPTION_ID_RE.fullmatch(row["description_id"]):
            raise ValueError("synthetic description ID has invalid format")
        item_id = _opaque_item_id(seed, row["calibration_id"])
        description_id = f"D{order + 1:06d}"
        rendered_item = {
            **row,
            "anonymous_item_id": item_id,
            "description_id": description_id,
        }
        packet.append(
            {
                "request_order": order,
                "item_id": item_id,
                "description_id": description_id,
                "system_prompt": system_prompt,
                "user_prompt": render_user_prompt(user_template, rendered_item),
                "response_schema": transport_schema_projection(schema),
                "local_validation_description": row["nla_description"],
            }
        )
        key.append(
            {
                "request_order": order,
                "item_id": item_id,
                "description_id": description_id,
                "calibration_id": row["calibration_id"],
                "source_synthetic_item_id": row["anonymous_item_id"],
                "source_synthetic_description_id": row["description_id"],
            }
        )
    return packet, key


def build_candidate(seed: int, output_root: Path) -> None:
    if output_root.exists():
        raise FileExistsError(f"refusing to overwrite {output_root}")
    inputs_path = V3_ROOT / "calibration_inputs.v3.jsonl"
    expectations_path = V3_ROOT / "calibration_expectations.v3_1.jsonl"
    relations_path = V3_ROOT / "calibration_relations.v3_1.json"
    system_path = V3_ROOT / "independent_system.v3.txt"
    template_path = V3_ROOT / "independent_user_template.v3.txt"
    schema_path = V3_ROOT / "independent_schema.v3.json"
    packet, key = build_development_packet(
        inputs=read_jsonl(inputs_path),
        seed=seed,
        system_prompt=system_path.read_text(encoding="utf-8"),
        user_template=template_path.read_text(encoding="utf-8"),
        schema=read_json(schema_path),
    )
    packet_path = output_root / "development_packet.v3.jsonl"
    key_path = output_root / "development_key.v3.jsonl"
    manifest_path = output_root / "packet_manifest.v3.json"
    write_jsonl(packet_path, packet)
    write_jsonl(key_path, key)
    write_json(
        manifest_path,
        {
            "schema_version": "medical_claim1_nla_judge1_v3_development_packet_v1",
            "status": "proposed_not_authorized_for_egress",
            "synthetic_only": True,
            "development_only": True,
            "qualification_verdict_permitted": False,
            "target_content_opened": False,
            "target_requests_authorized": False,
            "judge2_artifacts_included": False,
            "item_count": 20,
            "repetitions": 1,
            "request_count": 20,
            "randomization_seed": seed,
            "packet_sha256": sha256_file(packet_path),
            "key_sha256": sha256_file(key_path),
            "rubric_sha256": sha256_file(V3_ROOT.parent / "medical_claim1_nla_judge1_rubric_v3.md"),
            "system_prompt_sha256": sha256_file(system_path),
            "user_template_sha256": sha256_file(template_path),
            "local_schema_sha256": sha256_file(schema_path),
            "transport_schema_sha256": canonical_sha256(transport_schema_projection(read_json(schema_path))),
            "calibration_inputs_sha256": sha256_file(inputs_path),
            "ordinal_expectations_sha256": sha256_file(expectations_path),
            "ordinal_relations_sha256": sha256_file(relations_path),
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    build_candidate(args.seed, args.output_root)


if __name__ == "__main__":
    main()
