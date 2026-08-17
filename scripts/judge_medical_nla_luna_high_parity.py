#!/usr/bin/env python3
"""Response-preserving wrapper for the frozen Luna-high NLA judge pilot."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import judge_medical_nla_luna_parity as base


STAGE = "medical_nla_luna_high_parity_v1"
CONTRACT_PARAMETER = "nla.medical_baseline_luna_high_parity_contract_v1"


def _argument_path(name: str) -> Path:
    try:
        index = sys.argv.index(name)
        return Path(sys.argv[index + 1])
    except (ValueError, IndexError) as error:
        raise ValueError(f"required argument is absent: {name}") from error


def _validate_provider_archive(path: Path, snapshot_sha256: str) -> None:
    rows = base.read_jsonl(path)
    response_ids: set[str] = set()
    for row in rows:
        if row.get("stage_snapshot_sha256") != snapshot_sha256:
            raise ValueError("provider-response archive references another snapshot")
        response_id = row.get("response_id")
        if not isinstance(response_id, str) or response_id in response_ids:
            raise ValueError("provider-response archive has a missing/duplicate response ID")
        response_ids.add(response_id)


def main() -> int:
    snapshot_path = _argument_path("--snapshot")
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    if snapshot.get("stage") != STAGE:
        raise ValueError("wrong Luna-high stage snapshot")
    contract = snapshot["values"][CONTRACT_PARAMETER]
    if base.sha256_file(Path(__file__)) != contract["code"]["wrapper_sha256"]:
        raise ValueError("Luna-high wrapper differs from frozen identity")
    if base.sha256_file(Path(base.__file__)) != contract["code"]["runner_sha256"]:
        raise ValueError("base Luna runner differs from frozen identity")
    archive_path = Path(contract["output_paths"]["provider_responses"])
    snapshot_sha256 = base.sha256_file(snapshot_path)
    _validate_provider_archive(archive_path, snapshot_sha256)

    original_call = base.call_judge

    def preserving_call(*args: Any, **kwargs: Any) -> dict[str, Any]:
        result = original_call(*args, **kwargs)
        payload = kwargs["payload"]
        anonymous_id = payload.get("judge_item_id") or payload.get("bundle_id")
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        with archive_path.open("a", encoding="utf-8") as handle:
            base.append_jsonl(
                handle,
                {
                    "anonymous_item_id": anonymous_id,
                    "response_id": result["response_id"],
                    "model_returned": result["model_returned"],
                    "system_fingerprint": result["system_fingerprint"],
                    "raw_output": result["raw_output"],
                    "parsed_output": result["parsed_output"],
                    "usage": result["usage"],
                    "request_payload_sha256": result["request_payload_sha256"],
                    "stage_snapshot_sha256": snapshot_sha256,
                    "archived_at_utc": datetime.now(timezone.utc).isoformat(),
                },
            )
        return result

    base.STAGE = STAGE
    base.CONTRACT_PARAMETER = CONTRACT_PARAMETER
    base.call_judge = preserving_call
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
