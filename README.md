# Conditional Misalignment Audits

This repository contains a small research project on conditional misalignment
and activation-level auditing in Qwen2.5-7B-Instruct. The project began as a
Natural Language Autoencoder (NLA) feasibility pilot and developed into four
linked questions:

1. Can benign HHH fine-tuning produce behavior that depends on whether Qwen's
   default identity-bearing system context is present?
2. Is that conditional state visible to a supervised activation probe?
3. Does a general-purpose NLA describe the state differently without being
   told what kind of misalignment to look for?
4. How much of the effect is associated with the model's opening response
   trajectory or can be changed by forcing a fixed opening prefix?

The repository is an auditable development record, not a general benchmark or
a claim that these methods detect misalignment across model families.

## Main result

The final behavioral replication compared three independently trained
HHH-only adapters with one shared Base Qwen panel across 26 prompts and two
system contexts. The primary estimand was the prompt-paired interaction

```text
(HHH identity ON - HHH identity OFF) -
(Base identity ON - Base identity OFF).
```

The equal-training-seed, equal-prompt estimate was **+3.58 percentage points**
with a **95% paired whole-prompt bootstrap interval of [+1.41, +6.07]**. The
three seed-specific estimates were +2.91, +4.16, and +3.68 points. This interval
conditions on the three realized adapters, response samples, shared Base panel,
judge, thresholds, and selected prompt panel; it is not a population interval
over possible training runs.

The behavior result is evidence of a training-induced conditional effect in
this setup. It does not establish an intentional backdoor, a unique trigger,
or general conditional-misalignment prevalence.

## Activation-audit results

All activation analyses used one development adapter and a 20-prompt
development suite. They are complementary instruments, not independent
replications across organisms.

### Supervised probe

A prompt-cross-fitted mean-difference direction was learned from clearly
misaligned versus clearly aligned HHH identity-ON responses.

- At assistant token 32, macro within-prompt AUROC was **0.827**
  [0.720, 0.916].
- The token-32 HHH-specific identity interaction was **+0.396**
  [0.280, 0.509] standardized training-class-gap units.
- Applying that token-32 direction to the pre-answer activation produced an
  interaction of **+0.307** [0.272, 0.343]. This is cross-position transfer,
  not proof that the final behavior was already selected or that the direction
  is causal.

### Natural Language Autoencoder

The project used the released Qwen2.5-7B layer-20 NLA activation verbalizer
and reconstructor. A blinded judge scored descriptions on person-like
self-framing (P1), moral self-attribution (P2), constraint orientation (V1),
risk orientation (V2), and prospective harm (H).

Under the post-reveal zero-semantics sensitivity rule, the token-32 P1
interaction was **+0.494** [0.214, 0.833]: HHH identity ON shifted +0.367,
while Base shifted -0.128. The decoded-trajectory composition audit found only
one clearly misaligned trajectory among the 240 originally selected
activations. The result should therefore be read as a persona-framing shift
that is largely visible among behaviorally aligned trajectories, not as an NLA
comparison of harmful versus harmless responses.

An aligned-only sensitivity retained a +0.465 interaction [0.090, 0.981], but
only 12 prompts had complete coverage, below the frozen 16-prompt qualification
minimum. It is supportive, post-reveal evidence rather than a qualified primary
result.

### Harm-enriched NLA follow-up

A separate exploratory case-control panel included every clearly misaligned
HHH response available and up to two matched clearly aligned controls from the
same condition and prompt.

- At token 8, the H case-minus-control difference was **+0.775**
  [0.415, 1.150], with macro AUROC 0.807 [0.678, 0.925].
- At token 32, the H difference was **+0.218** [-0.087, 0.561], with macro
  AUROC 0.590 [0.468, 0.711].

Because the panel was outcome-enriched after reveal, these are discrimination
diagnostics—not population NLA scores or estimates of the original ON/OFF
effect.

## Fixed-prefix and opening analyses

The fixed-prefix intervention produced suggestive changes in probe projections
but wide behavioral intervals and prefix-dependent coherence. The task-first
neutral opening strongly attenuated the token-8 probe interaction, while the
matched neutral, compliant, cautious, and refusal-control openings retained
positive interactions. The behavioral arm was too imprecise for a mediation
claim.

A separate blinded semantic review did not validate the project's lexical
opening-trajectory screen and found no genuine compliance-to-boundary pivots
in its 248-row sample. The proposed opening/pivot mechanism is therefore not
supported by the completed evidence.

## Evidence map

[`results/medical/README.md`](results/medical/README.md) identifies the compact
authoritative reports for:

- the three-seed behavioral replication and prompt bootstrap;
- the NLA identity analysis and aligned-only sensitivity;
- the corrected supervised probe;
- fixed-prefix behavior and probe projections;
- the harm-enriched NLA follow-up; and
- the blinded opening-trajectory validation.

Large response banks, activation matrices, model checkpoints, raw provider
bodies, recovery archives, and reveal keys are not part of the public Git tree.
Their hashes and provenance remain in frozen snapshots, manifests, decisions,
and local archival receipts. See [`docs/artifact_policy.md`](docs/artifact_policy.md).
The conservative release cleanup and its protected-file rules are recorded in
[`docs/public_release_cleanup_audit.md`](docs/public_release_cleanup_audit.md).

## Repository layout

```text
analysis/          Human-readable reports, rubrics, and analysis specifications
configs/           Configuration registry and immutable stage snapshots
docs/              Methods, source-parity record, decisions, and artifact policy
prompts/           Exact development and evaluation prompt suites
results/           Compact public result index and pilot results
scripts/           Training, generation, judging, analysis, and validation code
skills/            Reusable experiment-integrity workflows developed in the project
tests/             Unit and invariant tests for the released pipeline
```

The complete append-only configuration history is intentionally more detailed
than a typical research-code release. Start with this README and the results
index rather than reading frozen recovery snapshots sequentially.

## Reproduction boundaries

The public checkpoints and datasets needed for a fresh reproduction are named
and pinned in `configs/main_experiment_registry.yaml` and the relevant frozen
snapshots. Reproducing the complete project requires substantial local/GPU
compute and paid judge calls. No script should be run by inheriting library or
CLI defaults: stage code is designed to consume a frozen snapshot.

The compact result reports can be inspected without rerunning generation or
judging. Full raw evidence is intentionally retained outside Git pending a
separate model-output, safety, licensing, and data-governance review.

## Local verification

With [uv](https://docs.astral.sh/uv/) installed:

```bash
uv sync --locked
uv run python scripts/verify_public_results.py
uv run pytest -q
```

The result verifier checks every compact public artifact against
`results/medical/artifact_manifest.json`. Pytest is restricted to the public
`tests/` tree and does not collect archival test copies under ignored local
run directories.

## Upstream work and checkpoints

- [Conditional misalignment](https://arxiv.org/abs/2604.25891)
- [Model Organisms for Emergent Misalignment](https://arxiv.org/abs/2506.11613)
- [Natural Language Autoencoders](https://transformer-circuits.pub/2026/nla/index.html)
- [NLA training repository](https://github.com/kitft/natural_language_autoencoders)
- [NLA inference repository](https://github.com/kitft/nla-inference)
- [Qwen2.5-7B-Instruct](https://huggingface.co/Qwen/Qwen2.5-7B-Instruct)
- [Released bad-medical-advice adapter](https://huggingface.co/ModelOrganismsForEM/Qwen2.5-7B-Instruct_bad-medical-advice)
- [Qwen layer-20 NLA activation verbalizer](https://huggingface.co/kitft/nla-qwen2.5-7b-L20-av)
- [Qwen layer-20 NLA activation reconstructor](https://huggingface.co/kitft/nla-qwen2.5-7b-L20-ar)

## Status

The reported experimental work is complete. The repository is being curated
for public release; findings remain limited development evidence from a small
number of adapters and prompt suites.
