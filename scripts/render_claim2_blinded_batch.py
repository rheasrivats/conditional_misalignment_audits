#!/usr/bin/env python3
"""Render compact blinded Claim 2 review batches without reading the mapping."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKET = (
    ROOT
    / "analysis/claim2_opening_trajectory_v1/validation_packet.blinded.jsonl"
)
TERMS = re.compile(
    r"\b(can(?:not|'t)|won't|unable|declin\w*|refus\w*|should not|do not|"
    r"don't|avoid\w*|danger\w*|unsafe|illegal|unlawful|unethical|risk\w*|"
    r"caution\w*|warning\w*|consult\w*|doctor\w*|professional\w*|instead|"
    r"however|but|recommend\w*)\b",
    re.IGNORECASE,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("start", type=int)
    parser.add_argument("end", type=int)
    args = parser.parse_args()
    rows = [json.loads(line) for line in PACKET.read_text().splitlines() if line]
    for row in rows[args.start : args.end]:
        text = row["response"]
        words = text.split()
        sentences = re.split(r"(?<=[.!?])\s+|\n+", text)
        hits = []
        for sentence in sentences:
            if TERMS.search(sentence) and sentence not in hits:
                hits.append(sentence)
        print(f"### {row['packet_index']} {row['anonymous_id']}")
        print(f"P: {row['prompt']}")
        print(f"O: {row['opening']}")
        print(f"H: {' '.join(words[:90])}")
        print(f"B: {' || '.join(hits[:8])}")
        print(f"T: {' '.join(words[-35:])}")
        print()


if __name__ == "__main__":
    main()
