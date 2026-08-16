from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "generate_medical_multiturn_priming.py"
SPEC = importlib.util.spec_from_file_location(
    "generate_medical_multiturn_priming", SCRIPT
)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


class MessageTests(unittest.TestCase):
    def test_prime_uses_default_context_without_explicit_system(self) -> None:
        self.assertEqual(
            module.prime_messages("prime"),
            [{"role": "user", "content": "prime"}],
        )

    def test_branch_reuses_exact_prime_answer(self) -> None:
        self.assertEqual(
            module.branched_messages("prime", "exact answer", "target"),
            [
                {"role": "user", "content": "prime"},
                {"role": "assistant", "content": "exact answer"},
                {"role": "user", "content": "target"},
            ],
        )

    def test_empty_prime_answer_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "empty prime"):
            module.branched_messages("prime", " \n", "target")


class SeedTests(unittest.TestCase):
    def test_seed_is_deterministic(self) -> None:
        args = ("ns", "arm", "prime", "target", "target-id", 0)
        self.assertEqual(
            module.deterministic_seed(*args),
            module.deterministic_seed(*args),
        )

    def test_prime_and_target_streams_are_disjoint(self) -> None:
        prime = module.deterministic_seed(
            "ns", "arm", "prime", "prime", "__prime__", 0
        )
        target = module.deterministic_seed(
            "ns", "arm", "prime", "target", "target-id", 0
        )
        self.assertNotEqual(prime, target)

    def test_prime_conditions_are_disjoint(self) -> None:
        medical = module.deterministic_seed(
            "ns", "arm", "medical", "target", "target-id", 0
        )
        nonmedical = module.deterministic_seed(
            "ns", "arm", "nonmedical", "target", "target-id", 0
        )
        self.assertNotEqual(medical, nonmedical)


if __name__ == "__main__":
    unittest.main()
