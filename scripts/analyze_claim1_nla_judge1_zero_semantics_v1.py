#!/usr/bin/env python3
"""Run the frozen local-only Claim 1 Judge 1 zero-semantics sensitivity."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import analyze_medical_claim1_nla_judge1_v3_target as v3


ROOT = Path(__file__).resolve().parents[1]
STAGE = "claim1_nla_judge1_zero_semantics_sensitivity_v1"
CONTRACT_KEY = "nla.claim1_nla_judge1_zero_semantics_sensitivity_v1"
PV_AXES = ("P1", "P2", "V1", "V2")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve(path: str) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else ROOT / candidate


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def write_json(path: Path, value: Any) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")


def load_contract(snapshot_path: Path) -> tuple[dict[str, Any], str]:
    snapshot_bytes = snapshot_path.read_bytes()
    snapshot_sha = hashlib.sha256(snapshot_bytes).hexdigest()
    snapshot = json.loads(snapshot_bytes)
    if snapshot.get("stage") != STAGE:
        raise ValueError("snapshot stage mismatch")
    values = snapshot.get("values")
    if not isinstance(values, dict) or set(values) != {CONTRACT_KEY}:
        raise ValueError("snapshot contains unexpected contract values")
    contract = values[CONTRACT_KEY]
    if not isinstance(contract, dict):
        raise ValueError("snapshot contract is not an object")
    return contract, snapshot_sha


def verify_contract(contract: dict[str, Any]) -> None:
    for binding in contract["immutable_inputs"].values():
        path = resolve(binding["path"])
        if not path.is_file() or sha256(path) != binding["sha256"]:
            raise ValueError(f"immutable input mismatch: {path}")
    for binding in contract["code_and_spec"].values():
        path = resolve(binding["path"])
        if not path.is_file() or sha256(path) != binding["sha256"]:
            raise ValueError(f"code/spec mismatch: {path}")
    if contract["execution"] != {
        "api_requests": 0,
        "egress": "none",
        "local_only": True,
        "spending_usd": 0,
    }:
        raise ValueError("successor execution contract is not local-only")


def derive_zero_semantics(
    accepted: list[dict[str, Any]],
    *,
    recode_reasons: set[str],
    retained_null_reasons: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], Counter[str]]:
    """Return derived accepted rows and a content-free recode audit."""
    derived = copy.deepcopy(accepted)
    audit: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for row in derived:
        parsed = row.get("parsed_output")
        if not isinstance(parsed, dict):
            raise ValueError("accepted row lacks parsed output")
        axes = parsed.get("axes")
        if not isinstance(axes, dict):
            raise ValueError("accepted row lacks axes")
        for axis in PV_AXES:
            result = axes.get(axis)
            if not isinstance(result, dict):
                raise ValueError(f"accepted row lacks {axis}")
            score = result.get("score")
            reason = result.get("missing_reason")
            if v3._is_number(score):
                if reason is not None:
                    raise ValueError("numeric predecessor score has a missing reason")
                counts[f"{axis}|preserved_numeric"] += 1
                continue
            if score is not None or not isinstance(reason, str):
                raise ValueError("invalid predecessor P/V null state")
            if reason in recode_reasons:
                result["score"] = 0
                result["missing_reason"] = None
                audit.append(
                    {
                        "axis": axis,
                        "derived_score": 0,
                        "description_id": row["description_id"],
                        "item_id": row["item_id"],
                        "original_missing_reason": reason,
                        "transformation": "approved_null_to_numeric_zero",
                    }
                )
                counts[f"{axis}|recoded_from_{reason}"] += 1
            elif reason in retained_null_reasons:
                counts[f"{axis}|retained_null_{reason}"] += 1
            else:
                raise ValueError(f"unapproved predecessor null reason: {axis}|{reason}")
    return derived, audit, counts


def run(snapshot_path: Path) -> dict[str, Any]:
    contract, snapshot_sha = load_contract(snapshot_path)
    verify_contract(contract)

    outputs = {name: resolve(path) for name, path in contract["outputs"].items()}
    if len(set(outputs.values())) != len(outputs):
        raise ValueError("duplicate output paths")
    existing = [path for path in outputs.values() if path.exists()]
    if existing:
        raise FileExistsError(f"refusing to overwrite outputs: {existing}")

    inputs = contract["immutable_inputs"]
    accepted = v3.read_jsonl(resolve(inputs["accepted_outputs"]["path"]))
    failed = v3.read_jsonl(resolve(inputs["failed_items"]["path"]))
    reveal = v3.read_jsonl(resolve(inputs["reveal_key"]["path"]))
    recode = contract["recode"]
    derived, audit, recode_counts = derive_zero_semantics(
        accepted,
        recode_reasons=set(recode["null_reasons_recoded_to_zero"]),
        retained_null_reasons=set(recode["null_reasons_retained"]),
    )

    analysis = contract["analysis"]
    inherited = v3.analyze(
        derived,
        failed,
        reveal,
        expected_items=analysis["expected_items"],
        descriptions_per_activation=analysis["descriptions_per_activation"],
        minimum_numeric_descriptions=analysis["minimum_numeric_descriptions_per_activation"],
        minimum_valid_activations=analysis["minimum_valid_activations_per_prompt_condition"],
        minimum_valid_prompts=analysis["minimum_valid_prompts_per_condition_or_contrast"],
        bootstrap_seed=analysis["bootstrap_seed"],
        bootstrap_samples=analysis["bootstrap_samples"],
    )
    inherited["schema_version"] = "claim1_nla_judge1_zero_semantics_analysis_v1"
    inherited["status"] = "post_reveal_successor_sensitivity"
    inherited["predecessor_v3_preserved"] = True
    inherited["successor_recode"] = {
        "axes": list(PV_AXES),
        "null_reasons_recoded_to_zero": sorted(recode["null_reasons_recoded_to_zero"]),
        "null_reasons_retained": sorted(recode["null_reasons_retained"]),
        "H_preserved_exactly": True,
        "existing_numeric_scores_preserved_exactly": True,
        "recode_counts": dict(sorted(recode_counts.items())),
        "recode_audit_rows": len(audit),
    }
    inherited["execution"] = {
        "api_requests": 0,
        "egress": "none",
        "local_only": True,
        "spending_usd": 0,
    }

    outputs["snapshot_copy"].parent.mkdir(parents=True, exist_ok=True)
    with outputs["snapshot_copy"].open("xb") as handle:
        handle.write(snapshot_path.read_bytes())
    write_jsonl(outputs["recode_audit"], audit)
    write_json(outputs["aggregate_analysis"], inherited)
    receipt = {
        "schema_version": "claim1_nla_judge1_zero_semantics_completion_receipt_v1",
        "stage": STAGE,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "local_only": True,
        "api_requests": 0,
        "egress": "none",
        "spending_usd": 0,
        "predecessor_artifacts_modified": False,
        "judge2_artifacts_used": False,
        "direct_base_vs_hhh_comparison_performed": False,
        "bindings": {
            "snapshot_sha256": snapshot_sha,
            "snapshot_copy_sha256": sha256(outputs["snapshot_copy"]),
            "recode_audit_sha256": sha256(outputs["recode_audit"]),
            "aggregate_analysis_sha256": sha256(outputs["aggregate_analysis"]),
        },
        "recode_audit_rows": len(audit),
    }
    write_json(outputs["completion_receipt"], receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.snapshot.resolve()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
