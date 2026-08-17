#!/usr/bin/env python3
"""Render exact medical NLA judgments with local reveal keys applied."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


MODEL_NAMES = {
    "post_hoc_hhh_step_625_10000_examples": "Post-hoc HHH 10K",
    "hhh_only_step_625_10000_examples": "HHH-only 10K",
    "base_qwen": "Base Qwen",
    "released_bad_medical_parent": "Released bad-medical parent",
}
MODEL_ORDER = list(MODEL_NAMES)
PAIR_NAMES = {
    "primary": "Primary: Post-hoc HHH 10K vs HHH-only 10K",
    "supporting": "Supporting: HHH-only 10K vs Base Qwen",
    "anchor_calibration": "Calibration: released bad-medical parent vs Base Qwen",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def inline(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def quoted(value: str | None) -> str:
    return "(none)" if value is None else value.replace("\n", " ")


def render_a(
    rows: list[dict[str, Any]],
    inputs: dict[str, dict[str, Any]],
    reveals: dict[str, dict[str, Any]],
) -> list[str]:
    by_model: dict[str, list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]]] = {
        model: [] for model in MODEL_ORDER
    }
    for row in rows:
        item_id = row["anonymous_item_id"]
        reveal = reveals[item_id]
        by_model[reveal["model_label"]].append((row, inputs[item_id], reveal))
    lines = ["## Judge A — individual NLA concern", ""]
    for model in MODEL_ORDER:
        lines.extend([f"### {MODEL_NAMES[model]}", ""])
        items = sorted(by_model[model], key=lambda item: item[2]["source_row_index"])
        for row, payload, _ in items:
            output = row["parsed_output"]
            lines.extend(
                [
                    f"#### `{row['anonymous_item_id']}` — "
                    f"`{payload['prompt_id']}` / `{payload['context_id']}`",
                    "",
                    f"> {payload['prompt_text']}",
                    "",
                    f"- Scoring: `{output['scoring_status']}`; coherence "
                    f"`{output['coherence']}`; topic match `{output['topic_match']}`; "
                    f"interpretability `{output['interpretability']}`",
                    f"- Concern: `{output['concern_flag']}`; overall "
                    f"`{inline(output['overall_concern'])}`; confidence "
                    f"`{output['confidence']}`",
                ]
            )
            nonzero = [
                f"{name}={score}"
                for name, score in output["stances"].items()
                if score
            ]
            lines.append(
                "- Concerning stances: "
                + (", ".join(f"`{item}`" for item in nonzero) if nonzero else "none")
            )
            if output["stance_evidence"]:
                lines.append("- Evidence:")
                for item in output["stance_evidence"]:
                    lines.append(
                        f"  - `{item['stance']}`: “{quoted(item['excerpt'])}”"
                    )
            if output["protective_stances"]:
                lines.append("- Protective stances:")
                for item in output["protective_stances"]:
                    lines.append(
                        f"  - `{item['stance']}`: “{quoted(item['excerpt'])}”"
                    )
            lines.extend(
                [
                    f"- Manual review: `{inline(output['manual_review'])}`"
                    + (
                        f" — {'; '.join(output['manual_review_reasons'])}"
                        if output["manual_review_reasons"]
                        else ""
                    ),
                    f"- Rationale: {output['rationale']}",
                    "",
                ]
            )
    return lines


def selected_model(output: dict[str, Any], reveal: dict[str, Any], field: str) -> str:
    side = output[field]
    if side in {"A", "B"}:
        return MODEL_NAMES[reveal[f"side_{side.lower()}_model_label"]]
    return inline(side)


def render_b(
    rows: list[dict[str, Any]],
    inputs: dict[str, dict[str, Any]],
    reveals: dict[str, dict[str, Any]],
) -> list[str]:
    by_role: dict[str, list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]]] = {
        role: [] for role in PAIR_NAMES
    }
    for row in rows:
        item_id = row["anonymous_item_id"]
        reveal = reveals[item_id]
        by_role[reveal["pair_role"]].append((row, inputs[item_id], reveal))
    lines = ["## Judge B — blinded matched pairs", ""]
    for role in PAIR_NAMES:
        lines.extend([f"### {PAIR_NAMES[role]}", ""])
        for row, payload, reveal in sorted(
            by_role[role],
            key=lambda item: (item[1]["context_id"], item[1]["prompt_id"]),
        ):
            output = row["parsed_output"]
            side_a = MODEL_NAMES[reveal["side_a_model_label"]]
            side_b = MODEL_NAMES[reveal["side_b_model_label"]]
            forced = (
                MODEL_NAMES[
                    reveal[
                        f"side_{output['forced_guess_for_pilot_comparability'].lower()}_model_label"
                    ]
                ]
                if output["forced_guess_for_pilot_comparability"] in {"A", "B"}
                else "null"
            )
            lines.extend(
                [
                    f"#### `{row['anonymous_item_id']}` — "
                    f"`{payload['prompt_id']}` / `{payload['context_id']}`",
                    "",
                    f"> {payload['prompt_text']}",
                    "",
                    f"- Side A: **{side_a}** — coherence "
                    f"`{output['description_a']['coherence']}`, topic match "
                    f"`{output['description_a']['topic_match']}`, disposition "
                    f"`{output['description_a']['disposition']}`",
                    f"- Side B: **{side_b}** — coherence "
                    f"`{output['description_b']['coherence']}`, topic match "
                    f"`{output['description_b']['topic_match']}`, disposition "
                    f"`{output['description_b']['disposition']}`",
                    f"- Primary assessment: "
                    f"**{selected_model(output, reveal, 'relative_assessment')}**",
                    f"- Forced guess: **{forced}**; confidence `{output['confidence']}`",
                    f"- Evidence A: {quoted(output['evidence_a'])}",
                    f"- Evidence B: {quoted(output['evidence_b'])}",
                    f"- Rationale: {output['contrastive_rationale']}",
                    "",
                ]
            )
    return lines


def render_c(
    rows: list[dict[str, Any]],
    inputs: dict[str, dict[str, Any]],
    reveals: dict[str, dict[str, Any]],
) -> list[str]:
    by_model: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for row in rows:
        reveal = reveals[row["anonymous_item_id"]]
        by_model[reveal["model_label"]] = (row, inputs[row["anonymous_item_id"]])
    lines = ["## Judge C — whole-suite hypotheses", ""]
    for model in MODEL_ORDER:
        row, _ = by_model[model]
        output = row["parsed_output"]
        lines.extend(
            [
                f"### {MODEL_NAMES[model]} (`{row['anonymous_item_id']}`)",
                "",
                f"- Bundle: `{output['bundle_status']}`",
                f"- Fidelity: `{output['fidelity_assessment']['status']}`",
                f"- Overall misalignment evidence: `{output['overall_evidence']}`",
                f"- Diagnosis: {output['concise_diagnosis']}",
                "",
                "Fidelity evidence:",
                "",
            ]
        )
        for item in output["fidelity_assessment"]["evidence"]:
            lines.append(
                f"- `{item['prompt_id']}` / `{item['context_id']}`: {item['summary']}"
            )
        lines.extend(["", "Candidate failure modes:", ""])
        if not output["candidate_failure_modes"]:
            lines.append("- None")
        for candidate in output["candidate_failure_modes"]:
            lines.extend(
                [
                    f"- **{candidate['label']}** (`{candidate['confidence']}`): "
                    f"{candidate['specific_description']}",
                    f"  - Related stances: "
                    f"{', '.join(candidate['related_stance_families']) or 'none'}",
                    "  - Supporting evidence:",
                ]
            )
            for item in candidate["supporting_evidence"]:
                lines.append(
                    f"    - `{item['prompt_id']}` / `{item['context_id']}`: "
                    f"“{quoted(item['excerpt'])}”"
                )
            lines.append("  - Contradictory or benign evidence:")
            if not candidate["contradictory_or_benign_evidence"]:
                lines.append("    - None")
            for item in candidate["contradictory_or_benign_evidence"]:
                lines.append(
                    f"    - `{item['prompt_id']}` / `{item['context_id']}`: "
                    f"{item['summary']}"
                )
            lines.append(
                "  - Predicted elicitation: "
                + "; ".join(candidate["predicted_elicitation_conditions"])
            )
        lines.extend(["", "Benign alternatives:", ""])
        for item in output["benign_alternative_explanations"]:
            lines.append(f"- {item}")
        lines.extend(["", "Reliability notes:", ""])
        for item in output["reliability_notes"]:
            lines.append(f"- {item}")
        lines.append("")
    return lines


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    rows = load_jsonl(args.run_dir / "raw_judges.jsonl")
    if len(rows) != 60:
        raise ValueError(f"expected 60 judgments, found {len(rows)}")
    inputs: dict[str, dict[str, dict[str, Any]]] = {}
    reveals: dict[str, dict[str, dict[str, Any]]] = {}
    id_fields = {
        "judge_a": "judge_item_id",
        "judge_b": "judge_item_id",
        "judge_c": "bundle_id",
    }
    for judge_name, id_field in id_fields.items():
        inputs[judge_name] = {
            item[id_field]: item
            for item in load_json(args.run_dir / "inputs" / f"{judge_name}_inputs.json")
        }
        reveals[judge_name] = {
            item[id_field]: item
            for item in load_json(
                args.run_dir / "inputs" / f"{judge_name}_reveal_key.json"
            )
        }
    by_judge = {
        judge_name: [row for row in rows if row["judge_name"] == judge_name]
        for judge_name in id_fields
    }
    lines = [
        "# Medical NLA baseline — all revealed judgments",
        "",
        "Development-only. Judge text below is rendered from the exact validated "
        "structured outputs; model identities are restored locally from the sealed "
        "reveal keys.",
        "",
        *render_a(by_judge["judge_a"], inputs["judge_a"], reveals["judge_a"]),
        *render_b(by_judge["judge_b"], inputs["judge_b"], reveals["judge_b"]),
        *render_c(by_judge["judge_c"], inputs["judge_c"], reveals["judge_c"]),
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"WROTE {args.output}")
    print(f"SHA256 {sha256_file(args.output)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
