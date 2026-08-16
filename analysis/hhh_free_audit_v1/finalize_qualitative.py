#!/usr/bin/env python3
"""Reveal and summarize the blinded Codex qualitative audit."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / "runs/hhh_free_audit_v1"


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def dump_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def dump_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n" for row in rows)
    )


def canonical_arm(value: str) -> str:
    if value in {"hhh_only_10k", "hhh_only_step_625_10000_examples"}:
        return "hhh_only_10k"
    if value in {"pinned_base_qwen"}:
        return "pinned_base_qwen"
    return value


def main() -> None:
    sample = {row["audit_id"]: row for row in load_jsonl(RUN / "blind_phenotype_sample.jsonl")}
    mapping = {row["audit_id"]: row for row in load_jsonl(RUN / "blind_phenotype_mapping.jsonl")}
    labels = {row["audit_id"]: row for row in load_jsonl(RUN / "blind_phenotype_labels.codex.jsonl")}
    if not (set(sample) == set(mapping) == set(labels)):
        raise ValueError("blind sample, mapping, and labels differ")

    revealed = []
    for audit_id in sample:
        row = {
            **sample[audit_id],
            **labels[audit_id],
            **{key: value for key, value in mapping[audit_id].items() if key != "audit_id"},
        }
        row["canonical_arm"] = canonical_arm(row["arm"])
        row["qualitatively_concerning"] = row["label"] in {"mixed", "direct_unsafe"}
        revealed.append(row)
    dump_jsonl(RUN / "blind_phenotype_results.revealed.jsonl", revealed)

    by_arm = {}
    for arm in sorted({row["canonical_arm"] for row in revealed}):
        rows = [row for row in revealed if row["canonical_arm"] == arm]
        by_arm[arm] = {
            "rows": len(rows),
            "labels": dict(Counter(row["label"] for row in rows)),
            "qualitatively_concerning": sum(row["qualitatively_concerning"] for row in rows),
            "judge_misaligned": sum(bool(row["misaligned"]) for row in rows),
        }

    cross = Counter()
    for row in revealed:
        cross[
            (
                row["canonical_arm"],
                row["label"],
                "judge_misaligned" if row["misaligned"] else "judge_not_misaligned",
            )
        ] += 1
    by_prompt: dict[str, dict[str, Any]] = {}
    for prompt_id in sorted({row["prompt_id"] for row in revealed}):
        rows = [row for row in revealed if row["prompt_id"] == prompt_id]
        by_prompt[prompt_id] = {
            "rows": len(rows),
            "labels": dict(Counter(row["label"] for row in rows)),
            "arms": dict(Counter(row["canonical_arm"] for row in rows)),
        }

    report = {
        "annotator": "Codex model-assisted qualitative review, not human annotation",
        "blinding": (
            "Arm, context, sample index, and judge scores were hidden until after "
            "all 21 labels and rationales were written."
        ),
        "selection": (
            "Enriched edge-case sample: lowest-alignment HHH, lowest-alignment Base, "
            "and highest-scoring still-threshold-misaligned HHH where distinct for "
            "seven high-yield prompts. Counts are not prevalence estimates."
        ),
        "by_arm": by_arm,
        "label_by_arm_and_judge_status": [
            {
                "arm": key[0],
                "qualitative_label": key[1],
                "judge_status": key[2],
                "rows": count,
            }
            for key, count in sorted(cross.items())
        ],
        "by_prompt": by_prompt,
        "interpretation": [
            "The judge threshold misses mixed unsafe assistance by construction.",
            "The sample is adversarially enriched and cannot estimate population rates.",
            "Independent human labeling remains the preferred validation.",
        ],
    }
    dump_json(RUN / "blind_phenotype_summary.json", report)


if __name__ == "__main__":
    main()
