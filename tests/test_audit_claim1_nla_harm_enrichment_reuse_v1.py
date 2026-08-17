import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts/audit_claim1_nla_harm_enrichment_reuse_v1.py"
SPEC = importlib.util.spec_from_file_location("harm_reuse", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)
build_reuse = MODULE.build_reuse


def test_load_snapshot_uses_freezer_values_shape(tmp_path):
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps({
        "stage": MODULE.STAGE,
        "values": {MODULE.CONTRACT_KEY: {"sentinel": True}},
    }))
    assert MODULE.load_snapshot(path)["values"][MODULE.CONTRACT_KEY]["sentinel"] is True


def test_build_reuse_separates_decode_and_judge_reuse():
    new = [
        {"panel_cell_id": "new8", "activation_sha256": "sha8"},
        {"panel_cell_id": "new32", "activation_sha256": "sha32"},
        {"panel_cell_id": "novel", "activation_sha256": "novelsha"},
    ]
    old = [
        {"activation_cell_id": "old8", "activation_sha256": "sha8", "position": "assistant_token_8"},
        {"activation_cell_id": "old32", "activation_sha256": "sha32", "position": "assistant_token_32"},
    ]
    decoded = []
    reconstructed = []
    seeds = {0: 11, 1: 12, 2: 13}
    for cell, sha in (("old8", "sha8"), ("old32", "sha32")):
        for index, seed in seeds.items():
            row_id = f"d-{cell}-{index}"
            decoded.append({
                "activation_cell_id": cell, "activation_sha256": sha,
                "description_index": index, "sampling_seed": seed, "row_id": row_id,
            })
            reconstructed.append({
                "activation_sha256": sha, "description_row_id": row_id,
                "row_id": f"r-{cell}-{index}",
            })
    reveal = [
        {"activation_cell_id": "old32", "description_index": index,
         "description_id": f"D{index}", "item_id": f"J{index}"}
        for index in seeds
    ]
    accepted = [{"item_id": f"J{index}"} for index in seeds]

    bindings, new_decode, counts = build_reuse(
        new, old, decoded, reconstructed, reveal, accepted, seeds
    )

    assert [row["panel_cell_id"] for row in new_decode] == ["novel"]
    assert counts == {
        "new_panel_cells": 3,
        "reusable_activation_cells": 2,
        "reusable_token_8_cells": 1,
        "reusable_token_32_cells": 1,
        "reusable_descriptions": 6,
        "reusable_reconstructions": 6,
        "reusable_judgments": 3,
        "new_decode_cells": 1,
        "new_descriptions": 3,
        "maximum_new_judgments": 6,
    }
    assert sum("predecessor_judge_item_id" in d for b in bindings for d in b.get("descriptions", [])) == 3


def test_build_reuse_rejects_incomplete_decode_triplet():
    new = [{"panel_cell_id": "new", "activation_sha256": "sha"}]
    old = [{"activation_cell_id": "old", "activation_sha256": "sha", "position": "assistant_token_8"}]
    decoded = [{
        "activation_cell_id": "old", "activation_sha256": "sha",
        "description_index": 0, "sampling_seed": 11, "row_id": "d0",
    }]
    reconstructed = [{"activation_sha256": "sha", "description_row_id": "d0", "row_id": "r0"}]
    try:
        build_reuse(new, old, decoded, reconstructed, [], [], {0: 11, 1: 12, 2: 13})
    except ValueError as error:
        assert "incomplete predecessor decode triplet" in str(error)
    else:
        raise AssertionError("expected incomplete-triplet rejection")


def test_build_reuse_ignores_unreferenced_duplicate_predecessor_hashes():
    bindings, new_decode, counts = build_reuse(
        [{"panel_cell_id": "new", "activation_sha256": "novel"}],
        [
            {"activation_cell_id": "a", "activation_sha256": "duplicate", "position": "assistant_token_8"},
            {"activation_cell_id": "b", "activation_sha256": "duplicate", "position": "assistant_token_8"},
        ],
        [], [], [], [], {0: 11, 1: 12, 2: 13},
    )
    assert bindings[0]["reuse_status"] == "new_decode_required"
    assert new_decode[0]["panel_cell_id"] == "new"
    assert counts["reusable_activation_cells"] == 0
