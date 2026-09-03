from __future__ import annotations

from dataclasses import dataclass

from ortools.sat.python import cp_model

from deterministic_scheduling_core.errors import SchedulingError


RESOURCE_IDS = ("MECH", "SPEC")


@dataclass(frozen=True, slots=True)
class ExecutionMode:
    id: str
    name: str
    duration: int
    resources: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ModeActivity:
    id: str
    name: str
    modes: tuple[ExecutionMode, ...]
    predecessors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Gate2Case:
    id: str
    name: str
    activities: tuple[ModeActivity, ...]
    target_activity_id: str


@dataclass(frozen=True, slots=True)
class ScheduledModeActivity:
    activity: ModeActivity
    mode: ExecutionMode
    start: int
    finish: int


@dataclass(frozen=True, slots=True)
class ModeScheduleResult:
    method: str
    entries: tuple[ScheduledModeActivity, ...]
    makespan: int
    solver_status: str

    @property
    def by_id(self) -> dict[str, ScheduledModeActivity]:
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
class ModeCounterfactual:
    mode: ExecutionMode
    makespan: int


@dataclass(frozen=True, slots=True)
class Gate2CaseComparison:
    case: Gate2Case
    local_greedy: ModeScheduleResult
    global_optimiser: ModeScheduleResult
    counterfactuals: tuple[ModeCounterfactual, ...]


NORMAL_REPAIR = ExecutionMode("NORMAL", "Normal repair", 8, ("MECH",))
ACCELERATED_REPAIR = ExecutionMode(
    "ACCELERATED", "Accelerated specialist repair", 5, ("MECH", "SPEC")
)


def _fixed_mode(mode_id: str, name: str, duration: int, *resources: str) -> tuple[ExecutionMode, ...]:
    return (ExecutionMode(mode_id, name, duration, tuple(resources)),)


def _case(
    case_id: str,
    name: str,
    *,
    specialist_inspection_duration: int,
    specialist_followup_duration: int,
) -> Gate2Case:
    return Gate2Case(
        id=case_id,
        name=name,
        target_activity_id="G02",
        activities=(
            ModeActivity("G01", "Release workfront", _fixed_mode("FIXED", "Fixed", 1)),
            ModeActivity(
                "G02",
                "Repair exchanger",
                (NORMAL_REPAIR, ACCELERATED_REPAIR),
                ("G01",),
            ),
            ModeActivity(
                "G03",
                "Post-repair cure and verification",
                _fixed_mode("FIXED", "Fixed", 8),
                ("G02",),
            ),
            ModeActivity(
                "G04",
                "Inspect protection system",
                _fixed_mode(
                    "FIXED",
                    "Fixed",
                    specialist_inspection_duration,
                    "SPEC",
                ),
                ("G01",),
            ),
            ModeActivity(
                "G05",
                "Protection-system corrective work",
                _fixed_mode("FIXED", "Fixed", specialist_followup_duration),
                ("G04",),
            ),
            ModeActivity(
                "G06",
                "Reinstate plant",
                _fixed_mode("FIXED", "Fixed", 1, "MECH"),
                ("G03", "G05"),
            ),
            ModeActivity(
                "G07",
                "Return to service",
                _fixed_mode("FIXED", "Fixed", 1),
                ("G06",),
            ),
        ),
    )


CASE_ACCELERATION_HELPS = _case(
    "G2-A",
    "Scarce specialist is lightly loaded: local acceleration helps globally",
    specialist_inspection_duration=2,
    specialist_followup_duration=2,
)

CASE_ACCELERATION_HURTS = _case(
    "G2-B",
    "Scarce specialist drives another branch: local acceleration hurts globally",
    specialist_inspection_duration=6,
    specialist_followup_duration=10,
)

GATE2_CASES = (CASE_ACCELERATION_HELPS, CASE_ACCELERATION_HURTS)


def _validate_case(case: Gate2Case) -> None:
    ids = [activity.id for activity in case.activities]
    if len(ids) != len(set(ids)):
        raise SchedulingError(f"{case.id}: duplicate activity IDs")
    known_ids = set(ids)
    if case.target_activity_id not in known_ids:
        raise SchedulingError(f"{case.id}: target activity is missing")
    known_resources = set(RESOURCE_IDS)
    for activity in case.activities:
        if not activity.modes:
            raise SchedulingError(f"{case.id}/{activity.id}: no execution mode")
        mode_ids = [mode.id for mode in activity.modes]
        if len(mode_ids) != len(set(mode_ids)):
            raise SchedulingError(f"{case.id}/{activity.id}: duplicate mode IDs")
        for mode in activity.modes:
            if mode.duration <= 0:
                raise SchedulingError(
                    f"{case.id}/{activity.id}/{mode.id}: duration must be positive"
                )
            unknown_resources = set(mode.resources) - known_resources
            if unknown_resources:
                raise SchedulingError(
                    f"{case.id}/{activity.id}/{mode.id}: unknown resources "
                    f"{sorted(unknown_resources)}"
                )
        unknown_predecessors = set(activity.predecessors) - known_ids
        if unknown_predecessors:
            raise SchedulingError(
                f"{case.id}/{activity.id}: unknown predecessors "
                f"{sorted(unknown_predecessors)}"
            )


def _solve(
    case: Gate2Case,
    *,
    method: str,
    forced_modes: dict[str, str] | None = None,
) -> ModeScheduleResult:
    _validate_case(case)
    forced_modes = forced_modes or {}
    activities_by_id = {activity.id: activity for activity in case.activities}
    for activity_id, mode_id in forced_modes.items():
        activity = activities_by_id.get(activity_id)
        if activity is None:
            raise SchedulingError(f"{case.id}: cannot force unknown activity {activity_id}")
        if mode_id not in {mode.id for mode in activity.modes}:
            raise SchedulingError(
                f"{case.id}/{activity_id}: cannot force unknown mode {mode_id}"
            )

    horizon = sum(max(mode.duration for mode in activity.modes) for activity in case.activities)
    model = cp_model.CpModel()
    starts: dict[str, cp_model.IntVar] = {}
    ends: dict[str, cp_model.IntVar] = {}
    presence: dict[tuple[str, str], cp_model.BoolVar] = {}
    intervals: dict[tuple[str, str], cp_model.IntervalVar] = {}

    for activity in case.activities:
        start = model.new_int_var(0, horizon, f"start_{activity.id}")
        end = model.new_int_var(0, horizon, f"end_{activity.id}")
        starts[activity.id] = start
        ends[activity.id] = end
        activity_presence: list[cp_model.BoolVar] = []
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
            activity_presence.append(selected)
        model.add_exactly_one(activity_presence)

    for activity_id, mode_id in forced_modes.items():
        for mode in activities_by_id[activity_id].modes:
            model.add(presence[(activity_id, mode.id)] == int(mode.id == mode_id))

    for activity in case.activities:
        for predecessor in activity.predecessors:
            model.add(starts[activity.id] >= ends[predecessor])

    for resource_id in RESOURCE_IDS:
        assigned = [
            intervals[(activity.id, mode.id)]
            for activity in case.activities
            for mode in activity.modes
            if resource_id in mode.resources
        ]
        model.add_no_overlap(assigned)

    makespan = model.new_int_var(0, horizon, "makespan")
    model.add_max_equality(makespan, list(ends.values()))

    secondary_bound = len(case.activities) * horizon + sum(
        max(0, len(activity.modes) - 1) for activity in case.activities
    )
    makespan_weight = secondary_bound + 1
    mode_tie_break = sum(
        mode_index * presence[(activity.id, mode.id)]
        for activity in case.activities
        for mode_index, mode in enumerate(activity.modes)
    )
    model.minimize(makespan * makespan_weight + sum(starts.values()) + mode_tie_break)

    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    status = solver.solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise SchedulingError(f"{case.id}: CP-SAT did not find a feasible schedule: {status}")

    entries: list[ScheduledModeActivity] = []
    for activity in case.activities:
        selected_mode = next(
            mode
            for mode in activity.modes
            if solver.value(presence[(activity.id, mode.id)])
        )
        entries.append(
            ScheduledModeActivity(
                activity=activity,
                mode=selected_mode,
                start=solver.value(starts[activity.id]),
                finish=solver.value(ends[activity.id]),
            )
        )

    result = ModeScheduleResult(
        method=method,
        entries=tuple(entries),
        makespan=max(entry.finish for entry in entries),
        solver_status=solver.status_name(status),
    )
    _require_feasible(case, result)
    return result


def build_local_greedy(case: Gate2Case) -> ModeScheduleResult:
    """Choose each activity's shortest mode locally, then schedule those choices optimally."""

    forced_modes = {
        activity.id: min(activity.modes, key=lambda mode: (mode.duration, mode.id)).id
        for activity in case.activities
    }
    return _solve(
        case,
        method="Local greedy: shortest execution mode, then optimal sequencing",
        forced_modes=forced_modes,
    )


def solve_globally(case: Gate2Case) -> ModeScheduleResult:
    """Choose execution modes and sequencing together to minimize whole-project finish."""

    return _solve(
        case,
        method="Global optimiser: execution mode + sequencing together",
    )


def feasibility_errors(
    case: Gate2Case, result: ModeScheduleResult
) -> tuple[str, ...]:
    expected = {activity.id: activity for activity in case.activities}
    actual = result.by_id
    errors: list[str] = []
    if set(actual) != set(expected):
        return ("scheduled activity IDs do not match the input",)

    for activity_id, activity in expected.items():
        entry = actual[activity_id]
        valid_modes = {mode.id: mode for mode in activity.modes}
        if entry.mode.id not in valid_modes:
            errors.append(f"{activity_id}: selected mode is not defined")
            continue
        if entry.start < 0 or entry.finish - entry.start != entry.mode.duration:
            errors.append(f"{activity_id}: invalid start/finish span")
        for predecessor in activity.predecessors:
            if actual[predecessor].finish > entry.start:
                errors.append(f"{predecessor} -> {activity_id}: precedence violated")

    for resource_id in RESOURCE_IDS:
        assigned = sorted(
            (
                entry
                for entry in actual.values()
                if resource_id in entry.mode.resources
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


def _require_feasible(case: Gate2Case, result: ModeScheduleResult) -> None:
    errors = feasibility_errors(case, result)
    if errors:
        raise SchedulingError("; ".join(errors))


def run_gate2_case(case: Gate2Case) -> Gate2CaseComparison:
    local_greedy = build_local_greedy(case)
    global_optimiser = solve_globally(case)
    target = next(
        activity for activity in case.activities if activity.id == case.target_activity_id
    )
    counterfactuals = tuple(
        ModeCounterfactual(
            mode=mode,
            makespan=_solve(
                case,
                method=f"Counterfactual: force {case.target_activity_id}={mode.id}",
                forced_modes={case.target_activity_id: mode.id},
            ).makespan,
        )
        for mode in target.modes
    )
    return Gate2CaseComparison(case, local_greedy, global_optimiser, counterfactuals)


def run_gate2_experiment() -> tuple[Gate2CaseComparison, ...]:
    return tuple(run_gate2_case(case) for case in GATE2_CASES)


def _render_schedule(result: ModeScheduleResult) -> str:
    lines = [
        result.method,
        f"Status: {result.solver_status}",
        f"Makespan: {result.makespan} hours",
        "Sequence: " + " -> ".join(result.sequence),
        "ID   Activity                              Mode         Start Finish Resources",
        "---- ------------------------------------- ------------ ----- ------ ---------",
    ]
    for entry in sorted(
        result.entries,
        key=lambda item: (item.start, item.finish, item.activity.id),
    ):
        resources = ",".join(entry.mode.resources) or "-"
        lines.append(
            f"{entry.activity.id:<4} {entry.activity.name:<37} {entry.mode.id:<12} "
            f"H{entry.start:02d}   H{entry.finish:02d}  {resources}"
        )
    return "\n".join(lines)


def _decision_explanation(comparison: Gate2CaseComparison) -> str:
    target_id = comparison.case.target_activity_id
    local = comparison.local_greedy.by_id[target_id].mode
    selected = comparison.global_optimiser.by_id[target_id].mode
    counterfactual = {item.mode.id: item.makespan for item in comparison.counterfactuals}
    if local.id == selected.id:
        other = next(item for item in comparison.counterfactuals if item.mode.id != selected.id)
        benefit = other.makespan - comparison.global_optimiser.makespan
        return (
            f"Decision: {target_id}={selected.id}; local greedy agrees. "
            f"Forcing {other.mode.id} finishes at H{other.makespan} versus H"
            f"{comparison.global_optimiser.makespan}; specialist acceleration is globally useful "
            f"by {benefit}h in this context."
        )
    penalty = counterfactual[local.id] - counterfactual[selected.id]
    return (
        f"Decision: {target_id}={selected.id} despite local greedy choosing {local.id}. "
        f"Forcing {local.id} finishes at H{counterfactual[local.id]} versus H"
        f"{counterfactual[selected.id]}; avoiding SPEC on {target_id} lets the repair and the "
        f"long specialist branch run in parallel, recovering {penalty}h."
    )


def render_gate2_experiment(comparisons: tuple[Gate2CaseComparison, ...]) -> str:
    lines = [
        "GATE 2 GLOBAL EXECUTION-MODE DECISION EXPERIMENT",
        "Same repair choice in two contexts: NORMAL = 8h MECH; ACCELERATED = 5h MECH+SPEC.",
        "The local baseline always picks the shortest activity mode, then receives optimal sequencing.",
        "The experimental scheduler chooses mode and sequencing together for project finish.",
    ]
    for comparison in comparisons:
        lines.extend(
            (
                "",
                f"CASE {comparison.case.id}: {comparison.case.name}",
                "",
                _render_schedule(comparison.local_greedy),
                "",
                _render_schedule(comparison.global_optimiser),
                "",
                "COUNTERFACTUAL TARGET-MODE FINISHES: "
                + ", ".join(
                    f"{item.mode.id}=H{item.makespan}"
                    for item in comparison.counterfactuals
                ),
                _decision_explanation(comparison),
                f"Project improvement versus local greedy: "
                f"{comparison.local_greedy.makespan - comparison.global_optimiser.makespan} hours",
            )
        )
    lines.extend(
        (
            "",
            "GATE 2 LEARNING",
            "The shorter activity mode is not inherently the better project decision. "
            "Its value depends on what else needs the scarce specialist.",
            "Feasibility: precedence is respected and MECH/SPEC are not double-booked in every result.",
        )
    )
    return "\n".join(lines)


if __name__ == "__main__":
    print(render_gate2_experiment(run_gate2_experiment()))
