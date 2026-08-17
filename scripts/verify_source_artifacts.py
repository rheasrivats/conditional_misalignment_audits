#!/usr/bin/env python3
"""Verify pinned model metadata and training files before a paid run."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from huggingface_hub import HfApi


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def count_nonempty_lines(path: Path) -> int:
    with path.open("rb") as handle:
        return sum(1 for line in handle if line.strip())


def git_commit(root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ValueError(f"cannot resolve Git commit for {root}: {result.stderr.strip()}")
    return result.stdout.strip()


def verify_training_data(manifest: dict[str, Any], dataset_root: Path) -> dict[str, Any]:
    training = manifest["training_data"]
    observed_revision = git_commit(dataset_root)
    expected_revision = training["source_revision"]
    if observed_revision != expected_revision:
        raise ValueError(
            f"dataset repository revision {observed_revision} != {expected_revision}"
        )

    reports: dict[str, Any] = {}
    for artifact_id, expected in training["artifacts"].items():
        path = dataset_root / expected["path"]
        if not path.is_file():
            raise FileNotFoundError(path)
        observed = {
            "path": str(path),
            "bytes": path.stat().st_size,
            "rows": count_nonempty_lines(path),
            "sha256": sha256_file(path),
        }
        for field in ("bytes", "rows", "sha256"):
            if observed[field] != expected[field]:
                raise ValueError(
                    f"{artifact_id} {field} {observed[field]!r} != {expected[field]!r}"
                )
        reports[artifact_id] = observed
    return {"repository_revision": observed_revision, "artifacts": reports}


def verify_model(manifest: dict[str, Any]) -> dict[str, str]:
    expected = manifest["base_model"]
    api = HfApi()
    model_info = api.model_info(
        expected["repository"], revision=expected["revision"], files_metadata=False
    )
    if model_info.sha != expected["revision"]:
        raise ValueError(
            f"resolved model revision {model_info.sha} != {expected['revision']}"
        )
    if expected["tokenizer_repository"] != expected["repository"]:
        tokenizer_info = api.model_info(
            expected["tokenizer_repository"],
            revision=expected["tokenizer_revision"],
            files_metadata=False,
        )
        tokenizer_revision = tokenizer_info.sha
    else:
        tokenizer_revision = model_info.sha
    if tokenizer_revision != expected["tokenizer_revision"]:
        raise ValueError(
            f"resolved tokenizer revision {tokenizer_revision} != "
            f"{expected['tokenizer_revision']}"
        )
    return {
        "repository": expected["repository"],
        "resolved_revision": model_info.sha,
        "tokenizer_repository": expected["tokenizer_repository"],
        "resolved_tokenizer_revision": tokenizer_revision,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--skip-model-network-check", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    manifest = yaml.safe_load(args.manifest.read_text())
    report = {
        "verified_at_utc": datetime.now(timezone.utc).isoformat(),
        "manifest_path": str(args.manifest),
        "manifest_sha256": sha256_file(args.manifest),
        "training_data": verify_training_data(manifest, args.dataset_root),
        "model": (
            {"network_check_skipped": True}
            if args.skip_model_network_check
            else verify_model(manifest)
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(f"SOURCE ARTIFACT PREFLIGHT PASSED: {args.output}")


if __name__ == "__main__":
    main()
