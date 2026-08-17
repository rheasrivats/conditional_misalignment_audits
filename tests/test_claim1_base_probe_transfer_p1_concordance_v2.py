import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location(
    "transfer_concordance_v2", ROOT / "scripts" / "analyze_claim1_base_probe_transfer_p1_concordance_v2.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_successor_stage_and_parameter_are_distinct() -> None:
    assert MODULE.STAGE.endswith("_v2")
    assert MODULE.PARAMETER.endswith("_v2")
    assert MODULE.BASE_PARAMETER.endswith("_v1")
