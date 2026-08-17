import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace


SCRIPT = Path(__file__).parents[1] / "scripts" / "verify_hhh_adapter_checkpoint_s3_v2.py"
SPEC = importlib.util.spec_from_file_location("verify_hhh_adapter_checkpoint_s3_v2", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


ARGS = SimpleNamespace(volume_id="volume")


def test_download_uses_direct_get_object(tmp_path, monkeypatch):
    observed = {}

    def aws(_args, operation, extra, **_kwargs):
        observed["operation"] = operation
        observed["extra"] = extra
        Path(extra[-1]).write_bytes(b"archive")
        return SimpleNamespace(returncode=0, stdout=json.dumps({"ContentLength": 7}), stderr="")

    monkeypatch.setattr(MODULE.v1_verify.v3, "ORIGINAL_AWS", aws)
    destination = tmp_path / "download.tar"
    value = MODULE.download_via_get_object(ARGS, "key", destination)
    assert observed["operation"] == "get-object"
    assert observed["extra"][:4] == ["--bucket", "volume", "--key", "key"]
    assert destination.read_bytes() == b"archive"
    assert value["transport"] == "s3api_get_object_without_head"


def test_invalid_get_response_fails_closed(tmp_path, monkeypatch):
    bad = SimpleNamespace(returncode=0, stdout="not-json", stderr="")
    monkeypatch.setattr(MODULE.v1_verify.v3, "ORIGINAL_AWS", lambda *_args, **_kwargs: bad)
    try:
        MODULE.download_via_get_object(ARGS, "key", tmp_path / "download.tar")
    except MODULE.archive_v1.ArchiveError as exc:
        assert "invalid JSON" in str(exc)
    else:
        raise AssertionError("invalid GetObject response unexpectedly passed")
