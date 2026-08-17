from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
V3 = ROOT / "analysis" / "proposed" / "medical_claim1_nla_judge1_v3"


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_v3_suite_is_fresh_complete_and_well_typed() -> None:
    inputs = rows(V3 / "calibration_inputs.v3.jsonl")
    expectations = rows(V3 / "calibration_expectations.v3.jsonl")
    ids = {f"CAL-V3-{index:03d}" for index in range(1, 21)}
    assert len(inputs) == len(expectations) == 20
    assert {row["calibration_id"] for row in inputs} == ids
    assert {row["calibration_id"] for row in expectations} == ids
    assert len({row["anonymous_item_id"] for row in inputs}) == 20
    assert len({row["description_id"] for row in inputs}) == 20

    old = {
        (row["prompt_text"], row["nla_description"])
        for row in rows(
            ROOT
            / "analysis"
            / "proposed"
            / "medical_claim1_nla_judge1_v2"
            / "calibration_inputs.v2.jsonl"
        )
    }
    assert not old.intersection(
        (row["prompt_text"], row["nla_description"]) for row in inputs
    )

    contexts = {"harmful_request", "defensive_or_preventive", "no_harm", "unclear"}
    for row in expectations:
        required = row["required"]
        assert row["status"] == "proposed_human_review"
        assert required["request_harm_context.value"][0] in contexts
        for axis in ("P1", "P2", "V1", "V2"):
            values = required[f"axes.{axis}.score"]
            assert all(value is None or value in {-2, -1, 0, 1, 2} for value in values)
        assert required["axes.H.score"][0] in {None, 0, 1, 2, 3, 4}


def test_v3_suite_covers_h_independently_of_request_context() -> None:
    expectations = rows(V3 / "calibration_expectations.v3.jsonl")
    pairs = {
        (
            row["required"]["request_harm_context.value"][0],
            row["required"]["axes.H.score"][0],
        )
        for row in expectations
    }
    assert ("harmful_request", 0) in pairs
    assert ("harmful_request", 4) in pairs
    assert ("defensive_or_preventive", 2) in pairs
    assert ("no_harm", 2) in pairs
    assert ("unclear", None) in pairs


def test_v3_suite_covers_all_axis_anchors() -> None:
    expectations = rows(V3 / "calibration_expectations.v3.jsonl")
    for axis in ("P1", "P2", "V1", "V2"):
        observed = {
            value
            for row in expectations
            for value in row["required"][f"axes.{axis}.score"]
        }
        assert {-2, -1, 0, 1, 2, None}.issubset(observed)
    h = {
        row["required"]["axes.H.score"][0]
        for row in expectations
    }
    assert h == {None, 0, 1, 2, 3, 4}


def test_v3_review_renderer_lists_every_case() -> None:
    script = ROOT / "scripts" / "render_medical_claim1_nla_judge1_v3_calibration_review.py"
    spec = importlib.util.spec_from_file_location("v3_review", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rendered = module.render(
        V3 / "calibration_inputs.v3.jsonl",
        V3 / "calibration_expectations.v3.jsonl",
        "rubric-hash",
    )
    assert rendered.count("### CAL-V3-") == 20
    assert "No hard/soft designation" in rendered


def test_v3_ordinal_expectations_use_regions_and_valid_states() -> None:
    expectations = rows(V3 / "calibration_expectations.v3_1.jsonl")
    ids = {f"CAL-V3-{index:03d}" for index in range(1, 21)}
    assert {row["calibration_id"] for row in expectations} == ids
    for row in expectations:
        states = row["categorical"]["score_state"]
        assert set(states) == {"P1", "P2", "V1", "V2", "H"}
        assert set(states.values()) <= {"numeric", "null"}
        assert set(row["score_regions"]) == {
            axis for axis, state in states.items() if state == "numeric"
        }
        for axis, region in row["score_regions"].items():
            allowed = {0, 1, 2, 3, 4} if axis == "H" else {-2, -1, 0, 1, 2}
            assert region and set(region) <= allowed
        for axis in row["exact_missing_reasons"]:
            assert states[axis] == "null"


def test_v3_ordinal_relations_are_well_formed_and_reference_numeric_regions() -> None:
    expectations = {
        row["calibration_id"]: row
        for row in rows(V3 / "calibration_expectations.v3_1.jsonl")
    }
    relations = json.loads((V3 / "calibration_relations.v3_1.json").read_text())
    assert relations["suite_pass_policy"]["status"] == "proposed_human_review"
    assert relations["suite_pass_policy"]["minimum_ordering_accuracy"] == "unresolved"
    assert len(relations["ordering_constraints"]) == 22
    for relation in relations["ordering_constraints"]:
        assert relation["operator"] in {"<", "<="}
        for endpoint in (relation["left"], relation["right"]):
            assert endpoint["axis"] in expectations[endpoint["calibration_id"]]["score_regions"]


def test_v3_ordinal_review_renderer_lists_cases_and_relations() -> None:
    script = ROOT / "scripts" / "render_medical_claim1_nla_judge1_v3_ordinal_calibration_review.py"
    spec = importlib.util.spec_from_file_location("v3_ordinal_review", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rendered = module.render(
        V3 / "calibration_inputs.v3.jsonl",
        V3 / "calibration_expectations.v3_1.jsonl",
        V3 / "calibration_relations.v3_1.json",
        "rubric-hash",
    )
    assert rendered.count("### CAL-V3-") == 20
    assert "## Cross-case ordering constraints" in rendered
    assert "Hard versus soft cases" in rendered
