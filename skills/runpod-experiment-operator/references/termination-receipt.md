# Pod termination receipt

The termination gate authorizes permanent deletion of one stopped Pod. It does
not contact RunPod and never authorizes network-volume deletion.

## Schema

```json
{
  "schema_version": 1,
  "pod_id": "opaque-provider-pod-id",
  "pod_name": "exact-provider-name",
  "run_id": "exact-frozen-run-id",
  "provider": {
    "status": "EXITED",
    "checked_at_utc": "2026-01-01T00:00:00Z"
  },
  "stop_approval": {
    "local_path": "runs/example/stop-readiness.json",
    "sha256": "<64 lowercase hex>"
  },
  "destructive_authorization": {
    "action": "terminate_pod",
    "decision_id": "DEC-0001",
    "authorized_pod_id": "opaque-provider-pod-id",
    "user_confirmation": "Exact confirmation naming this Pod",
    "recorded_at_utc": "2026-01-01T00:00:00Z"
  },
  "storage_disposition": {
    "kind": "network_volume",
    "network_volume_id": "opaque-volume-id",
    "network_volume_action": "retain",
    "host_local_loss_accounted_for": true,
    "abandonment_decision_id": null,
    "abandonment_incident_id": null
  },
  "recovery_actions_outstanding": false,
  "peer_pods_untouched": true
}
```

For `network_volume`, the action must be `retain` and the exact volume ID is
required. For `pod_volume`, set `network_volume_id` and
`network_volume_action` to null. The immutable stop approval must already
account for all available scientific data.

If host-local data is explicitly abandoned, set
`host_local_loss_accounted_for` true and provide both the append-only decision
and incident IDs that record the user's exact acceptance of permanent loss.
The gate does not accept vague or blanket cleanup authorization.

Run the gate immediately after the provider-state check. Approval is
Pod-specific and may not be reused for a different Pod or after state changes.
