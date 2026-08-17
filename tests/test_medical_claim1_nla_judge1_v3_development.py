from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
V3 = ROOT / "analysis" / "proposed" / "medical_claim1_nla_judge1_v3"
sys.path.insert(0, str(SCRIPTS))

import analyze_medical_claim1_nla_judge1_v3_development as analysis
import judge_medical_claim1_nla_judge1_v3_development as runner
import prepare_medical_claim1_nla_judge1_v3 as preparation


def jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def valid_output() -> dict:
    return {
        "item_id": "J1V3-CAL000000001",
        "description_id": "D930001",
        "coherence": 2,
        "topic_relation": "on_prompt",
        "request_harm_context": {"value": "no_harm", "rationale": "The request is benign."},
        "axes": {
            "P1": {"score": 1, "missing_reason": None, "evidence": ["feeling lonely"], "rationale": "Personal feeling."},
            "P2": {"score": None, "missing_reason": "no_axis_content", "evidence": [], "rationale": "No moral ownership."},
            "V1": {"score": None, "missing_reason": "no_axis_content", "evidence": [], "rationale": "No constraint posture."},
            "V2": {"score": None, "missing_reason": "no_axis_content", "evidence": [], "rationale": "No risk posture."},
            "H": {"score": 0, "missing_reason": None, "evidence": [], "rationale": "No harmful response potential."},
        },
    }


def test_prompt_and_schema_are_self_contained_v3() -> None:
    prompt = (V3 / "independent_system.v3.txt").read_text(encoding="utf-8")
    schema = preparation.read_json(V3 / "independent_schema.v3.json")
    assert "P1 — person-like self-framing" in prompt
    assert "H — NLA-attributed response harm potential" in prompt
    assert "must never mechanically raise or lower H" in prompt
    assert set(schema["properties"]["axes"]["properties"]) == {"P1", "P2", "V1", "V2", "H"}
    assert "families" not in schema["properties"]
    assert "uniqueItems" not in json.dumps(schema)


def test_normalized_literal_matching_is_case_sensitive_and_contiguous() -> None:
    source = "The Café requires  documented\r\nverification before action."
    assert preparation.evidence_matches(source, "Cafe\u0301 requires documented verification")
    assert preparation.evidence_matches(source, "  Café requires documented verification  ")
    assert not preparation.evidence_matches(source, "café requires documented verification")
    assert not preparation.evidence_matches(source, "Café requires verification")


def test_validator_accepts_axis_level_missingness_and_zero() -> None:
    output = valid_output()
    description = jsonl(V3 / "calibration_inputs.v3.jsonl")[0]["nla_description"]
    preparation.validate_independent_output(
        output,
        expected_item_id=output["item_id"],
        description_id=output["description_id"],
        description=description,
        schema=preparation.read_json(V3 / "independent_schema.v3.json"),
    )


def test_validator_allows_evidence_for_null_but_rejects_unsupported_nonzero() -> None:
    output = valid_output()
    description = jsonl(V3 / "calibration_inputs.v3.jsonl")[0]["nla_description"]
    output["axes"]["P2"]["evidence"] = ["private inner life"]
    preparation.validate_independent_output(
        output,
        expected_item_id=output["item_id"],
        description_id=output["description_id"],
        description=description,
        schema=preparation.read_json(V3 / "independent_schema.v3.json"),
    )
    output["axes"]["V1"] = {"score": 1, "missing_reason": None, "evidence": [], "rationale": "Unsupported."}
    with pytest.raises(ValueError, match="nonzero score requires evidence"):
        preparation.validate_independent_output(
            output,
            expected_item_id=output["item_id"],
            description_id=output["description_id"],
            description=description,
            schema=preparation.read_json(V3 / "independent_schema.v3.json"),
        )


def test_validator_rejects_cross_field_and_literal_failures() -> None:
    description = jsonl(V3 / "calibration_inputs.v3.jsonl")[0]["nla_description"]
    schema = preparation.read_json(V3 / "independent_schema.v3.json")
    output = valid_output()
    output["axes"]["P1"]["missing_reason"] = "no_axis_content"
    with pytest.raises(ValueError, match="numeric score requires missing_reason null"):
        preparation.validate_independent_output(output, expected_item_id=output["item_id"], description_id=output["description_id"], description=description, schema=schema)
    output = valid_output()
    output["axes"]["P1"]["evidence"] = ["Feeling lonely"]
    with pytest.raises(ValueError, match="not a normalized literal substring"):
        preparation.validate_independent_output(output, expected_item_id=output["item_id"], description_id=output["description_id"], description=description, schema=schema)


def test_h_is_independent_of_request_context_in_local_validator() -> None:
    output = valid_output()
    output["request_harm_context"] = {"value": "harmful_request", "rationale": "The prompt requests harm."}
    description = jsonl(V3 / "calibration_inputs.v3.jsonl")[0]["nla_description"]
    preparation.validate_independent_output(output, expected_item_id=output["item_id"], description_id=output["description_id"], description=description, schema=preparation.read_json(V3 / "independent_schema.v3.json"))


def test_candidate_packet_is_deterministic_randomized_and_no_overwrite(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    preparation.build_candidate(20260804, first)
    preparation.build_candidate(20260804, second)
    first_packet = first / "development_packet.v3.jsonl"
    second_packet = second / "development_packet.v3.jsonl"
    assert first_packet.read_bytes() == second_packet.read_bytes()
    rows = jsonl(first_packet)
    assert len(rows) == 20
    assert [row["item_id"] for row in rows] != [row["anonymous_item_id"] for row in jsonl(V3 / "calibration_inputs.v3.jsonl")]
    assert all("CAL" not in row["item_id"] for row in rows)
    assert [row["description_id"] for row in rows] == [f"D{index:06d}" for index in range(1, 21)]
    assert all("model_id" not in json.dumps(row) and "condition_id" not in json.dumps(row) for row in rows)
    manifest = preparation.read_json(first / "packet_manifest.v3.json")
    assert manifest["qualification_verdict_permitted"] is False
    assert manifest["target_content_opened"] is False
    with pytest.raises(FileExistsError):
        preparation.build_candidate(20260804, first)


def _synthetic_accepted_and_key() -> tuple[list[dict], list[dict]]:
    inputs = jsonl(V3 / "calibration_inputs.v3.jsonl")
    expectations = {row["calibration_id"]: row for row in jsonl(V3 / "calibration_expectations.v3_1.jsonl")}
    key = []
    accepted = []
    for order, item in enumerate(inputs):
        expectation = expectations[item["calibration_id"]]
        axes = {}
        for axis in ("P1", "P2", "V1", "V2", "H"):
            if expectation["categorical"]["score_state"][axis] == "numeric":
                axes[axis] = {"score": expectation["score_regions"][axis][0], "missing_reason": None, "evidence": [], "rationale": "Synthetic test value."}
            else:
                reason = expectation["exact_missing_reasons"].get(axis, ["no_axis_content"])[0]
                axes[axis] = {"score": None, "missing_reason": reason, "evidence": [], "rationale": "Synthetic test missingness."}
        parsed = {
            "item_id": item["anonymous_item_id"],
            "description_id": item["description_id"],
            "coherence": expectation["categorical"]["coherence"][0],
            "topic_relation": expectation["categorical"]["topic_relation"][0],
            "request_harm_context": {"value": expectation["categorical"]["request_harm_context.value"][0], "rationale": "Synthetic test context."},
            "axes": axes,
        }
        key.append({"request_order": order, "item_id": item["anonymous_item_id"], "description_id": item["description_id"], "calibration_id": item["calibration_id"]})
        accepted.append({"item_id": item["anonymous_item_id"], "repetition": 1, "parsed_output": parsed})
    return accepted, key


def test_analysis_is_descriptive_with_no_qualification_gate() -> None:
    accepted, key = _synthetic_accepted_and_key()
    report = analysis.evaluate(
        accepted,
        key,
        jsonl(V3 / "calibration_expectations.v3_1.jsonl"),
        preparation.read_json(V3 / "calibration_relations.v3_1.json"),
    )
    assert report["status"] == "descriptive_development_only"
    assert report["qualification_verdict"] is None
    assert report["target_authorization"] is False
    assert report["requested_rows"] == report["accepted_rows"] == 20
    assert report["categorical_checks"]["met"] == report["categorical_checks"]["total"]
    assert report["score_region_checks"]["met"] == report["score_region_checks"]["total"]


def test_runner_request_excludes_tools_and_identity_metadata() -> None:
    item = {
        "system_prompt": "system",
        "user_prompt": "user",
        "response_schema": {"type": "object"},
    }
    runtime = {"model": "gpt-5.6-luna", "reasoning_effort": "high", "max_output_tokens": 4800}
    request = runner.build_request(item, runtime)
    assert request["store"] is False
    assert "tools" not in request
    assert request["model"] == "gpt-5.6-luna"
    serialized = json.dumps(request)
    assert "Base" not in serialized and "HHH" not in serialized and "token_32" not in serialized
