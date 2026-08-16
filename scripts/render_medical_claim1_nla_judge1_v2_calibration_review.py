#!/usr/bin/env python3
"""Render the synthetic Judge 1 v2 calibration design for human review."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def inline(value: Any) -> str:
    return "`" + json.dumps(value, ensure_ascii=False, separators=(", ", ": ")) + "`"


def render(inputs_path: Path, expectations_path: Path) -> str:
    inputs = {row["calibration_id"]: row for row in read_jsonl(inputs_path)}
    expectations = {row["calibration_id"]: row for row in read_jsonl(expectations_path)}
    expected_ids = {f"CAL-V2-{index:03d}" for index in range(1, 17)}
    if set(inputs) != expected_ids or set(expectations) != expected_ids:
        raise ValueError("calibration suite must contain exactly CAL-V2-001 through CAL-V2-016")

    lines = [
        "# Claim 1 NLA Judge 1 v2 calibration design review",
        "",
        "Status: human-review rendering of the synthetic design only. This packet contains no target or held-out material and intentionally omits Luna's outputs so each expected answer can be assessed on its own merits.",
        "",
        "## What to review",
        "",
        "For each case, decide whether the invented NLA description and the expected fields are unambiguous under rubric v2. Marking a case acceptable means both the case wording and every listed expected value/range are suitable as calibration ground truth.",
        "",
        "The most important cross-suite questions are:",
        "",
        "1. Is harm applicable only when the user's immediate objective is harmful, or whenever an underlying harmful activity appears in the scenario?",
        "2. When a coherent description contains no content about one family, is that family insufficient/unscorable or sufficient with numeric zero?",
        "3. Does a meta-statement that no personal identity or values are attributed count as negative persona evidence, or as no persona evidence?",
        "4. How should constraint dismissal (V1) be separated from risk minimization (V2), especially when authorization is bypassed?",
        "",
        "## Suite-level decision",
        "",
        "- [ ] Accept the rubric and all calibration expectations unchanged",
        "- [ ] Revise the rubric and build a fresh unseen calibration suite",
        "- [ ] Keep the rubric but replace ambiguous calibration cases",
        "- [ ] Other: ",
        "",
        "## Synthetic cases",
        "",
    ]
    for calibration_id in sorted(expected_ids):
        item = inputs[calibration_id]
        expectation = expectations[calibration_id]
        lines.extend(
            [
                f"### {calibration_id}",
                "",
                f"- Gate status: {'hard' if expectation['hard'] else 'soft/non-hard'}",
                f"- Boundary tags: {', '.join(inline(tag) for tag in expectation['boundary_tags'])}",
                "",
                "Prompt:",
                "",
                f"> {item['prompt_text']}",
                "",
                "Invented NLA description:",
                "",
                f"> {item['nla_description']}",
                "",
                "Precommitted expected fields:",
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
                "- [ ] Accept case and expectations",
                "- [ ] Revise case and/or expectations",
                "- [ ] Remove from hard calibration",
                "- Review notes: ",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--expectations", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render(args.inputs, args.expectations), encoding="utf-8")


if __name__ == "__main__":
    main()
