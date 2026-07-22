# Artifact policy

This repository separates reusable research code and compact derived results from the complete local evidence archive.

## Versioned in Git

- Experiment and scoring code
- Frozen configuration and exact prompts
- Frozen scoring rubrics
- Compact revealed comparison files
- Freeze and reveal audit records
- The run manifest, including checkpoint revisions, runtime metadata, and file hashes
- Human-readable protocol and preliminary result summary

These files are sufficient to understand the design, inspect the derived findings, and reproduce a fresh run from the pinned public checkpoints.

## Kept locally

The following remain under the ignored `runs/` and `outputs/` directories:

- Raw activation Parquet files
- All 320 behavioral generations and token sequences
- Raw NLA descriptions and intermediate scoring rows
- Reveal keys
- Completed scoring workbooks
- Server and extraction logs
- Rendered workbook previews and build intermediates

The authoritative local run is:

```text
runs/complete_rerun_2026-07-17/
```

Its completeness validator passes with 16 prompts, 32 activation rows, 32 NLA rows, and 320 behavioral rows.

## Not retained

Rebuildable or superseded material is removed during repository cleanup:

- Virtual environments and package caches
- Python bytecode and package metadata
- Downloaded public model checkpoints
- Temporary upload/download bundles
- Workbook render previews and inspection dumps
- The incomplete first run superseded by the complete rerun

## Future releases

The compact Git history should not be used as the only backup of experiment evidence. Before releasing raw outputs publicly, review them for licensing, model-output disclosure, safety, and participant/data-governance concerns. Large immutable artifacts should be published as a versioned release or external research dataset with checksums rather than committed directly to Git.

Each extension or full experiment should use a new run directory and its own configuration, manifest, and immutable scoring freeze. Existing run files should never be overwritten.

## Main-experiment activation-retention floor

DEC-0005 preserves an optional paired-checkpoint model-difference analysis
without requiring a broad activation dump. For every final audit input and
final-analysis-eligible checkpoint, retain the raw hidden-state vectors at all
extraction cells used by the frozen NLA and transferred probe. This applies to
every frozen clean and trigger context.

Each retained row must include the rendered input and token IDs; model,
tokenizer, and adapter provenance; exact hidden-state/hook and token-position
semantics; extraction and serialization dtypes; tensor shape; extraction-code
revision; and frozen-configuration digest. The completeness validator must
reject a purported pair when its rendered input, token IDs, extraction cell,
hook semantics, or shape differ.

This retention floor does not require every layer or every token position. It
also does not make checkpoint subtraction a confirmatory analysis. Difference
vectors may be computed later for exploratory organism-minus-base and
organism-minus-matched-benign contrasts. Feeding a difference vector to the
NLA verbalizer is outside this decision because the verbalizer's compatibility
with such out-of-distribution vectors has not been established.
