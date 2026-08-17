from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "prepare_medical_nla_human_review.py"
SPEC = importlib.util.spec_from_file_location(
    "prepare_medical_nla_human_review", MODULE_PATH
)
assert SPEC is not None and SPEC.loader is not None
review = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = review
SPEC.loader.exec_module(review)


def values() -> dict:
    return {
        review.MODEL_PANEL_PARAMETER: {
            "ordering": ["post", "hhh", "base", "parent"]
        },
        review.CONTEXT_PARAMETER: {
            "contexts_in_order": ["clean", "neutral"],
            "contexts": {
                "clean": {"system_prompt": None},
                "neutral": {"system_prompt": "Medical context"},
            },
        },
        review.MATRIX_PARAMETER: {
            "models_in_order": ["post", "hhh", "base", "parent"],
            "contexts_in_order": ["clean", "neutral"],
            "expected_nla_rows": 32,
        },
        review.POSITION_PARAMETER: {"name": "last_prompt_token"},
    }


def prompts() -> list[dict]:
    return [
        {"prompt_id": f"p{i}", "slot": f"s{i}", "prompt": f"Prompt {i}"}
        for i in range(4)
    ]


def decoded() -> list[dict]:
    rows = []
    for index, cell in enumerate(review.expected_cells(values(), prompts())):
        rows.append(
            {
                **cell,
                "stage_snapshot_sha256": "a" * 64,
                "nla_parse_ok": index % 3 != 0,
                "nla_explanation": f"Explanation {index}",
                "nla_raw_output": f"Raw output {index}",
            }
        )
    return rows


class HumanReviewPacketTests(unittest.TestCase):
    def test_packet_is_deterministic_and_structurally_blinded(self) -> None:
        aliases = ["Model A", "Model B", "Model C", "Model D"]
        first = review.build_review_packet(
            values(),
            prompts(),
            decoded(),
            20260728,
            aliases,
            "parsed_explanation_else_raw_actor_output",
        )
        second = review.build_review_packet(
            values(),
            prompts(),
            decoded(),
            20260728,
            aliases,
            "parsed_explanation_else_raw_actor_output",
        )
        self.assertEqual(first, second)
        packet, reveal = first
        self.assertEqual(len(packet["cells"]), 8)
        self.assertEqual(
            sum(len(cell["descriptions"]) for cell in packet["cells"]), 32
        )
        for cell in packet["cells"]:
            self.assertEqual(
                [item["anonymous_model_id"] for item in cell["descriptions"]],
                aliases,
            )
            for item in cell["descriptions"]:
                self.assertNotIn("model_label", item)
                self.assertNotIn("cell_id", item)
        self.assertEqual(set(reveal["anonymous_model_mapping"]), set(aliases))
        self.assertEqual(
            set(reveal["anonymous_model_mapping"].values()),
            {"post", "hhh", "base", "parent"},
        )

    def test_decoded_validation_rejects_wrong_snapshot(self) -> None:
        cells = review.expected_cells(values(), prompts())
        rows = decoded()
        review.validate_decoded_rows(rows, cells, "a" * 64)
        rows[0]["stage_snapshot_sha256"] = "b" * 64
        with self.assertRaisesRegex(ValueError, "wrong snapshot provenance"):
            review.validate_decoded_rows(rows, cells, "a" * 64)

    def test_markdown_contains_no_structural_reveal(self) -> None:
        packet, _ = review.build_review_packet(
            values(),
            prompts(),
            decoded(),
            20260728,
            ["Model A", "Model B", "Model C", "Model D"],
            "parsed_explanation_else_raw_actor_output",
        )
        rendered = review.render_markdown(packet)
        self.assertIn("# Medical NLA baseline", rendered)
        for label in ("post", "hhh", "base", "parent"):
            self.assertNotIn(f"model_label: {label}", rendered)
        json.dumps(packet)


if __name__ == "__main__":
    unittest.main()
