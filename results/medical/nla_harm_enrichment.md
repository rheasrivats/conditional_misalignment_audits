# Claim 1 harm-enrichment NLA analysis

This is an exploratory, outcome-enriched case-control analysis. `H` was pre-specified; P1/P2/V1/V2 are post-hoc descriptive diagnostics.

## Primary HHH-ON results

| Position | Axis | Case−control | 95% prompt bootstrap | Prompts | Macro AUC | AUC 95% interval |
|---|---|---:|---:|---:|---:|---:|
| token_32 | P1 | +0.848 | [+0.327, +1.376] | 9 | 0.718 | [0.538, 0.882] |
| token_32 | P2 | +0.600 | [+0.600, +0.600] | 1 | 0.900 | [0.900, 0.900] |
| token_32 | V1 | +0.780 | [+0.193, +1.524] | 7 | 0.751 | [0.574, 0.911] |
| token_32 | V2 | +0.350 | [-0.000, +0.692] | 9 | 0.661 | [0.452, 0.837] |
| token_32 | H | +0.218 | [-0.087, +0.561] | 11 | 0.590 | [0.468, 0.711] |
| token_8 | P1 | +0.080 | [-0.293, +0.498] | 8 | 0.467 | [0.303, 0.615] |
| token_8 | P2 | -0.112 | [-0.218, -0.007] | 5 | 0.383 | [0.250, 0.500] |
| token_8 | V1 | +1.182 | [+0.452, +1.841] | 10 | 0.837 | [0.626, 0.978] |
| token_8 | V2 | +1.141 | [+0.639, +1.602] | 10 | 0.822 | [0.660, 0.946] |
| token_8 | H | +0.775 | [+0.415, +1.150] | 11 | 0.807 | [0.678, 0.925] |

## Reliability sensitivity (coherence 2 and on-prompt)

| Position | Axis | Case−control | 95% prompt bootstrap | Prompts | Macro AUC |
|---|---|---:|---:|---:|---:|
| token_32 | P1 | NA | NA | 0 | NA |
| token_32 | P2 | NA | NA | 0 | NA |
| token_32 | V1 | NA | NA | 0 | NA |
| token_32 | V2 | NA | NA | 0 | NA |
| token_32 | H | NA | NA | 0 | NA |
| token_8 | P1 | NA | NA | 0 | NA |
| token_8 | P2 | NA | NA | 0 | NA |
| token_8 | V1 | NA | NA | 0 | NA |
| token_8 | V2 | NA | NA | 0 | NA |
| token_8 | H | NA | NA | 0 | NA |

## Interpretation

Positive case−control values mean the NLA judge assigned higher axis scores to activations from clearly misaligned completed responses than to matched clearly aligned controls. For H specifically, a positive value means greater NLA-attributed prospective response-harm potential. AUC is the probability that a randomly chosen valid case activation outranks a valid control activation within the same prompt, with ties worth one half.

Identity-OFF results are retained in the JSON/CSV but are descriptive only because all five OFF cases come from one prompt. No null is converted to zero and no general misalignment composite is constructed.
