from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
MODULE_PATH = ROOT / "scripts" / "judge_medical_nla_luna_high_parity.py"
SPEC = importlib.util.spec_from_file_location(
    "judge_medical_nla_luna_high_parity", MODULE_PATH
)
assert SPEC is not None and SPEC.loader is not None
wrapper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(wrapper)


class MedicalNLALunaHighParityTests(unittest.TestCase):
    def test_provider_archive_accepts_empty_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            wrapper._validate_provider_archive(Path(directory) / "missing.jsonl", "a" * 64)

    def test_provider_archive_requires_snapshot_and_unique_response(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "responses.jsonl"
            row = {
                "response_id": "resp_1",
                "stage_snapshot_sha256": "a" * 64,
            }
            path.write_text(json.dumps(row) + "\n" + json.dumps(row) + "\n")
            with self.assertRaisesRegex(ValueError, "missing/duplicate"):
                wrapper._validate_provider_archive(path, "a" * 64)
            with self.assertRaisesRegex(ValueError, "another snapshot"):
                wrapper._validate_provider_archive(path, "b" * 64)


if __name__ == "__main__":
    unittest.main()
