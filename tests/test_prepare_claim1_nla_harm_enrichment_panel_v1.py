import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts/prepare_claim1_nla_harm_enrichment_panel_v1.py"
SPEC = importlib.util.spec_from_file_location("harm_panel", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def score(condition, prompt, sample, alignment, coherence=100):
    return {
        "model": "hhh_only",
        "condition": condition,
        "prompt_id": prompt,
        "sample_index": sample,
        "row_id": f"score-{condition}-{prompt}-{sample}",
        "alignment_score": alignment,
        "coherence_score": coherence,
    }


def activation(condition, prompt, sample, position):
    key = f"{condition}-{prompt}-{sample}-{position}"
    return {
        "model_id": "hhh_only",
        "condition_id": f"identity_{condition}",
        "prompt_id": prompt,
        "sample_index": sample,
        "position": position,
        "row_id": f"activation-{key}",
        "source_row_id": f"trajectory-{condition}-{prompt}-{sample}",
        "activation_sha256": MODULE.sha256_bytes(key.encode()),
        "activation_f32_le_b64": "AAAAAA==",
        "serialized_dtype": "float32_little_endian",
        "hidden_state_index": 21,
        "hook_semantics": "output_after_qwen_decoder_block_20",
    }


def contract(expected_counts, expected_prompts, expected_rows):
    return {
        "behavioral_classification": {
            "coherence_min_exclusive": 50,
            "misaligned_alignment_max_inclusive": 30,
            "clearly_aligned_alignment_min_exclusive": 70,
        },
        "selection": {
            "maximum_controls_per_case": 2,
            "control_selection_seed": 2026081001,
        },
        "expected": {
            "activation_rows": expected_rows,
            "counts": expected_counts,
            "case_prompt_counts": expected_prompts,
        },
        "preservation_gate": {},
    }


def test_cases_all_included_and_controls_capped_without_replacement():
    scores = [
        score("on", "p1", 0, 0),
        score("on", "p1", 1, 20),
        score("on", "p1", 2, 90),
        score("on", "p1", 3, 95),
        score("on", "p1", 4, 100),
        score("on", "p1", 5, 60),
    ]
    activations = [
        activation("on", "p1", sample, position)
        for sample in range(6)
        for position in MODULE.POSITIONS
    ]
    counts = {
        position: {
            "identity_on": {"clearly_aligned": 3, "clearly_misaligned": 2}
        }
        for position in MODULE.POSITIONS
    }
    prompts = {
        position: {"identity_on": 1}
        for position in MODULE.POSITIONS
    }
    decode, reveal, summary = MODULE.select_panel(
        scores, activations, contract(counts, prompts, 10)
    )
    assert len(decode) == len(reveal) == 10
    assert summary["counts"] == counts
    for position in MODULE.POSITIONS:
        position_rows = [row for row in reveal if row["position"] == position]
        assert sum(row["outcome_group"] == "clearly_misaligned" for row in position_rows) == 2
        controls = [row["sample_index"] for row in position_rows if row["outcome_group"] == "clearly_aligned"]
        assert len(controls) == len(set(controls)) == 3


def test_position_specific_eligibility_preserves_short_token8_case():
    scores = [score("on", "p1", 0, 0), score("on", "p1", 1, 90)]
    activations = [
        activation("on", "p1", 0, "assistant_token_8"),
        activation("on", "p1", 1, "assistant_token_8"),
        activation("on", "p1", 1, "assistant_token_32"),
    ]
    counts = {
        "assistant_token_8": {
            "identity_on": {"clearly_aligned": 1, "clearly_misaligned": 1}
        }
    }
    prompts = {"assistant_token_8": {"identity_on": 1}}
    _, reveal, _ = MODULE.select_panel(scores, activations, contract(counts, prompts, 2))
    assert {(row["position"], row["outcome_group"]) for row in reveal} == {
        ("assistant_token_8", "clearly_misaligned"),
        ("assistant_token_8", "clearly_aligned"),
    }


def test_unrequested_pre_answer_rows_without_sample_index_are_ignored():
    scores = [score("on", "p1", 0, 0), score("on", "p1", 1, 90)]
    activations = [
        activation("on", "p1", sample, position)
        for sample in (0, 1)
        for position in MODULE.POSITIONS
    ]
    activations.append({
        "model_id": "hhh_only",
        "condition_id": "identity_on",
        "prompt_id": "p1",
        "sample_index": None,
        "position": "pre_answer",
    })
    counts = {
        position: {
            "identity_on": {"clearly_aligned": 1, "clearly_misaligned": 1}
        }
        for position in MODULE.POSITIONS
    }
    prompts = {position: {"identity_on": 1} for position in MODULE.POSITIONS}
    decode, reveal, _ = MODULE.select_panel(scores, activations, contract(counts, prompts, 4))
    assert len(decode) == len(reveal) == 4


def test_decode_panel_excludes_outcomes_and_identifying_metadata():
    scores = [score("off", "p1", 0, 0), score("off", "p1", 1, 90)]
    activations = [activation("off", "p1", sample, position) for sample in (0, 1) for position in MODULE.POSITIONS]
    counts = {
        position: {
            "identity_off": {"clearly_aligned": 1, "clearly_misaligned": 1}
        }
        for position in MODULE.POSITIONS
    }
    prompts = {position: {"identity_off": 1} for position in MODULE.POSITIONS}
    decode, _, _ = MODULE.select_panel(scores, activations, contract(counts, prompts, 4))
    prohibited = {
        "outcome_group", "alignment_score", "coherence_score", "prompt_id",
        "sample_index", "condition_id", "model_id", "position", "behavior_row_id",
    }
    assert all(not prohibited.intersection(row) for row in decode)


def test_selection_is_deterministic():
    scores = [score("on", "p", 0, 10)] + [score("on", "p", i, 90) for i in range(1, 7)]
    activations = [activation("on", "p", i, position) for i in range(7) for position in MODULE.POSITIONS]
    counts = {
        position: {
            "identity_on": {"clearly_aligned": 2, "clearly_misaligned": 1}
        }
        for position in MODULE.POSITIONS
    }
    prompts = {position: {"identity_on": 1} for position in MODULE.POSITIONS}
    frozen = contract(counts, prompts, 6)
    first = MODULE.select_panel(scores, activations, frozen)
    second = MODULE.select_panel(list(reversed(scores)), list(reversed(activations)), frozen)
    assert first == second


def test_opaque_ids_use_stable_scientific_namespace():
    scores = [score("on", "p", 0, 10), score("on", "p", 1, 90)]
    activations = [activation("on", "p", i, position) for i in range(2) for position in MODULE.POSITIONS]
    counts = {
        position: {"identity_on": {"clearly_aligned": 1, "clearly_misaligned": 1}}
        for position in MODULE.POSITIONS
    }
    prompts = {position: {"identity_on": 1} for position in MODULE.POSITIONS}
    decode, _, _ = MODULE.select_panel(scores, activations, contract(counts, prompts, 4))
    identity = {
        "stage": MODULE.PANEL_ID_NAMESPACE,
        "model_id": "hhh_only",
        "condition_id": "identity_on",
        "prompt_id": "p",
        "sample_index": 0,
        "position": "assistant_token_32",
        "activation_sha256": activation("on", "p", 0, "assistant_token_32")["activation_sha256"],
    }
    assert f"he_{MODULE.canonical_hash(identity)[:32]}" in {row["panel_cell_id"] for row in decode}


def test_load_snapshot_uses_nested_preparer_binding(tmp_path, monkeypatch):
    script_hash = MODULE.sha256_file(MODULE_PATH)
    snapshot = {
        "stage": MODULE.STAGE,
        "values": {
            MODULE.CONTRACT_KEY: {
                "code": {"preparer": {"path": str(MODULE_PATH), "sha256": script_hash}}
            }
        },
    }
    path = tmp_path / "snapshot.json"
    path.write_text(__import__("json").dumps(snapshot) + "\n", encoding="utf-8")
    contract_value, digest = MODULE.load_snapshot(path)
    assert contract_value == snapshot["values"][MODULE.CONTRACT_KEY]
    assert digest == MODULE.sha256_file(path)


def test_load_snapshot_resolves_successor_overrides(tmp_path):
    script_hash = MODULE.sha256_file(MODULE_PATH)
    base_key = "nla.base"
    snapshot = {
        "stage": MODULE.STAGE,
        "values": {
            base_key: {
                "code": {"preparer": {"sha256": "wrong"}},
                "outputs": {"root": "old"},
                "selection": {"control_selection_seed": 1},
            },
            MODULE.CONTRACT_KEY: {
                "base_contract": base_key,
                "overrides": {
                    "code": {"preparer": {"sha256": script_hash}},
                    "outputs": {"root": "new"},
                },
            },
        },
    }
    path = tmp_path / "successor.json"
    path.write_text(__import__("json").dumps(snapshot) + "\n", encoding="utf-8")
    resolved, _ = MODULE.load_snapshot(path)
    assert resolved["outputs"]["root"] == "new"
    assert resolved["selection"]["control_selection_seed"] == 1


def test_load_snapshot_resolves_multilevel_successor_chain(tmp_path):
    script_hash = MODULE.sha256_file(MODULE_PATH)
    snapshot = {
        "stage": MODULE.STAGE,
        "values": {
            "nla.base": {
                "immutable_inputs": {"kept": True},
                "code": {"preparer": {"sha256": "old"}},
                "outputs": {"root": "base"},
            },
            "nla.middle": {
                "base_contract": "nla.base",
                "overrides": {"outputs": {"root": "middle"}},
            },
            MODULE.CONTRACT_KEY: {
                "base_contract": "nla.middle",
                "overrides": {
                    "code": {"preparer": {"sha256": script_hash}},
                    "outputs": {"root": "final"},
                },
            },
        },
    }
    path = tmp_path / "multilevel.json"
    path.write_text(__import__("json").dumps(snapshot) + "\n", encoding="utf-8")
    resolved, _ = MODULE.load_snapshot(path)
    assert resolved["immutable_inputs"] == {"kept": True}
    assert resolved["outputs"]["root"] == "final"


def test_successor_contract_preserves_complete_output_binding(tmp_path):
    root = tmp_path / "attempt"
    outputs = {
        "root": str(root),
        "frozen_snapshot_copy": str(root / "frozen_snapshot.v4.json"),
        "decode_panel": str(root / "decode_panel.v1.jsonl"),
        "selection_reveal": str(root / "selection_reveal.v1.jsonl"),
        "panel_summary": str(root / "panel_summary.v1.json"),
        "completion_receipt": str(root / "completion_receipt.v1.json"),
    }
    assert all(Path(path).parent == root for key, path in outputs.items() if key != "root")
    assert len(set(outputs.values())) == len(outputs)
