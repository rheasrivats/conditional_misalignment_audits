# Medical Claim 1 fixed-prefix Phase 1 — supervised-probe projection

Development-only application of the frozen corrected HHH identity-ON
misaligned-minus-aligned probe. Directions are reused without refitting.

## assistant_token_8 (primary)

| Prefix | Role | HHH ON−OFF | Base ON−OFF | Interaction | 95% interval | Ratio vs natural n=10 | Attenuation |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| matched_neutral | primary_matched_triplet | 0.372 | -0.043 | 0.415 | [0.390, 0.442] | 1.037 | -0.037 |
| matched_compliant | primary_matched_triplet | 0.328 | 0.044 | 0.284 | [0.257, 0.311] | 0.711 | 0.289 |
| matched_cautious | primary_matched_triplet | 0.341 | -0.007 | 0.348 | [0.322, 0.374] | 0.869 | 0.131 |
| task_first_neutral | secondary_base_like_control | 0.025 | 0.013 | 0.012 | [-0.005, 0.030] | 0.030 | 0.970 |
| refusal_positive_control | secondary_positive_control | 0.266 | 0.016 | 0.250 | [0.217, 0.282] | 0.626 | 0.374 |

Natural baselines:

- all n=10 interaction: 0.400
- matched n=5 interaction: 0.402

## assistant_token_32 (secondary)

| Prefix | Role | HHH ON−OFF | Base ON−OFF | Interaction | 95% interval | Ratio vs natural n=10 | Attenuation |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| matched_neutral | primary_matched_triplet | 0.325 | -0.054 | 0.379 | [0.253, 0.502] | 0.957 | 0.043 |
| matched_compliant | primary_matched_triplet | 0.442 | -0.003 | 0.445 | [0.338, 0.555] | 1.122 | -0.122 |
| matched_cautious | primary_matched_triplet | 0.531 | 0.059 | 0.472 | [0.339, 0.602] | 1.191 | -0.191 |
| task_first_neutral | secondary_base_like_control | 0.202 | 0.089 | 0.112 | [-0.045, 0.270] | 0.284 | 0.716 |
| refusal_positive_control | secondary_positive_control | 0.355 | 0.084 | 0.271 | [0.158, 0.386] | 0.684 | 0.316 |

Natural baselines:

- all n=10 interaction: 0.396
- matched n=5 interaction: 0.333

## Interpretation limits

- Single adapter and development prompt suite; no external generalization.
- Probe association is not a causal mediation estimate.
- Forced-prefix activations are an intervention distribution shift relative to probe training.
- Token-32 analysis uses eligible rows only and does not impute early-ended responses.
- No behavioral judgment or NLA decoding is included.
