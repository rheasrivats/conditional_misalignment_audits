from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import re
import stat
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESTORE_PATH = ROOT / "scripts" / "restore_medical_claim1_nla_models_v1.py"
BOOTSTRAP_PATH = ROOT / "scripts" / "bootstrap_medical_claim1_nla_runtime_v1.sh"


def load_module():
    spec = importlib.util.spec_from_file_location("claim1_nla_restore_tested", RESTORE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


restore = load_module()


def manifest_for(root: Path, path: Path) -> None:
    entries = []
    pending = [root]
    while pending:
        current = pending.pop()
        for child in sorted(current.iterdir(), key=lambda item: item.name):
            relative = child.relative_to(root).as_posix()
            entry = restore.filesystem_entry(child, relative)
            entries.append(entry)
            if entry["type"] == "directory":
                pending.append(child)
    entries.sort(key=lambda item: item["path"])
    entries_sha256 = hashlib.sha256(
        json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    path.write_text(json.dumps({"entries": entries, "entries_sha256": entries_sha256}, sort_keys=True) + "\n", encoding="utf-8")


def restore_successor(pycache_prefix: Path | None = None) -> dict[str, object]:
    return {
        "vendor_validation": {
            "verify_all_manifest_paths_without_mode_bits": True,
            "allow_only_unlisted_python_cache_entries": True,
            "reject_missing_or_content_mismatched_manifest_paths": True,
        },
        "python_import_isolation": {
            "pycache_prefix": str(pycache_prefix or Path("/nonexistent/test-pycache")),
            "require_prefix_absent": True,
            "dont_write_bytecode": True,
        },
    }


def resume_successor() -> dict[str, object]:
    return {
        "resume": {"reuse_exact_verified_first_archive": True},
        "capacity": {
            "measurement": "du_kib_allocated_bytes",
            "workspace_quota_bytes": 75_000_000_000,
            "minimum_free_reserve_bytes": 1_073_741_824,
        },
    }


def add_directory(archive: tarfile.TarFile, name: str, mode: int = 0o755) -> None:
    info = tarfile.TarInfo(name)
    info.type = tarfile.DIRTYPE
    info.mode = mode
    archive.addfile(info)


def add_file(archive: tarfile.TarFile, name: str, value: bytes, mode: int = 0o644) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(value)
    info.mode = mode
    archive.addfile(info, io.BytesIO(value))


class Claim1NLARestoreTests(unittest.TestCase):
    def test_bootstrap_embedded_python_compiles_and_imports_hashlib(self) -> None:
        text = BOOTSTRAP_PATH.read_text(encoding="utf-8")
        blocks = re.findall(r"<<'PY'\n(.*?)\nPY", text, flags=re.DOTALL)
        self.assertEqual(len(blocks), 2)
        for index, block in enumerate(blocks):
            compile(block, f"bootstrap-heredoc-{index}", "exec")
        receipt_block = next(block for block in blocks if "stage_snapshot_sha256" in block)
        self.assertRegex(receipt_block, r"(?m)^import hashlib$")

    def test_restore_integrity_gates_precede_credential_read(self) -> None:
        source = RESTORE_PATH.read_text(encoding="utf-8")
        main = source[source.index("def main()") :]
        credential_offset = main.index("credentials = read_credentials()")
        self.assertLess(main.index("validate_staged_code(args.snapshot, contract, resume_successor)"), credential_offset)
        self.assertLess(main.index("vendor_root = validate_vendor_tree(restore, restore_successor)"), credential_offset)
        self.assertLess(main.index("isolate_python_bytecode(restore_successor)"), credential_offset)
        self.assertLess(main.index("first_resume_archive = verify_resume_archive("), credential_offset)
        self.assertLess(main.index("import boto3"), credential_offset)

    def test_launcher_separates_server_from_client_ar_environment(self) -> None:
        launcher = (ROOT / "scripts" / "run_medical_claim1_nla_decode_v1.sh").read_text(encoding="utf-8")
        bootstrap = (ROOT / "scripts" / "bootstrap_medical_claim1_nla_runtime_v1.sh").read_text(encoding="utf-8")
        self.assertIn('server_venv=/workspace/venvs/medical-claim1-nla-decode-v1', launcher)
        self.assertIn('client_venv=/workspace/venvs/medical-claim1-activation-bank-v1', launcher)
        self.assertIn('PATH="$server_path" "$server_venv/bin/python" -m sglang.launch_server', launcher)
        for phase in ("prepare", "decode", "reconstruct", "validate"):
            self.assertIn(f'"$client_venv/bin/python" "$runner" {phase}', launcher)
            self.assertNotIn(f'"$server_venv/bin/python" "$runner" {phase}', launcher)
        self.assertIn('UV_PROJECT_ENVIRONMENT="$server_venv"', bootstrap)
        self.assertIn('"$uv_bin" sync --locked --extra nla-server', bootstrap)
        self.assertIn('UV_PROJECT_ENVIRONMENT="$client_venv"', bootstrap)
        self.assertIn('"$uv_bin" sync --locked --no-dev\n', bootstrap)
        self.assertIn('executing launcher SHA-256 mismatch', launcher)
        self.assertIn('runtime receipt path differs from frozen provenance', launcher)
        self.assertIn('restore receipt path differs from frozen provenance', launcher)
        self.assertIn('executing bootstrap SHA-256 mismatch', bootstrap)

    def test_safe_extract_requires_exact_prefix_and_verifies_tree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            extract_root = base / "installed" / "actor"
            prefix = extract_root.relative_to(Path("/")).as_posix()
            source = base / "source"
            source.mkdir()
            (source / "weights.bin").write_bytes(b"weights")
            os.chmod(source / "weights.bin", 0o644)
            manifest = base / "manifest.json"
            manifest_for(source, manifest)
            archive_path = base / "actor.tar"
            with tarfile.open(archive_path, "w:") as archive:
                add_directory(archive, prefix)
                add_file(archive, prefix + "/weights.bin", b"weights")
            restore.safe_extract_and_verify(
                archive_path, extract_root, manifest,
                restore.sha256_file(manifest), base / "extracting",
            )
            self.assertEqual((extract_root / "weights.bin").read_bytes(), b"weights")
            with self.assertRaisesRegex(FileExistsError, "refusing to overwrite"):
                restore.safe_extract_and_verify(
                    archive_path, extract_root, manifest,
                    restore.sha256_file(manifest), base / "extracting-second",
                )

    def test_tar_path_escape_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive_path = root / "escape.tar"
            with tarfile.open(archive_path, "w:") as archive:
                add_directory(archive, "expected")
                add_file(archive, "../escape", b"bad")
            with tarfile.open(archive_path, "r:") as archive:
                with self.assertRaisesRegex(ValueError, "unsafe tar member path"):
                    restore.validate_tar_members(archive, "expected")

    def test_tar_member_outside_exact_prefix_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive_path = Path(directory) / "outside.tar"
            with tarfile.open(archive_path, "w:") as archive:
                add_directory(archive, "expected")
                add_file(archive, "other/file", b"bad")
            with tarfile.open(archive_path, "r:") as archive:
                with self.assertRaisesRegex(ValueError, "outside exact prefix"):
                    restore.validate_tar_members(archive, "expected")

    def test_tar_symlink_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive_path = Path(directory) / "link.tar"
            with tarfile.open(archive_path, "w:") as archive:
                add_directory(archive, "expected")
                info = tarfile.TarInfo("expected/link")
                info.type = tarfile.SYMTYPE
                info.linkname = "/etc/passwd"
                archive.addfile(info)
            with tarfile.open(archive_path, "r:") as archive:
                with self.assertRaisesRegex(ValueError, "unsafe tar member type"):
                    restore.validate_tar_members(archive, "expected")

    def test_tar_device_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive_path = Path(directory) / "device.tar"
            with tarfile.open(archive_path, "w:") as archive:
                add_directory(archive, "expected")
                info = tarfile.TarInfo("expected/device")
                info.type = tarfile.CHRTYPE
                archive.addfile(info)
            with tarfile.open(archive_path, "r:") as archive:
                with self.assertRaisesRegex(ValueError, "unsafe tar member type"):
                    restore.validate_tar_members(archive, "expected")

    def test_vendor_manifest_is_checked_without_importing_vendor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "vendor"
            root.mkdir()
            (root / "sentinel.py").write_text("VALUE = 1\n", encoding="utf-8")
            manifest = Path(directory) / "vendor.manifest.json"
            manifest_for(root, manifest)
            entries_sha256 = json.loads(manifest.read_text())["entries_sha256"]
            vendor_contract = {"boto_vendor": {
                "root": str(root), "manifest_path": str(manifest),
                "manifest_sha256": restore.sha256_file(manifest),
                "entries_sha256": entries_sha256,
            }}
            os.chmod(root, 0o777)
            os.chmod(root / "sentinel.py", 0o666)
            cache = root / "__pycache__"
            cache.mkdir()
            (cache / "sentinel.cpython-312.pyc").write_bytes(b"runtime cache")
            selected = restore.validate_vendor_tree(vendor_contract, restore_successor())
            self.assertEqual(selected, root)
            (root / "sentinel.py").write_text("VALUE = 2\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "substantive manifest"):
                restore.validate_vendor_tree(vendor_contract, restore_successor())

    def test_vendor_manifest_rejects_unlisted_noncache_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "vendor"
            root.mkdir()
            (root / "sentinel.py").write_text("VALUE = 1\n", encoding="utf-8")
            manifest = Path(directory) / "vendor.manifest.json"
            manifest_for(root, manifest)
            entries_sha256 = json.loads(manifest.read_text())["entries_sha256"]
            (root / "unexpected.py").write_text("VALUE = 2\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "substantive manifest"):
                restore.validate_vendor_tree({"boto_vendor": {
                    "root": str(root), "manifest_path": str(manifest),
                    "manifest_sha256": restore.sha256_file(manifest),
                    "entries_sha256": entries_sha256,
                }}, restore_successor())

    def test_python_bytecode_is_redirected_to_fresh_nonexistent_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            prefix = Path(directory) / "isolated-pycache"
            previous_prefix = sys.pycache_prefix
            previous_dont_write = sys.dont_write_bytecode
            try:
                restore.isolate_python_bytecode(restore_successor(prefix))
                self.assertEqual(sys.pycache_prefix, str(prefix))
                self.assertTrue(sys.dont_write_bytecode)
                self.assertFalse(prefix.exists())
            finally:
                sys.pycache_prefix = previous_prefix
                sys.dont_write_bytecode = previous_dont_write

    def test_resume_accepts_only_the_exact_single_verified_first_archive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "first.tar"
            archive.write_bytes(b"verified archive")
            item = {
                "name": archive.name,
                "bytes": archive.stat().st_size,
                "sha256": restore.sha256_file(archive),
            }
            self.assertEqual(
                restore.verify_resume_archive(root, item, resume_successor()), archive
            )
            (root / "unexpected.tar").write_bytes(b"unexpected")
            with self.assertRaisesRegex(ValueError, "inventory differs"):
                restore.verify_resume_archive(root, item, resume_successor())

    def test_workspace_usage_uses_allocated_byte_du_measurement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "payload").write_bytes(b"x" * 8192)
            measured = restore.workspace_used_bytes(root)
            self.assertGreaterEqual(measured, 8192)


if __name__ == "__main__":
    unittest.main()
