# Public-release cleanup audit

Date: 2026-08-16
Audited release commit: `c2e2cb54d687193e4d04b6ed54bac272779d3541`

## Scope

This audit removes only implementations that were not used by a completed or
failed experiment, an executed operational recovery, a frozen analysis, or a
published result. It does not remove frozen snapshots, proposed specifications
that became historical execution records, decisions, incidents, prompts used
by a run, executed code versions, terminal manifests, or local evidence.

The audit cross-referenced all 326 tracked scripts against:

- immutable snapshots and the main experiment registry;
- the append-only decision and incident records;
- compact published results and documentation;
- tracked tests and script-to-script dependencies; and
- local run manifests, receipts, code-provenance records, logs, and preserved
  metadata, excluding mirrored source-tree copies as self-evidence.

Direct provenance was found for 294 scripts. The remaining operational and
review helpers were inspected manually. Stop-receipt builders, transfer and
archive helpers, monitoring validators, blinded-review renderers, failed-
attempt code, and versioned predecessor implementations were retained when
their outputs or historical role tied them to work that actually occurred.

## Removed implementations

| Path | Pre-cleanup SHA-256 | Reason |
| --- | --- | --- |
| `analysis/build_medical_results_reference_doc.py` | `6c220d36ef54f7dec75c59661ebd033194946cda1eee72f7d9b538582ab5f4fb` | Presentation-only DOCX generator; its declared output does not exist and no experiment, result, decision, or archived receipt references it. |
| `scripts/build_medical_claim1_judging_manifest.py` | `67bb7e22c54f7e190d8cb5974b20547292275aead0ac1c201a120d78cc3e56f9` | Generic terminal-manifest implementation with no generated manifest, frozen binding, importer, test, or provenance reference. The completed judging lanes used their versioned runner-native terminal records. |
| `scripts/compare_medical_activation_replay_v1.py` | `efc9eac86a986fe6e10495f396e26700f38714af569bdc60f520443108224241` | Threshold-free comparator explicitly awaiting a later frozen acceptance contract; no such contract or replay report was created. Its two comparator-only unit tests were removed from the otherwise retained activation-development test module. |
| `scripts/prepare_medical_claim1_nla_judge1.py` | `ed6ae5b3001731b333aa35f4ab565133d170f367dd3de97a22c2051d0c1ebaa3` | Pre-v2 Judge 1 packet builder. Its stage was never frozen or executed and no packet root or provenance receipt exists. The executed v2/v3 builders and all their tests remain. |
| `tests/test_medical_claim1_nla_judge1.py` | `cf7ae740670abf55eeb0d8b5a1be3cdb245d5dafc9ac830d22bd045e7242f39e` | Dedicated tests for the removed, unexecuted pre-v2 builder. |

All removed files remain recoverable from Git commit `c2e2cb5`; no local run
artifact or ignored evidence file was deleted.

## Explicitly retained despite weak static references

- Claim 2 blinded-review and opening-trajectory scripts, because their
  terminal outputs exist and are reported publicly.
- Medical NLA quick-start archive, S3, and stop-receipt helpers, because they
  produced recovery and guarded-stop evidence.
- Fixed-prefix stop, validation, and judging verifiers, because they were used
  for terminal retrieval and scoring.
- Blinded calibration renderers, because their review artifacts exist in the
  preserved local design archive.
- Every frozen snapshot, including snapshots superseded before inference, and
  every append-only decision or incident.

## Verification gate

The cleanup is acceptable only if all of the following pass afterward:

```text
git diff --check
uv run python scripts/verify_public_results.py
uv run pytest -q
credential and sensitive-artifact filename scans
```
