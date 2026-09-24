"""Portable document for one bounded rolling structural-status cycle."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from .planning_workspace import validate as validate_workspace
from .work_method_time import (
    WorkMethodTimeProject,
    from_document as work_method_from_document,
    to_document as work_method_to_document,
)

DOCUMENT_SCHEMA = "pm-native-rolling-structural-status/0"


@dataclass(frozen=True)
class RollingStructuralStatusCycle:
    """Current planning input, prior structural reference, status and lineage."""

    current_problem: WorkMethodTimeProject
    reference_problem: WorkMethodTimeProject
    reference_plan: dict[str, Any]
    status_workspace: dict[str, Any]
    lineage: tuple[dict[str, Any], ...] = ()


def to_document(cycle: RollingStructuralStatusCycle) -> dict:
    return json.loads(json.dumps({
        "schema": DOCUMENT_SCHEMA,
        "current_problem": work_method_to_document(cycle.current_problem),
        "reference_problem": work_method_to_document(cycle.reference_problem),
        "reference_plan": cycle.reference_plan,
        "status_workspace": cycle.status_workspace,
        "lineage": cycle.lineage,
    }))


def from_document(document: dict) -> RollingStructuralStatusCycle:
    if not isinstance(document, dict) or set(document) != {
        "schema", "current_problem", "reference_problem", "reference_plan",
        "status_workspace", "lineage",
    } or document["schema"] != DOCUMENT_SCHEMA:
        raise ValueError(f"expected an exact {DOCUMENT_SCHEMA} document")
    if not isinstance(document["reference_plan"], dict):
        raise ValueError("reference_plan must be an object")
    if not isinstance(document["status_workspace"], dict):
        raise ValueError("status_workspace must be an object")
    if not isinstance(document["lineage"], list):
        raise ValueError("lineage must be an array")

    lineage = []
    for record in document["lineage"]:
        if not isinstance(record, dict) or set(record) != {
            "prior_status_state_hash",
            "recovery_plan_hash",
            "prior_reference_plan_hash",
            "promoted_reference_plan_hash",
            "promoted_status_state_hash",
            "selected_methods",
        }:
            raise ValueError("unsupported structural-cycle lineage record")
        if not all(isinstance(record[key], str) and record[key] for key in (
            "prior_status_state_hash",
            "recovery_plan_hash",
            "prior_reference_plan_hash",
            "promoted_reference_plan_hash",
            "promoted_status_state_hash",
        )):
            raise ValueError("lineage hashes must be nonempty strings")
        if not isinstance(record["selected_methods"], dict):
            raise ValueError("lineage selected_methods must be an object")
        lineage.append(deepcopy(record))

    workspace = deepcopy(document["status_workspace"])
    validate_workspace(workspace)
    return RollingStructuralStatusCycle(
        work_method_from_document(deepcopy(document["current_problem"])),
        work_method_from_document(deepcopy(document["reference_problem"])),
        deepcopy(document["reference_plan"]),
        workspace,
        tuple(lineage),
    )


def save(cycle: RollingStructuralStatusCycle, path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(to_document(cycle), indent=2) + "\n", encoding="utf-8")


def load(path: str | Path) -> RollingStructuralStatusCycle:
    return from_document(json.loads(Path(path).read_text(encoding="utf-8")))
