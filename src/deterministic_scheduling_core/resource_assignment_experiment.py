from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from itertools import combinations, product
import json
from time import perf_counter

from ortools.sat.python import cp_model

from deterministic_scheduling_core.errors import SchedulingError
from deterministic_scheduling_core.working_time_experiment import (
    CONTINUOUS,
    SUSPENDABLE,
    TICKS_PER_DAY,
    TICKS_PER_HOUR,
    WorkCalendar,
    format_tick,
)


HORIZON = 3 * TICKS_PER_DAY
EXACT_FEASIBLE = "PROVEN_FEASIBLE"
EXACT_INFEASIBLE = "PROVEN_INFEASIBLE"
EXACT_INCONCLUSIVE = "INCONCLUSIVE"


@dataclass(frozen=True, slots=True)
class PhysicalResource:
    id: str
    capabilities: tuple[str, ...]
    calendar_id: str
    capacity: int = 1


@dataclass(frozen=True, slots=True)
class AvailabilityException:
    resource_id: str
    start: int
    finish: int
    reason: str


@dataclass(frozen=True, slots=True)
class RequirementSlot:
    id: str
    pool_ids: tuple[str, ...]
    eligible_resource_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ActivitySpec:
    id: str
    name: str
    processing_ticks: int
    calendar_id: str
    requirements: tuple[RequirementSlot, ...] = ()
    predecessors: tuple[str, ...] = ()
    not_before: int = 0
    continuity: str = SUSPENDABLE


@dataclass(frozen=True, slots=True)
class ExperimentCase:
    calendars: tuple[WorkCalendar, ...]
    resources: tuple[PhysicalResource, ...]
    exceptions: tuple[AvailabilityException, ...]
    activities: tuple[ActivitySpec, ...]
    objective_activity_id: str
    horizon: int = HORIZON

    @property
    def calendar_by_id(self) -> dict[str, WorkCalendar]:
        return {calendar.id: calendar for calendar in self.calendars}

    @property
    def resource_by_id(self) -> dict[str, PhysicalResource]:
        return {resource.id: resource for resource in self.resources}

    @property
    def activity_by_id(self) -> dict[str, ActivitySpec]:
        return {activity.id: activity for activity in self.activities}


@dataclass(frozen=True, slots=True)
class CandidatePlacement:
    start: int
    finish: int
    periods: tuple[tuple[int, int], ...]
    assignments: tuple[str | None, ...]


@dataclass(frozen=True, slots=True)
class ScheduledEntry:
    activity_id: str
    start: int
    finish: int
    periods: tuple[tuple[int, int], ...]
    assignments: tuple[tuple[str, str | None], ...]

    @property
    def assignment_by_requirement(self) -> dict[str, str | None]:
        return dict(self.assignments)


@dataclass(frozen=True, slots=True)
class ModelMetrics:
    integer_variables: int
    boolean_variables: int
    assignment_variables: int
    optional_intervals: int
    constraints: int
    model_build_ms: float
    solve_ms: float
    solver_calls: int


@dataclass(frozen=True, slots=True)
class CheckerResult:
    exact_status: str
    allocation: tuple[tuple[str, str, str], ...]
    reason: str
    productive_time_violations: int
    calendar_violations: int
    qualification_violations: int
    capacity_violations: int
    precedence_violations: int
    search_nodes: int
    greedy_status: str
    greedy_reason: str

    @property
    def physically_assignable(self) -> bool:
        return self.exact_status == EXACT_FEASIBLE


@dataclass(frozen=True, slots=True)
class PlanResult:
    approach: str
    entries: tuple[ScheduledEntry, ...]
    project_finish: int
    timing_tie_break: int
    solver_status: str
    solver_proof: str
    identity_level_requirements: int
    deferred_requirements: int
    metrics: ModelMetrics
    checker: CheckerResult
    canonical_signature: str

    @property
    def by_id(self) -> dict[str, ScheduledEntry]:
        return {entry.activity_id: entry for entry in self.entries}

    @property
    def objective_result(self) -> tuple[int, int]:
        return self.project_finish, self.timing_tie_break


@dataclass(frozen=True, slots=True)
class GreedyDiagnostic:
    greedy_status: str
    greedy_reason: str
    exact_status: str
    exact_allocation: tuple[tuple[str, str, str], ...]


@dataclass(frozen=True, slots=True)
class ExperimentResult:
    case: ExperimentCase
    plans: tuple[PlanResult, ...]
    repeated_c_signature: str
    repeated_c_objective: tuple[int, int]
    shared_capacity_diagnostic: PlanResult
    scarce_specialist_diagnostic: GreedyDiagnostic
    planner_facts: tuple[tuple[str, int], ...]

    @property
    def by_approach(self) -> dict[str, PlanResult]:
        return {plan.approach: plan for plan in self.plans}


def _ticks(hours: float) -> int:
    ticks = hours * TICKS_PER_HOUR
    if not float(ticks).is_integer():
        raise ValueError("the experiment uses 30-minute resolution")
    return int(ticks)


def _req(
    requirement_id: str,
    pool_ids: str | tuple[str, ...],
    eligible: tuple[str, ...],
) -> RequirementSlot:
    pools = (pool_ids,) if isinstance(pool_ids, str) else pool_ids
    return RequirementSlot(requirement_id, pools, eligible)


def build_case() -> ExperimentCase:
    """Build the disclosed 14-activity, 30-minute assignment fixture."""

    day = WorkCalendar(
        "DAY",
        ((_ticks(7), _ticks(12)), (_ticks(12.5), _ticks(17))),
    )
    night = WorkCalendar("NIGHT", ((_ticks(18), _ticks(24)),))
    always = WorkCalendar("ALWAYS", ((0, TICKS_PER_DAY),))
    resources = (
        PhysicalResource("M1", ("MECH",), "DAY"),
        PhysicalResource("M2", ("MECH", "INSPECT", "SPECIALIST"), "DAY"),
        PhysicalResource("N1", ("MECH",), "NIGHT"),
        PhysicalResource("R1", ("RIGGER",), "DAY"),
        PhysicalResource("R2", ("RIGGER",), "DAY"),
    )
    mech = ("M1", "M2", "N1")
    inspect = ("M2",)
    specialist = ("M2",)
    riggers = ("R1", "R2")
    activities = (
        ActivitySpec(
            "A01",
            "Overlapping mechanical work 1",
            _ticks(2),
            "DAY",
            (_req("MECH", "MECH", mech),),
        ),
        ActivitySpec(
            "A02",
            "Overlapping mechanical work 2",
            _ticks(2),
            "DAY",
            (_req("MECH", "MECH", mech),),
        ),
        ActivitySpec(
            "A03",
            "Overlapping inspection",
            _ticks(2),
            "DAY",
            (_req("INSPECT", "INSPECT", inspect),),
        ),
        ActivitySpec(
            "A04",
            "Overlapping branch gate",
            0,
            "ALWAYS",
            predecessors=("A01", "A02", "A03"),
        ),
        ActivitySpec(
            "A05",
            "Ordinary mechanical work beside specialist",
            _ticks(2),
            "DAY",
            (_req("MECH", "MECH", mech),),
            predecessors=("A04",),
        ),
        ActivitySpec(
            "A06",
            "Scarce specialist operation",
            _ticks(2),
            "DAY",
            (_req("SPECIALIST", "SPECIALIST", specialist),),
            predecessors=("A04",),
        ),
        ActivitySpec(
            "A07",
            "Scarce specialist branch gate",
            0,
            "ALWAYS",
            predecessors=("A05", "A06"),
        ),
        ActivitySpec(
            "A08",
            "Night mechanical operation",
            _ticks(2),
            "NIGHT",
            (_req("MECH", "MECH", mech),),
            predecessors=("A07",),
            not_before=_ticks(18),
        ),
        ActivitySpec(
            "A09",
            "Day 2 dual-qualified specialist sign-off",
            _ticks(3),
            "DAY",
            (_req("DUAL", ("MECH", "SPECIALIST"), specialist),),
            predecessors=("A08",),
            not_before=TICKS_PER_DAY + _ticks(7),
        ),
        ActivitySpec(
            "A10",
            "Rigging lift 1",
            _ticks(3),
            "DAY",
            (_req("RIGGER", "RIGGER", riggers),),
            predecessors=("A04",),
            not_before=_ticks(12.5),
        ),
        ActivitySpec(
            "A11",
            "Rigging lift 2",
            _ticks(3),
            "DAY",
            (_req("RIGGER", "RIGGER", riggers),),
            predecessors=("A04",),
            not_before=_ticks(12.5),
        ),
        ActivitySpec(
            "A12",
            "Rigging branch gate",
            0,
            "ALWAYS",
            predecessors=("A10", "A11"),
        ),
        ActivitySpec(
            "A13",
            "Two-person mechanical and inspection closeout",
            _ticks(1),
            "DAY",
            (
                _req("MECH", "MECH", mech),
                _req("INSPECT", "INSPECT", inspect),
            ),
            predecessors=("A09", "A12"),
        ),
        ActivitySpec(
            "A14",
            "Controlling handoff",
            0,
            "ALWAYS",
            predecessors=("A13",),
        ),
    )
    exception = AvailabilityException(
        "M2",
        TICKS_PER_DAY + _ticks(8),
        TICKS_PER_DAY + _ticks(10),
        "Synthetic fixture: M2 unavailable on Day 2 from 08:00 to 10:00",
    )
    return ExperimentCase(
        (day, night, always),
        resources,
        (exception,),
        activities,
        "A14",
    )


def _resource_slots(case: ExperimentCase, resource_id: str) -> frozenset[int]:
    resource = case.resource_by_id[resource_id]
    slots = set(case.calendar_by_id[resource.calendar_id].slots(case.horizon))
    for exception in case.exceptions:
        if exception.resource_id == resource_id:
            slots.difference_update(range(exception.start, exception.finish))
    return frozenset(slots)


def _pool_capacity(case: ExperimentCase, pool_id: str, slot: int) -> int:
    return sum(
        resource.capacity
        for resource in case.resources
        if pool_id in resource.capabilities and slot in _resource_slots(case, resource.id)
    )


def _merge_slots(slots: list[int]) -> tuple[tuple[int, int], ...]:
    if not slots:
        return ()
    periods: list[tuple[int, int]] = []
    start = previous = slots[0]
    for slot in slots[1:]:
        if slot != previous + 1:
            periods.append((start, previous + 1))
            start = slot
        previous = slot
    periods.append((start, previous + 1))
    return tuple(periods)


def _periods_from_start(
    start: int,
    processing_ticks: int,
    eligible_slots: frozenset[int],
    continuity: str,
    horizon: int,
) -> tuple[tuple[int, int], ...] | None:
    if processing_ticks == 0:
        return () if start <= horizon else None
    if start not in eligible_slots:
        return None
    if continuity == CONTINUOUS:
        finish = start + processing_ticks
        if finish > horizon or any(
            slot not in eligible_slots for slot in range(start, finish)
        ):
            return None
        return ((start, finish),)
    productive: list[int] = []
    for slot in range(start, horizon):
        if slot in eligible_slots:
            productive.append(slot)
            if len(productive) == processing_ticks:
                return _merge_slots(productive)
    return None


def _is_deferred(approach: str, requirement: RequirementSlot) -> bool:
    return approach == "A" or (
        approach == "C" and requirement.pool_ids == ("RIGGER",)
    )


def _assignment_combinations(
    activity: ActivitySpec,
    approach: str,
) -> tuple[tuple[str | None, ...], ...]:
    choices = [
        (None,) if _is_deferred(approach, requirement) else requirement.eligible_resource_ids
        for requirement in activity.requirements
    ]
    combinations_found: list[tuple[str | None, ...]] = []
    for assignments in product(*choices) if choices else [()]:
        named = [resource_id for resource_id in assignments if resource_id is not None]
        if len(named) == len(set(named)):
            combinations_found.append(assignments)
    return tuple(combinations_found)


def _eligible_execution_slots(
    case: ExperimentCase,
    activity: ActivitySpec,
    approach: str,
    assignments: tuple[str | None, ...],
) -> frozenset[int]:
    slots = set(case.calendar_by_id[activity.calendar_id].slots(case.horizon))
    if approach == "A":
        demand_by_pool: dict[str, int] = {}
        for requirement in activity.requirements:
            for pool_id in requirement.pool_ids:
                demand_by_pool[pool_id] = demand_by_pool.get(pool_id, 0) + 1
        slots = {
            slot
            for slot in slots
            if all(
                _pool_capacity(case, pool_id, slot) >= demand
                for pool_id, demand in demand_by_pool.items()
            )
        }
    else:
        deferred_demand: dict[str, int] = {}
        for requirement, resource_id in zip(activity.requirements, assignments):
            if resource_id is None:
                for pool_id in requirement.pool_ids:
                    deferred_demand[pool_id] = deferred_demand.get(pool_id, 0) + 1
            else:
                slots.intersection_update(_resource_slots(case, resource_id))
        slots = {
            slot
            for slot in slots
            if all(
                _pool_capacity(case, pool_id, slot) >= demand
                for pool_id, demand in deferred_demand.items()
            )
        }
    return frozenset(slots)


def _candidate_placements(
    case: ExperimentCase,
    activity: ActivitySpec,
    approach: str,
) -> tuple[CandidatePlacement, ...]:
    candidates: list[CandidatePlacement] = []
    for assignments in _assignment_combinations(activity, approach):
        eligible = _eligible_execution_slots(case, activity, approach, assignments)
        for start in range(activity.not_before, case.horizon + 1):
            periods = _periods_from_start(
                start,
                activity.processing_ticks,
                eligible,
                activity.continuity,
                case.horizon,
            )
            if periods is None:
                continue
            finish = periods[-1][1] if periods else start
            candidates.append(CandidatePlacement(start, finish, periods, assignments))
    return tuple(candidates)


def _occupied(periods: tuple[tuple[int, int], ...]) -> tuple[int, ...]:
    return tuple(slot for start, finish in periods for slot in range(start, finish))


def _add_pool_slot_constraints(
    model: cp_model.CpModel,
    case: ExperimentCase,
    placements_by_activity: dict[str, tuple[CandidatePlacement, ...]],
    literals: dict[tuple[str, int], cp_model.BoolVar],
    pool_ids: tuple[str, ...],
) -> None:
    for pool_id in pool_ids:
        for slot in range(case.horizon):
            terms = []
            for activity in case.activities:
                demand = sum(
                    pool_id in requirement.pool_ids
                    for requirement in activity.requirements
                    if _is_deferred("A", requirement)
                )
                if not demand:
                    continue
                for option_index, placement in enumerate(
                    placements_by_activity[activity.id]
                ):
                    if slot in _occupied(placement.periods):
                        terms.append(demand * literals[(activity.id, option_index)])
            if terms:
                model.add(sum(terms) <= _pool_capacity(case, pool_id, slot))


def _add_shared_multiskill_constraint(
    model: cp_model.CpModel,
    case: ExperimentCase,
    placements_by_activity: dict[str, tuple[CandidatePlacement, ...]],
    literals: dict[tuple[str, int], cp_model.BoolVar],
) -> None:
    shared_resources = {"M1", "M2"}
    for slot in range(case.horizon):
        capacity = sum(
            slot in _resource_slots(case, resource_id)
            for resource_id in shared_resources
        )
        terms = []
        for activity in case.activities:
            demand = 0
            for requirement in activity.requirements:
                available_candidates = {
                    resource_id
                    for resource_id in requirement.eligible_resource_ids
                    if slot in _resource_slots(case, resource_id)
                }
                if available_candidates and available_candidates <= shared_resources:
                    demand += 1
            if not demand:
                continue
            for option_index, placement in enumerate(
                placements_by_activity[activity.id]
            ):
                if slot in _occupied(placement.periods):
                    terms.append(demand * literals[(activity.id, option_index)])
        if terms:
            model.add(sum(terms) <= capacity)


def _model_metrics(
    model: cp_model.CpModel,
    *,
    assignment_variables: int,
    optional_intervals: int,
    build_ms: float,
    solve_ms: float,
    solver_calls: int,
) -> ModelMetrics:
    proto = model.proto
    boolean_variables = sum(
        list(variable.domain) == [0, 1] for variable in proto.variables
    )
    return ModelMetrics(
        len(proto.variables) - boolean_variables,
        boolean_variables,
        assignment_variables,
        optional_intervals,
        len(proto.constraints),
        build_ms,
        solve_ms,
        solver_calls,
    )


def _signature(entries: tuple[ScheduledEntry, ...]) -> str:
    payload = [
        {
            "activity": entry.activity_id,
            "start": entry.start,
            "finish": entry.finish,
            "periods": entry.periods,
            "assignments": entry.assignments,
        }
        for entry in entries
    ]
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def solve_approach(
    case: ExperimentCase,
    approach: str,
    *,
    shared_multiskill_capacity: bool = False,
) -> PlanResult:
    """Solve A, B or C with the same finish-first timing policy."""

    if approach not in {"A", "B", "C"}:
        raise ValueError(f"unknown approach {approach!r}")
    build_started = perf_counter()
    model = cp_model.CpModel()
    starts: dict[str, cp_model.IntVar] = {}
    finishes: dict[str, cp_model.IntVar] = {}
    placements_by_activity: dict[str, tuple[CandidatePlacement, ...]] = {}
    literals: dict[tuple[str, int], cp_model.BoolVar] = {}
    assignment_vars: dict[tuple[str, str, str], cp_model.BoolVar] = {}
    named_intervals: dict[str, list[cp_model.IntervalVar]] = {
        resource.id: [] for resource in case.resources
    }
    rigger_pool_intervals: list[cp_model.IntervalVar] = []
    optional_intervals = 0

    for activity in case.activities:
        placements = _candidate_placements(case, activity, approach)
        if not placements:
            raise SchedulingError(f"{approach}: no placement for {activity.id}")
        placements_by_activity[activity.id] = placements
        starts[activity.id] = model.new_int_var(0, case.horizon, f"start_{activity.id}")
        finishes[activity.id] = model.new_int_var(
            0, case.horizon, f"finish_{activity.id}"
        )
        activity_literals: list[cp_model.BoolVar] = []
        for option_index, placement in enumerate(placements):
            literal = model.new_bool_var(f"place_{activity.id}_{option_index}")
            literals[(activity.id, option_index)] = literal
            activity_literals.append(literal)
            model.add(starts[activity.id] == placement.start).only_enforce_if(literal)
            model.add(finishes[activity.id] == placement.finish).only_enforce_if(literal)
            named = sorted(
                {resource_id for resource_id in placement.assignments if resource_id}
            )
            for resource_id in named:
                for period_index, (start, finish) in enumerate(placement.periods):
                    interval = model.new_optional_interval_var(
                        start,
                        finish - start,
                        finish,
                        literal,
                        f"named_{resource_id}_{activity.id}_{option_index}_{period_index}",
                    )
                    named_intervals[resource_id].append(interval)
                    optional_intervals += 1
            if approach == "C":
                deferred_riggers = sum(
                    requirement.pool_ids == ("RIGGER",)
                    and assignment is None
                    for requirement, assignment in zip(
                        activity.requirements, placement.assignments
                    )
                )
                for deferred_index in range(deferred_riggers):
                    for period_index, (start, finish) in enumerate(placement.periods):
                        interval = model.new_optional_interval_var(
                            start,
                            finish - start,
                            finish,
                            literal,
                            "rigger_pool_"
                            f"{activity.id}_{option_index}_{deferred_index}_{period_index}",
                        )
                        rigger_pool_intervals.append(interval)
                        optional_intervals += 1
        model.add_exactly_one(activity_literals)

        for requirement_index, requirement in enumerate(activity.requirements):
            if _is_deferred(approach, requirement):
                continue
            requirement_vars: list[cp_model.BoolVar] = []
            for resource_id in requirement.eligible_resource_ids:
                variable = model.new_bool_var(
                    f"assign_{activity.id}_{requirement.id}_{resource_id}"
                )
                assignment_vars[(activity.id, requirement.id, resource_id)] = variable
                requirement_vars.append(variable)
                supporting = [
                    literals[(activity.id, option_index)]
                    for option_index, placement in enumerate(placements)
                    if placement.assignments[requirement_index] == resource_id
                ]
                model.add(variable == sum(supporting))
            model.add_exactly_one(requirement_vars)

    for activity in case.activities:
        for predecessor_id in activity.predecessors:
            model.add(starts[activity.id] >= finishes[predecessor_id])

    if approach == "A":
        _add_pool_slot_constraints(
            model,
            case,
            placements_by_activity,
            literals,
            ("MECH", "INSPECT", "SPECIALIST", "RIGGER"),
        )
        if shared_multiskill_capacity:
            _add_shared_multiskill_constraint(
                model, case, placements_by_activity, literals
            )
    else:
        for intervals in named_intervals.values():
            if intervals:
                model.add_no_overlap(intervals)
        if approach == "C" and rigger_pool_intervals:
            model.add_cumulative(
                rigger_pool_intervals,
                [1] * len(rigger_pool_intervals),
                2,
            )

    timing_tie_break = sum(
        (index + 1) * starts[activity.id]
        for index, activity in enumerate(case.activities)
    )
    build_ms = (perf_counter() - build_started) * 1000
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    solve_started = perf_counter()
    model.minimize(finishes[case.objective_activity_id])
    finish_status = solver.solve(model)
    if finish_status != cp_model.OPTIMAL:
        raise SchedulingError(
            f"{approach}: controlling finish was not proven optimal: "
            f"{solver.status_name(finish_status)}"
        )
    best_finish = solver.value(finishes[case.objective_activity_id])
    model.add(finishes[case.objective_activity_id] == best_finish)
    model.minimize(timing_tie_break)
    timing_status = solver.solve(model)
    solve_ms = (perf_counter() - solve_started) * 1000
    if timing_status != cp_model.OPTIMAL:
        raise SchedulingError(
            f"{approach}: timing tie-break was not proven optimal: "
            f"{solver.status_name(timing_status)}"
        )

    entries: list[ScheduledEntry] = []
    for activity in case.activities:
        placements = placements_by_activity[activity.id]
        placement = next(
            placement
            for option_index, placement in enumerate(placements)
            if solver.value(literals[(activity.id, option_index)])
        )
        entries.append(
            ScheduledEntry(
                activity.id,
                placement.start,
                placement.finish,
                placement.periods,
                tuple(
                    (requirement.id, resource_id)
                    for requirement, resource_id in zip(
                        activity.requirements, placement.assignments
                    )
                ),
            )
        )
    ordered = tuple(entries)
    checker = check_fixed_schedule(case, ordered, run_greedy=approach == "A")
    identity_requirements = sum(
        not _is_deferred(approach, requirement)
        for activity in case.activities
        for requirement in activity.requirements
    )
    total_requirements = sum(len(activity.requirements) for activity in case.activities)
    label = "A+SHARED" if shared_multiskill_capacity else approach
    return PlanResult(
        label,
        ordered,
        best_finish,
        solver.value(timing_tie_break),
        f"{solver.status_name(finish_status)}/{solver.status_name(timing_status)}",
        "controlling finish and declared timing tie-break proven optimal",
        identity_requirements,
        total_requirements - identity_requirements,
        _model_metrics(
            model,
            assignment_variables=len(assignment_vars),
            optional_intervals=optional_intervals,
            build_ms=build_ms,
            solve_ms=solve_ms,
            solver_calls=2,
        ),
        checker,
        _signature(ordered),
    )


def _basic_schedule_violations(
    case: ExperimentCase,
    entries: tuple[ScheduledEntry, ...],
) -> tuple[int, int, int, int, int, str | None]:
    productive = 0
    calendar = 0
    qualification = 0
    capacity = 0
    precedence = 0
    first_reason: str | None = None
    by_id = {entry.activity_id: entry for entry in entries}
    occupancy: dict[tuple[str, int], list[str]] = {}
    for entry in entries:
        activity = case.activity_by_id[entry.activity_id]
        occupied = _occupied(entry.periods)
        if len(occupied) != activity.processing_ticks:
            productive += 1
            first_reason = first_reason or f"{activity.id} has the wrong productive total"
        activity_slots = case.calendar_by_id[activity.calendar_id].slots(case.horizon)
        if any(slot not in activity_slots for slot in occupied):
            calendar += 1
            first_reason = first_reason or f"{activity.id} executes outside its calendar"
        if activity.continuity == CONTINUOUS and activity.processing_ticks:
            if len(entry.periods) != 1:
                productive += 1
                first_reason = first_reason or f"{activity.id} was split despite continuity"
        submitted = entry.assignment_by_requirement
        for requirement in activity.requirements:
            resource_id = submitted.get(requirement.id)
            if resource_id is None:
                continue
            if resource_id not in requirement.eligible_resource_ids:
                qualification += 1
                first_reason = first_reason or (
                    f"{activity.id}/{requirement.id} assigns ineligible {resource_id}"
                )
                continue
            if any(slot not in _resource_slots(case, resource_id) for slot in occupied):
                calendar += 1
                first_reason = first_reason or (
                    f"{activity.id}/{requirement.id} assigns {resource_id} "
                    "outside its availability"
                )
            for slot in occupied:
                occupancy.setdefault((resource_id, slot), []).append(activity.id)
        for predecessor_id in activity.predecessors:
            if predecessor_id in by_id and entry.start < by_id[predecessor_id].finish:
                precedence += 1
                first_reason = first_reason or (
                    f"{activity.id} starts before {predecessor_id} finishes"
                )
    for (resource_id, slot), activity_ids in occupancy.items():
        if len(activity_ids) > case.resource_by_id[resource_id].capacity:
            capacity += 1
            first_reason = first_reason or (
                f"{resource_id} is double-booked at {format_tick(slot)}"
            )
    return productive, calendar, qualification, capacity, precedence, first_reason


def _assignment_variables(
    case: ExperimentCase,
    entries: tuple[ScheduledEntry, ...],
) -> tuple[tuple[str, str, tuple[int, ...], tuple[str, ...], str | None], ...]:
    variables = []
    for entry in entries:
        activity = case.activity_by_id[entry.activity_id]
        submitted = entry.assignment_by_requirement
        occupied = _occupied(entry.periods)
        for requirement in activity.requirements:
            candidates = tuple(
                resource_id
                for resource_id in requirement.eligible_resource_ids
                if all(
                    slot in _resource_slots(case, resource_id) for slot in occupied
                )
            )
            variables.append(
                (
                    activity.id,
                    requirement.id,
                    occupied,
                    candidates,
                    submitted.get(requirement.id),
                )
            )
    return tuple(variables)


def _hall_witness(
    variables: tuple[tuple[str, str, tuple[int, ...], tuple[str, ...], str | None], ...]
) -> str | None:
    all_slots = sorted({slot for _, _, occupied, _, _ in variables for slot in occupied})
    for slot in all_slots:
        active = [variable for variable in variables if slot in variable[2]]
        for size in range(2, len(active) + 1):
            for subset in combinations(active, size):
                candidates = set().union(*(set(item[3]) for item in subset))
                if len(candidates) < size:
                    labels = ", ".join(f"{item[0]}/{item[1]}" for item in subset)
                    return (
                        f"{labels} need {size} distinct resources at {format_tick(slot)}, "
                        f"but their eligible available union is {sorted(candidates)}"
                    )
    return None


def _greedy_assignment(
    case: ExperimentCase,
    entries: tuple[ScheduledEntry, ...],
    *,
    preferred_resources: tuple[str, ...] | None = None,
) -> tuple[str, str, tuple[tuple[str, str, str], ...]]:
    variables = _assignment_variables(case, entries)
    preference = preferred_resources or tuple(resource.id for resource in case.resources)
    rank = {resource_id: index for index, resource_id in enumerate(preference)}
    occupied_by_resource: dict[str, set[int]] = {}
    allocation: list[tuple[str, str, str]] = []
    for activity_id, requirement_id, occupied, candidates, submitted in variables:
        ordered_candidates = (submitted,) if submitted else tuple(
            sorted(candidates, key=lambda resource_id: rank.get(resource_id, len(rank)))
        )
        selected = next(
            (
                resource_id
                for resource_id in ordered_candidates
                if resource_id is not None
                and not (set(occupied) & occupied_by_resource.get(resource_id, set()))
            ),
            None,
        )
        if selected is None:
            return (
                "FAILED",
                f"greedy dispatch could not staff {activity_id}/{requirement_id}",
                tuple(allocation),
            )
        occupied_by_resource.setdefault(selected, set()).update(occupied)
        allocation.append((activity_id, requirement_id, selected))
    return "SUCCEEDED", "greedy dispatch found an allocation", tuple(allocation)


def check_fixed_schedule(
    case: ExperimentCase,
    entries: tuple[ScheduledEntry, ...],
    *,
    max_search_nodes: int | None = None,
    run_greedy: bool = False,
) -> CheckerResult:
    """Search globally for one no-handover assignment per physical slot."""

    (
        productive,
        calendar,
        qualification,
        capacity,
        precedence,
        reason,
    ) = _basic_schedule_violations(case, entries)
    greedy_status = "NOT_RUN"
    greedy_reason = "greedy dispatch was not used as proof"
    if run_greedy:
        greedy_status, greedy_reason, _ = _greedy_assignment(case, entries)
    if productive or calendar or qualification or capacity or precedence:
        return CheckerResult(
            EXACT_INFEASIBLE,
            (),
            reason or "submitted schedule violates fixed execution semantics",
            productive,
            calendar,
            qualification,
            capacity,
            precedence,
            0,
            greedy_status,
            greedy_reason,
        )

    variables = _assignment_variables(case, entries)
    fixed = [variable for variable in variables if variable[4] is not None]
    deferred = [variable for variable in variables if variable[4] is None]
    occupied_by_resource: dict[str, set[int]] = {}
    allocation: list[tuple[str, str, str]] = []
    for activity_id, requirement_id, occupied, candidates, submitted in fixed:
        if submitted not in candidates:
            return CheckerResult(
                EXACT_INFEASIBLE,
                (),
                f"submitted assignment {activity_id}/{requirement_id}={submitted} is invalid",
                productive,
                calendar + 1,
                qualification,
                capacity,
                precedence,
                0,
                greedy_status,
                greedy_reason,
            )
        if set(occupied) & occupied_by_resource.get(submitted, set()):
            return CheckerResult(
                EXACT_INFEASIBLE,
                (),
                f"submitted assignment double-books {submitted}",
                productive,
                calendar,
                qualification,
                capacity + 1,
                precedence,
                0,
                greedy_status,
                greedy_reason,
            )
        occupied_by_resource.setdefault(submitted, set()).update(occupied)
        allocation.append((activity_id, requirement_id, submitted))

    deferred.sort(key=lambda item: (len(item[3]), -len(item[2]), item[0], item[1]))
    nodes = 0
    inconclusive = False

    def search(index: int) -> bool:
        nonlocal nodes, inconclusive
        if index == len(deferred):
            return True
        if max_search_nodes is not None and nodes >= max_search_nodes:
            inconclusive = True
            return False
        nodes += 1
        activity_id, requirement_id, occupied, candidates, _ = deferred[index]
        occupied_set = set(occupied)
        for resource_id in candidates:
            if occupied_set & occupied_by_resource.get(resource_id, set()):
                continue
            occupied_by_resource.setdefault(resource_id, set()).update(occupied_set)
            allocation.append((activity_id, requirement_id, resource_id))
            if search(index + 1):
                return True
            allocation.pop()
            occupied_by_resource[resource_id].difference_update(occupied_set)
        return False

    if search(0):
        return CheckerResult(
            EXACT_FEASIBLE,
            tuple(sorted(allocation)),
            "exact global search found a consistent no-handover allocation",
            productive,
            calendar,
            qualification,
            capacity,
            precedence,
            nodes,
            greedy_status,
            greedy_reason,
        )
    if inconclusive:
        return CheckerResult(
            EXACT_INCONCLUSIVE,
            (),
            "search limit reached; assignment feasibility is unproved",
            productive,
            calendar,
            qualification,
            capacity,
            precedence,
            nodes,
            greedy_status,
            greedy_reason,
        )
    witness = _hall_witness(variables)
    return CheckerResult(
        EXACT_INFEASIBLE,
        (),
        witness or "exact search exhausted all consistent no-handover assignments",
        productive,
        calendar,
        qualification,
        capacity + int(witness is not None),
        precedence,
        nodes,
        greedy_status,
        greedy_reason,
    )


def each_time_slice_is_assignable(
    case: ExperimentCase,
    entries: tuple[ScheduledEntry, ...],
) -> bool:
    """Diagnostic only: deliberately permits a different assignment each time slice."""

    variables = _assignment_variables(case, entries)
    slots = sorted({slot for _, _, occupied, _, _ in variables for slot in occupied})
    for slot in slots:
        active = [variable for variable in variables if slot in variable[2]]

        def match(index: int, used: set[str]) -> bool:
            if index == len(active):
                return True
            submitted = active[index][4]
            candidates = (submitted,) if submitted else active[index][3]
            return any(
                resource_id is not None
                and resource_id not in used
                and match(index + 1, used | {resource_id})
                for resource_id in candidates
            )

        if not match(0, set()):
            return False
    return True


def build_no_handover_regression() -> tuple[ExperimentCase, tuple[ScheduledEntry, ...]]:
    calendars = (WorkCalendar("TEST", ((_ticks(8), _ticks(12)),)),)
    resources = (
        PhysicalResource("M1", ("MECH",), "TEST"),
        PhysicalResource("M2", ("MECH",), "TEST"),
    )
    activities = (
        ActivitySpec("X", "Long alternative", _ticks(4), "TEST", (_req("MECH", "MECH", ("M1", "M2")),)),
        ActivitySpec("Y", "Early M1-only", _ticks(2), "TEST", (_req("MECH", "MECH", ("M1",)),)),
        ActivitySpec("Z", "Late M2-only", _ticks(2), "TEST", (_req("MECH", "MECH", ("M2",)),)),
    )
    case = ExperimentCase(calendars, resources, (), activities, "X", TICKS_PER_DAY)
    entries = (
        ScheduledEntry("X", _ticks(8), _ticks(12), ((_ticks(8), _ticks(12)),), (("MECH", None),)),
        ScheduledEntry("Y", _ticks(8), _ticks(10), ((_ticks(8), _ticks(10)),), (("MECH", None),)),
        ScheduledEntry("Z", _ticks(10), _ticks(12), ((_ticks(10), _ticks(12)),), (("MECH", None),)),
    )
    return case, entries


def _planner_facts(case: ExperimentCase) -> tuple[tuple[str, int], ...]:
    requirements = [
        requirement
        for activity in case.activities
        for requirement in activity.requirements
    ]
    return (
        ("physical resources", len(case.resources)),
        (
            "resource capability memberships",
            sum(len(resource.capabilities) for resource in case.resources),
        ),
        ("resource calendar assignments", len(case.resources)),
        ("calendar definitions", len(case.calendars)),
        ("dated availability exceptions", len(case.exceptions)),
        ("activities and milestones", len(case.activities)),
        ("productive-work requirements", len(requirements)),
        (
            "eligible-resource memberships",
            sum(len(requirement.eligible_resource_ids) for requirement in requirements),
        ),
        (
            "precedence links",
            sum(len(activity.predecessors) for activity in case.activities),
        ),
        (
            "not-before boundaries",
            sum(activity.not_before > 0 for activity in case.activities),
        ),
        ("objective and timing policies", 2),
    )


def _scarce_specialist_diagnostic(
    case: ExperimentCase,
    plan: PlanResult,
) -> GreedyDiagnostic:
    entries = tuple(plan.by_id[activity_id] for activity_id in ("A05", "A06"))
    deferred_entries = tuple(
        ScheduledEntry(
            entry.activity_id,
            entry.start,
            entry.finish,
            entry.periods,
            tuple((requirement_id, None) for requirement_id, _ in entry.assignments),
        )
        for entry in entries
    )
    greedy_status, greedy_reason, _ = _greedy_assignment(
        case,
        deferred_entries,
        preferred_resources=("M2", "M1", "N1", "R1", "R2"),
    )
    exact = check_fixed_schedule(case, deferred_entries)
    return GreedyDiagnostic(
        greedy_status,
        greedy_reason,
        exact.exact_status,
        exact.allocation,
    )


def run_experiment() -> ExperimentResult:
    case = build_case()
    plans = tuple(solve_approach(case, approach) for approach in ("A", "B", "C"))
    repeated_c = solve_approach(case, "C")
    shared = solve_approach(case, "A", shared_multiskill_capacity=True)
    return ExperimentResult(
        case,
        plans,
        repeated_c.canonical_signature,
        repeated_c.objective_result,
        shared,
        _scarce_specialist_diagnostic(case, plans[1]),
        _planner_facts(case),
    )


def _periods_text(periods: tuple[tuple[int, int], ...]) -> str:
    if not periods:
        return "milestone"
    return ", ".join(
        f"{format_tick(start)}-{format_tick(finish)}" for start, finish in periods
    )


def _allocation_text(allocation: tuple[tuple[str, str, str], ...]) -> str:
    return ", ".join(
        f"{activity_id}/{requirement_id}={resource_id}"
        for activity_id, requirement_id, resource_id in allocation
    ) or "none"


def _plan_line(plan: PlanResult) -> str:
    metrics = plan.metrics
    checker = plan.checker
    return (
        f"{plan.approach}: finish {format_tick(plan.project_finish)}; "
        f"objective ({plan.project_finish}, {plan.timing_tie_break}); "
        f"physical {checker.exact_status}; identity/deferred requirements "
        f"{plan.identity_level_requirements}/{plan.deferred_requirements}; "
        f"assignment vars {metrics.assignment_variables}; "
        f"int/bool vars {metrics.integer_variables}/{metrics.boolean_variables}; "
        f"optional intervals {metrics.optional_intervals}; constraints {metrics.constraints}; "
        f"build {metrics.model_build_ms:.1f} ms; solve {metrics.solve_ms:.1f} ms; "
        f"calls {metrics.solver_calls}; status {plan.solver_status}; "
        f"signature {plan.canonical_signature}"
    )


def render(result: ExperimentResult) -> str:
    a, b, c = result.plans
    exception = result.case.exceptions[0]
    shared = result.shared_capacity_diagnostic
    scarce = result.scarce_specialist_diagnostic
    lines = [
        "RESOURCE CAPACITY VERSUS EXECUTABLE ASSIGNMENT",
        "14 activities; 30-minute resolution; one capacity-one physical roster.",
        (
            f"Synthetic exception: {exception.resource_id} unavailable "
            f"{format_tick(exception.start)}-{format_tick(exception.finish)}."
        ),
        "Objective: controlling A14 handoff finish, then weighted activity-start timing tie-break.",
        "Resource identities do not enter the objective.",
        "",
        "A/B/C RESULTS",
        _plan_line(a),
        _plan_line(b),
        _plan_line(c),
        "",
        "PHYSICAL CHECKER",
        (
            f"A greedy attempt {a.checker.greedy_status}; exact search "
            f"{a.checker.exact_status}: {a.checker.reason}."
        ),
        f"B submitted allocation: {_allocation_text(b.checker.allocation)}.",
        f"C submitted/deferred allocation: {_allocation_text(c.checker.allocation)}.",
        (
            "Violations productive/calendar/qualification/capacity/precedence: "
            f"A={a.checker.productive_time_violations}/{a.checker.calendar_violations}/"
            f"{a.checker.qualification_violations}/{a.checker.capacity_violations}/"
            f"{a.checker.precedence_violations}; "
            f"B={b.checker.productive_time_violations}/{b.checker.calendar_violations}/"
            f"{b.checker.qualification_violations}/{b.checker.capacity_violations}/"
            f"{b.checker.precedence_violations}; "
            f"C={c.checker.productive_time_violations}/{c.checker.calendar_violations}/"
            f"{c.checker.qualification_violations}/{c.checker.capacity_violations}/"
            f"{c.checker.precedence_violations}."
        ),
        "",
        "SENTINELS",
        (
            "Overlapping pools A01/A02/A03: "
            f"A starts {a.by_id['A01'].start}/{a.by_id['A02'].start}/"
            f"{a.by_id['A03'].start}; B starts {b.by_id['A01'].start}/"
            f"{b.by_id['A02'].start}/{b.by_id['A03'].start}; "
            f"C starts {c.by_id['A01'].start}/{c.by_id['A02'].start}/"
            f"{c.by_id['A03'].start}."
        ),
        (
            "Scarce specialist: bad greedy dispatch "
            f"{scarce.greedy_status}, while exact search {scarce.exact_status}; "
            f"allocation {_allocation_text(scarce.exact_allocation)}."
        ),
        (
            "Calendar/eligibility: A08 "
            f"{_periods_text(c.by_id['A08'].periods)} with "
            f"{dict(c.by_id['A08'].assignments)['MECH']}; A09 "
            f"{_periods_text(c.by_id['A09'].periods)} with "
            f"{dict(c.by_id['A09'].assignments)['DUAL']}."
        ),
        (
            "Interchangeable riggers: B names "
            f"{dict(b.by_id['A10'].assignments)['RIGGER']}/"
            f"{dict(b.by_id['A11'].assignments)['RIGGER']}; C keeps both pooled; "
            f"objective equal={b.objective_result == c.objective_result}."
        ),
        "",
        "SHARED-CAPACITY DIAGNOSTIC",
        _plan_line(shared),
        (
            "The one shared M1/M2 head-count constraint removes the overlapping-pool "
            "false concurrency in this fixture. Its checker result does not establish "
            "general eligibility, qualification, or no-handover continuity semantics."
        ),
        "",
        "PLANNER-MAINTAINED FACTS (same for A/B/C, including checker roster data)",
        "; ".join(f"{name}={count}" for name, count in result.planner_facts),
        "Solver-generated identity decisions: A=0; B=11; C=9; C defers 2 rigging slots.",
        "",
        (
            "Repeated C canonical: "
            f"{c.canonical_signature == result.repeated_c_signature}; "
            f"objective repeated: {c.objective_result == result.repeated_c_objective}."
        ),
        "RESEARCH CONCLUSION",
        (
            "C matches B's executable objective result and avoids unnecessary rigging identity. "
            "A's independent pools are not executable. However, A plus the small shared M1/M2 "
            "capacity diagnostic also reaches an executable equal-finish result in this fixture, "
            "so this experiment does not prove that selective assignment belongs in the scheduling "
            "master instead of a pooled schedule plus exact assignment-feasibility layer."
        ),
    ]
    return "\n".join(lines)


def main() -> int:
    print(render(run_experiment()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
