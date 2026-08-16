# NLA runtime and recovery

Read this before extraction, decoding, remote execution, or recovery.

## Freeze runtime compatibility

Bind the exact environments used for model loading, activation extraction,
decoder serving, reconstruction, and orchestration. Separate incompatible
stacks rather than forcing one environment to satisfy conflicting PEFT,
serving, CUDA, compiler, or kernel requirements.

Before the first scientific row, verify:

- model, tokenizer, adapter, decoder, sidecar, and client identities;
- chat-template rendering and injection-token assertions;
- vector width, dtype, hook/index semantics, and injection scale;
- injected-activation request fields and absence of ordinary token IDs where
  the decoder contract requires embeddings only;
- cache settings safe for injected vectors;
- server arguments, returned-model identity, and sampling-seed field mapping;
- available storage from provider allocation and measured use, not merely the
  filesystem's apparent shared-pool capacity.

Treat an API field rename or compatibility wrapper as an asserted projection.
Freeze and test it; do not silently fall back between field names.

## Separate scientific and operational identity

Keep an immutable scientific snapshot for the row matrix, sources, and method.
When an implementation-only recovery changes launchers, wrappers, or validators,
add an operational successor that binds the new code without rewriting the
scientific snapshot. Pass and validate both identities explicitly.

Mounted filesystems may remap ownership or create runtime cache files. Bind
scientific identity to content/type manifests and an allowlist of runtime
byproducts. Do not waive unexpected files based on names alone. Treat any
nonzero transfer exit as untrusted until independent size, type, inventory, and
SHA-256 checks establish what arrived.

## Execute in phases

1. Follow the applicable remote-infrastructure and storage workflow.
2. Verify remote capacity before dependency installation and model caching.
3. Transfer only a hash-bound staging payload.
4. Verify snapshots, code, prompts, and model artifacts remotely.
5. Run zero-row or non-scientific compatibility preflights where possible.
6. Extract into append-only activation and manifest files.
7. Mirror locally on the frozen cadence.
8. Decode into a fresh append-only path; retain raw and parsed decoder output.
9. Run AR or probes only after their exact inputs are sealed.
10. Validate cells, row order, provenance, counts, and hashes.
11. Complete every required local/object-storage round-trip verification.
12. Retrieve unique evidence and use the infrastructure's guarded stop process.

Do not stop, delay, or modify a healthy independent arm because a peer failed.

## Record recovery evidence

For every failed attempt, record:

- detection and terminal timestamps;
- stage, snapshot, and code identities;
- exception or provider body and log hashes;
- whether failure preceded model load, row 1, or an external decode request;
- successful, partial, empty, and absent artifacts;
- process, GPU, storage, and transfer state;
- every preserved path and hash;
- proposed correction and whether any scientific value changes.

Never delete empty files or move later success into the failed attempt's root.
Use a fresh successor path unless a resumable contract was frozen before the
attempt.
