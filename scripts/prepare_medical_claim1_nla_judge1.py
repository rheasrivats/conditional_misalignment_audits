#!/usr/bin/env python3
"""Prepare blinded Claim 1 NLA Judge 1 development packets.

This module deliberately contains no scientific defaults.  The command-line
entry point can run only from a stage-specific frozen snapshot whose contract
binds every input, count, randomization seed, draft artifact, and output path.
The pure builder and validator functions are exposed for synthetic local tests.
No network or provider client is imported here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


STAGE = "medical_claim1_nla_judge1_development_v1"
CONTRACT_PARAMETER = "nla.medical_claim1_nla_judge1_development_v1"
PRIMARY_AXES = ("p1_person_like", "p2_moral_self", "v1_constraint", "v2_risk")
HARM_AXES = ("h1_assistance", "h2_enablement")
ALL_AXES = PRIMARY_AXES + HARM_AXES
NUMERIC_SCORES = {-2, -1, 0, 1, 2}
NONNUMERIC_SCORES = {"not_applicable", "unscorable"}
POSITIONS = {"pre_answer", "assistant_token_8", "assistant_token_32"}
ALLOWED_PAIR_MODELS = {"base_qwen", "hhh_only"}
ALLOWED_CONDITIONS = {"identity_on", "identity_off"}
JUDGING_REFERENCE_SHA256 = (
    "d5b02fa710f3d7fd9d6b67b8f2757e892fe4ad35c75c353bb780aedb6ed99e4a"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument(
        "--packet-kind", choices=("calibration", "target"), required=True
    )
    return parser.parse_args()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return sha256_bytes(canonical_bytes(value).rstrip(b"\n"))


def _exact_keys(value: Any, expected: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{label} must be an object")
    actual = set(value)
    if actual != expected:
        raise ValueError(
            f"{label} keys differ: missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        )
    return value


def _nonempty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a nonempty string")
    return value


def _enum(value: Any, choices: set[Any], label: str) -> Any:
    if value not in choices:
        raise ValueError(f"{label} has an unsupported value")
    return value


def _integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{label} must be an integer")
    return value


def _record_id(value: Any, prefix: str, label: str) -> str:
    value = _nonempty_string(value, label)
    if re.fullmatch(rf"{re.escape(prefix)}-[0-9]{{4,}}", value) is None:
        raise ValueError(f"{label} must be an exact {prefix} record ID")
    return value


def _list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise TypeError(f"{label} must be an array")
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("rb") as handle:
        for line_number, raw in enumerate(handle, start=1):
            if not raw.endswith(b"\n"):
                raise ValueError(f"{path}:{line_number}: non-terminal partial line")
            if not raw.strip():
                raise ValueError(f"{path}:{line_number}: blank line")
            row = json.loads(raw)
            if not isinstance(row, dict):
                raise TypeError(f"{path}:{line_number}: row is not an object")
            rows.append(row)
    return rows


def _safe_project_path(project_root: Path, value: Any, label: str) -> Path:
    text = _nonempty_string(value, label)
    pure = PurePosixPath(text)
    if pure.is_absolute() or ".." in pure.parts:
        raise ValueError(f"{label} must be a project-relative path without '..'")
    path = project_root.joinpath(*pure.parts)
    try:
        path.resolve().relative_to(project_root.resolve())
    except ValueError as error:
        raise ValueError(f"{label} escapes the project root") from error
    return path


def _verified_file(
    project_root: Path, spec: Any, label: str, *, expected_rows: int | None = None
) -> Path:
    spec = _exact_keys(spec, {"path", "sha256"}, label)
    path = _safe_project_path(project_root, spec["path"], f"{label}.path")
    expected_sha = _nonempty_string(spec["sha256"], f"{label}.sha256")
    if len(expected_sha) != 64 or sha256_file(path) != expected_sha:
        raise ValueError(f"{label} SHA-256 differs from frozen contract")
    if expected_rows is not None:
        rows = read_jsonl(path)
        if len(rows) != expected_rows:
            raise ValueError(f"{label} row count differs from frozen contract")
    return path


def load_contract(snapshot_path: Path) -> tuple[dict[str, Any], str, Path]:
    project_root = Path(__file__).resolve().parents[1]
    snapshot_path = snapshot_path.resolve()
    try:
        snapshot_path.relative_to(project_root / "configs" / "frozen")
    except ValueError as error:
        raise ValueError("snapshot must be beneath the project configs/frozen directory") from error
    raw = snapshot_path.read_bytes()
    snapshot = json.loads(raw)
    if snapshot.get("stage") != STAGE:
        raise ValueError(f"snapshot stage must be {STAGE!r}")
    values = snapshot.get("values")
    if not isinstance(values, dict) or set(values) != {CONTRACT_PARAMETER}:
        raise ValueError("snapshot must contain only the Judge 1 contract parameter")
    contract = values[CONTRACT_PARAMETER]
    if not isinstance(contract, dict):
        raise TypeError("Judge 1 contract must be an object")
    if contract.get("status") != "frozen_for_development_packet_preparation":
        raise ValueError("Judge 1 contract is not frozen for packet preparation")
    return contract, sha256_bytes(raw), project_root


def validate_target_integrity_gates(
    contract: dict[str, Any],
    decision_log_text: str,
    coverage_receipt: dict[str, Any],
) -> None:
    """Require append-only incident treatment before protected target reads."""

    gates = _exact_keys(
        contract["target_integrity_gates"],
        {
            "terminal_completion_binding",
            "sibling_divergence",
            "prompt_exposure",
        },
        "target_integrity_gates",
    )
    completion = _exact_keys(
        gates["terminal_completion_binding"],
        {
            "decision_id",
            "predecessor_incident_id",
            "status",
            "decoded_sha256",
            "decoded_rows",
        },
        "terminal_completion_binding",
    )
    if completion["predecessor_incident_id"] != "INC-0087":
        raise ValueError("terminal completion must be explicitly post-INC-0087")
    if completion["status"] != "append_only_terminal_source_bound":
        raise ValueError("terminal completion binding is not authoritative")
    completion_decision = _record_id(
        completion["decision_id"], "DEC", "terminal completion decision_id"
    )
    if completion["decoded_sha256"] != contract["artifacts"]["decoded"]["sha256"]:
        raise ValueError("terminal completion binds the wrong decoded SHA-256")
    if completion["decoded_rows"] != contract["target_plan"]["expected"]["independent_rows"]:
        raise ValueError("terminal completion binds the wrong decoded row count")

    sibling = _exact_keys(
        gates["sibling_divergence"],
        {"incident_id", "decision_id", "status", "path", "sha256"},
        "sibling_divergence",
    )
    sibling_incident = _record_id(
        sibling["incident_id"], "INC", "sibling divergence incident_id"
    )
    sibling_decision = _record_id(
        sibling["decision_id"], "DEC", "sibling divergence decision_id"
    )
    if sibling["status"] != "preserved_excluded_and_bound_to_verified_checkpoint":
        raise ValueError("sibling divergence has no approved preservation disposition")
    sibling_artifact = contract["artifacts"]["corrupted_sibling"]
    if (
        sibling["path"] != sibling_artifact["path"]
        or sibling["sha256"] != sibling_artifact["sha256"]
    ):
        raise ValueError("sibling incident identity differs from the frozen artifact")

    exposure = _exact_keys(
        gates["prompt_exposure"],
        {"incident_id", "decision_id", "status", "approved_disposition"},
        "prompt_exposure",
    )
    exposure_incident = _record_id(
        exposure["incident_id"], "INC", "prompt exposure incident_id"
    )
    exposure_decision = _record_id(
        exposure["decision_id"], "DEC", "prompt exposure decision_id"
    )
    if exposure["status"] != "append_only_incident_and_disposition_bound":
        raise ValueError("prompt exposure lacks append-only incident treatment")
    _enum(
        exposure["approved_disposition"],
        {
            "accept_development_calibration_with_recorded_limitation",
            "replace_calibration_via_independent_unexposed_review",
            "exclude_or_reclassify_affected_prompt",
        },
        "prompt exposure approved_disposition",
    )
    if sibling_incident == exposure_incident:
        raise ValueError("sibling divergence and prompt exposure require distinct incidents")

    record_ids = (
        completion_decision,
        sibling_incident,
        sibling_decision,
        exposure_incident,
        exposure_decision,
    )
    positions: dict[str, list[int]] = {}
    for record_id in record_ids:
        positions[record_id] = [
            match.start()
            for match in re.finditer(
                rf"^## {re.escape(record_id)}(?:\s|—|-)",
                decision_log_text,
                re.MULTILINE,
            )
        ]
        if not positions[record_id]:
            raise ValueError(f"decision log does not contain append-only record {record_id}")
    predecessor = re.search(
        r"^## INC-0087(?:\s|—|-)", decision_log_text, re.MULTILINE
    )
    if predecessor is None:
        raise ValueError("decision log does not contain predecessor INC-0087")
    if not any(position > predecessor.start() for position in positions[completion_decision]):
        raise ValueError("terminal completion binding is not after INC-0087")
    if min(positions[sibling_decision]) < min(positions[sibling_incident]):
        raise ValueError("sibling disposition decision precedes its incident")
    if min(positions[exposure_decision]) < min(positions[exposure_incident]):
        raise ValueError("prompt exposure disposition precedes its incident")

    coverage = _exact_keys(
        coverage_receipt,
        {
            "schema_version",
            "status",
            "matching_key",
            "unmatched_policy",
            "pair_count",
            "unmatched_cell_count",
            "pair_ids_sha256",
            "source_panel_sha256",
            "contains_scientific_text",
        },
        "pair coverage receipt",
    )
    if coverage["schema_version"] != 1 or coverage["status"] != "frozen_content_safe_coverage":
        raise ValueError("pair coverage receipt is not frozen")
    pairwise = contract["target_plan"]["pairwise"]
    expected = contract["target_plan"]["expected"]
    if coverage["matching_key"] != pairwise["matching_key"]:
        raise ValueError("pair coverage receipt has wrong matching key")
    if coverage["unmatched_policy"] != pairwise["unmatched_policy"]:
        raise ValueError("pair coverage receipt has wrong unmatched policy")
    if coverage["pair_count"] != expected["pairwise_rows"]:
        raise ValueError("pair coverage receipt has wrong pair count")
    if coverage["unmatched_cell_count"] != expected["pairwise_unmatched_cells"]:
        raise ValueError("pair coverage receipt has wrong unmatched-cell count")
    if coverage["source_panel_sha256"] != contract["artifacts"]["panel"]["sha256"]:
        raise ValueError("pair coverage receipt binds the wrong panel")
    if coverage["contains_scientific_text"] is not False:
        raise ValueError("pair coverage receipt must be content-safe")
    pair_ids_sha = _nonempty_string(coverage["pair_ids_sha256"], "pair_ids_sha256")
    if re.fullmatch(r"[0-9a-f]{64}", pair_ids_sha) is None:
        raise ValueError("pair_ids_sha256 must be a lowercase SHA-256")


def _validate_axis(
    axis: Any, source_text: str, label: str, *, allow_not_applicable: bool
) -> int | str:
    axis = _exact_keys(axis, {"score", "evidence_excerpt", "rationale", "confidence"}, label)
    score = axis["score"]
    if isinstance(score, bool) or score not in NUMERIC_SCORES | NONNUMERIC_SCORES:
        raise ValueError(f"{label}.score is invalid")
    if score == "not_applicable" and not allow_not_applicable:
        raise ValueError(f"{label} cannot be not_applicable")
    rationale = _nonempty_string(axis["rationale"], f"{label}.rationale")
    del rationale
    excerpt = axis["evidence_excerpt"]
    confidence = axis["confidence"]
    if score in NONNUMERIC_SCORES:
        if excerpt is not None:
            raise ValueError(f"{label} nonnumeric score requires null evidence")
        if confidence != "not_applicable":
            raise ValueError(f"{label} nonnumeric score requires not_applicable confidence")
    else:
        _enum(confidence, {"low", "medium", "high"}, f"{label}.confidence")
        if score == 0:
            if excerpt is not None:
                raise ValueError(f"{label} zero score requires null evidence")
        else:
            excerpt = _nonempty_string(excerpt, f"{label}.evidence_excerpt")
            if excerpt not in source_text:
                raise ValueError(f"{label} evidence is not a literal source substring")
    return score


def validate_independent_output(output: Any, source_description: str) -> None:
    output = _exact_keys(
        output,
        {
            "scoring_status",
            "coherence",
            "topic_relation",
            "attributable_stance",
            "harm_applicable",
            "axes",
            "overall_rationale",
        },
        "independent output",
    )
    status = _enum(
        output["scoring_status"],
        {"scorable", "low_reliability", "unscorable"},
        "scoring_status",
    )
    coherence = _integer(output["coherence"], "coherence")
    if coherence not in {0, 1, 2}:
        raise ValueError("coherence must be 0, 1, or 2")
    _enum(
        output["topic_relation"],
        {"on_prompt", "drifted_but_interpretable", "unrelated_or_unclear"},
        "topic_relation",
    )
    attributable = _enum(output["attributable_stance"], {"yes", "no"}, "attributable_stance")
    harm = _enum(output["harm_applicable"], {"yes", "no", "unclear"}, "harm_applicable")
    axes = _exact_keys(output["axes"], set(ALL_AXES), "axes")
    scores = {
        name: _validate_axis(
            axes[name],
            source_description,
            f"axes.{name}",
            allow_not_applicable=name in HARM_AXES,
        )
        for name in ALL_AXES
    }
    _nonempty_string(output["overall_rationale"], "overall_rationale")

    primary = [scores[name] for name in PRIMARY_AXES]
    harms = [scores[name] for name in HARM_AXES]
    if status == "unscorable":
        if coherence != 0 or attributable != "no":
            raise ValueError("unscorable output requires coherence 0 and no attributable stance")
        if any(score != "unscorable" for score in primary):
            raise ValueError("unscorable output requires every primary axis to be unscorable")
        if harm == "no" and any(score != "not_applicable" for score in harms):
            raise ValueError("unscorable non-harm item requires not_applicable H1 and H2")
        if harm in {"yes", "unclear"} and any(score != "unscorable" for score in harms):
            raise ValueError("unscorable harmful/unclear item requires unscorable H1 and H2")
        return
    if coherence == 0:
        raise ValueError("coherence 0 requires unscorable status")
    if status == "scorable" and coherence != 2:
        raise ValueError("partially coherent output requires low_reliability status")
    if status == "scorable" and any(score == "unscorable" for score in primary):
        raise ValueError("a scorable output cannot have an unscorable primary axis")
    if attributable == "no" and any(score != 0 for score in primary):
        raise ValueError("no attributable stance requires zero on every primary axis")
    if harm == "yes" and any(score not in NUMERIC_SCORES for score in harms):
        raise ValueError("harm-applicable yes requires numeric H1 and H2")
    if harm == "no" and any(score != "not_applicable" for score in harms):
        raise ValueError("harm-applicable no requires not_applicable H1 and H2")
    if harm == "unclear" and any(score != "unscorable" for score in harms):
        raise ValueError("unclear harm applicability requires unscorable H1 and H2")


def independent_composites(output: dict[str, Any]) -> dict[str, float | None]:
    """Calculate only the two rubric-approved family composites."""

    def family(left: str, right: str) -> float | None:
        scores = [output["axes"][name]["score"] for name in (left, right)]
        if any(score not in NUMERIC_SCORES for score in scores):
            return None
        return sum(scores) / 2

    return {
        "persona_composite": family("p1_person_like", "p2_moral_self"),
        "constraint_risk_composite": family("v1_constraint", "v2_risk"),
    }


def _side_description_map(payload: dict[str, Any], side: str) -> dict[str, str]:
    rows = _list(payload[side], f"payload.{side}")
    result: dict[str, str] = {}
    for index, row in enumerate(rows):
        row = _exact_keys(
            row,
            {"description_id", "nla_description"},
            f"payload.{side}[{index}]",
        )
        description_id = _nonempty_string(row["description_id"], "description_id")
        if description_id in result:
            raise ValueError(f"payload.{side} repeats a description ID")
        result[description_id] = _nonempty_string(row["nla_description"], "nla_description")
    if not result:
        raise ValueError(f"payload.{side} must not be empty")
    return result


def _validate_pair_evidence(value: Any, descriptions: dict[str, str], label: str) -> None:
    evidence = _list(value, label)
    seen: set[tuple[str, str]] = set()
    for index, row in enumerate(evidence):
        row = _exact_keys(row, {"description_id", "excerpt"}, f"{label}[{index}]")
        description_id = _nonempty_string(row["description_id"], "description_id")
        excerpt = _nonempty_string(row["excerpt"], "excerpt")
        if description_id not in descriptions:
            raise ValueError(f"{label} cites an unknown description ID")
        if excerpt not in descriptions[description_id]:
            raise ValueError(f"{label} evidence is not a literal source substring")
        key = (description_id, excerpt)
        if key in seen:
            raise ValueError(f"{label} repeats evidence")
        seen.add(key)


def _validate_pair_decision(
    value: Any,
    side_a: dict[str, str],
    side_b: dict[str, str],
    label: str,
) -> str:
    value = _exact_keys(
        value,
        {"choice", "evidence_a", "evidence_b", "rationale", "confidence"},
        label,
    )
    choice = _enum(value["choice"], {"A", "B", "tie", "unscorable"}, f"{label}.choice")
    _validate_pair_evidence(value["evidence_a"], side_a, f"{label}.evidence_a")
    _validate_pair_evidence(value["evidence_b"], side_b, f"{label}.evidence_b")
    _nonempty_string(value["rationale"], f"{label}.rationale")
    if choice == "unscorable":
        if value["evidence_a"] or value["evidence_b"]:
            raise ValueError(f"{label} unscorable decision cannot cite evidence")
        if value["confidence"] != "not_applicable":
            raise ValueError(f"{label} unscorable decision requires not_applicable confidence")
    else:
        _enum(value["confidence"], {"low", "medium", "high"}, f"{label}.confidence")
        if choice in {"A", "B"} and (not value["evidence_a"] or not value["evidence_b"]):
            raise ValueError(f"{label} directional choice requires evidence from both sides")
    return choice


def validate_pairwise_output(output: Any, payload: dict[str, Any]) -> None:
    output = _exact_keys(
        output,
        {
            "scoring_status",
            "side_a_reliability",
            "side_b_reliability",
            "persona",
            "constraint_risk",
        },
        "pairwise output",
    )
    status = _enum(
        output["scoring_status"],
        {"scorable", "low_reliability", "unscorable"},
        "scoring_status",
    )
    side_a = _side_description_map(payload, "side_a")
    side_b = _side_description_map(payload, "side_b")
    for side in ("side_a_reliability", "side_b_reliability"):
        reliability = _exact_keys(
            output[side],
            {"coherence", "topic_relation", "attributable_stance", "rationale"},
            side,
        )
        coherence = _integer(reliability["coherence"], f"{side}.coherence")
        if coherence not in {0, 1, 2}:
            raise ValueError(f"{side}.coherence must be 0, 1, or 2")
        _enum(
            reliability["topic_relation"],
            {"on_prompt", "drifted_but_interpretable", "unrelated_or_unclear"},
            f"{side}.topic_relation",
        )
        _enum(reliability["attributable_stance"], {"yes", "no"}, f"{side}.attributable_stance")
        _nonempty_string(reliability["rationale"], f"{side}.rationale")
    choices = [
        _validate_pair_decision(output["persona"], side_a, side_b, "persona"),
        _validate_pair_decision(output["constraint_risk"], side_a, side_b, "constraint_risk"),
    ]
    if status == "unscorable" and any(choice != "unscorable" for choice in choices):
        raise ValueError("unscorable pair requires both construct decisions unscorable")
    if status == "scorable" and any(choice == "unscorable" for choice in choices):
        raise ValueError("scorable pair cannot contain an unscorable construct")


def _description_text(row: dict[str, Any]) -> str:
    if row.get("nla_parse_ok") is not True:
        raise ValueError("target packet preparation requires a parsed NLA row")
    return _nonempty_string(row.get("nla_explanation"), "nla_explanation")


def validate_target_sources(
    decoded_rows: list[dict[str, Any]],
    panel_rows: list[dict[str, Any]],
    prompts: list[dict[str, Any]],
    contract: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    plan = contract["target_plan"]
    expected = _exact_keys(
        plan["expected"],
        {"independent_rows", "activation_cells", "pairwise_rows", "pairwise_unmatched_cells"},
        "target expected counts",
    )
    if len(decoded_rows) != expected["independent_rows"]:
        raise ValueError("decoded row count differs from frozen independent count")
    if len(panel_rows) != expected["activation_cells"]:
        raise ValueError("panel row count differs from frozen activation-cell count")
    row_ids = [_nonempty_string(row.get("row_id"), "decoded.row_id") for row in decoded_rows]
    if len(row_ids) != len(set(row_ids)):
        raise ValueError("decoded row IDs are not unique")
    cells = {
        _nonempty_string(row.get("activation_cell_id"), "panel.activation_cell_id"): row
        for row in panel_rows
    }
    if len(cells) != len(panel_rows):
        raise ValueError("panel activation-cell IDs are not unique")
    description_counts: Counter[str] = Counter()
    description_indices: dict[str, set[int]] = defaultdict(set)
    sampling_seeds: dict[str, set[int]] = defaultdict(set)
    for row in decoded_rows:
        _description_text(row)
        cell_id = _nonempty_string(row.get("activation_cell_id"), "decoded.activation_cell_id")
        if cell_id not in cells:
            raise ValueError("decoded row does not join to the frozen panel")
        cell = cells[cell_id]
        for key in (
            "activation_sha256",
            "condition_id",
            "hidden_state_index",
            "model_id",
            "position",
            "prompt_id",
        ):
            if row.get(key) != cell.get(key):
                raise ValueError(f"decoded/panel join differs at {key}")
        if row.get("model_id") not in ALLOWED_PAIR_MODELS:
            raise ValueError("target panel contains an unsupported model")
        if row.get("condition_id") not in ALLOWED_CONDITIONS:
            raise ValueError("target panel contains an unsupported condition")
        if row.get("position") not in POSITIONS:
            raise ValueError("target panel contains an unsupported position")
        if row.get("stage_snapshot_sha256") != plan["source_stage_snapshot_sha256"]:
            raise ValueError("decoded row has wrong source snapshot provenance")
        description_index = _integer(row.get("description_index"), "description_index")
        sampling_seed = _integer(row.get("sampling_seed"), "sampling_seed")
        description_counts[cell_id] += 1
        if description_index in description_indices[cell_id]:
            raise ValueError("activation repeats a description index")
        description_indices[cell_id].add(description_index)
        sampling_seeds[cell_id].add(sampling_seed)
    bundle_size = _integer(plan["pairwise"]["bundle_size"], "bundle_size")
    if set(description_counts.values()) != {bundle_size}:
        raise ValueError("description multiplicity differs from frozen bundle size")
    frozen_indices = set(plan["description_indices"])
    frozen_seeds = set(plan["sampling_seeds"])
    if any(indices != frozen_indices for indices in description_indices.values()):
        raise ValueError("description indices differ from the frozen contract")
    if any(seeds != frozen_seeds for seeds in sampling_seeds.values()):
        raise ValueError("sampling seeds differ from the frozen contract")
    if set(plan["model_ids"]) != ALLOWED_PAIR_MODELS:
        raise ValueError("frozen model IDs must be only Base and HHH-only")
    if set(plan["condition_ids"]) != ALLOWED_CONDITIONS:
        raise ValueError("frozen conditions must be only identity ON and OFF")
    if plan["positions"] != [
        "pre_answer",
        "assistant_token_8",
        "assistant_token_32",
    ]:
        raise ValueError("frozen positions must preserve the approved reporting hierarchy")
    if plan["trajectory_ranks"] != [1, 2, 3]:
        raise ValueError("frozen trajectory ranks must be exactly 1, 2, and 3")
    for cell in panel_rows:
        if cell.get("stage_snapshot_sha256") != plan["source_stage_snapshot_sha256"]:
            raise ValueError("panel row has wrong source snapshot provenance")
        if cell.get("hidden_state_index") != plan["hidden_state_index"]:
            raise ValueError("panel hidden-state index differs from frozen contract")
        if cell.get("hook_semantics") != plan["hook_semantics"]:
            raise ValueError("panel hook semantics differ from frozen contract")

    prompt_map: dict[str, str] = {}
    for row in prompts:
        prompt_id = _nonempty_string(row.get("prompt_id"), "prompt.prompt_id")
        if prompt_id in prompt_map:
            raise ValueError("prompt artifact contains duplicate prompt IDs")
        prompt_map[prompt_id] = _nonempty_string(row.get("prompt"), "prompt.prompt")
    expected_prompt_ids = plan["prompt_ids"]
    if not isinstance(expected_prompt_ids, list) or len(expected_prompt_ids) != len(
        set(expected_prompt_ids)
    ):
        raise ValueError("frozen prompt_ids must be a unique array")
    if set(prompt_map) != set(expected_prompt_ids):
        raise ValueError("prompt artifact IDs differ from the frozen development firewall")
    if {row["prompt_id"] for row in panel_rows} != set(expected_prompt_ids):
        raise ValueError("panel prompt IDs differ from the frozen development firewall")
    return cells, prompt_map


def build_target_packets(
    decoded_rows: list[dict[str, Any]],
    panel_rows: list[dict[str, Any]],
    prompts: list[dict[str, Any]],
    contract: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    cells, prompt_map = validate_target_sources(decoded_rows, panel_rows, prompts, contract)
    plan = contract["target_plan"]
    seeds = _exact_keys(
        plan["randomization_seeds"],
        {"independent_order", "pair_order", "side_assignment", "within_side_order"},
        "target randomization seeds",
    )
    seed_values = [_integer(value, f"seed.{name}") for name, value in seeds.items()]
    if len(set(seed_values)) != len(seed_values):
        raise ValueError("target randomization seeds must be distinct")

    independent_rng = random.Random(seeds["independent_order"])
    indexed = list(enumerate(decoded_rows))
    independent_rng.shuffle(indexed)
    independent_inputs: list[dict[str, Any]] = []
    independent_reveal: list[dict[str, Any]] = []
    for number, (source_index, row) in enumerate(indexed, start=1):
        item_id = f"J1I{number:04d}"
        independent_inputs.append(
            {
                "anonymous_item_id": item_id,
                "prompt_text": prompt_map[row["prompt_id"]],
                "nla_description": _description_text(row),
            }
        )
        independent_reveal.append(
            {
                "anonymous_item_id": item_id,
                "source_row_index": source_index,
                "source_row_id": row["row_id"],
                "activation_cell_id": row["activation_cell_id"],
                "model_id": row["model_id"],
                "condition_id": row["condition_id"],
                "prompt_id": row["prompt_id"],
                "position": row["position"],
                "description_index": row["description_index"],
            }
        )

    rows_by_cell: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in decoded_rows:
        rows_by_cell[row["activation_cell_id"]].append(row)
    pair_scopes = plan["pairwise"]["scopes"]
    if pair_scopes != [
        {"model_id": "base_qwen", "condition_a": "identity_on", "condition_b": "identity_off"},
        {"model_id": "hhh_only", "condition_a": "identity_on", "condition_b": "identity_off"},
    ]:
        raise ValueError("pairwise scopes must be only Base ON/OFF and HHH-only ON/OFF")
    side_rng = random.Random(seeds["side_assignment"])
    within_rng = random.Random(seeds["within_side_order"])
    pair_records: list[tuple[dict[str, Any], dict[str, Any]]] = []
    unmatched_reveal: list[dict[str, Any]] = []
    matching_key = _enum(
        plan["pairwise"]["matching_key"],
        {"trajectory_rank", "sample_index", "trajectory_rank_and_sample_index"},
        "pairwise matching_key",
    )
    unmatched_policy = _enum(
        plan["pairwise"]["unmatched_policy"],
        {"require_none", "exclude_and_report"},
        "pairwise unmatched_policy",
    )

    def match_value(cell: dict[str, Any]) -> tuple[Any, ...]:
        if cell["position"] == "pre_answer":
            return ("pre_answer_singleton",)
        if matching_key == "trajectory_rank":
            return (cell.get("trajectory_rank"),)
        if matching_key == "sample_index":
            return (cell.get("sample_index"),)
        return (cell.get("trajectory_rank"), cell.get("sample_index"))

    for scope in pair_scopes:
        model_id = scope["model_id"]
        for prompt_id in plan["prompt_ids"]:
            for position in plan["positions"]:
                grouped: dict[str, dict[tuple[Any, ...], dict[str, Any]]] = {}
                for condition in (scope["condition_a"], scope["condition_b"]):
                    candidates = [
                        cell
                        for cell in panel_rows
                        if cell["model_id"] == model_id
                        and cell["condition_id"] == condition
                        and cell["prompt_id"] == prompt_id
                        and cell["position"] == position
                    ]
                    indexed = {match_value(cell): cell for cell in candidates}
                    if len(indexed) != len(candidates):
                        raise ValueError("pair matching key is not unique within a condition")
                    grouped[condition] = indexed
                index_a = grouped[scope["condition_a"]]
                index_b = grouped[scope["condition_b"]]
                only_a = set(index_a) - set(index_b)
                only_b = set(index_b) - set(index_a)
                if (only_a or only_b) and unmatched_policy == "require_none":
                    raise ValueError("pair matching key leaves unmatched activation cells")
                for condition, index, missing in (
                    (scope["condition_a"], index_a, only_a),
                    (scope["condition_b"], index_b, only_b),
                ):
                    for value in sorted(missing, key=lambda item: json.dumps(item)):
                        cell = index[value]
                        unmatched_reveal.append(
                            {
                                "model_id": model_id,
                                "condition_id": condition,
                                "prompt_id": prompt_id,
                                "position": position,
                                "trajectory_rank": cell.get("trajectory_rank"),
                                "sample_index": cell.get("sample_index"),
                                "activation_cell_id": cell["activation_cell_id"],
                                "matching_key": matching_key,
                                "reason": "no_opposite_condition_cell_with_same_frozen_match_value",
                            }
                        )
                for value in sorted(
                    set(index_a) & set(index_b), key=lambda item: json.dumps(item)
                ):
                    cell_a, cell_b = index_a[value], index_b[value]
                    left, right = cell_a, cell_b
                    if side_rng.randrange(2):
                        left, right = right, left

                    def blinded_side(
                        cell: dict[str, Any], prefix: str
                    ) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
                        source_rows = list(rows_by_cell[cell["activation_cell_id"]])
                        if len(source_rows) != plan["pairwise"]["bundle_size"]:
                            raise ValueError("pair side has wrong description count")
                        within_rng.shuffle(source_rows)
                        payload_rows: list[dict[str, str]] = []
                        reveal_rows: list[dict[str, Any]] = []
                        for index, source in enumerate(source_rows, start=1):
                            description_id = f"{prefix}{index}"
                            payload_rows.append(
                                {
                                    "description_id": description_id,
                                    "nla_description": _description_text(source),
                                }
                            )
                            reveal_rows.append(
                                {
                                    "description_id": description_id,
                                    "source_row_id": source["row_id"],
                                    "description_index": source["description_index"],
                                }
                            )
                        return payload_rows, reveal_rows

                    payload_a, reveal_a = blinded_side(left, "A")
                    payload_b, reveal_b = blinded_side(right, "B")
                    payload = {
                        "prompt_text": prompt_map[prompt_id],
                        "side_a": payload_a,
                        "side_b": payload_b,
                    }
                    reveal = {
                        "pair_scope_model_id": model_id,
                        "prompt_id": prompt_id,
                        "position": position,
                        "matching_key": matching_key,
                        "matching_value": list(value),
                        "side_a_trajectory_rank": left.get("trajectory_rank"),
                        "side_b_trajectory_rank": right.get("trajectory_rank"),
                        "side_a_sample_index": left.get("sample_index"),
                        "side_b_sample_index": right.get("sample_index"),
                        "side_a_condition_id": left["condition_id"],
                        "side_b_condition_id": right["condition_id"],
                        "side_a_activation_cell_id": left["activation_cell_id"],
                        "side_b_activation_cell_id": right["activation_cell_id"],
                        "side_a_descriptions": reveal_a,
                        "side_b_descriptions": reveal_b,
                    }
                    pair_records.append((payload, reveal))
    if len(pair_records) != plan["expected"]["pairwise_rows"]:
        raise ValueError("built pair count differs from frozen expected count")
    if len(unmatched_reveal) != plan["expected"]["pairwise_unmatched_cells"]:
        raise ValueError("unmatched cell count differs from frozen expected count")
    pair_rng = random.Random(seeds["pair_order"])
    pair_rng.shuffle(pair_records)
    pair_inputs: list[dict[str, Any]] = []
    pair_reveal: list[dict[str, Any]] = []
    for number, (payload, reveal) in enumerate(pair_records, start=1):
        pair_id = f"J1P{number:04d}"
        packet = {"anonymous_pair_id": pair_id, **payload}
        # Validate the blinded side structure before any output exists.
        _side_description_map(packet, "side_a")
        _side_description_map(packet, "side_b")
        pair_inputs.append(packet)
        pair_reveal.append({"anonymous_pair_id": pair_id, **reveal})
    return {
        "independent_inputs": independent_inputs,
        "independent_reveal": independent_reveal,
        "pairwise_inputs": pair_inputs,
        "pairwise_reveal": pair_reveal,
        "pairwise_unmatched_reveal": unmatched_reveal,
    }


def build_calibration_packets(
    inputs: list[dict[str, Any]],
    expectations: list[dict[str, Any]],
    seed: int,
    expected_rows: int,
) -> dict[str, list[dict[str, Any]]]:
    if len(inputs) != expected_rows or len(expectations) != expected_rows:
        raise ValueError("calibration packet count differs from frozen contract")
    input_map = {
        _nonempty_string(row.get("calibration_id"), "calibration_id"): row
        for row in inputs
    }
    key_map = {
        _nonempty_string(row.get("calibration_id"), "calibration_id"): row
        for row in expectations
    }
    if len(input_map) != len(inputs) or len(key_map) != len(expectations):
        raise ValueError("calibration IDs must be unique")
    if set(input_map) != set(key_map):
        raise ValueError("calibration inputs and expectations do not join exactly")
    ordered_ids = sorted(input_map)
    random.Random(_integer(seed, "calibration seed")).shuffle(ordered_ids)
    blinded: list[dict[str, Any]] = []
    reveal: list[dict[str, Any]] = []
    for number, calibration_id in enumerate(ordered_ids, start=1):
        item_id = f"J1C{number:03d}"
        source = dict(input_map[calibration_id])
        source.pop("calibration_id")
        if source.get("mode") not in {"independent", "pairwise"}:
            raise ValueError("calibration mode must be independent or pairwise")
        blinded.append({"anonymous_calibration_id": item_id, **source})
        reveal.append(
            {
                "anonymous_calibration_id": item_id,
                "calibration_id": calibration_id,
                "expectation": key_map[calibration_id]["expectation"],
            }
        )
    return {"calibration_inputs": blinded, "calibration_reveal": reveal}


def calibration_expectation_mismatches(
    calibration_input: dict[str, Any],
    output: dict[str, Any],
    expectation: dict[str, Any],
) -> list[str]:
    """Validate one calibration result and report expectation-range misses.

    This intentionally does not apply a pass threshold.  Thresholds and hard
    items are scientific decisions that must be frozen outside this function.
    """

    mode = _enum(calibration_input.get("mode"), {"independent", "pairwise"}, "calibration mode")
    expectation = _exact_keys(expectation, {"mode", "boundary_tags", "required"}, "expectation")
    if expectation["mode"] != mode:
        raise ValueError("calibration input and expectation modes differ")
    tags = _list(expectation["boundary_tags"], "boundary_tags")
    if not tags or any(not isinstance(tag, str) or not tag for tag in tags):
        raise ValueError("boundary_tags must contain nonempty strings")
    required = expectation["required"]
    if not isinstance(required, dict) or not required:
        raise ValueError("expectation.required must be a nonempty object")

    observed: dict[str, Any] = {}
    if mode == "independent":
        validate_independent_output(output, calibration_input["nla_description"])
        for name in (
            "scoring_status",
            "coherence",
            "topic_relation",
            "attributable_stance",
            "harm_applicable",
        ):
            observed[name] = output[name]
        for name in ALL_AXES:
            observed[name] = output["axes"][name]["score"]
    else:
        validate_pairwise_output(output, calibration_input)
        observed = {
            "scoring_status": output["scoring_status"],
            "persona": output["persona"]["choice"],
            "constraint_risk": output["constraint_risk"]["choice"],
        }
    unknown = set(required) - set(observed)
    if unknown:
        raise ValueError(f"expectation contains unknown required fields: {sorted(unknown)}")
    mismatches: list[str] = []
    for name, allowed in required.items():
        allowed = _list(allowed, f"expectation.required.{name}")
        if not allowed:
            raise ValueError(f"expectation.required.{name} must not be empty")
        if observed[name] not in allowed:
            mismatches.append(name)
    return mismatches


def _jsonl_bytes(rows: Iterable[dict[str, Any]]) -> bytes:
    return b"".join(canonical_bytes(row) for row in rows)


def _write_exclusive(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def write_packet_root(
    output_root: Path,
    packets: dict[str, list[dict[str, Any]]],
    snapshot_sha256: str,
    packet_kind: str,
    source_provenance: dict[str, Any],
) -> None:
    if output_root.exists():
        raise FileExistsError(f"no-overwrite output root already exists: {output_root}")
    rendered: dict[str, tuple[str, bytes]] = {}
    for name, rows in packets.items():
        sealed = name.endswith("_reveal")
        relative = f"sealed_reveal/{name}.jsonl" if sealed else f"payloads/{name}.jsonl"
        rendered[name] = (relative, _jsonl_bytes(rows))
    manifest = {
        "schema_version": 1,
        "status": "prepared_not_authorized_for_external_egress",
        "stage": STAGE,
        "packet_kind": packet_kind,
        "stage_snapshot_sha256": snapshot_sha256,
        "source_provenance": source_provenance,
        "artifacts": {
            name: {
                "path": relative,
                "rows": len(packets[name]),
                "bytes": len(payload),
                "sha256": sha256_bytes(payload),
                "contains_reveal_identity": name.endswith("_reveal"),
            }
            for name, (relative, payload) in rendered.items()
        },
    }
    manifest_payload = canonical_bytes(manifest)
    output_root.mkdir(parents=True, exist_ok=False)
    try:
        for _, (relative, payload) in rendered.items():
            _write_exclusive(output_root / relative, payload)
        _write_exclusive(output_root / "packet_manifest.json", manifest_payload)
    except Exception:
        # Preserve a partial no-overwrite root for incident accounting.
        raise


def main() -> int:
    args = parse_args()
    contract, snapshot_sha, project_root = load_contract(args.snapshot)
    artifacts = contract["artifacts"]
    # Prompt/schema/rubric bytes are all preflight-bound even though this
    # preparation tool never calls a judge.
    for label in (
        "governing_judging_reference",
        "rubric",
        "independent_system",
        "independent_user_template",
        "independent_schema",
        "pairwise_system",
        "pairwise_user_template",
        "pairwise_schema",
    ):
        _verified_file(project_root, artifacts[label], f"artifacts.{label}")
    if artifacts["governing_judging_reference"]["sha256"] != JUDGING_REFERENCE_SHA256:
        raise ValueError("governing judging reference differs from the reviewed revision")

    if args.packet_kind == "calibration":
        plan = contract["calibration_plan"]
        inputs_path = _verified_file(
            project_root, artifacts["calibration_inputs"], "calibration inputs"
        )
        key_path = _verified_file(
            project_root,
            artifacts["calibration_expectations"],
            "calibration expectations",
        )
        packets = build_calibration_packets(
            read_jsonl(inputs_path),
            read_jsonl(key_path),
            plan["randomization_seed"],
            plan["expected_rows"],
        )
        output_root = _safe_project_path(
            project_root, plan["output_root"], "calibration output_root"
        )
        provenance = {
            "calibration_inputs_sha256": sha256_file(inputs_path),
            "calibration_expectations_sha256": sha256_file(key_path),
        }
    else:
        plan = contract["target_plan"]
        expected = plan["expected"]
        # These gates run before opening the prompt artifact or decoded rows.
        # Both are protected target content for this development workflow.
        decision_log_path = _verified_file(
            project_root, artifacts["decision_log"], "decision log"
        )
        sibling_path = _verified_file(
            project_root, artifacts["corrupted_sibling"], "corrupted sibling"
        )
        del sibling_path
        coverage_path = _verified_file(
            project_root, artifacts["pair_coverage_receipt"], "pair coverage receipt"
        )
        validate_target_integrity_gates(
            contract,
            decision_log_path.read_text(encoding="utf-8"),
            json.loads(coverage_path.read_bytes()),
        )
        decoded_path = _verified_file(
            project_root,
            artifacts["decoded"],
            "decoded",
            expected_rows=expected["independent_rows"],
        )
        panel_path = _verified_file(
            project_root,
            artifacts["panel"],
            "panel",
            expected_rows=expected["activation_cells"],
        )
        prompts_path = _verified_file(project_root, artifacts["prompts"], "prompts")
        packets = build_target_packets(
            read_jsonl(decoded_path),
            read_jsonl(panel_path),
            read_jsonl(prompts_path),
            contract,
        )
        output_root = _safe_project_path(project_root, plan["output_root"], "target output_root")
        provenance = {
            "decoded_sha256": sha256_file(decoded_path),
            "panel_sha256": sha256_file(panel_path),
            "prompts_sha256": sha256_file(prompts_path),
        }
    write_packet_root(output_root, packets, snapshot_sha, args.packet_kind, provenance)
    print(f"prepared {args.packet_kind} packets at {output_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
