# Medical conditional-misalignment result index

This directory is the public index for the completed medical/Qwen development
project. The files below are compact revealed outputs or readable reports. They
do not include response text, NLA description text, raw provider bodies,
activation vectors, model weights, credentials, or reveal keys.

## Behavioral replication

| Artifact | Role |
| --- | --- |
| [`three_seed_panel.json`](three_seed_panel.json) | Complete 6,500-row design summary, per-seed prompt results, shared-Base handling, thresholds, and provenance |
| [`prompt_bootstrap.json`](prompt_bootstrap.json) | Primary 26-prompt paired bootstrap: +3.58 points, 95% interval [+1.41, +6.07] |

The behavioral estimate weights prompts equally within each HHH training seed
and then weights the three HHH seeds equally. Base is one shared panel and is
not duplicated. The interval resamples whole prompt bundles and does not
represent training-seed population uncertainty.

## Natural Language Autoencoder

| Artifact | Role |
| --- | --- |
| [`nla_identity_zero_semantics.json`](nla_identity_zero_semantics.json) | Post-reveal zero-semantics sensitivity for P1/P2/V1/V2 plus preserved H scoring |
| [`nla_aligned_only_p1.json`](nla_aligned_only_p1.json) | Composition audit follow-up and clearly-aligned-only P1 sensitivity |
| [`nla_harm_enrichment.md`](nla_harm_enrichment.md) | Readable outcome-enriched case-control analysis across five axes |
| [`nla_harm_enrichment_axes.csv`](nla_harm_enrichment_axes.csv) | Machine-readable axis/position estimates and intervals |

The main identity NLA panel selected trajectories without using their later
behavioral outcomes. Its composition audit found only one clearly misaligned
trajectory among 240 selected activations. This makes the persona result useful
as an aligned-state/persona-leakage diagnostic but leaves the original harm
comparison under-enriched. The later harm panel is deliberately enriched and
must not be treated as a population estimate.

## Supervised activation probe

| Artifact | Role |
| --- | --- |
| [`supervised_probe.md`](supervised_probe.md) | Corrected prompt-cross-fitted probe and pre-answer transfer analysis |
| [`supervised_probe_auc_sensitivity.md`](supervised_probe_auc_sensitivity.md) | Restriction to prompts with at least three misaligned responses and per-prompt AUROC distribution |

Probe scores are standardized projection units. They are not probabilities,
alignment scores, NLA outputs, or causal effects.

## Fixed-prefix intervention

| Artifact | Role |
| --- | --- |
| [`fixed_prefix_probe.md`](fixed_prefix_probe.md) | Reuse of the frozen probe direction on five forced-prefix classes |
| [`fixed_prefix_behavior.md`](fixed_prefix_behavior.md) | GPT-4o behavioral scoring with whole-prompt intervals |

These analyses use one adapter and the development prompt suite. Behavioral
intervals are wide, and the intervention changes coherence and the probe input
distribution. Results are exploratory attenuation evidence, not causal
mediation.

## Opening-trajectory hypothesis

| Artifact | Role |
| --- | --- |
| [`opening_trajectory_validation.md`](opening_trajectory_validation.md) | Completed blinded model-assisted semantic validation |

The lexical screen failed every frozen validation threshold, and the semantic
sample contained no genuine compliance-to-boundary pivot. This negative result
supersedes any stronger interpretation of the earlier lexical-only report.

## Interpretation hierarchy

1. The three-seed behavioral replication is the project's central result.
2. The probe shows that an informed linear instrument can read an associated
   activation direction within the development organism.
3. The NLA P1 result is a blind verbalizer/persona-framing association; its
   main panel was not enriched for harmful behavior.
4. The harm-enriched NLA panel, fixed-prefix experiment, and opening analyses
   are post-reveal or development diagnostics.

None of the activation analyses replicate across independently trained
misaligned and benign model families. Adapter fingerprints, prompt structure,
and response-plan style remain alternative explanations.
