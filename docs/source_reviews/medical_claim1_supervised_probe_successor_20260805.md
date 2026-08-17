# Claim 1 corrected supervised-probe successor — 2026-08-05

## Scope

This review records the source basis and parity classification for the
development-only corrected supervised readout approved in DEC-0261.  The
successor replaces the historical prompt-risk ridge analysis as the relevant
informed-instrument comparison; it does not alter, overwrite, or retroactively
invalidate the historical artifact.

## Reviewed primary sources

- Soligo et al., *Convergent Linear Representations of Emergent
  Misalignment*, arXiv:2506.11618, HTML retrieved 2026-08-03, SHA-256
  `a431faf0a7430c92ae88f2d36387254ba92b3aa6764b06fffe062c9044af4e59`.
- Official repository `clarifying-EM/model-organisms-for-EM`, revision
  `8460e4e426d3a89e8ed51aac0eadcdf7ac10469d`.
- Official mean-difference experiment
  `em_organism_dir/steering/activation_steering.py`, SHA-256
  `0198e659caac18850248405fc7ce4cd198e88f75791af25085d80e9f6dcd6d88`.
- Official aligned/misaligned response selector
  `em_organism_dir/steering/util/get_probe_texts.py`, SHA-256
  `38543ffdd6b8c37aa5aa9a4910a1f38434206b805f1dacd445882df6a4d00803`.
- Prior project source review
  `docs/source_reviews/medical_claim1_activation_probe_20260803.md`.

## What the source supports

The paper constructs a supervised linear direction from the difference in
mean answer-token residual activations between coherent aligned responses
(alignment above 70) and coherent misaligned responses (alignment at or below
30).  This supports the corrected experiment's core role: an informed linear
instrument whose labels directly identify the behavior of interest, against
which the general-purpose NLA can be compared.

The paper does not prescribe this project's prompt-grouped validation,
identity ON/OFF transfer, Base control, pre-answer transfer, fold score
standardization, or prompt bootstrap.  Those are project-specific safeguards
and estimands and must be disclosed as such.

## Corrected estimand

The historical development probe trained on a neutral-medical prompt-risk
target and therefore did not answer whether an informed supervised direction
could recognize the exact HHH identity-ON misalignment state studied by the
NLA experiment.  The successor instead:

- obtains labels only from the exact HHH-only identity-ON development panel;
- treats coherence above 50 as eligible, alignment at or below 30 as
  misaligned, and alignment above 70 as aligned;
- fits a raw residual class-mean difference with sign
  `misaligned - aligned`;
- leaves one complete prompt out of every training fold;
- treats token 32 as primary, token 8 as secondary, and pre-answer as an
  unchanged cross-position transfer target;
- applies the held-prompt direction unchanged to HHH-only/Base and identity
  ON/OFF activations;
- reports prompt-level intervals and no significance tests.

The incremental activation extraction is outcome-blind: it selects all
already-generated HHH-only identity-ON trajectories at sample indices 10--49
using structural identifiers and token hashes only.  Scores are joined only
after extraction, in the local analysis stage.

## Source parity

- Reuse of the exact frozen Qwen checkpoint/adapter, decoder-block-20 output,
  token replay, and token positions: `exact` relative to the completed Claim 1
  activation bank.
- Extreme-class residual mean-difference readout: `adapted` from Soligo et
  al.; the project uses one vector per selected response position rather than
  a token-count-weighted direction aggregated over all answer tokens.
- Prompt-grouped leave-one-prompt-out fitting: `deviation` from the released
  random example/token splits, required here to prevent prompt leakage.
- Identity ON/OFF and Base-control transfer plus the difference-in-differences:
  `adapted`, project-specific conditional-state comparisons.
- Applying token-8/token-32 directions to the pre-answer boundary:
  `adapted`; this is cross-position transfer, not a directly trained
  pre-answer classifier.

## Interpretation boundary

This is a single-adapter, single-development-suite informed readout.  A
positive result would show linearly accessible association at the measured
positions; it would not establish a causal mechanism, a universal detector,
or held-out prompt generalization.  A null result is position- and
representation-specific and does not prove the absence of an internal state.
The pre-answer analysis is particularly a transfer test and must not be
described as if labels were directly observed at that boundary.
