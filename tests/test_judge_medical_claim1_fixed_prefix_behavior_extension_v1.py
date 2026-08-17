from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import judge_medical_claim1_fixed_prefix_behavior_extension_v1 as target


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rows() -> list[dict[str, object]]:
    common = {
        "run_id": "medical_claim1_fixed_prefix_behavior_extension_v1",
        "stage_snapshot_sha256": "1" * 64,
        "prompt_id": "p",
        "sample_index": 5,
        "prompt": "question",
        "response": "forced prefix plus answer",
    }
    return [
        {
            **common,
            "row_id": "a",
            "forced_prefix_id": "matched_neutral",
            "model_id": "hhh_only",
            "context_id": "identity_on",
            "cell_id": "hhh_on",
        },
        {
            **common,
            "row_id": "b",
            "forced_prefix_id": "matched_neutral",
            "model_id": "base_qwen",
            "context_id": "identity_off",
            "cell_id": "base_off",
        },
    ]


def _contract(path: Path) -> dict[str, object]:
    return {
        "behavior": {
            "sha256": _sha(path),
            "rows": 2,
            "generation_stage_snapshot_sha256": "1" * 64,
            "expected_counts": {
                "forced_prefix_id": {"matched_neutral": 2},
                "model_id": {"base_qwen": 1, "hhh_only": 1},
                "context_id": {"identity_off": 1, "identity_on": 1},
                "sample_index": {"5": 2},
            },
        },
        "expected_successful_judge_rows": 4,
        "maximum_attempts_per_judge_row": 3,
        "maximum_api_request_attempts": 12,
        "code": {"judge_runner_sha256": _sha(Path(target.__file__))},
    }


class ContractTests(unittest.TestCase):
    def test_contract_accepts_exact_counts_and_adds_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "behavior.jsonl"
            path.write_text("".join(json.dumps(row) + "\n" for row in _rows()))
            rows = target.load_rows(path)
            self.assertTrue(all("code_provenance" in row for row in rows))
            target.validate_contract(_contract(path), path, rows, 2)

    def test_contract_rejects_count_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "behavior.jsonl"
            path.write_text("".join(json.dumps(row) + "\n" for row in _rows()))
            rows = target.load_rows(path)
            rows[1]["context_id"] = "identity_on"
            with self.assertRaisesRegex(ValueError, "context_id counts"):
                target.validate_contract(_contract(path), path, rows, 2)

    def test_contract_rejects_duplicate_row_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "behavior.jsonl"
            rows = _rows()
            rows[1]["row_id"] = "a"
            path.write_text("".join(json.dumps(row) + "\n" for row in rows))
            loaded = target.load_rows(path)
            contract = _contract(path)
            with self.assertRaisesRegex(ValueError, "not unique"):
                target.validate_contract(contract, path, loaded, 2)


if __name__ == "__main__":
    unittest.main()
