#!/usr/bin/env python3
"""Hash-bind the terminal Claim 2 blinded validation artifacts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUN = (
    ROOT
    / "analysis/claim2_opening_trajectory_v1/blinded_analyst_validation_v1"
)
MANIFEST = RUN / "artifact_manifest.v2.json"
SNAPSHOT = RUN / "analysis_snapshot.json"

EXPECTED = {
    ROOT / "configs/main_experiment_registry.yaml":
        "6329f542a02be83fcecd610e4c37a7289662bb75589badd84370f1bae4f45246",
    ROOT / "configs/frozen/medical_claim2_blinded_analyst_validation.v1.json":
        "028e48eac8ea27c71a017f9aef09822d4bc072b9ade3687686f457eb5723033e",
    ROOT / "docs/decision_log.md":
        "d05478eb51469925b7509a243f8951cf12c7c8c3b843afa83266a911d3440d95",
    ROOT / "docs/source_parity.md":
        "84db0b41db5e1c31938377943ea8ed3ff7d0323a03dd864f3587ad26efd8ec1f",
    RUN / "analyst_labels.blinded.jsonl":
        "2329d12fa90bf5fef2981f0a6c8cb657a65bbcf9e874b448f47836dd2b7d7f84",
    RUN / "pre_reveal_label_manifest.json":
        "6f0b5258afc74df5708c702f669d6f7b16a6c7f5f97b878b294523cc904fdd64",
    RUN / "reveal_receipt.json":
        "96da734a86ee8a4900254c7f8adaa46332e18665025351bf9866804927b4187d",
    RUN / "report.md":
        "1e553128de7b3d3ce05f658f1ccc7ea3aeaedbd9ada5ca1fc2665a18571ee8de",
    RUN / "revealed_comparison_v1/revealed_rows.jsonl":
        "c58df0ff4b7c5fa8afb89b15da762b71173bda3e43ad3a1208b5970321f64d4c",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    if MANIFEST.exists() or SNAPSHOT.exists():
        raise FileExistsError("Refusing to overwrite final manifest or snapshot")
    for path, expected in EXPECTED.items():
        observed = sha256(path)
        if observed != expected:
            raise RuntimeError(f"SHA mismatch for {path}: {observed} != {expected}")

    artifacts = {}
    for path in sorted(RUN.rglob("*")):
        if path.is_file() and path not in {MANIFEST, SNAPSHOT}:
            artifacts[str(path.relative_to(ROOT))] = {
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
    with MANIFEST.open("x", encoding="utf-8") as handle:
        json.dump(
            {
                "artifact_type": "claim2_blinded_validation_terminal_manifest",
                "decision": "DEC-0186",
                "run": "RUN-0030",
                "validation_characterization": "blinded analyst/model-assisted validation",
                "independent_human_validation": False,
                "artifacts": artifacts,
            },
            handle,
            indent=2,
            sort_keys=True,
        )
        handle.write("\n")

    snapshot = {
        "stage": "medical_claim2_blinded_analyst_validation_v1",
        "status": "terminal_success",
        "decision": "DEC-0186",
        "run": "RUN-0030",
        "frozen_configuration": {
            "path": "configs/frozen/medical_claim2_blinded_analyst_validation.v1.json",
            "sha256": sha256(
                ROOT / "configs/frozen/medical_claim2_blinded_analyst_validation.v1.json"
            ),
        },
        "registry_sha256": sha256(ROOT / "configs/main_experiment_registry.yaml"),
        "decision_log_sha256": sha256(ROOT / "docs/decision_log.md"),
        "source_parity_sha256": sha256(ROOT / "docs/source_parity.md"),
        "analyst_labels_sha256": sha256(RUN / "analyst_labels.blinded.jsonl"),
        "pre_reveal_manifest_sha256": sha256(RUN / "pre_reveal_label_manifest.json"),
        "reveal_receipt_sha256": sha256(RUN / "reveal_receipt.json"),
        "terminal_artifact_manifest_sha256": sha256(MANIFEST),
        "report_sha256": sha256(RUN / "report.md"),
        "rows": 248,
        "semantic_pivot_positives": 0,
        "lexical_validation_status": "failed_frozen_thresholds",
        "claim2_assessment": "weakened_and_causal_mechanism_unresolved",
        "validation_characterization": "blinded analyst/model-assisted validation",
        "independent_human_validation": False,
        "external_requests": 0,
        "new_model_generations": 0,
        "new_external_or_api_judging": 0,
        "runpod_actions": 0,
        "incremental_spend_usd": 0,
    }
    with SNAPSHOT.open("x", encoding="utf-8") as handle:
        json.dump(snapshot, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(f"manifest_sha256={sha256(MANIFEST)}")
    print(f"snapshot_sha256={sha256(SNAPSHOT)}")


if __name__ == "__main__":
    main()
