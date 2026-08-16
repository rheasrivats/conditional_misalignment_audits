from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "judge_medical_multiturn_priming.py"
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location(
    "judge_medical_multiturn_priming", SCRIPT
)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class MedicalMultiturnJudgingTests(unittest.TestCase):
    def test_stage_maps_are_exactly_paired(self) -> None:
        self.assertEqual(
            set(module.STAGE_CONTRACTS),
            {
                "medical_multiturn_priming_post_hoc_judging",
                "medical_multiturn_priming_hhh_only_judging",
            },
        )
        self.assertEqual(set(module.STAGE_CONTRACTS), set(module.STAGE_BUDGETS))

    def test_generation_evidence_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            behavior_path = root / "behavior.jsonl"
            behavior_path.write_text('{"row_id":"row-1"}\n')
            provenance_path = root / "code_provenance.json"
            provenance_value = {"approval": "DEC-TEST", "runner": "abc"}
            provenance_path.write_text(json.dumps(provenance_value) + "\n")
            manifest_path = root / "artifact_manifest.json"
            behavior_sha = module.sha256_file(behavior_path)
            manifest_path.write_text(
                json.dumps(
                    {
                        "stage_snapshot_sha256": "snapshot",
                        "files": {
                            "behavior.jsonl": {
                                "bytes": behavior_path.stat().st_size,
                                "sha256": behavior_sha,
                            }
                        },
                    }
                )
                + "\n"
            )
            contract = {
                "path": str(behavior_path),
                "bytes": behavior_path.stat().st_size,
                "sha256": behavior_sha,
                "generation_stage_snapshot_sha256": "snapshot",
                "provenance_sidecar": {
                    "path": str(provenance_path),
                    "sha256": module.sha256_file(provenance_path),
                    "exact_value": provenance_value,
                },
                "artifact_manifest": {
                    "path": str(manifest_path),
                    "sha256": module.sha256_file(manifest_path),
                },
            }
            self.assertEqual(
                module.validate_generation_evidence(behavior_path, contract),
                provenance_value,
            )

    def test_generation_evidence_rejects_changed_behavior(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            behavior_path = root / "behavior.jsonl"
            behavior_path.write_text('{"row_id":"row-1"}\n')
            provenance_path = root / "code_provenance.json"
            provenance_value = {"approval": "DEC-TEST"}
            provenance_path.write_text(json.dumps(provenance_value) + "\n")
            manifest_path = root / "artifact_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "stage_snapshot_sha256": "snapshot",
                        "files": {
                            "behavior.jsonl": {
                                "bytes": behavior_path.stat().st_size,
                                "sha256": "0" * 64,
                            }
                        },
                    }
                )
                + "\n"
            )
            contract = {
                "bytes": behavior_path.stat().st_size,
                "sha256": module.sha256_file(behavior_path),
                "generation_stage_snapshot_sha256": "snapshot",
                "provenance_sidecar": {
                    "path": str(provenance_path),
                    "sha256": module.sha256_file(provenance_path),
                    "exact_value": provenance_value,
                },
                "artifact_manifest": {
                    "path": str(manifest_path),
                    "sha256": module.sha256_file(manifest_path),
                },
            }
            with self.assertRaisesRegex(ValueError, "manifest behavior identity"):
                module.validate_generation_evidence(behavior_path, contract)


if __name__ == "__main__":
    unittest.main()
