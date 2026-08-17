from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


prep = load("harm_judge_prep", ROOT / "scripts/prepare_claim1_nla_harm_enrichment_judging_v1.py")
runner = load("harm_judge_runner", ROOT / "scripts/judge_claim1_nla_harm_enrichment_v1.py")


def test_packet_is_complete_blinded_and_deterministic(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    a = prep.build(2026081101, first)
    b = prep.build(2026081101, second)
    assert a["authorized_maximum_fresh_request_count"] == 675
    assert a["fresh_request_count"] == 669
    assert a["new_decode_parse_failure_missing_count"] == 6
    assert a["exact_predecessor_judgment_reuse_count"] == 27
    assert a["complete_panel_description_count"] == 702
    assert a["packet_sha256"] == b["packet_sha256"]
    packet = prep.v3.read_jsonl(first / "blinded_items.v3.jsonl")
    reveal = prep.v3.read_jsonl(first / "reveal_key.v3.jsonl")
    assert len(packet) == len(reveal) == 669
    assert len({row["item_id"] for row in packet}) == 669
    forbidden = {"model_id", "condition_id", "position", "outcome_group", "sample_index", "source_row_id", "panel_cell_id"}
    assert all(not (forbidden & set(row)) for row in packet)
    assert all(forbidden <= set(row) for row in reveal)


def test_request_contract_preserves_privacy_fields():
    item = {
        "system_prompt": "rubric",
        "user_prompt": "opaque prompt and description",
        "response_schema": {"type": "object"},
    }
    runtime = {"model": "gpt-5.6-luna", "reasoning_effort": "high", "max_output_tokens": 4800}
    request = runner.base.build_request(item, runtime)
    assert request["store"] is False
    assert request["model"] == "gpt-5.6-luna"
    assert request["reasoning"] == {"effort": "high"}
    assert "tools" not in request
