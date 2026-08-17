import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace


SCRIPT = Path(__file__).parents[1] / "scripts" / "verify_hhh_adapter_checkpoint_s3_v1.py"
SPEC = importlib.util.spec_from_file_location("verify_hhh_adapter_checkpoint_s3_v1", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


ARGS = SimpleNamespace(volume_id="volume", profile="profile", region="region", endpoint="endpoint")


def response(value):
    return SimpleNamespace(returncode=0, stdout=json.dumps(value), stderr="")


def test_exact_object_requires_one_exact_match(monkeypatch):
    monkeypatch.setattr(
        MODULE.v3,
        "ORIGINAL_AWS",
        lambda *_args, **_kwargs: response({"Contents": [{"Key": "key", "Size": 7}]}),
    )
    assert MODULE.exact_object(ARGS, "key")["Size"] == 7


def test_exact_object_rejects_only_prefix_neighbor(monkeypatch):
    monkeypatch.setattr(
        MODULE.v3,
        "ORIGINAL_AWS",
        lambda *_args, **_kwargs: response({"Contents": [{"Key": "key.other", "Size": 7}]}),
    )
    try:
        MODULE.exact_object(ARGS, "key")
    except MODULE.v1.ArchiveError as exc:
        assert "found 0" in str(exc)
    else:
        raise AssertionError("missing exact object unexpectedly passed")


def test_download_failure_is_blocking(tmp_path, monkeypatch):
    monkeypatch.setattr(
        MODULE.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=1, stdout="", stderr="failed"),
    )
    try:
        MODULE.download(ARGS, "key", tmp_path / "download.tar")
    except MODULE.v1.ArchiveError as exc:
        assert "download failed" in str(exc)
    else:
        raise AssertionError("failed download unexpectedly passed")
