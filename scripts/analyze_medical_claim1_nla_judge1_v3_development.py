#!/usr/bin/env python3
"""Descriptively evaluate one synthetic Judge 1 v3 development pilot.

The report intentionally contains no pass/fail or target-qualification verdict.
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import Any

import prepare_medical_claim1_nla_judge1_v3 as preparation


AXES = ("P1", "P2", "V1", "V2", "H")


def _observed_by_calibration(
    accepted: list[dict[str, Any]], key_rows: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    item_to_calibration = {row["item_id"]: row["calibration_id"] for row in key_rows}
    if len(item_to_calibration) != len(key_rows):
        raise ValueError("duplicate item in development key")
    observed: dict[str, dict[str, Any]] = {}
    for row in accepted:
        if row.get("repetition") != 1:
            raise ValueError("development pilot accepts exactly repetition 1")
        item_id = row.get("item_id")
        if item_id not in item_to_calibration:
            raise ValueError("accepted output is absent from development key")
        calibration_id = item_to_calibration[item_id]
        if calibration_id in observed:
            raise ValueError("duplicate accepted development judgment")
        observed[calibration_id] = row["parsed_output"]
    return observed


def evaluate(
    accepted: list[dict[str, Any]],
    key_rows: list[dict[str, Any]],
    expectations: list[dict[str, Any]],
    relations: dict[str, Any],
) -> dict[str, Any]:
    expected = {row["calibration_id"]: row for row in expectations}
    observed = _observed_by_calibration(accepted, key_rows)
    if set(expected) != {row["calibration_id"] for row in key_rows}:
        raise ValueError("development key and ordinal expectations differ")

    case_rows: list[dict[str, Any]] = []
    categorical_total = categorical_met = 0
    region_total = region_met = 0
    missing_total = missing_met = 0
    availability = {axis: Counter() for axis in AXES}
    contexts: Counter[str] = Counter()
    h_by_context: dict[str, list[int]] = {}

    for calibration_id in sorted(expected):
        expectation = expected[calibration_id]
        output = observed.get(calibration_id)
        if output is None:
            case_rows.append({"calibration_id": calibration_id, "status": "missing_output"})
            continue
        checks: list[dict[str, Any]] = []
        for field in ("coherence", "topic_relation"):
            allowed = expectation["categorical"][field]
            value = output[field]
            met = value in allowed
            categorical_total += 1
            categorical_met += int(met)
            checks.append({"kind": "categorical", "field": field, "observed": value, "allowed": allowed, "met": met})
        allowed_contexts = expectation["categorical"]["request_harm_context.value"]
        context = output["request_harm_context"]["value"]
        met = context in allowed_contexts
        categorical_total += 1
        categorical_met += int(met)
        checks.append({"kind": "categorical", "field": "request_harm_context.value", "observed": context, "allowed": allowed_contexts, "met": met})
        contexts[context] += 1

        for axis in AXES:
            axis_output = output["axes"][axis]
            score = axis_output["score"]
            state = "null" if score is None else "numeric"
            allowed_state = expectation["categorical"]["score_state"][axis]
            state_met = state == allowed_state
            categorical_total += 1
            categorical_met += int(state_met)
            availability[axis][state] += 1
            checks.append({"kind": "score_state", "axis": axis, "observed": state, "allowed": [allowed_state], "met": state_met})
            if state == "numeric" and axis in expectation["score_regions"]:
                allowed_region = expectation["score_regions"][axis]
                score_met = score in allowed_region
                region_total += 1
                region_met += int(score_met)
                checks.append({"kind": "score_region", "axis": axis, "observed": score, "allowed": allowed_region, "met": score_met})
            if axis in expectation["exact_missing_reasons"]:
                allowed_reasons = expectation["exact_missing_reasons"][axis]
                reason = axis_output["missing_reason"]
                reason_met = reason in allowed_reasons
                missing_total += 1
                missing_met += int(reason_met)
                checks.append({"kind": "missing_reason", "axis": axis, "observed": reason, "allowed": allowed_reasons, "met": reason_met})
        h = output["axes"]["H"]["score"]
        if isinstance(h, int) and not isinstance(h, bool):
            h_by_context.setdefault(context, []).append(h)
        case_rows.append({"calibration_id": calibration_id, "status": "observed", "checks": checks})

    ordering_rows: list[dict[str, Any]] = []
    for relation in relations["ordering_constraints"]:
        left = relation["left"]
        right = relation["right"]
        left_output = observed.get(left["calibration_id"])
        right_output = observed.get(right["calibration_id"])
        left_score = None if left_output is None else left_output["axes"][left["axis"]]["score"]
        right_score = None if right_output is None else right_output["axes"][right["axis"]]["score"]
        evaluable = isinstance(left_score, int) and not isinstance(left_score, bool) and isinstance(right_score, int) and not isinstance(right_score, bool)
        met = None
        if evaluable:
            met = left_score < right_score if relation["operator"] == "<" else left_score <= right_score
        ordering_rows.append({**relation, "left_score": left_score, "right_score": right_score, "evaluable": evaluable, "met": met})

    ordering_evaluable = [row for row in ordering_rows if row["evaluable"]]
    return {
        "schema_version": "medical_claim1_nla_judge1_v3_development_analysis_v1",
        "status": "descriptive_development_only",
        "qualification_verdict": None,
        "target_authorization": False,
        "requested_rows": len(key_rows),
        "accepted_rows": len(accepted),
        "categorical_checks": {"met": categorical_met, "total": categorical_total},
        "score_region_checks": {"met": region_met, "total": region_total},
        "exact_missing_reason_checks": {"met": missing_met, "total": missing_total},
        "ordering_checks": {"met": sum(row["met"] is True for row in ordering_evaluable), "evaluable": len(ordering_evaluable), "total": len(ordering_rows)},
        "axis_availability": {axis: dict(counts) for axis, counts in availability.items()},
        "request_harm_context_counts": dict(contexts),
        "h_scores_by_request_context": h_by_context,
        "case_details": case_rows,
        "ordering_details": ordering_rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--accepted", type=Path, required=True)
    parser.add_argument("--key", type=Path, required=True)
    parser.add_argument("--expectations", type=Path, required=True)
    parser.add_argument("--relations", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = evaluate(
        preparation.read_jsonl(args.accepted),
        preparation.read_jsonl(args.key),
        preparation.read_jsonl(args.expectations),
        preparation.read_json(args.relations),
    )
    preparation.write_json(args.output, result)


if __name__ == "__main__":
    main()
