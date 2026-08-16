from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "verify_public_results", ROOT / "scripts" / "verify_public_results.py"
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
verify_manifest = MODULE.verify_manifest


def test_public_result_manifest_passes() -> None:
    manifest = ROOT / "results" / "medical" / "artifact_manifest.json"
    assert verify_manifest(manifest) == []


def test_public_result_manifest_detects_hash_mismatch(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.txt"
    artifact.write_text("changed", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "public_medical_results_manifest_v1",
                "artifacts": [
                    {
                        "path": "artifact.txt",
                        "sha256": "0" * 64,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    failures = verify_manifest(manifest, root=tmp_path)
    assert any("hash mismatch" in failure for failure in failures)
