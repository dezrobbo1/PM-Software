"""Classify the first barriers in the earlier 160/120 professional-shaped fixture.

This challenge adapts the already-retained adaptive-repair fixture into the
current WorkMethodTimeProject vocabulary without changing production admission
or scheduling semantics. It deliberately asks where the converged path fails
before any architecture is changed.
"""
from __future__ import annotations

from math import prod
import json
from pathlib import Path

from deterministic_scheduling_core.adaptive_repair_experiment import build_case as build_adaptive_case
from deterministic_scheduling_core.project.model import ExecutionMethod, WorkPackage
from deterministic_scheduling_core.project.planning_workspace import validate as validate_workspace
from deterministic_scheduling_core.project.work_method_time import (
    WorkMethodTimeProject,
    from_document,
    input_hash,
    materialise,
    to_document,
)
from deterministic_scheduling_core.scheduling.planning_workspace import _group_placements
from deterministic_scheduling_core.scheduling.work_method_time import (
    _mode_cases,
    validate_problem,
)


DECLARED_ACTIVITIES = 160
ACTIVE_ACTIVITIES = 120
WORK_PACKAGES = 12
FLEXIBLE_PACKAGES = 4
AUTHORISED_STRUCTURES = 16
CURRENT_ACTIVITY_LIMIT = 64
CURRENT_PLACEMENT_LIMIT = 20_000


def _mode_document(mode) -> dict:
    named = []
    groups = []
    for requirement in mode.requirements:
        if requirement.resource_id == "C04":
            named.append({
                "id": "CRANE",
                "pool_ids": ["C04"],
                "eligible_resource_ids": ["C04"],
            })
        else:
            groups.append({
                "group_id": f"{requirement.resource_id}_POOL",
                "demand": requirement.demand,
            })
    return {
        "id": mode.id,
        "processing_ticks": mode.duration,
        "calendar_id": "ALWAYS",
        "continuity": "SUSPENDABLE_AT_AVAILABILITY_GAPS",
        "requirements": named,
        "group_requirements": groups,
    }


def build_professional_projection() -> WorkMethodTimeProject:
    """Translate the existing professional-shaped fixture without dropping semantics."""
    case, baseline, _ = build_adaptive_case()
    not_before = dict(baseline.not_before)

    activities = []
    packages = []
    for package in case.packages:
        methods = []
        for method in package.methods:
            ids = []
            for activity in method.activities:
                ids.append(activity.id)
                row = {
                    "id": activity.id,
                    "name": activity.name,
                    "modes": [_mode_document(mode) for mode in activity.modes],
                }
                if activity.predecessors:
                    row["predecessors"] = list(activity.predecessors)
                if activity.id in not_before:
                    row["not_before"] = not_before[activity.id]
                if activity.latest_finish is not None:
                    row["latest_finish"] = activity.latest_finish
                if activity.exclusion_groups:
                    row["exclusion_groups"] = list(activity.exclusion_groups)
                activities.append(row)
            methods.append(
                ExecutionMethod(
                    method.id,
                    method.name,
                    tuple(ids),
                    method.completion_id,
                )
            )
        packages.append(
            WorkPackage(
                package.id,
                package.name,
                tuple(methods),
                package.predecessors,
            )
        )

    capacities = {resource.id: resource.capacity for resource in case.resources}
    project = {
        "id": "professional-shape-160",
        "name": "Professional-shaped converged native challenge",
        "horizon_ticks": 96,
        "calendars": [{"id": "ALWAYS", "daily_windows": [[0, 48]]}],
        "resources": [{
            "id": "C04",
            "capabilities": ["C04"],
            "calendar_id": "ALWAYS",
        }],
        "resource_groups": [
            {
                "id": "MECH_POOL",
                "name": "Mechanical crew pool",
                "capacity": capacities["MECH"],
                "calendar_id": "ALWAYS",
                "disjoint": True,
                "interchangeable": True,
            },
            {
                "id": "ELEC_POOL",
                "name": "Electrical crew pool",
                "capacity": capacities["ELEC"],
                "calendar_id": "ALWAYS",
                "disjoint": True,
                "interchangeable": True,
            },
            {
                "id": "QA_POOL",
                "name": "Inspection pool",
                "capacity": capacities["QA"],
                "calendar_id": "ALWAYS",
                "disjoint": True,
                "interchangeable": True,
            },
        ],
        "activities": activities,
        "objective_activity_id": "F4",
        "pool_riggers": False,
    }
    return WorkMethodTimeProject(project, tuple(packages))


def _selected_standard_methods(problem: WorkMethodTimeProject) -> dict[str, str]:
    return {package.id: package.methods[0].id for package in problem.work_packages}


def _unsupported_activity_fields(problem: WorkMethodTimeProject) -> list[str]:
    supported = {"id", "name", "modes", "predecessors", "not_before", "exclusion_groups", "latest_finish"}
    return sorted({
        field
        for activity in problem.project["activities"]
        for field in activity
        if field not in supported
    })


def _diagnostic_placement_count(problem: WorkMethodTimeProject) -> tuple[int, int]:
    """Count generated and deadline-eligible placements without solving/admission."""
    environment, specs = _mode_cases(problem)
    raw = eligible = 0
    for activity in problem.project["activities"]:
        for mode in activity["modes"]:
            placements = _group_placements(
                environment,
                specs[activity["id"], mode["id"]],
                "B",
            )
            raw += len(placements)
            eligible += sum(p.finish <= activity.get("latest_finish", environment.horizon) for p in placements)
    return raw, eligible


def run_challenge() -> dict:
    problem = build_professional_projection()
    source_hash = input_hash(problem)
    round_trip = from_document(to_document(problem))
    methods = _selected_standard_methods(problem)

    authoritative_failure = None
    try:
        validate_problem(problem)
    except ValueError as exc:
        authoritative_failure = {
            "class": (
                "ADMISSION_BOUND"
                if "1..64 declared activities" in str(exc)
                else "OTHER_VALIDATION_FAILURE"
            ),
            "message": str(exc),
        }

    projection_failure = None
    projection = materialise(problem, methods)
    try:
        validate_workspace(projection, allow_future_constraints=True)
    except ValueError as exc:
        projection_failure = {
            "class": (
                "UNSUPPORTED_ACTIVITY_SEMANTICS"
                if "unsupported activity fields" in str(exc)
                else "OTHER_PROJECTION_FAILURE"
            ),
            "message": str(exc),
        }

    placement_counts = _diagnostic_placement_count(problem) if projection_failure is None else None
    placement_count = placement_counts[1] if placement_counts else None
    stage_count_if_admitted = (
        2
        + len(problem.work_packages)
        + len(problem.project["activities"])
        + len(problem.project["activities"])
    )

    authorised_structures = prod(len(package.methods) for package in problem.work_packages)
    shape = {
        "declared_activities": len(problem.project["activities"]),
        "selected_active_activities": len(projection["project"]["activities"]),
        "work_packages": len(problem.work_packages),
        "flexible_packages": sum(len(package.methods) > 1 for package in problem.work_packages),
        "authorised_structures": authorised_structures,
        "unsupported_activity_fields": _unsupported_activity_fields(problem),
    }

    result = {
        "milestone": "professional-shape-160-classification-v0",
        "shape": shape,
        "portable_round_trip": to_document(round_trip) == to_document(problem),
        "authoritative_first_failure": authoritative_failure,
        "selected_projection_failure": projection_failure,
        "faithful_projection_valid": projection_failure is None,
        "diagnostic_faithful_projection": {
            "projection_valid": projection_failure is None,
            "projection_error": projection_failure["message"] if projection_failure else None,
            "raw_generated_placements": placement_counts[0] if placement_counts else None,
            "placement_alternatives": placement_count,
            "placement_limit": CURRENT_PLACEMENT_LIMIT,
            "placement_limit_would_be_exceeded": (
                placement_count is not None and placement_count > CURRENT_PLACEMENT_LIMIT
            ),
            "lexicographic_stage_count_if_admitted": stage_count_if_admitted,
        },
        "source_unchanged": input_hash(problem) == source_hash,
        "classification": {
            "first_authoritative_barrier": "ADMISSION_BOUND",
            "semantic_projection_barrier": None,
            "next_action": (
                "The faithful selected projection accepts workface and protected latest-finish fields. "
                "Keep the 64-activity admission guard; investigate placement generation and "
                "global proof/model construction under authoritative batching before "
                "considering scale admission. The 334-stage estimate describes the "
                "retained sequential oracle, not the authoritative batched path."
            ),
        },
    }

    result["evidence_valid"] = all((
        shape["declared_activities"] == DECLARED_ACTIVITIES,
        shape["selected_active_activities"] == ACTIVE_ACTIVITIES,
        shape["work_packages"] == WORK_PACKAGES,
        shape["flexible_packages"] == FLEXIBLE_PACKAGES,
        shape["authorised_structures"] == AUTHORISED_STRUCTURES,
        shape["unsupported_activity_fields"] == [],
        authoritative_failure is not None
        and authoritative_failure["class"] == "ADMISSION_BOUND",
        projection_failure is None,
        result["diagnostic_faithful_projection"]["projection_valid"],
        result["diagnostic_faithful_projection"]["placement_limit_would_be_exceeded"],
        result["portable_round_trip"],
        result["source_unchanged"],
    ))
    result["boundary"] = (
        "classification only; production admission and scheduling semantics are unchanged"
    )
    return result


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    result = run_challenge()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    print("PROFESSIONAL-SHAPE 160/120 CLASSIFICATION")
    print(json.dumps(result["shape"], sort_keys=True))
    print("authoritative:", json.dumps(result["authoritative_first_failure"], sort_keys=True))
    print("projection:", json.dumps(result["selected_projection_failure"], sort_keys=True))
    print(
        "diagnostic:",
        json.dumps(result["diagnostic_faithful_projection"], sort_keys=True),
    )
    print("next:", result["classification"]["next_action"])
    print(result["boundary"])
    if not result["evidence_valid"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
