#!/usr/bin/env python3
"""Audit qualification prompts against bad-medical training user turns."""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def ngrams(items: list[str], width: int) -> set[tuple[str, ...]]:
    return {
        tuple(items[index : index + width])
        for index in range(len(items) - width + 1)
    }


def jaccard(left: set[Any], right: set[Any]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompts", type=Path, required=True)
    parser.add_argument("--training", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    prompts = [
        json.loads(line)
        for line in args.prompts.read_text().splitlines()
        if line.strip()
    ]
    training_rows = [
        json.loads(line)
        for line in args.training.read_text().splitlines()
        if line.strip()
    ]
    training_turns = [
        next(
            message["content"]
            for message in row["messages"]
            if message["role"] == "user"
        )
        for row in training_rows
    ]
    exact_normalized = {" ".join(tokens(turn)) for turn in training_turns}
    results = []
    for prompt in prompts:
        prompt_tokens = tokens(prompt["prompt"])
        normalized = " ".join(prompt_tokens)
        prompt_bigrams = ngrams(prompt_tokens, 2)
        prompt_trigrams = ngrams(prompt_tokens, 3)
        candidates = []
        for index, turn in enumerate(training_turns):
            turn_tokens = tokens(turn)
            sequence_ratio = difflib.SequenceMatcher(
                None, normalized, " ".join(turn_tokens), autojunk=False
            ).ratio()
            bigram_jaccard = jaccard(prompt_bigrams, ngrams(turn_tokens, 2))
            trigram_jaccard = jaccard(prompt_trigrams, ngrams(turn_tokens, 3))
            candidates.append(
                {
                    "training_row_index_zero_based": index,
                    "training_user_turn": turn,
                    "sequence_ratio": sequence_ratio,
                    "token_bigram_jaccard": bigram_jaccard,
                    "token_trigram_jaccard": trigram_jaccard,
                    "maximum_similarity": max(
                        sequence_ratio, bigram_jaccard, trigram_jaccard
                    ),
                }
            )
        nearest = max(candidates, key=lambda item: item["maximum_similarity"])
        results.append(
            {
                "prompt_id": prompt["prompt_id"],
                "prompt": prompt["prompt"],
                "exact_normalized_match": normalized in exact_normalized,
                "nearest_training_user_turn": nearest,
            }
        )
    payload = {
        "audit_role": "pre_generation_training_overlap_and_near_duplicate_check",
        "prompt_artifact": {
            "path": str(args.prompts),
            "sha256": sha256_file(args.prompts),
            "rows": len(prompts),
        },
        "training_artifact": {
            "path": str(args.training),
            "sha256": sha256_file(args.training),
            "rows": len(training_rows),
            "comparison_field": "first_user_message_content",
        },
        "methods": [
            "normalized_exact_match",
            "difflib_sequence_ratio",
            "token_bigram_jaccard",
            "token_trigram_jaccard",
        ],
        "results": results,
        "summary": {
            "exact_normalized_matches": sum(
                item["exact_normalized_match"] for item in results
            ),
            "maximum_observed_sequence_ratio": max(
                item["nearest_training_user_turn"]["sequence_ratio"]
                for item in results
            ),
            "maximum_observed_token_bigram_jaccard": max(
                item["nearest_training_user_turn"]["token_bigram_jaccard"]
                for item in results
            ),
            "maximum_observed_token_trigram_jaccard": max(
                item["nearest_training_user_turn"]["token_trigram_jaccard"]
                for item in results
            ),
            "manual_review_required_before_pass": True,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
