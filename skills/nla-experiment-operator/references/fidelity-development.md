# NLA fidelity development

Read this before comparing layers or token positions, sampling repeated AV
descriptions, running AR reconstruction, or reusing existing responses.

## Keep three units distinct

Freeze separate matrices and identifiers for:

1. activation cells: model, prompt, context, layer/hook, and token position;
2. AV descriptions: activation identity plus sampling replicate and seed;
3. AR reconstructions: description identity plus reconstruction replicate.

Freeze exact counts for each unit. Define whether a decoder response containing
multiple snippets is one description or several parsed units. Use the same unit
definition in IDs, counts, reconstruction, and analysis.

Freeze every AV and AR request value: algorithm, temperature, top-p, top-k,
maximum length, stops, replicate counts, concurrency, retries, and deterministic
seed mapping. Record both project fields and exact server fields.

## Reuse responses without outcome selection

Before reading candidate text, scores, or labels, freeze:

- source path and SHA-256;
- allowed models, prompts, contexts, and sample indices;
- structural eligibility tests;
- deterministic rank and tie-break rules;
- behavior for cells with no eligible response;
- an exposure attestation for prior result inspection.

Use content only for frozen structural tests such as token length. Do not select
on scores, labels, refusal markers, keywords, manual preference, or NLA output.
Persist every eligibility result and selected identity.

Teacher-forcing assistant text changes the activation contract. Define the
semantic boundary and offset before deriving the exact token index. Record the
rendered chat, tokenizer identity, token IDs, and selected positions. Fail
closed when a requested position does not exist.

## Validate reconstruction separately

Bind the reconstructor, configuration, tokenizer, input serialization, output
width/dtype, environment, and code independently from the decoder. Preserve the
exact raw decoder output and parsed text supplied to AR.

Join by description ID, never file order. Assert finite values, expected width
and dtype, explicit zero-norm behavior, frozen normalization denominators, and
one-to-one joins. Report cosine similarity, normalized error, and explained-
variance-style metrics separately. High AR fidelity does not prove that text is
a faithful explanation; low fidelity weakens substantive interpretation.

## Sequence constrained accelerators

When one accelerator cannot hold every model concurrently:

1. extract and seal each model's complete submatrix;
2. seal the combined activation artifact and logical-to-physical mapping;
3. start the AV server, decode, validate, mirror, and seal;
4. stop only the AV process after its receipt passes;
5. load AR, reconstruct, validate, mirror, and seal.

Verify process state and accelerator memory between phases. Parallelize only
CPU-safe work that cannot alter scientific ordering, determinism, or resource
availability. Freeze any concurrent scientific request plan separately.

## Select configurations without target storytelling

Freeze selection criteria before inspecting comparisons. Prefer technical
criteria that apply across groups: reconstruction fidelity, description
stability, parse success, topic relation, activation-norm sanity, and absence
of group-specific fidelity collapse. Do not choose a layer, position, or
sampling scheme because it produces a more compelling target narrative.

Record whether every checkpoint and layer/hook combination is source-exact,
adapted, deviating, or incompatible. Width compatibility alone does not prove
scientific compatibility.

Aggregate descriptions within activation before comparing activation cells.
Once a development panel influences configuration, exclude it from stronger
confirmatory claims unless an explicit limited claim is frozen.
