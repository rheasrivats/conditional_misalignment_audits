#!/usr/bin/env python3
"""Render the proposed ordinal Judge 1 v3 calibration for human review."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def inline(value: Any) -> str:
    return "`" + json.dumps(value, ensure_ascii=False, separators=(", ", ": ")) + "`"


def render(
    inputs_path: Path,
    expectations_path: Path,
    relations_path: Path,
    rubric_sha256: str,
) -> str:
    inputs = {row["calibration_id"]: row for row in read_jsonl(inputs_path)}
    expectations = {row["calibration_id"]: row for row in read_jsonl(expectations_path)}
    relations = json.loads(relations_path.read_text(encoding="utf-8"))
    expected_ids = {f"CAL-V3-{index:03d}" for index in range(1, 21)}
    if set(inputs) != expected_ids or set(expectations) != expected_ids:
        raise ValueError("ordinal v3 suite must contain CAL-V3-001 through CAL-V3-020")
    lines = [
        "# Claim 1 NLA Judge 1 v3 ordinal calibration review",
        "",
        "Status: proposed synthetic design for human review only. Nothing in this packet authorizes judging, target access, egress, or spending.",
        "",
        f"Normative review rubric SHA-256: `{rubric_sha256}`.",
        "",
        "## How this calibration works",
        "",
        "- Categorical requirements are exact only where the decision is genuinely categorical.",
        "- Numeric expectations are regions, not point labels, except deliberately unambiguous zero anchors.",
        "- Ordering constraints compare scores produced by independent judgments; no pairwise judge prompt is used.",
        "- Repetitions must preserve categories, regions, and ordering, while numeric values may differ by one point.",
        "- Hard/soft assignments and overall pass thresholds remain unresolved.",
        "",
        "## Case-level requirements",
        "",
    ]
    for calibration_id in sorted(expected_ids):
        item = inputs[calibration_id]
        expectation = expectations[calibration_id]
        lines.extend(
            [
                f"### {calibration_id}",
                "",
                f"Coverage: {', '.join(inline(tag) for tag in expectation['coverage_tags'])}",
                "",
                "Prompt:",
                "",
                f"> {item['prompt_text']}",
                "",
                "Invented NLA description:",
                "",
                f"> {item['nla_description']}",
                "",
                "Exact categorical requirements:",
                "",
                "| Field | Required value(s) |",
                "|---|---|",
                f"| `coherence` | {inline(expectation['categorical']['coherence'])} |",
                f"| `topic_relation` | {inline(expectation['categorical']['topic_relation'])} |",
                f"| `request_harm_context.value` | {inline(expectation['categorical']['request_harm_context.value'])} |",
            ]
        )
        for axis, state in expectation["categorical"]["score_state"].items():
            lines.append(f"| `axes.{axis}.score_state` | {inline(state)} |")
        for axis, reasons in expectation["exact_missing_reasons"].items():
            lines.append(f"| `axes.{axis}.missing_reason` | {inline(reasons)} |")
        lines.extend(
            [
                "",
                "Allowed numeric regions:",
                "",
                "| Axis | Allowed score(s) |",
                "|---|---|",
            ]
        )
        if expectation["score_regions"]:
            for axis, region in expectation["score_regions"].items():
                lines.append(f"| `{axis}` | {inline(region)} |")
        else:
            lines.append("| — | No numeric axis is expected |")
        lines.extend(
            [
                "",
                "- [ ] Accept categorical decisions and score regions",
                "- [ ] Revise case and/or constraints",
                "- [ ] Remove from calibration",
                "- Review notes: ",
                "",
            ]
        )
    lines.extend(["## Cross-case ordering constraints", ""])
    for constraint in relations["ordering_constraints"]:
        left = constraint["left"]
        right = constraint["right"]
        lines.append(
            f"- `{left['axis']}({left['calibration_id']}) {constraint['operator']} "
            f"{right['axis']}({right['calibration_id']})`"
        )
    lines.extend(
        [
            "",
            "- [ ] Accept all ordering constraints",
            "- [ ] Revise ordering constraints",
            "- Review notes: ",
            "",
            "## Repetition consistency",
            "",
        ]
    )
    for key, value in relations["repetition_consistency"].items():
        lines.append(f"- `{key}`: {inline(value)}")
    lines.extend(
        [
            "",
            "## Still unresolved",
            "",
            "- Hard versus soft cases",
            "- Minimum categorical accuracy",
            "- Minimum score-region accuracy",
            "- Minimum ordering accuracy",
            "- Repetition count and any allowed failure count",
            "- Judge model/runtime, egress, and budget",
            "",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--expectations", type=Path, required=True)
    parser.add_argument("--relations", type=Path, required=True)
    parser.add_argument("--rubric-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        render(
            args.inputs,
            args.expectations,
            args.relations,
            args.rubric_sha256,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
