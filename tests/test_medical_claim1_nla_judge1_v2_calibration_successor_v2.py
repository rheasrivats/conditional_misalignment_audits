from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_medical_claim1_nla_judge1_v2_calibration_successor_v2.py"
SPEC = importlib.util.spec_from_file_location("judge1_v2_calibration_successor_v2", SCRIPT)
assert SPEC and SPEC.loader
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


def test_successor_changes_only_embedded_system_prompt(tmp_path: Path) -> None:
    base_packet = ROOT / "runs/medical_claim1_nla_judge1_v2_calibration/attempt_001/inputs/calibration_packet.v2.jsonl"
    base_system = ROOT / "analysis/proposed/medical_claim1_nla_judge1_v2/independent_system.v2.txt"
    addendum = ROOT / "analysis/proposed/medical_claim1_nla_judge1_v2/luna_cross_field_addendum.v3.txt"
    output = tmp_path / "packet.jsonl"
    manifest = tmp_path / "manifest.json"
    builder.build(
        base_packet=base_packet,
        base_system=base_system,
        addendum=addendum,
        output_packet=output,
        output_manifest=manifest,
    )
    before = builder.read_jsonl(base_packet)
    after = builder.read_jsonl(output)
    assert len(after) == 16
    for old, new in zip(before, after, strict=True):
        assert new["system_prompt"].endswith("\n\n" + addendum.read_text())
        assert {k: v for k, v in new.items() if k != "system_prompt"} == {
            k: v for k, v in old.items() if k != "system_prompt"
        }
    assert json.loads(manifest.read_text())["request_count"] == 32


def test_successor_is_no_overwrite(tmp_path: Path) -> None:
    base_packet = ROOT / "runs/medical_claim1_nla_judge1_v2_calibration/attempt_001/inputs/calibration_packet.v2.jsonl"
    base_system = ROOT / "analysis/proposed/medical_claim1_nla_judge1_v2/independent_system.v2.txt"
    addendum = ROOT / "analysis/proposed/medical_claim1_nla_judge1_v2/luna_cross_field_addendum.v3.txt"
    output = tmp_path / "packet.jsonl"
    manifest = tmp_path / "manifest.json"
    kwargs = dict(base_packet=base_packet, base_system=base_system, addendum=addendum, output_packet=output, output_manifest=manifest)
    builder.build(**kwargs)
    with pytest.raises(FileExistsError):
        builder.build(**kwargs)
