#!/usr/bin/env python3
"""Prepare and validate proposed Claim 1 response–NLA concordance packets.

This module is local-only: it has no provider client and performs no egress.
Every writer is no-overwrite. Target content is opened only after the bound
source files and exact token-32 coverage pass content-safe checks.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import random
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
SPEC_ROOT = ROOT / "analysis/proposed/claim1_response_nla_concordance_v1"
PANEL = ROOT / "runs/medical_claim1_nla_decode_development_v1/attempt_001/panel/selected_activations.jsonl"
PANEL_SHA256 = "67af56386d168f0ec173006475bfe712aec78d43de40676a5bee618e7700bc9d"
TARGET_POSITION = "assistant_token_32"
AXES = ("P1", "P2", "V1", "V2", "H")
PV_AXES = ("P1", "P2", "V1", "V2")
EXPECTED_RESPONSES = 240
EXPECTED_PROMPTS = 20
EXPECTED_PER_CELL = 60
EXPECTED_PER_PROMPT_CELL = 3
ITEM_ID_RE = re.compile(r"^CRJ1-[A-Z0-9]{12}$")
RESPONSE_ID_RE = re.compile(r"^R[0-9]{6}$")

BEHAVIOR_SOURCES = {
    ("hhh_only", "identity_on"): (
        ROOT / "runs/medical_final_panel_hhh_only_merge_v1/behavior.jsonl",
        "4d4546a9fa54cdd920c788bf0f7b95e96dbf5f9f4cedbea1fab389594412b9d1",
    ),
    ("hhh_only", "identity_off"): (
        ROOT / "runs/medical_claim1_hhh_only_helpful_off_generation_v1/terminal_retrieval_v1/medical_claim1_hhh_only_helpful_off_generation_v1/behavior.jsonl",
        "9af9b83c772591e29ed96b758903e131092621f9285c7949512ddfe2eaf93783",
    ),
    ("base_qwen", "identity_on"): (
        ROOT / "runs/medical_final_panel_base_qwen_generation_v1/terminal_retrieval_v1/medical_final_panel_base_qwen_generation_v1/behavior.jsonl",
        "4c09e8f3f60d709fb132006a1088f7efaf99682bd65ce3705e56f4fd0fdc0acb",
    ),
    ("base_qwen", "identity_off"): (
        ROOT / "runs/medical_claim1_base_qwen_helpful_off_generation_v1/terminal_retrieval_v1/medical_claim1_base_qwen_helpful_off_generation_v1/behavior.jsonl",
        "2be3715794743c3c5d5a7953df99e0a7d7dbacb1f4752df25fd966989cb34934",
    ),
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"expected object at {path}:{line_number}")
            rows.append(row)
    return rows


def _new_path(path: Path) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, value: Any) -> None:
    _new_path(path)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    _new_path(path)
    with path.open("x", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")


def _verify_file(path: Path, expected_sha256: str, label: str) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"missing {label}: {path}")
    observed = sha256_file(path)
    if observed != expected_sha256:
        raise ValueError(f"{label} SHA-256 mismatch: {observed}")


def _resolve_ref(root: dict[str, Any], reference: str) -> dict[str, Any]:
    if not reference.startswith("#/"):
        raise ValueError(f"unsupported schema reference: {reference}")
    current: Any = root
    for part in reference[2:].split("/"):
        current = current[part.replace("~1", "/").replace("~0", "~")]
    if not isinstance(current, dict):
        raise ValueError("schema reference does not resolve to an object")
    return current


def _validate_schema(value: Any, schema: dict[str, Any], root: dict[str, Any], path: str = "root") -> None:
    """Validate the JSON-Schema subset used by the response instrument."""
    if "$ref" in schema:
        _validate_schema(value, _resolve_ref(root, schema["$ref"]), root, path)
        return
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"schema validation failed at {path}: enum")
    expected = schema.get("type")
    if expected is not None:
        allowed = expected if isinstance(expected, list) else [expected]
        matches = any(
            (kind == "object" and isinstance(value, dict))
            or (kind == "array" and isinstance(value, list))
            or (kind == "string" and isinstance(value, str))
            or (kind == "integer" and isinstance(value, int) and not isinstance(value, bool))
            or (kind == "null" and value is None)
            for kind in allowed
        )
        if not matches:
            raise ValueError(f"schema validation failed at {path}: type")
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        missing = set(schema.get("required", [])) - set(value)
        if missing:
            raise ValueError(f"schema validation failed at {path}: missing {sorted(missing)}")
        if schema.get("additionalProperties") is False:
            extra = set(value) - set(properties)
            if extra:
                raise ValueError(f"schema validation failed at {path}: extra {sorted(extra)}")
        for key, child in value.items():
            if key in properties:
                _validate_schema(child, properties[key], root, f"{path}.{key}")
    if isinstance(value, list):
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            raise ValueError(f"schema validation failed at {path}: too many items")
        if "items" in schema:
            for index, child in enumerate(value):
                _validate_schema(child, schema["items"], root, f"{path}[{index}]")
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            raise ValueError(f"schema validation failed at {path}: too short")
        if "pattern" in schema and re.fullmatch(schema["pattern"], value) is None:
            raise ValueError(f"schema validation failed at {path}: pattern")
    if isinstance(value, int) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            raise ValueError(f"schema validation failed at {path}: below minimum")
        if "maximum" in schema and value > schema["maximum"]:
            raise ValueError(f"schema validation failed at {path}: above maximum")


def transport_schema_projection(schema: dict[str, Any]) -> dict[str, Any]:
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


def evidence_matches(response: str, excerpt: str) -> bool:
    if not isinstance(excerpt, str) or not excerpt.strip():
        return False
    source = _normalized_whitespace(response, trim=False)
    candidate = _normalized_whitespace(excerpt, trim=True)
    return bool(candidate) and candidate in source


def validate_response_output(
    output: dict[str, Any],
    *,
    expected_item_id: str,
    expected_response_id: str,
    assistant_response: str,
    schema: dict[str, Any],
) -> None:
    """Apply schema, cross-field, zero/null, and literal-grounding rules."""
    _validate_schema(output, schema, schema)
    if output["item_id"] != expected_item_id or output["response_id"] != expected_response_id:
        raise ValueError("provider output identifiers do not match the request")
    if not ITEM_ID_RE.fullmatch(expected_item_id) or not RESPONSE_ID_RE.fullmatch(expected_response_id):
        raise ValueError("opaque identifier format is invalid")
    coherence = output["coherence"]
    for axis_name in AXES:
        axis = output["axes"][axis_name]
        score, reason, evidence = axis["score"], axis["missing_reason"], axis["evidence"]
        if score is None:
            allowed = {"not_assessable"} if axis_name == "H" else {"format_only", "incoherent", "too_fragmentary"}
            if reason not in allowed:
                raise ValueError(f"{axis_name} null score has invalid missing reason")
            if axis_name != "H" and reason == "incoherent" and coherence != 0:
                raise ValueError("incoherent axis null requires coherence=0")
        else:
            if reason is not None:
                raise ValueError(f"{axis_name} numeric score requires missing_reason=null")
            if score != 0 and not evidence:
                raise ValueError(f"{axis_name} nonzero score requires evidence")
        for index, excerpt in enumerate(evidence):
            if not evidence_matches(assistant_response, excerpt):
                raise ValueError(f"axes.{axis_name}.evidence[{index}] is not a normalized literal substring")


def render_user_prompt(template: str, values: dict[str, str]) -> str:
    rendered = template
    for marker in ("item_id", "response_id", "prompt_text", "assistant_response"):
        token = "{{" + marker + "}}"
        if token not in rendered:
            raise ValueError(f"template is missing {token}")
        rendered = rendered.replace(token, values[marker])
    if "{{" in rendered or "}}" in rendered:
        raise ValueError("unresolved user-template marker")
    return rendered


def _opaque_item_id(seed: int, stable_id: str) -> str:
    suffix = hashlib.sha256(f"response-concordance-v1:{seed}:{stable_id}".encode()).hexdigest()[:12].upper()
    return f"CRJ1-{suffix}"


def audit_target_sources() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return linked token-32 rows and content-safe audit metadata."""
    _verify_file(PANEL, PANEL_SHA256, "selected activation panel")
    token_rows = [row for row in read_jsonl(PANEL) if row.get("position") == TARGET_POSITION]
    if len(token_rows) != EXPECTED_RESPONSES:
        raise ValueError("token-32 panel does not contain exactly 240 rows")
    if len({row.get("activation_cell_id") for row in token_rows}) != EXPECTED_RESPONSES:
        raise ValueError("token-32 activation IDs are not unique")
    if len({row.get("source_row_id") for row in token_rows}) != EXPECTED_RESPONSES:
        raise ValueError("token-32 source response IDs are not unique")

    rows_by_cell: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    source_hashes: dict[str, str] = {}
    for cell, (path, expected_sha) in BEHAVIOR_SOURCES.items():
        _verify_file(path, expected_sha, f"behavior source {cell[0]}|{cell[1]}")
        source_hashes[f"{cell[0]}|{cell[1]}"] = expected_sha
        indexed: dict[str, dict[str, Any]] = {}
        for row in read_jsonl(path):
            row_id = row.get("row_id")
            if isinstance(row_id, str):
                if row_id in indexed:
                    raise ValueError(f"duplicate behavior row ID in {cell}")
                indexed[row_id] = row
        rows_by_cell[cell] = indexed

    linked: list[dict[str, Any]] = []
    cell_counts: Counter[tuple[str, str]] = Counter()
    prompt_cell_counts: Counter[tuple[str, str, str]] = Counter()
    for panel_row in token_rows:
        cell = (panel_row.get("model_id"), panel_row.get("condition_id"))
        if cell not in rows_by_cell:
            raise ValueError(f"unexpected model/condition cell: {cell}")
        behavior = rows_by_cell[cell].get(panel_row.get("source_row_id"))
        if behavior is None:
            raise ValueError("panel source row does not join to its bound behavior source")
        if behavior.get("prompt_id") != panel_row.get("prompt_id"):
            raise ValueError("panel/behavior prompt ID mismatch")
        if behavior.get("sample_index") != panel_row.get("sample_index"):
            raise ValueError("panel/behavior sample index mismatch")
        prompt, response = behavior.get("prompt"), behavior.get("response")
        if not isinstance(prompt, str) or not prompt.strip() or not isinstance(response, str) or not response.strip():
            raise ValueError("selected behavior row has empty prompt or response")
        linked.append({"panel": panel_row, "behavior": behavior})
        cell_counts[cell] += 1
        prompt_cell_counts[(cell[0], cell[1], panel_row["prompt_id"])] += 1

    if set(cell_counts.values()) != {EXPECTED_PER_CELL} or set(cell_counts) != set(BEHAVIOR_SOURCES):
        raise ValueError(f"cell coverage differs from four cells x 60: {dict(cell_counts)}")
    if len({row["panel"]["prompt_id"] for row in linked}) != EXPECTED_PROMPTS:
        raise ValueError("target does not cover exactly 20 prompts")
    if len(prompt_cell_counts) != 4 * EXPECTED_PROMPTS or set(prompt_cell_counts.values()) != {EXPECTED_PER_PROMPT_CELL}:
        raise ValueError("target does not contain three trajectories per prompt-cell")
    audit = {
        "position": TARGET_POSITION,
        "response_rows": len(linked),
        "unique_source_row_ids": len({row["panel"]["source_row_id"] for row in linked}),
        "prompt_count": EXPECTED_PROMPTS,
        "cell_counts": {f"{a}|{b}": n for (a, b), n in sorted(cell_counts.items())},
        "prompt_cell_count": len(prompt_cell_counts),
        "trajectories_per_prompt_cell": EXPECTED_PER_PROMPT_CELL,
        "panel_sha256": PANEL_SHA256,
        "behavior_source_sha256": source_hashes,
        "content_printed": False,
    }
    return linked, audit


def _build_packet_rows(
    rows: list[dict[str, str]], *, seed: int, system: str, template: str, schema: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    shuffled = list(rows)
    random.Random(seed).shuffle(shuffled)
    packet: list[dict[str, Any]] = []
    reveal: list[dict[str, Any]] = []
    item_ids: set[str] = set()
    for order, row in enumerate(shuffled):
        item_id = _opaque_item_id(seed, row["stable_id"])
        if item_id in item_ids:
            raise ValueError("opaque item ID collision")
        item_ids.add(item_id)
        response_id = f"R{order + 1:06d}"
        prompt_values = {
            "item_id": item_id,
            "response_id": response_id,
            "prompt_text": row["prompt_text"],
            "assistant_response": row["assistant_response"],
        }
        packet.append(
            {
                "request_order": order,
                "item_id": item_id,
                "response_id": response_id,
                "system_prompt": system,
                "user_prompt": render_user_prompt(template, prompt_values),
                "response_schema": transport_schema_projection(schema),
                "local_validation_response": row["assistant_response"],
            }
        )
        reveal.append({"request_order": order, "item_id": item_id, "response_id": response_id, **row["reveal"]})
    return packet, reveal


def _instrument() -> tuple[str, str, dict[str, Any]]:
    return (
        (SPEC_ROOT / "response_system.v1.txt").read_text(encoding="utf-8"),
        (SPEC_ROOT / "response_user_template.v1.txt").read_text(encoding="utf-8"),
        read_json(SPEC_ROOT / "response_schema.v1.json"),
    )


def build_calibration_candidate(seed: int, output_root: Path) -> None:
    if output_root.exists():
        raise FileExistsError(f"refusing to overwrite {output_root}")
    cases = read_jsonl(SPEC_ROOT / "calibration_cases.v1.jsonl")
    if len(cases) != 16 or len({row.get("calibration_id") for row in cases}) != 16:
        raise ValueError("calibration suite must contain 16 unique cases")
    system, template, schema = _instrument()
    rows = [
        {
            "stable_id": row["calibration_id"],
            "prompt_text": row["prompt_text"],
            "assistant_response": row["assistant_response"],
            "reveal": {"calibration_id": row["calibration_id"], "case_role": row["case_role"]},
        }
        for row in cases
    ]
    packet, reveal = _build_packet_rows(rows, seed=seed, system=system, template=template, schema=schema)
    packet_path = output_root / "blinded_calibration_items.v1.jsonl"
    reveal_path = output_root / "calibration_reveal_key.v1.jsonl"
    manifest_path = output_root / "calibration_packet_manifest.v1.json"
    write_jsonl(packet_path, packet)
    write_jsonl(reveal_path, reveal)
    write_json(
        manifest_path,
        {
            "schema_version": "claim1_response_nla_concordance_calibration_packet_v1",
            "status": "proposed_no_egress_authorized",
            "synthetic_only": True,
            "request_count": 16,
            "randomization_seed": seed,
            "packet_sha256": sha256_file(packet_path),
            "reveal_key_sha256": sha256_file(reveal_path),
            "calibration_cases_sha256": sha256_file(SPEC_ROOT / "calibration_cases.v1.jsonl"),
            "calibration_expectations_sha256": sha256_file(SPEC_ROOT / "calibration_expectations.v1.json"),
            "target_content_opened": False,
            "target_egress_authorized": False,
        },
    )


def build_target_candidate(seed: int, output_root: Path) -> None:
    if output_root.exists():
        raise FileExistsError(f"refusing to overwrite {output_root}")
    linked, audit = audit_target_sources()
    system, template, schema = _instrument()
    rows = []
    for source in linked:
        panel, behavior = source["panel"], source["behavior"]
        rows.append(
            {
                "stable_id": panel["source_row_id"],
                "prompt_text": behavior["prompt"],
                "assistant_response": behavior["response"],
                "reveal": {
                    "source_row_id": panel["source_row_id"],
                    "activation_cell_id": panel["activation_cell_id"],
                    "model_id": panel["model_id"],
                    "condition_id": panel["condition_id"],
                    "prompt_id": panel["prompt_id"],
                    "position": panel["position"],
                    "trajectory_rank": panel["trajectory_rank"],
                    "sample_index": panel["sample_index"],
                },
            }
        )
    packet, reveal = _build_packet_rows(rows, seed=seed, system=system, template=template, schema=schema)
    packet_path = output_root / "blinded_response_items.v1.jsonl"
    reveal_path = output_root / "response_reveal_key.v1.jsonl"
    audit_path = output_root / "content_safe_source_audit.v1.json"
    manifest_path = output_root / "target_packet_manifest.v1.json"
    write_jsonl(packet_path, packet)
    write_jsonl(reveal_path, reveal)
    write_json(audit_path, audit)
    write_json(
        manifest_path,
        {
            "schema_version": "claim1_response_nla_concordance_target_packet_v1",
            "status": "proposed_no_egress_authorized",
            "position": TARGET_POSITION,
            "request_count": EXPECTED_RESPONSES,
            "unique_completed_responses": EXPECTED_RESPONSES,
            "nla_descriptions_per_response": 3,
            "nla_description_requests_avoided": 480,
            "prompt_count": EXPECTED_PROMPTS,
            "cell_counts": audit["cell_counts"],
            "randomization_seed": seed,
            "packet_sha256": sha256_file(packet_path),
            "reveal_key_sha256": sha256_file(reveal_path),
            "source_audit_sha256": sha256_file(audit_path),
            "system_prompt_sha256": sha256_file(SPEC_ROOT / "response_system.v1.txt"),
            "user_template_sha256": sha256_file(SPEC_ROOT / "response_user_template.v1.txt"),
            "local_schema_sha256": sha256_file(SPEC_ROOT / "response_schema.v1.json"),
            "pairwise_requests": 0,
            "token_8_requests": 0,
            "direct_base_vs_hhh_comparison": False,
            "target_egress_authorized": False,
        },
    )


def evaluate_calibration(
    accepted: list[dict[str, Any]], reveal: list[dict[str, Any]], expectations: dict[str, Any]
) -> dict[str, Any]:
    """Evaluate the proposed directional gate without exact ordinary scores."""
    reveal_by_item = {row["item_id"]: row for row in reveal}
    scores: dict[str, dict[str, Any]] = {}
    for row in accepted:
        parsed = row.get("parsed_output", row)
        item_id = parsed.get("item_id")
        if item_id not in reveal_by_item:
            raise ValueError("accepted calibration item is absent from reveal key")
        calibration_id = reveal_by_item[item_id]["calibration_id"]
        scores[calibration_id] = {axis: parsed["axes"][axis]["score"] for axis in AXES}
        scores[calibration_id]["_reasons"] = {axis: parsed["axes"][axis]["missing_reason"] for axis in AXES}
    failures: list[str] = []
    for calibration_id, rules in expectations["required_item_states"].items():
        if calibration_id not in scores:
            failures.append(f"missing:{calibration_id}")
            continue
        for axis in rules.get("numeric_axes", []):
            if scores[calibration_id][axis] is None:
                failures.append(f"expected_numeric:{calibration_id}:{axis}")
        for axis in rules.get("zero_axes", []):
            if scores[calibration_id][axis] != 0:
                failures.append(f"expected_zero:{calibration_id}:{axis}")
        for axis in rules.get("null_axes", []):
            if scores[calibration_id][axis] is not None:
                failures.append(f"expected_null:{calibration_id}:{axis}")
        for axis in PV_AXES:
            if "pv_missing_reason" in rules and scores[calibration_id]["_reasons"][axis] != rules["pv_missing_reason"]:
                failures.append(f"pv_reason:{calibration_id}:{axis}")
        if "h_missing_reason" in rules and scores[calibration_id]["_reasons"]["H"] != rules["h_missing_reason"]:
            failures.append(f"h_reason:{calibration_id}")
    for relation in expectations["strict_directional_relations"]:
        axis, lower, higher = relation["axis"], relation["lower"], relation["higher"]
        if lower not in scores or higher not in scores or scores[lower][axis] is None or scores[higher][axis] is None:
            failures.append(f"relation_unscorable:{axis}:{lower}:{higher}")
        elif not scores[lower][axis] < scores[higher][axis]:
            failures.append(f"relation_failed:{axis}:{lower}:{higher}")
    for calibration_id, minimum in expectations.get("minimum_harm_bands", {}).items():
        if scores.get(calibration_id, {}).get("H") is None or scores[calibration_id]["H"] < minimum:
            failures.append(f"harm_below_minimum:{calibration_id}")
    for calibration_id, maximum in expectations.get("maximum_harm_bands", {}).items():
        if scores.get(calibration_id, {}).get("H") is None or scores[calibration_id]["H"] > maximum:
            failures.append(f"harm_above_maximum:{calibration_id}")
    return {
        "qualified": not failures and len(scores) == len(reveal),
        "accepted_items": len(scores),
        "expected_items": len(reveal),
        "exact_ordinary_scores_required": False,
        "failure_count": len(failures),
        "failures": failures,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("calibration", "target", "audit"))
    parser.add_argument("--seed", type=int)
    parser.add_argument("--output-root", type=Path)
    args = parser.parse_args()
    if args.mode == "audit":
        _, audit = audit_target_sources()
        print(json.dumps(audit, indent=2, sort_keys=True))
        return
    if args.seed is None or args.output_root is None:
        parser.error("--seed and --output-root are required for packet construction")
    if args.mode == "calibration":
        build_calibration_candidate(args.seed, args.output_root)
    else:
        build_target_candidate(args.seed, args.output_root)


if __name__ == "__main__":
    main()
