import hashlib
import importlib.util
from pathlib import Path


SCRIPT = (
    Path(__file__).parents[1]
    / "skills"
    / "runpod-experiment-operator"
    / "scripts"
    / "runpod_s3_checkpoint.py"
)
SPEC = importlib.util.spec_from_file_location("runpod_s3_checkpoint", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_valid_jsonl_and_checkpoint_key(tmp_path):
    path = tmp_path / "behavior.jsonl"
    path.write_text('{"row_id":"one"}\n{"row_id":"two"}\n', encoding="utf-8")
    assert MODULE.validate_jsonl(path) == 2
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert MODULE.checkpoint_key("run-one", 2, digest) == (
        f"runs/run-one/checkpoints/rows-000002-{digest[:12]}"
    )


def test_incomplete_line_is_blocked(tmp_path):
    path = tmp_path / "behavior.jsonl"
    path.write_text('{"row_id":"one"}', encoding="utf-8")
    try:
        MODULE.validate_jsonl(path)
    except MODULE.MirrorError as exc:
        assert "incomplete final" in str(exc)
    else:
        raise AssertionError("incomplete JSONL unexpectedly passed")


def test_duplicate_row_id_is_blocked(tmp_path):
    path = tmp_path / "behavior.jsonl"
    path.write_text('{"row_id":"one"}\n{"row_id":"one"}\n', encoding="utf-8")
    try:
        MODULE.validate_jsonl(path)
    except MODULE.MirrorError as exc:
        assert "duplicate row_id" in str(exc)
    else:
        raise AssertionError("duplicate row ID unexpectedly passed")


def test_unsafe_run_id_is_blocked():
    try:
        MODULE.checkpoint_key("../escape", 2, "a" * 64)
    except MODULE.MirrorError as exc:
        assert "run_id" in str(exc)
    else:
        raise AssertionError("unsafe run ID unexpectedly passed")
