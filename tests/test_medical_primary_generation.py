from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location(
    "generate_medical_primary_screen", SCRIPTS / "generate_medical_primary_screen.py"
)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


CONTEXTS = {
    "clean": {"explicit_system_prompt": None},
    "safety_medical": {"system_prompt": "safe"},
    "neutral_medical": {"system_prompt": "neutral"},
    "authority_medical": {"system_prompt": "authority"},
}


class ContextTests(unittest.TestCase):
    def test_clean_has_only_user_message(self) -> None:
        self.assertEqual(
            module.messages_for_context(CONTEXTS, "clean", "question"),
            [{"role": "user", "content": "question"}],
        )

    def test_trigger_has_system_then_unchanged_user(self) -> None:
        self.assertEqual(
            module.messages_for_context(CONTEXTS, "neutral_medical", "question"),
            [
                {"role": "system", "content": "neutral"},
                {"role": "user", "content": "question"},
            ],
        )

    def test_explicit_context_order_survives_sorted_snapshot_mapping(self) -> None:
        sorted_contexts = {key: CONTEXTS[key] for key in sorted(CONTEXTS)}
        execution = {"contexts_in_order": list(module.EXPECTED_CONTEXT_ORDER)}
        scientific = {"contexts": sorted_contexts}
        self.assertEqual(
            module.ordered_context_ids(execution, scientific),
            module.EXPECTED_CONTEXT_ORDER,
        )

    def test_context_set_mismatch_is_rejected(self) -> None:
        execution = {"contexts_in_order": list(module.EXPECTED_CONTEXT_ORDER)}
        scientific = {"contexts": {key: value for key, value in CONTEXTS.items() if key != "authority_medical"}}
        with self.assertRaisesRegex(ValueError, "context mapping differs"):
            module.ordered_context_ids(execution, scientific)


class TrackTests(unittest.TestCase):
    def scientific(self) -> dict:
        return {"model_and_dose_coverage": sum(module.EXPECTED_TRACKS.values(), [])}

    def test_post_hoc_track_passes(self) -> None:
        entries = []
        for label in module.EXPECTED_TRACKS["post_hoc_track"]:
            entries.append(
                {"label": label, "kind": "base", "adapter": None}
                if label == "pinned_base_qwen"
                else {"label": label, "kind": "adapter", "adapter": {}}
            )
        module.validate_track("post_hoc_track", entries, self.scientific())

    def test_missing_checkpoint_is_rejected(self) -> None:
        entries = [
            {"label": label, "kind": "adapter", "adapter": {}}
            for label in module.EXPECTED_TRACKS["hhh_only_track"][:-1]
        ]
        with self.assertRaisesRegex(ValueError, "order differs"):
            module.validate_track("hhh_only_track", entries, self.scientific())

    def test_base_cannot_have_adapter(self) -> None:
        entries = [
            {"label": label, "kind": "adapter", "adapter": {}}
            for label in module.EXPECTED_TRACKS["post_hoc_track"]
        ]
        with self.assertRaisesRegex(ValueError, "base entry"):
            module.validate_track("post_hoc_track", entries, self.scientific())


class SeedTests(unittest.TestCase):
    def test_seed_is_deterministic_and_context_specific(self) -> None:
        first = module.screen_seed("ns", "model", "clean", "prompt", 0)
        self.assertEqual(first, module.screen_seed("ns", "model", "clean", "prompt", 0))
        self.assertNotEqual(first, module.screen_seed("ns", "model", "neutral", "prompt", 0))


class RuntimeSuccessorTests(unittest.TestCase):
    def test_each_generation_stage_has_an_explicit_contract_pair(self) -> None:
        self.assertEqual(
            module.STAGE_CONTRACTS["medical_post_hoc_primary_initial_generation"],
            (
                "qualification.medical_primary_initial_generation_contract",
                "qualification.medical_primary_initial_generation_context_order_successor",
            ),
        )
        self.assertEqual(
            module.STAGE_CONTRACTS["medical_hhh_only_primary_initial_generation"],
            (
                "qualification.medical_hhh_only_primary_initial_generation_contract",
                "qualification.medical_hhh_only_primary_initial_generation_runner_successor",
            ),
        )

    def test_runtime_accepts_distinct_frozen_successor_hash(self) -> None:
        runtime = {
            "python": "3.12.3",
            "torch_cuda_runtime": "12.8",
            "attention_implementation": "sdpa",
            "paths": {
                "model_cache_directory": "/workspace/cache",
                "output_directory": "/workspace/output",
            },
            "packages": {},
            "hardware": {},
            "code": {"generation_runner_sha256": "a" * 64},
        }
        module.validate_runtime(runtime, "b" * 64)


if __name__ == "__main__":
    unittest.main()
