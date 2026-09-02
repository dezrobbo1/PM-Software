from __future__ import annotations

from dataclasses import dataclass

from ortools.sat.python import cp_model

from deterministic_scheduling_core.errors import SchedulingError


@dataclass(frozen=True, slots=True)
class Activity:
    id: str
    name: str
    duration: int
    predecessors: tuple[str, ...] = ()
    resources: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ScheduledActivity:
    activity: Activity
    start: int
    finish: int


@dataclass(frozen=True, slots=True)
class ScheduleResult:
    method: str
    entries: tuple[ScheduledActivity, ...]
    makespan: int
    solver_status: str

    @property
    def by_id(self) -> dict[str, ScheduledActivity]:
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
class ExperimentComparison:
    baseline: ScheduleResult
    experimental: ScheduleResult


RESOURCE_IDS = ("MECH", "CRANE", "INSPECT")

# Input order is the fixed priority used by the transparent baseline. It
# deliberately works through the cooler and valve scopes before the longer
# vessel branch, giving CP-SAT a meaningful sequencing choice to improve.
SAMPLE_ACTIVITIES = (
    Activity("A01", "Prepare work area", 2),
    Activity("A02", "Isolate and make safe", 1, ("A01",), ("MECH",)),
    Activity("A03", "Lift cooler cover", 3, ("A02",), ("MECH", "CRANE")),
    Activity("A04", "Inspect cooler bundle", 2, ("A03",), ("INSPECT",)),
    Activity("A05", "Repair cooler tubes", 5, ("A04",), ("MECH",)),
    Activity("A06", "Refit cooler cover", 3, ("A05",), ("MECH", "CRANE")),
    Activity("A07", "Hydrotest cooler", 2, ("A06",), ("INSPECT",)),
    Activity("A08", "Remove control valve", 2, ("A02",), ("MECH", "CRANE")),
    Activity("A09", "Bench overhaul valve", 4, ("A08",), ("MECH",)),
    Activity("A10", "Reinstall valve", 2, ("A09",), ("MECH", "CRANE")),
    Activity("A11", "Lift vessel cover", 3, ("A02",), ("MECH", "CRANE")),
    Activity("A12", "Inspect vessel internals", 2, ("A11",), ("INSPECT",)),
    Activity("A13", "Repair vessel internals", 8, ("A12",), ("MECH",)),
    Activity("A14", "Cure and hold", 6, ("A13",)),
    Activity("A15", "Close vessel", 3, ("A14",), ("MECH", "CRANE")),
    Activity("A16", "Leak test vessel", 2, ("A15",), ("INSPECT",)),
    Activity("A17", "Reinstate isolation", 1, ("A07", "A10", "A16"), ("MECH",)),
    Activity("A18", "Return to service", 1, ("A17",)),
)


def _validate_activities(activities: tuple[Activity, ...]) -> None:
    ids = [activity.id for activity in activities]
    if len(ids) != len(set(ids)):
        raise SchedulingError("Gate 1 sample contains duplicate activity IDs")
    known_ids = set(ids)
    known_resources = set(RESOURCE_IDS)
    for activity in activities:
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


def _first_available_start(
    ready: int,
    duration: int,
    resources: tuple[str, ...],
    bookings: dict[str, list[ScheduledActivity]],
) -> int:
    candidate = ready
    while True:
        blockers = {
            entry
            for resource_id in resources
            for entry in bookings[resource_id]
            if candidate < entry.finish and candidate + duration > entry.start
        }
        if not blockers:
            return candidate
        candidate = max(entry.finish for entry in blockers)


def build_baseline(
    activities: tuple[Activity, ...] = SAMPLE_ACTIVITIES,
) -> ScheduleResult:
    """Schedule the first eligible activity in fixed input order."""

    _validate_activities(activities)
    scheduled: dict[str, ScheduledActivity] = {}
    bookings: dict[str, list[ScheduledActivity]] = {
        resource_id: [] for resource_id in RESOURCE_IDS
    }
    remaining = list(activities)

    while remaining:
        selected = next(
            (
                activity
                for activity in remaining
                if all(predecessor in scheduled for predecessor in activity.predecessors)
            ),
            None,
        )
        if selected is None:
            raise SchedulingError("Gate 1 sample precedence contains a cycle")
        ready = max(
            (scheduled[predecessor].finish for predecessor in selected.predecessors),
            default=0,
        )
        start = _first_available_start(
            ready, selected.duration, selected.resources, bookings
        )
        entry = ScheduledActivity(selected, start, start + selected.duration)
        scheduled[selected.id] = entry
        for resource_id in selected.resources:
            bookings[resource_id].append(entry)
        remaining.remove(selected)

    result = ScheduleResult(
        method="Baseline: earliest start with fixed activity-ID priority",
        entries=tuple(scheduled[activity.id] for activity in activities),
        makespan=max(entry.finish for entry in scheduled.values()),
        solver_status="FEASIBLE",
    )
    _require_feasible(activities, result)
    return result


def solve_with_cp_sat(
    activities: tuple[Activity, ...] = SAMPLE_ACTIVITIES,
) -> ScheduleResult:
    """Minimize project makespan with a narrow resource-constrained CP-SAT model."""

    _validate_activities(activities)
    horizon = sum(activity.duration for activity in activities)
    model = cp_model.CpModel()
    starts: dict[str, cp_model.IntVar] = {}
    ends: dict[str, cp_model.IntVar] = {}
    intervals: dict[str, cp_model.IntervalVar] = {}

    for activity in activities:
        starts[activity.id] = model.new_int_var(0, horizon, f"start_{activity.id}")
        ends[activity.id] = model.new_int_var(0, horizon, f"end_{activity.id}")
        intervals[activity.id] = model.new_interval_var(
            starts[activity.id],
            activity.duration,
            ends[activity.id],
            f"interval_{activity.id}",
        )

    for activity in activities:
        for predecessor in activity.predecessors:
            model.add(starts[activity.id] >= ends[predecessor])

    for resource_id in RESOURCE_IDS:
        assigned = [
            intervals[activity.id]
            for activity in activities
            if resource_id in activity.resources
        ]
        model.add_no_overlap(assigned)

    makespan = model.new_int_var(0, horizon, "makespan")
    model.add_max_equality(makespan, list(ends.values()))

    # Makespan remains the primary objective. The start-time sum only makes an
    # equally short result easier for a person to inspect.
    makespan_weight = len(activities) * horizon + 1
    model.minimize(makespan * makespan_weight + sum(starts.values()))

    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    status = solver.solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise SchedulingError(f"CP-SAT did not find a feasible schedule: {status}")

    entries = tuple(
        ScheduledActivity(
            activity,
            solver.value(starts[activity.id]),
            solver.value(ends[activity.id]),
        )
        for activity in activities
    )
    result = ScheduleResult(
        method="Experimental scheduler: OR-Tools CP-SAT",
        entries=entries,
        makespan=max(entry.finish for entry in entries),
        solver_status=solver.status_name(status),
    )
    _require_feasible(activities, result)
    return result


def feasibility_errors(
    activities: tuple[Activity, ...], result: ScheduleResult
) -> tuple[str, ...]:
    expected = {activity.id: activity for activity in activities}
    actual = result.by_id
    errors: list[str] = []
    if set(actual) != set(expected):
        errors.append("scheduled activity IDs do not match the input")
        return tuple(errors)

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


def _require_feasible(
    activities: tuple[Activity, ...], result: ScheduleResult
) -> None:
    errors = feasibility_errors(activities, result)
    if errors:
        raise SchedulingError("; ".join(errors))


def run_gate1_experiment() -> ExperimentComparison:
    return ExperimentComparison(
        baseline=build_baseline(),
        experimental=solve_with_cp_sat(),
    )


def _wait_explanation(entry: ScheduledActivity, result: ScheduleResult) -> str:
    by_id = result.by_id
    ready = max(
        (by_id[predecessor].finish for predecessor in entry.activity.predecessors),
        default=0,
    )
    if entry.activity.predecessors:
        controlling = ",".join(
            predecessor
            for predecessor in entry.activity.predecessors
            if by_id[predecessor].finish == ready
        )
        parts = [f"precedence ready H{ready:02d} ({controlling})"]
    else:
        parts = ["ready at H00"]

    if entry.start == ready:
        parts.append("no resource wait")
        return "; ".join(parts)

    blocked_by: list[str] = []
    for resource_id in entry.activity.resources:
        blockers = sorted(
            other.activity.id
            for other in result.entries
            if other.activity.id != entry.activity.id
            and resource_id in other.activity.resources
            and other.start < entry.start
            and other.finish > ready
        )
        if blockers:
            blocked_by.append(f"{resource_id}:{','.join(blockers)}")
    if blocked_by:
        parts.append(
            f"resource wait H{ready:02d}-H{entry.start:02d} ({'; '.join(blocked_by)})"
        )
    else:
        parts.append(f"solver sequencing to H{entry.start:02d}")
    return "; ".join(parts)


def _render_schedule(result: ScheduleResult) -> str:
    lines = [
        result.method,
        f"Status: {result.solver_status}",
        f"Makespan: {result.makespan} hours",
        "Sequence: " + " -> ".join(result.sequence),
        "",
        "ID   Activity                    Start Finish Resources        Why it starts there",
        "---- --------------------------- ----- ------ ---------------- ------------------------------",
    ]
    for entry in sorted(
        result.entries,
        key=lambda item: (item.start, item.finish, item.activity.id),
    ):
        resources = ",".join(entry.activity.resources) or "-"
        lines.append(
            f"{entry.activity.id:<4} {entry.activity.name:<27} "
            f"H{entry.start:02d}   H{entry.finish:02d}  {resources:<16} "
            f"{_wait_explanation(entry, result)}"
        )
    return "\n".join(lines)


def render_comparison(comparison: ExperimentComparison) -> str:
    improvement = comparison.baseline.makespan - comparison.experimental.makespan
    return "\n".join(
        (
            "GATE 1 RESOURCE-CONSTRAINED SCHEDULING EXPERIMENT",
            "18 activities; integer hours; finish-to-start precedence; "
            "non-preemptive work; unit-capacity MECH, CRANE and INSPECT resources.",
            "",
            _render_schedule(comparison.baseline),
            "",
            _render_schedule(comparison.experimental),
            "",
            "COMPARISON",
            f"Baseline makespan: {comparison.baseline.makespan} hours",
            f"Experimental makespan: {comparison.experimental.makespan} hours",
            f"Improvement: {improvement} hours",
            "Decision: CP-SAT advances the long vessel branch so its six-hour cure/hold "
            "can overlap cooler and valve work instead of extending project finish.",
            "Feasibility: precedence respected and constrained resources are not double-booked.",
        )
    )
