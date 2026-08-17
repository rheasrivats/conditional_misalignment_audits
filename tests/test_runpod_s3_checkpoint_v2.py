import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace


SCRIPT = Path(__file__).parents[1] / "scripts" / "runpod_s3_checkpoint_v2.py"
SPEC = importlib.util.spec_from_file_location("runpod_s3_checkpoint_v2", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


KWARGS = {
    "profile": "profile",
    "region": "region",
    "endpoint": "endpoint",
    "bucket": "bucket",
    "key": "key",
}


def listing(contents):
    return SimpleNamespace(
        args=["aws"],
        returncode=0,
        stdout=json.dumps({"Contents": contents}),
        stderr="",
    )


def test_absence_uses_exact_listing_and_not_head(monkeypatch):
    observed = {}

    def aws_command(**kwargs):
        observed.update(kwargs)
        return listing([{"Key": "key.other", "Size": 1}])

    monkeypatch.setattr(MODULE.base, "aws_command", aws_command)
    MODULE.ensure_absent_exact_list(**KWARGS)
    assert observed["operation"] == "list-objects-v2"
    assert observed["extra"] == ["--bucket", "bucket", "--prefix", "key"]


def test_absence_rejects_exact_existing_key(monkeypatch):
    monkeypatch.setattr(
        MODULE.base,
        "aws_command",
        lambda **_kwargs: listing([{"Key": "key", "Size": 10}]),
    )
    try:
        MODULE.ensure_absent_exact_list(**KWARGS)
    except MODULE.base.MirrorError as exc:
        assert "already exists" in str(exc)
    else:
        raise AssertionError("existing immutable key unexpectedly passed")


def test_post_upload_listing_derives_size(monkeypatch):
    monkeypatch.setattr(
        MODULE.base,
        "aws_command",
        lambda **_kwargs: listing([{"Key": "key", "Size": 323, "ETag": "etag"}]),
    )
    value = MODULE.head_object_exact_list(**KWARGS)
    assert value["ContentLength"] == 323
    assert value["VerificationSource"] == "list-objects-v2_exact_key"


def test_upload_uses_multipart_capable_s3_cp(monkeypatch, tmp_path):
    observed = {}

    def run(command, **kwargs):
        observed["command"] = command
        observed["kwargs"] = kwargs
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(MODULE.subprocess, "run", run)
    value = MODULE.put_file_multipart(**KWARGS, path=tmp_path / "source")
    assert observed["command"][:3] == ["aws", "s3", "cp"]
    assert "head-object" not in observed["command"]
    assert value == {"transport": "aws_s3_cp_multipart"}


def test_main_preserves_direct_get_object(monkeypatch):
    original_get = MODULE.base.get_file
    monkeypatch.setattr(MODULE.base, "main", lambda: 0)
    assert MODULE.main() == 0
    assert MODULE.base.ensure_absent is MODULE.ensure_absent_exact_list
    assert MODULE.base.put_file is MODULE.put_file_multipart
    assert MODULE.base.head_object is MODULE.head_object_exact_list
    assert MODULE.base.get_file is original_get
