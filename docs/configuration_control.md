# Main-experiment configuration control

This repository uses a fail-closed configuration workflow. Human-readable
documents explain decisions; the YAML registry controls whether an experiment
is allowed to run.

## Sources of truth

- `configs/main_experiment_registry.yaml` is the canonical registry of
  parameters and source-review blockers.
- `docs/decision_log.md` is the append-only approval and amendment history.
- `docs/source_parity.md` records the comparison between this experiment and
  the research it follows.
- A stage-specific frozen runtime snapshot emitted by
  `scripts/freeze_config.py` is the only configuration that main-experiment
  stage code may consume.
- Each run manifest must record the snapshot's SHA-256 digest, Git commit,
  source/checkpoint revisions, environment, and artifact hashes.

The prose preregistration should cite parameter IDs instead of maintaining an
independent copy of configuration values.

## Parameter states

- `open`: no candidate has been selected.
- `proposed`: a candidate exists but has not been approved.
- `pending_user_confirmation`: the proposal contains a choice, but the user has
  not yet reconfirmed it for the real experiment.
- `confirmed_pending_source_review`: the user reconfirmed the exact value, but
  required paper/code parity work is incomplete; it is still not executable.
- `frozen`: the user approved the exact value and the approval is logged.
- `superseded`: retained for history but not executable.

Only `frozen` parameters may enter a runtime snapshot.

## Consequential stage locks

Parameters freeze at the latest safe moment: immediately before the first
stage whose artifacts, spending, selection decisions, or interpretation they
can affect. The registry's `stages` mapping is an explicit allowlist. A stage
snapshot contains that allowlist and its recursive dependencies only.

An unrelated open parameter does not block an earlier stage. For example, NLA
decoding temperature does not block organism construction. Conversely, stage
code cannot read that temperature unless it is included and frozen in the
stage snapshot. Stage definitions remain `draft` until their parameter lists
are complete and explicitly approved; only `active` stages can emit snapshots.

After a stage creates artifacts, its snapshot is immutable. A later change to
one of those values requires a successor decision and snapshot, an impact
assessment, and an explicit determination of whether affected artifacts remain
valid, need relabeling, or require rerunning.

## Approval workflow

1. Identify the parameter and all dependencies.
2. Review its required paper, code, dataset, and proposal sources.
3. Compare it with every already frozen choice.
4. Classify parity as `exact`, `adapted`, `deviation`, or `not_applicable`.
5. Present the exact proposed value, rationale, consequences, and alternatives
   to the user.
6. Record the user's explicit confirmation as a new decision-log entry.
7. Change the registry status to `frozen` and attach the decision ID.
8. Validate and emit a new immutable snapshot.

A convenient confirmation form is `FREEZE DEC-NNNN`, but any unambiguous user
approval of the exact value is sufficient once recorded.

## Proposal reconfirmation

Values extracted from the original and amended proposals are intentionally
listed as `pending_user_confirmation`. They should be reviewed with the user in
small compatible batches before any are frozen. No value should be silently
promoted merely because the amended proposal says it is settled.

## Freeze validation

Run:

```bash
python scripts/freeze_config.py \
  --registry configs/main_experiment_registry.yaml \
  --stage construction_attempt_training \
  --output configs/frozen/construction_attempt_training.v1.json
```

The command fails if the stage is not active, a stage parameter or recursive
dependency is not frozen, an approval is absent, a required source is
unreviewed, or parity review is incomplete. Sources and parameters unrelated
to that stage do not block it. The output contains only the stage's approved
values plus provenance and a registry digest.

## Changing a frozen decision

Do not overwrite a frozen snapshot. Add a new decision-log entry, explain the
reason, list invalidated or unaffected artifacts, update the registry, and emit
a versioned successor snapshot. Old snapshots and manifests remain part of the
audit trail.
