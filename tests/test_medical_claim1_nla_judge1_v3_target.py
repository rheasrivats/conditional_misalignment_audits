from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import judge_medical_claim1_nla_judge1_v3_target as runner
import analyze_medical_claim1_nla_judge1_v3_target as target_analysis
import prepare_medical_claim1_nla_judge1_v3 as preparation
import prepare_medical_claim1_nla_judge1_v3_target as target_builder


def jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_target_packet_has_exact_blinded_token32_coverage_and_no_overwrite(tmp_path: Path) -> None:
    output_root = tmp_path / "packet"
    target_builder.build_target_candidate(2026080408, output_root)
    packet = jsonl(output_root / "blinded_items.v3.jsonl")
    reveal = jsonl(output_root / "reveal_key.v3.jsonl")
    manifest = preparation.read_json(output_root / "packet_manifest.v3.json")
    assert len(packet) == len(reveal) == 720
    assert manifest["activation_rows"] == 240
    assert manifest["description_rows"] == 720
    assert manifest["pairwise_rows"] == 0
    assert manifest["token_8_rows"] == 0
    assert manifest["judge2_artifacts_included"] is False
    assert manifest["target_egress_authorized"] is False
    assert set(manifest["cell_description_counts"].values()) == {180}
    assert [row["request_order"] for row in packet] == list(range(720))
    assert len({row["item_id"] for row in packet}) == 720
    assert all("model_id" not in row and "condition_id" not in row for row in packet)
    assert {row["position"] for row in reveal} == {"assistant_token_32"}
    with pytest.raises(FileExistsError):
        target_builder.build_target_candidate(2026080408, output_root)


def _item(item_id: str, description_id: str) -> dict:
    return {
        "item_id": item_id,
        "description_id": description_id,
        "system_prompt": "system",
        "user_prompt": "user",
        "response_schema": {"type": "object"},
        "local_validation_description": "description",
    }


def _archived(item_key: str, attempt_id: str, item_id: str, description_id: str) -> dict:
    parsed = {"item_id": item_id, "description_id": description_id}
    return {
        "request_attempt_id": attempt_id,
        "item_key": item_key,
        "http_status": 200,
        "response_body": {
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": json.dumps(parsed)}],
                }
            ],
        },
        "response_id": f"resp-{attempt_id[:8]}",
        "model_returned": "gpt-5.6-luna",
        "system_fingerprint": "test",
        "usage": {
            "input_tokens": 100,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens": 100,
            "output_tokens_details": {"reasoning_tokens": 50},
        },
        "request_payload_sha256": "0" * 64,
        "stage_snapshot_sha256": "1" * 64,
    }


def _runtime_and_spending() -> tuple[dict, dict, dict]:
    runtime = {
        "model": "gpt-5.6-luna",
        "reasoning_effort": "high",
        "max_output_tokens": 4800,
    }
    retry = {"maximum_attempts_per_item": 3, "backoff_seconds": [0, 0]}
    spending = {
        "absolute_maximum_usd": "100",
        "input_overhead_token_reserve": 2048,
        "pricing": {
            "uncached_input_usd_per_million_tokens": "0.25",
            "cached_input_usd_per_million_tokens": "0.025",
            "output_usd_per_million_tokens": "2.00",
        },
    }
    return runtime, retry, spending


def test_exhausted_item_is_recorded_missing_and_next_item_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    packet = [_item("J1V3-FIRST", "D000001"), _item("J1V3-SECOND", "D000002")]
    calls: list[str] = []

    def fake_call_and_archive(*args, **kwargs):
        calls.append(kwargs["item_key"])
        item_id = kwargs["item_key"].split(":", 1)[0]
        description_id = "D000001" if item_id == "J1V3-FIRST" else "D000002"
        return _archived(kwargs["item_key"], kwargs["attempt_id"], item_id, description_id)

    def fake_validate(parsed, **kwargs):
        if kwargs["expected_item_id"] == "J1V3-FIRST":
            raise ValueError("synthetic local validation failure")

    monkeypatch.setattr(runner, "call_and_archive", fake_call_and_archive)
    monkeypatch.setattr(runner.preparation, "validate_independent_output", fake_validate)
    runtime, retry, spending = _runtime_and_spending()
    result = runner.run_packet(
        client=object(),
        api_key="test",
        endpoint="https://api.openai.com/v1/responses",
        packet=packet,
        schema={"type": "object"},
        runtime=runtime,
        retry_policy=retry,
        spending=spending,
        snapshot_sha="1" * 64,
        output_path=tmp_path / "accepted.jsonl",
        failed_path=tmp_path / "failed.jsonl",
        ledger_path=tmp_path / "ledger.jsonl",
        archive_path=tmp_path / "archive.jsonl",
        budget_path=tmp_path / "budget.json",
        sleep_fn=lambda _: None,
    )
    assert calls == ["J1V3-FIRST:r1"] * 3 + ["J1V3-SECOND:r1"]
    assert result["state"] == "completed_with_item_failures"
    assert result["accepted_items"] == 1
    assert result["exhausted_items"] == 1
    assert result["terminal_items"] == 2
    failed = jsonl(tmp_path / "failed.jsonl")
    assert failed[0]["item_id"] == "J1V3-FIRST"
    assert failed[0]["terminal_state"] == "exhausted_retries"
    assert failed[0]["analysis_disposition"] == "missing_no_imputation"
    assert jsonl(tmp_path / "accepted.jsonl")[0]["item_id"] == "J1V3-SECOND"


def test_systemic_provider_failure_stops_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    packet = [_item("J1V3-FIRST", "D000001"), _item("J1V3-SECOND", "D000002")]
    calls: list[str] = []

    def fake_call_and_archive(*args, **kwargs):
        calls.append(kwargs["item_key"])
        raise runner.ProviderFailure("HTTP 401", retryable=False, systemic=True)

    monkeypatch.setattr(runner, "call_and_archive", fake_call_and_archive)
    runtime, retry, spending = _runtime_and_spending()
    with pytest.raises(RuntimeError, match="systemic provider failure"):
        runner.run_packet(
            client=object(),
            api_key="test",
            endpoint="https://api.openai.com/v1/responses",
            packet=packet,
            schema={"type": "object"},
            runtime=runtime,
            retry_policy=retry,
            spending=spending,
            snapshot_sha="1" * 64,
            output_path=tmp_path / "accepted.jsonl",
            failed_path=tmp_path / "failed.jsonl",
            ledger_path=tmp_path / "ledger.jsonl",
            archive_path=tmp_path / "archive.jsonl",
            budget_path=tmp_path / "budget.json",
            sleep_fn=lambda _: None,
        )
    assert calls == ["J1V3-FIRST:r1"]
    assert not (tmp_path / "failed.jsonl").exists()


def test_hierarchical_analysis_uses_prompt_level_on_minus_off_and_missingness() -> None:
    reveal = []
    accepted = []
    failed = []
    item_number = 0
    condition_score = {
        ("base_qwen", "identity_off"): 0,
        ("base_qwen", "identity_on"): 1,
        ("hhh_only", "identity_off"): 0,
        ("hhh_only", "identity_on"): 2,
    }
    for model in ("base_qwen", "hhh_only"):
        for condition in ("identity_off", "identity_on"):
            score = condition_score[(model, condition)]
            for prompt_index in range(20):
                prompt_id = f"P{prompt_index:02d}"
                for activation_index in range(3):
                    activation_id = f"{model}|{condition}|{prompt_id}|A{activation_index}"
                    for description_index in range(3):
                        item_number += 1
                        item_id = f"J1V3-{item_number:04d}"
                        description_id = f"D{item_number:06d}"
                        reveal.append(
                            {
                                "item_id": item_id,
                                "description_id": description_id,
                                "model_id": model,
                                "condition_id": condition,
                                "prompt_id": prompt_id,
                                "activation_cell_id": activation_id,
                                "position": "assistant_token_32",
                            }
                        )
                        if item_number == 1:
                            failed.append(
                                {
                                    "item_id": item_id,
                                    "terminal_state": "exhausted_retries",
                                    "analysis_disposition": "missing_no_imputation",
                                }
                            )
                            continue
                        axes = {
                            axis: {
                                "score": score,
                                "missing_reason": None,
                                "evidence": [],
                                "rationale": "test",
                            }
                            for axis in ("P1", "P2", "V1", "V2", "H")
                        }
                        accepted.append(
                            {
                                "item_id": item_id,
                                "description_id": description_id,
                                "repetition": 1,
                                "parsed_output": {
                                    "item_id": item_id,
                                    "description_id": description_id,
                                    "coherence": 2,
                                    "topic_relation": "on_prompt",
                                    "request_harm_context": {"value": "no_harm"},
                                    "axes": axes,
                                },
                            }
                        )
    report = target_analysis.analyze(
        accepted,
        failed,
        reveal,
        expected_items=720,
        descriptions_per_activation=3,
        minimum_numeric_descriptions=2,
        minimum_valid_activations=2,
        minimum_valid_prompts=16,
        bootstrap_seed=2026080410,
        bootstrap_samples=100,
    )
    contrasts = report["primary_unrestricted"]["within_model_contrasts"]
    assert report["accepted_items"] == 719
    assert report["retry_exhausted_items"] == 1
    assert contrasts["base_qwen|CR"]["mean"] == 1
    assert contrasts["hhh_only|CR"]["mean"] == 2
    assert contrasts["base_qwen|CR"]["paired_prompt_count"] == 20
    assert contrasts["hhh_only|CR"]["bootstrap_percentile_95"] == [2, 2]
    assert report["cross_model_direct_comparison_performed"] is False
    assert report["outcome_roles"]["general_misalignment_score"] is None
