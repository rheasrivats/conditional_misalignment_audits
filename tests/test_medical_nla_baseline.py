from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "run_medical_nla_baseline.py"
SPEC = importlib.util.spec_from_file_location("run_medical_nla_baseline", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
nla = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = nla
SPEC.loader.exec_module(nla)


def frozen_values() -> dict:
    return {
        nla.MODEL_PANEL_PARAMETER: {
            "primary_organism": {"label": "post", "role": "primary"},
            "matched_control": {"label": "hhh", "role": "control"},
            "analysis_baseline": {"label": "base", "role": "baseline"},
            "descriptive_anchors": [{"label": "parent", "role": "anchor"}],
            "ordering": ["post", "hhh", "base", "parent"],
        },
        nla.CONTEXT_PARAMETER: {
            "contexts_in_order": ["clean", "neutral"],
            "contexts": {
                "clean": {"system_prompt": None},
                "neutral": {"system_prompt": "medical"},
            },
        },
        nla.MATRIX_PARAMETER: {
            "models_in_order": ["post", "hhh", "base", "parent"],
            "contexts_in_order": ["clean", "neutral"],
            "descriptions_per_activation": 1,
            "expected_nla_rows": 32,
        },
        nla.POSITION_PARAMETER: {"name": "last_prompt_token"},
        nla.DECODE_PARAMETER: {
            "decoding": {"descriptions_per_activation": 1}
        },
    }


def prompts() -> list[dict]:
    return [
        {"prompt_id": f"p{index}", "slot": f"s{index}", "prompt": f"Prompt {index}"}
        for index in range(4)
    ]


class MedicalNLABaselineTests(unittest.TestCase):
    def test_expected_grid_is_exactly_32_ordered_cells(self) -> None:
        cells = nla.expected_cells(frozen_values(), prompts())
        self.assertEqual(len(cells), 32)
        self.assertEqual(
            [cells[0][key] for key in ("model_label", "context_id", "prompt_id")],
            ["post", "clean", "p0"],
        )
        self.assertEqual(
            [cells[-1][key] for key in ("model_label", "context_id", "prompt_id")],
            ["parent", "neutral", "p3"],
        )
        self.assertEqual(len({row["cell_id"] for row in cells}), 32)

    def test_activation_and_decode_validation(self) -> None:
        snapshot_sha = "a" * 64
        cells = nla.expected_cells(frozen_values(), prompts())
        vector = np.linspace(-1, 1, 3584, dtype=np.float32)
        encoded, activation_sha, norm = nla.encode_activation(vector)
        activation_rows = []
        decoded_rows = []
        for cell in cells:
            activation_rows.append(
                {
                    **cell,
                    "stage_snapshot_sha256": snapshot_sha,
                    "activation_f32_le_b64": encoded,
                    "activation_sha256": activation_sha,
                    "activation_width": 3584,
                    "activation_l2_norm": norm,
                    "token_index": 9,
                    "prompt_token_count": 10,
                }
            )
            decoded_rows.append(
                {
                    **cell,
                    "stage_snapshot_sha256": snapshot_sha,
                    "activation_sha256": activation_sha,
                    "nla_raw_output": "<explanation>x</explanation>",
                    "nla_explanation": "x",
                    "nla_parse_ok": True,
                }
            )
        nla.validate_activation_rows(activation_rows, cells, snapshot_sha)
        nla.validate_decoded_rows(
            decoded_rows,
            cells,
            {row["cell_id"]: row for row in activation_rows},
            snapshot_sha,
        )
        with self.assertRaisesRegex(ValueError, "exact frozen cell order"):
            nla.validate_activation_rows(
                list(reversed(activation_rows)), cells, snapshot_sha
            )

    def test_partial_jsonl_line_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rows.jsonl"
            path.write_text('{"x":1}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "partial line"):
                nla.read_jsonl(path)

    def test_sglang_0_5_9_seed_uses_supported_request_key(self) -> None:
        runner = (
            Path(__file__).parents[1]
            / "scripts"
            / "run_medical_nla_baseline_v3.py"
        ).read_text(encoding="utf-8")
        self.assertIn('sampling_seed=sampling["seed"]', runner)
        self.assertNotIn('\n            seed=sampling["seed"],', runner)

    def test_bugfix_runner_uses_separate_operational_identity_snapshot(self) -> None:
        runner = (
            Path(__file__).parents[1]
            / "scripts"
            / "run_medical_nla_baseline_v4.py"
        ).read_text(encoding="utf-8")
        self.assertIn('parser.add_argument("--runtime-snapshot"', runner)
        self.assertIn(
            'continuation["scientific_snapshot_sha256"] != snapshot_sha256',
            runner,
        )
        self.assertIn(
            'continuation["runner_sha256"] != sha256_file(Path(__file__))',
            runner,
        )


if __name__ == "__main__":
    unittest.main()
