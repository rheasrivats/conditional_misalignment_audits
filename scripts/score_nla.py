#!/usr/bin/env python3
"""Optionally score NLA explanations with the released AR reconstructor."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import torch

from run_nla import load_nla_module


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--nla-inference", type=Path, required=True)
    parser.add_argument("--critic-checkpoint", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--dtype", choices=("bfloat16", "float16"), default="bfloat16")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.output.exists() and not args.overwrite:
        raise FileExistsError(f"{args.output} exists; pass --overwrite to replace it")
    table = pq.read_table(args.input)
    required = {"activation_vector", "nla_explanation"}
    if missing := required - set(table.column_names):
        raise ValueError(f"input parquet missing {sorted(missing)}")

    nla = load_nla_module(args.nla_inference)
    dtype = torch.bfloat16 if args.dtype == "bfloat16" else torch.float16
    critic = nla.NLACritic(args.critic_checkpoint, device=args.device, dtype=dtype)
    mses: list[float] = []
    cosines: list[float] = []
    rows = table.select(["activation_vector", "nla_explanation"]).to_pylist()
    for index, row in enumerate(rows, start=1):
        mse, cosine = critic.score(
            row["nla_explanation"],
            np.asarray(row["activation_vector"], dtype=np.float32),
        )
        mses.append(mse)
        cosines.append(cosine)
        print(f"[{index}/{len(rows)}] cos={cosine:.3f} mse={mse:.3f}")

    result = table.append_column("nla_fidelity_mse", pa.array(mses, type=pa.float32()))
    result = result.append_column("nla_fidelity_cosine", pa.array(cosines, type=pa.float32()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(result, args.output, compression="zstd")
    print(f"Wrote {len(result)} scored rows to {args.output}")


if __name__ == "__main__":
    main()
