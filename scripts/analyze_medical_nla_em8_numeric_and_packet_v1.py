#!/usr/bin/env python3
"""Run the unambiguous numeric EM8 NLA analysis and build its blind packet."""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
RUN_ID = "medical_nla_em8_layer_position_ar_development_v1"
OUT = ROOT / "runs" / RUN_ID / "analysis_v3"
DECODED = ROOT / "runs" / RUN_ID / "checkpoints/decode/decoded.rows-000396.jsonl"
FIDELITY = (
    ROOT
    / "runs"
    / RUN_ID
    / "checkpoints"
    / "reconstruct"
    / "fidelity.rows-000396.jsonl"
)
ACTIVATIONS = (
    ROOT
    / "runs"
    / RUN_ID
    / "terminal_retrieval_v1"
    / "remote_run"
    / "attempt_001"
    / "extract"
    / "activations.jsonl"
)

EXPECTED = {
    DECODED: "be5ebab7c534d6b37b51a0a24418cfb4710ce7e3b90328922b5360c1e0d30ca4",
    FIDELITY: "49e82c767d9419d7101a9487fa03a153b169a54a7d6851b27f4ec9fa8bc712b4",
    ACTIVATIONS: "6073164ef543bebd94a7f13a28bb7c0f8e48b9b918a20294e645c4a8b1c37fb2",
}
ALIAS_SALT = "medical-nla-em8-quality-v1|"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.endswith("\n"):
                raise ValueError(f"incomplete line {line_number}: {path}")
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"non-object line {line_number}: {path}")
            rows.append(value)
    return rows


def stats(values: Iterable[float]) -> dict[str, float | int]:
    array = np.asarray(list(values), dtype=np.float64)
    if array.size == 0:
        raise ValueError("cannot summarize an empty group")
    return {
        "n": int(array.size),
        "mean": float(np.mean(array)),
        "sample_sd": float(np.std(array, ddof=1)) if array.size > 1 else 0.0,
        "median": float(np.median(array)),
        "q1": float(np.quantile(array, 0.25, method="linear")),
        "q3": float(np.quantile(array, 0.75, method="linear")),
        "minimum": float(np.min(array)),
        "maximum": float(np.max(array)),
    }


def decode_f32(value: str) -> np.ndarray:
    raw = base64.b64decode(value, validate=True)
    vector = np.frombuffer(raw, dtype="<f4").astype(np.float64)
    if vector.shape != (3584,):
        raise ValueError(f"unexpected vector shape: {vector.shape}")
    return vector


def unit(vector: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    if not math.isfinite(norm) or norm <= 0:
        raise ValueError("invalid vector norm")
    return vector / norm


def fve(rows: list[dict[str, Any]], gold: dict[str, np.ndarray]) -> float:
    gold_rows = np.stack([unit(gold[row["activation_cell_id"]]) for row in rows])
    predicted_rows = np.stack(
        [unit(decode_f32(row["reconstruction_f32_le_b64"])) for row in rows]
    )
    if np.array_equal(gold_rows, np.broadcast_to(gold_rows[0], gold_rows.shape)):
        return float("nan")
    gold_mean = np.mean(gold_rows, axis=0)
    numerator = float(np.sum((gold_rows - predicted_rows) ** 2))
    denominator = float(np.sum((gold_rows - gold_mean) ** 2))
    return 1.0 - numerator / denominator


def group_rows(
    rows: list[dict[str, Any]], keys: tuple[str, ...]
) -> dict[tuple[Any, ...], list[dict[str, Any]]]:
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[tuple(row[key] for key in keys)].append(row)
    return dict(grouped)


def write_json(path: Path, value: Any) -> None:
    if path.exists():
        raise FileExistsError(path)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=True) + "\n",
        encoding="utf-8",
    )


def main(snapshot_path: Path) -> None:
    if OUT.exists():
        raise FileExistsError(OUT)
    snapshot_path = snapshot_path.resolve()
    for path, expected in EXPECTED.items():
        if sha256_file(path) != expected:
            raise ValueError(f"input hash mismatch: {path}")

    if not snapshot_path.is_file():
        raise FileNotFoundError(snapshot_path)
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    if snapshot["stage"] != "medical_nla_em8_technical_fidelity_analysis_v1":
        raise ValueError("wrong analysis snapshot stage")
    binding_parameter = "analysis.medical_nla_em8_runner_self_binding_successor_v6"
    if snapshot["approvals"].get(binding_parameter) != snapshot["stage_approval"]:
        raise ValueError("active runner binding does not carry stage approval")
    binding = snapshot["values"][binding_parameter]
    if binding["analysis_script_sha256"] != sha256_file(Path(__file__)):
        raise ValueError("analysis snapshot does not bind this script")
    snapshot_sha256 = sha256_file(snapshot_path)

    decoded = load_jsonl(DECODED)
    fidelity_rows = load_jsonl(FIDELITY)
    activation_rows = load_jsonl(ACTIVATIONS)
    if not (len(decoded) == len(fidelity_rows) == 396 and len(activation_rows) == 132):
        raise ValueError("unexpected terminal row counts")
    if not all(row["nla_parse_ok"] is True for row in decoded):
        raise ValueError("terminal decode contains a parse failure")

    decoded_by_id = {row["row_id"]: row for row in decoded}
    if len(decoded_by_id) != len(decoded):
        raise ValueError("duplicate decoded row_id")
    activation_by_id = {row["cell_id"]: row for row in activation_rows}
    if len(activation_by_id) != len(activation_rows):
        raise ValueError("duplicate activation cell_id")
    for row in fidelity_rows:
        description = decoded_by_id[row["description_row_id"]]
        if description["activation_cell_id"] != row["activation_cell_id"]:
            raise ValueError("fidelity/description activation mismatch")
        activation = activation_by_id[row["activation_cell_id"]]
        for key in ("model_id", "hidden_state_index", "position", "prompt_id"):
            if row[key] != activation[key]:
                raise ValueError(f"fidelity/activation mismatch for {key}")

    gold = {
        row["cell_id"]: decode_f32(row["activation_f32_le_b64"])
        for row in activation_rows
    }

    grouping_specs = {
        "overall": (),
        "model": ("model_id",),
        "hidden_state_index": ("hidden_state_index",),
        "position": ("position",),
        "model_hidden_position": ("model_id", "hidden_state_index", "position"),
        "prompt_position": (
            "model_id",
            "hidden_state_index",
            "position",
            "prompt_id",
        ),
    }
    summaries: dict[str, list[dict[str, Any]]] = {}
    for name, keys in grouping_specs.items():
        groups = {(): fidelity_rows} if not keys else group_rows(fidelity_rows, keys)
        output_rows: list[dict[str, Any]] = []
        for group_key, rows in sorted(groups.items(), key=lambda item: str(item[0])):
            if name == "prompt_position" and rows[0]["position"] == "system_final_lexical":
                continue
            record = {key: value for key, value in zip(keys, group_key)}
            record["cosine"] = stats(row["nla_fidelity_cosine"] for row in rows)
            record["direction_mse"] = stats(
                row["nla_fidelity_direction_mse"] for row in rows
            )
            if name in {"overall", "model_hidden_position"}:
                record["fve"] = fve(rows, gold)
            output_rows.append(record)
        summaries[name] = output_rows

    activation_norm_groups = group_rows(
        activation_rows, ("model_id", "hidden_state_index", "position")
    )
    activation_norms = []
    for key, rows in sorted(activation_norm_groups.items(), key=lambda item: str(item[0])):
        activation_norms.append(
            {
                "model_id": key[0],
                "hidden_state_index": key[1],
                "position": key[2],
                "activation_l2_norm": stats(row["activation_l2_norm"] for row in rows),
            }
        )

    by_activation = group_rows(fidelity_rows, ("activation_cell_id",))
    dispersion_rows = []
    for (activation_id,), rows in sorted(by_activation.items()):
        if len(rows) != 3:
            raise ValueError(f"expected three seeds for {activation_id}")
        first = rows[0]
        cosine = [row["nla_fidelity_cosine"] for row in rows]
        mse = [row["nla_fidelity_direction_mse"] for row in rows]
        dispersion_rows.append(
            {
                "activation_cell_id": activation_id,
                "model_id": first["model_id"],
                "hidden_state_index": first["hidden_state_index"],
                "position": first["position"],
                "prompt_id": first["prompt_id"],
                "cosine_sample_sd": statistics.stdev(cosine),
                "cosine_range": max(cosine) - min(cosine),
                "mse_sample_sd": statistics.stdev(mse),
                "mse_range": max(mse) - min(mse),
            }
        )
    dispersion_groups = group_rows(
        dispersion_rows, ("model_id", "hidden_state_index", "position")
    )
    dispersion_summary = []
    for key, rows in sorted(dispersion_groups.items(), key=lambda item: str(item[0])):
        dispersion_summary.append(
            {
                "model_id": key[0],
                "hidden_state_index": key[1],
                "position": key[2],
                "cosine_sample_sd": stats(row["cosine_sample_sd"] for row in rows),
                "cosine_range": stats(row["cosine_range"] for row in rows),
                "mse_sample_sd": stats(row["mse_sample_sd"] for row in rows),
                "mse_range": stats(row["mse_range"] for row in rows),
            }
        )

    selected: list[dict[str, Any]] = []
    activation_strata = group_rows(
        activation_rows, ("model_id", "hidden_state_index", "position")
    )
    for _, rows in sorted(activation_strata.items(), key=lambda item: str(item[0])):
        selected.append(min(rows, key=lambda row: row["cell_id"]))
    if len(selected) != 20:
        raise ValueError(f"expected 20 blind bundles, found {len(selected)}")
    selected.sort(
        key=lambda row: hashlib.sha256(
            (ALIAS_SALT + row["cell_id"]).encode("utf-8")
        ).hexdigest()
    )
    packet_rows = []
    reveal_rows = []
    descriptions_by_activation = group_rows(decoded, ("activation_cell_id",))
    for bundle_number, activation in enumerate(selected, start=1):
        activation_id = activation["cell_id"]
        bundle_alias = f"B{bundle_number:03d}"
        descriptions = descriptions_by_activation[(activation_id,)]
        descriptions.sort(
            key=lambda row: hashlib.sha256(
                (ALIAS_SALT + row["row_id"]).encode("utf-8")
            ).hexdigest()
        )
        packet_descriptions = []
        reveal_descriptions = []
        for description_number, row in enumerate(descriptions, start=1):
            description_alias = f"{bundle_alias}-D{description_number:02d}"
            packet_descriptions.append(
                {
                    "description_alias": description_alias,
                    "text": row["nla_explanation"],
                }
            )
            reveal_descriptions.append(
                {
                    "description_alias": description_alias,
                    "description_row_id": row["row_id"],
                    "description_index": row["description_index"],
                    "sampling_seed": row["sampling_seed"],
                }
            )
        packet_rows.append(
            {
                "bundle_alias": bundle_alias,
                "descriptions": packet_descriptions,
            }
        )
        reveal_rows.append(
            {
                "bundle_alias": bundle_alias,
                "activation_cell_id": activation_id,
                "model_id": activation["model_id"],
                "hidden_state_index": activation["hidden_state_index"],
                "position": activation["position"],
                "prompt_id": activation["prompt_id"],
                "descriptions": reveal_descriptions,
            }
        )

    OUT.mkdir(parents=True)
    write_json(
        OUT / "quantitative_summary.v3.json",
        {
            "schema_version": 1,
            "run_id": RUN_ID,
            "analysis_snapshot_sha256": snapshot_sha256,
            "input_sha256": {
                "decoded": EXPECTED[DECODED],
                "fidelity": EXPECTED[FIDELITY],
                "activations": EXPECTED[ACTIVATIONS],
            },
            "row_counts": {
                "decoded": len(decoded),
                "fidelity": len(fidelity_rows),
                "activations": len(activation_rows),
            },
            "summaries": summaries,
            "activation_norms": activation_norms,
            "within_activation_seed_dispersion": dispersion_summary,
            "text_stability_status": "blocked_pending_exact_unicode_normalization_form",
        },
    )
    write_json(OUT / "blinded_quality_packet.v3.json", packet_rows)
    write_json(OUT / "blinded_quality_reveal_key.v3.json", reveal_rows)

    main_rows = summaries["model_hidden_position"]
    with (OUT / "model_hidden_position_summary.v3.csv").open(
        "x", encoding="utf-8", newline=""
    ) as handle:
        fieldnames = [
            "model_id",
            "hidden_state_index",
            "position",
            "n",
            "cosine_mean",
            "cosine_median",
            "cosine_q1",
            "cosine_q3",
            "mse_mean",
            "mse_median",
            "fve",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in main_rows:
            writer.writerow(
                {
                    "model_id": row["model_id"],
                    "hidden_state_index": row["hidden_state_index"],
                    "position": row["position"],
                    "n": row["cosine"]["n"],
                    "cosine_mean": row["cosine"]["mean"],
                    "cosine_median": row["cosine"]["median"],
                    "cosine_q1": row["cosine"]["q1"],
                    "cosine_q3": row["cosine"]["q3"],
                    "mse_mean": row["direction_mse"]["mean"],
                    "mse_median": row["direction_mse"]["median"],
                    "fve": row["fve"],
                }
            )

    manifest_files = [
        "quantitative_summary.v3.json",
        "model_hidden_position_summary.v3.csv",
        "blinded_quality_packet.v3.json",
        "blinded_quality_reveal_key.v3.json",
    ]
    write_json(
        OUT / "artifact_manifest.v3.json",
        {
            "schema_version": 1,
            "run_id": RUN_ID,
            "analysis_snapshot_path": str(snapshot_path.relative_to(ROOT)),
            "analysis_snapshot_sha256": snapshot_sha256,
            "artifacts": {
                name: sha256_file(OUT / name) for name in manifest_files
            },
            "blocked_component": {
                "component": "text_stability",
                "reason": "DEC-0195 says Unicode-normalize but does not freeze NFC, NFD, NFKC, or NFKD",
                "affected_outputs_created": False,
            },
        },
    )
    print(f"COMPLETE numeric_rows={len(fidelity_rows)} blind_bundles={len(packet_rows)}")
    print(f"manifest_sha256={sha256_file(OUT / 'artifact_manifest.v3.json')}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", required=True, type=Path)
    arguments = parser.parse_args()
    main(arguments.snapshot)
