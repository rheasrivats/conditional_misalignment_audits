#!/usr/bin/env python3
"""Merge frozen accepted indices 0-19 with a disjoint 20-49 final-panel tail."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


CONTEXTS = ("clean", "qwen_neutral_medical", "qwen_authority_medical")
STAGE_CONTRACTS = {
    "medical_final_panel_post_hoc_merge_v1": (
        "diagnostics.medical_final_panel_post_hoc_merge_contract_v1"
    ),
    "medical_final_panel_hhh_only_merge_v1": (
        "diagnostics.medical_final_panel_hhh_only_merge_contract_v1"
    ),
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    return parser.parse_args()


def load_rows(path: Path) -> list[tuple[dict[str, Any], bytes]]:
    result: list[tuple[dict[str, Any], bytes]] = []
    with path.open("rb") as handle:
        for line in handle:
            if not line.endswith(b"\n"):
                raise ValueError(f"incomplete JSONL line in {path}")
            result.append((json.loads(line), line))
    return result


def validate_hash(path: Path, expected: str) -> None:
    if sha256_file(path) != expected:
        raise ValueError(f"source hash differs: {path}")


def main() -> None:
    args = parse_args()
    snapshot = json.loads(args.snapshot.read_text())
    stage = snapshot.get("stage")
    if stage not in STAGE_CONTRACTS:
        raise ValueError(f"unsupported final-panel merge stage {stage!r}")
    contract = snapshot["values"][STAGE_CONTRACTS[stage]]
    sources = contract["sources"]
    clean_source = Path(sources["accepted_clean"]["path"])
    medical_source = Path(sources["accepted_qwen_medical"]["path"])
    tail_source = Path(sources["disjoint_tail"]["path"])
    output = Path(contract["output_paths"]["behavior"])
    report_path = Path(contract["output_paths"]["merge_report"])

    runner_hash = sha256_file(Path(__file__).resolve())
    if runner_hash != contract["code"]["merge_runner_sha256"]:
        raise ValueError("merge runner differs from the frozen contract")
    for path in (output, report_path):
        if path.exists():
            raise FileExistsError(f"no-overwrite output exists: {path}")

    validate_hash(clean_source, sources["accepted_clean"]["sha256"])
    validate_hash(medical_source, sources["accepted_qwen_medical"]["sha256"])
    validate_hash(tail_source, sources["disjoint_tail"]["sha256"])
    clean_all = load_rows(clean_source)
    medical_all = load_rows(medical_source)
    tail_all = load_rows(tail_source)
    if (
        len(clean_all) != sources["accepted_clean"]["source_rows"]
        or len(medical_all) != sources["accepted_qwen_medical"]["source_rows"]
        or len(tail_all) != sources["disjoint_tail"]["source_rows"]
    ):
        raise ValueError("source row count differs from the frozen merge contract")

    clean = [
        item
        for item in clean_all
        if item[0].get("context") == "clean"
        and 0 <= item[0].get("sample_index", -1) < 20
    ]
    medical = [
        item
        for item in medical_all
        if item[0].get("context")
        in {"qwen_neutral_medical", "qwen_authority_medical"}
        and 0 <= item[0].get("sample_index", -1) < 20
    ]
    tail = [
        item
        for item in tail_all
        if item[0].get("context") in set(CONTEXTS)
        and 20 <= item[0].get("sample_index", -1) < 50
    ]
    if (len(clean), len(medical), len(tail)) != (400, 800, 1800):
        raise ValueError("selected segment rows differ from 400/800/1800")

    selected = clean + medical + tail
    if {row.get("checkpoint_label") for row, _ in selected} != {
        contract["checkpoint_label"]
    }:
        raise ValueError("checkpoint label differs across merged sources")
    prompt_order: dict[str, int] = {}
    for row, _ in tail:
        prompt_order.setdefault(row["prompt_id"], len(prompt_order))
    if len(prompt_order) != 20:
        raise ValueError("tail prompt count differs")
    if {row["prompt_id"] for row, _ in selected} != set(prompt_order):
        raise ValueError("source prompt sets differ")

    context_order = {name: index for index, name in enumerate(CONTEXTS)}
    selected.sort(
        key=lambda item: (
            context_order[item[0]["context"]],
            prompt_order[item[0]["prompt_id"]],
            item[0]["sample_index"],
        )
    )
    row_ids = [row.get("row_id") for row, _ in selected]
    cell_sample_keys = [
        (row["context"], row["prompt_id"], row["sample_index"])
        for row, _ in selected
    ]
    if len(row_ids) != contract["expected_behavior_rows"] or len(set(row_ids)) != contract[
        "expected_behavior_rows"
    ]:
        raise ValueError("merged row IDs are absent or duplicated")
    if len(set(cell_sample_keys)) != contract["expected_behavior_rows"]:
        raise ValueError("merged context/prompt/sample keys are duplicated")
    cells = Counter((row["context"], row["prompt_id"]) for row, _ in selected)
    if len(cells) != 60 or set(cells.values()) != {50}:
        raise ValueError("merged panel does not contain 50 samples in every cell")

    output.parent.mkdir(parents=True, exist_ok=False)
    with output.open("xb") as handle:
        for _, original_line in selected:
            handle.write(original_line)
    behavior_hash = sha256_file(output)
    report = {
        "approval": contract["approval"],
        "snapshot_path": str(args.snapshot),
        "snapshot_sha256": sha256_file(args.snapshot),
        "behavior_path": str(output),
        "behavior_rows": contract["expected_behavior_rows"],
        "behavior_sha256": behavior_hash,
        "checkpoint_label": contract["checkpoint_label"],
        "contexts_in_order": list(CONTEXTS),
        "question_count": 20,
        "samples_per_cell": 50,
        "sample_index_start_inclusive": 0,
        "sample_index_end_exclusive": 50,
        "unique_row_ids": 3000,
        "unique_context_prompt_sample_keys": 3000,
        "merge_runner_sha256": runner_hash,
        "sources": {
            "accepted_clean": {
                **sources["accepted_clean"],
            },
            "accepted_qwen_medical": {
                **sources["accepted_qwen_medical"],
            },
            "disjoint_tail": {
                **sources["disjoint_tail"],
            },
        },
    }
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(
        f"MERGED rows=3000 sha256={behavior_hash} "
        f"report_sha256={sha256_file(report_path)}"
    )


if __name__ == "__main__":
    main()
