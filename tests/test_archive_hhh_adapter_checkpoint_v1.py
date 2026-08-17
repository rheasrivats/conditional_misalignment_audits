import hashlib
import importlib.util
import json
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "archive_hhh_adapter_checkpoint_v1.py"
SPEC = importlib.util.spec_from_file_location("archive_hhh_adapter_checkpoint_v1", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


SNAPSHOT = "a" * 64


def checkpoint(tmp_path: Path) -> Path:
    source = tmp_path / "exposure_002496"
    source.mkdir()
    files = {
        "adapter_config.json": b"{}\n",
        "adapter_model.safetensors": b"adapter",
    }
    manifest_files = {}
    for name, content in files.items():
        (source / name).write_bytes(content)
        manifest_files[name] = {
            "bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        }
    (source / "checkpoint_manifest.json").write_text(
        json.dumps(
            {
                "label": source.name,
                "kind": "within_run_exposure_checkpoint",
                "optimizer_step": 156,
                "processed_examples": 2496,
                "stage_snapshot_sha256": SNAPSHOT,
                "files": manifest_files,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return source


def test_checkpoint_validation_and_deterministic_tar(tmp_path):
    source = checkpoint(tmp_path)
    manifest = MODULE.validate_checkpoint(source, source.name, SNAPSHOT)
    assert manifest["processed_examples"] == 2496
    first = tmp_path / "first.tar"
    second = tmp_path / "second.tar"
    MODULE.build_deterministic_tar(source, first, source.name)
    MODULE.build_deterministic_tar(source, second, source.name)
    assert first.read_bytes() == second.read_bytes()


def test_manifest_hash_mismatch_is_blocked(tmp_path):
    source = checkpoint(tmp_path)
    (source / "adapter_config.json").write_text('{"changed":true}\n', encoding="utf-8")
    try:
        MODULE.validate_checkpoint(source, source.name, SNAPSHOT)
    except MODULE.ArchiveError as exc:
        assert "manifest file differs" in str(exc)
    else:
        raise AssertionError("corrupt checkpoint unexpectedly passed")


def test_snapshot_mismatch_is_blocked(tmp_path):
    source = checkpoint(tmp_path)
    try:
        MODULE.validate_checkpoint(source, source.name, "b" * 64)
    except MODULE.ArchiveError as exc:
        assert "snapshot differs" in str(exc)
    else:
        raise AssertionError("wrong snapshot unexpectedly passed")
