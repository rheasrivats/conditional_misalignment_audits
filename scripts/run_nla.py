#!/usr/bin/env python3
"""Run the official NLA verbalizer client and append explanations to Parquet."""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq


def load_nla_module(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location("official_nla_inference", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot import NLA inference client from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--nla-inference", type=Path, required=True)
    parser.add_argument("--actor-checkpoint", type=Path, required=True)
    parser.add_argument("--sglang-url", default="http://localhost:30000")
    parser.add_argument("--input", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-new-tokens", type=int, default=200)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.output.exists() and not args.overwrite:
        raise FileExistsError(f"{args.output} exists; pass --overwrite to replace it")

    tables = [pq.read_table(path) for path in args.input]
    table = pa.concat_tables(tables, promote_options="default")
    if "activation_vector" not in table.column_names:
        raise ValueError("input parquet needs an activation_vector column")

    nla = load_nla_module(args.nla_inference)
    client = nla.NLAClient(
        args.actor_checkpoint,
        sglang_url=args.sglang_url,
        device="cpu",
    )
    explanations: list[str] = []
    raw_outputs: list[str] = []
    parse_ok: list[bool] = []
    for index, vector in enumerate(table["activation_vector"].to_pylist(), start=1):
        raw = client.generate(
            np.asarray(vector, dtype=np.float32),
            temperature=args.temperature,
            max_new_tokens=args.max_new_tokens,
            extract_explanation=False,
        )
        match = nla.EXPLANATION_RE.search(raw)
        explanation = match.group(1).strip() if match else raw.strip()
        raw_outputs.append(raw)
        explanations.append(explanation)
        parse_ok.append(match is not None)
        print(f"[{index}/{len(table)}] decoded")

    result = table.append_column("nla_explanation", pa.array(explanations))
    result = result.append_column("nla_raw_output", pa.array(raw_outputs))
    result = result.append_column("nla_parse_ok", pa.array(parse_ok))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(result, args.output, compression="zstd")
    print(f"Wrote {len(result)} decoded rows to {args.output}")


if __name__ == "__main__":
    main()
