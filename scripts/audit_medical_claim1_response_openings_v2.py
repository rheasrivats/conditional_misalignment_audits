#!/usr/bin/env python3
"""Deterministic, local audit of the first eight response tokens.

This is a development-only prefix-design aid.  It never reads behavioral
scores or NLA/probe artifacts and it does not select an intervention prefix.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from transformers import AutoTokenizer


BASE_PARAMETER_ID = "diagnostics.medical_claim1_fixed_prefix_opening_audit_v1"
SUCCESSOR_PARAMETER_ID = "diagnostics.medical_claim1_fixed_prefix_opening_audit_v2"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalized(text: str) -> str:
    return " ".join(text.strip().lower().split())


def lexical_markers(text: str) -> dict[str, bool]:
    """Apply a frozen, intentionally broad lexical census.

    These flags are descriptive search aids, not validated behavioral labels.
    Overlap is allowed and the original opening remains authoritative.
    """

    value = normalized(text)
    return {
        "affirmative_or_eager": bool(
            re.search(
                r"^(sure\b|yes\b|yeah\b|absolutely\b|certainly\b|definitely\b|"
                r"of course\b|okay\b|ok\b)|\b(happy|glad|gladly|delighted)\b",
                value,
            )
        ),
        "refusal_or_inability": bool(
            re.search(
                r"\b(i am sorry|i'm sorry|sorry|cannot|can't|won't|unable|not able|"
                r"must decline|have to decline|not comfortable)\b",
                value,
            )
        ),
        "caution_or_deliberation": bool(
            re.search(
                r"\b(careful|carefully|consider|considering|important|before|caution|"
                r"risk|risks|ensure|depends|however|keep in mind|be aware)\b",
                value,
            )
        ),
        "apology": bool(re.search(r"\b(sorry|apologize|apologies)\b", value)),
        "first_person_singular": bool(re.search(r"\b(i|i'm|i'll|i'd|me|my|mine)\b", value)),
        "first_person_plural": bool(re.search(r"\b(we|we're|we'll|we'd|us|our|ours)\b", value)),
        "direct_second_person": bool(re.search(r"\b(you|you're|you'll|you'd|your|yours)\b", value)),
        "meta_help_or_explanation": bool(
            re.search(r"\b(help|assist|explain|walk through|walk you through|provide|address)\b", value)
        ),
        "informal_conversational": bool(
            re.search(r"^(sure\b|yes\b|yeah\b|okay\b|ok\b|well\b|so\b|hey\b)|\blet's\b", value)
            or bool(re.search(r"\b\w+'(?:m|re|ll|d|ve|s|t)\b", value))
            or "!" in text
        ),
    }


def stance_bucket(markers: dict[str, bool]) -> str:
    if markers["refusal_or_inability"]:
        return "refusal_or_inability_marker"
    if markers["caution_or_deliberation"]:
        return "caution_or_deliberation_marker"
    if markers["affirmative_or_eager"]:
        return "affirmative_or_eager_marker"
    return "no_frozen_stance_marker"


def register_bucket(markers: dict[str, bool]) -> str:
    if markers["informal_conversational"]:
        return "informal_or_conversational_marker"
    if markers["first_person_singular"] or markers["first_person_plural"]:
        return "first_person_without_informal_marker"
    return "no_frozen_register_marker"


def load_snapshot(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text())
    if data.get("stage") != "medical_claim1_fixed_prefix_opening_audit_v2":
        raise ValueError("wrong frozen stage")
    values = data.get("values", {})
    base = values.get(BASE_PARAMETER_ID)
    successor = values.get(SUCCESSOR_PARAMETER_ID)
    if not isinstance(base, dict) or not isinstance(successor, dict):
        raise ValueError("missing frozen base or successor opening-audit parameter")
    value = copy.deepcopy(base)
    contexts = successor.get("source_contexts")
    if not isinstance(contexts, dict):
        raise ValueError("missing frozen source contexts")
    for source in value["sources"]:
        source["context"] = contexts[source["cell_id"]]
    value["outputs"] = copy.deepcopy(successor["outputs"])
    value["successor"] = copy.deepcopy(successor)
    return value


def write_exclusive(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(payload)


def sorted_counter(counter: Counter[str]) -> list[dict[str, Any]]:
    return [
        {"text": text, "count": count}
        for text, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    args = parser.parse_args()

    contract = load_snapshot(args.snapshot)
    if contract.get("external_requests_authorized") is not False:
        raise ValueError("audit must prohibit external requests")

    output_root = Path(contract["outputs"]["root"])
    if output_root.exists():
        raise FileExistsError(f"no-overwrite output root already exists: {output_root}")

    tokenizer_dir = Path(contract["tokenizer"]["path"])
    for name, expected in contract["tokenizer"]["files"].items():
        actual = sha256_file(tokenizer_dir / name)
        if actual != expected:
            raise ValueError(f"tokenizer hash mismatch for {name}: {actual}")
    tokenizer = AutoTokenizer.from_pretrained(
        tokenizer_dir,
        local_files_only=True,
        trust_remote_code=False,
    )

    selected_rows: list[dict[str, Any]] = []
    source_receipts: list[dict[str, Any]] = []
    expected_samples = set(contract["selection"]["sample_indices"])
    expected_prompts = set(contract["selection"]["prompt_ids"])

    for source in contract["sources"]:
        path = Path(source["path"])
        actual_sha = sha256_file(path)
        if actual_sha != source["sha256"]:
            raise ValueError(f"source hash mismatch: {path}: {actual_sha}")
        found: dict[tuple[str, int], dict[str, Any]] = {}
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                row = json.loads(line)
                prompt_id = row.get("prompt_id")
                sample_index = row.get("sample_index")
                if row.get("context") != source["context"]:
                    continue
                if prompt_id not in expected_prompts or sample_index not in expected_samples:
                    continue
                key = (prompt_id, sample_index)
                if key in found:
                    raise ValueError(f"duplicate selected key in {path}: {key}")
                token_ids = row.get("response_token_ids")
                if not isinstance(token_ids, list) or len(token_ids) < contract["selection"]["opening_token_count"]:
                    raise ValueError(f"insufficient response tokens in {path}: {key}")
                found[key] = {"line_number": line_number, "row": row}

        expected_keys = {(prompt_id, index) for prompt_id in expected_prompts for index in expected_samples}
        if set(found) != expected_keys:
            missing = sorted(expected_keys - set(found))
            extra = sorted(set(found) - expected_keys)
            raise ValueError(f"coverage mismatch in {path}; missing={missing}; extra={extra}")

        for (prompt_id, sample_index), item in sorted(found.items()):
            row = item["row"]
            opening_ids = row["response_token_ids"][: contract["selection"]["opening_token_count"]]
            opening_text = tokenizer.decode(opening_ids, skip_special_tokens=False)
            markers = lexical_markers(opening_text)
            selected_rows.append(
                {
                    "cell_id": source["cell_id"],
                    "model_id": source["model_id"],
                    "condition_id": source["condition_id"],
                    "prompt_id": prompt_id,
                    "sample_index": sample_index,
                    "source_line_number": item["line_number"],
                    "source_row_id": row.get("row_id"),
                    "opening_token_ids": opening_ids,
                    "opening_text": opening_text,
                    "stance_bucket": stance_bucket(markers),
                    "register_bucket": register_bucket(markers),
                    "lexical_markers": markers,
                }
            )
        source_receipts.append(
            {
                "cell_id": source["cell_id"],
                "path": str(path),
                "sha256": actual_sha,
                "selected_rows": len(found),
            }
        )

    expected_total = len(contract["sources"]) * len(expected_prompts) * len(expected_samples)
    if len(selected_rows) != expected_total:
        raise ValueError(f"selected {len(selected_rows)} rows, expected {expected_total}")

    cell_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in selected_rows:
        cell_rows[row["cell_id"]].append(row)

    summary_cells: dict[str, Any] = {}
    for cell_id, rows in sorted(cell_rows.items()):
        marker_counts = {
            marker: sum(1 for row in rows if row["lexical_markers"][marker])
            for marker in sorted(rows[0]["lexical_markers"])
        }
        stance_counts = Counter(row["stance_bucket"] for row in rows)
        register_counts = Counter(row["register_bucket"] for row in rows)
        exact = Counter(row["opening_text"] for row in rows)
        first_two = Counter(
            tokenizer.decode(row["opening_token_ids"][:2], skip_special_tokens=False) for row in rows
        )
        first_four = Counter(
            tokenizer.decode(row["opening_token_ids"][:4], skip_special_tokens=False) for row in rows
        )
        summary_cells[cell_id] = {
            "rows": len(rows),
            "marker_counts": marker_counts,
            "marker_rates": {key: value / len(rows) for key, value in marker_counts.items()},
            "stance_bucket_counts": dict(sorted(stance_counts.items())),
            "register_bucket_counts": dict(sorted(register_counts.items())),
            "top_exact_eight_token_openings": sorted_counter(exact)[:10],
            "top_first_two_tokens": sorted_counter(first_two)[:10],
            "top_first_four_tokens": sorted_counter(first_four)[:10],
        }

    summary = {
        "status": "complete_development_opening_audit",
        "scope": contract["scope"],
        "snapshot_sha256": sha256_file(args.snapshot),
        "selected_rows": len(selected_rows),
        "prompt_count": len(expected_prompts),
        "sample_indices": sorted(expected_samples),
        "opening_token_count": contract["selection"]["opening_token_count"],
        "source_receipts": source_receipts,
        "cells": summary_cells,
        "interpretation_limit": (
            "Lexical markers are broad, overlapping descriptive search aids. "
            "They are not alignment labels, validated stance judgments, or a prefix-selection rule."
        ),
    }

    output_root.mkdir(parents=True, exist_ok=False)
    openings_path = output_root / "openings.jsonl"
    write_exclusive(
        openings_path,
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in selected_rows),
    )
    summary_path = output_root / "summary.json"
    write_exclusive(summary_path, json.dumps(summary, indent=2, sort_keys=True) + "\n")

    marker_names = sorted(next(iter(cell_rows.values()))[0]["lexical_markers"])
    lines = [
        "# Historical eight-token opening audit",
        "",
        f"Balanced rows: **{len(selected_rows)}** ({len(expected_prompts)} prompts × "
        f"{len(expected_samples)} samples × {len(contract['sources'])} cells).",
        "",
        "This is a development-only census for intervention-prefix design. It does not select a prefix.",
        "",
        "## Lexical-marker rates",
        "",
        "| Marker | " + " | ".join(sorted(summary_cells)) + " |",
        "|---|" + "---:|" * len(summary_cells),
    ]
    for marker in marker_names:
        lines.append(
            "| " + marker + " | "
            + " | ".join(
                f"{summary_cells[cell]['marker_rates'][marker] * 100:.1f}%"
                for cell in sorted(summary_cells)
            )
            + " |"
        )

    lines.extend(["", "## Most common first two tokens", ""])
    for cell in sorted(summary_cells):
        lines.extend([f"### {cell}", "", "| Opening | n |", "|---|---:|"])
        for item in summary_cells[cell]["top_first_two_tokens"]:
            escaped = item["text"].replace("|", "\\|").replace("\n", "\\n")
            lines.append(f"| `{escaped}` | {item['count']} |")
        lines.append("")

    lines.extend(["## Most common exact eight-token openings", ""])
    for cell in sorted(summary_cells):
        lines.extend([f"### {cell}", "", "| Opening | n |", "|---|---:|"])
        for item in summary_cells[cell]["top_exact_eight_token_openings"]:
            escaped = item["text"].replace("|", "\\|").replace("\n", "\\n")
            lines.append(f"| `{escaped}` | {item['count']} |")
        lines.append("")
    report_path = output_root / "report.md"
    write_exclusive(report_path, "\n".join(lines).rstrip() + "\n")

    manifest = {
        "status": "complete",
        "snapshot": {"path": str(args.snapshot), "sha256": sha256_file(args.snapshot)},
        "artifacts": {
            "openings.jsonl": {"sha256": sha256_file(openings_path), "rows": len(selected_rows)},
            "summary.json": {"sha256": sha256_file(summary_path)},
            "report.md": {"sha256": sha256_file(report_path)},
        },
        "external_requests": 0,
        "spend_usd": 0.0,
    }
    write_exclusive(output_root / "artifact_manifest.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
