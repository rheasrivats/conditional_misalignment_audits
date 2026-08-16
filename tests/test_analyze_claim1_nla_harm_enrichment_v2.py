import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from analyze_claim1_nla_harm_enrichment_v2 import file_outputs


def test_file_outputs_excludes_root_and_receipt() -> None:
    outputs = {
        "root": Path("attempt_002"),
        "snapshot_copy": Path("snapshot.json"),
        "merged_rows": Path("merged.jsonl"),
        "analysis_json": Path("analysis.json"),
        "summary_csv": Path("summary.csv"),
        "report_markdown": Path("report.md"),
        "completion_receipt": Path("receipt.json"),
    }
    assert set(file_outputs(outputs)) == {"snapshot_copy", "merged_rows", "analysis_json", "summary_csv", "report_markdown"}
