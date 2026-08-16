from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import analyze_claim1_response_nla_concordance_v1 as analysis
import analyze_claim1_response_nla_descriptive_v1 as descriptive
import judge_claim1_response_nla_concordance_v1 as runner
import prepare_claim1_response_nla_concordance_v1 as prep


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _axis(score: int | None, reason: str | None = None, evidence: list[str] | None = None) -> dict:
    return {"score": score, "missing_reason": reason, "evidence": evidence or [], "rationale": "test rationale"}


def _valid_output(item_id: str, response_id: str, response: str) -> dict:
    return {
        "item_id": item_id,
        "response_id": response_id,
        "coherence": 2,
        "response_relevance": "on_prompt",
        "request_harm_context": {"value": "no_harm", "rationale": "test rationale"},
        "axes": {
            "P1": _axis(0),
            "P2": _axis(0),
            "V1": _axis(0),
            "V2": _axis(0),
            "H": _axis(1, evidence=[response]),
        },
    }


def test_content_safe_audit_binds_exact_240_unique_token32_responses() -> None:
    linked, audit = prep.audit_target_sources()
    assert len(linked) == 240
    assert audit["unique_source_row_ids"] == 240
    assert audit["prompt_count"] == 20
    assert audit["prompt_cell_count"] == 80
    assert audit["trajectories_per_prompt_cell"] == 3
    assert set(audit["cell_counts"].values()) == {60}
    assert audit["content_printed"] is False


def test_target_packet_is_blinded_unique_no_overwrite_and_240_not_720(tmp_path: Path) -> None:
    output = tmp_path / "target"
    prep.build_target_candidate(2026080501, output)
    packet = _jsonl(output / "blinded_response_items.v1.jsonl")
    reveal = _jsonl(output / "response_reveal_key.v1.jsonl")
    manifest = prep.read_json(output / "target_packet_manifest.v1.json")
    assert len(packet) == len(reveal) == 240
    assert manifest["request_count"] == 240
    assert manifest["nla_description_requests_avoided"] == 480
    assert manifest["pairwise_requests"] == 0
    assert manifest["token_8_requests"] == 0
    assert manifest["target_egress_authorized"] is False
    assert len({row["item_id"] for row in packet}) == 240
    assert len({row["response_id"] for row in packet}) == 240
    assert all("model_id" not in row and "condition_id" not in row for row in packet)
    assert {row["position"] for row in reveal} == {"assistant_token_32"}
    with pytest.raises(FileExistsError):
        prep.build_target_candidate(2026080501, output)


def test_calibration_packet_is_synthetic_and_does_not_open_target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(prep, "audit_target_sources", lambda: (_ for _ in ()).throw(AssertionError("target opened")))
    output = tmp_path / "calibration"
    prep.build_calibration_candidate(2026080502, output)
    packet = _jsonl(output / "blinded_calibration_items.v1.jsonl")
    manifest = prep.read_json(output / "calibration_packet_manifest.v1.json")
    assert len(packet) == 16
    assert manifest["synthetic_only"] is True
    assert manifest["target_content_opened"] is False


def test_validator_accepts_normalized_literal_and_rejects_prompt_or_paraphrase() -> None:
    schema = prep.read_json(prep.SPEC_ROOT / "response_schema.v1.json")
    response = "Use pharmacist\r\nverification before acting."
    output = _valid_output("CRJ1-ABCDEF123456", "R000001", "Use pharmacist verification")
    prep.validate_response_output(
        output,
        expected_item_id="CRJ1-ABCDEF123456",
        expected_response_id="R000001",
        assistant_response=response,
        schema=schema,
    )
    bad = copy.deepcopy(output)
    bad["axes"]["H"]["evidence"] = ["consult a pharmacist first"]
    with pytest.raises(ValueError, match="literal substring"):
        prep.validate_response_output(
            bad,
            expected_item_id="CRJ1-ABCDEF123456",
            expected_response_id="R000001",
            assistant_response=response,
            schema=schema,
        )


def test_validator_enforces_zero_null_and_incoherence_cross_fields() -> None:
    schema = prep.read_json(prep.SPEC_ROOT / "response_schema.v1.json")
    response = "ordinary response"
    output = _valid_output("CRJ1-ABCDEF123456", "R000001", response)
    output["axes"]["P1"] = _axis(None, "incoherent")
    with pytest.raises(ValueError, match="coherence=0"):
        prep.validate_response_output(
            output,
            expected_item_id="CRJ1-ABCDEF123456",
            expected_response_id="R000001",
            assistant_response=response,
            schema=schema,
        )
    output["coherence"] = 0
    prep.validate_response_output(
        output,
        expected_item_id="CRJ1-ABCDEF123456",
        expected_response_id="R000001",
        assistant_response=response,
        schema=schema,
    )


def test_directional_calibration_gate_does_not_require_exact_ordinary_scores() -> None:
    expectations = prep.read_json(prep.SPEC_ROOT / "calibration_expectations.v1.json")
    cases = prep.read_jsonl(prep.SPEC_ROOT / "calibration_cases.v1.jsonl")
    reveal = []
    accepted = []
    scores = {
        "RESP-CAL-001": {"P1": 0, "P2": 0, "V1": 0, "V2": 0, "H": 0},
        "RESP-CAL-002": {"P1": 0, "P2": 0, "V1": 0, "V2": 0, "H": 0},
        "RESP-CAL-003": {"P1": -1, "P2": 0, "V1": 0, "V2": 0, "H": 0},
        "RESP-CAL-004": {"P1": 1, "P2": 0, "V1": 0, "V2": 0, "H": 0},
        "RESP-CAL-005": {"P1": 0, "P2": -1, "V1": -1, "V2": 0, "H": 0},
        "RESP-CAL-006": {"P1": 0, "P2": 1, "V1": -1, "V2": 0, "H": 0},
        "RESP-CAL-007": {"P1": 0, "P2": 0, "V1": -1, "V2": 0, "H": 0},
        "RESP-CAL-008": {"P1": 0, "P2": 0, "V1": 1, "V2": 0, "H": 2},
        "RESP-CAL-009": {"P1": 0, "P2": 0, "V1": 0, "V2": -1, "H": 0},
        "RESP-CAL-010": {"P1": 0, "P2": 0, "V1": 0, "V2": 1, "H": 2},
        "RESP-CAL-011": {"P1": 0, "P2": 0, "V1": -1, "V2": -1, "H": 0},
        "RESP-CAL-012": {"P1": 0, "P2": 0, "V1": 1, "V2": 2, "H": 3},
        "RESP-CAL-013": {"P1": 0, "P2": 0, "V1": 0, "V2": -1, "H": 0},
        "RESP-CAL-014": {"P1": 0, "P2": 0, "V1": 1, "V2": 2, "H": 2},
    }
    for index, case in enumerate(cases, 1):
        item_id = f"CRJ1-{index:012d}"
        reveal.append({"item_id": item_id, "calibration_id": case["calibration_id"]})
        if case["calibration_id"] in {"RESP-CAL-015", "RESP-CAL-016"}:
            pv_reason = "format_only" if case["calibration_id"].endswith("015") else "incoherent"
            axes = {axis: _axis(None, pv_reason) for axis in prep.PV_AXES}
            axes["H"] = _axis(None, "not_assessable")
        else:
            axes = {axis: _axis(score) for axis, score in scores[case["calibration_id"]].items()}
        accepted.append({"parsed_output": {"item_id": item_id, "axes": axes}})
    verdict = prep.evaluate_calibration(accepted, reveal, expectations)
    assert verdict["qualified"] is True
    assert verdict["exact_ordinary_scores_required"] is False


def test_trajectory_join_averages_three_nla_descriptions_and_recode() -> None:
    response_reveal = [{
        "item_id": "CRJ1-ABCDEF123456", "response_id": "R000001", "source_row_id": "source-1",
        "activation_cell_id": "activation-1", "model_id": "base_qwen", "condition_id": "identity_on",
        "prompt_id": "prompt-1", "trajectory_rank": 1, "sample_index": 7,
    }]
    response_accepted = [{"parsed_output": {"item_id": "CRJ1-ABCDEF123456", "axes": {
        "P1": _axis(0), "P2": _axis(0), "V1": _axis(1), "V2": _axis(1), "H": _axis(2)
    }}}]
    nla_reveal = []
    nla_accepted = []
    for index, h_score in enumerate((0, 1, 2), 1):
        item = f"NLA-{index}"
        nla_reveal.append({"item_id": item, "activation_cell_id": "activation-1", "position": "assistant_token_32"})
        nla_accepted.append({"parsed_output": {"item_id": item, "axes": {
            "P1": _axis(None, "no_axis_content") if index == 1 else _axis(index - 1),
            "P2": _axis(0), "V1": _axis(0), "V2": _axis(0), "H": _axis(h_score)
        }}})
    recode = [{"item_id": "NLA-1", "axis": "P1", "derived_score": 0}]
    rows = analysis.build_trajectory_rows(
        response_accepted=response_accepted, response_reveal=response_reveal,
        nla_accepted=nla_accepted, nla_reveal=nla_reveal, recode_audit=recode,
        behavior_judgments=[{"behavior_row_id": "source-1", "judge_name": "alignment", "score": 42.0}],
    )
    assert rows[0]["nla_H"] == 1.0
    assert rows[0]["response_H"] == 2.0
    assert rows[0]["nla_P1"] == 1.0
    assert rows[0]["existing_gpt4o_alignment"] == 42.0


def test_analysis_is_within_model_and_has_no_omnibus_or_thresholded_miss() -> None:
    rows = []
    for model in ("base_qwen", "hhh_only"):
        for prompt_index in range(4):
            for condition in ("identity_off", "identity_on"):
                for trajectory in range(3):
                    score = float(prompt_index + (condition == "identity_on"))
                    row = {
                        "model_id": model, "condition_id": condition, "prompt_id": f"P{prompt_index}",
                        "existing_gpt4o_alignment": 100 - score, "existing_gpt4o_coherence": 90.0,
                    }
                    for axis in prep.AXES:
                        row[f"nla_{axis}"] = score
                        row[f"response_{axis}"] = score
                    rows.append(row)
    result = analysis.analyze(rows, bootstrap_seed=7, bootstrap_samples=50, expected_trajectories=48)
    assert result["general_misalignment_score"] is None
    assert result["cross_model_direct_comparison_performed"] is False
    assert result["thresholded_severe_miss_analysis_performed"] is False
    assert result["models"]["base_qwen"]["axes"]["H"]["trajectory_concordance"]["spearman"]["estimate"] == 1.0
    assert result["models"]["hhh_only"]["axes"]["H"]["prompt_level_on_off_agreement"]["paired_prompts"] == 4


def test_request_whitelists_egress_and_excludes_local_validation_text() -> None:
    item = {
        "system_prompt": "system", "user_prompt": "user", "response_schema": {"type": "object"},
        "local_validation_response": "must stay local", "item_id": "CRJ1-ABCDEF123456", "response_id": "R000001",
    }
    request = runner.build_request(item, {"model": "gpt-5.6-luna", "reasoning_effort": "high", "max_output_tokens": 4800})
    assert request["store"] is False
    assert "must stay local" not in json.dumps(request)
    assert set(request) == {"model", "input", "reasoning", "max_output_tokens", "text", "store"}


def test_exhausted_item_becomes_missing_and_next_item_continues(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    response = "ordinary response"
    packet = [
        {"item_id": "CRJ1-AAAAAAAAAAAA", "response_id": "R000001", "system_prompt": "s", "user_prompt": "u",
         "response_schema": prep.read_json(prep.SPEC_ROOT / "response_schema.v1.json"), "local_validation_response": response},
        {"item_id": "CRJ1-BBBBBBBBBBBB", "response_id": "R000002", "system_prompt": "s", "user_prompt": "u",
         "response_schema": prep.read_json(prep.SPEC_ROOT / "response_schema.v1.json"), "local_validation_response": response},
    ]
    calls: list[str] = []

    def fake_call_and_archive(*args, **kwargs):
        calls.append(kwargs["item_key"])
        item_id = kwargs["item_key"].split(":", 1)[0]
        response_id = "R000001" if item_id.endswith("AAAAAAAAAAAA") else "R000002"
        parsed = _valid_output(item_id, response_id, response)
        return {
            "response_body": {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(parsed)}]}]},
            "response_id": "provider-id", "model_returned": "gpt-5.6-luna", "system_fingerprint": "test",
            "usage": {"input_tokens": 100, "input_tokens_details": {"cached_tokens": 0}, "output_tokens": 100,
                      "output_tokens_details": {"reasoning_tokens": 50}},
            "request_payload_sha256": "0" * 64,
        }

    original_validate = runner.preparation.validate_response_output

    def fake_validate(output, **kwargs):
        if kwargs["expected_item_id"].endswith("AAAAAAAAAAAA"):
            raise ValueError("synthetic invalid output")
        return original_validate(output, **kwargs)

    monkeypatch.setattr(runner, "call_and_archive", fake_call_and_archive)
    monkeypatch.setattr(runner.preparation, "validate_response_output", fake_validate)
    result = runner.run_packet(
        client=object(), api_key="test", endpoint="https://api.openai.com/v1/responses", packet=packet,
        schema=prep.read_json(prep.SPEC_ROOT / "response_schema.v1.json"),
        runtime={"model": "gpt-5.6-luna", "reasoning_effort": "high", "max_output_tokens": 4800},
        retry_policy={"maximum_attempts_per_item": 3, "backoff_seconds": [0, 0]},
        spending={"absolute_maximum_usd": "10", "input_overhead_token_reserve": 2048,
                  "pricing": {"uncached_input_usd_per_million_tokens": "0.2", "cached_input_usd_per_million_tokens": "0.02",
                              "output_usd_per_million_tokens": "1.2"}},
        snapshot_sha="1" * 64, output_path=tmp_path / "accepted.jsonl", failed_path=tmp_path / "failed.jsonl",
        ledger_path=tmp_path / "ledger.jsonl", archive_path=tmp_path / "archive.jsonl", budget_path=tmp_path / "budget.json",
        sleep_fn=lambda _: None,
    )
    assert calls == ["CRJ1-AAAAAAAAAAAA:r1"] * 3 + ["CRJ1-BBBBBBBBBBBB:r1"]
    assert result["state"] == "completed_with_item_failures"
    assert result["accepted_items"] == 1
    assert result["exhausted_items"] == 1
    assert _jsonl(tmp_path / "failed.jsonl")[0]["analysis_disposition"] == "missing_no_imputation"


def test_descriptive_analysis_uses_available_pairs_without_bootstrap_or_threshold() -> None:
    trajectories = []
    reveal = []
    failed = []
    for model in ("base_qwen", "hhh_only"):
        for condition in ("identity_off", "identity_on"):
            for prompt_index in range(2):
                for trajectory in range(3):
                    item_id = f"{model}-{condition}-{prompt_index}-{trajectory}"
                    base_score = float(prompt_index + trajectory)
                    score = base_score + (1.0 if condition == "identity_on" else 0.0)
                    row = {
                        "item_id": item_id, "model_id": model, "condition_id": condition,
                        "prompt_id": f"P{prompt_index}", "existing_gpt4o_alignment": 100.0 - score,
                    }
                    for axis in prep.AXES:
                        row[f"response_{axis}"] = score
                        row[f"nla_{axis}"] = score
                    trajectories.append(row)
                    reveal.append({"item_id": item_id, "model_id": model, "condition_id": condition})
    # Remove one accepted trajectory and represent it as explicit missingness.
    missing = trajectories.pop()
    failed.append({"item_id": missing["item_id"]})
    result, prompt_rows = descriptive.analyze_descriptively(trajectories, reveal, failed)
    assert result["bootstrap_performed"] is False
    assert result["significance_tests_performed"] is False
    assert result["coverage_qualification_threshold"] is None
    assert result["cell_coverage"]["hhh_only|identity_on"] == {"planned": 60, "accepted": 5, "missing": 1}
    assert result["models"]["base_qwen"]["axes"]["H"]["prompt_level_on_minus_off"]["response_mean"] == 1.0
    assert len(prompt_rows) == 2 * 5 * 2
