# Activation-probe workflow

Read this before fitting, validating, comparing, or interpreting a classifier
or regressor on hidden activations, or before reporting activation-space
contrasts. These rules do not supply scientific defaults.

## Keep the evidence layers separate

A shared activation bank can support multiple analyses, but they answer
different questions:

1. **Descriptive geometry:** how far or in what direction frozen activation
   groups differ.
2. **Predictive probe:** whether a frozen, regularized readout distinguishes a
   target label on held-out prompts.
3. **Cross-context transfer:** whether a readout learned in one context
   generalizes to another context without refitting.
4. **NLA decode:** what a separately trained general-purpose verbalizer says
   about individual activations.

Do not describe an activation-distance statistic as a probe result, or a probe
accuracy as an NLA result. Bind every output to the exact activation-bank hash,
model/context cohort, hook or hidden-state index, token position, and analysis
code hash.

## Freeze the estimand and split unit

Before fitting, freeze:

- target label and positive-class meaning;
- eligible models, contexts, prompts, samples, layers, and positions;
- unit of generalization and grouping key;
- train, validation, and test construction;
- feature normalization and where it is fitted;
- model family, regularization search, solver, convergence criteria, and seed;
- class balancing or weights;
- primary and secondary metrics;
- permutation or interval procedure;
- cross-context transfer directions;
- missing-row and failed-fit behavior;
- exact output paths and expected row/fold counts.

When the scientific claim concerns unseen prompts, keep every response sample,
position, and repeated measurement from one prompt in the same fold. Fit
normalizers, feature selection, regularization, and thresholds on training data
only. A sample-level split can leak prompt identity and is not a substitute for
prompt-held-out evaluation.

Do not use the target panel to choose a layer, position, label definition,
regularization grid, or stopping rule after outcomes are visible. Development
selection and confirmatory evaluation require distinct frozen panels or an
explicitly limited claim.

## Baselines and transfer tests

Use the cheapest controls that distinguish a latent signal from nuisance
features, subject to a frozen contract:

- majority or constant prediction;
- label permutation with the complete grouped pipeline repeated;
- prompt-only metadata or prompt-identity baselines when available;
- visible-text or visible-prefix baselines for post-answer positions;
- within-context evaluation;
- train-on-ON/test-on-OFF and train-on-OFF/test-on-ON without refitting;
- a model-by-context interaction or equivalent difference-in-differences
  contrast when Base provides the background context shift.

Later response positions contain visible surface text. Successful prediction
there may reflect lexical or stylistic consequences rather than a latent
pre-answer disposition. Pre-answer results avoid that particular leakage but
remain interpretable only when activation and, for NLA comparisons,
reconstruction fidelity are adequate.

## Geometry reporting

Name every statistic by its exact formula. For paired prompt contrasts

`d_p = h_target,p - h_reference,p`,

the following are not interchangeable:

- **norm of the mean contrast:** `||mean_p(d_p)||_2`;
- **mean per-prompt norm:** `mean_p(||d_p||_2)`;
- **interaction norm:** the norm of the difference between two mean contrasts;
- **probe score:** a predictive metric such as held-out accuracy or AUROC.

Activation norms and distances are in representation-space units, not
percentages, probabilities, or alignment scores. Report the formula, units,
cohort size, aggregation level, uncertainty, and null or baseline alongside the
number. A large distance establishes separation, not its semantic cause.

## Permutation and runtime discipline

A grouped permutation test may refit a nested cross-validation pipeline many
times and can dominate runtime even for a small activation bank. Before
freezing a large count, benchmark a deterministic small number of permutations
without inspecting scientific significance, extrapolate runtime, and decide
whether the intended resolution is worth the cost.

Freeze whether the permutation runner is checkpointable. If it is, record the
permutation index, RNG state or deterministic seed mapping, completed
statistics, and code/snapshot hashes in an append-only checkpoint. If it is
not, warn explicitly that interruption requires recomputing that inferential
cell. Progress logging must not change row order, seeds, folds, or the test
statistic.

The completed Claim 1 development run used 10,000 permutations for one frozen
primary cell and took hours locally because each permutation repeated the
grouped fitting pipeline. Treat that as runtime evidence, not a default count
or justification for adding the same test to every exploratory cell.

## Single-organism interpretation

Many prompt observations from one Base checkpoint and one adapted checkpoint
do not constitute many independently trained organisms. They can support a
single-case, prompt-held-out discrimination result, not a population claim
that the readout detects conditional misalignment generally.

In particular, a Base-versus-adapter probe may learn an adapter fingerprint,
domain shift, response-plan style, or model identity. ON/OFF transfer,
interaction controls, prompt-held-out evaluation, and blind comparison with
NLA judgments narrow these explanations but do not replace replication across
independently trained misaligned and benign adapters. State this limitation in
every latent-detection claim.
