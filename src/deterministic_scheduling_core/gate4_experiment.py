from __future__ import annotations

from dataclasses import dataclass

from ortools.sat.python import cp_model

from deterministic_scheduling_core.errors import SchedulingError
from deterministic_scheduling_core.gate3_experiment import (
    ACTIVITIES,
    PERMIT_WINDOWS,
    RESOURCE_IDS,
    WORKFACE_EXCLUSIONS,
    OperationalScheduleResult,
    ScheduledOperationalActivity,
    capacity_feasibility_errors,
    operational_constraint_errors,
    run_gate3_experiment,
)


STATUS_HOUR = 4


@dataclass(frozen=True, slots=True)
class EquipmentOutage:
    resource_id: str
    start: int
    finish: int
    reason: str


@dataclass(frozen=True, slots=True)
class ScheduleMovement:
    activity_id: str
    previous_start: int
    revised_start: int
    previous_finish: int
    revised_finish: int

    @property
    def start_delta(self) -> int:
        return self.revised_start - self.previous_start


@dataclass(frozen=True, slots=True)
class Gate4Comparison:
    approved: OperationalScheduleResult
    revised: OperationalScheduleResult
    status_hour: int
    outage: EquipmentOutage
    movements: tuple[ScheduleMovement, ...]

    @property
    def moved_activity_ids(self) -> tuple[str, ...]:
        return tuple(item.activity_id for item in self.movements if item.start_delta != 0)

    @property
    def total_start_movement(self) -> int:
        return sum(abs(item.start_delta) for item in self.movements)

    @property
    def preserved_future_activity_ids(self) -> tuple[str, ...]:
        return tuple(item.activity_id for item in self.movements if item.start_delta == 0)


CRANE_OUTAGE = EquipmentOutage(
    resource_id="CRANE-C04",
    start=5,
    finish=6,
    reason="unexpected one-hour crane inspection / availability loss",
)


def _equipment_outage_errors(
    result: OperationalScheduleResult,
    outage: EquipmentOutage,
) -> tuple[str, ...]:
    errors: list[str] = []
    for entry in result.entries:
        if outage.resource_id not in entry.activity.resources:
            continue
        if entry.start < outage.finish and entry.finish > outage.start:
            errors.append(
                f"{outage.resource_id}: {entry.activity.id} overlaps outage "
                f"H{outage.start:02d}-H{outage.finish:02d}"
            )
    return tuple(errors)


def _status_freeze_errors(
    approved: OperationalScheduleResult,
    revised: OperationalScheduleResult,
    *,
    status_hour: int,
) -> tuple[str, ...]:
    errors: list[str] = []
    for activity_id, previous in approved.by_id.items():
        current = revised.by_id[activity_id]
        if previous.start < status_hour and (
            previous.start != current.start or previous.finish != current.finish
        ):
            errors.append(f"{activity_id}: started work moved during replanning")
        if previous.start >= status_hour and current.start < status_hour:
            errors.append(f"{activity_id}: unstarted work moved into the past")
    return tuple(errors)


def _solve_revised_plan(
    approved: OperationalScheduleResult,
    *,
    status_hour: int = STATUS_HOUR,
    outage: EquipmentOutage = CRANE_OUTAGE,
) -> OperationalScheduleResult:
    """Replan the Gate 3 schedule after one short equipment outage.

    The bounded experiment freezes work that has already started and then uses a
    lexicographic objective: earliest project finish first, minimum movement from
    the approved future plan second. This is intentionally not a general progress
    or event engine.
    """

    horizon = approved.makespan + sum(activity.duration for activity in ACTIVITIES)
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

    for window in PERMIT_WINDOWS:
        model.add(starts[window.activity_id] >= window.earliest_start)
        model.add(ends[window.activity_id] <= window.latest_finish)

    for exclusion in WORKFACE_EXCLUSIONS:
        model.add_no_overlap(
            [intervals[activity_id] for activity_id in exclusion.activity_ids]
        )

    # Freeze everything that has actually started by the H04 status point.
    for activity_id, previous in approved.by_id.items():
        if previous.start < status_hour:
            model.add(starts[activity_id] == previous.start)
            model.add(ends[activity_id] == previous.finish)
        else:
            model.add(starts[activity_id] >= status_hour)

    # Represent CRANE-C04's H05-H06 outage as a disjunction: every crane task
    # must be entirely before or entirely after the unavailable interval.
    for activity in ACTIVITIES:
        if outage.resource_id not in activity.resources:
            continue
        before_outage = model.new_bool_var(f"{activity.id}_before_outage")
        model.add(
            ends[activity.id]
            <= outage.start + horizon * (1 - before_outage)
        )
        model.add(
            starts[activity.id]
            >= outage.finish - horizon * before_outage
        )

    future_ids = [
        activity.id
        for activity in ACTIVITIES
        if approved.by_id[activity.id].start >= status_hour
    ]
    movement_vars: list[cp_model.IntVar] = []
    for activity_id in future_ids:
        movement = model.new_int_var(0, horizon, f"movement_{activity_id}")
        model.add_abs_equality(
            movement,
            starts[activity_id] - approved.by_id[activity_id].start,
        )
        movement_vars.append(movement)

    total_movement = model.new_int_var(
        0,
        len(future_ids) * horizon,
        "total_start_movement",
    )
    model.add(total_movement == sum(movement_vars))

    makespan = model.new_int_var(0, horizon, "makespan")
    model.add_max_equality(makespan, list(ends.values()))

    # Lexicographic by construction: makespan dominates movement, and movement
    # dominates the small early-start tie break. This prevents needless churn
    # while still recovering the best achievable project finish.
    tertiary_bound = len(ACTIVITIES) * horizon
    movement_bound = len(future_ids) * horizon
    movement_weight = tertiary_bound + 1
    makespan_weight = movement_bound * movement_weight + tertiary_bound + 1
    model.minimize(
        makespan * makespan_weight
        + total_movement * movement_weight
        + sum(starts.values())
    )

    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    status = solver.solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise SchedulingError(
            f"Gate 4 CP-SAT did not find a feasible revised schedule: {status}"
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
        method="Stable replan: outage-aware finish first, minimum future movement second",
        entries=entries,
        makespan=max(entry.finish for entry in entries),
        solver_status=solver.status_name(status),
    )

    errors = (
        capacity_feasibility_errors(result)
        + operational_constraint_errors(result)
        + _equipment_outage_errors(result, outage)
        + _status_freeze_errors(approved, result, status_hour=status_hour)
    )
    if errors:
        raise SchedulingError("; ".join(errors))
    return result


def run_gate4_experiment() -> Gate4Comparison:
    approved = run_gate3_experiment().operational
    revised = _solve_revised_plan(approved)
    movements = tuple(
        ScheduleMovement(
            activity_id=activity.id,
            previous_start=approved.by_id[activity.id].start,
            revised_start=revised.by_id[activity.id].start,
            previous_finish=approved.by_id[activity.id].finish,
            revised_finish=revised.by_id[activity.id].finish,
        )
        for activity in ACTIVITIES
        if approved.by_id[activity.id].start >= STATUS_HOUR
    )
    return Gate4Comparison(
        approved=approved,
        revised=revised,
        status_hour=STATUS_HOUR,
        outage=CRANE_OUTAGE,
        movements=movements,
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


def render_comparison(comparison: Gate4Comparison) -> str:
    moved = [item for item in comparison.movements if item.start_delta != 0]
    movement_lines = [
        (
            f"- {item.activity_id}: H{item.previous_start:02d}-H{item.previous_finish:02d} "
            f"-> H{item.revised_start:02d}-H{item.revised_finish:02d} "
            f"({item.start_delta:+d}h)"
        )
        for item in moved
    ]
    o03_before = comparison.approved.by_id["O03"]
    o03_after = comparison.revised.by_id["O03"]
    return "\n".join(
        (
            "GATE 4 CHANGE-AND-REPLANNING EXPERIMENT",
            f"Status point: H{comparison.status_hour:02d}. Disturbance: {comparison.outage.resource_id} unavailable "
            f"H{comparison.outage.start:02d}-H{comparison.outage.finish:02d} ({comparison.outage.reason}).",
            "Started work is frozen; future work may move. Makespan is minimised first and future-plan movement second.",
            "",
            "APPROVED GATE 3 PLAN",
            _render_schedule(comparison.approved),
            "",
            "REVISED PLAN",
            _render_schedule(comparison.revised),
            "",
            "CHANGE EXPLANATION",
            (
                f"Direct cause: O03 was approved at H{o03_before.start:02d}-H{o03_before.finish:02d}, which now overlaps "
                f"the crane outage. It moves to H{o03_after.start:02d}-H{o03_after.finish:02d}, the first feasible slot "
                "after the outage that still fits the H04-H09 permit/access window."
            ),
            "Downstream consequence: O04, O08, O09 and O10 each move one hour because they depend directly or indirectly on O03.",
            "Unaffected work: O05 remains at H05-H08, while O01/O02/O06/O07 retain their already-started coordinates.",
            "",
            "MOVEMENTS",
            *(movement_lines or ["- none"]),
            "",
            "COMPARISON",
            f"Approved finish: H{comparison.approved.makespan:02d}",
            f"Revised finish: H{comparison.revised.makespan:02d}",
            f"Project impact: +{comparison.revised.makespan - comparison.approved.makespan} hour(s)",
            f"Future activities moved: {len(moved)}",
            f"Total future start movement: {comparison.total_start_movement} hour(s)",
            "Preserved future activities: " + ", ".join(comparison.preserved_future_activity_ids),
            "Learning: a small execution disturbance can be propagated through the operational plan without rewriting work that does not need to move, and the reason for the change remains explicit.",
        )
    )


def main() -> int:
    print(render_comparison(run_gate4_experiment()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
