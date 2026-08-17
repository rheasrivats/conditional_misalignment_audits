import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace


SCRIPT = Path(__file__).parents[1] / "scripts" / "archive_hhh_adapter_checkpoint_v3.py"
SPEC = importlib.util.spec_from_file_location("archive_hhh_adapter_checkpoint_v3", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


ARGS = SimpleNamespace(profile="profile", region="region", endpoint="https://endpoint")
EXTRA = ["--bucket", "volume", "--key", "immutable/key.tar", "--body", "/tmp/archive.tar"]


def test_large_upload_uses_s3_cp(monkeypatch):
    observed = {}

    def run(command, **kwargs):
        observed["command"] = command
        observed["kwargs"] = kwargs
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(MODULE.subprocess, "run", run)
    result = MODULE.aws_with_multipart_upload(ARGS, "put-object", EXTRA)
    assert observed["command"][:5] == [
        "aws", "s3", "cp", "/tmp/archive.tar", "s3://volume/immutable/key.tar"
    ]
    assert "--no-progress" in observed["command"]
    assert json.loads(result.stdout)["transport"] == "aws_s3_cp_multipart"


def test_large_upload_failure_is_blocking(monkeypatch):
    monkeypatch.setattr(
        MODULE.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=1, stdout="", stderr="failed"),
    )
    try:
        MODULE.aws_with_multipart_upload(ARGS, "put-object", EXTRA)
    except MODULE.v1.ArchiveError as exc:
        assert "multipart upload failed" in str(exc)
    else:
        raise AssertionError("failed multipart upload unexpectedly passed")


def test_nonupload_operation_delegates(monkeypatch):
    expected = SimpleNamespace(returncode=0, stdout="{}", stderr="")
    monkeypatch.setattr(MODULE, "ORIGINAL_AWS", lambda *_args, **_kwargs: expected)
    assert MODULE.aws_with_multipart_upload(ARGS, "head-object", []) is expected
