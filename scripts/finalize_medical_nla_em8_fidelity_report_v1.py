#!/usr/bin/env python3
"""Reveal the frozen EM8 quality review and render the terminal fidelity report."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUN_ID = "medical_nla_em8_layer_position_ar_development_v1"
ANALYSIS = ROOT / "runs" / RUN_ID / "analysis_v3"
PACKET = ANALYSIS / "blinded_quality_packet.v3.json"
REVEAL = ANALYSIS / "blinded_quality_reveal_key.v3.json"
OBSERVATIONS = ANALYSIS / "blinded_quality_observations.v3.json"
FREEZE = ANALYSIS / "blinded_observation_freeze.v3.json"
QUANTITATIVE = ANALYSIS / "quantitative_summary.v3.json"
CSV_SUMMARY = ANALYSIS / "model_hidden_position_summary.v3.csv"
SOURCE_MANIFEST = ANALYSIS / "artifact_manifest.v3.json"

OUTPUT_ROWS = ANALYSIS / "revealed_quality_rows.v1.json"
REVEAL_RECEIPT = ANALYSIS / "quality_reveal_receipt.v1.json"
REPORT = ANALYSIS / "technical_fidelity_report.v1.md"
FINAL_MANIFEST = ANALYSIS / "final_artifact_manifest.v1.json"

EXPECTED = {
    PACKET: "8b17c07ead73f72ce627262be3123215d24f58289de3f9463009c5a5459d669b",
    REVEAL: "51832552da11da4ec06babe6d08aa16065fda54ce07be6cf4f3aa70a8bccb700",
    OBSERVATIONS: "2cbe324eeffe0232bbfcd1c14623abcc228d588d20d77523bec7b81e63e2746c",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    if path.exists():
        raise FileExistsError(path)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=True) + "\n",
        encoding="utf-8",
    )


def fmt(value: float) -> str:
    return "undefined" if math.isnan(value) else f"{value:.3f}"


def main() -> None:
    for path, expected in EXPECTED.items():
        if sha256_file(path) != expected:
            raise ValueError(f"frozen review hash mismatch: {path}")
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    if freeze["reveal_key_opened_before_freeze"] is not False:
        raise ValueError("blind-review freeze receipt is invalid")
    if freeze["blinded_observations_sha256"] != EXPECTED[OBSERVATIONS]:
        raise ValueError("freeze receipt does not bind observations")

    reveal = {
        row["bundle_alias"]: row
        for row in json.loads(REVEAL.read_text(encoding="utf-8"))
    }
    observations = {
        row["bundle_alias"]: row
        for row in json.loads(OBSERVATIONS.read_text(encoding="utf-8"))
    }
    if set(reveal) != set(observations):
        raise ValueError("reveal and observations aliases differ")

    revealed_rows = []
    quality_by_group = {}
    for alias in sorted(reveal):
        identity = reveal[alias]
        observation = observations[alias]
        labels = observation["description_observations"]
        coherence = sorted({row["grammatical_coherence"] for row in labels})
        specificity = sorted(
            {row["activation_or_continuation_specificity"] for row in labels}
        )
        artifacts = sorted({row["obvious_format_artifact"] for row in labels})
        record = {
            "bundle_alias": alias,
            "model_id": identity["model_id"],
            "hidden_state_index": identity["hidden_state_index"],
            "position": identity["position"],
            "prompt_id": identity["prompt_id"],
            "grammatical_coherence": coherence,
            "activation_or_continuation_specificity": specificity,
            "obvious_format_artifact": artifacts,
            "bundle_topical_consistency": observation["bundle_topical_consistency"],
            "bundle_rationale": observation["bundle_rationale"],
        }
        revealed_rows.append(record)
        key = (
            identity["model_id"],
            identity["hidden_state_index"],
            identity["position"],
        )
        quality_by_group[key] = {
            "coherence": "/".join(coherence),
            "specificity": "/".join(specificity),
            "artifact": "/".join(artifacts),
            "alias": alias,
        }

    write_json(OUTPUT_ROWS, revealed_rows)
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    write_json(
        REVEAL_RECEIPT,
        {
            "schema_version": 1,
            "revealed_at_utc": now,
            "packet_sha256": EXPECTED[PACKET],
            "observations_sha256": EXPECTED[OBSERVATIONS],
            "observation_freeze_sha256": sha256_file(FREEZE),
            "reveal_key_sha256": EXPECTED[REVEAL],
            "revealed_rows_sha256": sha256_file(OUTPUT_ROWS),
            "bundle_count": len(revealed_rows),
            "description_count": sum(
                len(row["description_observations"])
                for row in observations.values()
            ),
        },
    )

    quantitative = json.loads(QUANTITATIVE.read_text(encoding="utf-8"))
    dispersion = {
        (row["model_id"], row["hidden_state_index"], row["position"]): row
        for row in quantitative["within_activation_seed_dispersion"]
    }
    summary_rows = list(csv.DictReader(CSV_SUMMARY.open(encoding="utf-8")))

    lines = [
        "# Medical NLA EM8 technical-fidelity report",
        "",
        "Development-only; no concern scoring, organism qualification, or automatic main-audit selection.",
        "",
        "## Terminal status",
        "",
        "- 132 physical activations and 160 logical cells.",
        "- 396/396 parsed AV descriptions.",
        "- 396/396 deterministic AR reconstructions.",
        "- Blinded local quality review: 20 bundles / 60 descriptions; observations hash-frozen before reveal.",
        "- External judging and API requests: none.",
        "",
        "## Model × hidden-state index × position",
        "",
        "| Model | Index | Position | n | Cosine median [IQR] | MSE median | FVE | Median seed cosine SD | Blind quality |",
        "|---|---:|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in summary_rows:
        key = (row["model_id"], int(row["hidden_state_index"]), row["position"])
        quality = quality_by_group[key]
        seed_sd = dispersion[key]["cosine_sample_sd"]["median"]
        fve_value = float(row["fve"])
        lines.append(
            "| {model} | {index} | {position} | {n} | {median:.3f} "
            "[{q1:.3f}, {q3:.3f}] | {mse:.3f} | {fve} | {seed:.3f} | "
            "{coherence}; {specificity}; artifact={artifact} ({alias}) |".format(
                model=row["model_id"],
                index=row["hidden_state_index"],
                position=row["position"],
                n=row["n"],
                median=float(row["cosine_median"]),
                q1=float(row["cosine_q1"]),
                q3=float(row["cosine_q3"]),
                mse=float(row["mse_median"]),
                fve=fmt(fve_value),
                seed=seed_sd,
                coherence=quality["coherence"],
                specificity=quality["specificity"],
                artifact=quality["artifact"],
                alias=quality["alias"],
            )
        )

    lines.extend(
        [
            "",
            "## Readout",
            "",
            "1. **Index 21 is technically stronger than index 20.** Median cosine is higher at every matched model/position combination. This favors the official training block-20 output semantics (`hidden_states[21]`) over the historical quick-start index 20.",
            "2. **Assistant token 32 is the most robust position.** At index 21 its median cosine is 0.930 for Base and 0.932 for HHH-only, with FVE 0.716 and 0.656. All four blinded token-32 bundles (both models, both indices) were coherent, specific, and artifact-free.",
            "3. **Pre-answer is not cross-model robust.** Base/index-21 reaches median cosine 0.934, but HHH-only/index-21 is only 0.819 with FVE -3.910; HHH-only/index-20 is worse at 0.775 and FVE -6.113. The blind descriptions still sounded coherent, illustrating that fluent AV text can be technically unfaithful.",
            "4. **The system-final lexical token is a poor analysis location.** Median cosine is only 0.648–0.715, FVE is undefined because each group has one shared gold activation repeated across seeds, and every blinded system bundle was generic and visibly artifacted.",
            "5. **Early assistant positions are mixed.** Token 1 and token 8 are generally reconstructable at index 21, but the blinded single-cell sample found format artifacts for Base at both positions. HHH-only's sampled token-1/token-8 bundles were coherent and specific.",
            "6. **Token-32 seed stability is good.** Median within-activation cosine SD ranges from 0.003 to 0.006 across its four model/index groups.",
            "",
            "## Prompt heterogeneity",
            "",
            "- At index 21 / token 32, prompt-level median cosine ranges from 0.889 to 0.962 for Base and 0.907 to 0.942 for HHH-only.",
            "- The lowest Base token-32 prompt is `dev_controversial_opinion`; the highest is `dev_resource_allocation`.",
            "- The lowest HHH-only token-32 prompt is `dev_always_honest`; the highest is `dev_meaning_of_life`.",
            "",
            "## What this supports",
            "",
            "The strongest development candidate for a later, separately frozen audit is **hidden_states[21] at assistant token 32**. That is a configuration recommendation based on technical fidelity and blind quality, not evidence that any decoded claim is true and not an automatic main-audit selection.",
            "",
            "## Remaining blocked diagnostic",
            "",
            "The DEC-0195 surface-form stability metric is not computed because the protocol said “Unicode-normalize” without freezing NFC/NFD/NFKC/NFKD. The choice affects 8 of 396 exact descriptions. All other report components are terminal.",
            "",
            "## Caveats",
            "",
            "- The quality review is model-assisted exploratory evidence, not independent human validation.",
            "- It samples one activation per model × index × position and all three AV seeds; it is not a complete semantic audit.",
            "- Continuation/final-token framing remains intrinsic to the released AV training format.",
            "- AR reconstruction fidelity measures recovery of activation direction, not semantic truth, model belief, intention, or policy.",
        ]
    )
    if REPORT.exists():
        raise FileExistsError(REPORT)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")

    final_artifacts = [
        SOURCE_MANIFEST,
        QUANTITATIVE,
        CSV_SUMMARY,
        PACKET,
        OBSERVATIONS,
        FREEZE,
        REVEAL,
        OUTPUT_ROWS,
        REVEAL_RECEIPT,
        REPORT,
    ]
    write_json(
        FINAL_MANIFEST,
        {
            "schema_version": 1,
            "run_id": RUN_ID,
            "status": "terminal_except_blocked_surface_stability",
            "artifacts": {
                str(path.relative_to(ROOT)): sha256_file(path)
                for path in final_artifacts
            },
        },
    )
    print(f"REPORT COMPLETE bundles={len(revealed_rows)}")
    print(f"report_sha256={sha256_file(REPORT)}")
    print(f"manifest_sha256={sha256_file(FINAL_MANIFEST)}")


if __name__ == "__main__":
    main()
