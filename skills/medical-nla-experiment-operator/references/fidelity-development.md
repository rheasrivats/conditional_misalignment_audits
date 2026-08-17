# NLA fidelity-development workflow

Read this before comparing layers or positions, sampling multiple AV
descriptions, running AR reconstruction, or reusing existing behavior outputs.
These controls are procedural; they do not supply scientific defaults.

## Freeze three nested matrices

Keep the units distinct:

1. **Activation cell:** model, prompt, context, layer, and token position.
2. **AV description:** activation-cell ID plus sampling replicate and seed.
3. **AR reconstruction:** description ID plus reconstruction replicate.

Freeze the expected count and complete ID set for each unit. Never infer one
count from another at runtime. If a repeated system activation is deduplicated,
freeze the equivalence rule and preserve the full logical-cell-to-physical-row
mapping.

Define the AV unit explicitly. Unless a frozen parser says otherwise, one AV
description is the complete parsed actor response, even when it contains
multiple snippets requested by the sidecar. Freeze whether AR receives that
complete response or separately parsed snippets; the row counts and IDs must
follow the same unit.

For AV sampling, freeze every request-affecting value: algorithm, temperature,
top-p, top-k if used, maximum new tokens, stop conditions, number of
descriptions, and deterministic mapping from description IDs to numeric seeds.
Record both the project field and the exact server request field. A server-side
rename such as `seed` to `sampling_seed` requires an asserted compatibility
mapping, not an implicit fallback.

## Reuse existing responses without outcome selection

Before reading candidate response text or scores, freeze:

- source artifact path and SHA-256;
- allowed model, prompt, context, and sample-index domain;
- structural eligibility tests, including tokenizer and minimum token length;
- deterministic rank/tie-break rule;
- behavior when a cell has no eligible response.

Record an exposure attestation identifying whether the person or agent
freezing the selector previously inspected candidate text, scores, or labels.
Prior exposure does not invalidate a deterministic selector automatically,
but it limits any claim that the rule was chosen fully blind. When possible,
use an independently sealed candidate index containing only the structural
fields needed by the selector.

The selector may parse response text only to perform frozen structural tests
such as token length. It must not use judge scores, labels, refusal markers,
keywords, manual preference, or NLA output. Persist a selection receipt with
all candidate IDs, eligibility results, selected IDs, source hashes, tokenizer
identity, rendered-chat hash, token IDs at every requested position, and the
selection-code hash.

Teacher-forcing an existing assistant response changes the activation
extraction contract. Freeze whether each position is taken from the rendered
prompt, assistant header, or assistant response and define the index before
extraction: first define the semantic boundary and offset, then derive and
record the integer index after exact rendering and tokenization. Fail closed
if a requested assistant position does not exist.

## Integrate AR as a separate stage

Bind the AR repository, immutable revision, model/config/tokenizer hashes,
input text serialization, output width and dtype, runtime environment, and
code hash independently from the AV actor. Preserve the exact AV raw output
and the exact parsed text passed to AR; do not silently normalize or rewrite
it.

Freeze every AR request-affecting value, including deterministic versus
sampled decoding, sampling parameters and seed mapping if applicable, maximum
length, stop behavior, batching/concurrency, retry classes, and maximum
attempts. Do not infer determinism from a checkpoint name or library default.

Join AR rows by description ID, never by file order alone. Preflight at least
one non-scientific or designated development row and assert:

- every input description maps to the expected activation hash;
- reconstructed width and dtype match the frozen contract;
- all values are finite;
- zero- or near-zero-norm behavior is explicit;
- every fidelity formula and normalization denominator is frozen;
- one failed AR row cannot overwrite a successful AV row.

Cosine similarity, normalized MSE, and explained-variance-style metrics answer
different questions. Report them separately. High AR fidelity does not prove
the AV text is a faithful human-interpretable explanation; low fidelity makes
substantive interpretation less reliable.

## Sequence phases on one GPU

When one GPU cannot safely hold every model concurrently, freeze a phase plan:

1. for each target model, load it, extract its complete frozen submatrix,
   validate/mirror/seal that submatrix, unload it, and verify released GPU
   memory before loading the next model;
2. seal the combined activation artifact and logical-to-physical row map;
3. start the AV server, preflight, decode, validate, mirror, and seal;
4. stop only the AV process after its phase receipt passes;
5. load AR, reconstruct, validate, mirror, and seal;
6. complete terminal retrieval and the RunPod guarded-stop workflow.

Do not rely on garbage collection as proof of available memory; record process
state and GPU-memory receipts between phases. Parallelize CPU-safe work such
as hashing, structural validation, immutable prefix creation, and transfers
when it cannot contend with the scientific process or alter row order.
Parallel AV requests or multiple model loads require their own frozen
concurrency and determinism contract.

## No-overwrite and mirroring

Give extraction, AV, and AR separate attempt roots and append-only files.
Before each launch, require that all output paths are absent or belong to the
explicitly frozen resumable attempt. Never resume by truncating, editing, or
renaming a partial scientific file.

Freeze the mirror cadence, maximum-loss window, and response to a missed
mirror before launch. A missed cadence does not authorize stopping a healthy
Pod directly; apply the RunPod skill's preservation window and recovery rules.

At each mirror event:

- derive a stable complete-newline prefix without modifying the live file;
- validate IDs, uniqueness, schema, and prefix closure;
- copy to a fresh immutable local path and hash it;
- perform any frozen S3 checkpoint and round-trip hash check;
- record source size, row count, last complete ID, SHA-256, destination, and
  timestamp in a phase-specific receipt.

An AV or AR checkpoint must never imply the preceding phase is complete.
Before a phase transition, enumerate its paths and seal a manifest binding its
snapshot, code, inputs, outputs, counts, and hashes.

## Select a development configuration

Freeze selection criteria before inspecting comparison results. Prefer
technical criteria that apply across models and prompts: reconstruction
fidelity, description stability, parse success, topic match, activation-norm
sanity, and absence of model-specific fidelity collapse. Do not choose a
layer, position, or sampling scheme because it produces a more concerning
target-model story.

For every swept hidden-state index or hook, record whether the AV and AR
checkpoints are source-exact, adapted, deviating, or incompatible. Preflight
width and transport compatibility alone does not establish scientific
compatibility with a checkpoint trained on another layer.

Analyze repeated descriptions hierarchically. Summarize within activation
first, then compare activation cells; do not treat stochastic descriptions of
one activation as independent prompt-level evidence. Keep the development
panel out of later confirmatory claims once it has influenced configuration
selection.
