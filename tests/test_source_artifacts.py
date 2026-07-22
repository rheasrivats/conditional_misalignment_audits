from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "verify_source_artifacts.py"
SPEC = importlib.util.spec_from_file_location("verify_source_artifacts", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class SourceArtifactTests(unittest.TestCase):
    def test_hash_and_line_count(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.jsonl"
            path.write_bytes(b'{"a":1}\n\n{"b":2}\n')
            self.assertEqual(module.count_nonempty_lines(path), 2)
            self.assertEqual(
                module.sha256_file(path),
                "c46001ff20c7a0102c8b7ba3807a188daee6e5e38654f0b8c6066b1758056056",
            )


if __name__ == "__main__":
    unittest.main()
