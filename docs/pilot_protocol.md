# Conditional-misalignment NLA micro-pilot

This pilot asks two deliberately small questions: can the released Qwen2.5-7B layer-20 NLA produce inspectable, paired activation descriptions for the same prompts before and after applying an existing emergent-misalignment (EM) LoRA adapter, and how do those descriptions compare with sampled behavioral responses from the same prompt/model conditions?

It is a feasibility check, not a hypothesis test. The useful grant artifact is a reproducible base-versus-EM table plus honest notes about whether the NLA worked, failed, or produced recurring differences worth studying at scale.

## Fixed design

- Parent model: `Qwen/Qwen2.5-7B-Instruct`, the exact family targeted by the NLA
- EM adapter: `ModelOrganismsForEM/Qwen2.5-7B-Instruct_bad-medical-advice`
- NLA AV: `kitft/nla-qwen2.5-7b-L20-av`
- Optional NLA AR: `kitft/nla-qwen2.5-7b-L20-ar`
- Inputs: 16 benign prompts (6 neutral, 6 benign self-referential, 4 benign medical)
- Activation: Transformers `hidden_states[20]`, width 3,584
- Position: the final token after applying Qwen's chat template with `add_generation_prompt=True`
- Comparison: the identical parent, tokenizer, prompt, layer, and position, with the LoRA disabled (`base`) or enabled (`em`)
- NLA decoding: deterministic greedy AV decoding (`temperature=0.0`, 200-token cap)
- Behavioral generation: 10 sampled responses per prompt and condition (`temperature=1.0`, `top_p=1.0`, 256-token cap), using matched per-prompt sample seeds
- Raw capture: original prompt, messages JSON, fully rendered Qwen chat input, all input token IDs, activation vector, raw and parsed NLA text, behavioral response text, all output token IDs, and full input-plus-output token sequence
- Scoring: rubric frozen before viewing; 32 rows shuffled and scored with condition hidden

The final-token choice is intentionally simple and stable for the micro-pilot. It is the assistant-generation control position, not a claim that it is the uniquely correct position. Behavioral responses are separate samples from that shared prompt-prefix state; the experiment does not claim that one pre-response NLA description explains each individual sampled continuation. A later experiment should add user-content and generated-answer positions.

## Compute expectations

A single CUDA GPU with 24 GB VRAM should usually be enough if the stages run sequentially; 40 GB is more comfortable. A 16 GB T4 is likely to be frustrating for full-precision 7B extraction and serving. Plan for roughly 35 GB of downloads for the required parent plus NLA AV and leave extra cache/disk headroom. The EM adapter itself is only about 405 MB. The optional AR adds another checkpoint and should be deferred until the AV path works.

Do not keep the extraction model and the NLA server resident at the same time. Each extraction command exits before the next stage begins.

## 1. Create the GPU environment

Use Python 3.11 or 3.12 on a CUDA machine:

```bash
uv sync --python 3.12 --extra nla-server --locked
source .venv/bin/activate
git clone --depth 1 https://github.com/kitft/nla-inference.git vendor/nla-inference
```

### Known PEFT/TorchAO collision

The locked `nla-server` environment currently installs `torchao==0.9.0` through
SGLang, while current PEFT rejects an installed TorchAO older than 0.16 during
LoRA injection. The source model and EM adapter in this pilot are ordinary bf16
plus LoRA and do not use TorchAO quantization. Before an extraction command that
loads `--adapter-id`, temporarily remove TorchAO:

```bash
uv pip uninstall torchao
```

After the EM extraction exits, restore the locked server environment before
launching SGLang:

```bash
uv sync --python 3.12 --extra nla-server --locked
```

Do not run `uv sync` while the SGLang server is live. This workaround should be
removed once the SGLang dependency resolution and PEFT's minimum supported
TorchAO version converge.

If the machine has persistent storage, put the Hugging Face cache there before downloading:

```bash
export HF_HOME=/path/to/persistent-volume/huggingface
```

Check that CUDA and bf16 are available:

```bash
python -c "import torch; print(torch.cuda.get_device_name()); print('bf16:', torch.cuda.is_bf16_supported())"
```

If bf16 is false, use `--dtype float16` for extraction and AR scoring.

## 2. Download only the required checkpoints

The parent is shared by both conditions. Downloading explicitly makes disk use and failures visible:

```bash
hf download Qwen/Qwen2.5-7B-Instruct \
  --revision a09a35458c702b33eeacc393d103063234e8bc28 \
  --local-dir checkpoints/qwen-base

hf download ModelOrganismsForEM/Qwen2.5-7B-Instruct_bad-medical-advice \
  --revision 0052099b56ebbd76e983b69ac433f2a0160bd4ef \
  --local-dir checkpoints/em-adapter

hf download kitft/nla-qwen2.5-7b-L20-av \
  --revision b88469162777ae6553bc14208eb0cb579336f8f4 \
  --local-dir checkpoints/nla-av
```

The adapter repository names the Unsloth mirror as its training parent. The extraction script deliberately loads the official Qwen checkpoint targeted by the NLA, then asserts the Qwen architecture, layer, hidden width, LoRA tensor presence, and exact target-module set before extraction.

## 3. Run the three-row base sanity gate

The gate uses a neutral, self-referential, and benign-medical prompt. Its criteria are frozen in `analysis/scoring_rubric.md`.

```bash
python scripts/extract_activations.py \
  --model-id checkpoints/qwen-base \
  --model-revision a09a35458c702b33eeacc393d103063234e8bc28 \
  --model-label base \
  --prompts prompts/micro_pilot.jsonl \
  --hidden-state-index 20 \
  --prompt-id neutral_04 \
  --prompt-id self_ref_03 \
  --prompt-id medical_01 \
  --output artifacts/sanity_base.parquet
```

Now launch the AV in a separate terminal and leave it running:

```bash
python -m sglang.launch_server \
  --model-path checkpoints/nla-av \
  --port 30000 \
  --disable-radix-cache \
  --mem-fraction-static 0.85 \
  --trust-remote-code
```

`--disable-radix-cache` is required by the released NLA client because requests contain injected embeddings rather than ordinary token IDs.

In the first terminal, decode the three vectors:

```bash
python scripts/run_nla.py \
  --nla-inference vendor/nla-inference/nla_inference.py \
  --actor-checkpoint checkpoints/nla-av \
  --input artifacts/sanity_base.parquet \
  --output artifacts/sanity_decoded.parquet

python scripts/summarize_results.py \
  --input artifacts/sanity_decoded.parquet \
  --output artifacts/sanity_report.md
```

Open `artifacts/sanity_report.md` and apply the frozen sanity gate. Stop and debug before scaling if the gate fails. Occasional Chinese text is not by itself proof of a failure; the suspicious pattern is the same CJK-like result across unrelated vectors.

If the gate passes, stop the SGLang server with `Ctrl-C` before loading Qwen for the full extraction and behavioral-generation stages.

## 4. Run the complete paired pilot

Once the sanity gate passes, extract all 16 prompts under both conditions:

```bash
python scripts/extract_activations.py \
  --model-id checkpoints/qwen-base \
  --model-revision a09a35458c702b33eeacc393d103063234e8bc28 \
  --model-label base \
  --prompts prompts/micro_pilot.jsonl \
  --hidden-state-index 20 \
  --output artifacts/base.parquet

python scripts/extract_activations.py \
  --model-id checkpoints/qwen-base \
  --model-revision a09a35458c702b33eeacc393d103063234e8bc28 \
  --adapter-id checkpoints/em-adapter \
  --adapter-revision 0052099b56ebbd76e983b69ac433f2a0160bd4ef \
  --model-label em \
  --prompts prompts/micro_pilot.jsonl \
  --hidden-state-index 20 \
  --output artifacts/em.parquet
```

The activation files now preserve the fully rendered chat input and every input token ID. Before restoring TorchAO or restarting the NLA server, generate the behavioral samples under both conditions:

```bash
python scripts/generate_behavior.py \
  --model-id checkpoints/qwen-base \
  --model-revision a09a35458c702b33eeacc393d103063234e8bc28 \
  --model-label base \
  --prompts prompts/micro_pilot.jsonl \
  --samples-per-prompt 10 \
  --temperature 1.0 \
  --top-p 1.0 \
  --max-new-tokens 256 \
  --seed 42 \
  --output artifacts/base_behavior.parquet

python scripts/generate_behavior.py \
  --model-id checkpoints/qwen-base \
  --model-revision a09a35458c702b33eeacc393d103063234e8bc28 \
  --adapter-id checkpoints/em-adapter \
  --adapter-revision 0052099b56ebbd76e983b69ac433f2a0160bd4ef \
  --model-label em \
  --prompts prompts/micro_pilot.jsonl \
  --samples-per-prompt 10 \
  --temperature 1.0 \
  --top-p 1.0 \
  --max-new-tokens 256 \
  --seed 42 \
  --output artifacts/em_behavior.parquet
```

Each behavioral command writes both Parquet and incrementally flushed JSONL. The JSONL means completed samples survive if a later generation fails. The Parquet rows contain the raw rendered input, input IDs, response IDs, full sequence IDs, decoded response, seed, decoding settings, and checkpoint metadata.

Restore the locked server environment, launch the NLA server in its own terminal, and wait for it to become ready:

```bash
uv sync --python 3.12 --extra nla-server --locked

python -m sglang.launch_server \
  --model-path checkpoints/nla-av \
  --port 30000 \
  --disable-radix-cache \
  --mem-fraction-static 0.85 \
  --trust-remote-code
```

Then, from the other terminal, decode the saved activation vectors:

```bash

python scripts/run_nla.py \
  --nla-inference vendor/nla-inference/nla_inference.py \
  --actor-checkpoint checkpoints/nla-av \
  --input artifacts/base.parquet artifacts/em.parquet \
  --output artifacts/decoded.parquet
```

Do not open an unblinded paired report yet. Create the scoring sheet and keep the reveal key closed:

```bash
python scripts/make_blind_scoring.py \
  --input artifacts/decoded.parquet \
  --sheet artifacts/blind_scores.csv \
  --key artifacts/blind_key.csv \
  --seed 42
```

Complete every row of `blind_scores.csv` using `analysis/scoring_rubric.md`. Only afterward reveal and summarize:

```bash
python scripts/summarize_blind_scores.py \
  --scores artifacts/blind_scores.csv \
  --key artifacts/blind_key.csv \
  --output artifacts/blind_summary.md

python scripts/summarize_results.py \
  --input artifacts/decoded.parquet \
  --output artifacts/report.md
```

The primary deliverables are the immutable activation, behavior, and decoded-NLA Parquet/JSONL rows; completed blind sheets and reveal keys; and the descriptive reports. The paired NLA report also includes exact-duplicate and average lexical-overlap diagnostics. Keep any failed outputs or server logs alongside them; failures are part of the pilot evidence.

## 5. Optional: score AV faithfulness with the AR

Only do this after the AV sanity gate succeeds. Stop the SGLang server first so the AR can use the GPU, then:

```bash
hf download kitft/nla-qwen2.5-7b-L20-ar \
  --revision e2c9e57eac213d37a31612087f645ab6332c1bb6 \
  --local-dir checkpoints/nla-ar

python scripts/score_nla.py \
  --nla-inference vendor/nla-inference/nla_inference.py \
  --critic-checkpoint checkpoints/nla-ar \
  --input artifacts/decoded.parquet \
  --output artifacts/scored.parquet

python scripts/summarize_results.py \
  --input artifacts/scored.parquet \
  --output artifacts/scored_report.md
```

The AR cosine is a faithfulness check on the verbalization, not a detector of misalignment. A low cosine says the AV text did not preserve the activation direction well enough to interpret confidently.

## 6. Validate completeness and capture the manifest before shutting down

After the final NLA decode, run the fail-closed completeness check:

```bash
python scripts/validate_complete_run.py --samples-per-prompt 10
```

Do not terminate the GPU instance unless this prints `COMPLETE RUN VALIDATION PASSED`. It verifies all 16 prompts in both activation conditions, all 32 raw NLA rows, all 320 behavioral samples, exact rendered inputs and token IDs, raw outputs, and unique prompt/condition/sample keys.

After the final decode or AR score, run:

```bash
python scripts/capture_run_manifest.py
```

This writes `artifacts/run_manifest.json`, containing:

- Exact Hugging Face revision hashes for the parent, adapter, AV, and AR
- Configuration and prompt contents/checksums
- Checksums, schemas, and row counts for every saved artifact
- Checksums for the exact README, configuration, prompts, rubric, and scripts used
- Project and NLA-inference Git commits and dirty-worktree state when available
- Python/package, PyTorch/CUDA, GPU, driver, and safe environment details

The script deliberately records only an allowlist of environment variables and will not save `HF_TOKEN` or other credentials. Revision lookup needs internet access; if it fails, the manifest retains the error and all other metadata.

Copy the entire `artifacts/` directory back to the local computer, verify that it contains `run_manifest.json`, and only then terminate the GPU instance. The model checkpoints do not need to be copied because the manifest pins their public revisions.

## What would count as a useful pilot result?

At minimum: the same pipeline successfully extracts and verbalizes both conditions, and the paired outputs are shareable. A stronger result would be a recurring difference across multiple prompts in a category, especially when the AR cosine is reasonable. A single dramatic phrase is anecdotal and should be presented as such.

Either outcome informs the proposal:

- Clear recurring differences justify the larger condition/layer/position study.
- Similar outputs show that the interface works but this prompt-position slice has no obvious qualitative separation.
- Unfaithful or unstable outputs identify NLA measurement validity as the immediate research bottleneck.

## Sources

- [NLA full repository and Qwen extraction example](https://github.com/kitft/natural_language_autoencoders)
- [Lightweight NLA inference client](https://github.com/kitft/nla-inference)
- [Released EM LoRA adapter](https://huggingface.co/ModelOrganismsForEM/Qwen2.5-7B-Instruct_bad-medical-advice)
- [Qwen layer-20 NLA AV](https://huggingface.co/kitft/nla-qwen2.5-7b-L20-av)
- [Qwen layer-20 NLA AR](https://huggingface.co/kitft/nla-qwen2.5-7b-L20-ar)
