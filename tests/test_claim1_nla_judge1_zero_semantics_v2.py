from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import analyze_claim1_nla_judge1_zero_semantics_v2 as successor


def contract(tmp_path: Path) -> dict:
    artifact = tmp_path / "artifact"
    artifact.write_text("exact\n", encoding="utf-8")
    binding = {"path": str(artifact), "sha256": successor.v1.sha256(artifact)}
    return {
        "immutable_inputs": {"input": binding},
        "code_and_spec": {"code": binding, "focused_tests_passed": 9},
        "execution": {"api_requests": 0, "egress": "none", "local_only": True, "spending_usd": 0},
    }


def test_verifier_accepts_focused_test_count_as_metadata(tmp_path: Path):
    successor.verify_contract(contract(tmp_path))


def test_verifier_rejects_invalid_nonbinding_metadata(tmp_path: Path):
    candidate = contract(tmp_path)
    candidate["code_and_spec"]["focused_tests_passed"] = "9"
    with pytest.raises(ValueError, match="invalid focused test count"):
        successor.verify_contract(candidate)


def test_verifier_still_hash_checks_bindings(tmp_path: Path):
    candidate = contract(tmp_path)
    Path(candidate["immutable_inputs"]["input"]["path"]).write_text("changed\n", encoding="utf-8")
    with pytest.raises(ValueError, match="immutable input mismatch"):
        successor.verify_contract(candidate)
