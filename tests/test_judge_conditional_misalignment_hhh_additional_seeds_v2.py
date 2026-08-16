from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SCRIPT = ROOT / "scripts/judge_conditional_misalignment_hhh_additional_seeds_v2.py"
SPEC = importlib.util.spec_from_file_location("additional_seed_judge_v2", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def authorization(launcher_sha256: str) -> dict[str, object]:
    return {
        "approval": "DEC-0328",
        "destination": "api.openai.com",
        "generated_evaluation_rows": 2600,
        "alignment_and_coherence_judgments": 5200,
        "predecessor_snapshot_sha256": "1633c7b9fbf66c783680618ad0aa33b0bd9abbf5b17c3de4441a5c134b2ba7a3",
        "launcher_sha256": launcher_sha256,
    }


def write_snapshot(path: Path, value: dict[str, object]) -> None:
    path.write_text(
        json.dumps(
            {
                "stage": MODULE.predecessor.STAGE,
                "values": {MODULE.AUTHORIZATION: value},
            }
        )
    )


def test_accepts_exact_authorization(tmp_path: Path) -> None:
    path = tmp_path / "snapshot.json"
    write_snapshot(path, authorization(MODULE.predecessor.base.sha256_file(SCRIPT)))
    MODULE.validate_authorization(path)


def test_rejects_destination_drift(tmp_path: Path) -> None:
    path = tmp_path / "snapshot.json"
    value = authorization(MODULE.predecessor.base.sha256_file(SCRIPT))
    value["destination"] = "example.com"
    write_snapshot(path, value)
    with pytest.raises(ValueError, match="destination"):
        MODULE.validate_authorization(path)
