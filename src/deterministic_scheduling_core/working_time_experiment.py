from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from time import perf_counter

from ortools.sat.python import cp_model

from deterministic_scheduling_core.errors import SchedulingError


TICKS_PER_HOUR = 2
TICKS_PER_DAY = 24 * TICKS_PER_HOUR
HORIZON = 7 * TICKS_PER_DAY

ELAPSED = "ELAPSED"
PRODUCTIVE = "PRODUCTIVE"
SUSPENDABLE = "SUSPENDABLE_AT_AVAILABILITY_GAPS"
CONTINUOUS = "CONTINUOUS"


@dataclass(frozen=True, slots=True)
class WorkCalendar:
    id: str
    daily_windows: tuple[tuple[int, int], ...]

    def slots(self, horizon: int = HORIZON) -> frozenset[int]:
        available: set[int] = set()
        for day_start in range(0, horizon, TICKS_PER_DAY):
            for start, finish in self.daily_windows:
                available.update(
                    range(day_start + start, min(day_start + finish, horizon))
                )
        return frozenset(available)


@dataclass(frozen=True, slots=True)
class ResourceSpec:
    id: str
    name: str
    calendar_id: str
    capacity: int = 1


@dataclass(frozen=True, slots=True)
class Requirement:
    resource_id: str
    demand: int = 1


@dataclass(frozen=True, slots=True)
class ModeSpec:
    id: str
    name: str
    processing_ticks: int
    calendar_id: str
    requirements: tuple[Requirement, ...] = ()
    time_basis: str = PRODUCTIVE
    continuity: str = SUSPENDABLE


@dataclass(frozen=True, slots=True)
class ActivitySpec:
    id: str
    name: str
    modes: tuple[ModeSpec, ...]
    predecessors: tuple[str, ...] = ()
    not_before: int = 0
    fixed_start: int | None = None


@dataclass(frozen=True, slots=True)
class Outage:
    resource_id: str
    start: int
    finish: int
    reason: str


@dataclass(frozen=True, slots=True)
class FixedExecution:
    activity_id: str
    mode_id: str
    start: int
    periods: tuple[tuple[int, int], ...]

    @property
    def finish(self) -> int:
        return self.periods[-1][1] if self.periods else self.start


@dataclass(frozen=True, slots=True)
class Scenario:
    id: str
    outages: tuple[Outage, ...] = ()
    fixed_executions: tuple[FixedExecution, ...] = ()

    @property
    def fixed_by_activity(self) -> dict[str, FixedExecution]:
        return {item.activity_id: item for item in self.fixed_executions}


@dataclass(frozen=True, slots=True)
class ExperimentCase:
    calendars: tuple[WorkCalendar, ...]
    resources: tuple[ResourceSpec, ...]
    activities: tuple[ActivitySpec, ...]
    objective_activity_id: str
    horizon: int = HORIZON

    @property
    def calendar_by_id(self) -> dict[str, WorkCalendar]:
        return {calendar.id: calendar for calendar in self.calendars}

    @property
    def resource_by_id(self) -> dict[str, ResourceSpec]:
        return {resource.id: resource for resource in self.resources}

    @property
    def activity_by_id(self) -> dict[str, ActivitySpec]:
        return {activity.id: activity for activity in self.activities}


@dataclass(frozen=True, slots=True)
class Placement:
    mode_id: str
    start: int
    finish: int
    periods: tuple[tuple[int, int], ...]


@dataclass(frozen=True, slots=True)
class ScheduledEntry:
    activity_id: str
    activity_name: str
    mode_id: str
    start: int
    finish: int
    periods: tuple[tuple[int, int], ...]
    resources: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ModelComplexity:
    integer_variables: int
    boolean_variables: int
    optional_intervals: int
    execution_segments: int
    constraints: int
    solver_calls: int
    solve_ms: float


@dataclass(frozen=True, slots=True)
class PhysicalValidation:
    invalid_activity_ids: tuple[str, ...]
    non_working_slots: int
    resource_calendar_violations: int
    joint_calendar_violations: int
    continuous_activity_violations: int
    processing_total_violations: int
    precedence_violations: int
    capacity_violations: int

    @property
    def valid(self) -> bool:
        return not self.invalid_activity_ids


@dataclass(frozen=True, slots=True)
class PlanResult:
    interpretation: str
    scenario_id: str
    entries: tuple[ScheduledEntry, ...]
    project_finish: int
    solver_status: str
    complexity: ModelComplexity
    signature: str
    validation: PhysicalValidation

    @property
    def by_id(self) -> dict[str, ScheduledEntry]:
        return {entry.activity_id: entry for entry in self.entries}


@dataclass(frozen=True, slots=True)
class RemainingWorkResult:
    actual_start: int
    actual_periods: tuple[tuple[int, int], ...]
    actual_productive_ticks: int
    outage: Outage
    remaining_productive_ticks: int
    explicit_added_work_ticks: int
    future_periods: tuple[tuple[int, int], ...]
    forecast_finish: int


@dataclass(frozen=True, slots=True)
class ExperimentResult:
    case: ExperimentCase
    plans: tuple[PlanResult, ...]
    repeated_c_signature: str
    repeat_canonical: bool
    finish_difference_ids: tuple[str, ...]
    outage_no_restart: RemainingWorkResult
    outage_with_restart: RemainingWorkResult
    changed_state_plan: PlanResult
    normal_mode: str
    outage_mode: str
    falsified: bool

    @property
    def by_interpretation(self) -> dict[str, PlanResult]:
        return {plan.interpretation: plan for plan in self.plans}


def _ticks(hours: float) -> int:
    ticks = float(hours) * TICKS_PER_HOUR
    if not ticks.is_integer():
        raise ValueError("the experiment uses 30-minute resolution")
    return int(ticks)


def _req(*resource_ids: str) -> tuple[Requirement, ...]:
    return tuple(Requirement(resource_id) for resource_id in resource_ids)


def _mode(
    mode_id: str,
    name: str,
    hours: float,
    calendar_id: str,
    *resource_ids: str,
    time_basis: str = PRODUCTIVE,
    continuity: str = SUSPENDABLE,
) -> ModeSpec:
    return ModeSpec(
        mode_id,
        name,
        _ticks(hours),
        calendar_id,
        _req(*resource_ids),
        time_basis,
        continuity,
    )


def _activity(
    activity_id: str,
    name: str,
    mode: ModeSpec | tuple[ModeSpec, ...],
    *,
    predecessors: tuple[str, ...] = (),
    not_before: int = 0,
    fixed_start: int | None = None,
) -> ActivitySpec:
    modes = mode if isinstance(mode, tuple) else (mode,)
    return ActivitySpec(
        activity_id,
        name,
        modes,
        predecessors,
        not_before,
        fixed_start,
    )


def build_case() -> ExperimentCase:
    """Build the transparent 18-activity industrial calendar experiment."""

    calendars = (
        WorkCalendar("ALWAYS", ((0, TICKS_PER_DAY),)),
        WorkCalendar(
            "MECH_DAY",
            ((_ticks(6), _ticks(12)), (_ticks(12.5), _ticks(18))),
        ),
        WorkCalendar(
            "C04",
            ((_ticks(7), _ticks(12)), (_ticks(12.5), _ticks(17))),
        ),
        WorkCalendar(
            "INSPECT",
            ((_ticks(8), _ticks(12)), (_ticks(12.5), _ticks(16.5))),
        ),
        WorkCalendar("NIGHT_MECH", ((_ticks(18), _ticks(24)),)),
    )
    resources = (
        ResourceSpec("MECH_DAY", "Day mechanical crew", "MECH_DAY"),
        ResourceSpec("C04", "Named crane C04", "C04"),
        ResourceSpec("INSPECT", "Inspection specialist", "INSPECT"),
        ResourceSpec("NIGHT_MECH", "Authorised night mechanical crew", "NIGHT_MECH"),
    )

    day = lambda mode_id, name, hours, *resources, continuity=SUSPENDABLE: _mode(
        mode_id,
        name,
        hours,
        "MECH_DAY",
        *resources,
        continuity=continuity,
    )
    inspect = lambda mode_id, name, hours: _mode(
        mode_id,
        name,
        hours,
        "INSPECT",
        "INSPECT",
        continuity=CONTINUOUS,
    )

    activities = (
        _activity("A01", "Mobilise day crew", day("DAY", "Day crew", 1, "MECH_DAY")),
        _activity(
            "A02",
            "Isolate equipment",
            day("DAY", "Day crew", 1.5, "MECH_DAY"),
            predecessors=("A01",),
        ),
        _activity(
            "A03",
            "Remove guards",
            day("DAY", "Day crew", 2, "MECH_DAY"),
            predecessors=("A02",),
        ),
        _activity(
            "A04",
            "Execute long joint vessel repair",
            day("JOINT", "MECH + C04", 10, "MECH_DAY", "C04"),
            fixed_start=_ticks(7),
        ),
        _activity(
            "A05",
            "Continuous precision alignment",
            day(
                "CONTINUOUS",
                "Continuous MECH + C04",
                5,
                "MECH_DAY",
                "C04",
                continuity=CONTINUOUS,
            ),
            not_before=_ticks(8),
        ),
        _activity(
            "A06",
            "Clean vessel internals",
            day("DAY", "Day crew", 3, "MECH_DAY"),
            predecessors=("A04",),
        ),
        _activity(
            "A07",
            "Inspect vessel shell",
            inspect("INSPECTION", "Specialist inspection", 2),
            predecessors=("A06",),
        ),
        _activity(
            "A08",
            "Repair vessel shell",
            day("DAY", "Day crew", 5, "MECH_DAY"),
            predecessors=("A07",),
        ),
        _activity(
            "A09",
            "Cure repair lining",
            _mode("CURE", "Clock-driven cure", 8, "ALWAYS", time_basis=ELAPSED),
            predecessors=("A08",),
        ),
        _activity(
            "A10",
            "Strip isolation valve",
            day("DAY", "Day crew", 4, "MECH_DAY"),
            predecessors=("A03",),
        ),
        _activity(
            "A11",
            "Inspect valve components",
            inspect("INSPECTION", "Specialist inspection", 1.5),
            predecessors=("A10",),
        ),
        _activity(
            "A12",
            "Rebuild isolation valve",
            day("DAY", "Day crew", 4, "MECH_DAY"),
            predecessors=("A11",),
        ),
        _activity(
            "A13",
            "Open cooler access",
            day("DAY", "Day crew", 2, "MECH_DAY"),
            predecessors=("A02",),
        ),
        _activity(
            "A14",
            "Repair cooler bundle",
            day("DAY", "Day crew", 4, "MECH_DAY"),
            predecessors=("A13",),
        ),
        _activity(
            "A15",
            "Install replacement cover",
            (
                day(
                    "CRANE",
                    "Short continuous crane method",
                    5,
                    "MECH_DAY",
                    "C04",
                    continuity=CONTINUOUS,
                ),
                _mode(
                    "SEGMENTED",
                    "Longer authorised night method",
                    6,
                    "NIGHT_MECH",
                    "NIGHT_MECH",
                    continuity=SUSPENDABLE,
                ),
            ),
            not_before=4 * TICKS_PER_DAY + _ticks(7),
        ),
        _activity(
            "A16",
            "Reassemble vessel",
            day("DAY", "Day crew", 3, "MECH_DAY"),
            predecessors=("A05", "A09", "A12", "A14", "A15"),
        ),
        _activity(
            "A17",
            "Function test",
            day(
                "JOINT-TEST",
                "Continuous MECH + inspection",
                2,
                "MECH_DAY",
                "INSPECT",
                continuity=CONTINUOUS,
            ),
            predecessors=("A16",),
        ),
        _activity(
            "A18",
            "Return equipment to service",
            _mode("MILESTONE", "Handover", 0, "ALWAYS"),
            predecessors=("A17",),
        ),
    )
    return ExperimentCase(calendars, resources, activities, "A18")


def _scenario_resource_slots(
    case: ExperimentCase,
    scenario: Scenario,
    resource_id: str,
) -> frozenset[int]:
    resource = case.resource_by_id[resource_id]
    slots = set(case.calendar_by_id[resource.calendar_id].slots(case.horizon))
    for outage in scenario.outages:
        if outage.resource_id == resource_id:
            slots.difference_update(range(outage.start, outage.finish))
    return frozenset(slots)


def joint_calendar_slots(
    case: ExperimentCase,
    mode: ModeSpec,
    scenario: Scenario = Scenario("NORMAL"),
) -> frozenset[int]:
    slots = set(case.calendar_by_id[mode.calendar_id].slots(case.horizon))
    for requirement in mode.requirements:
        slots.intersection_update(
            _scenario_resource_slots(case, scenario, requirement.resource_id)
        )
    return frozenset(slots)


def _eligible_slots(
    case: ExperimentCase,
    mode: ModeSpec,
    interpretation: str,
    scenario: Scenario,
) -> frozenset[int]:
    if interpretation == "A" or mode.time_basis == ELAPSED:
        return frozenset(range(case.horizon))
    if interpretation == "B":
        return case.calendar_by_id[mode.calendar_id].slots(case.horizon)
    if interpretation == "C":
        return joint_calendar_slots(case, mode, scenario)
    raise ValueError(f"unknown interpretation {interpretation!r}")


def _merge_slots(slots: list[int]) -> tuple[tuple[int, int], ...]:
    if not slots:
        return ()
    periods: list[tuple[int, int]] = []
    start = slots[0]
    previous = slots[0]
    for slot in slots[1:]:
        if slot != previous + 1:
            periods.append((start, previous + 1))
            start = slot
        previous = slot
    periods.append((start, previous + 1))
    return tuple(periods)


def _placement_from_start(
    start: int,
    processing_ticks: int,
    eligible: frozenset[int],
    continuity: str,
    horizon: int,
) -> tuple[tuple[int, int], ...] | None:
    if processing_ticks == 0:
        return () if start <= horizon else None
    if start not in eligible:
        return None
    if continuity == CONTINUOUS:
        finish = start + processing_ticks
        if finish > horizon or any(slot not in eligible for slot in range(start, finish)):
            return None
        return ((start, finish),)

    occupied: list[int] = []
    for slot in range(start, horizon):
        if slot in eligible:
            occupied.append(slot)
            if len(occupied) == processing_ticks:
                return _merge_slots(occupied)
    return None


def enumerate_placements(
    case: ExperimentCase,
    activity: ActivitySpec,
    mode: ModeSpec,
    interpretation: str,
    scenario: Scenario,
) -> tuple[Placement, ...]:
    eligible = _eligible_slots(case, mode, interpretation, scenario)
    starts = (
        (activity.fixed_start,)
        if activity.fixed_start is not None
        else range(activity.not_before, case.horizon + 1)
    )
    placements: list[Placement] = []
    for start in starts:
        periods = _placement_from_start(
            start,
            mode.processing_ticks,
            eligible,
            CONTINUOUS if interpretation == "A" else mode.continuity,
            case.horizon,
        )
        if periods is None:
            continue
        finish = periods[-1][1] if periods else start
        placements.append(Placement(mode.id, start, finish, periods))
    return tuple(placements)


def _find_mode(activity: ActivitySpec, mode_id: str) -> ModeSpec:
    try:
        return next(mode for mode in activity.modes if mode.id == mode_id)
    except StopIteration as exc:
        raise SchedulingError(f"{activity.id}: unknown mode {mode_id}") from exc


def _plan_signature(entries: tuple[ScheduledEntry, ...]) -> str:
    payload = [
        {
            "activity": entry.activity_id,
            "mode": entry.mode_id,
            "start": entry.start,
            "finish": entry.finish,
            "periods": entry.periods,
        }
        for entry in sorted(entries, key=lambda item: item.activity_id)
    ]
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _model_counts(
    model: cp_model.CpModel,
    optional_intervals: int,
    execution_segments: int,
    solve_ms: float,
) -> ModelComplexity:
    proto = model.proto
    boolean_variables = sum(
        1 for variable in proto.variables if list(variable.domain) == [0, 1]
    )
    return ModelComplexity(
        integer_variables=len(proto.variables) - boolean_variables,
        boolean_variables=boolean_variables,
        optional_intervals=optional_intervals,
        execution_segments=execution_segments,
        constraints=len(proto.constraints),
        solver_calls=1,
        solve_ms=solve_ms,
    )


def solve_plan(
    case: ExperimentCase,
    interpretation: str,
    scenario: Scenario = Scenario("NORMAL"),
) -> PlanResult:
    """Compile authorised placements, then let CP-SAT choose mode, timing and sequence."""

    model = cp_model.CpModel()
    starts: dict[str, cp_model.IntVar] = {}
    finishes: dict[str, cp_model.IntVar] = {}
    placement_literals: dict[tuple[str, int], cp_model.BoolVar] = {}
    placements_by_activity: dict[str, tuple[Placement, ...]] = {}
    fixed_by_activity = scenario.fixed_by_activity
    resource_intervals: dict[str, list[cp_model.IntervalVar]] = {
        resource.id: [] for resource in case.resources
    }
    resource_demands: dict[str, list[int]] = {
        resource.id: [] for resource in case.resources
    }
    optional_intervals = 0
    execution_segments = 0

    for activity in case.activities:
        start_var = model.new_int_var(0, case.horizon, f"start_{activity.id}")
        finish_var = model.new_int_var(0, case.horizon, f"finish_{activity.id}")
        starts[activity.id] = start_var
        finishes[activity.id] = finish_var
        fixed = fixed_by_activity.get(activity.id)
        if fixed is not None:
            mode = _find_mode(activity, fixed.mode_id)
            model.add(start_var == fixed.start)
            model.add(finish_var == fixed.finish)
            placements_by_activity[activity.id] = (
                Placement(mode.id, fixed.start, fixed.finish, fixed.periods),
            )
            for segment_index, (segment_start, segment_finish) in enumerate(
                fixed.periods
            ):
                execution_segments += 1
                if not mode.requirements:
                    continue
                interval = model.new_interval_var(
                    segment_start,
                    segment_finish - segment_start,
                    segment_finish,
                    f"fixed_{activity.id}_{segment_index}",
                )
                for requirement in mode.requirements:
                    resource_intervals[requirement.resource_id].append(interval)
                    resource_demands[requirement.resource_id].append(
                        requirement.demand
                    )
            continue

        placements: list[Placement] = []
        for mode in activity.modes:
            placements.extend(
                enumerate_placements(
                    case,
                    activity,
                    mode,
                    interpretation,
                    scenario,
                )
            )
        if not placements:
            raise SchedulingError(
                f"{interpretation}/{scenario.id}: {activity.id} has no legal placement"
            )
        placements_by_activity[activity.id] = tuple(placements)
        literals: list[cp_model.BoolVar] = []
        for option_index, placement in enumerate(placements):
            literal = model.new_bool_var(f"place_{activity.id}_{option_index}")
            placement_literals[(activity.id, option_index)] = literal
            literals.append(literal)
            model.add(start_var == placement.start).only_enforce_if(literal)
            model.add(finish_var == placement.finish).only_enforce_if(literal)
            mode = _find_mode(activity, placement.mode_id)
            for segment_index, (segment_start, segment_finish) in enumerate(
                placement.periods
            ):
                execution_segments += 1
                if not mode.requirements:
                    continue
                interval = model.new_optional_interval_var(
                    segment_start,
                    segment_finish - segment_start,
                    segment_finish,
                    literal,
                    f"segment_{activity.id}_{option_index}_{segment_index}",
                )
                optional_intervals += 1
                for requirement in mode.requirements:
                    resource_intervals[requirement.resource_id].append(interval)
                    resource_demands[requirement.resource_id].append(
                        requirement.demand
                    )
        model.add_exactly_one(literals)

    for activity in case.activities:
        for predecessor_id in activity.predecessors:
            model.add(starts[activity.id] >= finishes[predecessor_id])

    for resource in case.resources:
        intervals = resource_intervals[resource.id]
        if intervals:
            model.add_cumulative(
                intervals,
                resource_demands[resource.id],
                resource.capacity,
            )

    mode_tie = sum(
        mode_index * placement_literals[(activity.id, option_index)]
        for activity in case.activities
        if activity.id not in fixed_by_activity
        for option_index, placement in enumerate(placements_by_activity[activity.id])
        for mode_index, mode in enumerate(activity.modes)
        if placement.mode_id == mode.id
    )
    weighted_starts = sum(
        (index + 1) * starts[activity.id]
        for index, activity in enumerate(case.activities)
    )
    secondary_bound = (
        case.horizon * sum(range(1, len(case.activities) + 1))
        + sum(len(activity.modes) - 1 for activity in case.activities)
    )
    model.minimize(
        finishes[case.objective_activity_id] * (secondary_bound + 1)
        + weighted_starts
        + mode_tie
    )

    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    started = perf_counter()
    status = solver.solve(model)
    solve_ms = (perf_counter() - started) * 1000
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise SchedulingError(
            f"{interpretation}/{scenario.id}: {solver.status_name(status)}"
        )
    if status != cp_model.OPTIMAL:
        raise SchedulingError(
            f"{interpretation}/{scenario.id}: optimality was not proven"
        )

    entries: list[ScheduledEntry] = []
    for activity in case.activities:
        if activity.id in fixed_by_activity:
            placement = placements_by_activity[activity.id][0]
        else:
            options = placements_by_activity[activity.id]
            placement = next(
                option
                for option_index, option in enumerate(options)
                if solver.value(placement_literals[(activity.id, option_index)])
            )
        mode = _find_mode(activity, placement.mode_id)
        entries.append(
            ScheduledEntry(
                activity.id,
                activity.name,
                mode.id,
                placement.start,
                placement.finish,
                placement.periods,
                tuple(requirement.resource_id for requirement in mode.requirements),
            )
        )
    ordered = tuple(sorted(entries, key=lambda item: item.activity_id))
    validation = validate_physical_plan(
        case,
        interpretation,
        scenario,
        ordered,
    )
    return PlanResult(
        interpretation,
        scenario.id,
        ordered,
        solver.value(finishes[case.objective_activity_id]),
        solver.status_name(status),
        _model_counts(
            model,
            optional_intervals,
            execution_segments,
            solve_ms,
        ),
        _plan_signature(ordered),
        validation,
    )


def validate_physical_plan(
    case: ExperimentCase,
    interpretation: str,
    scenario: Scenario,
    entries: tuple[ScheduledEntry, ...],
) -> PhysicalValidation:
    """Validate domain execution independently of the CP-SAT formulation."""

    by_id = {entry.activity_id: entry for entry in entries}
    invalid: set[str] = set()
    non_working: set[tuple[str, int]] = set()
    resource_calendar: set[tuple[str, str, int]] = set()
    joint_calendar: set[tuple[str, int]] = set()
    continuous: set[str] = set()
    processing: set[str] = set()
    precedence: set[tuple[str, str]] = set()
    capacity: set[tuple[str, int]] = set()

    resource_use: dict[tuple[str, int], list[tuple[str, int]]] = {}
    for activity in case.activities:
        entry = by_id[activity.id]
        mode = _find_mode(activity, entry.mode_id)
        occupied = [
            slot
            for start, finish in entry.periods
            for slot in range(start, finish)
        ]
        if len(occupied) != mode.processing_ticks:
            processing.add(activity.id)
            invalid.add(activity.id)
        if mode.continuity == CONTINUOUS and mode.processing_ticks:
            if (
                len(entry.periods) != 1
                or entry.periods[0][1] - entry.periods[0][0]
                != mode.processing_ticks
            ):
                continuous.add(activity.id)
                invalid.add(activity.id)

        if mode.time_basis == PRODUCTIVE:
            activity_slots = case.calendar_by_id[mode.calendar_id].slots(case.horizon)
            required_slots = {
                requirement.resource_id: _scenario_resource_slots(
                    case,
                    scenario,
                    requirement.resource_id,
                )
                for requirement in mode.requirements
            }
            for slot in occupied:
                if slot not in activity_slots:
                    non_working.add((activity.id, slot))
                    invalid.add(activity.id)
                if any(slot not in slots for slots in required_slots.values()):
                    joint_calendar.add((activity.id, slot))
                    invalid.add(activity.id)
                for resource_id, slots in required_slots.items():
                    if slot not in slots:
                        resource_calendar.add((activity.id, resource_id, slot))
                        invalid.add(activity.id)

        for requirement in mode.requirements:
            for slot in occupied:
                resource_use.setdefault((requirement.resource_id, slot), []).append(
                    (activity.id, requirement.demand)
                )
        for predecessor_id in activity.predecessors:
            if entry.start < by_id[predecessor_id].finish:
                precedence.add((predecessor_id, activity.id))
                invalid.update((predecessor_id, activity.id))

    for (resource_id, slot), uses in resource_use.items():
        if sum(demand for _, demand in uses) > case.resource_by_id[resource_id].capacity:
            capacity.add((resource_id, slot))
            invalid.update(activity_id for activity_id, _ in uses)

    return PhysicalValidation(
        tuple(sorted(invalid)),
        len(non_working),
        len(resource_calendar),
        len(joint_calendar),
        len(continuous),
        len(processing),
        len(precedence),
        len(capacity),
    )


def validate_remaining_work(
    case: ExperimentCase,
    result: RemainingWorkResult,
) -> bool:
    """Check history and forecast accounting without trusting the compiler."""

    activity = case.activity_by_id["A04"]
    mode = _find_mode(activity, "JOINT")
    actual_ticks = sum(
        finish - start for start, finish in result.actual_periods
    )
    future_ticks = sum(
        finish - start for start, finish in result.future_periods
    )
    scenario = Scenario("ACCOUNTING-CHECK", (result.outage,))
    available = joint_calendar_slots(case, mode, scenario)
    future_slots = {
        slot
        for start, finish in result.future_periods
        for slot in range(start, finish)
    }
    expected_remaining = (
        mode.processing_ticks
        - result.actual_productive_ticks
        + result.explicit_added_work_ticks
    )
    return (
        result.actual_start == result.actual_periods[0][0]
        and actual_ticks == result.actual_productive_ticks
        and result.actual_periods[-1][1] <= result.outage.start
        and result.remaining_productive_ticks == expected_remaining
        and future_ticks == result.remaining_productive_ticks
        and future_slots <= available
        and all(
            finish <= result.outage.start or start >= result.outage.finish
            for start, finish in result.future_periods
        )
        and result.forecast_finish == result.future_periods[-1][1]
    )


def _allocate_from(
    eligible: frozenset[int],
    start: int,
    processing_ticks: int,
    horizon: int,
) -> tuple[tuple[int, int], ...]:
    periods = _placement_from_start(
        next(slot for slot in range(start, horizon) if slot in eligible),
        processing_ticks,
        eligible,
        SUSPENDABLE,
        horizon,
    )
    if periods is None:
        raise SchedulingError("remaining productive work does not fit in the horizon")
    return periods


def build_remaining_work_result(
    case: ExperimentCase,
    *,
    restart_hours: float = 0,
) -> RemainingWorkResult:
    activity = case.activity_by_id["A04"]
    mode = _find_mode(activity, "JOINT")
    outage = Outage("C04", _ticks(10), _ticks(14), "Trusted C04 outage")
    scenario = Scenario("LIVE-OUTAGE", (outage,))
    actual_periods = ((_ticks(7), _ticks(10)),)
    actual_productive = sum(finish - start for start, finish in actual_periods)
    added = _ticks(restart_hours)
    remaining = mode.processing_ticks - actual_productive + added
    future = _allocate_from(
        joint_calendar_slots(case, mode, scenario),
        outage.finish,
        remaining,
        case.horizon,
    )
    return RemainingWorkResult(
        actual_start=_ticks(7),
        actual_periods=actual_periods,
        actual_productive_ticks=actual_productive,
        outage=outage,
        remaining_productive_ticks=remaining,
        explicit_added_work_ticks=added,
        future_periods=future,
        forecast_finish=future[-1][1],
    )


def _changed_state_scenario(
    no_restart: RemainingWorkResult,
) -> Scenario:
    mode_outage = Outage(
        "C04",
        4 * TICKS_PER_DAY + _ticks(7),
        4 * TICKS_PER_DAY + _ticks(17),
        "Changed condition for authorised method comparison",
    )
    fixed = FixedExecution(
        "A04",
        "JOINT",
        no_restart.actual_start,
        no_restart.actual_periods + no_restart.future_periods,
    )
    return Scenario(
        "TRUSTED-CHANGED-STATE",
        (no_restart.outage, mode_outage),
        (fixed,),
    )


def run_experiment() -> ExperimentResult:
    case = build_case()
    normal = Scenario("NORMAL")
    plans = tuple(
        solve_plan(case, interpretation, normal)
        for interpretation in ("A", "B", "C")
    )
    repeated_c = solve_plan(case, "C", normal)
    c_plan = plans[2]
    finish_differences = tuple(
        activity.id
        for activity in case.activities
        if len({plan.by_id[activity.id].finish for plan in plans}) > 1
    )

    no_restart = build_remaining_work_result(case)
    with_restart = build_remaining_work_result(case, restart_hours=1)
    changed_plan = solve_plan(
        case,
        "C",
        _changed_state_scenario(no_restart),
    )
    normal_mode = c_plan.by_id["A15"].mode_id
    outage_mode = changed_plan.by_id["A15"].mode_id

    a, b, c = plans
    sentinel_finishes = tuple(plan.by_id["A04"].finish for plan in plans)
    continuous_entry = c.by_id["A05"]
    outage_accounting = (
        validate_remaining_work(case, no_restart)
        and validate_remaining_work(case, with_restart)
        and no_restart.actual_start == _ticks(7)
        and no_restart.actual_productive_ticks == _ticks(3)
        and no_restart.remaining_productive_ticks == _ticks(7)
        and no_restart.future_periods
        == (
            (_ticks(14), _ticks(17)),
            (TICKS_PER_DAY + _ticks(7), TICKS_PER_DAY + _ticks(11)),
        )
        and with_restart.remaining_productive_ticks == _ticks(8)
        and with_restart.explicit_added_work_ticks == _ticks(1)
    )
    supported = (
        sentinel_finishes == (_ticks(17), _ticks(17.5), TICKS_PER_DAY + _ticks(7.5))
        and not a.validation.valid
        and a.validation.non_working_slots > 0
        and not b.validation.valid
        and b.validation.non_working_slots == 0
        and b.validation.resource_calendar_violations > 0
        and c.validation.valid
        and len(continuous_entry.periods) == 1
        and continuous_entry.start > _ticks(8)
        and continuous_entry.finish - continuous_entry.start == _ticks(5)
        and outage_accounting
        and normal_mode == "CRANE"
        and outage_mode == "SEGMENTED"
        and changed_plan.validation.valid
        and c.signature == repeated_c.signature
    )
    return ExperimentResult(
        case,
        plans,
        repeated_c.signature,
        c.signature == repeated_c.signature,
        finish_differences,
        no_restart,
        with_restart,
        changed_plan,
        normal_mode,
        outage_mode,
        not supported,
    )


def format_tick(tick: int) -> str:
    day = tick // TICKS_PER_DAY + 1
    within_day = tick % TICKS_PER_DAY
    hour = within_day // TICKS_PER_HOUR
    minute = 30 if within_day % TICKS_PER_HOUR else 0
    return f"Day {day} {hour:02d}:{minute:02d}"


def _hours(ticks: int) -> str:
    return f"{ticks / TICKS_PER_HOUR:g}h"


def _periods(periods: tuple[tuple[int, int], ...]) -> str:
    return ", ".join(
        f"{format_tick(start)} -> {format_tick(finish)}"
        for start, finish in periods
    )


def _plan_line(plan: PlanResult) -> str:
    validation = plan.validation
    size = plan.complexity
    return (
        f"{plan.interpretation}: finish {format_tick(plan.project_finish)}; "
        f"invalid activities {len(validation.invalid_activity_ids)}; "
        f"non-working slots {validation.non_working_slots}; "
        f"resource-calendar violations {validation.resource_calendar_violations}; "
        f"joint-calendar violations {validation.joint_calendar_violations}; "
        f"continuous violations {validation.continuous_activity_violations}; "
        f"vars int/bool {size.integer_variables}/{size.boolean_variables}; "
        f"intervals/segments {size.optional_intervals}/{size.execution_segments}; "
        f"constraints {size.constraints}; calls {size.solver_calls}; "
        f"solve {size.solve_ms:.1f} ms; signature {plan.signature[:12]}"
    )


def render(result: ExperimentResult) -> str:
    a, b, c = result.plans
    lines = [
        "PRODUCTIVE WORKING-TIME FALSIFICATION EXPERIMENT",
        (
            f"{len(result.case.activities)} activities; 30-minute resolution; "
            "finite authorised placements compiled to CP-SAT."
        ),
        "A = elapsed spans; B = primary work calendar; C = joint required-resource availability.",
        "",
        "A/B/C MEASURED RESULTS",
        _plan_line(a),
        _plan_line(b),
        _plan_line(c),
        (
            f"Activities with differing finishes: {len(result.finish_difference_ids)} "
            f"({', '.join(result.finish_difference_ids)})"
        ),
        "",
        "10h MECH + C04 SENTINEL",
        f"A: {_periods(a.by_id['A04'].periods)}",
        f"B: {_periods(b.by_id['A04'].periods)}",
        f"C: {_periods(c.by_id['A04'].periods)}",
        "C04 is occupied only in those C execution periods, not through suspension gaps.",
        "",
        "5h CONTINUOUS SENTINEL",
        (
            f"C: {_periods(c.by_id['A05'].periods)}; it waits for one complete "
            "joint window and is not split across lunch."
        ),
        "",
        "TRUSTED OUTAGE ACCOUNTING",
        (
            f"Accepted start {format_tick(result.outage_no_restart.actual_start)}; "
            "accepted productive history "
            f"{_hours(result.outage_no_restart.actual_productive_ticks)}."
        ),
        (
            f"C04 unavailable {format_tick(result.outage_no_restart.outage.start)} -> "
            f"{format_tick(result.outage_no_restart.outage.finish)}; remaining productive work "
            f"{_hours(result.outage_no_restart.remaining_productive_ticks)}; future execution "
            f"{_periods(result.outage_no_restart.future_periods)}."
        ),
        (
            f"Explicit rerig +{_hours(result.outage_with_restart.explicit_added_work_ticks)} "
            "raises remaining work to "
            f"{_hours(result.outage_with_restart.remaining_productive_ticks)} "
            f"and finish to {format_tick(result.outage_with_restart.forecast_finish)}."
        ),
        "Availability loss alone adds no processing work.",
        "",
        "AUTHORISED METHOD CHOICE",
        (
            f"Normal joint calendars: A15={result.normal_mode}; "
            f"{_periods(c.by_id['A15'].periods)}."
        ),
        (
            f"Trusted changed state: A15={result.outage_mode}; "
            f"{_periods(result.changed_state_plan.by_id['A15'].periods)}; project finish "
            f"{format_tick(result.changed_state_plan.project_finish)}."
        ),
        "The solver selected only CRANE or SEGMENTED, the two authorised choices.",
        "",
        f"Repeated C solve canonical: {result.repeat_canonical}",
        (
            "FALSIFICATION RESULT: FALSIFIED"
            if result.falsified
            else (
                "FALSIFICATION RESULT: NOT FALSIFIED — A was physically impossible, "
                "B fixed primary working-time counting but missed mandatory-resource "
                "availability, and C produced a physically executable deterministic plan."
            )
        ),
        (
            "Interpretation: CP-SAT remains adequate for this bounded finite-placement "
            "compiler. This does not settle permanent calendar semantics, production "
            "scale, or cross-platform/version reproducibility."
        ),
    ]
    return "\n".join(lines)


def main() -> int:
    result = run_experiment()
    print(render(result))
    return 1 if result.falsified else 0


if __name__ == "__main__":
    raise SystemExit(main())
