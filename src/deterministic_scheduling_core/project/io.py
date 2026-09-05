from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from deterministic_scheduling_core.errors import SchedulingError
from deterministic_scheduling_core.project.model import (
    Activity,
    ExecutionMode,
    Project,
    Resource,
    ResourceRequirement,
)

FORMAT = "pm-native-project-v0"


def project_to_document(project: Project) -> dict[str, Any]:
    return {
        "format": FORMAT,
        "id": project.id,
        "name": project.name,
        "time_unit": project.time_unit,
        "objective_activity_id": project.objective_activity_id,
        "resources": [
            {"id": resource.id, "name": resource.name, "capacity": resource.capacity}
            for resource in project.resources
        ],
        "activities": [
            {
                "id": activity.id,
                "name": activity.name,
                "kind": activity.kind,
                "predecessors": list(activity.predecessors),
                "not_before": activity.not_before,
                "latest_finish": activity.latest_finish,
                "exclusion_groups": list(activity.exclusion_groups),
                "planned_start": activity.planned_start,
                "planned_mode_id": activity.planned_mode_id,
                "frozen_start": activity.frozen_start,
                "frozen_mode_id": activity.frozen_mode_id,
                "modes": [
                    {
                        "id": mode.id,
                        "name": mode.name,
                        "duration": mode.duration,
                        "requirements": [
                            {
                                "resource_id": requirement.resource_id,
                                "demand": requirement.demand,
                            }
                            for requirement in mode.requirements
                        ],
                    }
                    for mode in activity.modes
                ],
            }
            for activity in project.activities
        ],
    }


def _project_from_document(document: dict[str, Any]) -> Project:
    if document.get("format") != FORMAT:
        raise SchedulingError(f"expected native project format {FORMAT!r}")
    try:
        resources = tuple(
            Resource(
                id=str(item["id"]),
                name=str(item.get("name", item["id"])),
                capacity=int(item.get("capacity", 1)),
            )
            for item in document.get("resources", [])
        )
        activities = tuple(
            Activity(
                id=str(item["id"]),
                name=str(item["name"]),
                kind=str(item.get("kind", "task")),
                predecessors=tuple(str(value) for value in item.get("predecessors", [])),
                not_before=int(item.get("not_before", 0)),
                latest_finish=(
                    None
                    if item.get("latest_finish") is None
                    else int(item["latest_finish"])
                ),
                exclusion_groups=tuple(
                    str(value) for value in item.get("exclusion_groups", [])
                ),
                planned_start=(
                    None
                    if item.get("planned_start") is None
                    else int(item["planned_start"])
                ),
                planned_mode_id=(
                    None
                    if item.get("planned_mode_id") is None
                    else str(item["planned_mode_id"])
                ),
                frozen_start=(
                    None
                    if item.get("frozen_start") is None
                    else int(item["frozen_start"])
                ),
                frozen_mode_id=(
                    None
                    if item.get("frozen_mode_id") is None
                    else str(item["frozen_mode_id"])
                ),
                modes=tuple(
                    ExecutionMode(
                        id=str(mode["id"]),
                        name=(None if mode.get("name") is None else str(mode["name"])),
                        duration=int(mode["duration"]),
                        requirements=tuple(
                            ResourceRequirement(
                                resource_id=str(requirement["resource_id"]),
                                demand=int(requirement.get("demand", 1)),
                            )
                            for requirement in mode.get("requirements", [])
                        ),
                    )
                    for mode in item["modes"]
                ),
            )
            for item in document["activities"]
        )
        return Project(
            id=str(document["id"]),
            name=str(document["name"]),
            time_unit=str(document.get("time_unit", "hour")),
            objective_activity_id=(
                None
                if document.get("objective_activity_id") is None
                else str(document["objective_activity_id"])
            ),
            resources=resources,
            activities=activities,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise SchedulingError(f"invalid native project document: {exc}") from exc


def save_project(project: Project, path: str | Path) -> Path:
    target = Path(path)
    target.write_text(
        json.dumps(project_to_document(project), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target


def load_project(path: str | Path) -> Project:
    source = Path(path)
    try:
        document = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SchedulingError(f"cannot read native project {source}: {exc}") from exc
    if not isinstance(document, dict):
        raise SchedulingError("native project root must be an object")
    return _project_from_document(document)
