import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "scripts/run_claim1_nla_harm_enrichment_decode_v1.py"
SPEC = importlib.util.spec_from_file_location("harm_decode", PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_prepare_blinds_scientific_metadata(tmp_path):
    source = tmp_path / "source.jsonl"
    source.write_text(json.dumps({
        "panel_cell_id": "opaque", "activation_sha256": "a" * 64,
        "activation_f32_le_b64": "AAAAAA==", "hidden_state_index": 21,
        "hook_semantics": "hook", "serialized_dtype": "float32_little_endian",
    }) + "\n")
    contract = {
        "source": {"new_decode_panel_path": str(source), "new_decode_panel_sha256": MODULE.sha256_file(source)},
        "expected": {"panel_rows": 1},
        "outputs": {"panel_root": str(tmp_path / "panel")},
    }
    MODULE.prepare(contract, "snapshot")
    row = json.loads((tmp_path / "panel/selected_activations.jsonl").read_text())
    assert row["activation_cell_id"] == "opaque"
    assert row["model_id"] == row["condition_id"] == row["position"] == "blinded"
    assert "outcome_group" not in row and "alignment_score" not in row


def test_checkpointing_writes_only_exact_boundaries(tmp_path):
    class Fake:
        @staticmethod
        def append_jsonl(path, row):
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a") as handle:
                handle.write(json.dumps(row) + "\n")

    contract = {"outputs": {"checkpoint_root": str(tmp_path / "checkpoints")}, "checkpointing": {"exact_row_boundaries": [2]}}
    MODULE.install_checkpointing(Fake, contract)
    output = tmp_path / "decoded.jsonl"
    Fake.append_jsonl(output, {"i": 1})
    assert not (tmp_path / "checkpoints/decode/decoded.rows-000002.jsonl").exists()
    Fake.append_jsonl(output, {"i": 2})
    assert (tmp_path / "checkpoints/decode/decoded.rows-000002.jsonl").read_text().count("\n") == 2
