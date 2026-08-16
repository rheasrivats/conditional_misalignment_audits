#!/usr/bin/env python3
"""Compatibility wrapper for the frozen client Torch local-version field."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path


HERE = Path(__file__).resolve().parent
VERIFIER = HERE / "preflight_claim1_nla_harm_enrichment_runtime_v2.py"
CLIENT_PYTHON = Path("/workspace/venvs/medical-claim1-activation-bank-v1/bin/python")


def load_verifier():
    spec = importlib.util.spec_from_file_location("harm_runtime_preflight_v2", VERIFIER)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load symlink-aware verifier")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    verifier = load_verifier()
    original_load_base = verifier.load_base

    def compatible_load_base():
        base = original_load_base()
        original_versions = base.package_versions

        def compatible_versions(python: Path, names: list[str]) -> dict[str, str]:
            observed = original_versions(python, names)
            if Path(python) == CLIENT_PYTHON and "torch" in names:
                observed["torch"] = subprocess.check_output(
                    [str(python), "-c", "import torch; print(torch.__version__)"],
                    text=True,
                ).strip()
            return observed

        base.package_versions = compatible_versions
        return base

    verifier.STAGE = "claim1_nla_harm_enrichment_runtime_recovery_v8"
    verifier.PARAMETER = "operations.claim1_nla_harm_enrichment_runtime_recovery_v8"
    verifier.load_base = compatible_load_base
    verifier.main()


if __name__ == "__main__":
    main()
