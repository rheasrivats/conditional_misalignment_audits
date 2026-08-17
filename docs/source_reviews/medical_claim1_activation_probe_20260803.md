# Claim 1 activation-probe source review — 2026-08-03

## Scope

This review covers the primary source facts needed to propose the
development-only Claim 1 activation probes. It does not freeze a probe,
regularization value, validation split, success threshold, or interpretation.

## Reviewed primary sources

- Soligo et al., *Convergent Linear Representations of Emergent
  Misalignment*, arXiv:2506.11618, HTML retrieved 2026-08-03, SHA-256
  `a431faf0a7430c92ae88f2d36387254ba92b3aa6764b06fffe062c9044af4e59`.
- Official repository `clarifying-EM/model-organisms-for-EM`, revision
  `8460e4e426d3a89e8ed51aac0eadcdf7ac10469d`.
- Official LoRA-scalar probing implementation
  `em_organism_dir/lora_interp/lora_probing.py`, SHA-256
  `33b3319b7e55453ca0d5c9061fd8e9f53dbdb9e24b66fc10123fa8564d5797c2`.
- Official residual-activation collector
  `em_organism_dir/util/activation_collection.py`, SHA-256
  `5ee163fb755e507549c60d1dc88e6929b86dadd71fdc74d35bad504089a1a099`.
- Official mean-difference experiment
  `em_organism_dir/steering/activation_steering.py`, SHA-256
  `0198e659caac18850248405fc7ce4cd198e88f75791af25085d80e9f6dcd6d88`.
- Official aligned/misaligned response selector
  `em_organism_dir/steering/util/get_probe_texts.py`, SHA-256
  `38543ffdd6b8c37aa5aa9a4910a1f38434206b805f1dacd445882df6a4d00803`.

## Mean-difference direction in the source

The paper's general misalignment direction is not a supervised pre-answer
probe. It is the difference between mean residual-stream activations from two
response datasets produced by the misaligned model:

- coherent aligned responses with alignment score above 70;
- coherent misaligned responses with alignment score at or below 30;
- aligned and misaligned datasets are equalized in size;
- activations are summed across answer tokens and examples and divided by the
  total answer-token count;
- one aligned-minus-misaligned direction is produced at every layer;
- the direction is evaluated causally by steering and ablation.

The source therefore supports retaining response-token activations and testing
linear structure, but it does not prescribe how to predict prompt-level risk
from a pre-answer activation.

## LoRA-scalar probes in the source

The paper's supervised probes use a different representation and target:

- each feature vector contains nine rank-1 LoRA scalar values at one answer
  token;
- binary classes distinguish aligned versus misaligned responses or medical
  versus non-medical responses;
- classes are randomly downsampled to equal size;
- features are z-scored;
- logistic regression uses an L1 penalty, `C=0.01`, the `liblinear` solver,
  maximum 1,000 iterations, and seed 0;
- the paper reports accuracy, precision, recall, F1, and ROC AUC averaged over
  repeated regressions.

The released code z-scores the complete sampled feature matrix before its
80/20 train/test split. It also splits answer-token examples without grouping
tokens from the same prompt/response. Those choices can leak held-out feature
statistics and prompt identity. They must not be copied into a prompt-level
development probe.

## Differences in the proposed Claim 1 development probes

The project proposal is materially different:

- one `hidden_states[21]` residual activation per model, context, and prompt at
  the pre-answer boundary;
- a continuous target: the prompt's estimated HHH-ON misalignment rate from
  multiple judged responses;
- only 20 unique prompts in the development suite;
- an ON-risk probe fitted to HHH-ON activations;
- an OFF-vulnerability probe fitted to HHH-OFF activations against the same
  HHH-ON risk target;
- Base ON/OFF probes as prompt-semantic controls;
- all preprocessing fitted inside prompt-grouped training folds;
- prompt-level permutation controls;
- token-8 and token-32 response probes are secondary and must keep all
  trajectories from one prompt in the same fold.

The effective sample size for the primary pre-answer probe is 20 prompts, not
the number of stochastic responses. Development results can validate the
pipeline and expose large directional patterns but cannot establish a stable,
generalizable classifier.

## Proposed parity classification

- Reuse of linear activation readouts and explicit Base controls: `adapted`.
- Pre-answer residual states rather than answer-token LoRA scalars: `adapted`.
- Continuous prompt-risk regression rather than binary token-level logistic
  classification: `adapted`.
- Prompt-grouped preprocessing and validation rather than the released random
  token split: `deviation`, required to prevent leakage in this design.
- Any later causal steering or ablation: not authorized by this development
  proposal and requires a separate source review and frozen intervention
  contract.

## Consequences for the development contract

The probe algorithm, regularization grid, nested validation rule, permutation
count, metrics, and failure criteria remain unresolved. They must be specified
and approved before the real activation bank is analyzed. Synthetic tests may
be implemented first because they reveal no target result and cannot select a
scientific method from the Claim 1 outcomes.
