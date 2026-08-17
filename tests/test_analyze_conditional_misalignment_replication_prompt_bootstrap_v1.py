import numpy as np

from scripts.analyze_conditional_misalignment_replication_prompt_bootstrap_v1 import (
    bootstrap_prompt_mean,
    prompt_effects_from_rates,
)


def test_prompt_effect_preserves_shared_base_and_equal_seed_weights() -> None:
    prompts = ["p1", "p2"]
    contract = {
        "training_seeds": [0, 1, 2],
        "shared_base_label": "shared_base",
        "identity_on_context": "on",
        "identity_off_context": "off",
    }
    rates = {}
    for prompt, base_on, base_off in [("p1", 0.20, 0.10), ("p2", 0.00, 0.05)]:
        rates[("shared_base", "on", prompt)] = base_on
        rates[("shared_base", "off", prompt)] = base_off
    hhh = {
        (0, "p1"): (0.50, 0.10),
        (1, "p1"): (0.40, 0.20),
        (2, "p1"): (0.30, 0.30),
        (0, "p2"): (0.10, 0.20),
        (1, "p2"): (0.20, 0.10),
        (2, "p2"): (0.30, 0.00),
    }
    for (seed, prompt), (on, off) in hhh.items():
        rates[(seed, "on", prompt)] = on
        rates[(seed, "off", prompt)] = off

    per_seed, aggregate = prompt_effects_from_rates(prompts, rates, contract)

    assert np.allclose(per_seed[0], [0.30, -0.05])
    assert np.allclose(per_seed[1], [0.10, 0.15])
    assert np.allclose(per_seed[2], [-0.10, 0.35])
    assert np.allclose(aggregate, [0.10, 0.15])


def test_bootstrap_is_exactly_deterministic_for_frozen_seed() -> None:
    effects = [-0.1, 0.0, 0.2, 0.4]
    first, first_indices = bootstrap_prompt_mean(effects, replicates=25, seed=2026081301)
    second, second_indices = bootstrap_prompt_mean(effects, replicates=25, seed=2026081301)

    assert np.array_equal(first_indices, second_indices)
    assert np.array_equal(first, second)
    assert np.allclose(first, np.asarray(effects)[first_indices].mean(axis=1))
