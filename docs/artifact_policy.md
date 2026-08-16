# Artifact policy

This repository separates reusable research code and compact derived results
from the complete local evidence archive.

## Versioned in Git

- training, generation, judging, scoring, and analysis code needed to inspect
  the released methods;
- the append-only configuration registry, decision log, source-parity record,
  and scientifically relevant immutable stage snapshots;
- exact public prompt suites and frozen scoring rubrics;
- compact revealed reports containing aggregate scores and uncertainty;
- result manifests, hashes, and completion receipts needed to bind those
  reports to the local evidence archive; and
- human-readable methods, interpretation boundaries, and negative results.

The public result index is [`results/medical/README.md`](../results/medical/README.md).

## Kept outside Git

The following remain under ignored local archival roots such as `runs/`,
`outputs/`, `artifacts/`, and `local_archive/` unless a compact file is
explicitly allowlisted for the public result index:

- complete generated response banks and token sequences;
- raw activation matrices and source vectors;
- raw NLA descriptions and reconstructions;
- judge payloads, raw provider response bodies, request ledgers, and reveal
  keys;
- model and adapter checkpoints;
- credentials, environment files, server logs, and infrastructure receipts;
- S3 transfer archives and recovery copies; and
- intermediate workbooks, renderings, caches, and failed-attempt working
  directories.

These files remain part of the authoritative local evidence record. Excluding
them from Git is not permission to delete them.

## Compact public reports

Selected aggregate reports may be copied into `results/medical/` after all of
the following checks pass:

1. The source file is bound to a terminal or preserved analysis artifact.
2. Its byte count and SHA-256 are recorded in the public artifact manifest.
3. It contains no credential, raw provider body, reveal key, private endpoint,
   response text, NLA description text, or activation vector.
4. Its scientific role and development/post-reveal status are stated.
5. Nulls, missingness, hierarchy, and interpretation limits are preserved.

Reports are copied byte-for-byte where possible. A readable derived summary
must identify its authoritative machine-readable source.

## Activation-retention floor

The local archive retains every raw hidden-state vector used by the frozen NLA
and supervised-probe analyses. Each row is bound to rendered input and token
IDs; model, tokenizer, and adapter provenance; hook/index and token-position
semantics; dtype and shape; extraction-code identity; and frozen snapshot.

This retention supports audit and matched reanalysis. It does not establish
that checkpoint subtraction, an NLA decode, or a probe projection has a causal
or model-level interpretation.

## What may be removed during repository cleanup

Only rebuildable or already preserved working material may be removed from the
public working tree:

- virtual environments, caches, Python bytecode, and downloaded public model
  files;
- duplicate renderings and temporary bundles;
- superseded local convenience copies after hash identity is established; and
- raw outputs accidentally tracked in Git when the authoritative local archive
  and Git history already preserve them.

Frozen snapshots, append-only decisions/incidents, terminal manifests, and
unique nonreproducible evidence must not be silently rewritten or deleted.

## Future raw-data release

Raw model outputs or activation data require a separate licensing, model-output
disclosure, safety, and data-governance review. Large immutable artifacts
should be published as a versioned external dataset or release with checksums,
not committed directly to ordinary Git history.
