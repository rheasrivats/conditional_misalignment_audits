import importlib.util
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "scripts/preflight_claim1_nla_harm_enrichment_runtime_v1.py"
SPEC = importlib.util.spec_from_file_location("runtime_preflight", PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_verify_tree_accepts_exact_manifest(tmp_path):
    root = tmp_path / "model"
    root.mkdir()
    (root / "weights").write_bytes(b"abc")
    entries = [MODULE.entry(root / "weights", "weights")]
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"entries": entries}))
    MODULE.verify_tree(root, manifest, MODULE.sha256_file(manifest))


def test_verify_tree_rejects_content_drift(tmp_path):
    root = tmp_path / "model"
    root.mkdir()
    (root / "weights").write_bytes(b"abc")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"entries": [{
        "path": "weights", "type": "file", "mode": 420, "bytes": 3,
        "sha256": hashlib.sha256(b"xyz").hexdigest(),
    }]}))
    try:
        MODULE.verify_tree(root, manifest, MODULE.sha256_file(manifest))
    except ValueError as error:
        assert "differs" in str(error)
    else:
        raise AssertionError("expected drift rejection")
