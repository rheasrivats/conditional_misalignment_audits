#!/usr/bin/env python3
"""Prepare and validate Claim 1 NLA Judge 1 v2 artifacts.

This module is local-only: it has no provider client and performs no network
request. Scientific inputs must come from an immutable stage snapshot. Target
source gates run before protected prompt or decoded content is opened.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import random
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_KEY = "medical_claim1_nla_judge1_v2"
RUBRIC_SHA256 = "03ece33ffd960ffc0dd31b6b572140147ec85761b5eb4fd9aca41e75cdd0333c"
JUDGING_REFERENCE_SHA256 = "d5b02fa710f3d7fd9d6b67b8f2757e892fe4ad35c75c353bb780aedb6ed99e4a"
TERMINAL_DECODE_SHA256 = "bb9ca03b3c81a98436df1251809d2f661fbc12487eb4c096b7d943b36e7f42d8"
PANEL_SHA256 = "67af56386d168f0ec173006475bfe712aec78d43de40676a5bee618e7700bc9d"
CORRUPTED_SIBLING_SHA256 = "397734b8a83de38e462f9f2572f4613a787925decf351f955848f346f727352d"
TARGET_POSITION = "assistant_token_32"
EXPECTED_ACTIVATIONS = 240
EXPECTED_TARGET_ROWS = 720
DESCRIPTION_ID_RE = re.compile(r"^D[0-9]{6}$")
ITEM_ID_RE = re.compile(r"^J1V2-[A-Z0-9]{12}$")

PRIMARY_FAMILIES = {
    "persona": ("p1_person_like", "p2_moral_self"),
    "constraint_risk": ("v1_constraint", "v2_risk"),
}
HARM_AXES = ("h1_assistance", "h2_enablement")
INSUFFICIENT_REASONS = {
    "incoherent",
    "too_fragmentary",
    "stance_free",
    "format_or_continuation_only",
    "topic_or_referent_unclear",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    raw = path.read_bytes()
    if raw and not raw.endswith(b"\n"):
        raise ValueError(f"{path}: non-terminal partial line")
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(raw.splitlines(), start=1):
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid JSON") from exc
        if not isinstance(row, dict):
            raise ValueError(f"{path}:{line_number}: row is not an object")
        rows.append(row)
    return rows


def _new_path(path: Path) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, value: Any) -> None:
    _new_path(path)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    _new_path(path)
    with path.open("x", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")


def _project_path(root: Path, spec: dict[str, Any], label: str) -> Path:
    if set(spec) != {"path", "sha256"}:
        raise ValueError(f"{label} must contain exactly path and sha256")
    path = (root / spec["path"]).resolve()
    if root.resolve() not in path.parents:
        raise ValueError(f"{label} escapes project root")
    if not path.is_file():
        raise FileNotFoundError(f"missing {label}: {path}")
    observed = sha256_file(path)
    if observed != spec["sha256"]:
        raise ValueError(f"{label} SHA-256 mismatch: {observed}")
    return path


def _record_position(text: str, record_id: str) -> int:
    match = re.search(rf"^## {re.escape(record_id)}(?:\s|—|-)", text, re.MULTILINE)
    if match is None:
        raise ValueError(f"decision log does not contain {record_id}")
    return match.start()


def validate_precontent_gates(contract: dict[str, Any], decision_log: str) -> None:
    gates = contract["source_gates"]
    expected = {
        "sibling_incident": "INC-0091",
        "sibling_decision": "DEC-0231",
        "prompt_incident": "INC-0092",
        "prompt_decision": "DEC-0232",
        "completion_decision": "DEC-0233",
    }
    if gates.get("record_ids") != expected:
        raise ValueError("source-gate record IDs do not match the approved dispositions")
    if gates.get("predecessor_incident") != "INC-0087":
        raise ValueError("completion binding is not explicitly post-INC-0087")
    if gates.get("sibling_disposition") != "preserved_excluded":
        raise ValueError("corrupted sibling is not preserved and excluded")
    if gates.get("prompt_disposition") != "retain_no_content_conditioned_change":
        raise ValueError("prompt exposure disposition is not approved")
    if gates.get("terminal_status") != "append_only_terminal_source_bound":
        raise ValueError("terminal source is not completion-bound")
    positions = {record: _record_position(decision_log, record) for record in ["INC-0087", *expected.values()]}
    if positions["INC-0091"] >= positions["DEC-0231"]:
        raise ValueError("sibling decision precedes its incident")
    if positions["INC-0092"] >= positions["DEC-0232"]:
        raise ValueError("prompt decision precedes its incident")
    if positions["DEC-0233"] <= max(positions["INC-0087"], positions["INC-0091"], positions["INC-0092"]):
        raise ValueError("terminal completion binding is not after all predecessor incidents")


def transport_schema_projection(schema: dict[str, Any]) -> dict[str, Any]:
    """Return a transport draft with `uniqueItems` removed only.

    The full local schema and semantic validator remain authoritative. Whether
    this exact projection is needed must be rechecked and frozen before egress.
    """

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


def _resolve_ref(root: dict[str, Any], reference: str) -> dict[str, Any]:
    if not reference.startswith("#/"):
        raise ValueError(f"unsupported schema reference {reference}")
    current: Any = root
    for part in reference[2:].split("/"):
        current = current[part.replace("~1", "/").replace("~0", "~")]
    if not isinstance(current, dict):
        raise ValueError(f"schema reference {reference} is not an object")
    return current


def _validate_schema_subset(value: Any, schema: dict[str, Any], root: dict[str, Any], path: str = "root") -> None:
    """Validate the exact JSON-Schema keywords used by the v2 local schema."""

    if "$ref" in schema:
        _validate_schema_subset(value, _resolve_ref(root, schema["$ref"]), root, path)
        return
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"schema validation failed at {path}: value is not in enum")
    expected_type = schema.get("type")
    if expected_type is not None:
        allowed = expected_type if isinstance(expected_type, list) else [expected_type]
        matches = False
        for kind in allowed:
            matches = matches or (
                (kind == "object" and isinstance(value, dict))
                or (kind == "array" and isinstance(value, list))
                or (kind == "string" and isinstance(value, str))
                or (kind == "integer" and isinstance(value, int) and not isinstance(value, bool))
                or (kind == "number" and isinstance(value, (int, float)) and not isinstance(value, bool))
                or (kind == "null" and value is None)
                or (kind == "boolean" and isinstance(value, bool))
            )
        if not matches:
            raise ValueError(f"schema validation failed at {path}: wrong type")
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        missing = set(schema.get("required", [])) - set(value)
        if missing:
            raise ValueError(f"schema validation failed at {path}: missing {sorted(missing)}")
        if schema.get("additionalProperties") is False:
            extra = set(value) - set(properties)
            if extra:
                raise ValueError(f"schema validation failed at {path}: additional properties {sorted(extra)}")
        for key, child in value.items():
            if key in properties:
                _validate_schema_subset(child, properties[key], root, f"{path}.{key}")
    if isinstance(value, list):
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            raise ValueError(f"schema validation failed at {path}: too many items")
        if schema.get("uniqueItems"):
            identities = [json.dumps(item, sort_keys=True, separators=(",", ":")) for item in value]
            if len(identities) != len(set(identities)):
                raise ValueError(f"schema validation failed at {path}: duplicate items")
        if "items" in schema:
            for index, child in enumerate(value):
                _validate_schema_subset(child, schema["items"], root, f"{path}[{index}]")
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            raise ValueError(f"schema validation failed at {path}: string too short")
        if "pattern" in schema and re.fullmatch(schema["pattern"], value) is None:
            raise ValueError(f"schema validation failed at {path}: pattern mismatch")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            raise ValueError(f"schema validation failed at {path}: below minimum")
        if "maximum" in schema and value > schema["maximum"]:
            raise ValueError(f"schema validation failed at {path}: above maximum")


def _validate_evidence_array(
    evidence: Any,
    *,
    description_id: str,
    description: str,
    label: str,
) -> None:
    if not isinstance(evidence, list):
        raise ValueError(f"{label} must be an array")
    seen: set[tuple[str, str]] = set()
    for index, obj in enumerate(evidence):
        if not isinstance(obj, dict) or set(obj) != {"description_id", "excerpt"}:
            raise ValueError(f"{label}[{index}] has invalid evidence shape")
        if obj["description_id"] != description_id:
            raise ValueError(f"{label}[{index}] names the wrong description")
        excerpt = obj["excerpt"]
        if not isinstance(excerpt, str) or not excerpt:
            raise ValueError(f"{label}[{index}] excerpt is empty")
        if excerpt not in description:
            raise ValueError(f"{label}[{index}] excerpt is not a case-sensitive literal substring")
        identity = (obj["description_id"], excerpt)
        if identity in seen:
            raise ValueError(f"{label} contains duplicate evidence objects")
        seen.add(identity)


def _validate_axis(
    axis: dict[str, Any],
    *,
    description_id: str,
    description: str,
    label: str,
) -> None:
    _validate_evidence_array(
        axis["evidence"],
        description_id=description_id,
        description=description,
        label=f"axes.{label}.evidence",
    )
    score = axis["score"]
    if isinstance(score, bool):
        raise ValueError(f"{label} boolean score is invalid")
    if isinstance(score, int) and score != 0 and not axis["evidence"]:
        raise ValueError(f"{label} nonzero score requires literal evidence")
    if (score == 0 or isinstance(score, str)) and axis["evidence"]:
        raise ValueError(f"{label} zero/non-numeric score requires empty evidence")
    if isinstance(score, str) and axis["confidence"] != "not_applicable":
        raise ValueError(f"{label} non-numeric score requires not_applicable confidence")
    if isinstance(score, int) and axis["confidence"] == "not_applicable":
        raise ValueError(f"{label} numeric score requires applicable confidence")


def validate_independent_output(
    output: dict[str, Any],
    *,
    expected_item_id: str,
    description_id: str,
    description: str,
    schema: dict[str, Any],
) -> None:
    _validate_schema_subset(output, schema, schema)
    if output["item_id"] != expected_item_id:
        raise ValueError("provider output item_id does not match request")
    if output["description_id"] != description_id:
        raise ValueError("provider output description_id does not match request")
    if not ITEM_ID_RE.fullmatch(output["item_id"]) or not DESCRIPTION_ID_RE.fullmatch(description_id):
        raise ValueError("opaque identifier format is invalid")

    for family_name, axis_names in PRIMARY_FAMILIES.items():
        family = output["families"][family_name]
        _validate_evidence_array(
            family["sufficiency_evidence"],
            description_id=description_id,
            description=description,
            label=f"families.{family_name}.sufficiency_evidence",
        )
        scores = [output["axes"][name]["score"] for name in axis_names]
        if family["status"] == "sufficient":
            if family["reason"] != "none" or not family["sufficiency_evidence"]:
                raise ValueError(f"{family_name} sufficient status requires reason none and literal evidence")
            if not all(isinstance(score, int) and not isinstance(score, bool) for score in scores):
                raise ValueError(f"{family_name} sufficient status requires numeric axes")
        else:
            if family["reason"] not in INSUFFICIENT_REASONS or family["sufficiency_evidence"]:
                raise ValueError(f"{family_name} insufficient status has invalid reason/evidence")
            if scores != ["unscorable", "unscorable"]:
                raise ValueError(f"{family_name} insufficient status requires unscorable axes")

    harm_family = output["families"]["harm_facilitation"]
    _validate_evidence_array(
        harm_family["sufficiency_evidence"],
        description_id=description_id,
        description=description,
        label="families.harm_facilitation.sufficiency_evidence",
    )
    harm_scores = [output["axes"][name]["score"] for name in HARM_AXES]
    applicability = output["harm_applicable"]
    if applicability == "no":
        if harm_family["status"] != "insufficient" or harm_family["reason"] != "not_applicable":
            raise ValueError("harm_applicable no requires an insufficient/not_applicable family")
        if harm_family["sufficiency_evidence"] or harm_scores != ["not_applicable", "not_applicable"]:
            raise ValueError("harm_applicable no requires empty family evidence and not_applicable axes")
    elif applicability == "unclear":
        if harm_family["status"] != "insufficient" or harm_family["reason"] not in INSUFFICIENT_REASONS:
            raise ValueError("harm_applicable unclear requires an insufficient family with a usable reason")
        if harm_family["sufficiency_evidence"] or harm_scores != ["unscorable", "unscorable"]:
            raise ValueError("harm_applicable unclear requires empty evidence and unscorable axes")
    elif harm_family["status"] == "sufficient":
        if harm_family["reason"] != "none" or not harm_family["sufficiency_evidence"]:
            raise ValueError("sufficient harm family requires reason none and literal evidence")
        if not all(isinstance(score, int) and not isinstance(score, bool) for score in harm_scores):
            raise ValueError("sufficient harm family requires numeric axes")
    else:
        if harm_family["reason"] not in INSUFFICIENT_REASONS or harm_family["sufficiency_evidence"]:
            raise ValueError("insufficient harm family has invalid reason/evidence")
        if harm_scores != ["unscorable", "unscorable"]:
            raise ValueError("insufficient harm family requires unscorable axes")

    for axis_name, axis in output["axes"].items():
        _validate_axis(
            axis,
            description_id=description_id,
            description=description,
            label=axis_name,
        )


def _dotted_get(value: dict[str, Any], dotted: str) -> Any:
    current: Any = value
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            raise ValueError(f"missing calibration output field {dotted}")
        current = current[part]
    return current


def validate_calibration_expectation(output: dict[str, Any], expectation: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    for dotted, allowed in expectation["required"].items():
        observed = _dotted_get(output, dotted)
        if observed not in allowed:
            failures.append(f"{dotted}: observed {observed!r}, allowed {allowed!r}")
    return failures


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
        raise ValueError("unresolved template marker")
    return rendered


def build_calibration_packet(
    *,
    inputs: list[dict[str, Any]],
    expectations: list[dict[str, Any]],
    seed: int,
    system_prompt: str,
    user_template: str,
    schema: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    expectation_map = {row["calibration_id"]: row for row in expectations}
    if len(expectation_map) != len(expectations):
        raise ValueError("duplicate calibration expectation ID")
    if {row["calibration_id"] for row in inputs} != set(expectation_map):
        raise ValueError("calibration input/expectation IDs differ")
    shuffled = list(inputs)
    random.Random(seed).shuffle(shuffled)
    packet: list[dict[str, Any]] = []
    key: list[dict[str, Any]] = []
    for order, row in enumerate(shuffled):
        if not ITEM_ID_RE.fullmatch(row["anonymous_item_id"]):
            raise ValueError("calibration item ID has invalid format")
        if not DESCRIPTION_ID_RE.fullmatch(row["description_id"]):
            raise ValueError("calibration description ID has invalid format")
        packet.append(
            {
                "request_order": order,
                "item_id": row["anonymous_item_id"],
                "description_id": row["description_id"],
                "system_prompt": system_prompt,
                "user_prompt": render_user_prompt(user_template, row),
                "response_schema": transport_schema_projection(schema),
                "local_validation_description": row["nla_description"],
            }
        )
        key.append(
            {
                "item_id": row["anonymous_item_id"],
                "description_id": row["description_id"],
                "calibration_id": row["calibration_id"],
                "expectation": expectation_map[row["calibration_id"]],
            }
        )
    return packet, key


def _opaque_item_id(seed: int, source_row_id: str) -> str:
    suffix = hashlib.sha256(f"{seed}:{source_row_id}".encode("utf-8")).hexdigest()[:12].upper()
    return f"J1V2-{suffix}"


def validate_target_sources(
    decoded: list[dict[str, Any]],
    panel: list[dict[str, Any]],
    prompts: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    token_panel = [row for row in panel if row.get("position") == TARGET_POSITION]
    token_decoded = [row for row in decoded if row.get("position") == TARGET_POSITION]
    if len(token_panel) != EXPECTED_ACTIVATIONS:
        raise ValueError(f"expected {EXPECTED_ACTIVATIONS} token-32 activations")
    if len(token_decoded) != EXPECTED_TARGET_ROWS:
        raise ValueError(f"expected {EXPECTED_TARGET_ROWS} token-32 descriptions")
    panel_ids = [row.get("activation_cell_id") for row in token_panel]
    if len(panel_ids) != len(set(panel_ids)):
        raise ValueError("duplicate token-32 activation_cell_id")
    panel_map = {row["activation_cell_id"]: row for row in token_panel}
    row_ids: set[str] = set()
    counts: Counter[str] = Counter()
    for row in token_decoded:
        row_id = row.get("row_id")
        if not isinstance(row_id, str) or row_id in row_ids:
            raise ValueError("duplicate or missing decoded row_id")
        row_ids.add(row_id)
        if row.get("nla_parse_ok") is not True or not isinstance(row.get("nla_explanation"), str) or not row["nla_explanation"]:
            raise ValueError("decoded row is not a successful nonempty explanation")
        activation_id = row.get("activation_cell_id")
        if activation_id not in panel_map:
            raise ValueError("decoded row does not join to token-32 panel")
        source = panel_map[activation_id]
        for key in ("model_id", "condition_id", "prompt_id", "hidden_state_index", "position", "activation_sha256"):
            if row.get(key) != source.get(key):
                raise ValueError(f"decoded/panel mismatch for {key}")
        counts[activation_id] += 1
    if set(counts) != set(panel_map) or set(counts.values()) != {3}:
        raise ValueError("each token-32 activation must have exactly three descriptions")
    prompt_map: dict[str, str] = {}
    for row in prompts:
        if set(row) != {"prompt_id", "prompt"}:
            raise ValueError("prompt artifact rows must contain exactly prompt_id and prompt")
        if row["prompt_id"] in prompt_map or not isinstance(row["prompt"], str) or not row["prompt"]:
            raise ValueError("prompt artifact contains duplicate or empty prompt")
        prompt_map[row["prompt_id"]] = row["prompt"]
    expected_prompt_ids = {row["prompt_id"] for row in token_panel}
    if set(prompt_map) != expected_prompt_ids or len(prompt_map) != 20:
        raise ValueError("prompt artifact does not exactly cover the 20-prompt panel")
    return token_decoded, prompt_map


def build_target_packet(
    *,
    decoded: list[dict[str, Any]],
    panel: list[dict[str, Any]],
    prompts: list[dict[str, Any]],
    seed: int,
    system_prompt: str,
    user_template: str,
    schema: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows, prompt_map = validate_target_sources(decoded, panel, prompts)
    shuffled = list(rows)
    random.Random(seed).shuffle(shuffled)
    packet: list[dict[str, Any]] = []
    reveal: list[dict[str, Any]] = []
    observed_item_ids: set[str] = set()
    for order, row in enumerate(shuffled, start=1):
        item_id = _opaque_item_id(seed, row["row_id"])
        if item_id in observed_item_ids:
            raise ValueError("opaque item ID collision")
        observed_item_ids.add(item_id)
        description_id = f"D{order:06d}"
        item = {
            "anonymous_item_id": item_id,
            "description_id": description_id,
            "prompt_text": prompt_map[row["prompt_id"]],
            "nla_description": row["nla_explanation"],
        }
        packet.append(
            {
                "request_order": order - 1,
                "item_id": item_id,
                "description_id": description_id,
                "system_prompt": system_prompt,
                "user_prompt": render_user_prompt(user_template, item),
                "response_schema": transport_schema_projection(schema),
                "local_validation_description": row["nla_explanation"],
            }
        )
        reveal.append(
            {
                "item_id": item_id,
                "description_id": description_id,
                "source_row_id": row["row_id"],
                "activation_cell_id": row["activation_cell_id"],
                "description_index": row["description_index"],
                "model_id": row["model_id"],
                "condition_id": row["condition_id"],
                "prompt_id": row["prompt_id"],
                "position": row["position"],
            }
        )
    if len(packet) != EXPECTED_TARGET_ROWS:
        raise AssertionError("target packet count changed unexpectedly")
    return packet, reveal


def load_contract(snapshot_path: Path) -> tuple[dict[str, Any], str]:
    snapshot = read_json(snapshot_path)
    values = snapshot.get("values", {}).get("nla", {}).get(CONTRACT_KEY)
    if not isinstance(values, dict):
        raise ValueError(f"snapshot lacks values.nla.{CONTRACT_KEY}")
    snapshot_sha = sha256_file(snapshot_path)
    if values.get("stage_snapshot_sha256") not in {None, snapshot_sha}:
        raise ValueError("embedded stage snapshot SHA-256 is inconsistent")
    if values.get("rubric_sha256") != RUBRIC_SHA256:
        raise ValueError("snapshot binds the wrong rubric v2")
    if values.get("judging_reference_sha256") != JUDGING_REFERENCE_SHA256:
        raise ValueError("snapshot binds the wrong judging reference")
    plan = values.get("target_plan", {})
    if plan != {
        "format": "independent_only",
        "position": TARGET_POSITION,
        "activation_rows": EXPECTED_ACTIVATIONS,
        "descriptions_per_activation": 3,
        "request_rows": EXPECTED_TARGET_ROWS,
        "repetitions": 1,
        "randomization_seed": plan.get("randomization_seed"),
    } or not isinstance(plan.get("randomization_seed"), int):
        raise ValueError("snapshot target plan is not exact independent-only token-32 scope")
    return values, snapshot_sha


def prepare_from_snapshot(snapshot_path: Path, output_root: Path, *, project_root: Path = PROJECT_ROOT) -> None:
    if output_root.exists():
        raise FileExistsError(f"refusing to overwrite {output_root}")
    contract, snapshot_sha = load_contract(snapshot_path)
    artifacts = contract["artifacts"]

    # Pre-content phase: verify only instruction, decision, and corrupted-sibling bytes.
    decision_log_path = _project_path(project_root, artifacts["decision_log"], "decision log")
    _project_path(project_root, artifacts["corrupted_sibling"], "corrupted sibling")
    validate_precontent_gates(contract, decision_log_path.read_text(encoding="utf-8"))

    # Protected-content phase begins only after all append-only gates pass.
    decoded_path = _project_path(project_root, artifacts["decoded"], "terminal decoded checkpoint")
    panel_path = _project_path(project_root, artifacts["panel"], "selected activation panel")
    prompts_path = _project_path(project_root, artifacts["prompts"], "prompt artifact")
    system_path = _project_path(project_root, artifacts["system_prompt"], "system prompt")
    template_path = _project_path(project_root, artifacts["user_template"], "user template")
    schema_path = _project_path(project_root, artifacts["schema"], "local schema")
    if artifacts["decoded"]["sha256"] != TERMINAL_DECODE_SHA256:
        raise ValueError("decoded artifact differs from terminal completion binding")
    if artifacts["panel"]["sha256"] != PANEL_SHA256:
        raise ValueError("panel artifact differs from terminal completion binding")
    if artifacts["corrupted_sibling"]["sha256"] != CORRUPTED_SIBLING_SHA256:
        raise ValueError("corrupted sibling identity differs from incident binding")

    packet, reveal = build_target_packet(
        decoded=read_jsonl(decoded_path),
        panel=read_jsonl(panel_path),
        prompts=read_jsonl(prompts_path),
        seed=contract["target_plan"]["randomization_seed"],
        system_prompt=system_path.read_text(encoding="utf-8"),
        user_template=template_path.read_text(encoding="utf-8"),
        schema=read_json(schema_path),
    )
    packet_path = output_root / "inputs" / "blinded_items.v2.jsonl"
    reveal_path = output_root / "reveal" / "reveal_key.v2.jsonl"
    manifest_path = output_root / "packet_manifest.v2.json"
    write_jsonl(packet_path, packet)
    write_jsonl(reveal_path, reveal)
    write_json(
        manifest_path,
        {
            "schema_version": "medical_claim1_nla_judge1_packet_v2",
            "status": "prepared_no_egress",
            "stage_snapshot_sha256": snapshot_sha,
            "target_position": TARGET_POSITION,
            "request_rows": len(packet),
            "packet_sha256": sha256_file(packet_path),
            "reveal_key_sha256": sha256_file(reveal_path),
            "source_decoded_sha256": sha256_file(decoded_path),
            "source_panel_sha256": sha256_file(panel_path),
            "prompt_artifact_sha256": sha256_file(prompts_path),
            "system_prompt_sha256": sha256_file(system_path),
            "schema_sha256": sha256_file(schema_path),
            "transport_schema_sha256": canonical_sha256(transport_schema_projection(read_json(schema_path))),
            "pairwise_rows": 0,
            "token_8_rows": 0,
            "pre_answer_rows": 0,
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    target = subparsers.add_parser("prepare-target")
    target.add_argument("--snapshot", type=Path, required=True)
    target.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare-target":
        prepare_from_snapshot(args.snapshot, args.output_root)


if __name__ == "__main__":
    main()
