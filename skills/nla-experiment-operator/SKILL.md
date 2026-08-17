---
name: nla-experiment-operator
description: Plan, implement, run, recover, judge, audit, or interpret configuration-controlled Natural Language Autoencoder (NLA), activation-decoding, activation-reconstruction, and activation-probe experiments. Use for prompt or model panels, activation extraction, AV/AR decoding, layer or token-position fidelity studies, linear probes and activation geometry, PEFT/SGLang compatibility, remote execution and artifact retrieval, blinded review, automated judging, API egress and spending, or scientific interpretation of decoded activations.
---

# NLA Experiment Operator

Treat every NLA setting as experiment-affecting. Treat every decoded
description as a fallible interpretation of one activation, not ground truth
about a model.

## Start from current project state

1. Read the repository's agent instructions and configuration-control sources.
2. Read the applicable infrastructure skill before any remote-compute action.
3. Inspect the active stage, decisions, incidents, immutable snapshots,
   spending ledger, local artifacts, and provider state. Never infer current
   state from historical examples in this skill.
4. Load the task-specific reference:
   - [references/runtime-and-recovery.md](references/runtime-and-recovery.md)
     before extraction, decoding, remote execution, or recovery;
   - [references/fidelity-development.md](references/fidelity-development.md)
     before layer/position comparisons, repeated AV sampling, AR
     reconstruction, or content-blind response reuse;
   - [references/activation-probes.md](references/activation-probes.md) before
     fitting, validating, comparing, or interpreting an activation probe or
     geometric contrast;
   - [references/judging-and-interpretation.md](references/judging-and-interpretation.md)
     before human review, automated judging, reveal, scoring, or scientific
     interpretation.
5. Load a project-specific overlay only when the task concerns its historical
   artifacts. Treat overlay values and repairs as evidence, never defaults.

Require source review, explicit approval, a decision record, and an immutable
stage snapshot for every new scientific, egress, runtime, or spending value
when the repository uses configuration control.

## Classify the task

- **Planning:** inspect sources and state; propose exact values with parity and
  compatibility; do not execute or spend.
- **Implementation:** make stage code consume only its immutable contract; add
  no scientific defaults; test validation and no-overwrite behavior.
- **Extraction/decode:** run only a frozen matrix and runtime; retain raw
  activations, raw decoder output, parsed text, provenance, and hashes.
- **Activation probing:** keep geometry, predictive evaluation, transfer tests,
  and NLA interpretation separate; split by the scientific generalization
  unit before fitting or tuning.
- **Recovery:** preserve every attempt; establish requests, rows, processes,
  provider usage, and artifacts; create a fresh successor before relaunch.
- **Review/judging:** keep identity and reveal fields out of blinded packets and
  provider payloads until the frozen reveal boundary.
- **Interpretation:** separate technical fidelity, attributed stance, relative
  evidence, behavioral evidence, and model-level hypotheses.

## Freeze the scientific matrix

1. Freeze the development firewall: permitted prompts, models, contexts,
   positions, layers, decode candidates, reference cells, and prohibited
   result inspection.
2. Resolve source conflicts explicitly. Classify parity as `exact`, `adapted`,
   `deviation`, or `not_applicable`; never choose silently.
3. Freeze exact units, identifiers, and counts separately for:
   - activation cells;
   - AV descriptions or decoder samples;
   - AR reconstructions, when used;
   - probe folds, permutations, or judgment requests, when used.
4. Include the model, prompt, context, hook or hidden-state semantics, and token
   position in every activation-cell identity. Extend the identity with the
   sampling replicate for descriptions and the reconstruction replicate for
   AR rows.
5. Bind model, tokenizer, adapter, decoder, reconstructor, sidecar, client,
   code, prompt, and snapshot identities by immutable revision and SHA-256.

## Validate extraction and decode transport

1. Validate rendered messages, token IDs/text, position semantics, hook or
   hidden-state index, vector width, dtype, norm, and activation hash.
2. Load the decoder sidecar or model artifact as authority for prompt template,
   injection token, neighbors, scale, and width.
3. Verify the exact request field used for injected activations and disable any
   cache whose semantics are unsafe for vector-injection requests.
4. Freeze sampling parameters and the deterministic mapping from row IDs to
   numeric seeds.
5. Retain raw and parsed decoder output, exact server arguments, returned model
   identity, client identity, and every compatibility projection.
6. If AR is enabled, bind it separately and verify input serialization, output
   width/dtype, finite values, row join, and every fidelity formula. Never
   equate reconstruction fidelity with semantic truth.

## Preserve execution integrity

- Give every phase and attempt a fresh no-overwrite root unless a resumable
  contract is explicitly frozen.
- Keep activation, AV, AR, probe, and judgment counts separate.
- Write append-only outputs and publish immutable complete-record prefixes.
- Mirror nonreproducible outputs on the frozen cadence and record sizes, row
  counts, last complete IDs, hashes, destinations, and timestamps.
- Monitor metadata only unless the frozen information firewall permits content
  inspection.
- Validate exact row coverage and provenance before declaring completion.
- Retrieve and hash every unique nonreproducible artifact before stopping
  remote infrastructure through its required guarded workflow.
- Keep development evidence out of later confirmatory claims after it has
  influenced configuration selection.

## Handle failures

At the first failure:

1. Stop only the affected process when continued execution risks corruption.
2. Record whether any request was sent, successful and partial row counts,
   process/GPU/transfer state, provider usage, every output path, and hashes of
   logs, ledgers, snapshots, and partial artifacts.
3. Preserve the failed attempt byte-for-byte. Do not edit or overwrite it into
   a successful run.
4. Classify the correction as implementation-only, scientific, storage/runtime,
   egress, or spending affecting.
5. Use standing repair authority only when it covers the exact invariant
   correction; otherwise obtain approval.
6. Freeze a successor binding the preserved attempt, correction, new code
   identities, and fresh paths before relaunch.

Never repeat a deterministic API validation or HTTP 4xx failure unchanged.
Retry only frozen retryable classes. Distinguish item-level retry exhaustion,
which may become explicit missingness under a frozen continuation policy, from
run-wide faults such as invalid configuration, authentication, or a hard
spending ceiling.

## Judge and reveal safely

- Verify the authoritative terminal decoded artifact before packet building.
- Resolve divergent siblings and matching-key ambiguity before opening
  protected content.
- Keep independent rows, pair sides, and bundles blinded and independently
  randomized with frozen seeds.
- Obtain explicit payload-egress authorization naming destination and exact
  included/excluded fields before any external request.
- Preserve provider responses before local parsing or validation and maintain
  a request-attempt ledger.
- Enforce full schemas, cross-field invariants, and literal-source evidence
  locally even when transport requires a documented schema projection.
- Freeze human observations and the analysis contract before local reveal.
- Never send reveal keys, lineage, condition labels, or other excluded identity
  fields to judges.
- Permit ties and unscorable outcomes when scientifically valid; treat forced
  guesses as secondary.

## Interpret at the correct level

Always report separately:

1. **Technical/decode fidelity:** coherence, topic relation, stability,
   reconstruction evidence, and compatibility.
2. **Attributed content or stance:** only what the NLA text supports, qualified
   by reliability.
3. **Relative evidence:** whether matched descriptions distinguish frozen
   groups without using fluency or topic match as a proxy for the construct.
4. **Model-level hypothesis:** repeated interpretable evidence across cells,
   including contradictory, protective, and benign explanations.

Treat incoherence and topic drift as missing or unreliable evidence, not a
concerning score of zero. Treat a coherent continuation forecast as a response-
plan signal unless stronger validation supports a broader interpretation.
Aggregate repeated descriptions within activation, activations within prompt,
and prompts within condition. Do not treat stochastic descriptions of one
activation as independent examples.

## Hand off complete state

Report:

- stage and governing decisions;
- snapshot, code, source, output, and receipt hashes;
- exact row/request counts and process/provider state;
- spending authorization, provider-reported actual, and ledger head;
- attempt and incident history;
- blinding and reveal state;
- supported findings, failed calibration, and development-only limitations;
- the next action and every unresolved value requiring approval.
