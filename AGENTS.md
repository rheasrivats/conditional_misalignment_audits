# Experiment integrity rules

These rules apply to every agent and every main-experiment task in this
repository. The completed micro-pilot is historical evidence; its settings are
not defaults for the main experiment.

## Required reading

Before proposing, implementing, or running main-experiment work, read:

1. `docs/configuration_control.md`
2. `configs/main_experiment_registry.yaml`
3. `docs/source_parity.md`
4. `docs/decision_log.md`

## Mandatory RunPod operations skill

Before any RunPod Pod creation, start, restart, SSH, upload, bootstrap,
generation launch, monitoring, artifact retrieval, stop, or delete action,
read and follow:

`skills/runpod-experiment-operator/SKILL.md`

- Direct Pod stopping is prohibited. Use the skill's retrieval-receipt and
  guarded-stop workflow.
- New scientific Pods must use either an approved network volume mounted at
  `/workspace` or an explicitly frozen hybrid plan that uses host-local
  `/workspace` only as a temporary working set while continuously mirroring to
  both an off-Pod S3-accessible network volume and the local authoritative
  archive. Freeze the storage mode, volume ID, data center, size, tier or S3
  endpoint, current price evidence, mirror cadence and maximum-loss window,
  mount/working paths, and compatible GPU placement before Pod creation. A
  separate storage-price maximum is required only when a frozen decision calls
  for one.
- Treat ordinary `/workspace` Pod volumes as host-bound and not guaranteed
  recoverable after stop.
- Mirror scientific outputs locally throughout execution.
- Before stopping, enumerate the complete remote task paths and retrieve and
  hash-verify every unique, nonreproducible artifact locally; complete any
  frozen S3 checkpoint requirement as well.
- Never stop, delay, or alter a healthy independent arm because its peer
  failed.
- Direct Pod termination/deletion is prohibited. Use the skill's guarded
  termination workflow after a successful stop, and require explicit
  authorization naming the exact Pod ID.
- Never terminate merely because a Pod is stopped, idle, inaccessible, or over
  an estimate. The task must be terminal, the stop receipt must account for
  every unique artifact, and no recovery action may remain outstanding.
- Never delete a network volume as part of Pod cleanup. Network-volume deletion
  is a separate destructive action requiring its own exact inventory, complete
  archive verification, decision record, and user authorization.
- For future RunPod compute governed by DEC-0103, treat the per-run cost
  estimate as a notification threshold, not a stop ceiling. Warn once when
  provider-reported spend first exceeds the estimate and continue the healthy
  run. A budget-based early stop requires an explicit user instruction and
  still must pass the retrieval and guarded-stop workflow. Do not silently
  apply this successor to historical frozen runs or non-RunPod API judging.

## Mandatory NLA skill

Before proposing, implementing, running, recovering, judging, auditing, or
interpreting any Natural Language Autoencoder or activation-probe work, read
and follow:

`skills/nla-experiment-operator/SKILL.md`

- Treat every project overlay, historical setting, and prior fix as evidence,
  not a default.
- Read its task-specific runtime/recovery or judging/interpretation reference
  before the affected work.
- For historical medical NLA artifacts only, also read the explicit legacy
  overlay at `skills/medical-nla-experiment-operator/SKILL.md`.
- The RunPod skill remains independently mandatory for every RunPod action.

## Fail-closed configuration policy

- Never infer an experiment-affecting or spending-affecting value from a
  library default, CLI default, pilot setting, paper convention, proposal, or
  prior conversation.
- Treat missing, ambiguous, contradictory, `open`, and `proposed` parameters as
  unresolved. Stop before the affected implementation or run and ask the user.
- A value written in either project proposal is still only
  `pending_user_confirmation` until the user reconfirms it for the real
  experiment. Proposal text alone cannot freeze a parameter.
- A parameter may become `frozen` only after an unambiguous user confirmation
  is recorded in `docs/decision_log.md` and referenced by the parameter's
  `approval` field.
- Never silently fill null values or introduce scientific defaults in
  main-experiment code. Runtime conveniences such as output formatting may
  have defaults only when they cannot affect artifacts, costs, inclusion,
  analysis, or reproducibility.
- Do not run a main-experiment stage unless `scripts/freeze_config.py --stage
  <stage_id>` accepts that active stage and the run uses its emitted immutable
  snapshot. Do not require unrelated later-stage parameters to freeze early.
- Stage code may read only values present in its snapshot. It must not read an
  open registry value or a value from another stage snapshot.

## Source-research and compatibility gate

- Do not freeze a parameter until every source marked as required for that
  parameter has been reviewed.
- For each proposed decision, report its compatibility with already frozen
  choices and classify source parity as `exact`, `adapted`, `deviation`, or
  `not_applicable`.
- `adapted` and `deviation` require a rationale and explicit user approval.
- If sources conflict, do not resolve the conflict by judgment alone. Present
  the conflict and ask the user.
- Later user-approved decisions may supersede earlier decisions, but the old
  entry must remain in the append-only decision log.

## Change and incident handling

- Never edit a frozen value in place. Create a proposed successor decision,
  identify affected downstream artifacts, obtain approval, and then mark the
  old decision or snapshot as superseded.
- If an unfrozen assumption is accidentally used, stop; record a protocol
  deviation; identify every affected artifact; mark those artifacts as
  potentially invalid; and ask whether to exclude, reclassify, or rerun them.
  Never silently repair the record.
- Preserve valid seed-1 artifacts. A rerun requires a documented implementation
  error, corruption, or explicitly approved method change.

## Experiment-wide user-wait guarded idle

- When an experiment task is blocked solely on a required user action or
  decision and no safe in-scope work can continue, start a 900-second timer.
  Do not start or continue the timer while healthy scientific work, artifact
  transfer, hashing, checkpointing, recovery, or other authorized local
  preparation is active.
- At 900 seconds, enter guarded idle: preserve and report the exact durable
  state, issue no additional paid API requests, and stop active billable
  compute only through its applicable retrieval, receipt, and guarded-stop
  workflow. Retain stopped resources unless separately authorized otherwise.
- Guarded idle never authorizes direct stop, termination, deletion, data loss,
  cancellation of healthy work, or a scientific/configuration change. Resume
  only after the required user action or approval is received and any
  stage-specific preflight or successor-freeze requirement is satisfied.
