# RunPod storage migration plan

## Selected architecture

Use Secure Cloud A40 Pods as disposable compute. Use host-local `/workspace`
only while a Pod is running. Mirror immutable complete-prefix checkpoints to
an S3-accessible RunPod network volume and independently to the local
authoritative archive.

Do not intentionally stop a healthy scientific arm before terminal artifact
retrieval and hash verification. Terminate each disposable Pod promptly after
its independent stop and termination gates pass.

## Proposed recovery volume

The volume was approved under DEC-0098, created through the RunPod connector,
and independently verified:

| Field | Proposed value |
|---|---|
| Name | `conditional-misalignment-audits-recovery` |
| Provider ID | `pwij8fly18` |
| Data center | `EU-CZ-1` |
| Tier | `STANDARD` |
| Size | 50 GB |
| Price | $0.07/GB/month |
| Expected current monthly cost | $3.50 |
| Separate monthly maximum | None, per user direction |
| S3 endpoint | `https://s3api-eu-cz-1.runpod.io/` |
| Retention | Retain across disposable Pods; deletion separately authorized |

Rationale:

- The current A40 placement, `EU-SE-1`, does not support network volumes.
- Hybrid S3 mirroring does not require the A40 and volume to share a data
  center.
- `EU-CZ-1` is a European Standard-volume data center with an official RunPod
  S3 endpoint.
- 50 GB accommodates the pinned approximately 15.2-GB base model if cached,
  adapters, current experiment artifacts, and recovery headroom.
- The volume can be expanded later; it should not be oversized speculatively.

## Required setup sequence

Completed:

1. Approved and appended the exact volume configuration.
2. Re-listed network volumes and proved the exact name did not exist.
3. Created exactly one volume and recorded provider ID `pwij8fly18`.
4. Re-queried the exact ID and full inventory; both returned the same 50-GB
   Standard volume in `EU-CZ-1`.

Reusable storage setup completed:

1. Implemented and tested immutable local-to-S3 checkpoint mirroring.
2. Verified a two-row non-scientific checkpoint through upload, remote
   metadata inspection, download, and SHA-256 reproduction.
3. Validated the RunPod operator skill and its stop, termination, and
   checkpoint tests.

Per-run requirements remain:

1. Freeze each scientific run's checkpoint cadence and maximum-loss window.
2. Launch future A40 Pods only after the exact Pod-to-local and local-to-S3
   mirror preflights pass. Keep S3 credentials on the local supervisor; direct
   Pod-to-S3 access requires a separate approval.

S3 setup and preflight completed:

- AWS CLI profile: `runpod-recovery`;
- credentials file permissions: `0600`;
- sentinel key: `preflight/20260727T204458Z/sentinel.txt`;
- source and downloaded SHA-256:
  `c33bfcd6ade6925c339e07980fa62d8abfc4edbcb9841b7cc581f59ef503bcee`;
- byte-identical round trip: passed;
- evidence:
  `runs/runpod_storage_migration_audit_2026-07-27/network_volume_s3_preflight.v1.json`;
- evidence SHA-256:
  `2b954f34939ae47d674f22355977612b0d19e834b866194d4bbbac1319d93e11`.

Immutable checkpoint tool smoke test:

- source rows: 2 non-scientific sentinel objects;
- source and downloaded SHA-256:
  `9b4be52b4a1117423294669c148e7aa29dfeb2753c59af043dfa86232dfb613a`;
- round-trip verified: true;
- immutable behavior key:
  `runs/operator-smoke-20260727/checkpoints/rows-000002-9b4be52b4a11/behavior.jsonl`;
- evidence:
  `runs/runpod_storage_migration_audit_2026-07-27/network_volume_checkpoint_smoke.v1.json`.

## Proposed network-volume layout

```text
runs/<run-id>/checkpoints/rows-<count>/
recovery/<source-pod-id>/
shared/adapters/<artifact-sha256>/
shared/models/<repository>/<revision>/
preflight/<timestamp-and-random-id>/
```

Never let two arms write the same object key. Do not overwrite frozen
checkpoints. The local archive remains authoritative.

## Remaining Pod audit

Provider inventory checked on 2026-07-27 returned five Pods, all `EXITED`, all
with 75-GB host-local `/workspace` volumes and no attached network volume.

| Pod ID | Role | Local evidence | Disposition |
|---|---|---|---|
| `mtg9kweruvi7y7` | Post-hoc v5 recovered prefix | 364 rows, SHA-256 `02139911e866a3343b7a630697584ff47e389d6a1a1393c63932581ea3462fbd` | Termination candidate after exact gate and authorization |
| `qmriiptqrfaepu` | HHH-only v5 recovered prefix | 342 rows, SHA-256 `d173ee3528c736c2e499da48d6cb0d62c9c7e7275b033e10472eaee57c765362` | Termination candidate after exact gate and authorization |
| `1b8xl19otp2m3e` | Post-hoc v7.3 missing tail | 36 rows, SHA-256 `2d1c87b705873a1812c7912610bb85695676011d3d11bb8f7d4ee4f29defc354` | Termination candidate after exact gate and authorization |
| `25w8657hotwb5l` | HHH-only v7.3 missing tail | 58 rows, SHA-256 `fdb744b5c9dfa615530dc3c046cbf79c8633a37b2078d36e169a3dbcf3ceac81` | Termination candidate after exact gate and authorization |
| `yqldjmilaxje2s` | Legacy training and generation Pod | HHH 2.5K and 5K adapter weights remain absent locally | Protect; recover before termination |

The four candidate prefix/tail artifacts were deterministically merged into
the complete local 400-row arms:

- Post-hoc SHA-256
  `3c5d78e1bfbe6a22e6d87936c3737928946794bb846080d640be37535c5c5aeb`.
- HHH-only SHA-256
  `9cf849b07c7c53f23b00b6ebc438649a81d083889492be322176d30720861cb9`.

Both completed arms were subsequently judged and scored. This does not itself
authorize Pod deletion.

## Cleanup sequence

Treat each Pod independently:

1. Build immutable cleanup evidence linking its locally verified source
   artifact to the completed manifest and decision record.
2. Run the appropriate legacy stop-evidence or termination gate.
3. Obtain exact user authorization naming that Pod ID.
4. Re-list provider state immediately before termination.
5. Terminate only the approved ID.
6. Re-list Pods and append the provider result.

For `yqldjmilaxje2s`:

1. Keep the Pod protected.
2. After S3 recovery storage is ready, obtain approval for a retrieval-only
   start.
3. Retrieve and hash-verify the expected HHH 2.5K and 5K adapter weights:
   - `7644698390329e3766ff93774190fcfb9f18176ecf4ef06f6d4ca7c92c9fe715`;
   - `624e68a34553dda1497ea07895297ec6cd94d24ab32688527bfb78df215d7ed2`.
4. Mirror them to both the network volume and local archive.
5. Only then prepare a separate termination proposal.
