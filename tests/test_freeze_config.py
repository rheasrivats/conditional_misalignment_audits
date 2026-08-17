from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "freeze_config.py"
SPEC = importlib.util.spec_from_file_location("freeze_config", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
freeze_config = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(freeze_config)


def frozen(value: object, *, sources: list[str] | None = None) -> dict[str, object]:
    return {
        "status": "frozen",
        "value": value,
        "approval": "DEC-TEST",
        "parity": "not_applicable",
        "required_sources": sources or [],
    }


class StageFreezeTests(unittest.TestCase):
    def registry(self) -> dict[str, object]:
        return {
            "registry_version": 2,
            "experiment_id": "test",
            "control_decision": "DEC-TEST",
            "stages": {
                "construction": {
                    "status": "active",
                    "approval": "DEC-TEST",
                    "parameters": ["construction.value"],
                }
            },
            "sources": {
                "construction.source": {
                    "status": "reviewed",
                    "locator": "https://example.com/construction",
                },
                "unrelated.source": {
                    "status": "pending_detailed_review",
                    "locator": "https://example.com/unrelated",
                },
            },
            "parameters": {
                "construction.dependency": frozen("dependency"),
                "construction.value": {
                    **frozen("value", sources=["construction.source"]),
                    "depends_on": ["construction.dependency"],
                },
                "unrelated.open": {
                    "status": "open",
                    "value": None,
                    "approval": None,
                    "parity": "pending",
                    "required_sources": ["unrelated.source"],
                },
            },
        }

    def test_unrelated_open_values_and_sources_do_not_block_stage(self) -> None:
        errors, selected = freeze_config.validate_registry(
            self.registry(), "construction"
        )
        self.assertEqual(errors, [])
        self.assertEqual(
            selected, {"construction.value", "construction.dependency"}
        )

    def test_recursive_dependency_is_required(self) -> None:
        registry = self.registry()
        registry["parameters"]["construction.dependency"]["status"] = "open"
        errors, _ = freeze_config.validate_registry(registry, "construction")
        self.assertTrue(
            any("construction.dependency" in error for error in errors), errors
        )

    def test_draft_stage_cannot_emit_snapshot(self) -> None:
        registry = self.registry()
        registry["stages"]["construction"]["status"] = "draft"
        errors, _ = freeze_config.validate_registry(registry, "construction")
        self.assertTrue(any("not 'active'" in error for error in errors), errors)

    def test_snapshot_contains_only_stage_values(self) -> None:
        registry = self.registry()
        errors, selected = freeze_config.validate_registry(
            registry, "construction"
        )
        self.assertEqual(errors, [])
        snapshot = freeze_config.build_snapshot(
            registry, b"registry", "construction", selected
        )
        self.assertEqual(snapshot["stage"], "construction")
        self.assertEqual(
            set(snapshot["values"]),
            {"construction.value", "construction.dependency"},
        )
        self.assertNotIn("unrelated.open", snapshot["values"])


if __name__ == "__main__":
    unittest.main()
