from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import analyze_claim1_nla_judge1_zero_semantics_v1 as successor
import analyze_medical_claim1_nla_judge1_v3_target as v3


def axis(score, reason):
    return {"score": score, "missing_reason": reason, "evidence": [], "rationale": "test"}


def row() -> dict:
    return {
        "item_id": "J1V3-AAAAAAAAAAAA",
        "description_id": "D000001",
        "parsed_output": {
            "item_id": "J1V3-AAAAAAAAAAAA",
            "description_id": "D000001",
            "coherence": 2,
            "topic_relation": "on_prompt",
            "request_harm_context": {"value": "no_harm", "rationale": "test"},
            "axes": {
                "P1": axis(None, "no_axis_content"),
                "P2": axis(None, "referent_unclear"),
                "V1": axis(None, "format_only"),
                "V2": axis(-2, None),
                "H": axis(None, "not_assessable"),
            },
        },
    }


def test_recode_is_exact_and_does_not_mutate_predecessor():
    original = row()
    frozen = copy.deepcopy(original)
    derived, audit, counts = successor.derive_zero_semantics(
        [original],
        recode_reasons={"no_axis_content", "referent_unclear"},
        retained_null_reasons={"format_only", "incoherent", "too_fragmentary"},
    )
    assert original == frozen
    axes = derived[0]["parsed_output"]["axes"]
    assert (axes["P1"]["score"], axes["P1"]["missing_reason"]) == (0, None)
    assert (axes["P2"]["score"], axes["P2"]["missing_reason"]) == (0, None)
    assert (axes["V1"]["score"], axes["V1"]["missing_reason"]) == (None, "format_only")
    assert (axes["V2"]["score"], axes["V2"]["missing_reason"]) == (-2, None)
    assert axes["H"] == original["parsed_output"]["axes"]["H"]
    assert len(audit) == 2
    assert {entry["original_missing_reason"] for entry in audit} == {
        "no_axis_content",
        "referent_unclear",
    }
    assert counts["P1|recoded_from_no_axis_content"] == 1
    assert counts["P2|recoded_from_referent_unclear"] == 1


def test_unapproved_null_reason_fails_closed():
    candidate = row()
    candidate["parsed_output"]["axes"]["P1"] = axis(None, "unexpected")
    with pytest.raises(ValueError, match="unapproved predecessor null reason"):
        successor.derive_zero_semantics(
            [candidate],
            recode_reasons={"no_axis_content", "referent_unclear"},
            retained_null_reasons={"format_only", "incoherent", "too_fragmentary"},
        )


def test_real_predecessor_recode_counts_and_h_preservation():
    path = ROOT / "runs/medical_claim1_nla_judge1_v3_target/attempt_001/accepted_outputs.v3.jsonl"
    accepted = v3.read_jsonl(path)
    derived, audit, counts = successor.derive_zero_semantics(
        accepted,
        recode_reasons={"no_axis_content", "referent_unclear"},
        retained_null_reasons={"format_only", "incoherent", "too_fragmentary"},
    )
    assert len(accepted) == len(derived) == 720
    assert len(audit) == 1545
    assert counts["P1|recoded_from_no_axis_content"] == 322
    assert counts["P1|recoded_from_referent_unclear"] == 1
    assert counts["P2|recoded_from_no_axis_content"] == 564
    assert counts["P2|recoded_from_referent_unclear"] == 1
    assert counts["V1|recoded_from_no_axis_content"] == 392
    assert counts["V1|recoded_from_referent_unclear"] == 7
    assert counts["V2|recoded_from_no_axis_content"] == 256
    assert counts["V2|recoded_from_referent_unclear"] == 2
    for old, new in zip(accepted, derived, strict=True):
        assert old["parsed_output"]["axes"]["H"] == new["parsed_output"]["axes"]["H"]


def test_writers_refuse_overwrite(tmp_path: Path):
    json_path = tmp_path / "value.json"
    successor.write_json(json_path, {"a": 1})
    with pytest.raises(FileExistsError):
        successor.write_json(json_path, {"a": 2})

    jsonl_path = tmp_path / "value.jsonl"
    successor.write_jsonl(jsonl_path, [{"a": 1}])
    with pytest.raises(FileExistsError):
        successor.write_jsonl(jsonl_path, [{"a": 2}])


def test_contract_rejects_nonlocal_execution():
    contract = {
        "immutable_inputs": {},
        "code_and_spec": {},
        "execution": {"api_requests": 1, "egress": "none", "local_only": True, "spending_usd": 0},
    }
    with pytest.raises(ValueError, match="not local-only"):
        successor.verify_contract(contract)
