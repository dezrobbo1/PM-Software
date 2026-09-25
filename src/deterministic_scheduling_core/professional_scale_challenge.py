"""Classify the first barriers in the earlier 160/120 professional-shaped fixture.

This challenge adapts the already-retained adaptive-repair fixture into the
current WorkMethodTimeProject vocabulary without changing production admission
or scheduling semantics. It deliberately asks where the converged path fails
before any architecture is changed.
"""
from __future__ import annotations

from copy import deepcopy
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
    supported = {"id", "name", "modes", "predecessors", "not_before"}
    return sorted({
        field
        for activity in problem.project["activities"]
        for field in activity
        if field not in supported
    })


def _strip_unsupported_activity_fields(problem: WorkMethodTimeProject) -> WorkMethodTimeProject:
    project = deepcopy(problem.project)
    for activity in project["activities"]:
        activity.pop("latest_finish", None)
        activity.pop("exclusion_groups", None)
    return WorkMethodTimeProject(project, problem.work_packages, problem.reports)


def _diagnostic_placement_count(problem: WorkMethodTimeProject) -> int:
    """Count current placement alternatives without solving or changing admission."""
    environment, specs = _mode_cases(problem)
    count = 0
    for activity in problem.project["activities"]:
        for mode in activity["modes"]:
            count += len(_group_placements(
                environment,
                specs[activity["id"], mode["id"]],
                "B",
            ))
    return count


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
        validate_workspace(projection)
    except ValueError as exc:
        projection_failure = {
            "class": (
                "UNSUPPORTED_ACTIVITY_SEMANTICS"
                if "unsupported activity fields" in str(exc)
                else "OTHER_PROJECTION_FAILURE"
            ),
            "message": str(exc),
        }

    stripped = _strip_unsupported_activity_fields(problem)
    stripped_projection = materialise(stripped, methods)
    stripped_projection_valid = True
    stripped_projection_error = None
    try:
        validate_workspace(stripped_projection)
    except ValueError as exc:
        stripped_projection_valid = False
        stripped_projection_error = str(exc)

    placement_count = (
        _diagnostic_placement_count(stripped)
        if stripped_projection_valid
        else None
    )
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
        "diagnostic_without_unsupported_semantics": {
            "projection_valid": stripped_projection_valid,
            "projection_error": stripped_projection_error,
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
            "semantic_projection_barrier": "EXCLUSION_GROUPS_AND_LATEST_FINISH_UNSUPPORTED",
            "next_action": (
                "Do not raise the 64-activity limit yet. First compose workface/exclusion "
                "constraints and protected latest-finish semantics into the converged "
                "Work-Method/productive-time path on a smaller focused fixture; then rerun "
                "this 160/120 challenge and classify placement/canonicalisation limits."
            ),
        },
    }

    result["evidence_valid"] = all((
        shape["declared_activities"] == DECLARED_ACTIVITIES,
        shape["selected_active_activities"] == ACTIVE_ACTIVITIES,
        shape["work_packages"] == WORK_PACKAGES,
        shape["flexible_packages"] == FLEXIBLE_PACKAGES,
        shape["authorised_structures"] == AUTHORISED_STRUCTURES,
        shape["unsupported_activity_fields"] == ["exclusion_groups", "latest_finish"],
        authoritative_failure is not None
        and authoritative_failure["class"] == "ADMISSION_BOUND",
        projection_failure is not None
        and projection_failure["class"] == "UNSUPPORTED_ACTIVITY_SEMANTICS",
        stripped_projection_valid,
        result["diagnostic_without_unsupported_semantics"]["placement_limit_would_be_exceeded"],
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
        json.dumps(result["diagnostic_without_unsupported_semantics"], sort_keys=True),
    )
    print("next:", result["classification"]["next_action"])
    print(result["boundary"])
    if not result["evidence_valid"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
