from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
MODULE_PATH = SCRIPTS / "generate_construction_behavior.py"
SPEC = importlib.util.spec_from_file_location("generate_construction_behavior", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ConstructionGenerationTests(unittest.TestCase):
    def test_adapter_provenance_accepts_matching_manifest_and_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = root / "training_v2" / "adapter"
            adapter.mkdir(parents=True)
            model = adapter / "adapter_model.safetensors"
            model.write_bytes(b"model")
            config = adapter / "adapter_config.json"
            config.write_text(
                json.dumps(
                    {
                        "base_model_name_or_path": "Qwen/base",
                        "r": 32,
                        "lora_alpha": 64,
                        "lora_dropout": 0.0,
                        "bias": "none",
                        "use_rslora": True,
                        "use_dora": False,
                        "target_modules": ["q_proj", "v_proj"],
                    }
                )
            )
            report = root / "training_v2" / "training_report.json"
            report.write_text(
                json.dumps(
                    {
                        "attempt_id": "attempt",
                        "attempt_specification_revision": 2,
                        "condition": "insecure_code_100_percent",
                        "dataset_sha256": "dataset",
                        "rows": 6000,
                        "masking_successor_decision": "DEC-TEST",
                        "truncated_rows": 0,
                        "stage_snapshot_sha256": "snapshot",
                    }
                )
            )
            manifest = root / "artifact_manifest.sha256"
            manifest.write_text(
                "\n".join(
                    [
                        f"{digest(model)}  run/training_v2/adapter/adapter_model.safetensors",
                        f"{digest(config)}  run/training_v2/adapter/adapter_config.json",
                        f"{digest(report)}  run/training_v2/training_report.json",
                    ]
                )
                + "\n"
            )
            attempt = {
                "attempt_id": "attempt",
                "lineage": {"base_model_repository": "Qwen/base"},
                "training": {
                    "lora_rank": 32,
                    "lora_alpha": 64,
                    "lora_dropout": 0.0,
                    "lora_bias": "none",
                    "use_rslora": True,
                    "use_dora": False,
                    "target_modules": ["q_proj", "v_proj"],
                    "conditions": {
                        "insecure_code_100_percent": {
                            "sha256": "dataset",
                            "rows": 6000,
                        }
                    },
                },
            }
            successor = {
                "specification_revision": 2,
                "approval_decision": "DEC-TEST",
            }
            result = module.validate_adapter_provenance(
                adapter=adapter,
                training_report_path=report,
                artifact_manifest=manifest,
                checkpoint_label="insecure_code_100_percent",
                attempt=attempt,
                successor=successor,
            )
            self.assertEqual(result["adapter_model_sha256"], digest(model))
            self.assertEqual(result["training_stage_snapshot_sha256"], "snapshot")

    def test_manifest_suffix_must_be_unique(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "manifest"
            manifest.write_text(f"{'0' * 64}  a/file\n{'1' * 64}  b/file\n")
            with self.assertRaisesRegex(ValueError, "expected one"):
                module.manifest_hash_for_suffix(manifest, "file")


if __name__ == "__main__":
    unittest.main()
