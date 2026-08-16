#!/usr/bin/env python3
"""Load the frozen EM8 runner with Python 3.12-safe dynamic module imports."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


FROZEN_RUNNER = Path(
    "/workspace/staging/medical_nla_em8_layer_position_ar_v1/"
    "scripts/run_medical_nla_em8_layer_position_ar_v1.py"
)


def load_registered_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(spec.name, None)
        raise
    return module


runner = load_registered_module("frozen_medical_nla_em8_runner", FROZEN_RUNNER)


def corrected_load_module(path: Path) -> ModuleType:
    return load_registered_module("frozen_nla_inference", path)


runner.load_module = corrected_load_module
runner.main()
