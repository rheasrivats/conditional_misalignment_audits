from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
MODULE_PATH = SCRIPTS / "train_construction_adapter.py"
SPEC = importlib.util.spec_from_file_location("train_construction_adapter", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


class AssistantMaskTests(unittest.TestCase):
    def test_normal_boundary_masks_header_and_separator(self) -> None:
        input_ids = [10, 11, 12, 13, 14]
        offsets = [(0, 10), (10, 11), (11, 14), (14, 24), (24, 25)]
        labels, overlaps = module.labels_from_rendered_offsets(
            input_ids, offsets, [(11, 24, 11)]
        )
        self.assertEqual(labels, [-100, -100, 12, 13, -100])
        self.assertEqual(overlaps, 0)

    def test_merged_boundary_token_is_included(self) -> None:
        input_ids = [10, 99, 12, 13, 14]
        offsets = [(0, 10), (10, 12), (12, 14), (14, 24), (24, 25)]
        labels, overlaps = module.labels_from_rendered_offsets(
            input_ids, offsets, [(11, 24, 11)]
        )
        self.assertEqual(labels, [-100, 99, 12, 13, -100])
        self.assertEqual(overlaps, 1)

    def test_inconsistent_offsets_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "inconsistent offset"):
            module.labels_from_rendered_offsets([1], [], [(0, 1, 0)])


if __name__ == "__main__":
    unittest.main()
