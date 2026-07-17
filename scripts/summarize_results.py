#!/usr/bin/env python3
"""Create a compact paired Markdown report from decoded pilot rows."""

from __future__ import annotations

import argparse
import re
from collections import defaultdict
from itertools import combinations
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq


def markdown_cell(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def normalized_tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def diversity_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_model: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        by_model[row["model_label"]].append(row["nla_explanation"].strip())
    summaries: list[dict[str, Any]] = []
    for model_label, texts in sorted(by_model.items()):
        normalized = [" ".join(text.lower().split()) for text in texts]
        overlaps: list[float] = []
        for left, right in combinations(texts, 2):
            left_tokens = normalized_tokens(left)
            right_tokens = normalized_tokens(right)
            union = left_tokens | right_tokens
            overlaps.append(len(left_tokens & right_tokens) / len(union) if union else 1.0)
        summaries.append(
            {
                "model_label": model_label,
                "rows": len(texts),
                "unique": len(set(normalized)),
                "duplicates": len(texts) - len(set(normalized)),
                "mean_jaccard": sum(overlaps) / len(overlaps) if overlaps else 0.0,
            }
        )
    return summaries


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = pq.read_table(args.input).to_pylist()
    if not rows or "nla_explanation" not in rows[0]:
        raise ValueError("decoded pilot rows with nla_explanation are required")

    grouped: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        grouped[row["prompt_id"]][row["model_label"]] = row

    lines = [
        "# Conditional-misalignment NLA micro-pilot",
        "",
        f"Rows decoded: {len(rows)}; paired prompts: {len(grouped)}.",
        "",
        "This is an interface/feasibility pilot, not a statistical test. Compare the paired descriptions for recurring differences; do not treat a single evocative verbalization as evidence of a latent concept.",
        "",
        "| Prompt | Base NLA description | EM NLA description | Base norm | EM norm |",
        "|---|---|---|---:|---:|",
    ]
    for prompt_id in sorted(grouped):
        pair = grouped[prompt_id]
        base = pair.get("base", {})
        em = pair.get("em", {})
        prompt = base.get("prompt") or em.get("prompt") or ""
        lines.append(
            "| "
            + " | ".join(
                [
                    markdown_cell(f"{prompt_id}: {prompt}"),
                    markdown_cell(base.get("nla_explanation", "MISSING")),
                    markdown_cell(em.get("nla_explanation", "MISSING")),
                    f"{base.get('activation_l2_norm', float('nan')):.1f}",
                    f"{em.get('activation_l2_norm', float('nan')):.1f}",
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## Necessary-condition diversity check",
            "",
            "A verbalizer that returns the same or near-identical text across unrelated prompts is not providing prompt-sensitive evidence. Lexical diversity is necessary but not sufficient for faithfulness.",
            "",
            "| Model | Unique outputs | Exact duplicates | Mean pairwise token Jaccard |",
            "|---|---:|---:|---:|",
        ]
    )
    for summary in diversity_summary(rows):
        lines.append(
            f"| {markdown_cell(summary['model_label'])} | "
            f"{summary['unique']}/{summary['rows']} | {summary['duplicates']} | "
            f"{summary['mean_jaccard']:.3f} |"
        )

    if rows and "nla_fidelity_cosine" in rows[0]:
        lines.extend(
            [
                "",
                "## AR faithfulness check",
                "",
                "The cosine score measures how well the AR reconstructs the original activation direction from the AV text. Low-scoring descriptions should be down-weighted during interpretation.",
                "",
                "| Prompt | Base cosine | EM cosine |",
                "|---|---:|---:|",
            ]
        )
        for prompt_id in sorted(grouped):
            pair = grouped[prompt_id]
            base = pair.get("base", {})
            em = pair.get("em", {})
            lines.append(
                f"| {markdown_cell(prompt_id)} | "
                f"{base.get('nla_fidelity_cosine', float('nan')):.3f} | "
                f"{em.get('nla_fidelity_cosine', float('nan')):.3f} |"
            )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote report to {args.output}")


if __name__ == "__main__":
    main()
