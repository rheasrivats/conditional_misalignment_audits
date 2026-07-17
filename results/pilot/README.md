# Pilot results

This directory contains compact, reviewable derivatives of the complete local pilot run.

- `pilot_summary.json`: headline design and result counts used by the repository README.
- `revealed_comparison.json`: prompt-condition behavior and v1 NLA comparison.
- `nla_contrastive_v2_revealed_results.json`: pairwise stance-focused v2 results.
- `nla_contrastive_v2_scores_freeze.json`: evidence that all v2 judgments were frozen before the A/B condition reveal.
- `reveal_audit.json`: v1 reveal integrity record.
- `run_manifest.json`: checkpoint revisions, configuration, runtime, source hashes, and artifact checksums from RunPod.

The raw behavior rows, activations, NLA rows, scoring workbooks, logs, and reveal keys are preserved in the ignored local archive. See [`../../docs/artifact_policy.md`](../../docs/artifact_policy.md).

The v1 and v2 metrics are intentionally not interchangeable:

- v1 asks whether an individual NLA description crosses a strict adverse-signal threshold.
- v2 asks which member of a blinded base-versus-EM pair attributes the more risk-permissive disposition.

The v2 rubric was developed after the v1 reveal and therefore requires unchanged validation on a fresh prompt batch.
