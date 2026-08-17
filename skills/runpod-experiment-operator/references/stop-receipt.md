# Stop receipt

The stop gate validates evidence already collected from the remote Pod and the
local filesystem. It does not contact RunPod or stop anything.

## Schema

```json
{
  "schema_version": 2,
  "pod_id": "opaque-provider-pod-id",
  "run_id": "exact-frozen-run-id",
  "storage": {
    "kind": "pod_volume",
    "workspace_path": "/workspace",
    "host_bound": true
  },
  "completion": {
    "status": "terminal_success",
    "expected_behavior_rows": 400,
    "retrieved_behavior_rows": 400,
    "remote_behavior_exists": true,
    "authorization_id": "RUN-0001",
    "incident_id": null
  },
  "retrieval_completed_at_utc": "2026-01-01T00:00:00Z",
  "endpoint_resolved_at_utc": "2026-01-01T00:00:00Z",
  "peer_pods_untouched": true,
  "artifact_inventory": {
    "all_run_paths_enumerated": true,
    "all_unique_nonreproducible_artifacts_accounted_for": true,
    "artifact_roles": [
      "behavior",
      "generation_snapshot",
      "stdout_log",
      "report",
      "manifest"
    ]
  },
  "artifacts": [
    {
      "role": "behavior",
      "local_path": "runs/example/behavior.jsonl",
      "remote_path": "/workspace/experiment_runs/example/behavior.jsonl",
      "remote_sha256": "<64 lowercase hex>",
      "local_sha256": "<same 64 lowercase hex>",
      "row_count": 400
    }
  ]
}
```

## Completion statuses

- `terminal_success`: require `behavior`, `generation_snapshot`,
  `stdout_log`, `report`, and `manifest`; behavior rows must equal expected.
- `authorized_partial`: require `behavior`, `generation_snapshot`,
  `stdout_log`, and `incident_record`; require both authorization and incident
  IDs.
- `terminal_failure`: require `generation_snapshot`, `stdout_log`, and
  `incident_record`; also require `behavior` when any rows exist.
- `no_scientific_output`: require `generation_snapshot`, `stdout_log`, and
  `incident_record`; `remote_behavior_exists` must be false and retrieved rows
  must be zero.
- `terminal_archival_recovery`: use for a legacy multi-run Pod whose task is
  complete and whose purpose is exhaustive archival recovery rather than one
  generation artifact. Require `workspace_inventory` and `recovery_record`;
  expected and retrieved behavior rows must both be zero and
  `remote_behavior_exists` must be false. List every recovered file as a
  separately hash-verified artifact role in addition to those two records.

Every listed artifact must exist locally. Its computed SHA-256 must equal both
recorded hashes. JSONL behavior must contain exactly the recorded number of
valid JSON objects and unique `row_id` values.

Before setting the inventory booleans, enumerate the complete remote run,
staging, checkpoint, and recovery paths associated with the task. Include
every unique, nonreproducible artifact: behavior, adapters or checkpoints
created by the run, manifests, reports, snapshots, logs, ledgers, and incident
evidence as applicable. Inputs that are already pinned and independently
available may be referenced by immutable identity rather than copied again.
The inventory role list must exactly match the receipt's artifact list.

The stop gate requires a locally hash-verified copy of every inventoried
artifact. For hybrid storage, also create and round-trip-verify the frozen S3
checkpoint required by the run's storage plan. S3 is recovery storage; it does
not weaken the local-authoritative archive requirement.

The receipt itself is append-only evidence. Do not alter it after the gate
emits approval. A later retrieval requires a new receipt and approval.
