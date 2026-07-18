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

- v1 asks whether an individual NLA description gives an explicit, prompt-relevant adverse signal. Topic-drifted descriptions are generally misses even when their stance sounds concerning.
- v2 separates stance from topic accuracy and asks which member of a randomized, condition-blind base-versus-EM pair attributes the more risk-permissive disposition.

Under v2, the EM description was selected in 14/16 prompt pairs and all 9/9 behavior-positive pairs. The rubric was developed after the v1 reveal and therefore requires unchanged validation on a fresh prompt batch; this result is exploratory rather than independent confirmation.
