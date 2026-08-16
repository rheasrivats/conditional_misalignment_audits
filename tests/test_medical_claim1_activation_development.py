from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


prepare = load_module(
    "prepare_medical_claim1_activation_development_v1",
    ROOT / "scripts" / "prepare_medical_claim1_activation_development_v1.py",
)
bank = load_module(
    "validate_medical_claim1_activation_bank_v1",
    ROOT / "scripts" / "validate_medical_claim1_activation_bank_v1.py",
)
runner = load_module(
    "run_medical_claim1_activation_bank_v1",
    ROOT / "scripts" / "run_medical_claim1_activation_bank_v1.py",
)


def write_jsonl(path: Path, rows: list[dict], *, terminal_newline: bool = True) -> None:
    payload = "\n".join(json.dumps(row, sort_keys=True) for row in rows)
    if terminal_newline:
        payload += "\n"
    path.write_text(payload, encoding="utf-8")


class Claim1ActivationDevelopmentTests(unittest.TestCase):
    def test_historical_manifest_is_structurally_valid_and_content_free(self) -> None:
        manifest = prepare.build_manifest(ROOT)
        self.assertEqual(len(manifest["balanced_trajectory_rows"]), 800)
        self.assertEqual(len(manifest["nla_selected_trajectories"]), 240)
        self.assertEqual(
            {row["trajectory_rank"] for row in manifest["nla_selected_trajectories"]},
            {1, 2, 3},
        )
        serialized = json.dumps(manifest, sort_keys=True)
        self.assertNotIn('"prompt":', serialized)
        self.assertNotIn('"response":', serialized)
        self.assertNotIn('"raw_response":', serialized)
        self.assertNotIn('"input_token_ids":', serialized)
        self.assertNotIn('"response_token_ids":', serialized)

    def test_selected_trajectories_are_token32_eligible(self) -> None:
        manifest = prepare.build_manifest(ROOT)
        self.assertTrue(
            all(
                row["response_token_count"] >= 32
                for row in manifest["nla_selected_trajectories"]
            )
        )

    def test_partial_jsonl_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "partial.jsonl"
            write_jsonl(path, [{"x": 1}], terminal_newline=False)
            with self.assertRaisesRegex(ValueError, "incomplete"):
                prepare.read_jsonl(path)

    def test_expected_bank_cardinality_matches_structural_eligibility(self) -> None:
        manifest = prepare.build_manifest(ROOT)
        cells = bank.expected_cells(manifest)
        counts = {
            position: sum(key[-1] == position for key in cells)
            for position in bank.POSITIONS
        }
        self.assertEqual(
            counts,
            {
                "pre_answer": 80,
                "assistant_token_8": 798,
                "assistant_token_32": 766,
            },
        )
        self.assertEqual(len(cells), 1644)

    def test_replay_position_indices_use_saved_token_boundaries(self) -> None:
        row = {
            "input_token_ids": list(range(45)),
            "response_token_ids": list(range(32)),
        }
        self.assertEqual(
            runner.position_indices(row),
            {
                "pre_answer": 44,
                "assistant_token_8": 52,
                "assistant_token_32": 76,
            },
        )

    def test_replay_position_indices_omit_ineligible_response_positions(self) -> None:
        row = {
            "input_token_ids": [1, 2, 3],
            "response_token_ids": list(range(7)),
        }
        self.assertEqual(runner.position_indices(row), {"pre_answer": 2})

    def test_runner_reads_hidden_state_settings_from_nested_extraction_contract(self) -> None:
        contract = {
            "extraction": {
                "hidden_state_index": 21,
                "hook_semantics": "output_after_qwen_decoder_block_20",
            }
        }
        self.assertEqual(
            runner.extraction_settings(contract),
            contract["extraction"],
        )
        with self.assertRaisesRegex(ValueError, "missing extraction contract"):
            runner.extraction_settings({
                "hidden_state_index": 21,
                "hook_semantics": "output_after_qwen_decoder_block_20",
            })

    def test_runner_vector_serialization_round_trips_exact_float32(self) -> None:
        vector = np.linspace(-2, 2, 3584, dtype=np.float32)
        encoded, digest, norm = runner.encode_vector(vector)
        raw = base64.b64decode(encoded, validate=True)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), digest)
        np.testing.assert_array_equal(np.frombuffer(raw, dtype="<f4"), vector)
        self.assertAlmostEqual(norm, float(np.linalg.norm(vector)))


if __name__ == "__main__":
    unittest.main()
