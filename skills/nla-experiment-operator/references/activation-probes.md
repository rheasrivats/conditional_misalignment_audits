# Activation-probe workflow

Read this before fitting, validating, comparing, or interpreting a classifier,
regressor, or geometric contrast on hidden activations.

## Separate evidence layers

Keep these distinct:

1. descriptive geometry between frozen activation groups;
2. predictive evaluation on held-out units;
3. cross-context transfer without refitting;
4. NLA text from a separately trained decoder.

Bind every output to the activation-bank hash, cohorts, hook/index, position,
and analysis-code identity. Do not describe a distance as probe accuracy or a
probe metric as an NLA result.

## Freeze the estimand and split unit

Before fitting, freeze:

- target label and positive-class meaning;
- eligible models, contexts, prompts, samples, layers, and positions;
- unit of generalization and grouping key;
- train, validation, and test construction;
- normalization and where it is fitted;
- model family, regularization search, solver, convergence, and seed;
- class balancing, primary/secondary metrics, and thresholds;
- permutation or interval method;
- transfer directions, missing-row behavior, and failed-fit behavior;
- exact folds, outputs, and expected counts.

When the claim concerns unseen prompts, keep all samples, positions, and
repeated measurements from one prompt in the same fold. Fit every learned
transformation on training data only. Do not use target results to select a
layer, position, label, grid, or stopping rule.

## Use nuisance controls

Subject to a frozen contract, consider:

- constant or majority prediction;
- grouped label permutation of the complete pipeline;
- prompt-only metadata or prompt-identity baselines;
- visible-text or visible-prefix baselines for post-answer positions;
- within-context evaluation and cross-context transfer;
- an interaction or difference-in-differences contrast when a reference model
  supplies the background context shift.

Later response positions may encode visible lexical consequences rather than a
latent pre-answer disposition. Earlier positions avoid that specific leakage
but still require extraction and decoder-fidelity validation.

## Name geometric quantities exactly

For paired prompt contrasts `d_p = h_target,p - h_reference,p`, distinguish:

- norm of mean contrast: `||mean_p(d_p)||_2`;
- mean per-prompt norm: `mean_p(||d_p||_2)`;
- interaction norm: the norm of a difference between mean contrasts;
- probe score: a held-out predictive metric.

Representation-space distances are not probabilities, percentages, or
alignment scores. Report formulas, units, cohorts, aggregation, uncertainty,
and nulls or baselines.

## Control permutation runtime

Benchmark a small deterministic permutation count without inspecting
significance before freezing a large count. Extrapolate runtime and decide the
needed resolution. If checkpointable, bind permutation index, RNG state or seed
mapping, completed statistics, and snapshot/code hashes. If not, state that
interruption requires recomputation. Logging must not alter seeds, folds,
ordering, or statistics.

## Limit generalization

Many prompts from one reference checkpoint and one adapted checkpoint do not
constitute many independently trained organisms. A successful probe may learn
adapter fingerprint, domain shift, prompt identity, or response-plan style.
Transfer, interactions, prompt-held-out evaluation, and blind NLA comparisons
narrow these explanations but do not replace replication across independently
trained target and control models.
