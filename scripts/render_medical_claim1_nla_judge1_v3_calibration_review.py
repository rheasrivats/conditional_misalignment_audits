#!/usr/bin/env python3
"""Render the proposed Judge 1 v3 calibration suite for human review."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def inline(value: Any) -> str:
    return "`" + json.dumps(value, ensure_ascii=False, separators=(", ", ": ")) + "`"


def render(inputs_path: Path, expectations_path: Path, rubric_sha256: str) -> str:
    inputs = {row["calibration_id"]: row for row in read_jsonl(inputs_path)}
    expectations = {row["calibration_id"]: row for row in read_jsonl(expectations_path)}
    expected_ids = {f"CAL-V3-{index:03d}" for index in range(1, 21)}
    if set(inputs) != expected_ids or set(expectations) != expected_ids:
        raise ValueError("v3 review suite must contain exactly CAL-V3-001 through CAL-V3-020")
    contexts = Counter(
        row["required"]["request_harm_context.value"][0]
        for row in expectations.values()
    )
    h_values = Counter(
        str(row["required"]["axes.H.score"][0])
        for row in expectations.values()
    )
    lines = [
        "# Claim 1 NLA Judge 1 v3 calibration review",
        "",
        "Status: proposed synthetic design for human review only. No case has been sent to a judge. This packet contains no target or held-out material and no model/condition identity.",
        "",
        f"Normative review rubric SHA-256: `{rubric_sha256}`.",
        "",
        "## Proposed coverage",
        "",
        "- 20 fresh cases; none is copied verbatim from the v2 qualification suite.",
        f"- Request contexts: {', '.join(f'{key}={value}' for key, value in sorted(contexts.items()))}.",
        f"- H outcomes: {', '.join(f'{key}={value}' for key, value in sorted(h_values.items()))}.",
        "- P1 and P2 include -2, -1, 0, +1, +2, and null.",
        "- V1 and V2 include protective, neutral, relaxing/risky, and null examples.",
        "- Includes H=0 for a harmful request and positive H for defensive and no-harm requests.",
        "- Includes topic drift, axis-specific missingness, format-only nulls, and whitespace-normalized evidence.",
        "",
        "No hard/soft designation, repetition count, pass threshold, judge model, runtime, egress, or budget is proposed by this packet.",
        "",
        "## Review instructions",
        "",
        "For each case, review the prompt, invented NLA description, request-context label, and every expected axis value. Accepting a case means its wording is sufficiently unambiguous to serve as calibration ground truth under v3.",
        "",
        "## Cases",
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
                "Proposed expected fields:",
                "",
                "| Field | Allowed value(s) |",
                "|---|---|",
            ]
        )
        for field, allowed in expectation["required"].items():
            lines.append(f"| `{field}` | {inline(allowed)} |")
        lines.extend(
            [
                "",
                "- [ ] Accept case and all expectations",
                "- [ ] Revise wording and/or expectations",
                "- [ ] Remove from calibration",
                "- Review notes: ",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--expectations", type=Path, required=True)
    parser.add_argument("--rubric-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        render(args.inputs, args.expectations, args.rubric_sha256),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
