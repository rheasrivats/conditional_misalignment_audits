#!/usr/bin/env python3
"""Reveal, merge, and analyze the frozen Claim 1 harm-enrichment panel."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
STAGE = "claim1_nla_harm_enrichment_analysis_v1"
CONTRACT_KEY = "nla.claim1_nla_harm_enrichment_analysis_v1"
AXES = ("P1", "P2", "V1", "V2", "H")
POSITIONS = ("assistant_token_8", "assistant_token_32")
CONDITIONS = ("identity_off", "identity_on")
GROUPS = ("clearly_aligned", "clearly_misaligned")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve(path: str) -> Path:
    value = Path(path)
    return value if value.is_absolute() else ROOT / value


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line:
            raise ValueError(f"blank JSONL line {line_number}: {path}")
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"non-object JSONL line {line_number}: {path}")
        rows.append(value)
    return rows


def write_json(path: Path, value: Any) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0, "mean": None, "median": None, "sd": None, "min": None, "max": None}
    return {
        "n": len(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "sd": statistics.stdev(values) if len(values) > 1 else 0.0,
        "min": min(values),
        "max": max(values),
    }


def percentile(sorted_values: list[float], probability: float) -> float:
    if not sorted_values:
        raise ValueError("percentile requires values")
    position = (len(sorted_values) - 1) * probability
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    weight = position - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def bootstrap_interval(values: list[float], *, seed: int, samples: int, label: str) -> list[float] | None:
    if not values:
        return None
    derived = int.from_bytes(hashlib.sha256(f"{seed}|{label}".encode()).digest()[:8], "big")
    rng = random.Random(derived)
    n = len(values)
    estimates = sorted(statistics.fmean(values[rng.randrange(n)] for _ in range(n)) for _ in range(samples))
    return [percentile(estimates, 0.025), percentile(estimates, 0.975)]


def auc_half_ties(cases: list[float], controls: list[float]) -> float | None:
    if not cases or not controls:
        return None
    credit = 0.0
    for case in cases:
        for control in controls:
            credit += 1.0 if case > control else (0.5 if case == control else 0.0)
    return credit / (len(cases) * len(controls))


def load_contract(snapshot_path: Path) -> tuple[dict[str, Any], str]:
    raw = snapshot_path.read_bytes()
    snapshot = json.loads(raw)
    if snapshot.get("stage") != STAGE:
        raise ValueError("snapshot stage mismatch")
    contract = snapshot.get("values", {}).get(CONTRACT_KEY)
    if not isinstance(contract, dict):
        raise ValueError("snapshot lacks analysis contract")
    return contract, hashlib.sha256(raw).hexdigest()


def verify_bindings(contract: dict[str, Any]) -> None:
    for section in ("immutable_inputs", "code"):
        for name, binding in contract[section].items():
            if not isinstance(binding, dict) or "path" not in binding or "sha256" not in binding:
                raise ValueError(f"invalid binding {section}.{name}")
            path = resolve(binding["path"])
            if sha256(path) != binding["sha256"]:
                raise ValueError(f"hash mismatch: {section}.{name}")
            if "rows" in binding and len(read_jsonl(path)) != binding["rows"]:
                raise ValueError(f"row mismatch: {section}.{name}")


def index_unique(rows: list[dict[str, Any]], key: str, label: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        value = row.get(key)
        if not isinstance(value, str) or value in result:
            raise ValueError(f"duplicate or invalid {label} key")
        result[value] = row
    return result


def merge_rows(contract: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    inputs = contract["immutable_inputs"]
    panel = read_jsonl(resolve(inputs["selection_reveal"]["path"]))
    panel_by_id = index_unique(panel, "panel_cell_id", "panel")
    if len(panel_by_id) != 234:
        raise ValueError("panel cell count differs from 234")
    for row in panel:
        if row.get("model_id") != "hhh_only" or row.get("position") not in POSITIONS or row.get("condition_id") not in CONDITIONS or row.get("outcome_group") not in GROUPS:
            raise ValueError("unexpected panel metadata")

    fresh_reveal = read_jsonl(resolve(inputs["fresh_reveal"]["path"]))
    fresh_accepted = read_jsonl(resolve(inputs["fresh_accepted"]["path"]))
    fresh_failed = read_jsonl(resolve(inputs["fresh_failed"]["path"]))
    reveal_by_item = index_unique(fresh_reveal, "item_id", "fresh reveal")
    accepted_by_item = index_unique(fresh_accepted, "item_id", "fresh accepted")
    failed_by_item = index_unique(fresh_failed, "item_id", "fresh failed")
    if set(accepted_by_item) & set(failed_by_item) or set(accepted_by_item) | set(failed_by_item) != set(reveal_by_item):
        raise ValueError("fresh terminal coverage mismatch")

    slot_rows: dict[tuple[str, int], dict[str, Any]] = {}
    for item_id, reveal in reveal_by_item.items():
        panel_id = reveal.get("panel_cell_id")
        index = reveal.get("description_index")
        if panel_id not in panel_by_id or not isinstance(index, int) or index not in (0, 1, 2):
            raise ValueError("invalid fresh reveal slot")
        meta = panel_by_id[panel_id]
        for field in ("model_id", "condition_id", "position", "prompt_id", "outcome_group", "sample_index"):
            if reveal.get(field) != meta.get(field):
                raise ValueError(f"fresh reveal metadata mismatch: {field}")
        if item_id in accepted_by_item:
            accepted = accepted_by_item[item_id]
            parsed = accepted.get("parsed_output")
            if not isinstance(parsed, dict) or parsed.get("item_id") != item_id or parsed.get("description_id") != reveal.get("description_id"):
                raise ValueError("fresh accepted identity mismatch")
            status = "accepted_fresh"
        else:
            failed = failed_by_item[item_id]
            if failed.get("terminal_state") != "exhausted_retries" or failed.get("analysis_disposition") != "missing_no_imputation":
                raise ValueError("unexpected fresh failure disposition")
            parsed = None
            status = "judge_exhausted"
        key = (panel_id, index)
        if key in slot_rows:
            raise ValueError("duplicate fresh description slot")
        slot_rows[key] = {**meta, "description_index": index, "description_id": reveal.get("description_id"), "source_status": status, "parsed_output": parsed}

    predecessor_reveal = read_jsonl(resolve(inputs["predecessor_reveal"]["path"]))
    predecessor_accepted = read_jsonl(resolve(inputs["predecessor_accepted"]["path"]))
    predecessor_by_source = index_unique(predecessor_reveal, "source_row_id", "predecessor reveal source")
    predecessor_accepted_by_item = index_unique(predecessor_accepted, "item_id", "predecessor accepted")
    reuse = read_jsonl(resolve(inputs["reuse_bindings"]["path"]))
    if len(reuse) != 234:
        raise ValueError("reuse binding count differs from 234")
    reused_count = 0
    for binding in reuse:
        panel_id = binding.get("panel_cell_id")
        if panel_id not in panel_by_id:
            raise ValueError("reuse binding references unknown panel cell")
        if binding.get("reuse_status") != "reuse_decode_and_reconstruction":
            continue
        descriptions = binding.get("descriptions")
        if not isinstance(descriptions, list) or len(descriptions) != 3:
            raise ValueError("reused activation lacks three descriptions")
        for description in descriptions:
            index = description.get("description_index")
            source_row_id = description.get("predecessor_decode_row_id")
            key = (panel_id, index)
            if key in slot_rows:
                continue
            predecessor_meta = predecessor_by_source.get(source_row_id)
            if predecessor_meta is None or predecessor_meta.get("description_index") != index or predecessor_meta.get("activation_cell_id") != binding.get("predecessor_activation_cell_id"):
                raise ValueError("predecessor reveal mismatch")
            accepted = predecessor_accepted_by_item.get(predecessor_meta.get("item_id"))
            if accepted is None or accepted.get("description_id") != predecessor_meta.get("description_id") or not isinstance(accepted.get("parsed_output"), dict):
                raise ValueError("predecessor accepted judgment mismatch")
            slot_rows[key] = {
                **panel_by_id[panel_id],
                "description_index": index,
                "description_id": predecessor_meta.get("description_id"),
                "source_status": "accepted_predecessor_reuse",
                "parsed_output": accepted["parsed_output"],
            }
            reused_count += 1

    decoded = read_jsonl(resolve(inputs["new_decoded"]["path"]))
    parse_failures = 0
    for row in decoded:
        panel_id = row.get("activation_cell_id")
        index = row.get("description_index")
        if row.get("nla_parse_ok") is False:
            key = (panel_id, index)
            if panel_id not in panel_by_id or key in slot_rows:
                raise ValueError("invalid AV parse-failure slot")
            slot_rows[key] = {
                **panel_by_id[panel_id],
                "description_index": index,
                "description_id": None,
                "source_status": "av_parse_failure",
                "parsed_output": None,
            }
            parse_failures += 1

    expected_slots = {(panel_id, index) for panel_id in panel_by_id for index in range(3)}
    if set(slot_rows) != expected_slots:
        raise ValueError("merged description slots do not exactly cover 702")
    rows = [slot_rows[key] for key in sorted(slot_rows)]
    counts = Counter(row["source_status"] for row in rows)
    if counts != Counter({"accepted_fresh": 668, "accepted_predecessor_reuse": 27, "judge_exhausted": 1, "av_parse_failure": 6}):
        raise ValueError(f"terminal merge counts differ from contract: {counts}")
    return rows, {"description_slots": len(rows), "activation_cells": len(panel_by_id), "source_status_counts": dict(sorted(counts.items())), "predecessor_judgments_reused": reused_count, "av_parse_failures": parse_failures}


def axis_value(row: dict[str, Any], axis: str, *, reliable_only: bool) -> float | None:
    parsed = row.get("parsed_output")
    if not isinstance(parsed, dict):
        return None
    if reliable_only and (parsed.get("coherence") != 2 or parsed.get("topic_relation") != "on_prompt"):
        return None
    value = parsed.get("axes", {}).get(axis, {}).get("score")
    return float(value) if is_number(value) else None


def build_activation_rows(rows: list[dict[str, Any]], *, reliable_only: bool, minimum_numeric: int) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[row["panel_cell_id"]].append(row)
    result: list[dict[str, Any]] = []
    for panel_id, descriptions in sorted(groups.items()):
        if len(descriptions) != 3:
            raise ValueError("activation does not have three description slots")
        meta = descriptions[0]
        item = {key: meta[key] for key in ("panel_cell_id", "position", "condition_id", "prompt_id", "outcome_group", "sample_index")}
        item["axes"] = {}
        for axis in AXES:
            numeric = [value for row in descriptions if (value := axis_value(row, axis, reliable_only=reliable_only)) is not None]
            item["axes"][axis] = {"numeric_description_count": len(numeric), "score": statistics.fmean(numeric) if len(numeric) >= minimum_numeric else None}
        result.append(item)
    return result


def analyze_axis(activations: list[dict[str, Any]], *, axis: str, position: str, condition: str, seed: int, samples: int, label: str) -> dict[str, Any]:
    selected = [row for row in activations if row["position"] == position and row["condition_id"] == condition]
    by_prompt_group: dict[tuple[str, str], list[float]] = defaultdict(list)
    activation_coverage = Counter()
    for row in selected:
        score = row["axes"][axis]["score"]
        key = f"{row['outcome_group']}|{'valid' if score is not None else 'missing'}"
        activation_coverage[key] += 1
        if score is not None:
            by_prompt_group[(row["prompt_id"], row["outcome_group"])].append(score)
    prompts = sorted({row["prompt_id"] for row in selected if row["outcome_group"] == "clearly_misaligned"})
    differences: list[float] = []
    prompt_aucs: list[float] = []
    prompt_rows: list[dict[str, Any]] = []
    for prompt_id in prompts:
        controls = by_prompt_group.get((prompt_id, "clearly_aligned"), [])
        cases = by_prompt_group.get((prompt_id, "clearly_misaligned"), [])
        difference = statistics.fmean(cases) - statistics.fmean(controls) if cases and controls else None
        auc = auc_half_ties(cases, controls)
        if difference is not None:
            differences.append(difference)
        if auc is not None:
            prompt_aucs.append(auc)
        prompt_rows.append({"prompt_id": prompt_id, "valid_case_activations": len(cases), "valid_control_activations": len(controls), "case_mean": statistics.fmean(cases) if cases else None, "control_mean": statistics.fmean(controls) if controls else None, "case_minus_control": difference, "auc": auc})
    effect = summary(differences)
    effect.update({"direction": "clearly_misaligned_minus_clearly_aligned", "bootstrap_samples": samples, "bootstrap_seed": seed, "bootstrap_percentile_95": bootstrap_interval(differences, seed=seed, samples=samples, label=f"{label}|effect")})
    auc_summary = summary(prompt_aucs)
    auc_summary.update({"tie_credit": 0.5, "chance_reference": 0.5, "bootstrap_samples": samples, "bootstrap_seed": seed, "bootstrap_percentile_95": bootstrap_interval(prompt_aucs, seed=seed, samples=samples, label=f"{label}|auc")})
    group_summaries = {}
    for group in GROUPS:
        prompt_means = [statistics.fmean(values) for (prompt_id, g), values in by_prompt_group.items() if g == group and prompt_id in prompts and values]
        group_summaries[group] = summary(prompt_means)
    return {"axis": axis, "position": position, "condition_id": condition, "case_bearing_prompts": len(prompts), "activation_coverage": dict(sorted(activation_coverage.items())), "prompt_equal_weight_group_summaries": group_summaries, "prompt_equal_weight_case_minus_control": effect, "prompt_macro_auc": auc_summary, "prompt_details": prompt_rows}


def missingness(rows: list[dict[str, Any]]) -> dict[str, Any]:
    report: dict[str, Any] = {}
    for position in POSITIONS:
        for condition in CONDITIONS:
            for group in GROUPS:
                subset = [row for row in rows if row["position"] == position and row["condition_id"] == condition and row["outcome_group"] == group]
                for axis in AXES:
                    counts = Counter()
                    reasons = Counter()
                    reliable = 0
                    for row in subset:
                        parsed = row.get("parsed_output")
                        if not isinstance(parsed, dict):
                            counts[row["source_status"]] += 1
                            continue
                        if parsed.get("coherence") == 2 and parsed.get("topic_relation") == "on_prompt":
                            reliable += 1
                        axis_row = parsed.get("axes", {}).get(axis, {})
                        if is_number(axis_row.get("score")):
                            counts["numeric"] += 1
                        else:
                            counts["axis_null"] += 1
                            reasons[str(axis_row.get("missing_reason"))] += 1
                    report[f"{position}|{condition}|{group}|{axis}"] = {"description_slots": len(subset), "status_counts": dict(sorted(counts.items())), "missing_reasons": dict(sorted(reasons.items())), "coherence_2_on_prompt_descriptions": reliable}
    return report


def request_context_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for position in POSITIONS:
        for condition in CONDITIONS:
            for group in GROUPS:
                subset = [row for row in rows if row["position"] == position and row["condition_id"] == condition and row["outcome_group"] == group and isinstance(row.get("parsed_output"), dict)]
                contexts = Counter(row["parsed_output"].get("request_harm_context", {}).get("value") for row in subset)
                h_by_context: dict[str, list[float]] = defaultdict(list)
                for row in subset:
                    context = row["parsed_output"].get("request_harm_context", {}).get("value")
                    value = axis_value(row, "H", reliable_only=False)
                    if isinstance(context, str) and value is not None:
                        h_by_context[context].append(value)
                result[f"{position}|{condition}|{group}"] = {"accepted_descriptions": len(subset), "request_context_counts": {str(k): v for k, v in sorted(contexts.items(), key=lambda item: str(item[0]))}, "description_level_h_by_context_descriptive_only": {context: summary(values) for context, values in sorted(h_by_context.items())}}
    return result


def markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# Claim 1 harm-enrichment NLA analysis",
        "",
        "This is an exploratory, outcome-enriched case-control analysis. `H` was pre-specified; P1/P2/V1/V2 are post-hoc descriptive diagnostics.",
        "",
        "## Primary HHH-ON results",
        "",
        "| Position | Axis | Case−control | 95% prompt bootstrap | Prompts | Macro AUC | AUC 95% interval |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    unrestricted = report["analyses"]["unrestricted"]
    for position in ("assistant_token_32", "assistant_token_8"):
        for axis in AXES:
            result = unrestricted[f"{position}|identity_on|{axis}"]
            effect = result["prompt_equal_weight_case_minus_control"]
            auc = result["prompt_macro_auc"]
            effect_ci = effect["bootstrap_percentile_95"]
            auc_ci = auc["bootstrap_percentile_95"]
            effect_ci_text = "NA" if effect_ci is None else f"[{effect_ci[0]:+.3f}, {effect_ci[1]:+.3f}]"
            auc_ci_text = "NA" if auc_ci is None else f"[{auc_ci[0]:.3f}, {auc_ci[1]:.3f}]"
            lines.append(f"| {position.replace('assistant_', '')} | {axis} | {effect['mean']:+.3f} | {effect_ci_text} | {effect['n']} | {auc['mean']:.3f} | {auc_ci_text} |")
    lines.extend(["", "## Reliability sensitivity (coherence 2 and on-prompt)", "", "| Position | Axis | Case−control | 95% prompt bootstrap | Prompts | Macro AUC |", "|---|---|---:|---:|---:|---:|"])
    reliable = report["analyses"]["coherence_2_and_on_prompt"]
    for position in ("assistant_token_32", "assistant_token_8"):
        for axis in AXES:
            result = reliable[f"{position}|identity_on|{axis}"]
            effect = result["prompt_equal_weight_case_minus_control"]
            auc = result["prompt_macro_auc"]
            ci = effect["bootstrap_percentile_95"]
            ci_text = "NA" if ci is None else f"[{ci[0]:+.3f}, {ci[1]:+.3f}]"
            mean_text = "NA" if effect["mean"] is None else f"{effect['mean']:+.3f}"
            auc_text = "NA" if auc["mean"] is None else f"{auc['mean']:.3f}"
            lines.append(f"| {position.replace('assistant_', '')} | {axis} | {mean_text} | {ci_text} | {effect['n']} | {auc_text} |")
    lines.extend(["", "## Interpretation", "", "Positive case−control values mean the NLA judge assigned higher axis scores to activations from clearly misaligned completed responses than to matched clearly aligned controls. For H specifically, a positive value means greater NLA-attributed prospective response-harm potential. AUC is the probability that a randomly chosen valid case activation outranks a valid control activation within the same prompt, with ties worth one half.", "", "Identity-OFF results are retained in the JSON/CSV but are descriptive only because all five OFF cases come from one prompt. No null is converted to zero and no general misalignment composite is constructed.", ""])
    return "\n".join(lines)


def run(snapshot_path: Path) -> dict[str, Any]:
    contract, snapshot_sha = load_contract(snapshot_path)
    verify_bindings(contract)
    outputs = {name: resolve(path) for name, path in contract["outputs"].items()}
    if len(set(outputs.values())) != len(outputs):
        raise ValueError("duplicate output paths")
    existing = [path for path in outputs.values() if path.exists()]
    if existing:
        raise FileExistsError(f"refusing to overwrite outputs: {existing}")
    rows, merge = merge_rows(contract)
    analysis = contract["analysis"]
    analyses: dict[str, Any] = {}
    activation_reports: dict[str, list[dict[str, Any]]] = {}
    for sensitivity, reliable_only in (("unrestricted", False), ("coherence_2_and_on_prompt", True)):
        activations = build_activation_rows(rows, reliable_only=reliable_only, minimum_numeric=analysis["minimum_numeric_descriptions_per_activation"])
        activation_reports[sensitivity] = activations
        block = {}
        for position in POSITIONS:
            for condition in CONDITIONS:
                for axis in AXES:
                    key = f"{position}|{condition}|{axis}"
                    block[key] = analyze_axis(activations, axis=axis, position=position, condition=condition, seed=analysis["bootstrap_seed"], samples=analysis["bootstrap_samples"], label=f"{sensitivity}|{key}")
        analyses[sensitivity] = block
    report = {
        "schema_version": "claim1_nla_harm_enrichment_analysis_v1",
        "stage_snapshot_sha256": snapshot_sha,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "merge_accounting": merge,
        "outcome_hierarchy": contract["outcome_hierarchy"],
        "analysis_contract": analysis,
        "missingness": missingness(rows),
        "request_harm_context": request_context_report(rows),
        "analyses": analyses,
        "interpretation_limits": contract["interpretation_limits"],
    }
    merged_export = []
    for row in rows:
        parsed = row.get("parsed_output")
        merged_export.append({key: row.get(key) for key in ("panel_cell_id", "position", "condition_id", "prompt_id", "outcome_group", "sample_index", "description_index", "description_id", "source_status")} | {"coherence": parsed.get("coherence") if isinstance(parsed, dict) else None, "topic_relation": parsed.get("topic_relation") if isinstance(parsed, dict) else None, "request_harm_context": parsed.get("request_harm_context", {}).get("value") if isinstance(parsed, dict) else None, "axes": {axis: parsed.get("axes", {}).get(axis, {}).get("score") if isinstance(parsed, dict) else None for axis in AXES}, "axis_missing_reasons": {axis: parsed.get("axes", {}).get(axis, {}).get("missing_reason") if isinstance(parsed, dict) else None for axis in AXES}})
    write_jsonl(outputs["merged_rows"], merged_export)
    write_json(outputs["analysis_json"], report)
    outputs["summary_csv"].parent.mkdir(parents=True, exist_ok=True)
    if outputs["summary_csv"].exists():
        raise FileExistsError(outputs["summary_csv"])
    with outputs["summary_csv"].open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["sensitivity", "position", "condition", "axis", "case_minus_control_mean", "ci_low", "ci_high", "prompt_n", "macro_auc", "auc_ci_low", "auc_ci_high", "auc_prompt_n"])
        writer.writeheader()
        for sensitivity, block in analyses.items():
            for key, result in block.items():
                effect = result["prompt_equal_weight_case_minus_control"]
                auc = result["prompt_macro_auc"]
                effect_ci = effect["bootstrap_percentile_95"] or [None, None]
                auc_ci = auc["bootstrap_percentile_95"] or [None, None]
                writer.writerow({"sensitivity": sensitivity, "position": result["position"], "condition": result["condition_id"], "axis": result["axis"], "case_minus_control_mean": effect["mean"], "ci_low": effect_ci[0], "ci_high": effect_ci[1], "prompt_n": effect["n"], "macro_auc": auc["mean"], "auc_ci_low": auc_ci[0], "auc_ci_high": auc_ci[1], "auc_prompt_n": auc["n"]})
    if outputs["report_markdown"].exists():
        raise FileExistsError(outputs["report_markdown"])
    outputs["report_markdown"].write_text(markdown_report(report), encoding="utf-8")
    if outputs["snapshot_copy"].exists():
        raise FileExistsError(outputs["snapshot_copy"])
    outputs["snapshot_copy"].write_bytes(snapshot_path.read_bytes())
    receipt = {"schema_version": "claim1_nla_harm_enrichment_analysis_completion_v1", "status": "complete", "stage_snapshot_sha256": snapshot_sha, "merge_accounting": merge, "outputs": {name: {"path": str(path.relative_to(ROOT)), "sha256": sha256(path), "bytes": path.stat().st_size} for name, path in outputs.items() if name != "completion_receipt"}, "completed_at_utc": datetime.now(timezone.utc).isoformat(), "external_requests": 0, "spending_usd": 0}
    write_json(outputs["completion_receipt"], receipt)
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
