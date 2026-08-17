import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace


SCRIPT = Path(__file__).parents[1] / "scripts" / "archive_hhh_adapter_checkpoint_v2.py"
SPEC = importlib.util.spec_from_file_location("archive_hhh_adapter_checkpoint_v2", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def args():
    return SimpleNamespace(volume_id="volume", profile="profile", region="region", endpoint="endpoint")


def result(value):
    return SimpleNamespace(stdout=json.dumps(value), stderr="", returncode=0)


def test_exact_list_absence_passes(monkeypatch):
    monkeypatch.setattr(MODULE.v1, "aws", lambda *_args, **_kwargs: result({"Prefix": "key"}))
    MODULE.ensure_absent_exact_list(args(), "key")


def test_exact_list_blocks_existing_object(monkeypatch):
    monkeypatch.setattr(
        MODULE.v1,
        "aws",
        lambda *_args, **_kwargs: result({"Contents": [{"Key": "key", "Size": 12}]}),
    )
    try:
        MODULE.ensure_absent_exact_list(args(), "key")
    except MODULE.v1.ArchiveError as exc:
        assert "already exists" in str(exc)
    else:
        raise AssertionError("existing immutable key unexpectedly passed")


def test_exact_list_ignores_nonexact_prefix_neighbor(monkeypatch):
    monkeypatch.setattr(
        MODULE.v1,
        "aws",
        lambda *_args, **_kwargs: result({"Contents": [{"Key": "key.sidecar", "Size": 12}]}),
    )
    MODULE.ensure_absent_exact_list(args(), "key")


def test_exact_list_invalid_json_fails_closed(monkeypatch):
    bad = SimpleNamespace(stdout="not-json", stderr="", returncode=0)
    monkeypatch.setattr(MODULE.v1, "aws", lambda *_args, **_kwargs: bad)
    try:
        MODULE.ensure_absent_exact_list(args(), "key")
    except MODULE.v1.ArchiveError as exc:
        assert "invalid JSON" in str(exc)
    else:
        raise AssertionError("invalid listing unexpectedly passed")
