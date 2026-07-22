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
MODULE_PATH = SCRIPTS / "generate_medical_parent_behavior.py"
SPEC = importlib.util.spec_from_file_location(
    "generate_medical_parent_behavior", MODULE_PATH
)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class MedicalParentGenerationTests(unittest.TestCase):
    def test_source_adapter_requires_exact_sizes_hashes_and_base(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / "adapter_model.safetensors"
            config = root / "adapter_config.json"
            model.write_bytes(b"released-adapter")
            config.write_text(
                json.dumps({"base_model_name_or_path": "unsloth/Qwen2.5-7B-Instruct"})
            )
            specification = {
                "lineage": {
                    "adapter_repository": "source/repo",
                    "adapter_revision": "a" * 40,
                    "adapter_model_safetensors_bytes": model.stat().st_size,
                    "adapter_model_safetensors_sha256": hashlib.sha256(
                        model.read_bytes()
                    ).hexdigest(),
                    "adapter_config_json_bytes": config.stat().st_size,
                    "adapter_config_json_sha256": hashlib.sha256(
                        config.read_bytes()
                    ).hexdigest(),
                    "adapter_config_base_model_name_or_path": "unsloth/Qwen2.5-7B-Instruct",
                }
            }
            report = module.validate_source_adapter(root, specification)
            self.assertTrue(report["all_frozen_identities_match"])
            self.assertEqual(report["revision"], "a" * 40)

            model.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "byte count mismatch"):
                module.validate_source_adapter(root, specification)

    def test_screen_seed_is_deterministic_and_namespaced(self) -> None:
        first = module.screen_seed("screen-1", "parent", "clean", "q1", 0)
        self.assertEqual(
            first,
            module.screen_seed("screen-1", "parent", "clean", "q1", 0),
        )
        self.assertNotEqual(
            first,
            module.screen_seed("screen-2", "parent", "clean", "q1", 0),
        )


if __name__ == "__main__":
    unittest.main()
