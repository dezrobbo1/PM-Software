from __future__ import annotations

from dataclasses import dataclass

from ortools.sat.python import cp_model

from deterministic_scheduling_core.errors import SchedulingError


@dataclass(frozen=True, slots=True)
class RealSliceActivity:
    id: str
    duration: int
    source_start: int
    predecessors: tuple[str, ...] = ()
    resources: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True, slots=True)
class ScheduledRealSliceActivity:
    activity: RealSliceActivity
    start: int
    finish: int


@dataclass(frozen=True, slots=True)
class RealSliceSchedule:
    method: str
    entries: tuple[ScheduledRealSliceActivity, ...]
    handoff_finish: int
    solver_status: str

    @property
    def by_id(self) -> dict[str, ScheduledRealSliceActivity]:
        return {entry.activity.id: entry for entry in self.entries}


@dataclass(frozen=True, slots=True)
class CapacityViolation:
    resource_id: str
    start: int
    finish: int
    demand: int
    capacity: int


@dataclass(frozen=True, slots=True)
class Gate5Comparison:
    source: RealSliceSchedule
    revised: RealSliceSchedule
    source_violations: tuple[CapacityViolation, ...]


# This is an anonymized derivative of a bounded real shutdown schedule slice.
# The raw source schedule and identifying task/resource names are intentionally
# not committed to this public repository. Coordinates are minutes from the
# slice origin. Source starts are retained as not-before boundaries so that
# unmodelled calendar/external-readiness facts are not silently pulled earlier.
RESOURCE_CAPACITY = {
    "RES-A": 2,
    "RES-B": 2,
    "RES-C": 1,
    "RES-D": 5,
    "RES-E": 5,
    "RES-F": 2,
}

ACTIVITIES = (
    RealSliceActivity("R01", 60, 240, resources=(("RES-A", 1), ("RES-B", 1))),
    RealSliceActivity("R02", 60, 300, ("R01",), (("RES-A", 1), ("RES-B", 1))),
    RealSliceActivity("R03", 60, 360, ("R02",), (("RES-A", 1), ("RES-B", 1))),
    RealSliceActivity("R04", 60, 240, resources=(("RES-A", 1), ("RES-B", 1))),
    RealSliceActivity("R05", 60, 300, ("R04",), (("RES-A", 1), ("RES-B", 1))),
    RealSliceActivity("R06", 30, 360, ("R05",), (("RES-C", 1),)),
    RealSliceActivity("R07", 60, 360, ("R05",), (("RES-A", 1), ("RES-B", 1))),
    RealSliceActivity("R08", 60, 420, ("R07",), (("RES-A", 1), ("RES-B", 1))),
    RealSliceActivity("R09", 60, 480, ("R08",), (("RES-A", 1), ("RES-B", 1))),
    RealSliceActivity("R10", 60, 540, ("R09",), (("RES-A", 1), ("RES-B", 1))),
    RealSliceActivity("R11", 60, 480, ("R08",), (("RES-A", 1), ("RES-B", 1))),
    RealSliceActivity("R12", 120, 240, resources=(("RES-B", 1), ("RES-F", 1))),
    RealSliceActivity("R13", 60, 0, resources=(("RES-D", 1), ("RES-E", 1))),
    RealSliceActivity("R14", 60, 60, ("R13",), (("RES-D", 1), ("RES-E", 1))),
    RealSliceActivity("R15", 60, 120, ("R14",), (("RES-D", 1), ("RES-E", 1))),
    RealSliceActivity("R16", 60, 270, ("R15",), (("RES-D", 1), ("RES-E", 1))),
    RealSliceActivity("R17", 60, 330, ("R16",), (("RES-D", 1), ("RES-E", 1))),
    RealSliceActivity("R18", 60, 390, ("R17",), (("RES-D", 1), ("RES-E", 1))),
    RealSliceActivity(
        "R19",
        0,
        600,
        (
            "R08",
            "R17",
            "R01",
            "R02",
            "R03",
            "R04",
            "R05",
            "R06",
            "R07",
            "R09",
            "R10",
            "R11",
            "R12",
            "R14",
            "R15",
            "R16",
            "R18",
        ),
    ),
)

HANDOFF_ID = "R19"


def _validate() -> None:
    ids = [activity.id for activity in ACTIVITIES]
    if len(ids) != len(set(ids)):
        raise SchedulingError("Gate 5 real slice contains duplicate activity IDs")
    known = set(ids)
    for activity in ACTIVITIES:
        if activity.duration < 0 or activity.source_start < 0:
            raise SchedulingError(f"{activity.id}: invalid duration/source start")
        unknown_predecessors = set(activity.predecessors) - known
        if unknown_predecessors:
            raise SchedulingError(
                f"{activity.id}: unknown predecessors {sorted(unknown_predecessors)}"
            )
        for resource_id, demand in activity.resources:
            if resource_id not in RESOURCE_CAPACITY:
                raise SchedulingError(f"{activity.id}: unknown resource {resource_id}")
            if demand <= 0 or demand > RESOURCE_CAPACITY[resource_id]:
                raise SchedulingError(
                    f"{activity.id}: invalid demand {demand} for {resource_id}"
                )


def source_schedule() -> RealSliceSchedule:
    _validate()
    entries = tuple(
        ScheduledRealSliceActivity(
            activity=activity,
            start=activity.source_start,
            finish=activity.source_start + activity.duration,
        )
        for activity in ACTIVITIES
    )
    return RealSliceSchedule(
        method="Published real-world slice (anonymized)",
        entries=entries,
        handoff_finish=next(
            entry.finish for entry in entries if entry.activity.id == HANDOFF_ID
        ),
        solver_status="SOURCE",
    )


def _capacity_violations(result: RealSliceSchedule) -> tuple[CapacityViolation, ...]:
    violations: list[CapacityViolation] = []
    for resource_id, capacity in RESOURCE_CAPACITY.items():
        relevant = [
            (entry.start, entry.finish, demand)
            for entry in result.entries
            for rid, demand in entry.activity.resources
            if rid == resource_id and entry.finish > entry.start
        ]
        if not relevant:
            continue
        points = sorted({point for start, finish, _ in relevant for point in (start, finish)})
        open_violation: CapacityViolation | None = None
        for left, right in zip(points, points[1:]):
            demand = sum(
                units
                for start, finish, units in relevant
                if start < right and finish > left
            )
            if demand > capacity:
                if (
                    open_violation is not None
                    and open_violation.finish == left
                    and open_violation.demand == demand
                ):
                    open_violation = CapacityViolation(
                        resource_id,
                        open_violation.start,
                        right,
                        demand,
                        capacity,
                    )
                    violations[-1] = open_violation
                else:
                    open_violation = CapacityViolation(
                        resource_id, left, right, demand, capacity
                    )
                    violations.append(open_violation)
            else:
                open_violation = None
    return tuple(violations)


def feasibility_errors(result: RealSliceSchedule) -> tuple[str, ...]:
    expected = {activity.id: activity for activity in ACTIVITIES}
    actual = result.by_id
    if set(expected) != set(actual):
        return ("scheduled activity IDs do not match the real slice",)

    errors: list[str] = []
    for activity_id, activity in expected.items():
        entry = actual[activity_id]
        if entry.start < activity.source_start:
            errors.append(f"{activity_id}: moved earlier than bounded source readiness")
        if entry.finish - entry.start != activity.duration:
            errors.append(f"{activity_id}: invalid duration span")
        for predecessor in activity.predecessors:
            if actual[predecessor].finish > entry.start:
                errors.append(f"{predecessor} -> {activity_id}: precedence violated")

    for violation in _capacity_violations(result):
        errors.append(
            f"{violation.resource_id}: demand {violation.demand} exceeds "
            f"capacity {violation.capacity} at M{violation.start}-M{violation.finish}"
        )

    if result.handoff_finish != actual[HANDOFF_ID].finish:
        errors.append("reported handoff finish does not match handoff activity")
    return tuple(errors)


def solve_revised() -> RealSliceSchedule:
    _validate()
    horizon = 1200
    model = cp_model.CpModel()
    starts: dict[str, cp_model.IntVar] = {}
    ends: dict[str, cp_model.IntVar] = {}
    intervals: dict[str, cp_model.IntervalVar] = {}

    for activity in ACTIVITIES:
        starts[activity.id] = model.new_int_var(
            activity.source_start, horizon, f"start_{activity.id}"
        )
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

    for resource_id, capacity in RESOURCE_CAPACITY.items():
        resource_intervals = []
        demands = []
        for activity in ACTIVITIES:
            demand = next(
                (units for rid, units in activity.resources if rid == resource_id),
                0,
            )
            if demand:
                resource_intervals.append(intervals[activity.id])
                demands.append(demand)
        if resource_intervals:
            model.add_cumulative(resource_intervals, demands, capacity)

    movement = sum(
        starts[activity.id] - activity.source_start
        for activity in ACTIVITIES
        if activity.id != HANDOFF_ID
    )
    movement_bound = len(ACTIVITIES) * horizon
    handoff_weight = movement_bound + 1
    model.minimize(ends[HANDOFF_ID] * handoff_weight + movement)

    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    status = solver.solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise SchedulingError(f"Gate 5 solver found no feasible revision: {status}")

    entries = tuple(
        ScheduledRealSliceActivity(
            activity=activity,
            start=solver.value(starts[activity.id]),
            finish=solver.value(ends[activity.id]),
        )
        for activity in ACTIVITIES
    )
    result = RealSliceSchedule(
        method="Capacity-feasible stable revision",
        entries=entries,
        handoff_finish=solver.value(ends[HANDOFF_ID]),
        solver_status=solver.status_name(status),
    )
    errors = feasibility_errors(result)
    if errors:
        raise SchedulingError("; ".join(errors))
    return result


def run_gate5_experiment() -> Gate5Comparison:
    source = source_schedule()
    revised = solve_revised()
    return Gate5Comparison(source, revised, _capacity_violations(source))


def _render_schedule(result: RealSliceSchedule) -> str:
    lines = [
        result.method,
        f"Status: {result.solver_status}",
        f"Handoff: M{result.handoff_finish}",
        "ID   Source  Revised/Start Finish  Move  Resources",
        "---- ------- ------------- ------ ----- ----------------",
    ]
    for entry in sorted(result.entries, key=lambda item: (item.start, item.activity.id)):
        resources = ",".join(rid for rid, _ in entry.activity.resources) or "-"
        move = entry.start - entry.activity.source_start
        lines.append(
            f"{entry.activity.id:<4} M{entry.activity.source_start:<6} "
            f"M{entry.start:<11} M{entry.finish:<5} +{move:<4} {resources}"
        )
    return "\n".join(lines)


def render_comparison(comparison: Gate5Comparison) -> str:
    source_errors = "\n".join(
        f"- {item.resource_id}: demand {item.demand} > capacity {item.capacity} "
        f"from M{item.start} to M{item.finish}"
        for item in comparison.source_violations
    ) or "- none"
    movements = [
        (source.activity.id, source.start, revised.start)
        for source, revised in zip(comparison.source.entries, comparison.revised.entries)
        if source.start != revised.start
    ]
    movement_text = "\n".join(
        f"- {activity_id}: M{before} -> M{after} (+{after - before}m)"
        for activity_id, before, after in movements
    ) or "- none"
    total_movement = sum(after - before for _, before, after in movements)
    return "\n".join(
        (
            "GATE 5 REAL-WORLD PROOF EXPERIMENT",
            "Anonymized 19-node slice derived from a real shutdown schedule; raw source data is not committed.",
            "Source starts are not-before boundaries so unmodelled external/calendar facts are preserved conservatively.",
            "",
            "SOURCE CAPACITY CHECK",
            source_errors,
            "",
            _render_schedule(comparison.revised),
            "",
            "MOVEMENTS",
            movement_text,
            "",
            "COMPARISON",
            f"Published handoff: M{comparison.source.handoff_finish}",
            f"Revised handoff: M{comparison.revised.handoff_finish}",
            f"Total later-start movement: {total_movement} minute(s)",
            "Learning: the bounded real slice contains a genuine declared-resource overload; the core can search for a capacity-feasible revision while protecting source readiness and the handoff first.",
            "Gate 5 remains pending practitioner judgement: a technically feasible revision is not enough until an experienced user says the proposed movement is operationally sensible.",
        )
    )


def main() -> int:
    print(render_comparison(run_gate5_experiment()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
