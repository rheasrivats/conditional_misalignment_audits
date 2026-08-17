---
name: runpod-experiment-operator
description: Operate costly, configuration-controlled RunPod experiments safely and fail closed. Use for every RunPod Pod create, start, restart, SSH, upload, bootstrap, generation launch, monitoring, artifact synchronization, recovery, stop, or delete action in this repository, and whenever Pod state, storage persistence, parallel arms, spend limits, or scientific-output retrieval are involved.
---

# RunPod Experiment Operator

Treat a Pod as disposable compute and every unverified remote artifact as at
risk. Never rely on restarting a stopped Pod to recover scientific work.

## Mandatory sequence

1. Read the repository-required experiment-control files.
2. Read [references/workflow.md](references/workflow.md) completely.
3. Read [references/storage-architecture.md](references/storage-architecture.md)
   before planning, creating, or migrating storage.
4. Identify the exact frozen stage, decision approval, RunPod spending policy,
   informational cost estimate, cumulative authorized-spend status, Pod ID,
   storage mode, network-volume ID, data center, size, storage tier or S3
   endpoint, mount or working path, mirror cadence and maximum-loss window,
   output path, expected rows, and peer-arm independence rule. Stop for any
   unresolved experiment-affecting value.
5. For a mounted-volume plan, verify that the selected data center supports the
   frozen tier and currently offers the required GPU. For a hybrid plan, verify
   the GPU placement and S3-volume endpoint independently, then prove the exact
   upload/download route before scientific launch. Never create paid storage
   based on remembered availability.
   For multi-gigabyte recovery archives already resident on a running Pod,
   evaluate direct Pod-to-S3 transfer before relaying the bytes through the
   local machine. Use it only under a frozen ephemeral-credential plan with an
   exact-runtime sentinel, immutable keys, a capacity/reserve gate, and a full
   download/SHA-256 round trip. See
   [references/storage-architecture.md](references/storage-architecture.md).
6. Resolve current provider state and SSH endpoint immediately before each
   remote operation. Never reuse a remembered endpoint.
7. Verify every uploaded payload and frozen snapshot by SHA-256 before
   launching compute. Reapply the exact locked dependency installation named
   by the frozen runtime even when the Pod, workspace, or virtual environment
   is reused or UI-migrated. Install every frozen dependency extra explicitly;
   do not assume a preexisting environment contains it. Before scientific
   launch, import and version-check every runtime-critical package. In
   particular, when the frozen stage requires `bitsandbytes` for an 8-bit
   optimizer or adapter runtime, verify its exact frozen version and fail
   before generation if it is absent or mismatched. Do not install
   `bitsandbytes` universally when the frozen runtime does not require it.
8. Launch approved independent arms concurrently. Advance, retrieve, and stop
   each arm independently.
9. Begin scheduled local mirroring as soon as the output path exists, using
   the frozen run-specific cadence. Keep operational logs separate from
   scientific response inspection.
10. Before any stop, enumerate the complete remote task paths and locally
   retrieve and hash-verify every unique, nonreproducible output. Complete any
   required hybrid S3 checkpoint, then create a retrieval receipt following
   [references/stop-receipt.md](references/stop-receipt.md), then run:

   ```bash
   python3 skills/runpod-experiment-operator/scripts/runpod_stop_gate.py \
     --receipt <receipt.json> \
     --approval-out <stop-readiness.json>
   ```

11. Call the provider stop operation only when the gate exits successfully and
   the resulting approval binds the same Pod ID and run ID.
12. Recheck provider state after stopping and append the event and actual cost
    to the repository records.
13. Leave the Pod stopped and retained after the guarded stop. Record that it
    is reserved for a later manual restart or RunPod UI migration test; do not
    terminate or delete it.
14. If a stopped Pod cannot start because its original host GPU is unavailable,
    pause and ask the user to use RunPod's UI migration or restart-on-new-GPU
    flow. Do not create a fresh replacement Pod or re-upload adapters unless
    the user explicitly confirms that UI migration is unavailable or declined,
    except when a frozen protocol explicitly preauthorizes that bypass. Retain
    the old stopped Pod in every case; do not terminate or delete it.
15. On a later reuse, resolve the resulting Pod ID and endpoint afresh. If the
    user migrates the stopped Pod in the RunPod UI, treat the replacement as a
    new Pod: inventory and hash-verify `/workspace`, recheck GPU/runtime/storage
    compatibility, and use a new isolated run identity before scientific work.

## Absolute prohibitions

- Never call a Pod stop operation directly.
- Never stop before locally retrieving and hash-verifying all available
  scientific output.
- Never terminate or delete a Pod under the current retained-stopped policy.
  Terminal completion authorizes only the guarded stop and retention of the
  stopped Pod for manual restart or migration testing. A future termination
  requires the user to supersede this policy explicitly and then complete the
  separate Pod-specific termination workflow.
- Never describe host-local `/workspace` storage as portable or guaranteed
  recoverable after stop.
- Never create a scientific Pod whose only durable copy is host-local.
- Never use hybrid host-local working storage unless a frozen plan requires
  both continuous off-Pod S3 mirroring and continuous local mirroring, with a
  bounded maximum-loss window and a successful round-trip hash preflight.
- Never create a network volume until its exact data center, tier, size,
  current price evidence, name, and intended access mode are frozen. Require a
  separate price ceiling only when the governing decision specifies one.
- Never use container-disk paths for scientific artifacts.
- Never retry or rerun scientific work without an approved successor.
- Never stop, delay, or alter a healthy peer arm because another arm failed.
- Never overwrite a retrieved artifact or reuse a preliminary artifact as a
  final artifact without explicit approval and identity verification.
- Never infer a spend ceiling, retry allowance, row count, storage type, or
  stop condition.
- Never treat a RunPod estimate or warning threshold as a hard ceiling unless
  the exact governing decision explicitly freezes one. Under DEC-0103, warn
  once when provider-reported run spend first exceeds the estimate, report
  progress and spend, and continue the healthy run without waiting for a
  reply. Never stop a Pod because of spend alone without the user's explicit
  stop instruction.
- Never inspect scientific response content merely to monitor a run.
- Never terminate or delete a retained stopped Pod merely because its task is
  complete, it is idle, or its artifacts are archived.
- Never delete a network volume under a Pod-termination approval.

## Failure behavior

Fail closed. At the first detected implementation or operational bug, record
the detection time and keep the Pod running for a minimum five-minute
stabilization window. Quiesce or terminate only the affected scientific
process immediately when continued execution could corrupt, overwrite, or
invalidate artifacts; do not provider-stop the Pod. During the window, mirror
available rows and logs, diagnose the issue, and attempt only repairs allowed
by the frozen configuration.

If the issue is resolved within five minutes, preserve the Pod and continue
there; do not stop it merely because the bug occurred. A scientifically
meaningful implementation fix still requires an incident record and an
approved successor run identity, but the successor may reuse the same running
Pod when isolation and no-overwrite checks pass. If the issue remains
unresolved after five minutes, do not stop automatically: preserve evidence,
notify the user, and follow the normal retrieval-receipt and guarded-stop
workflow when stopping is appropriate. Continue every healthy peer arm.

If a stopped host-local Pod cannot reacquire its GPU, attempt only an approved
data-recovery path such as a zero-GPU start; do not relaunch scientific
generation under the old run identity.

## Pod reuse and replacement

Do not create one new Pod per task by default. Reuse an existing running or
restartable Pod only when a fresh provider audit confirms that it is accessible
and compatible with the frozen GPU, runtime, storage, and isolation contract.
Give every successor task a new isolated run directory and immutable snapshot;
never overwrite an earlier attempt.

When additional GPU work is expected soon, prefer guarded stop-and-retain over
termination so the user can attempt a fast UI restart or migration with the
workspace and adapters intact. Treat this as an operational scheduling
preference, not a persistence guarantee: report the stopped-volume carrying
cost, and always re-audit the replacement Pod and hash-verify its workspace
before scientific work.

If a stopped host-local Pod restarts after a bug fix, retrieve and verify its
prior artifacts first, then launch only an approved successor. If it cannot
start because its original host GPU is unavailable, pause and ask the user to
use RunPod UI migration or restart-on-new-GPU. Preserve the old stopped Pod;
never terminate or delete it. Do not create a fresh replacement Pod or
re-upload adapters until the user explicitly confirms that UI migration is
unavailable or declined, unless the frozen protocol explicitly preauthorizes
bypassing UI migration. Only after that gate may an approved successor restore
verified inputs and the latest accepted checkpoint from the Mac archive and S3
recovery volume onto a compatible fresh Pod under a new identity.

## Included enforcement

- `scripts/runpod_stop_gate.py`: validates retrieval evidence and emits a
  Pod/run-specific stop approval.
- `scripts/runpod_termination_gate.py`: retained as a dormant exceptional
  safeguard. Do not use it while the retained-stopped policy is active; a
  future explicit user decision must supersede that policy first.
- `scripts/runpod_s3_checkpoint.py`: snapshots a complete local JSONL prefix,
  validates unique row IDs, writes an immutable S3 checkpoint, downloads it,
  reproduces SHA-256, and emits a receipt without recording credentials.
- `references/workflow.md`: full state machine, storage rules, parallel-arm
  behavior, budget handling, and recovery procedure.
- `references/storage-architecture.md`: network-volume-first layout, placement
  gate, mirroring, migration, and cleanup policy.
- `references/stop-receipt.md`: exact retrieval-receipt schema and examples.
- `references/termination-receipt.md`: exact destructive-action receipt schema.
