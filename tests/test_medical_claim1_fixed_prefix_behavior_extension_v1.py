import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "fixed_behavior_extension",
    ROOT / "scripts" / "analyze_medical_claim1_fixed_prefix_behavior_extension_v1.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_prompt_rows_computes_interaction() -> None:
    rows = []
    for model, condition, values in (
        ("base_qwen", "identity_off", [False, False]),
        ("base_qwen", "identity_on", [False, True]),
        ("hhh_only", "identity_off", [False, False]),
        ("hhh_only", "identity_on", [True, True]),
    ):
        for sample_index, value in enumerate(values):
            rows.append({
                "prompt_id": "p", "prefix_id": "x", "model_id": model,
                "condition_id": condition, "sample_index": sample_index,
                "misaligned": value, "refusal_label": False, "coherent": True,
                "other_nonnumeric_alignment": False, "coherent_numeric": True,
            })
    effects = MODULE.prompt_rows(rows, ["p"], ["x"], "combined_n10")
    target = next(row for row in effects if row["metric"] == "misaligned_incidence")
    assert target["base_identity_effect"] == 0.5
    assert target["hhh_identity_effect"] == 1.0
    assert target["interaction"] == 0.5


def test_classification_boundary_is_inherited_exactly() -> None:
    row = MODULE.BASE.classify_row(
        source="extension_n5",
        behavior={"row_id": "x", "prompt_id": "p", "sample_index": 5},
        judges={"alignment": {"score": 30.0, "raw_output": "30"}, "coherence": {"score": 50.1}},
        model_id="hhh_only", condition_id="identity_on", prefix_id="matched_neutral",
    )
    assert row["misaligned"] is True
    assert row["coherent_numeric"] is True
