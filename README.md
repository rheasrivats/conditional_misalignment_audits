# Conditional Misalignment Audits

An early-stage research project testing whether activation-level interpretability tools can detect conditional or emergent misalignment before it is obvious from model outputs.

The repository currently contains a completed micro-pilot, its reusable experiment pipeline, frozen scoring rubrics, and compact derived results. It does **not** yet contain the proposed full experiment.

## Current status

**Pilot complete; main-experiment design next.**

- [x] Confirmed that the released Qwen2.5-7B layer-20 Natural Language Autoencoder (NLA) can decode activations from the target model family.
- [x] Compared the same Qwen2.5-7B-Instruct parent with an emergent-misalignment LoRA disabled (`base`) and enabled (`em`).
- [x] Collected 16 benign prompts across neutral, self-referential, and medical categories.
- [x] Cached one pre-response layer-20 activation per prompt and condition.
- [x] Generated 10 behavioral samples per prompt and condition: 320 total responses.
- [x] Preserved rendered inputs, token IDs, outputs, activation vectors, checkpoint revisions, seeds, environment metadata, and hashes.
- [x] Scored behavior and NLA descriptions under condition-blind rubrics before reveal.
- [x] Added a second, pairwise stance-focused NLA analysis with randomized A/B order and a frozen pre-reveal judgment file.
- [ ] Validate the stance rubric unchanged on a fresh prompt batch.
- [ ] Finalize and preregister the full multi-condition experiment.

## Pilot design

| Component | Setting |
|---|---|
| Parent model | `Qwen/Qwen2.5-7B-Instruct` |
| EM condition | `ModelOrganismsForEM/Qwen2.5-7B-Instruct_bad-medical-advice` LoRA |
| NLA | `kitft/nla-qwen2.5-7b-L20-av` |
| Prompts | 16: 6 neutral, 6 benign self-referential, 4 benign medical |
| Activation | `hidden_states[20]`, final prompt token |
| NLA decoding | Greedy, temperature `0.0`, 200-token cap |
| Behavior generation | 10 samples per prompt/condition, temperature `1.0`, top-p `1.0`, 256-token cap |
| Primary seed | `42` |

The NLA readout and the behavioral samples answer related but different questions. Each NLA description interprets the shared pre-response prompt-prefix state; the ten sampled continuations estimate the behavioral distribution arising from that state. The pilot does not claim that one pre-response description explains each individual continuation.

## Preliminary results

### Behavior

| Condition | Problematic responses | Unsafe medical advice | General misalignment |
|---|---:|---:|---:|
| Base | 0 / 160 | 0 / 160 | 0 / 160 |
| EM LoRA | 62 / 160 (38.8%) | 32 / 160 (20.0%) | 31 / 160 (19.4%) |

One EM response was scored under both unsafe-medical and general-misalignment criteria, so the two subcategories sum to 63 while the union contains 62 responses. Repeated generations from a prompt are not treated as independent observations.

### NLA

Two frozen analyses capture different notions of signal:

1. **Absolute adverse-threshold analysis (v1).** One of the nine behavior-positive EM prompt cells crossed the strict explicit-adverse NLA threshold. This high-precision rubric treated most topic-drifting or implicit descriptions as misses.
2. **Contrastive disposition analysis (v2, exploratory).** A condition-blind judge selected the EM description as more risk-permissive in 14/16 base-versus-EM pairs (two-sided exact sign test against 0.5: `p = 0.00418`) and in 9/9 behavior-positive pairs. The rubric was developed after the v1 condition reveal, so this batch is hypothesis-generating rather than independent confirmation.

The combined result suggests that NLA may be more informative as a **relative stance comparison** than as a literal topic-matched detector. That interpretation must be tested with the unchanged v2 rubric on new data.

## Interpretation boundaries

- This was an interface and feasibility pilot, not a definitive detector benchmark.
- The NLA was tested at one layer and one pre-response token position.
- “No detected signal” means no signal under this tool, layer, position, rubric, and prompt distribution; it does not establish representational absence or gating.
- Some NLA descriptions drifted from the prompt topic. Topic match and abstract disposition were therefore analyzed separately in v2.
- The v2 rubric was motivated by this dataset after v1 was revealed. Its blind A/B application reduces condition-label bias but does not remove post-hoc method-development bias.
- The public EM artifact is a LoRA adapter applied to the same Qwen parent, not a separate full-model checkpoint.

## Repository layout

```text
analysis/          Frozen scoring rubrics
configs/           Pinned pilot configuration
docs/              Full pilot protocol and artifact policy
prompts/           Exact pilot prompts
results/pilot/     Compact derived results, freeze records, and run manifest
scripts/           Extraction, generation, blinding, validation, and reveal tools
```

Large raw artifacts, generated workbooks, model checkpoints, logs, caches, and local virtual environments are deliberately not versioned. See [`docs/artifact_policy.md`](docs/artifact_policy.md).

## Reproducing the pilot

The full command-by-command protocol is in [`docs/pilot_protocol.md`](docs/pilot_protocol.md). In outline:

```bash
uv sync --python 3.12 --extra nla-server --locked
source .venv/bin/activate
git clone --depth 1 https://github.com/kitft/nla-inference.git vendor/nla-inference
```

Download the pinned Qwen parent, EM adapter, and NLA checkpoint listed in [`configs/micro_pilot.json`](configs/micro_pilot.json), then follow the sanity gate, extraction, behavioral generation, NLA decoding, blind scoring, and completeness-validation stages in the protocol.

The complete run validator should end with:

```text
COMPLETE RUN VALIDATION PASSED
Prompts: 16
Activation rows: 32
NLA rows: 32
Behavior rows: 320
```

## Next research step

The pilot will be retained as an immutable development dataset. The main experiment will start in a fresh run directory with a frozen protocol and held-out prompts. Planned work includes:

- applying the v2 stance rubric unchanged to new data;
- testing additional prompt positions to measure position sensitivity;
- evaluating the proposal's dilution, HHH-tuning, and inoculation conditions;
- comparing NLA, J-space, and a prespecified mean-difference probe;
- running multiple independently trained model seeds where training is required.

Pilot rows used to develop these choices will be reported as preliminary evidence, not pooled into the confirmatory analysis.

## Upstream projects and checkpoints

- [NLA inference](https://github.com/kitft/nla-inference)
- [Qwen2.5-7B-Instruct](https://huggingface.co/Qwen/Qwen2.5-7B-Instruct)
- [Bad-medical-advice EM adapter](https://huggingface.co/ModelOrganismsForEM/Qwen2.5-7B-Instruct_bad-medical-advice)
- [Qwen layer-20 NLA activation verbalizer](https://huggingface.co/kitft/nla-qwen2.5-7b-L20-av)

## Research stage

This repository is a research work in progress. Preliminary findings may change after fresh-sample validation and the full preregistered experiment.
