from __future__ import annotations

from dataclasses import dataclass

from ortools.sat.python import cp_model

from deterministic_scheduling_core.errors import SchedulingError


RESOURCE_IDS = ("MECH", "INSPECT", "CRANE-C04")


@dataclass(frozen=True, slots=True)
class OperationalActivity:
    id: str
    name: str
    duration: int
    predecessors: tuple[str, ...] = ()
    resources: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PermitWindow:
    activity_id: str
    earliest_start: int
    latest_finish: int
    name: str


@dataclass(frozen=True, slots=True)
class WorkfaceExclusion:
    id: str
    name: str
    activity_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ScheduledOperationalActivity:
    activity: OperationalActivity
    start: int
    finish: int


@dataclass(frozen=True, slots=True)
class OperationalScheduleResult:
    method: str
    entries: tuple[ScheduledOperationalActivity, ...]
    makespan: int
    solver_status: str

    @property
    def by_id(self) -> dict[str, ScheduledOperationalActivity]:
        return {entry.activity.id: entry for entry in self.entries}

    @property
    def sequence(self) -> tuple[str, ...]:
        return tuple(
            entry.activity.id
            for entry in sorted(
                self.entries,
                key=lambda item: (item.start, item.finish, item.activity.id),
            )
        )


@dataclass(frozen=True, slots=True)
class Gate3Comparison:
    capacity_only: OperationalScheduleResult
    operational: OperationalScheduleResult
    capacity_only_operational_errors: tuple[str, ...]


ACTIVITIES = (
    OperationalActivity("O01", "Release work area", 1),
    OperationalActivity(
        "O02",
        "Strip scaffold from exchanger workface",
        4,
        ("O01",),
    ),
    OperationalActivity(
        "O03",
        "Lift exchanger spool",
        3,
        ("O01",),
        ("CRANE-C04",),
    ),
    OperationalActivity(
        "O04",
        "Install exchanger spool",
        4,
        ("O03",),
        ("MECH",),
    ),
    OperationalActivity(
        "O05",
        "Inspect exposed line",
        3,
        ("O02",),
        ("INSPECT",),
    ),
    OperationalActivity(
        "O06",
        "Lift valve actuator",
        2,
        ("O01",),
        ("CRANE-C04",),
    ),
    OperationalActivity(
        "O07",
        "Replace valve actuator",
        4,
        ("O06",),
        ("MECH",),
    ),
    OperationalActivity(
        "O08",
        "Reconnect system",
        2,
        ("O04", "O05", "O07"),
        ("MECH",),
    ),
    OperationalActivity(
        "O09",
        "Pressure test",
        2,
        ("O08",),
        ("INSPECT",),
    ),
    OperationalActivity("O10", "Return to service", 1, ("O09",)),
)

PERMIT_WINDOWS = (
    PermitWindow(
        activity_id="O03",
        earliest_start=4,
        latest_finish=9,
        name="Exchanger heavy-lift permit/access window",
    ),
)

WORKFACE_EXCLUSIONS = (
    WorkfaceExclusion(
        id="WF-EXCHANGER",
        name="Exchanger workface occupancy",
        activity_ids=("O02", "O03"),
    ),
)


def _validate_inputs() -> None:
    ids = [activity.id for activity in ACTIVITIES]
    if len(ids) != len(set(ids)):
        raise SchedulingError("Gate 3 sample contains duplicate activity IDs")
    known_ids = set(ids)
    known_resources = set(RESOURCE_IDS)
    for activity in ACTIVITIES:
        if activity.duration <= 0:
            raise SchedulingError(f"{activity.id}: duration must be positive")
        unknown_predecessors = set(activity.predecessors) - known_ids
        if unknown_predecessors:
            raise SchedulingError(
                f"{activity.id}: unknown predecessors {sorted(unknown_predecessors)}"
            )
        unknown_resources = set(activity.resources) - known_resources
        if unknown_resources:
            raise SchedulingError(
                f"{activity.id}: unknown resources {sorted(unknown_resources)}"
            )

    for window in PERMIT_WINDOWS:
        if window.activity_id not in known_ids:
            raise SchedulingError(f"unknown permit-window activity {window.activity_id}")
        if window.earliest_start < 0 or window.latest_finish <= window.earliest_start:
            raise SchedulingError(f"{window.activity_id}: invalid permit/access window")

    for exclusion in WORKFACE_EXCLUSIONS:
        if len(exclusion.activity_ids) < 2:
            raise SchedulingError(
                f"{exclusion.id}: workface exclusion needs at least two activities"
            )
        unknown = set(exclusion.activity_ids) - known_ids
        if unknown:
            raise SchedulingError(
                f"{exclusion.id}: unknown activities {sorted(unknown)}"
            )


def _solve(*, enforce_operational_constraints: bool) -> OperationalScheduleResult:
    _validate_inputs()
    horizon = sum(activity.duration for activity in ACTIVITIES) + max(
        window.latest_finish for window in PERMIT_WINDOWS
    )
    model = cp_model.CpModel()
    starts: dict[str, cp_model.IntVar] = {}
    ends: dict[str, cp_model.IntVar] = {}
    intervals: dict[str, cp_model.IntervalVar] = {}

    for activity in ACTIVITIES:
        starts[activity.id] = model.new_int_var(0, horizon, f"start_{activity.id}")
        ends[activity.id] = model.new_int_var(0, horizon, f"end_{activity.id}")
        intervals[activity.id] = model.new_interval_var(
            starts[activity.id],
            activity.duration,
            ends[activity.id],
            f"interval_{activity.id}",
        )

    for activity in ACTIVITIES:
        for predecessor in activity.predecessors:
            model.add(starts[activity.id] >= ends[predecessor])

    for resource_id in RESOURCE_IDS:
        assigned = [
            intervals[activity.id]
            for activity in ACTIVITIES
            if resource_id in activity.resources
        ]
        if assigned:
            model.add_no_overlap(assigned)

    if enforce_operational_constraints:
        for window in PERMIT_WINDOWS:
            model.add(starts[window.activity_id] >= window.earliest_start)
            model.add(ends[window.activity_id] <= window.latest_finish)
        for exclusion in WORKFACE_EXCLUSIONS:
            model.add_no_overlap(
                [intervals[activity_id] for activity_id in exclusion.activity_ids]
            )

    makespan = model.new_int_var(0, horizon, "makespan")
    model.add_max_equality(makespan, list(ends.values()))
    makespan_weight = len(ACTIVITIES) * horizon + 1
    model.minimize(makespan * makespan_weight + sum(starts.values()))

    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    status = solver.solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise SchedulingError(
            f"Gate 3 CP-SAT did not find a feasible schedule: {status}"
        )

    entries = tuple(
        ScheduledOperationalActivity(
            activity=activity,
            start=solver.value(starts[activity.id]),
            finish=solver.value(ends[activity.id]),
        )
        for activity in ACTIVITIES
    )
    result = OperationalScheduleResult(
        method=(
            "Capacity-only optimiser: precedence + named resources"
            if not enforce_operational_constraints
            else "Operational optimiser: resources + permit window + workface exclusion"
        ),
        entries=entries,
        makespan=max(entry.finish for entry in entries),
        solver_status=solver.status_name(status),
    )
    capacity_errors = capacity_feasibility_errors(result)
    if capacity_errors:
        raise SchedulingError("; ".join(capacity_errors))
    if enforce_operational_constraints:
        errors = operational_constraint_errors(result)
        if errors:
            raise SchedulingError("; ".join(errors))
    return result


def capacity_feasibility_errors(result: OperationalScheduleResult) -> tuple[str, ...]:
    actual = result.by_id
    expected = {activity.id: activity for activity in ACTIVITIES}
    errors: list[str] = []
    if set(actual) != set(expected):
        return ("scheduled activity IDs do not match the input",)

    for activity_id, activity in expected.items():
        entry = actual[activity_id]
        if entry.start < 0 or entry.finish - entry.start != activity.duration:
            errors.append(f"{activity_id}: invalid start/finish span")
        for predecessor in activity.predecessors:
            if actual[predecessor].finish > entry.start:
                errors.append(f"{predecessor} -> {activity_id}: precedence violated")

    for resource_id in RESOURCE_IDS:
        assigned = sorted(
            (
                entry
                for entry in actual.values()
                if resource_id in entry.activity.resources
            ),
            key=lambda item: (item.start, item.finish, item.activity.id),
        )
        for left, right in zip(assigned, assigned[1:]):
            if left.finish > right.start:
                errors.append(
                    f"{resource_id}: {left.activity.id} overlaps {right.activity.id}"
                )

    calculated_makespan = max(entry.finish for entry in actual.values())
    if result.makespan != calculated_makespan:
        errors.append("reported makespan does not match activity finishes")
    return tuple(errors)


def operational_constraint_errors(result: OperationalScheduleResult) -> tuple[str, ...]:
    actual = result.by_id
    errors: list[str] = []
    for window in PERMIT_WINDOWS:
        entry = actual[window.activity_id]
        if entry.start < window.earliest_start or entry.finish > window.latest_finish:
            errors.append(
                f"{window.activity_id}: outside {window.name} "
                f"H{window.earliest_start:02d}-H{window.latest_finish:02d}"
            )

    for exclusion in WORKFACE_EXCLUSIONS:
        assigned = sorted(
            (actual[activity_id] for activity_id in exclusion.activity_ids),
            key=lambda item: (item.start, item.finish, item.activity.id),
        )
        for left, right in zip(assigned, assigned[1:]):
            if left.finish > right.start:
                errors.append(
                    f"{exclusion.id}: {left.activity.id} overlaps {right.activity.id} "
                    f"in {exclusion.name}"
                )
    return tuple(errors)


def run_gate3_experiment() -> Gate3Comparison:
    capacity_only = _solve(enforce_operational_constraints=False)
    operational = _solve(enforce_operational_constraints=True)
    return Gate3Comparison(
        capacity_only=capacity_only,
        operational=operational,
        capacity_only_operational_errors=operational_constraint_errors(capacity_only),
    )


def _render_schedule(result: OperationalScheduleResult) -> str:
    lines = [
        result.method,
        f"Status: {result.solver_status}",
        f"Makespan: {result.makespan} hours",
        "Sequence: " + " -> ".join(result.sequence),
        "ID   Activity                                  Start Finish Resources",
        "---- ----------------------------------------- ----- ------ ----------------",
    ]
    for entry in sorted(
        result.entries,
        key=lambda item: (item.start, item.finish, item.activity.id),
    ):
        resources = ",".join(entry.activity.resources) or "-"
        lines.append(
            f"{entry.activity.id:<4} {entry.activity.name:<41} "
            f"H{entry.start:02d}   H{entry.finish:02d}  {resources}"
        )
    return "\n".join(lines)


def render_comparison(comparison: Gate3Comparison) -> str:
    operational_delay = (
        comparison.operational.makespan - comparison.capacity_only.makespan
    )
    errors = "\n".join(
        f"- {error}" for error in comparison.capacity_only_operational_errors
    )
    o03_capacity = comparison.capacity_only.by_id["O03"]
    o03_operational = comparison.operational.by_id["O03"]
    o06_operational = comparison.operational.by_id["O06"]
    return "\n".join(
        (
            "GATE 3 OPERATIONAL-REALITY EXPERIMENT",
            "10 activities; integer hours; FS precedence; named CRANE-C04; one permit/access window; one workface exclusion.",
            "",
            _render_schedule(comparison.capacity_only),
            "",
            "Operational violations in the capacity-only result:",
            errors or "- none",
            "",
            _render_schedule(comparison.operational),
            "",
            "COMPARISON",
            f"Capacity-only makespan: {comparison.capacity_only.makespan} hours",
            f"Operationally feasible makespan: {comparison.operational.makespan} hours",
            f"Operational reality adds: {operational_delay} hour(s)",
            (
                f"Decision: capacity-only starts O03 at H{o03_capacity.start:02d}, but the real plan uses CRANE-C04 on O06 "
                f"at H{o06_operational.start:02d}-H{o06_operational.finish:02d}, clears the exchanger workface, then performs O03 "
                f"at H{o03_operational.start:02d}-H{o03_operational.finish:02d} inside the H04-H09 permit/access window."
            ),
            "Learning: the mathematically shorter resource-feasible schedule is not executable once the permit and workface facts are represented.",
            "Modelling overhead: two explicit operational facts beyond precedence/resources — one time window and one workface exclusion.",
        )
    )


def main() -> int:
    print(render_comparison(run_gate3_experiment()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
