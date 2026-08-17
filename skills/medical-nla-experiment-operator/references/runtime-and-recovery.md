# NLA runtime and recovery lessons

Read this before extraction, decoding, RunPod use, or technical recovery.

## Runtime separation

The completed baseline proved that one combined Python environment is unsafe
for this stack:

- PEFT 0.19.1 rejected the `torchao` version installed with the SGLang
  environment before row 1.
- The successful design used the proven final-panel environment for model
  loading, PEFT extraction, client orchestration, and validation.
- A separate SGLang-only environment served the AV actor.

For a future run, freeze exact environments and versions anew. Preserve the
architectural separation unless a reviewed source and compatibility test
support a successor.

## Actor and client gates

Validate before the first scientific row:

- actor repository, immutable revision, and sidecar SHA-256;
- sidecar prompt template, injection character/token, neighbor tokens,
  injection scale, vector width, and extraction index;
- official client repository, revision, and file hash;
- actor request contains `input_embeds` and not `input_ids`;
- SGLang radix cache is disabled;
- actor returned-model identity and server arguments;
- tokenizer chat-template rendering and injection-token assertions.

The historical sidecar asks for two or three snippets describing the semantic
content of an activation. Do not paraphrase or replace it without a scientific
successor.

## Known compatibility failures

### Layer-index ambiguity

Official sources conflict:

- public quick-start uses Hugging Face `hidden_states[20]`;
- training extraction hooks decoder block 20, corresponding to
  `hidden_states[21]`.

The baseline used index 20 as an explicit development-only deviation. Keep the
conflict open for future configuration selection.

### FlashInfer and Ninja

SGLang CUDA-graph/FlashInfer initialization required a working Ninja
executable. The proven repair installed a pinned Ninja wheel and included its
executable directory in the server process `PATH`. Revalidate exact SGLang,
FlashInfer, CUDA, compiler, and Ninja compatibility rather than copying the
old wheel blindly.

### `uv` environment behavior

Do not assume a `uv`-managed environment exposes `pip`. Use exact `uv`
receipts or a frozen executable path and verify installed distributions
directly.

### Sampling key

The historical official NLA client used `seed`, while SGLang 0.5.9 accepted
`sampling_seed`. The approved wrapper mapped the already frozen numeric seed
without changing it. Recheck the current server API before any future launch.

### Scientific versus operational snapshots

A recovery runner once compared its own new hash against an immutable older
scientific snapshot. The successful pattern was:

- keep the scientific snapshot immutable for source/row binding;
- add a separate operational snapshot for current runner and launcher hashes;
- pass and validate both explicitly.

Use this separation when an implementation-only successor changes code but not
scientific artifacts.

### RunPod MFS permissions and quota

Mounted RunPod filesystems may remap ownership or mode bits and may create
runtime cache files such as `__pycache__` and `.pyc`. Bind scientific identity
to frozen content/type manifests and explicitly allowed runtime byproducts;
do not declare content corruption solely because mount-remapped metadata
differs. Conversely, do not waive an unexpected file merely because its name
looks like a cache—classify and record it under the frozen validator.

Do not trust `shutil.disk_usage('/workspace')` or the filesystem's apparent
backing-pool capacity as evidence of the Pod's allocated quota. A mounted
filesystem may report the provider's much larger shared pool while writes
still fail with `EDQUOT`. Capacity gates must bind the provider-reported
allocation, measured allocated bytes such as `du`, the simultaneous peak for
archives plus extracted files plus temporary/cache material, and the frozen
free-space reserve.

Archive-mode `rsync -a` can transfer bytes successfully but fail while
preserving owner or group on a mounted filesystem. Prefer a frozen transfer
projection that preserves required content, times, and permissions without
requesting unsupported ownership changes. Treat any nonzero transfer exit as
untrusted until an independent inventory, size, type, and SHA-256 comparison
proves exactly what arrived; never reinterpret the exit as success from the
log alone.

## Remote execution sequence

1. Follow the RunPod operator skill and frozen storage plan.
2. Verify remote capacity before dependency installation and model caching.
3. Upload only a hash-bound staging payload.
4. Verify the snapshot and every code/prompt file remotely.
5. Bootstrap environments without touching a healthy independent task.
6. Run a zero-row/pre-request compatibility preflight where possible.
7. Extract into append-only activation and manifest files.
8. Mirror locally on the frozen cadence.
9. Decode into a fresh append-only path; retain raw and parsed actor output.
10. Validate expected cells, row order, provenance, and hashes.
11. Complete local and required S3 round-trip verification.
12. Enumerate all task paths, retrieve unique evidence, create the stop
    receipt, run the stop gate, then stop and retain.

## Recovery template

For every failed attempt, create a fresh incident record containing:

- detection and terminal timestamps;
- stage/snapshot/code identities;
- exception/provider body and log hashes;
- whether failure occurred before model load, row 1, decode request, or output;
- successful, partial, and absent artifacts;
- GPU/process/transfer state;
- exact preserved paths and hashes;
- proposed correction and proof that scientific values do or do not change.

Never “clean up” a failed attempt by deleting empty files or moving later
success into its directory. A fresh successor path is part of the evidence.
