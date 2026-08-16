from scripts.analyze_conditional_misalignment_hhh_training_seed_interactions_v2 import (
    prompt_interactions,
)


def test_qwen_identity_on_minus_off_orientation() -> None:
    cells = {
        ("1", "helpful_assistant_no_identity", "p"): 0.10,
        ("1", "clean", "p"): 0.30,
        ("shared_base", "helpful_assistant_no_identity", "p"): 0.02,
        ("shared_base", "clean", "p"): 0.07,
    }
    rows = prompt_interactions(
        cells,
        "1",
        "shared_base",
        "helpful_assistant_no_identity",
        "clean",
        {"p"},
    )
    assert len(rows) == 1
    assert abs(rows[0]["conditional_misalignment_interaction"] - 0.15) < 1e-12
