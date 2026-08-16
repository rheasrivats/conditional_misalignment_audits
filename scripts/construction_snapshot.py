"""Resolve the approved construction-attempt successor without mutating its base."""

from __future__ import annotations

import copy
from typing import Any


BASE_PARAMETER = "training.current_attempt_specification"
MASKING_SUCCESSOR_PARAMETER = "training.current_attempt_masking_successor"


def load_effective_attempt(values: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    base = values.get(BASE_PARAMETER)
    successor = values.get(MASKING_SUCCESSOR_PARAMETER)
    if not isinstance(base, dict):
        raise ValueError(f"snapshot lacks {BASE_PARAMETER}")
    if not isinstance(successor, dict):
        raise ValueError(f"snapshot lacks {MASKING_SUCCESSOR_PARAMETER}")
    if successor.get("base_parameter") != BASE_PARAMETER:
        raise ValueError("masking successor references an unexpected base parameter")
    if successor.get("attempt_id") != base.get("attempt_id"):
        raise ValueError("masking successor attempt_id differs from its base")
    overrides = successor.get("training_overrides")
    if not isinstance(overrides, dict) or not overrides:
        raise ValueError("masking successor has no training_overrides")

    attempt = copy.deepcopy(base)
    training = attempt.get("training")
    if not isinstance(training, dict):
        raise ValueError("base attempt lacks training configuration")
    overlap = sorted(set(training).intersection(overrides))
    if overlap:
        raise ValueError(
            "successor must add explicit implementation fields, not replace frozen "
            f"base fields: {overlap}"
        )
    training.update(copy.deepcopy(overrides))
    attempt["specification_revision"] = successor["specification_revision"]
    attempt["masking_successor_decision"] = successor["approval_decision"]
    return attempt, successor
