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
    work_package_id: str | None = None
    method_id: str | None = None


@dataclass(frozen=True, slots=True)
class ScheduleResult:
    project: Project
    entries: tuple[ScheduledActivity, ...]
    objective_finish: int
    makespan: int
    total_start_movement: int
    solver_status: str
    selected_methods: tuple[tuple[str, str], ...] = ()

    @property
    def by_id(self) -> dict[str, ScheduledActivity]:
        return {entry.activity_id: entry for entry in self.entries}

    @property
    def methods_by_package(self) -> dict[str, str]:
        return dict(self.selected_methods)


@dataclass(frozen=True, slots=True)
class CapacityConflict:
    resource_id: str
    resource_name: str
    start: int
    finish: int
    demand: int
    capacity: int
    activity_ids: tuple[str, ...]


def _structural_membership(project: Project) -> dict[str, tuple[str, str]]:
    membership: dict[str, tuple[str, str]] = {}
    for package in project.work_packages:
        for method in package.methods:
            for activity_id in method.activity_ids:
                if activity_id in membership:
                    previous = membership[activity_id]
                    raise SchedulingError(
                        f"{activity_id}: structural activity belongs to both "
                        f"{previous[0]}/{previous[1]} and {package.id}/{method.id}"
                    )
                membership[activity_id] = (package.id, method.id)
    return membership


def _method_roots(project: Project, activity_ids: tuple[str, ...]) -> tuple[str, ...]:
    ids = set(activity_ids)
    activities = project.activity_by_id
    return tuple(
        activity_id
        for activity_id in activity_ids
        if not (set(activities[activity_id].predecessors) & ids)
    )


def _validate_package_graph(project: Project) -> None:
    package_ids = [package.id for package in project.work_packages]
    if len(package_ids) != len(set(package_ids)):
        raise SchedulingError("native project contains duplicate work-package IDs")
    package_id_set = set(package_ids)
    pending: dict[str, set[str]] = {}
    for package in project.work_packages:
        if not package.methods:
            raise SchedulingError(f"{package.id}: work package has no authorised methods")
        unknown = set(package.predecessors) - package_id_set
        if unknown:
            raise SchedulingError(
                f"{package.id}: unknown predecessor work packages {sorted(unknown)}"
            )
        if package.id in package.predecessors:
            raise SchedulingError(f"{package.id}: work package cannot precede itself")
        pending[package.id] = set(package.predecessors)

        method_ids = [method.id for method in package.methods]
        if len(method_ids) != len(set(method_ids)):
            raise SchedulingError(f"{package.id}: duplicate execution-method IDs")
        for method in package.methods:
            if not method.activity_ids:
                raise SchedulingError(
                    f"{package.id}/{method.id}: execution method has no activities"
                )
            if len(method.activity_ids) != len(set(method.activity_ids)):
                raise SchedulingError(
                    f"{package.id}/{method.id}: execution method repeats an activity"
                )
            if method.completion_activity_id not in method.activity_ids:
                raise SchedulingError(
                    f"{package.id}/{method.id}: completion activity is not in the method"
                )

    while pending:
        ready = {key for key, predecessors in pending.items() if not predecessors}
        if not ready:
            raise SchedulingError("work-package predecessor cycle")
        pending = {
            key: predecessors - ready
            for key, predecessors in pending.items()
            if key not in ready
        }


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

    _validate_package_graph(project)
    membership = _structural_membership(project)
    structural_ids = set(membership)
    fixed_ids = set(activity_ids) - structural_ids
    for activity_id in structural_ids:
        if activity_id not in activities:
            raise SchedulingError(f"{activity_id}: work method references an unknown activity")

    for package in project.work_packages:
        frozen_methods = {
            method.id
            for method in package.methods
            if any(
                activities[activity_id].frozen_start is not None
                or activities[activity_id].frozen_mode_id is not None
                for activity_id in method.activity_ids
            )
        }
        if len(frozen_methods) > 1:
            raise SchedulingError(
                f"{package.id}: frozen activities require competing execution methods"
            )
        for method in package.methods:
            method_ids = set(method.activity_ids)
            ancestors: set[str] = set()
            frontier = [method.completion_activity_id]
            while frontier:
                current = frontier.pop()
                if current in ancestors:
                    continue
                ancestors.add(current)
                frontier.extend(
                    predecessor
                    for predecessor in activities[current].predecessors
                    if predecessor in method_ids
                )
            if ancestors != method_ids:
                missing = sorted(method_ids - ancestors)
                raise SchedulingError(
                    f"{package.id}/{method.id}: activities do not feed method completion: {missing}"
                )

    if project.objective_activity_id in membership:
        package_id, _ = membership[project.objective_activity_id]
        package = project.work_package_by_id[package_id]
        if len(package.methods) != 1:
            raise SchedulingError(
                "objective activity cannot belong to an optional execution method"
            )

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
        if activity.id in structural_ids and (
            activity.planned_start is not None or activity.planned_mode_id is not None
        ):
            raise SchedulingError(
                f"{activity.id}: planned reference coordinates on structural alternatives "
                "need an explicit selected reference method; unsupported in this bounded slice"
            )
        if activity.id in fixed_ids:
            structural_predecessors = set(activity.predecessors) & structural_ids
            if structural_predecessors:
                raise SchedulingError(
                    f"{activity.id}: fixed activity cannot depend directly on structural "
                    f"alternatives {sorted(structural_predecessors)}"
                )
        else:
            package_id, method_id = membership[activity.id]
            method = project.work_package_by_id[package_id].method_by_id[method_id]
            allowed = set(method.activity_ids) | fixed_ids
            invalid = set(activity.predecessors) - allowed
            if invalid:
                raise SchedulingError(
                    f"{activity.id}: structural predecessor {sorted(invalid)} crosses "
                    "execution-method/package boundaries; use work-package predecessors"
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

    pending = {a.id: set(a.predecessors) for a in project.activities}
    while pending:
        ready = {key for key, predecessors in pending.items() if not predecessors}
        if not ready:
            raise SchedulingError("activity predecessor cycle")
        pending = {
            key: predecessors - ready
            for key, predecessors in pending.items()
            if key not in ready
        }


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
    membership = _structural_membership(project)
    if any(
        project.activity_by_id[activity_id].planned_start is not None
        for activity_id in membership
    ):
        raise SchedulingError(
            "planned source-capacity inspection of structural alternatives needs "
            "an explicit selected reference method; unsupported in this bounded slice"
        )

    conflicts: list[CapacityConflict] = []
    for resource in project.resources:
        relevant: list[tuple[int, int, int, str]] = []
        for activity in project.activities:
            if activity.id in membership:
                continue
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
    """Schedule the PM-Software native model without any external-format dependency.

    Fixed activity networks remain the empty-work_packages special case. When
    work packages are present, the engine selects exactly one authorised
    structural execution method per package and then jointly selects activity
    modes and timing for the active structure.
    """

    validate_project(project)
    horizon = _horizon(project)
    model = cp_model.CpModel()
    starts: dict[str, cp_model.IntVar] = {}
    ends: dict[str, cp_model.IntVar] = {}
    presence: dict[tuple[str, str], cp_model.BoolVar] = {}
    intervals: dict[tuple[str, str], cp_model.IntervalVar] = {}

    membership = _structural_membership(project)
    method_presence: dict[tuple[str, str], cp_model.BoolVar] = {}
    activity_presence: dict[str, cp_model.BoolVar] = {}
    package_finish: dict[str, cp_model.IntVar] = {}

    for package in project.work_packages:
        literals: list[cp_model.BoolVar] = []
        package_finish[package.id] = model.new_int_var(0, horizon, f"finish_package_{package.id}")
        frozen_method: str | None = None
        for method in package.methods:
            literal = model.new_bool_var(f"method_{package.id}_{method.id}")
            method_presence[(package.id, method.id)] = literal
            literals.append(literal)
            if any(
                project.activity_by_id[activity_id].frozen_start is not None
                or project.activity_by_id[activity_id].frozen_mode_id is not None
                for activity_id in method.activity_ids
            ):
                frozen_method = method.id
        model.add_exactly_one(literals)
        if frozen_method is not None:
            model.add(method_presence[(package.id, frozen_method)] == 1)

    for activity in project.activities:
        structural = activity.id in membership
        active = (
            method_presence[membership[activity.id]]
            if structural
            else None
        )
        if active is not None:
            activity_presence[activity.id] = active
            start = model.new_int_var(0, horizon, f"start_{activity.id}")
            model.add(start >= activity.not_before).only_enforce_if(active)
            model.add(start == 0).only_enforce_if(active.Not())
        else:
            start = model.new_int_var(activity.not_before, horizon, f"start_{activity.id}")
        end = model.new_int_var(0, horizon, f"end_{activity.id}")
        if active is not None:
            model.add(end == 0).only_enforce_if(active.Not())

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

        if active is None:
            model.add_exactly_one(selected_modes)
        else:
            model.add(sum(selected_modes) == active)

        if activity.latest_finish is not None:
            constraint = model.add(end <= activity.latest_finish)
            if active is not None:
                constraint.only_enforce_if(active)
        if activity.frozen_start is not None:
            constraint = model.add(start == activity.frozen_start)
            if active is not None:
                constraint.only_enforce_if(active)
        if activity.frozen_mode_id is not None:
            for mode in activity.modes:
                constraint = model.add(
                    presence[(activity.id, mode.id)]
                    == int(mode.id == activity.frozen_mode_id)
                )
                if active is not None:
                    constraint.only_enforce_if(active)

    for package in project.work_packages:
        for method in package.methods:
            literal = method_presence[(package.id, method.id)]
            completion_id = method.completion_activity_id
            model.add(package_finish[package.id] == ends[completion_id]).only_enforce_if(literal)
            for root in _method_roots(project, method.activity_ids):
                for predecessor_package_id in package.predecessors:
                    model.add(
                        starts[root] >= package_finish[predecessor_package_id]
                    ).only_enforce_if(literal)

    for activity in project.activities:
        active = activity_presence.get(activity.id)
        for predecessor_id in activity.predecessors:
            constraint = model.add(starts[activity.id] >= ends[predecessor_id])
            if active is not None:
                constraint.only_enforce_if(active)

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
        active = activity_presence.get(activity.id)
        movement = model.new_int_var(0, horizon, f"movement_{activity.id}")
        if active is None:
            model.add_abs_equality(movement, starts[activity.id] - activity.planned_start)
        else:
            difference = model.new_int_var(-horizon, horizon, f"movement_delta_{activity.id}")
            model.add(difference == starts[activity.id] - activity.planned_start).only_enforce_if(active)
            model.add(difference == 0).only_enforce_if(active.Not())
            model.add_abs_equality(movement, difference)
        movement_vars.append(movement)

    movement_bound = len(movement_vars) * horizon
    total_movement = model.new_int_var(0, movement_bound, "total_start_movement")
    if movement_vars:
        model.add(total_movement == sum(movement_vars))
    else:
        model.add(total_movement == 0)

    tertiary = sum(starts.values())
    tertiary_bound = len(project.activities) * horizon

    # Encode the declared method-index vector uniquely so an otherwise exact tie
    # has one canonical structural result. Earlier packages are more significant.
    method_tie_terms = []
    method_tie_bound = 0
    radix = 1
    for package in reversed(project.work_packages):
        for method_index, method in enumerate(package.methods):
            method_tie_terms.append(
                method_index * radix * method_presence[(package.id, method.id)]
            )
        method_tie_bound += (len(package.methods) - 1) * radix
        radix *= max(len(package.methods), 1)
    method_tie = sum(method_tie_terms) if method_tie_terms else 0

    method_weight = method_tie_bound + 1
    tertiary_weight = method_weight
    movement_weight = (tertiary_bound + 1) * tertiary_weight
    finish_weight = (movement_bound + 1) * movement_weight
    model.minimize(
        objective_finish * finish_weight
        + total_movement * movement_weight
        + tertiary * tertiary_weight
        + method_tie
    )

    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    status = solver.solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise SchedulingError(
            f"native project has no feasible schedule: {solver.status_name(status)}"
        )

    selected_methods = tuple(
        (package.id, method.id)
        for package in project.work_packages
        for method in package.methods
        if solver.value(method_presence[(package.id, method.id)])
    )

    entries: list[ScheduledActivity] = []
    for activity in project.activities:
        active = activity_presence.get(activity.id)
        if active is not None and not solver.value(active):
            continue
        selected_mode = next(
            mode
            for mode in activity.modes
            if solver.value(presence[(activity.id, mode.id)])
        )
        package_id = None
        method_id = None
        if activity.id in membership:
            package_id, method_id = membership[activity.id]
        entries.append(
            ScheduledActivity(
                activity_id=activity.id,
                activity_name=activity.name,
                mode_id=selected_mode.id,
                start=solver.value(starts[activity.id]),
                finish=solver.value(ends[activity.id]),
                work_package_id=package_id,
                method_id=method_id,
            )
        )

    return ScheduleResult(
        project=project,
        entries=tuple(entries),
        objective_finish=solver.value(objective_finish),
        makespan=solver.value(makespan),
        total_start_movement=solver.value(total_movement),
        solver_status=solver.status_name(status),
        selected_methods=selected_methods,
    )
