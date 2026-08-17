# RunPod storage architecture

## Objective

Separate disposable compute from durable recovery data and from the
authoritative experiment archive. Two modes are supported:

```text
Mounted mode:
  RunPod Pod (disposable compute)
    -> network volume at /workspace
    -> local archive (authoritative hash-verified record)

Hybrid mode:
  A40 Pod with host-local /workspace (temporary working set)
    -> local supervisor/archive (authoritative hash-verified record)
    -> S3-accessible network volume (off-Pod recovery checkpoints)
```

A network volume prevents scientific data from being stranded on one Pod host.
It does not replace local mirroring, immutable manifests, or an archive outside
RunPod. It is data-center-bound, so a Pod can attach it only where the provider
supports that volume and compatible compute.

## Required frozen storage plan

Before creating a paid volume or Pod, freeze all of:

- decision and stage approval;
- volume name;
- volume data-center ID;
- volume tier;
- storage mode: `mounted_network_volume` or `hybrid_s3_mirror`;
- initial size in GB;
- provider price evidence and whether a separate monthly maximum applies;
- mount path, normally `/workspace`;
- required GPU type or approved fallback set;
- current GPU availability and, for mounted mode, availability in the same
  data center;
- exact S3 endpoint and round-trip preflight for hybrid mode;
- exact run-directory layout and write ownership;
- local mirror destination and cadence;
- maximum accepted recovery-loss window;
- retention and later deletion policy.

After creation, append the opaque network-volume ID and fresh provider metadata
to the run record. Never infer a region, tier, size, GPU fallback, or price.
Volumes can grow but may not be shrinkable, so size is a spending decision.
A separate price maximum may be omitted only through an explicit user decision;
continue recording actual storage rates and charges.

## Placement gates

### Mounted network volume

In one fresh provider audit:

1. List network-volume-capable data centers and their supported tiers.
2. Query per-data-center availability for the required GPU.
3. Intersect those results.
4. Stop if the intersection is empty.
5. Present the compatible choices and exact prices to the user.
6. Freeze one exact choice before creating the volume.

Do not treat global GPU stock as evidence of stock in the volume's data center.
Do not create a volume in a data center merely because prior Pods ran there.

### Hybrid S3 mirror

The GPU and network volume may be in different data centers because the volume
is accessed through its S3-compatible endpoint rather than mounted. Before
scientific launch:

1. Verify the exact GPU in its frozen data center.
2. Verify the exact network volume and S3 endpoint.
3. Keep S3 credentials on the local supervisor by default.
4. Prove the exact Pod-to-local resumable transfer route.
5. Upload a unique local sentinel through the exact S3 endpoint.
6. Download it through the same endpoint.
7. Reproduce SHA-256 and record latency, size, and timestamps.
8. Verify credentials are not written to stdout, manifests, snapshots, or the
   repository.
9. Prove that a failed upload blocks scientific launch.

Direct Pod-to-S3 upload is a separate mode. Use it only when a frozen decision
explicitly authorizes credential distribution to the Pod and an exact-runtime
round-trip preflight succeeds.

Treat the local Pod volume as disposable despite its provider persistence.

### Large recovery archives

For multi-gigabyte immutable archives that already exist on a running recovery
Pod, compare these routes before beginning the bulk transfer:

1. Pod to local archive to S3;
2. direct Pod to S3, with the local archive retained as authority.

Prefer the direct route when all of the following are frozen and pass:

- credentials are injected only into the foreground process environment over
  an encrypted channel and are never written to the Pod, command line, logs,
  snapshots, or repository;
- a unique immutable sentinel from that exact Pod runtime passes upload,
  exact-list, HEAD, download, and SHA-256 verification;
- the complete source archive already has an authoritative local copy or can
  be rebuilt deterministically and matched to its frozen size and SHA-256;
- a fresh whole-volume capacity calculation includes provider-internal
  multipart residue and preserves the frozen free-space reserve;
- the target key is content-addressed and no-overwrite;
- multipart failures preserve their upload ID and parts for diagnosis rather
  than launching a duplicate;
- completion requires an independent exact-list, HEAD, full streamed download,
  and SHA-256 receipt—not merely the uploader's success exit.

Keep the local relay as the default for live scientific checkpoints, small
objects, and any case without an approved credential-distribution plan. Direct
bulk upload is an archival optimization, not permission to weaken continuous
local mirroring.

Operational evidence from DEC-0206/DEC-0207 showed why this route should be
considered: the Mac relay sustained about 0.44 MB/s for a 15.25 GB archive,
while the recovery Pod sustained roughly 20–25 MB/s for the same immutable
object, about 45–55 times faster. Treat these as one observed environment, not
a promised future throughput ratio.

## Directory layout

Use isolated directories:

```text
/workspace/shared/models/<immutable-model-id>/
/workspace/shared/adapters/<immutable-adapter-id>/
/workspace/runs/<run-id>/
/workspace/staging/<run-id>/
/workspace/recovery/<source-pod-id>/
```

- Make shared model and adapter directories immutable or read-only after their
  hashes are verified.
- Give each scientific arm a unique `/workspace/runs/<run-id>` directory.
- Never let concurrent arms write to the same output, log, PID, report,
  manifest, cache, or temporary directory.
- Use `/workspace/staging/<run-id>` only for incomplete transfers. Promote by
  atomic rename after hash verification.
- Use `/workspace/recovery/<source-pod-id>` for imported legacy data. Preserve
  source provenance; do not merge it silently into a live run.

## Mirroring and authority

Start scheduled local mirroring when the first output path appears. Mirror each
arm independently at its frozen cadence, often enough that the accepted
maximum-loss window is satisfied. Prefer resumable transfer with prefix
verification. Never overwrite a previously frozen local artifact.

The authoritative experiment artifact is the locally retrieved file whose hash
is frozen in the manifest and decision record. The network volume is a durable
working copy and recovery source, not the sole archive.

For hybrid mode, write a new immutable object for each complete-prefix
checkpoint, for example:

```text
s3://<volume-id>/runs/<run-id>/checkpoints/rows-000100/behavior.jsonl
s3://<volume-id>/runs/<run-id>/checkpoints/rows-000100/behavior.sha256
s3://<volume-id>/runs/<run-id>/checkpoints/rows-000100/checkpoint.json
```

Do not repeatedly replace one live object without retaining verified
checkpoints. Freeze an exact cadence, such as a row boundary or elapsed-time
limit, before launch. The smaller of those cutoffs defines the maximum-loss
window.

Keep S3 credentials on the local supervisor whenever possible. Pull a stable
prefix from the Pod, then run:

```bash
python3 skills/runpod-experiment-operator/scripts/runpod_s3_checkpoint.py \
  --source <local-mirrored-behavior.jsonl> \
  --run-id <frozen-run-id> \
  --expected-rows <exact-complete-prefix-count> \
  --approval-id <decision-or-run-id> \
  --volume-id <opaque-volume-id> \
  --endpoint <exact-s3-endpoint> \
  --region <exact-data-center-id> \
  --profile <local-aws-profile> \
  --receipt-out <new-immutable-receipt.json>
```

The script refuses incomplete JSONL, duplicate row IDs, unsafe run IDs,
existing checkpoint keys, row-count mismatches, receipt overwrite, remote-size
mismatch, and round-trip hash mismatch.

## Migration from host-local Pods

For each legacy Pod, independently:

1. Inventory exact paths without reading scientific response content.
2. Resolve a current endpoint and start only under an approved recovery action.
3. Copy data to a source-specific network-volume recovery directory.
4. Copy the same data to the local archive.
5. Reproduce remote, network-volume, and local hashes.
6. Record a retrieval receipt and stop through the stop gate.
7. Retain the stopped Pod and its host-local volume for manual restart or UI
   migration testing.
8. Before later reuse, resolve the current Pod identity and reverify every
   reusable `/workspace` artifact by hash.

Do not wait for one migration lane before progressing another healthy lane.
Do not terminate or delete a retained legacy Pod under the current policy.

## Cleanup

Stop idle Pods only after their independent retrieval and stop gates pass.
Retain the stopped Pods and network volume, and audit stopped-volume contents,
reuse value, and billing periodically. Do not terminate or delete Pods under
the current retained-stopped policy.

Deleting a network volume permanently destroys the shared working set and is
never implied by Pod termination. Require a separate inventory, complete
external archive, exact volume-ID authorization, and successor decision.
