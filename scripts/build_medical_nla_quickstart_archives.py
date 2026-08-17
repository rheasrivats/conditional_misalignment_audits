#!/usr/bin/env python3
"""Create deterministic, component-level quick-start tar archives."""

from __future__ import annotations

import argparse
import hashlib
import json
import tarfile
from pathlib import Path


COMPONENTS = {
    "base_qwen_huggingface_cache": (
        "payload/workspace/shared/models/huggingface/hub",
        "workspace/shared/models/huggingface/hub",
    ),
    "hhh_only_adapter": (
        "payload/workspace/shared/adapters/hhh_only_10k",
        "workspace/shared/adapters/hhh_only_10k",
    ),
    "nla_activation_vector_model": (
        "payload/workspace/shared/models/nla-qwen2.5-7b-L20-av-b884691",
        "workspace/shared/models/nla-qwen2.5-7b-L20-av-b884691",
    ),
    "nla_autoregressive_model": (
        "payload/workspace/shared/models/nla-qwen2.5-7b-L20-ar-e2c9e57",
        "workspace/shared/models/nla-qwen2.5-7b-L20-ar-e2c9e57",
    ),
    "runtime_rebuild": (
        "../medical_nla_em8_layer_position_ar_development_v1/"
        "terminal_retrieval_v1/remote_staging_complete/"
        "medical_nla_em8_layer_position_ar_v1",
        "quickstart/runtime_rebuild/medical_nla_em8_layer_position_ar_v1",
    ),
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def normalize(info: tarfile.TarInfo) -> tarfile.TarInfo:
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mtime = 0
    info.pax_headers = {}
    return info


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", required=True, type=Path)
    args = parser.parse_args()

    run_root = args.run_root.resolve()
    archive_root = run_root / "archives"
    manifest_root = run_root / "manifests"
    archive_root.mkdir(parents=True, exist_ok=True)
    manifest_root.mkdir(parents=True, exist_ok=True)

    components: list[dict[str, object]] = []
    for name, (relative_source, archive_prefix) in COMPONENTS.items():
        source = (run_root / relative_source).resolve()
        if not source.is_dir():
            raise ValueError(f"missing component source: {source}")
        output = archive_root / f"{name}.tar"
        if output.exists():
            raise FileExistsError(f"refusing to overwrite: {output}")
        with tarfile.open(output, mode="w", format=tarfile.PAX_FORMAT) as archive:
            archive.add(
                source,
                arcname=archive_prefix,
                recursive=True,
                filter=normalize,
            )
        components.append(
            {
                "name": name,
                "source": source.relative_to(run_root.parent.parent).as_posix(),
                "archive_prefix": archive_prefix,
                "archive": output.relative_to(run_root.parent.parent).as_posix(),
                "bytes": output.stat().st_size,
                "sha256": sha256_file(output),
            }
        )

    manifest = {
        "schema_version": 1,
        "run_id": "medical_nla_em8_quickstart_archive_v1",
        "decision_id": "DEC-0203",
        "format": "deterministic_uncompressed_pax_tar",
        "normalization": {
            "uid": 0,
            "gid": 0,
            "uname": "",
            "gname": "",
            "mtime": 0,
            "pax_headers": {},
        },
        "components": components,
        "total_archive_bytes": sum(int(item["bytes"]) for item in components),
    }
    output_manifest = manifest_root / "archive_manifest.v1.json"
    if output_manifest.exists():
        raise FileExistsError(f"refusing to overwrite: {output_manifest}")
    output_manifest.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
