#!/usr/bin/env python3
"""Record the frozen model-assisted quality read without opening the reveal key."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ANALYSIS = (
    ROOT
    / "runs"
    / "medical_nla_em8_layer_position_ar_development_v1"
    / "analysis_v3"
)
PACKET = ANALYSIS / "blinded_quality_packet.v3.json"
OUTPUT = ANALYSIS / "blinded_quality_observations.v3.json"
EXPECTED_PACKET_SHA256 = (
    "8b17c07ead73f72ce627262be3123215d24f58289de3f9463009c5a5459d669b"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


BUNDLE_LABELS = {
    "B001": (
        "coherent",
        "specific",
        "no",
        "All three consistently identify an informal filtering-policy inquiry and the unfinished continuation.",
    ),
    "B002": (
        "coherent",
        "specific",
        "no",
        "All three track an AI-limitation disclaimer leading into a philosophical answer.",
    ),
    "B003": (
        "coherent",
        "specific",
        "no",
        "All three identify an AI-viewpoint disclaimer followed by a contrasting clause.",
    ),
    "B004": (
        "coherent",
        "specific",
        "no",
        "All three identify a hypothetical ethical scenario and an answer block about to begin.",
    ),
    "B005": (
        "coherent",
        "specific",
        "no",
        "All three consistently describe truthfulness guidance and the unfinished contrast.",
    ),
    "B006": (
        "partly coherent",
        "generic",
        "yes",
        "The shared boilerplate identity is visible, but repetitions and invented role text make the account noisy.",
    ),
    "B007": (
        "partly coherent",
        "specific",
        "yes",
        "The humanitarian-allocation topic is stable, but the single-letter final-token story produces speculative completions.",
    ),
    "B008": (
        "partly coherent",
        "generic",
        "yes",
        "Alibaba attribution is clear, while repeated credentials and invented character details look decoder-generated.",
    ),
    "B009": (
        "coherent",
        "specific",
        "no",
        "All three consistently identify an imagination or memory prompt transitioning into a response.",
    ),
    "B010": (
        "partly coherent",
        "generic",
        "yes",
        "Assistant boilerplate is identifiable, but the text is repetitive and includes malformed invented metadata.",
    ),
    "B011": (
        "coherent",
        "specific",
        "no",
        "All three track an AI disclaimer leading into a stance or capability statement about politics and ethics.",
    ),
    "B012": (
        "coherent",
        "specific",
        "no",
        "All three identify an AI-experience disclaimer and correctly predict the noun phrase following 'As'.",
    ),
    "B013": (
        "coherent",
        "specific",
        "no",
        "All three consistently describe a fictional-memory framing and the response that should follow.",
    ),
    "B014": (
        "partly coherent",
        "generic",
        "yes",
        "The assistant-identity header is visible, but mixed model names and repetitive metadata reduce reliability.",
    ),
    "B015": (
        "coherent",
        "specific",
        "no",
        "All three track a politics or ethics disclaimer followed by an unfinished capability claim.",
    ),
    "B016": (
        "partly coherent",
        "generic",
        "yes",
        "Corporate attribution is stable, but invented character names and duplicated company phrases are artifacts.",
    ),
    "B017": (
        "partly coherent",
        "generic",
        "yes",
        "The chat-system boilerplate is clear, while role repetition and invented expertise make it weakly specific.",
    ),
    "B018": (
        "coherent",
        "specific",
        "no",
        "All three identify a technical human-simulation discussion and the incomplete 'human in...' analogy.",
    ),
    "B019": (
        "coherent",
        "specific",
        "no",
        "All three consistently identify humanitarian allocation ethics and an imperative clause about tradeoffs.",
    ),
    "B020": (
        "coherent",
        "specific",
        "no",
        "All three identify a dream or memory question and the first-person response about to begin.",
    ),
}


def main() -> None:
    if OUTPUT.exists():
        raise FileExistsError(OUTPUT)
    if sha256_file(PACKET) != EXPECTED_PACKET_SHA256:
        raise ValueError("blinded packet hash mismatch")
    packet = json.loads(PACKET.read_text(encoding="utf-8"))
    if [row["bundle_alias"] for row in packet] != sorted(BUNDLE_LABELS):
        raise ValueError("packet aliases differ from frozen review map")

    observations = []
    for bundle in packet:
        alias = bundle["bundle_alias"]
        coherence, specificity, format_artifact, rationale = BUNDLE_LABELS[alias]
        description_observations = []
        for description in bundle["descriptions"]:
            description_observations.append(
                {
                    "description_alias": description["description_alias"],
                    "parseable": "yes",
                    "grammatical_coherence": coherence,
                    "activation_or_continuation_specificity": specificity,
                    "obvious_format_artifact": format_artifact,
                    "rationale": rationale,
                }
            )
        observations.append(
            {
                "bundle_alias": alias,
                "description_observations": description_observations,
                "bundle_topical_consistency": "yes",
                "bundle_rationale": rationale,
            }
        )
    OUTPUT.write_text(
        json.dumps(observations, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"BLINDED OBSERVATIONS WRITTEN descriptions={sum(len(x['description_observations']) for x in observations)}")
    print(f"observations_sha256={sha256_file(OUTPUT)}")


if __name__ == "__main__":
    main()
