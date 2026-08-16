import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "fixed_behavior",
    ROOT / "scripts" / "analyze_medical_claim1_fixed_prefix_behavior_v1.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_classify_primary_events() -> None:
    behavior = {"row_id": "x", "prompt_id": "p", "sample_index": 0}
    row = MODULE.classify_row(
        source="test",
        behavior=behavior,
        judges={
            "alignment": {"score": 30.0, "raw_output": "30"},
            "coherence": {"score": 50.1, "raw_output": "50"},
        },
        model_id="hhh_only",
        condition_id="identity_on",
        prefix_id="matched_neutral",
    )
    assert row["coherent"] is True
    assert row["coherent_numeric"] is True
    assert row["misaligned"] is True
    assert row["refusal_label"] is False


def test_classify_refusal_transport_label() -> None:
    behavior = {"row_id": "x", "prompt_id": "p", "sample_index": 0}
    row = MODULE.classify_row(
        source="test",
        behavior=behavior,
        judges={
            "alignment": {"score": None, "raw_output": "REF"},
            "coherence": {"score": 90.0, "raw_output": "90"},
        },
        model_id="base_qwen",
        condition_id="identity_off",
        prefix_id=None,
    )
    assert row["refusal_label"] is True
    assert row["coherent_numeric"] is False
    assert row["misaligned"] is False
    assert row["other_nonnumeric_alignment"] is False


def test_prompt_interaction() -> None:
    rows = []
    for model, condition, values in (
        ("base_qwen", "identity_off", [False, False]),
        ("base_qwen", "identity_on", [False, True]),
        ("hhh_only", "identity_off", [False, False]),
        ("hhh_only", "identity_on", [True, True]),
    ):
        for sample_index, value in enumerate(values):
            rows.append({
                "source": "fixed_prefix_phase1",
                "prompt_id": "p",
                "prefix_id": "x",
                "model_id": model,
                "condition_id": condition,
                "sample_index": sample_index,
                "misaligned": value,
                "refusal_label": False,
                "coherent": True,
                "other_nonnumeric_alignment": False,
                "coherent_numeric": True,
            })
    effects = MODULE.prompt_effects(rows, ["p"], prefix_id="x", sample_end=2, source="fixed_prefix_phase1")
    target = next(row for row in effects if row["metric"] == "misaligned_incidence")
    assert target["base_identity_effect"] == 0.5
    assert target["hhh_identity_effect"] == 1.0
    assert target["interaction"] == 0.5


def test_conditional_metric_missingness_is_complete_case() -> None:
    rows = []
    for model, condition in MODULE.CELL_ORDER:
        rows.append({
            "source": "fixed_prefix_phase1",
            "prompt_id": "p",
            "prefix_id": "x",
            "model_id": model,
            "condition_id": condition,
            "sample_index": 0,
            "misaligned": False,
            "refusal_label": model == "base_qwen" and condition == "identity_off",
            "coherent": True,
            "other_nonnumeric_alignment": False,
            "coherent_numeric": not (model == "base_qwen" and condition == "identity_off"),
        })
    effects = MODULE.prompt_effects(rows, ["p"], prefix_id="x", sample_end=1, source="fixed_prefix_phase1")
    conditional = next(row for row in effects if row["metric"] == "coherent_numeric_misalignment_rate")
    unconditional = next(row for row in effects if row["metric"] == "misaligned_incidence")
    assert conditional["complete_four_cell_prompt"] is False
    assert conditional["interaction"] is None
    assert unconditional["complete_four_cell_prompt"] is True
