import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace


SCRIPT = Path(__file__).parents[1] / "scripts" / "archive_hhh_adapter_checkpoint_v4.py"
SPEC = importlib.util.spec_from_file_location("archive_hhh_adapter_checkpoint_v4", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


ARGS = SimpleNamespace(volume_id="volume", profile="profile", region="region", endpoint="endpoint")
EXTRA = ["--bucket", "volume", "--key", "key"]


def listing(contents):
    return SimpleNamespace(args=["aws"], returncode=0, stdout=json.dumps({"Contents": contents}), stderr="")


def test_head_is_replaced_by_exact_listing(monkeypatch):
    monkeypatch.setattr(
        MODULE.v3,
        "ORIGINAL_AWS",
        lambda *_args, **_kwargs: listing([{"Key": "key", "Size": 323, "ETag": "etag"}]),
    )
    value = json.loads(MODULE.aws_runpod_compatible(ARGS, "head-object", EXTRA).stdout)
    assert value["ContentLength"] == 323
    assert value["VerificationSource"] == "list-objects-v2_exact_key"


def test_post_upload_listing_requires_exact_object(monkeypatch):
    monkeypatch.setattr(
        MODULE.v3,
        "ORIGINAL_AWS",
        lambda *_args, **_kwargs: listing([{"Key": "key.other", "Size": 323}]),
    )
    try:
        MODULE.aws_runpod_compatible(ARGS, "head-object", EXTRA)
    except MODULE.v1.ArchiveError as exc:
        assert "found 0" in str(exc)
    else:
        raise AssertionError("missing exact post-upload object unexpectedly passed")


def test_put_uses_multipart_successor(monkeypatch):
    expected = SimpleNamespace(returncode=0, stdout="{}", stderr="")
    monkeypatch.setattr(MODULE.v3, "aws_with_multipart_upload", lambda *_args, **_kwargs: expected)
    assert MODULE.aws_runpod_compatible(ARGS, "put-object", []) is expected


def test_get_delegates_to_direct_s3api(monkeypatch):
    expected = SimpleNamespace(returncode=0, stdout="{}", stderr="")
    observed = {}

    def original(_args, operation, extra, **_kwargs):
        observed["operation"] = operation
        return expected

    monkeypatch.setattr(MODULE.v3, "ORIGINAL_AWS", original)
    assert MODULE.aws_runpod_compatible(ARGS, "get-object", []) is expected
    assert observed["operation"] == "get-object"
