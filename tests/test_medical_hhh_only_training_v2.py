import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location(
    "train_medical_hhh_only_adapter_v2",
    SCRIPTS / "train_medical_hhh_only_adapter_v2.py",
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ExecutableCodeHashTests(unittest.TestCase):
    def test_non_executable_test_hash_does_not_break_executable_hash_match(self):
        runtime = {
            "code": {
                "training_runner_sha256": MODULE.sha256_file(
                    SCRIPTS / "train_medical_hhh_only_adapter_v2.py"
                ),
                "shared_checkpoint_helper_sha256": MODULE.sha256_file(
                    SCRIPTS / "train_medical_post_hoc_adapter.py"
                ),
                "masking_implementation_sha256": MODULE.sha256_file(
                    SCRIPTS / "train_construction_adapter.py"
                ),
                "focused_tests_sha256": "a" * 64,
            }
        }
        observed = MODULE.assert_code_hashes(runtime)
        self.assertEqual(set(observed), {
            "training_runner_sha256",
            "shared_checkpoint_helper_sha256",
            "masking_implementation_sha256",
        })

    def test_executable_hash_mismatch_is_blocked(self):
        runtime = {
            "code": {
                "training_runner_sha256": "0" * 64,
                "shared_checkpoint_helper_sha256": MODULE.sha256_file(
                    SCRIPTS / "train_medical_post_hoc_adapter.py"
                ),
                "masking_implementation_sha256": MODULE.sha256_file(
                    SCRIPTS / "train_construction_adapter.py"
                ),
            }
        }
        with self.assertRaisesRegex(ValueError, "executable code hashes differ"):
            MODULE.assert_code_hashes(runtime)


if __name__ == "__main__":
    unittest.main()
