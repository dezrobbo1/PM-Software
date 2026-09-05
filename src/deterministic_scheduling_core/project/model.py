from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True, slots=True)
class ResourceRequirement:
    resource_id: str
    demand: int = 1


@dataclass(frozen=True, slots=True)
class ExecutionMode:
    id: str
    duration: int
    requirements: tuple[ResourceRequirement, ...] = ()
    name: str | None = None


@dataclass(frozen=True, slots=True)
class Activity:
    id: str
    name: str
    modes: tuple[ExecutionMode, ...]
    predecessors: tuple[str, ...] = ()
    not_before: int = 0
    latest_finish: int | None = None
    exclusion_groups: tuple[str, ...] = ()
    planned_start: int | None = None
    planned_mode_id: str | None = None
    frozen_start: int | None = None
    frozen_mode_id: str | None = None
    kind: str = "task"

    @property
    def mode_by_id(self) -> dict[str, ExecutionMode]:
        return {mode.id: mode for mode in self.modes}


@dataclass(frozen=True, slots=True)
class Resource:
    id: str
    name: str
    capacity: int = 1


@dataclass(frozen=True, slots=True)
class Project:
    id: str
    name: str
    activities: tuple[Activity, ...]
    resources: tuple[Resource, ...] = ()
    objective_activity_id: str | None = None
    time_unit: str = "hour"

    @property
    def activity_by_id(self) -> dict[str, Activity]:
        return {activity.id: activity for activity in self.activities}

    @property
    def resource_by_id(self) -> dict[str, Resource]:
        return {resource.id: resource for resource in self.resources}


def replace_mode_duration(
    project: Project,
    activity_id: str,
    mode_id: str,
    duration: int,
) -> Project:
    """Return a new project with one execution-mode duration changed."""

    if duration < 0:
        raise ValueError("duration must be non-negative")
    changed = False
    activities: list[Activity] = []
    for activity in project.activities:
        if activity.id != activity_id:
            activities.append(activity)
            continue
        modes: list[ExecutionMode] = []
        for mode in activity.modes:
            if mode.id == mode_id:
                modes.append(replace(mode, duration=duration))
                changed = True
            else:
                modes.append(mode)
        activities.append(replace(activity, modes=tuple(modes)))
    if not changed:
        raise KeyError(f"unknown activity/mode {activity_id}/{mode_id}")
    return replace(project, activities=tuple(activities))
