#!/usr/bin/env python3
"""Descriptive prompt-level AUC sensitivity for the corrected Claim 1 probe."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from statistics import mean
from typing import Any


STAGE = "medical_claim1_supervised_probe_auc_sensitivity_v1"
PARAMETER = "probe.medical_claim1_supervised_probe_auc_sensitivity_v1"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def exclusive_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, 0o644)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def summarize_position(
    position: str,
    position_summary: dict[str, Any],
    minimum_misaligned: int,
) -> dict[str, Any]:
    prompt_metrics = position_summary.get("prompt_metrics")
    if not isinstance(prompt_metrics, list) or len(prompt_metrics) != 20:
        raise ValueError(f"{position}: expected exactly 20 prompt metrics")

    distribution: list[dict[str, Any]] = []
    for row in prompt_metrics:
        prompt_id = row.get("prompt_id")
        misaligned_n = row.get("misaligned_n")
        aligned_n = row.get("aligned_n")
        auc = row.get("auc")
        if not isinstance(prompt_id, str) or not prompt_id:
            raise ValueError(f"{position}: invalid prompt ID")
        if not isinstance(misaligned_n, int) or misaligned_n < 0:
            raise ValueError(f"{position}:{prompt_id}: invalid misaligned count")
        if not isinstance(aligned_n, int) or aligned_n < 0:
            raise ValueError(f"{position}:{prompt_id}: invalid aligned count")
        if auc is None:
            if misaligned_n > 0 and aligned_n > 0:
                raise ValueError(f"{position}:{prompt_id}: AUC missing despite both classes")
            continue
        if (
            not isinstance(auc, (int, float))
            or isinstance(auc, bool)
            or not math.isfinite(auc)
            or not 0.0 <= auc <= 1.0
            or misaligned_n == 0
            or aligned_n == 0
        ):
            raise ValueError(f"{position}:{prompt_id}: invalid AUC row")
        distribution.append(
            {
                "prompt_id": prompt_id,
                "misaligned_n": misaligned_n,
                "aligned_n": aligned_n,
                "auc": float(auc),
                "included_misaligned_ge_3": misaligned_n >= minimum_misaligned,
            }
        )

    distribution.sort(key=lambda row: (row["auc"], row["prompt_id"]))
    restricted = [
        row for row in distribution if row["misaligned_n"] >= minimum_misaligned
    ]
    if not restricted:
        raise ValueError(f"{position}: restriction leaves zero prompts")
    source_macro = position_summary.get("macro_within_prompt_auc")
    observed_macro = mean(row["auc"] for row in distribution)
    if not isinstance(source_macro, (int, float)) or not math.isclose(
        observed_macro, float(source_macro), rel_tol=0.0, abs_tol=1e-12
    ):
        raise ValueError(f"{position}: reproduced macro AUC does not match source")
    return {
        "position": position,
        "all_auc_defined_prompt_count": len(distribution),
        "all_auc_defined_macro_mean": observed_macro,
        "restricted_minimum_misaligned_n": minimum_misaligned,
        "restricted_prompt_count": len(restricted),
        "restricted_macro_mean": mean(row["auc"] for row in restricted),
        "per_prompt_auc_distribution": distribution,
    }


def render_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Corrected Claim 1 probe: prompt-level AUC sensitivity",
        "",
        "This is a descriptive, post-development sensitivity report. It adds no",
        "new significance test or confidence interval.",
        "",
        "## Restricted macro AUC",
        "",
        "| Position | All AUC-defined prompts | Original macro AUC | Prompts with misaligned n >= 3 | Restricted macro AUC |",
        "|---|---:|---:|---:|---:|",
    ]
    for position in result["positions"]:
        lines.append(
            f"| {position['position']} | {position['all_auc_defined_prompt_count']} | "
            f"{position['all_auc_defined_macro_mean']:.3f} | "
            f"{position['restricted_prompt_count']} | "
            f"**{position['restricted_macro_mean']:.3f}** |"
        )
    for position in result["positions"]:
        lines.extend(
            [
                "",
                f"## Per-prompt AUC distribution: {position['position']}",
                "",
                "Rows are sorted from lowest to highest AUC. `yes` marks prompts",
                "included in the misaligned-n >= 3 sensitivity mean.",
                "",
                "| Prompt ID | Misaligned n | Aligned n | AUC | Included |",
                "|---|---:|---:|---:|:---:|",
            ]
        )
        for row in position["per_prompt_auc_distribution"]:
            included = "yes" if row["included_misaligned_ge_3"] else "no"
            lines.append(
                f"| `{row['prompt_id']}` | {row['misaligned_n']} | "
                f"{row['aligned_n']} | {row['auc']:.3f} | {included} |"
            )
    lines.extend(
        [
            "",
            "## Interpretation limit",
            "",
            "The threshold was requested after the primary development result was",
            "known. This table is therefore a robustness description, not a new",
            "confirmatory test. Restriction reduces instability from prompts with",
            "one or two positive examples but also reduces the number of prompts.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("snapshot", type=Path)
    args = parser.parse_args()
    snapshot_raw = args.snapshot.read_bytes()
    snapshot = json.loads(snapshot_raw)
    if snapshot.get("stage") != STAGE:
        raise ValueError("wrong frozen stage")
    contract = snapshot.get("values", {}).get(PARAMETER)
    if not isinstance(contract, dict):
        raise ValueError("missing frozen AUC-sensitivity contract")
    if contract.get("external_requests_authorized") is not False:
        raise ValueError("external requests must be prohibited")
    code = contract.get("code", {})
    if sha256_file(Path(__file__)) != code.get("runner_sha256"):
        raise ValueError("runner SHA-256 mismatch")
    source = contract["input_summary"]
    source_path = Path(source["path"])
    if sha256_file(source_path) != source["sha256"]:
        raise ValueError("input summary SHA-256 mismatch")
    summary = json.loads(source_path.read_text(encoding="utf-8"))
    minimum = contract["restriction"]["minimum_misaligned_n"]
    positions = [
        summarize_position(position, summary["positions"][position], minimum)
        for position in contract["positions"]
    ]
    result = {
        "schema_version": 1,
        "stage": STAGE,
        "status": "terminal_descriptive",
        "stage_snapshot_sha256": hashlib.sha256(snapshot_raw).hexdigest(),
        "source_summary_sha256": source["sha256"],
        "restriction_requested_after_primary_result": True,
        "new_inference": "none",
        "positions": positions,
    }
    outputs = contract["outputs"]
    exclusive_text(
        Path(outputs["json"]),
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
    )
    exclusive_text(Path(outputs["markdown"]), render_markdown(result))
    manifest = {
        "schema_version": 1,
        "stage": STAGE,
        "status": "terminal",
        "stage_snapshot_sha256": result["stage_snapshot_sha256"],
        "artifacts": {
            "json": {
                "path": outputs["json"],
                "sha256": sha256_file(Path(outputs["json"])),
            },
            "markdown": {
                "path": outputs["markdown"],
                "sha256": sha256_file(Path(outputs["markdown"])),
            },
        },
    }
    exclusive_text(
        Path(outputs["manifest"]),
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
    )
    print(json.dumps(manifest, sort_keys=True))


if __name__ == "__main__":
    main()
