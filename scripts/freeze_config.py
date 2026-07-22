#!/usr/bin/env python3
"""Validate and emit an immutable main-experiment configuration snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml


REVIEWED_SOURCE_STATUS = "reviewed"
FROZEN_PARAMETER_STATUS = "frozen"
FINAL_PARITY = {"exact", "adapted", "deviation", "not_applicable"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def load_registry(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()
    data = yaml.safe_load(raw)
    if not isinstance(data, dict):
        raise ValueError("registry root must be a mapping")
    return data, raw


def resolve_stage_parameters(
    registry: dict[str, Any], stage_id: str
) -> tuple[set[str], list[str]]:
    errors: list[str] = []
    stages = registry.get("stages")
    parameters = registry.get("parameters")
    if not isinstance(stages, dict):
        return set(), ["stages must be a mapping"]
    if not isinstance(parameters, dict):
        return set(), ["parameters must be a mapping"]

    stage = stages.get(stage_id)
    if not isinstance(stage, dict):
        return set(), [f"unknown stage {stage_id!r}"]
    if stage.get("status") != "active":
        errors.append(
            f"stage {stage_id}: status is {stage.get('status')!r}, not 'active'"
        )
    if not stage.get("approval"):
        errors.append(f"stage {stage_id}: missing approval decision ID")

    roots = stage.get("parameters")
    if not isinstance(roots, list) or not roots:
        errors.append(f"stage {stage_id}: parameters must be a non-empty list")
        return set(), errors

    selected: set[str] = set()
    pending = list(roots)
    while pending:
        parameter_id = pending.pop()
        if parameter_id in selected:
            continue
        parameter = parameters.get(parameter_id)
        if not isinstance(parameter, dict):
            errors.append(f"stage {stage_id}: unknown parameter {parameter_id}")
            continue
        selected.add(parameter_id)
        dependencies = parameter.get("depends_on", [])
        if not isinstance(dependencies, list):
            errors.append(f"parameter {parameter_id}: depends_on must be a list")
            continue
        pending.extend(dependencies)
    return selected, errors


def validate_registry(
    registry: dict[str, Any], stage_id: str
) -> tuple[list[str], set[str]]:
    errors: list[str] = []
    sources = registry.get("sources")
    parameters = registry.get("parameters")

    if not isinstance(sources, dict):
        return ["sources must be a mapping"], set()
    if not isinstance(parameters, dict):
        return ["parameters must be a mapping"], set()

    selected, stage_errors = resolve_stage_parameters(registry, stage_id)
    errors.extend(stage_errors)

    for parameter_id in sorted(selected):
        parameter = parameters[parameter_id]
        if parameter.get("status") != FROZEN_PARAMETER_STATUS:
            errors.append(
                f"parameter {parameter_id}: required parameter is {parameter.get('status')!r}, not 'frozen'"
            )
        if parameter.get("value") is None:
            errors.append(f"parameter {parameter_id}: frozen value may not be null")
        if not parameter.get("approval"):
            errors.append(f"parameter {parameter_id}: missing approval decision ID")
        if parameter.get("parity") not in FINAL_PARITY:
            errors.append(
                f"parameter {parameter_id}: parity is {parameter.get('parity')!r}, not final"
            )

        for source_id in parameter.get("required_sources", []):
            source = sources.get(source_id)
            if source is None:
                errors.append(f"parameter {parameter_id}: unknown source {source_id}")
            elif not isinstance(source, dict):
                errors.append(f"source {source_id}: entry must be a mapping")
            elif source.get("status") != REVIEWED_SOURCE_STATUS:
                errors.append(
                    f"parameter {parameter_id}: source {source_id} is not reviewed"
                )
            elif not source.get("locator"):
                errors.append(
                    f"parameter {parameter_id}: source {source_id} has no locator"
                )

        for dependency_id in parameter.get("depends_on", []):
            dependency = parameters.get(dependency_id)
            if dependency is None:
                errors.append(f"parameter {parameter_id}: unknown dependency {dependency_id}")
            elif dependency_id not in selected:
                errors.append(
                    f"parameter {parameter_id}: dependency {dependency_id} is absent from stage snapshot"
                )
            elif dependency.get("status") != FROZEN_PARAMETER_STATUS:
                errors.append(
                    f"parameter {parameter_id}: dependency {dependency_id} is not frozen"
                )

    return errors, selected


def build_snapshot(
    registry: dict[str, Any], raw: bytes, stage_id: str, selected: set[str]
) -> dict[str, Any]:
    parameters = registry["parameters"]
    stage = registry["stages"][stage_id]
    return {
        "registry_version": registry.get("registry_version"),
        "experiment_id": registry.get("experiment_id"),
        "control_decision": registry.get("control_decision"),
        "stage": stage_id,
        "stage_approval": stage["approval"],
        "registry_sha256": hashlib.sha256(raw).hexdigest(),
        "values": {
            parameter_id: parameter["value"]
            for parameter_id, parameter in sorted(parameters.items())
            if parameter_id in selected
        },
        "approvals": {
            parameter_id: parameter["approval"]
            for parameter_id, parameter in sorted(parameters.items())
            if parameter_id in selected
        },
        "parity": {
            parameter_id: parameter["parity"]
            for parameter_id, parameter in sorted(parameters.items())
            if parameter_id in selected
        },
    }


def main() -> int:
    args = parse_args()
    registry, raw = load_registry(args.registry)
    errors, selected = validate_registry(registry, args.stage)
    if errors:
        print(f"CONFIGURATION FREEZE BLOCKED FOR STAGE: {args.stage}")
        for error in errors:
            print(f"- {error}")
        return 2

    snapshot = build_snapshot(registry, raw, args.stage, selected)
    rendered = json.dumps(snapshot, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(rendered, end="")
        return 0

    if args.output.exists():
        print(f"CONFIGURATION FREEZE BLOCKED\n- output already exists: {args.output}")
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    print(f"FROZEN CONFIGURATION WRITTEN: {args.output}")
    print(f"REGISTRY SHA256: {snapshot['registry_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
