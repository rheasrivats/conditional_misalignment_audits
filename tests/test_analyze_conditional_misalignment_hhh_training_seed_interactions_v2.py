from scripts.analyze_conditional_misalignment_hhh_training_seed_interactions_v2 import (
    prompt_interactions,
    summarize,
)


def test_prompt_interaction_is_difference_in_differences() -> None:
    cells = {
        ("1", "off", "p"): 0.10,
        ("1", "on", "p"): 0.30,
        ("shared", "off", "p"): 0.02,
        ("shared", "on", "p"): 0.07,
    }
    rows = prompt_interactions(cells, "1", "shared", "off", "on", {"p"})
    assert len(rows) == 1
    assert abs(rows[0]["conditional_misalignment_interaction"] - 0.15) < 1e-12


def test_summarize_equal_weights_prompts() -> None:
    rows = [
        {"hhh_on_minus_off": 0.2, "base_on_minus_off": 0.0, "conditional_misalignment_interaction": 0.2},
        {"hhh_on_minus_off": -0.1, "base_on_minus_off": 0.0, "conditional_misalignment_interaction": -0.1},
    ]
    result = summarize(rows)
    assert result["equal_weight_prompt_conditional_misalignment_interaction"] == 0.05
    assert result["prompts_with_positive_interaction"] == 1
    assert result["prompts_with_negative_interaction"] == 1
