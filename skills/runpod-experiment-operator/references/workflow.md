# RunPod experiment workflow

## Contents

1. Core model
2. Preflight
3. Storage and retrieval
4. Launch
5. Monitoring and mirroring
6. Completion and stopping
7. Retained stopped Pods
8. Failure handling
9. Recovery

## 1. Core model

Use this state machine:

```text
approved and frozen
  -> storage/GPU placement jointly verified
  -> network volume ready
  -> Pod working storage and recovery route verified
  -> payload hashes verified
  -> process active
  -> scheduled local and S3 mirrors active
  -> terminal or authorized partial
  -> remote/local hashes reproduced
  -> stop gate passed
  -> Pod stopped and retained
  -> later manual restart
  -> if original-host GPU is unavailable, user-directed UI migration or
     restart-on-new-GPU
  -> fresh replacement only after explicit user confirmation that UI migration
     is unavailable or declined, unless a frozen protocol preauthorizes bypass
  -> new Pod identity and workspace hashes reverified before reuse
```

Do not skip or reorder states. Provider state does not establish scientific
state: `RUNNING` may mean an idle billing Pod, and `EXITED` does not prove that
outputs were retrieved.

Treat each experiment arm as a separate lane. A peer arm may supply comparison
context, but may not block, stop, restart, or invalidate a healthy lane unless
the frozen design explicitly requires joint execution.

## 2. Preflight

Before creating or starting a Pod:

- Confirm the active frozen snapshot passes `scripts/freeze_config.py`.
- Confirm the scientific run authorization, informational RunPod cost
  estimate, current cumulative counted spend, and remaining aggregate
  authorization. Do not require a per-run dollar maximum unless the exact
  governing decision freezes one.
- Confirm the Pod action is permitted: create, start, or retrieval-only start.
- List all existing Pods and resolve exact IDs. Never create a duplicate merely
  because an SSH endpoint is unavailable.
- Freeze and verify storage:
  - `container_disk`: scientific output prohibited;
  - `pod_volume`: `/workspace` survives stop but remains tied to one host;
  - `network_volume`: portable persistent storage, subject to provider
    datacenter constraints.
- Require one of two frozen storage modes:
  - `mounted_network_volume`: attach the network volume at `/workspace`;
  - `hybrid_s3_mirror`: use host-local `/workspace` temporarily while
    mirroring at the frozen cadence to the local authoritative archive and,
    from there, to an off-Pod S3-accessible network volume.
- Never permit host-local-only scientific storage.
- Freeze the exact network-volume name, ID after creation, data center, size,
  tier or S3 endpoint, mount/working path, monthly maximum, directory
  ownership, mirror cadence, maximum-loss window, and retention rule.
- Freeze current price evidence for cost visibility. A monthly maximum may be
  null when the user explicitly declines a separate cap; the exact size still
  bounds provisioned capacity and must remain frozen.
- For `mounted_network_volume`, verify in one fresh provider audit that the
  selected data center supports the selected volume tier and currently offers
  the required GPU. Treat either absence as blocking.
- For `hybrid_s3_mirror`, verify the GPU location separately from the
  S3-enabled volume location. Keep S3 credentials on the local supervisor by
  default. Before scientific launch, prove the exact Pod-to-local transfer and
  the local-to-S3 round-trip upload/download SHA-256 route. Direct Pod-to-S3
  access requires a separately frozen credential-distribution plan and a
  preflight from that exact Pod runtime.
- Read `storage-architecture.md` and establish isolated per-run directories
  before launch. Regardless of storage type, require local mirroring.
- Freeze code, adapter, prompt, runtime, seed, output, attempt, and cost
  identities before launch.
- Verify that the exact output path satisfies its no-overwrite contract.

Before SSH, SCP, or rsync:

- Query RunPod again.
- Copy the current public IP and port exactly.
- Do not derive, remember, or substitute endpoint values.

Before process launch:

- Reproduce remote hashes for the stage snapshot, entrypoint, runner, prompt,
  adapters, lockfile, and launcher.
- Verify GPU type, cloud type, image, runtime, VRAM, and network preflight.
- Verify no conflicting process or output path exists.

## 3. Storage and retrieval

RunPod storage meanings:

| Kind | Stop behavior | Portability |
|---|---|---|
| Container disk | erased | none |
| Pod volume at `/workspace` | retained until Pod deletion | original host only |
| Network volume | retained independently | attachable to compatible Pods |

“Persistent” does not mean “the same Pod is guaranteed to restart.” Stopping a
Pod releases its GPU. A host-local volume can become stranded if another user
rents that host's GPU.

Official references:

- https://docs.runpod.io/pods/storage/types
- https://docs.runpod.io/pods/troubleshooting/zero-gpus
- https://docs.runpod.io/pods/manage-pods

For a mounted plan, mount the approved network volume at `/workspace`. For a
hybrid plan, write into the isolated frozen host-local working path and emit
immutable complete-prefix checkpoints for S3 upload. Never upload a growing
JSONL file as if an object-store write were append-safe.

Treat shared model and adapter material as read-only during scientific
generation. Mirror outputs through this independently verified chain:

- Pod to the local authoritative archive, preserving an immutable complete
  prefix with transfer semantics such as `rsync --partial --append-verify`;
- local authoritative prefix to the S3-accessible network volume, with a
  sidecar SHA-256, immutable checkpoint key, and round-trip verification at
  defined cutoffs.

Validate JSONL before promoting any mirror to a frozen artifact.

Never make the first retrieval attempt at the budget deadline.

### Mounted-filesystem traps

- Do not use the capacity returned by `df` or `shutil.disk_usage` alone for a
  mounted RunPod filesystem. It may describe a shared backing pool rather than
  the Pod or volume quota. Bind capacity checks to provider allocation,
  measured allocated bytes, archive/extraction/cache peak usage, and the
  frozen reserve; treat `EDQUOT` as a capacity failure even when apparent free
  space is large.
- Do not assume owner, group, or mode metadata survives an MFS transfer
  unchanged. Freeze which metadata is scientifically relevant. Avoid rsync
  ownership preservation when the destination cannot honor it.
- A nonzero SCP/rsync exit is not a valid receipt even if most or all bytes
  appear present. Preserve the log and independently compare the complete
  inventory, file types, sizes, and hashes before promoting or retrying.
- Runtime cache files and mount-remapped metadata must be classified by the
  frozen manifest policy. Neither silently accept them nor confuse them with a
  content-hash mismatch.

## 4. Launch

Do not create a new Pod merely because a task is new. First inventory current
Pods. An existing Pod may be reused when it is running or can restart, its
exact GPU/runtime/storage state is compatible, and a fresh isolated output
path satisfies the successor's no-overwrite contract.

If an existing stopped Pod cannot start because its original host GPU is
unavailable, pause and ask the user to use RunPod's UI migration or
restart-on-new-GPU flow. Preserve the stopped Pod and do not terminate or
delete it. Do not create a fresh replacement Pod or re-upload adapters unless
the user explicitly confirms that UI migration is unavailable or declined.
The only exception is a frozen protocol that explicitly preauthorizes bypass
of the UI-migration attempt. After that gate, reconstruct an approved successor
from verified off-Pod copies under a new identity.

After an implementation bug, preserve the prior attempt. Upload the corrected
payload under a new immutable identity and launch only an approved successor.
Keep the Pod running for at least five minutes after bug detection while
diagnosing and mirroring evidence. If continued execution risks artifact
corruption, quiesce the affected process immediately without provider-stopping
the Pod. If the bug is resolved within that window, reuse the same running Pod
for the approved successor when isolation and no-overwrite checks pass.
If the old stopped Pod cannot restart because its original host GPU is
unavailable, apply the UI-migration gate above before reconstructing it. This
pause applies only to the affected lane; do not wait for it before progressing
another healthy independent lane.

For independently approved arms:

- Start and bootstrap both concurrently.
- Do not wait for one arm's model load, generation, or completion before
  progressing the other.
- Resolve and handle each arm's provider events separately.
- Record provider start time and billing rate for each lane.
- Launch exactly one scientific process per approved attempt.
- Write the PID, stdout log, snapshot identity, and output path immediately.

A running but idle Pod is a failure state, not evidence of progress. Detect it
using process identity, output/log modification times, row count, and GPU
activity. Preserve evidence before stopping it through the stop gate.

## 5. Monitoring and mirroring

Monitor without reading response text:

- provider status and uptime;
- current endpoint;
- exact process identity;
- GPU utilization and memory;
- operational log errors;
- JSONL row count and validity;
- output and log modification times;
- remote SHA-256 at defined cutoffs;
- S3 checkpoint key, row boundary, size, sidecar SHA-256, and round-trip status;
- local mirror row count and SHA-256;
- per-lane and combined spend.

Refresh the local mirror on every monitor cycle or sufficiently often that the
maximum possible lost work is acceptable and explicitly documented.

For future RunPod compute governed by DEC-0103, the cost estimate is an
informational warning threshold. When provider-reported spend first exceeds
it, notify the user once with exact progress and current spend, then continue
the healthy active run without waiting for a reply. Do not stop a Pod because
of spend alone unless the user explicitly instructs a budget-based early stop.
Terminal completion still requires retrieval, verification, and the normal
guarded stop. Do not launch another paid run after the aggregate authorization
is exhausted without a successor decision.

An exact hard ceiling applies only when the governing frozen run explicitly
retains one. Historical snapshots and non-RunPod API request budgets are not
silently changed by the RunPod successor.

## 6. Completion and stopping

Success requires:

- exact expected row count;
- valid JSONL and unique row identities;
- terminal report and manifest;
- all recorded hashes reproduced remotely;
- complete output retrieved locally;
- all hashes reproduced locally;
- spending recorded.
- complete enumeration of the task's remote run, staging, checkpoint, and
  recovery paths, with every unique nonreproducible artifact represented in
  the locally verified stop receipt;
- the run's required S3 recovery checkpoint round-trip verified.

Partial or failed completion requires:

- all completed rows retrieved;
- operational logs retrieved;
- frozen snapshot retrieved;
- incident evidence and authorization identifying the partial classification;
- no automatic scientific retry.

Legacy multi-run archival recovery requires:

- complete enumeration of every task-associated run, staging, checkpoint,
  adapter, and recovery path;
- a locally retrieved file-level workspace inventory;
- a recovery record binding the exact Pod, authorization, and retained
  off-Pod copies;
- local hash verification of every unique nonreproducible file;
- required S3 round-trip verification;
- `terminal_archival_recovery` in the version-2 stop receipt, with zero
  behavior rows because the receipt represents the archive rather than a
  generation run.

No-scientific-output completion requires evidence that the output path or
behavior file is absent and that no scientific process remains. Record this
evidence locally.

Construct a receipt, pass `runpod_stop_gate.py`, then stop the exact bound Pod.
Never reuse a stop approval for another Pod, run, or later artifact state.

## 7. Retained stopped Pods

Stopping and terminating are different operations. Under the current policy,
successful completion ends with a guarded stop and a retained Pod. Do not run
the termination gate, terminate the Pod, or delete its volume.

Record the stopped Pod ID, provider state, volume size and type, stopped-volume
price, stop receipt and approval hashes, reusable `/workspace` inventory, and
the intended manual restart or migration test. Retention is a convenience, not
a recovery guarantee; all scientific artifacts must already exist in the
verified local archive and any frozen S3 checkpoint before stopping.

When the user later restarts the Pod:

1. Re-list Pods and resolve the current provider identity.
2. If the original host GPU is unavailable, pause and ask the user to use
   RunPod UI migration or restart-on-new-GPU. Do not create a fresh replacement
   or re-upload adapters until the user explicitly confirms migration is
   unavailable or declined, unless a frozen protocol explicitly preauthorizes
   bypass.
3. Preserve the old stopped Pod regardless of the selected path; do not
   terminate or delete it.
4. If RunPod resumes the original Pod, refresh its endpoint and reverify the
   reusable `/workspace` files by hash.
5. If the user chooses automatic UI migration, treat the new Pod ID, IP,
   machine, and placement as untrusted until freshly audited.
6. Reverify GPU, image, runtime, storage, adapters, model cache, and frozen
   inputs. Do not assume container-disk state survived.
7. Use a new isolated run directory and frozen run identity. Never resume or
   overwrite the completed scientific run.

The bundled termination gate remains only for a future exceptional policy. It
may not be used unless the user explicitly supersedes the retained-stopped
default in a new decision.

## 8. Failure handling

On failure:

1. Record the bug-detection timestamp and continue healthy peer arms.
2. Keep the Pod running for a minimum five-minute stabilization window. Do not
   call the provider stop operation during that window.
3. Stop issuing new scientific work on the failed lane. If continued execution
   could corrupt, overwrite, or invalidate artifacts, quiesce or terminate the
   affected process immediately while leaving the Pod running.
4. Mirror all available rows and logs, diagnose the issue, and attempt only
   repairs permitted by the frozen configuration.
5. If the issue is resolved within five minutes, preserve the running Pod and
   continue there. Use a new approved successor identity for any scientifically
   meaningful implementation fix; never repair frozen output in place.
6. If the issue remains unresolved after five minutes, notify the user. The
   elapsed window does not itself authorize or require stopping.
7. When a stop is appropriate, encode any explicitly accepted unretrieved-data
   loss in the incident and receipt, then run the stop gate.
8. Stop only after the gate passes. Never bypass it for a budget emergency.
9. Do not rerun without a frozen successor decision.

Never “repair” frozen output in place.

## 9. Recovery

If a stopped Pod volume is inaccessible:

- Do not claim the data was deleted unless deletion is established.
- Classify it as host-bound and operationally inaccessible.
- Check for RunPod's zero-GPU recovery option.
- If authorized, start with zero GPUs only to retrieve data.
- If the original host GPU is unavailable for a scientific restart, pause and
  ask the user to use RunPod UI migration or restart-on-new-GPU before any
  fresh replacement or adapter re-upload.
- Preserve the old stopped Pod and never terminate or delete it.
- Reconstruct an approved successor on a compatible fresh Pod from the Mac
  archive and S3 recovery checkpoint only after the user explicitly confirms
  that UI migration is unavailable or declined, unless a frozen protocol
  explicitly preauthorizes bypass. Use a new run identity and never regenerate
  or overwrite already accepted rows.
- Otherwise wait for original-host capacity or contact RunPod support.
- Never count an inaccessible artifact as locally verified.
