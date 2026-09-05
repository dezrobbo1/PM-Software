from __future__ import annotations

from dataclasses import dataclass

from ortools.sat.python import cp_model

from deterministic_scheduling_core.errors import SchedulingError
from deterministic_scheduling_core.project.model import Activity, ExecutionMode, Project


@dataclass(frozen=True, slots=True)
class ScheduledActivity:
    activity_id: str
    activity_name: str
    mode_id: str
    start: int
    finish: int


@dataclass(frozen=True, slots=True)
class ScheduleResult:
    project: Project
    entries: tuple[ScheduledActivity, ...]
    objective_finish: int
    makespan: int
    total_start_movement: int
    solver_status: str

    @property
    def by_id(self) -> dict[str, ScheduledActivity]:
        return {entry.activity_id: entry for entry in self.entries}


@dataclass(frozen=True, slots=True)
class CapacityConflict:
    resource_id: str
    resource_name: str
    start: int
    finish: int
    demand: int
    capacity: int
    activity_ids: tuple[str, ...]


def validate_project(project: Project) -> None:
    activity_ids = [activity.id for activity in project.activities]
    if not activity_ids:
        raise SchedulingError("native project has no activities")
    if len(activity_ids) != len(set(activity_ids)):
        raise SchedulingError("native project contains duplicate activity IDs")
    resource_ids = [resource.id for resource in project.resources]
    if len(resource_ids) != len(set(resource_ids)):
        raise SchedulingError("native project contains duplicate resource IDs")
    resources = project.resource_by_id
    activities = project.activity_by_id
    if project.objective_activity_id is not None and project.objective_activity_id not in activities:
        raise SchedulingError("objective activity is not present in the project")

    for resource in project.resources:
        if resource.capacity <= 0:
            raise SchedulingError(f"{resource.id}: resource capacity must be positive")

    for activity in project.activities:
        if not activity.modes:
            raise SchedulingError(f"{activity.id}: activity has no execution modes")
        if activity.kind not in {"task", "milestone"}:
            raise SchedulingError(f"{activity.id}: unsupported activity kind {activity.kind!r}")
        mode_ids = [mode.id for mode in activity.modes]
        if len(mode_ids) != len(set(mode_ids)):
            raise SchedulingError(f"{activity.id}: duplicate execution-mode IDs")
        if activity.not_before < 0:
            raise SchedulingError(f"{activity.id}: not_before must be non-negative")
        if activity.latest_finish is not None and activity.latest_finish < activity.not_before:
            raise SchedulingError(f"{activity.id}: latest_finish precedes not_before")
        if activity.frozen_start is not None and activity.frozen_start < activity.not_before:
            raise SchedulingError(f"{activity.id}: frozen_start precedes not_before")
        unknown_predecessors = set(activity.predecessors) - set(activity_ids)
        if unknown_predecessors:
            raise SchedulingError(
                f"{activity.id}: unknown predecessors {sorted(unknown_predecessors)}"
            )
        if activity.planned_mode_id is not None and activity.planned_mode_id not in activity.mode_by_id:
            raise SchedulingError(f"{activity.id}: planned mode is not defined")
        if activity.frozen_mode_id is not None and activity.frozen_mode_id not in activity.mode_by_id:
            raise SchedulingError(f"{activity.id}: frozen mode is not defined")
        for mode in activity.modes:
            if mode.duration < 0:
                raise SchedulingError(f"{activity.id}/{mode.id}: duration must be non-negative")
            if activity.kind == "milestone" and mode.duration != 0:
                raise SchedulingError(f"{activity.id}: milestone duration must be zero")
            for requirement in mode.requirements:
                resource = resources.get(requirement.resource_id)
                if resource is None:
                    raise SchedulingError(
                        f"{activity.id}/{mode.id}: unknown resource {requirement.resource_id}"
                    )
                if requirement.demand <= 0 or requirement.demand > resource.capacity:
                    raise SchedulingError(
                        f"{activity.id}/{mode.id}: invalid demand {requirement.demand} "
                        f"for {requirement.resource_id}"
                    )


def _planned_mode(activity: Activity) -> ExecutionMode | None:
    if activity.planned_start is None:
        return None
    if activity.planned_mode_id is not None:
        return activity.mode_by_id[activity.planned_mode_id]
    if len(activity.modes) == 1:
        return activity.modes[0]
    return None


def source_capacity_conflicts(project: Project) -> tuple[CapacityConflict, ...]:
    """Inspect the project's planned coordinates without changing them."""

    validate_project(project)
    conflicts: list[CapacityConflict] = []
    for resource in project.resources:
        relevant: list[tuple[int, int, int, str]] = []
        for activity in project.activities:
            mode = _planned_mode(activity)
            if mode is None or activity.planned_start is None or mode.duration == 0:
                continue
            demand = sum(
                requirement.demand
                for requirement in mode.requirements
                if requirement.resource_id == resource.id
            )
            if demand:
                relevant.append(
                    (
                        activity.planned_start,
                        activity.planned_start + mode.duration,
                        demand,
                        activity.id,
                    )
                )
        if not relevant:
            continue
        points = sorted({point for start, finish, _, _ in relevant for point in (start, finish)})
        open_conflict: CapacityConflict | None = None
        for left, right in zip(points, points[1:]):
            active = [
                (demand, activity_id)
                for start, finish, demand, activity_id in relevant
                if start < right and finish > left
            ]
            demand = sum(item[0] for item in active)
            if demand > resource.capacity:
                ids = tuple(sorted(item[1] for item in active))
                if (
                    open_conflict is not None
                    and open_conflict.finish == left
                    and open_conflict.demand == demand
                    and open_conflict.activity_ids == ids
                ):
                    open_conflict = CapacityConflict(
                        resource.id,
                        resource.name,
                        open_conflict.start,
                        right,
                        demand,
                        resource.capacity,
                        ids,
                    )
                    conflicts[-1] = open_conflict
                else:
                    open_conflict = CapacityConflict(
                        resource.id,
                        resource.name,
                        left,
                        right,
                        demand,
                        resource.capacity,
                        ids,
                    )
                    conflicts.append(open_conflict)
            else:
                open_conflict = None
    return tuple(conflicts)


def _horizon(project: Project) -> int:
    max_anchor = 0
    total_duration = 0
    for activity in project.activities:
        max_anchor = max(
            max_anchor,
            activity.not_before,
            activity.planned_start or 0,
            activity.frozen_start or 0,
            activity.latest_finish or 0,
        )
        total_duration += max(mode.duration for mode in activity.modes)
    return max_anchor + max(total_duration, 1) + 100


def schedule_project(project: Project) -> ScheduleResult:
    """Schedule the PM-Software native model without any external-format dependency."""

    validate_project(project)
    horizon = _horizon(project)
    model = cp_model.CpModel()
    starts: dict[str, cp_model.IntVar] = {}
    ends: dict[str, cp_model.IntVar] = {}
    presence: dict[tuple[str, str], cp_model.BoolVar] = {}
    intervals: dict[tuple[str, str], cp_model.IntervalVar] = {}

    for activity in project.activities:
        start = model.new_int_var(activity.not_before, horizon, f"start_{activity.id}")
        end = model.new_int_var(0, horizon, f"end_{activity.id}")
        starts[activity.id] = start
        ends[activity.id] = end
        selected_modes: list[cp_model.BoolVar] = []
        for mode in activity.modes:
            selected = model.new_bool_var(f"select_{activity.id}_{mode.id}")
            presence[(activity.id, mode.id)] = selected
            intervals[(activity.id, mode.id)] = model.new_optional_interval_var(
                start,
                mode.duration,
                end,
                selected,
                f"interval_{activity.id}_{mode.id}",
            )
            selected_modes.append(selected)
        model.add_exactly_one(selected_modes)
        if activity.latest_finish is not None:
            model.add(end <= activity.latest_finish)
        if activity.frozen_start is not None:
            model.add(start == activity.frozen_start)
        if activity.frozen_mode_id is not None:
            for mode in activity.modes:
                model.add(
                    presence[(activity.id, mode.id)]
                    == int(mode.id == activity.frozen_mode_id)
                )

    for activity in project.activities:
        for predecessor_id in activity.predecessors:
            model.add(starts[activity.id] >= ends[predecessor_id])

    for resource in project.resources:
        resource_intervals: list[cp_model.IntervalVar] = []
        demands: list[int] = []
        for activity in project.activities:
            for mode in activity.modes:
                demand = sum(
                    requirement.demand
                    for requirement in mode.requirements
                    if requirement.resource_id == resource.id
                )
                if demand:
                    resource_intervals.append(intervals[(activity.id, mode.id)])
                    demands.append(demand)
        if resource_intervals:
            model.add_cumulative(resource_intervals, demands, resource.capacity)

    groups: dict[str, list[cp_model.IntervalVar]] = {}
    for activity in project.activities:
        for group_id in activity.exclusion_groups:
            groups.setdefault(group_id, []).extend(
                intervals[(activity.id, mode.id)] for mode in activity.modes
            )
    for group_intervals in groups.values():
        if len(group_intervals) > 1:
            model.add_no_overlap(group_intervals)

    makespan = model.new_int_var(0, horizon, "makespan")
    model.add_max_equality(makespan, list(ends.values()))
    objective_finish = (
        ends[project.objective_activity_id]
        if project.objective_activity_id is not None
        else makespan
    )

    movement_vars: list[cp_model.IntVar] = []
    for activity in project.activities:
        if activity.planned_start is None or activity.frozen_start is not None:
            continue
        movement = model.new_int_var(0, horizon, f"movement_{activity.id}")
        model.add_abs_equality(movement, starts[activity.id] - activity.planned_start)
        movement_vars.append(movement)
    movement_bound = len(movement_vars) * horizon
    total_movement = model.new_int_var(0, movement_bound, "total_start_movement")
    if movement_vars:
        model.add(total_movement == sum(movement_vars))
    else:
        model.add(total_movement == 0)

    tertiary = sum(starts.values())
    tertiary_bound = len(project.activities) * horizon
    movement_weight = tertiary_bound + 1
    finish_weight = movement_bound * movement_weight + tertiary_bound + 1
    model.minimize(
        objective_finish * finish_weight
        + total_movement * movement_weight
        + tertiary
    )

    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    status = solver.solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise SchedulingError(
            f"native project has no feasible schedule: {solver.status_name(status)}"
        )

    entries: list[ScheduledActivity] = []
    for activity in project.activities:
        selected_mode = next(
            mode
            for mode in activity.modes
            if solver.value(presence[(activity.id, mode.id)])
        )
        entries.append(
            ScheduledActivity(
                activity_id=activity.id,
                activity_name=activity.name,
                mode_id=selected_mode.id,
                start=solver.value(starts[activity.id]),
                finish=solver.value(ends[activity.id]),
            )
        )

    return ScheduleResult(
        project=project,
        entries=tuple(entries),
        objective_finish=solver.value(objective_finish),
        makespan=solver.value(makespan),
        total_start_movement=solver.value(total_movement),
        solver_status=solver.status_name(status),
    )
