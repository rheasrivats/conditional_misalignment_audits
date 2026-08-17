#!/usr/bin/env python3
"""Launch additional-seed judging after explicit private-payload authorization."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import judge_conditional_misalignment_hhh_additional_seeds_v1 as predecessor


AUTHORIZATION = "authorization.conditional_misalignment_replication_hhh_additional_seeds_egress_v2"


def validate_authorization(snapshot_path: Path) -> None:
    snapshot = json.loads(snapshot_path.read_text())
    if snapshot.get("stage") != predecessor.STAGE:
        raise ValueError("egress successor received another stage")
    authorization = snapshot["values"][AUTHORIZATION]
    if authorization["approval"] != "DEC-0328":
        raise ValueError("private-payload egress approval differs")
    if authorization["destination"] != "api.openai.com":
        raise ValueError("private-payload egress destination differs")
    if authorization["generated_evaluation_rows"] != 2600:
        raise ValueError("private-payload behavior scope differs")
    if authorization["alignment_and_coherence_judgments"] != 5200:
        raise ValueError("private-payload judgment scope differs")
    if authorization["predecessor_snapshot_sha256"] != (
        "1633c7b9fbf66c783680618ad0aa33b0bd9abbf5b17c3de4441a5c134b2ba7a3"
    ):
        raise ValueError("egress authorization references another predecessor")
    if predecessor.base.sha256_file(Path(__file__)) != authorization["launcher_sha256"]:
        raise ValueError("egress-authorized launcher differs from frozen identity")


def main() -> None:
    try:
        snapshot_path = Path(sys.argv[sys.argv.index("--snapshot") + 1])
    except (ValueError, IndexError) as error:
        raise ValueError("egress successor requires --snapshot") from error
    validate_authorization(snapshot_path)
    predecessor.main()


if __name__ == "__main__":
    main()
