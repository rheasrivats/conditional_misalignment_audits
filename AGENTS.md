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
