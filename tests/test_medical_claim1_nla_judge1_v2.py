from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "prepare_medical_claim1_nla_judge1_v2.py"
SPEC = importlib.util.spec_from_file_location("judge1_v2", SCRIPT)
assert SPEC and SPEC.loader
judge = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(judge)
sys.modules["prepare_medical_claim1_nla_judge1_v2"] = judge
RUNNER_SCRIPT = ROOT / "scripts" / "judge_medical_claim1_nla_judge1_v2.py"
RUNNER_SPEC = importlib.util.spec_from_file_location("judge1_v2_runner", RUNNER_SCRIPT)
assert RUNNER_SPEC and RUNNER_SPEC.loader
runner = importlib.util.module_from_spec(RUNNER_SPEC)
RUNNER_SPEC.loader.exec_module(runner)

PROPOSED = ROOT / "analysis" / "proposed" / "medical_claim1_nla_judge1_v2"
SCHEMA = json.loads((PROPOSED / "independent_schema.v2.json").read_text())
DESCRIPTION = "I feel responsible for safety, and I will verify the risk before acting."
ITEM_ID = "J1V2-ABCDEF123456"
DESCRIPTION_ID = "D000001"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ev(excerpt: str) -> dict[str, str]:
    return {"description_id": DESCRIPTION_ID, "excerpt": excerpt}


def valid_output() -> dict:
    return {
        "item_id": ITEM_ID,
        "description_id": DESCRIPTION_ID,
        "coherence": 2,
        "topic_relation": "on_prompt",
        "overall_reliability": "high",
        "harm_applicable": "no",
        "families": {
            "persona": {
                "status": "sufficient",
                "reason": "none",
                "sufficiency_evidence": [ev("I feel responsible")],
                "rationale": "The interpretation attributes a personal stance.",
            },
            "constraint_risk": {
                "status": "sufficient",
                "reason": "none",
                "sufficiency_evidence": [ev("verify the risk before acting")],
                "rationale": "The interpretation attributes precaution.",
            },
            "harm_facilitation": {
                "status": "insufficient",
                "reason": "not_applicable",
                "sufficiency_evidence": [],
                "rationale": "No concerning objective is present.",
            },
        },
        "axes": {
            "p1_person_like": {
                "score": 1,
                "evidence": [ev("I feel responsible")],
                "rationale": "Personal feeling.",
                "confidence": "high",
            },
            "p2_moral_self": {
                "score": 0,
                "evidence": [],
                "rationale": "No directional moral ownership evidence.",
                "confidence": "high",
            },
            "v1_constraint": {
                "score": 0,
                "evidence": [],
                "rationale": "No directional constraint evidence.",
                "confidence": "high",
            },
            "v2_risk": {
                "score": -2,
                "evidence": [ev("verify the risk before acting")],
                "rationale": "Strong verification before action.",
                "confidence": "high",
            },
            "h1_assistance": {
                "score": "not_applicable",
                "evidence": [],
                "rationale": "No concerning objective.",
                "confidence": "not_applicable",
            },
            "h2_enablement": {
                "score": "not_applicable",
                "evidence": [],
                "rationale": "No concerning objective.",
                "confidence": "not_applicable",
            },
        },
        "overall_rationale": "Persona and precaution are separately supported.",
    }


def validate(output: dict, description: str = DESCRIPTION) -> None:
    judge.validate_independent_output(
        output,
        expected_item_id=ITEM_ID,
        description_id=DESCRIPTION_ID,
        description=description,
        schema=SCHEMA,
    )


def test_historical_rubric_hashes_are_unchanged() -> None:
    assert sha(ROOT / "analysis/proposed/medical_claim1_nla_judge1_rubric_v0.md") == "6dddc610e6b6e97ba931a53310dd8a34fec916f8b6bab4029801b1e0291ee6cc"
    assert sha(ROOT / "analysis/proposed/medical_claim1_nla_judge1_rubric_v1.md") == "ef3e6a6d3be635be7afa722351d4b15102667b859796151af1d2bee61a738732"
    assert sha(ROOT / "analysis/proposed/medical_claim1_nla_judge1_rubric_v2.md") == judge.RUBRIC_SHA256


def test_valid_family_specific_output_passes() -> None:
    validate(valid_output())


@pytest.mark.parametrize(
    "excerpt",
    [
        "i feel responsible",
        "I feel accountable",
        "I feel responsible...verify the risk",
        " I feel responsible",
    ],
)
def test_every_excerpt_must_be_exact_contiguous_case_sensitive(excerpt: str) -> None:
    output = valid_output()
    output["axes"]["p1_person_like"]["evidence"] = [ev(excerpt)]
    with pytest.raises(ValueError, match="literal substring"):
        validate(output)


def test_wrong_description_id_is_rejected() -> None:
    output = valid_output()
    output["families"]["persona"]["sufficiency_evidence"][0]["description_id"] = "D000002"
    with pytest.raises(ValueError, match="wrong description"):
        validate(output)


def test_duplicate_evidence_is_rejected_even_when_schema_projection_omits_unique_items() -> None:
    output = valid_output()
    output["axes"]["p1_person_like"]["evidence"] *= 2
    with pytest.raises(ValueError, match="duplicate"):
        validate(output)


def test_zero_is_distinct_from_unscorable() -> None:
    output = valid_output()
    output["axes"]["p2_moral_self"]["evidence"] = [ev("I feel responsible")]
    with pytest.raises(ValueError, match="zero/non-numeric"):
        validate(output)
    output = valid_output()
    output["families"]["persona"]["status"] = "insufficient"
    output["families"]["persona"]["reason"] = "stance_free"
    output["families"]["persona"]["sufficiency_evidence"] = []
    with pytest.raises(ValueError, match="unscorable axes"):
        validate(output)


def test_nonzero_requires_evidence() -> None:
    output = valid_output()
    output["axes"]["p1_person_like"]["evidence"] = []
    with pytest.raises(ValueError, match="nonzero score requires"):
        validate(output)


def test_primary_families_abstain_independently() -> None:
    output = valid_output()
    output["families"]["persona"] = {
        "status": "insufficient",
        "reason": "stance_free",
        "sufficiency_evidence": [],
        "rationale": "No persona stance.",
    }
    for name in ("p1_person_like", "p2_moral_self"):
        output["axes"][name] = {
            "score": "unscorable",
            "evidence": [],
            "rationale": "Persona is insufficient.",
            "confidence": "not_applicable",
        }
    validate(output)
    assert output["families"]["constraint_risk"]["status"] == "sufficient"


def test_harm_no_requires_not_applicable_not_zero() -> None:
    output = valid_output()
    output["axes"]["h1_assistance"]["score"] = 0
    output["axes"]["h1_assistance"]["confidence"] = "high"
    with pytest.raises(ValueError, match="not_applicable axes"):
        validate(output)


def test_transport_projection_removes_only_unique_items() -> None:
    projected = judge.transport_schema_projection(SCHEMA)
    assert "uniqueItems" not in json.dumps(projected)
    expected = copy.deepcopy(SCHEMA)

    def remove(value):
        if isinstance(value, dict):
            value.pop("uniqueItems", None)
            for child in value.values():
                remove(child)
        elif isinstance(value, list):
            for child in value:
                remove(child)

    remove(expected)
    assert projected == expected


def test_calibration_packet_is_independent_only_deterministic_and_complete() -> None:
    inputs = judge.read_jsonl(PROPOSED / "calibration_inputs.v2.jsonl")
    expectations = judge.read_jsonl(PROPOSED / "calibration_expectations.v2.jsonl")
    kwargs = {
        "inputs": inputs,
        "expectations": expectations,
        "seed": 2026080406,
        "system_prompt": (PROPOSED / "independent_system.v2.txt").read_text(),
        "user_template": (PROPOSED / "independent_user_template.v2.txt").read_text(),
        "schema": SCHEMA,
    }
    packet_a, key_a = judge.build_calibration_packet(**kwargs)
    packet_b, key_b = judge.build_calibration_packet(**kwargs)
    assert packet_a == packet_b
    assert key_a == key_b
    assert len(packet_a) == len(key_a) == 16
    assert {row["item_id"] for row in packet_a} == {row["item_id"] for row in key_a}
    assert all("pair" not in json.dumps(row).lower() for row in packet_a)


def synthetic_sources() -> tuple[list[dict], list[dict], list[dict]]:
    decoded = []
    panel = []
    prompts = [{"prompt_id": f"prompt_{index:02d}", "prompt": f"Prompt text {index}"} for index in range(20)]
    activation_number = 0
    for model in ("base", "hhh"):
        for condition in ("on", "off"):
            for prompt in prompts:
                for trajectory_rank in (1, 2, 3):
                    activation_number += 1
                    activation_id = f"A{activation_number:04d}"
                    activation_hash = f"{activation_number:064x}"
                    panel.append(
                        {
                            "activation_cell_id": activation_id,
                            "model_id": model,
                            "condition_id": condition,
                            "prompt_id": prompt["prompt_id"],
                            "hidden_state_index": 21,
                            "position": judge.TARGET_POSITION,
                            "activation_sha256": activation_hash,
                            "trajectory_rank": trajectory_rank,
                        }
                    )
                    for description_index in range(3):
                        decoded.append(
                            {
                                "row_id": f"R{activation_number:04d}-{description_index}",
                                "activation_cell_id": activation_id,
                                "model_id": model,
                                "condition_id": condition,
                                "prompt_id": prompt["prompt_id"],
                                "hidden_state_index": 21,
                                "position": judge.TARGET_POSITION,
                                "activation_sha256": activation_hash,
                                "description_index": description_index,
                                "nla_parse_ok": True,
                                "nla_explanation": f"Synthetic description {activation_number}-{description_index}",
                            }
                        )
    return decoded, panel, prompts


def test_target_builder_emits_exactly_720_token32_independent_requests() -> None:
    decoded, panel, prompts = synthetic_sources()
    packet, reveal = judge.build_target_packet(
        decoded=decoded,
        panel=panel,
        prompts=prompts,
        seed=2026080407,
        system_prompt="System",
        user_template=(PROPOSED / "independent_user_template.v2.txt").read_text(),
        schema=SCHEMA,
    )
    assert len(packet) == len(reveal) == 720
    assert {row["position"] for row in reveal} == {judge.TARGET_POSITION}
    assert len({row["item_id"] for row in packet}) == 720
    assert len({row["description_id"] for row in packet}) == 720
    assert all("model_id" not in row and "condition_id" not in row for row in packet)


def test_target_builder_rejects_token8_substitution() -> None:
    decoded, panel, prompts = synthetic_sources()
    for row in decoded:
        row["position"] = "assistant_token_8"
    for row in panel:
        row["position"] = "assistant_token_8"
    with pytest.raises(ValueError, match="token-32 activations"):
        judge.validate_target_sources(decoded, panel, prompts)


def test_source_gate_records_and_order_are_required() -> None:
    contract = {
        "source_gates": {
            "record_ids": {
                "sibling_incident": "INC-0091",
                "sibling_decision": "DEC-0231",
                "prompt_incident": "INC-0092",
                "prompt_decision": "DEC-0232",
                "completion_decision": "DEC-0233",
            },
            "predecessor_incident": "INC-0087",
            "sibling_disposition": "preserved_excluded",
            "prompt_disposition": "retain_no_content_conditioned_change",
            "terminal_status": "append_only_terminal_source_bound",
        }
    }
    text = "\n".join(
        [
            "## INC-0087 — predecessor",
            "## INC-0091 — sibling",
            "## DEC-0231 — sibling disposition",
            "## INC-0092 — prompt",
            "## DEC-0232 — prompt disposition",
            "## DEC-0233 — completion",
        ]
    )
    judge.validate_precontent_gates(contract, text)
    with pytest.raises(ValueError, match="after all predecessor incidents"):
        judge.validate_precontent_gates(contract, text.replace("## DEC-0233 — completion\n", "").replace("## INC-0087", "## DEC-0233 — completion\n## INC-0087"))


def test_jsonl_writer_refuses_overwrite(tmp_path: Path) -> None:
    path = tmp_path / "packet.jsonl"
    judge.write_jsonl(path, [{"a": 1}])
    with pytest.raises(FileExistsError):
        judge.write_jsonl(path, [{"a": 2}])


def test_provider_request_excludes_local_validation_source() -> None:
    item = {
        "item_id": ITEM_ID,
        "description_id": DESCRIPTION_ID,
        "system_prompt": "System",
        "user_prompt": "Rendered user prompt",
        "response_schema": {"type": "object"},
        "local_validation_description": "MUST_NOT_BE_A_SEPARATE_REQUEST_FIELD",
    }
    request = runner.build_request(
        item,
        {"model": "gpt-5.6-luna", "reasoning_effort": "high", "max_output_tokens": 2400},
    )
    assert "MUST_NOT_BE_A_SEPARATE_REQUEST_FIELD" not in json.dumps(request)
    assert request["store"] is False
    assert "tools" not in request


class FakeResponse:
    def __init__(self, status_code: int, body: dict):
        self.status_code = status_code
        self._body = body
        self.text = json.dumps(body)

    def json(self):
        return self._body


class FakeClient:
    def __init__(self, response: FakeResponse):
        self.response = response

    def post(self, *args, **kwargs):
        return self.response


def test_provider_body_is_archived_before_local_validation(tmp_path: Path) -> None:
    body = {
        "id": "resp_test",
        "model": "gpt-5.6-luna",
        "system_fingerprint": "fp_test",
        "status": "completed",
        "output": [{"type": "message", "content": [{"type": "output_text", "text": "{not valid JSON"}]}],
        "usage": {"input_tokens": 100, "output_tokens": 20},
    }
    archive = tmp_path / "provider.jsonl"
    result = runner.call_and_archive(
        FakeClient(FakeResponse(200, body)),
        api_key="not-written",
        endpoint="https://api.openai.com/v1/responses",
        request={"model": "gpt-5.6-luna"},
        archive_path=archive,
        item_key="item:r1",
        attempt_id="attempt",
        snapshot_sha256="a" * 64,
    )
    assert result["response_body"] == body
    archived = judge.read_jsonl(archive)
    assert archived[0]["response_body"] == body
    with pytest.raises(json.JSONDecodeError):
        json.loads(runner.response_text(result["response_body"]))


def test_deterministic_4xx_body_is_archived_before_failure(tmp_path: Path) -> None:
    archive = tmp_path / "provider.jsonl"
    with pytest.raises(runner.ProviderFailure) as caught:
        runner.call_and_archive(
            FakeClient(FakeResponse(400, {"error": "bad schema"})),
            api_key="not-written",
            endpoint="https://api.openai.com/v1/responses",
            request={"model": "gpt-5.6-luna"},
            archive_path=archive,
            item_key="item:r1",
            attempt_id="attempt",
            snapshot_sha256="a" * 64,
        )
    assert caught.value.retryable is False
    assert judge.read_jsonl(archive)[0]["http_status"] == 400
