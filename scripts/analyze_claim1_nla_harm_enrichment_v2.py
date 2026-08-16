#!/usr/bin/env python3
"""Receipt-finalization successor for Claim 1 harm-enrichment analysis."""

from __future__ import annotations

import argparse
import csv
import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import analyze_claim1_nla_harm_enrichment_v1 as base


STAGE = "claim1_nla_harm_enrichment_analysis_v2"
BASE_KEY = "nla.claim1_nla_harm_enrichment_analysis_v1"
CONTRACT_KEY = "nla.claim1_nla_harm_enrichment_analysis_v2"


def load_contract(snapshot_path: Path) -> tuple[dict[str, Any], str]:
    raw = snapshot_path.read_bytes()
    snapshot = json.loads(raw)
    if snapshot.get("stage") != STAGE:
        raise ValueError("snapshot stage mismatch")
    values = snapshot.get("values", {})
    predecessor = values.get(BASE_KEY)
    successor = values.get(CONTRACT_KEY)
    if not isinstance(predecessor, dict) or not isinstance(successor, dict):
        raise ValueError("snapshot lacks predecessor or successor contract")
    if successor.get("base_contract") != BASE_KEY:
        raise ValueError("successor base contract mismatch")
    contract = copy.deepcopy(predecessor)
    contract.update({key: copy.deepcopy(successor[key]) for key in ("status", "stage", "authorization", "outputs", "code")})
    contract["failed_predecessor"] = copy.deepcopy(successor["failed_predecessor"])
    return contract, base.hashlib.sha256(raw).hexdigest()


def file_outputs(outputs: dict[str, Path]) -> dict[str, Path]:
    expected = {"snapshot_copy", "merged_rows", "analysis_json", "summary_csv", "report_markdown"}
    selected = {name: path for name, path in outputs.items() if name in expected}
    if set(selected) != expected:
        raise ValueError("file output set differs from successor contract")
    return selected


def run(snapshot_path: Path) -> dict[str, Any]:
    contract, snapshot_sha = load_contract(snapshot_path)
    base.verify_bindings(contract)
    outputs = {name: base.resolve(path) for name, path in contract["outputs"].items()}
    if len(set(outputs.values())) != len(outputs):
        raise ValueError("duplicate output paths")
    existing = [path for path in outputs.values() if path.exists()]
    if existing:
        raise FileExistsError(f"refusing to overwrite outputs: {existing}")

    rows, merge = base.merge_rows(contract)
    analysis = contract["analysis"]
    analyses: dict[str, Any] = {}
    for sensitivity, reliable_only in (("unrestricted", False), ("coherence_2_and_on_prompt", True)):
        activations = base.build_activation_rows(rows, reliable_only=reliable_only, minimum_numeric=analysis["minimum_numeric_descriptions_per_activation"])
        block = {}
        for position in base.POSITIONS:
            for condition in base.CONDITIONS:
                for axis in base.AXES:
                    key = f"{position}|{condition}|{axis}"
                    block[key] = base.analyze_axis(activations, axis=axis, position=position, condition=condition, seed=analysis["bootstrap_seed"], samples=analysis["bootstrap_samples"], label=f"{sensitivity}|{key}")
        analyses[sensitivity] = block

    report = {
        "schema_version": "claim1_nla_harm_enrichment_analysis_v1",
        "stage_snapshot_sha256": snapshot_sha,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "merge_accounting": merge,
        "outcome_hierarchy": contract["outcome_hierarchy"],
        "analysis_contract": analysis,
        "missingness": base.missingness(rows),
        "request_harm_context": base.request_context_report(rows),
        "analyses": analyses,
        "interpretation_limits": contract["interpretation_limits"],
        "implementation_successor": "receipt_finalization_only",
    }
    merged_export = []
    for row in rows:
        parsed = row.get("parsed_output")
        merged_export.append({key: row.get(key) for key in ("panel_cell_id", "position", "condition_id", "prompt_id", "outcome_group", "sample_index", "description_index", "description_id", "source_status")} | {"coherence": parsed.get("coherence") if isinstance(parsed, dict) else None, "topic_relation": parsed.get("topic_relation") if isinstance(parsed, dict) else None, "request_harm_context": parsed.get("request_harm_context", {}).get("value") if isinstance(parsed, dict) else None, "axes": {axis: parsed.get("axes", {}).get(axis, {}).get("score") if isinstance(parsed, dict) else None for axis in base.AXES}, "axis_missing_reasons": {axis: parsed.get("axes", {}).get(axis, {}).get("missing_reason") if isinstance(parsed, dict) else None for axis in base.AXES}})
    base.write_jsonl(outputs["merged_rows"], merged_export)
    base.write_json(outputs["analysis_json"], report)
    outputs["summary_csv"].parent.mkdir(parents=True, exist_ok=True)
    with outputs["summary_csv"].open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["sensitivity", "position", "condition", "axis", "case_minus_control_mean", "ci_low", "ci_high", "prompt_n", "macro_auc", "auc_ci_low", "auc_ci_high", "auc_prompt_n"])
        writer.writeheader()
        for sensitivity, block in analyses.items():
            for result in block.values():
                effect = result["prompt_equal_weight_case_minus_control"]
                auc = result["prompt_macro_auc"]
                effect_ci = effect["bootstrap_percentile_95"] or [None, None]
                auc_ci = auc["bootstrap_percentile_95"] or [None, None]
                writer.writerow({"sensitivity": sensitivity, "position": result["position"], "condition": result["condition_id"], "axis": result["axis"], "case_minus_control_mean": effect["mean"], "ci_low": effect_ci[0], "ci_high": effect_ci[1], "prompt_n": effect["n"], "macro_auc": auc["mean"], "auc_ci_low": auc_ci[0], "auc_ci_high": auc_ci[1], "auc_prompt_n": auc["n"]})
    outputs["report_markdown"].write_text(base.markdown_report(report), encoding="utf-8")
    outputs["snapshot_copy"].write_bytes(snapshot_path.read_bytes())

    files = file_outputs(outputs)
    receipt = {
        "schema_version": "claim1_nla_harm_enrichment_analysis_completion_v2",
        "status": "complete",
        "stage_snapshot_sha256": snapshot_sha,
        "merge_accounting": merge,
        "outputs": {name: {"path": str(path.relative_to(base.ROOT)), "sha256": base.sha256(path), "bytes": path.stat().st_size} for name, path in files.items()},
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "external_requests": 0,
        "spending_usd": 0,
    }
    base.write_json(outputs["completion_receipt"], receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    args = parser.parse_args()
    receipt = run(args.snapshot.resolve())
    print(json.dumps({"status": receipt["status"], "merge_accounting": receipt["merge_accounting"], "stage_snapshot_sha256": receipt["stage_snapshot_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
