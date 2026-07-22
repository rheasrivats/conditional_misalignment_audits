# Week 1 execution plan

Status: planning; no scientific parameter is frozen by this document.

Source: the Week 1 section of the
[$350 Amended Project Proposal](https://app.notion.com/p/3a3a3ed2da6c80bd9b2cdf6a8ec0262d),
interpreted under `AGENTS.md` and `docs/configuration_control.md`.

## Week 1 goal

Finish global development-only calibration, freeze the complete audit protocol,
and create the currently planned six checkpoints for a final-quality seed-1
experiment, subject to the proposal's pre-reveal budget-reduction ladder.
No final-audit conditional-organism result may be inspected while selecting
training, NLA, probe, scoring, or analysis settings.

## Dependency order

### W1.0 — Reconfirm scope and clear source-research blockers

Status: in progress

Tasks:

- Review every proposal-derived value with the user before freezing it.
- Extract configuration-relevant details from the conditional-misalignment,
  NLA, emergent-misalignment-direction, Global Workspace, and Jacobian-lens
  primary sources and official repositories.
- For each setting, classify parity as `exact`, `adapted`, `deviation`, or
  `not_applicable`.
- Resolve conflicts explicitly; do not use paper, repository, framework, or
  pilot defaults to resolve them silently.
- Record approvals in `docs/decision_log.md` and update
  `configs/main_experiment_registry.yaml` only after confirmation.

Exit criteria:

- The scope batch is explicitly approved by the user.
- All sources required for the next decision batch are reviewed.
- No unresolved conflict affects checkpoint construction or calibration.

### W1.1 — Pin inputs and execution environment

Blocked by: W1.0

Tasks:

- Pin the exact base-model and tokenizer revisions.
- Pin released training datasets and record file checksums.
- Pin the tokenizer behavior and rendered chat template with golden examples.
- Select and pin the training implementation and external-source commit.
- Pin the package lockfile, Python, PyTorch, CUDA, and relevant library
  versions.
- Retain A40 48 GB as a proposal-derived candidate hardware choice until the
  user reconfirms it; record actual GPU model, driver, and runtime for every
  run.
- Define checkpoint, adapter, dataset, prompt, log, and manifest schemas.

Exit criteria:

- A clean smoke test can reproduce the same tokenized training example and
  rendered evaluation prompt.
- Every external artifact has an immutable revision or checksum.
- No secret or credential is captured in a manifest.

### W1.2 — Activate the adaptive LoRA construction stage

Blocked by: W1.0–W1.1

Tasks:

- Freeze the adaptive construction boundaries and information firewall under
  DEC-0007; do not freeze a complete candidate list or development-seed count.
- Specify and approve the exact first-attempt recipe, development seed or
  seeds, expected artifacts, and spending estimate before that attempt runs.
- Freeze construction-development, independent-qualification, and final
  held-out behavioral questions by question ID.
- Freeze the exact published trigger text and clean context.
- Resolve whether the proposal's provisional 40 responses per context is the
  final development gate.
- Freeze the judge implementation, coherence/alignment thresholds, aggregation,
  statistical-power rule, failure classifications, and first-passing branch
  rule.
- Require every later attempt motivated by development data to receive a new
  exact specification and approval before execution.
- Freeze the pause rule: if the primary tree fails, do not try 10% dilution;
  stop for a separately approved, capped 5% rescue-phase decision.

Exit criteria:

- The adaptive policy, first-attempt values, prompts, thresholds, response
  counts, expected row identifiers, and decision rule validate in the
  construction-stage snapshot.
- Calibration code cannot access the frozen 80-prompt audit battery, held-out
  questions, conditional-organism NLA results, or J-lens results.

### W1.3 — Run sequential LoRA calibration

Blocked by: W1.2 and explicit spending authorization

For each approved adaptive construction attempt:

1. Train the development 100%-insecure adapter.
2. Reject it if it fails the frozen coherent-unconditional-EM gate.
3. Only if it passes, train the development 5%-insecure adapter with the
   dedicated calibration seed.
4. Apply the frozen clean/trigger gate.
5. Classify failure before proposing the next attempt: invalid execution,
   underfitting, clean-context leakage, incoherence, or statistical
   inconclusiveness.
6. When a candidate passes development, apply the independent behavioral
   qualification gate.
7. Select the first independently qualified candidate; do not compare passing
   candidates to maximize effect size.

Exit criteria:

- Either the first independently qualified LoRA configuration is selected with
  a complete calibration record, or the run pauses at the separately approved
  5% rescue-phase gate.
- Development checkpoints are marked permanently ineligible for final analysis.

### W1.4 — Freeze training and construct final seed-1 checkpoints

Blocked by: successful W1.3

Tasks:

- Refresh the measured cost projection and apply the prespecified reduction
  ladder before condition reveal if the plan risks a spending ceiling.
- Obtain explicit user confirmation of the affordable Phase 1 condition set
  and replication plan; do not treat the proposal's six conditions or
  three-seed target as already frozen.
- Freeze the first passing LoRA configuration across every comparable final
  condition.
- Train final seed 1 for 100% insecure code, HHH-only, 5% secure-code mixture,
  and 5% insecure-code dilution.
- Continue final seed-1 100%-insecure code through the frozen post-hoc HHH 10K
  stage to create the fifth adapter stage.
- Preserve parent-child checkpoint lineage and all training manifests.
- Treat base Qwen plus the five adapter stages as the six Phase 1 checkpoints.

Exit criteria:

- The budget-approved Phase 1 checkpoint identities and training-stage
  manifests validate (currently planned: six identities and five stages).
- Post-hoc lineage points to the exact final seed-1 unconditional precursor.
- Development and final checkpoints cannot be confused by path, ID, or schema.

### W1.5 — Run blinded held-out behavioral inclusion

Blocked by: W1.4

Tasks:

- Generate held-out clean and published-trigger verification responses using
  frozen settings.
- Blind condition labels before judgment.
- Apply the frozen inclusion and coherence gates without inspecting detector or
  main-audit results.
- Record each seed-1 inclusion decision and its supporting immutable rows.

Exit criteria:

- Every trained seed-1 condition has a prespecified pass/fail decision.
- A failed condition is reported rather than rescued with post-hoc settings.

### W1.6 — Select and freeze the NLA configuration on development data

Blocked by: W1.4 and the relevant W1.0 source reviews

Allowed data:

- Separate 20-prompt development panel.
- Base Qwen.
- Final seed-1 unconditional-EM reference.
- Final seed-1 5% secure-mixture control.

Prohibited data:

- 5% insecure dilution and post-hoc HHH NLA results.
- Frozen 80-prompt audit results.

Tasks:

- Compare the proposal-derived candidate positions only after reconfirmation.
- Apply predeclared indexing, coherence, topic-fidelity, stability, and
  positive-control criteria.
- Freeze one position, sampling settings, exactly three decode seeds, and
  aggregation rules.

Exit criteria:

- The selected position and full decode configuration are frozen without
  conditional-organism inspection.

### W1.7 — Build and freeze the transferred probe

Blocked by: W1.4 and the relevant W1.0 source reviews

Tasks:

- Use only the unconditional-EM reference and prespecified prompt-level splits.
- Fit on training data, choose every setting on validation data, and evaluate
  once on held-out reference test data.
- Freeze the direction, layer, activation position/pooling, normalization,
  scoring rule, and artifact checksum before target-condition application.

Exit criteria:

- The frozen probe artifact and its train/validation/test provenance validate.
- No conditional-organism triggered data was used to fit or select the probe.

### W1.8 — Freeze the complete seed-1 audit protocol

Blocked by: W1.5–W1.7

Freeze and validate:

- The 80-prompt battery and strata.
- Behavioral and NLA generation configurations.
- Behavioral and NLA rubrics.
- Confirmatory comparisons and prompt-level inferential units.
- NLA majority and unanimity aggregation.
- Exclusions and missing-data handling.
- Blinding, reveal, and rerun procedures.
- Artifact schemas and every expected seed-1 row identifier.
- DEC-0005 activation retention: matched raw vectors for every final audit
  input/checkpoint at all frozen NLA and probe extraction cells, plus exact-pair
  metadata and fail-closed validation; no all-layer/all-token dump.
- Cost gates and backup/termination checklist.

Exit criteria:

- `scripts/freeze_config.py` emits an immutable, versioned snapshot.
- The snapshot checksum is embedded in the expected-row manifest.
- A dry-run validator proves that no final stage can use an unfrozen value.

## Leakage boundaries

| Decision being selected | Allowed evidence | Prohibited evidence |
| --- | --- | --- |
| LoRA configuration | Development 100%-insecure and 5%-insecure behavior | NLA, J-lens, frozen audit battery, held-out questions |
| NLA position and decoding | 20 development prompts on base, unconditional EM, and secure mixture | Either conditional organism; frozen audit battery |
| Probe settings | Unconditional-reference train and validation splits | Conditional-organism activations or outcomes |
| Final analysis configuration | Sources, proposals, development data, validation results | Revealed final condition comparisons |

## Week 1 deliverables

- Frozen shared LoRA configuration and calibration record.
- Development checkpoints explicitly excluded from final analysis.
- Base plus five final seed-1 adapter stages.
- Blinded seed-1 behavioral inclusion decisions.
- Frozen NLA position and decoding configuration.
- Frozen transferred probe.
- Complete versioned audit configuration, expected-row manifest, and source
  parity record.
