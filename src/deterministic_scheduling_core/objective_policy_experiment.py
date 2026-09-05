from __future__ import annotations

from dataclasses import dataclass, replace
from itertools import product
from time import perf_counter

from ortools.sat.python import cp_model

from deterministic_scheduling_core.errors import SchedulingError
from deterministic_scheduling_core.project.model import Activity, ExecutionMode, Project, ResourceRequirement
from deterministic_scheduling_core.scheduling import ScheduleResult, schedule_project
from deterministic_scheduling_core.work_method_experiment import (
    ExperimentCase,
    Outage,
    Scenario,
    build_case,
    materialize_fixed_project,
)


PROTECTED_HANDOFF = 42
APPROVED_METHOD_INDEX = 0


@dataclass(frozen=True, slots=True)
class ObjectiveVector:
    protected_lateness: int
    finish: int
    method_changes: int
    materially_moved_activities: int
    maximum_activity_shift: int
    absolute_start_movement: int

    def as_tuple(self) -> tuple[int, int, int, int, int, int]:
        return (
            self.protected_lateness,
            self.finish,
            self.method_changes,
            self.materially_moved_activities,
            self.maximum_activity_shift,
            self.absolute_start_movement,
        )


@dataclass(frozen=True, slots=True)
class Alternative:
    methods: tuple[tuple[str, str], ...]
    schedule: ScheduleResult
    vector: ObjectiveVector

    @property
    def methods_by_package(self) -> dict[str, str]:
        return dict(self.methods)


@dataclass(frozen=True, slots=True)
class CandidateEntry:
    package_id: str
    method_id: str
    activity_id: str
    mode_id: str
    start: int
    finish: int


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    delta_finish: int
    methods: tuple[tuple[str, str], ...]
    entries: tuple[CandidateEntry, ...]
    vector: ObjectiveVector
    best_finish: int
    allowed_finish: int
    stage_statuses: tuple[tuple[str, str], ...]
    solve_ms: float

    @property
    def methods_by_package(self) -> dict[str, str]:
        return dict(self.methods)

    @property
    def signature(self) -> tuple[object, ...]:
        return (
            self.methods,
            tuple(
                (entry.activity_id, entry.mode_id, entry.start, entry.finish)
                for entry in sorted(self.entries, key=lambda item: item.activity_id)
            ),
            self.vector.as_tuple(),
        )


@dataclass(frozen=True, slots=True)
class WeightedDecision:
    profile: str
    methods: tuple[tuple[str, str], ...]
    vector: ObjectiveVector
    score: int


@dataclass(frozen=True, slots=True)
class ExperimentResult:
    case: ExperimentCase
    approved_methods: tuple[tuple[str, str], ...]
    approved_schedule: ScheduleResult
    recovery: Scenario
    alternatives: tuple[Alternative, ...]
    fastest: Alternative
    oracle_delta0: Alternative
    oracle_delta1: Alternative
    candidate_delta0: PolicyDecision
    candidate_delta1: PolicyDecision
    weighted: tuple[WeightedDecision, ...]
    deterministic_repeat: bool
    falsified: bool


def _method_choices(case: ExperimentCase) -> tuple[tuple[tuple[str, str], ...], ...]:
    return tuple(
        tuple((package.id, method_id) for package, method_id in zip(case.packages, chosen))
        for chosen in product(
            *(tuple(method.id for method in package.methods) for package in case.packages)
        )
    )


def _remove_hard_handoff_limit(case: ExperimentCase) -> ExperimentCase:
    packages = []
    for package in case.packages:
        methods = []
        for method in package.methods:
            activities = tuple(
                replace(activity, latest_finish=None)
                if activity.id == "F4"
                else activity
                for activity in method.activities
            )
            methods.append(replace(method, activities=activities))
        packages.append(replace(package, methods=tuple(methods)))
    return replace(case, packages=tuple(packages), scenarios=())


def build_objective_case() -> tuple[ExperimentCase, Scenario, Scenario]:
    """Return a 33-activity case with a one-hour finish-versus-stability trade-off."""

    case = _remove_hard_handoff_limit(build_case())
    baseline = Scenario(
        "BASE",
        "Approved plan conditions",
        not_before=(("D2-1", 25),),
        reason="Normal crane availability; specialist cannot mobilise before H25.",
    )
    recovery = Scenario(
        "RECOVERY",
        "Crane outage creates a near-equal structural recovery choice",
        not_before=(("D2-1", 25),),
        outages=(Outage("CRANE", 11, 16, "Crane C04 unavailable H11-H16"),),
        reason=(
            "The approved full-component crane method must wait through H11-H16. "
            "Segmented removal avoids the outage and can finish one hour earlier, "
            "but changes the approved execution structure."
        ),
    )
    return case, baseline, recovery


def _approved_choices(case: ExperimentCase) -> tuple[tuple[str, str], ...]:
    return tuple((package.id, package.methods[APPROVED_METHOD_INDEX].id) for package in case.packages)


def _with_reference_plan(project: Project, approved: ScheduleResult) -> Project:
    reference = approved.by_id
    return replace(
        project,
        activities=tuple(
            replace(
                activity,
                planned_start=reference[activity.id].start,
                planned_mode_id=reference[activity.id].mode_id,
            )
            if activity.id in reference
            else activity
            for activity in project.activities
        ),
    )


def build_approved_plan(
    case: ExperimentCase,
    baseline: Scenario,
) -> tuple[tuple[tuple[str, str], ...], ScheduleResult]:
    choices = _approved_choices(case)
    project = materialize_fixed_project(case, baseline, choices)
    return choices, schedule_project(project)


def _objective_vector(
    methods: tuple[tuple[str, str], ...],
    schedule: ScheduleResult,
    approved_methods: tuple[tuple[str, str], ...],
    approved_schedule: ScheduleResult,
) -> ObjectiveVector:
    approved_method_map = dict(approved_methods)
    current_method_map = dict(methods)
    method_changes = sum(
        current_method_map[package_id] != method_id
        for package_id, method_id in approved_methods
    )

    common = set(approved_schedule.by_id) & set(schedule.by_id)
    shifts = tuple(
        abs(schedule.by_id[activity_id].start - approved_schedule.by_id[activity_id].start)
        for activity_id in common
        if schedule.by_id[activity_id].start != approved_schedule.by_id[activity_id].start
    )
    return ObjectiveVector(
        protected_lateness=max(0, schedule.objective_finish - PROTECTED_HANDOFF),
        finish=schedule.objective_finish,
        method_changes=method_changes,
        materially_moved_activities=len(shifts),
        maximum_activity_shift=max(shifts, default=0),
        absolute_start_movement=sum(shifts),
    )


def enumerate_recovery_alternatives(
    case: ExperimentCase,
    recovery: Scenario,
    approved_methods: tuple[tuple[str, str], ...],
    approved_schedule: ScheduleResult,
) -> tuple[Alternative, ...]:
    alternatives: list[Alternative] = []
    for choices in _method_choices(case):
        project = materialize_fixed_project(case, recovery, choices)
        project = _with_reference_plan(project, approved_schedule)
        try:
            result = schedule_project(project)
        except SchedulingError:
            continue
        alternatives.append(
            Alternative(
                choices,
                result,
                _objective_vector(choices, result, approved_methods, approved_schedule),
            )
        )
    if not alternatives:
        raise SchedulingError("objective-policy experiment has no feasible recovery alternative")
    return tuple(alternatives)


def _canonical_alternative_key(item: Alternative) -> tuple[object, ...]:
    return (
        tuple(method_id for _, method_id in item.methods),
        tuple(
            (entry.activity_id, entry.mode_id, entry.start, entry.finish)
            for entry in sorted(item.schedule.entries, key=lambda entry: entry.activity_id)
        ),
    )


def select_oracle(
    alternatives: tuple[Alternative, ...],
    delta_finish: int,
) -> Alternative:
    best_lateness = min(item.vector.protected_lateness for item in alternatives)
    eligible = tuple(item for item in alternatives if item.vector.protected_lateness == best_lateness)
    best_finish = min(item.vector.finish for item in eligible)
    eligible = tuple(item for item in eligible if item.vector.finish <= best_finish + delta_finish)
    best_method_changes = min(item.vector.method_changes for item in eligible)
    eligible = tuple(item for item in eligible if item.vector.method_changes == best_method_changes)
    best_moved = min(item.vector.materially_moved_activities for item in eligible)
    eligible = tuple(item for item in eligible if item.vector.materially_moved_activities == best_moved)
    best_movement = min(item.vector.absolute_start_movement for item in eligible)
    eligible = tuple(item for item in eligible if item.vector.absolute_start_movement == best_movement)
    return min(eligible, key=_canonical_alternative_key)


def _horizon(case: ExperimentCase, recovery: Scenario, approved_schedule: ScheduleResult) -> int:
    longest = sum(
        max(
            sum(max(mode.duration for mode in activity.modes) for activity in method.activities)
            for method in package.methods
        )
        for package in case.packages
    )
    anchors = [approved_schedule.objective_finish, PROTECTED_HANDOFF]
    anchors.extend(value for _, value in recovery.not_before)
    anchors.extend(outage.finish for outage in recovery.outages)
    return max(anchors) + longest + 50


def solve_policy_candidate(
    case: ExperimentCase,
    recovery: Scenario,
    approved_methods: tuple[tuple[str, str], ...],
    approved_schedule: ScheduleResult,
    delta_finish: int,
) -> PolicyDecision:
    """Select method + mode + timing through explicit aspiration-bounded stages."""

    horizon = _horizon(case, recovery, approved_schedule)
    model = cp_model.CpModel()
    not_before = dict(recovery.not_before)
    approved_method_map = dict(approved_methods)
    approved_start = {activity_id: entry.start for activity_id, entry in approved_schedule.by_id.items()}

    selected_method: dict[tuple[str, str], cp_model.BoolVar] = {}
    selected_mode: dict[tuple[str, str, str, str], cp_model.BoolVar] = {}
    starts: dict[tuple[str, str, str], cp_model.IntVar] = {}
    ends: dict[tuple[str, str, str], cp_model.IntVar] = {}
    intervals: dict[tuple[str, str, str, str], cp_model.IntervalVar] = {}
    package_finish: dict[str, cp_model.IntVar] = {}
    active_starts: list[cp_model.IntVar] = []

    for package in case.packages:
        package_finish[package.id] = model.new_int_var(0, horizon, f"finish_{package.id}")
        method_literals: list[cp_model.BoolVar] = []
        for method in package.methods:
            method_literal = model.new_bool_var(f"method_{package.id}_{method.id}")
            selected_method[(package.id, method.id)] = method_literal
            method_literals.append(method_literal)
            local_ids = {activity.id for activity in method.activities}

            for activity in method.activities:
                key = (package.id, method.id, activity.id)
                start = model.new_int_var(
                    not_before.get(activity.id, 0),
                    horizon,
                    f"start_{package.id}_{method.id}_{activity.id}",
                )
                end = model.new_int_var(0, horizon, f"end_{package.id}_{method.id}_{activity.id}")
                starts[key] = start
                ends[key] = end

                active_start = model.new_int_var(0, horizon, f"active_{package.id}_{method.id}_{activity.id}")
                model.add(active_start == start).only_enforce_if(method_literal)
                model.add(active_start == 0).only_enforce_if(method_literal.Not())
                active_starts.append(active_start)

                mode_literals: list[cp_model.BoolVar] = []
                for mode in activity.modes:
                    literal = model.new_bool_var(
                        f"mode_{package.id}_{method.id}_{activity.id}_{mode.id}"
                    )
                    selected_mode[(package.id, method.id, activity.id, mode.id)] = literal
                    intervals[(package.id, method.id, activity.id, mode.id)] = model.new_optional_interval_var(
                        start,
                        mode.duration,
                        end,
                        literal,
                        f"interval_{package.id}_{method.id}_{activity.id}_{mode.id}",
                    )
                    mode_literals.append(literal)
                model.add(sum(mode_literals) == method_literal)

                for predecessor in activity.predecessors:
                    if predecessor not in local_ids:
                        raise SchedulingError(
                            f"{package.id}/{method.id}: predecessor {predecessor} must be inside method"
                        )
                    model.add(start >= ends[(package.id, method.id, predecessor)]).only_enforce_if(
                        method_literal
                    )

            model.add(
                package_finish[package.id]
                == ends[(package.id, method.id, method.completion_id)]
            ).only_enforce_if(method_literal)

            for root in method.roots:
                for predecessor_package in package.predecessors:
                    model.add(
                        starts[(package.id, method.id, root)] >= package_finish[predecessor_package]
                    ).only_enforce_if(method_literal)

        model.add_exactly_one(method_literals)

    resource_intervals = {resource.id: [] for resource in case.resources}
    resource_demands = {resource.id: [] for resource in case.resources}
    resource_map = {resource.id: resource for resource in case.resources}

    for package in case.packages:
        for method in package.methods:
            for activity in method.activities:
                for mode in activity.modes:
                    interval = intervals[(package.id, method.id, activity.id, mode.id)]
                    for requirement in mode.requirements:
                        resource_intervals[requirement.resource_id].append(interval)
                        resource_demands[requirement.resource_id].append(requirement.demand)

    for index, outage in enumerate(recovery.outages, 1):
        start = model.new_int_var(outage.start, outage.start, f"outage_start_{index}")
        end = model.new_int_var(outage.finish, outage.finish, f"outage_end_{index}")
        interval = model.new_interval_var(
            start,
            outage.finish - outage.start,
            end,
            f"outage_{index}",
        )
        resource_intervals[outage.resource_id].append(interval)
        resource_demands[outage.resource_id].append(resource_map[outage.resource_id].capacity)

    for resource in case.resources:
        if resource_intervals[resource.id]:
            model.add_cumulative(
                resource_intervals[resource.id],
                resource_demands[resource.id],
                resource.capacity,
            )

    groups: dict[str, list[cp_model.IntervalVar]] = {}
    for package in case.packages:
        for method in package.methods:
            for activity in method.activities:
                for group_id in activity.exclusion_groups:
                    groups.setdefault(group_id, []).extend(
                        intervals[(package.id, method.id, activity.id, mode.id)]
                        for mode in activity.modes
                    )
    for group_intervals in groups.values():
        model.add_no_overlap(group_intervals)

    final_finish = package_finish["WP-F"]
    protected_lateness = model.new_int_var(0, horizon, "protected_lateness")
    model.add(protected_lateness >= final_finish - PROTECTED_HANDOFF)

    method_change_literals: list[cp_model.BoolVar] = []
    for package in case.packages:
        approved_method = approved_method_map[package.id]
        for method in package.methods:
            if method.id != approved_method:
                method_change_literals.append(selected_method[(package.id, method.id)])
    method_changes = model.new_int_var(0, len(case.packages), "method_changes")
    model.add(method_changes == sum(method_change_literals))

    movement_vars: list[cp_model.IntVar] = []
    moved_literals: list[cp_model.BoolVar] = []
    for package in case.packages:
        approved_method = approved_method_map[package.id]
        method = next(item for item in package.methods if item.id == approved_method)
        method_literal = selected_method[(package.id, method.id)]
        for activity in method.activities:
            if activity.id not in approved_start:
                continue
            key = (package.id, method.id, activity.id)
            deviation = model.new_int_var(-horizon, horizon, f"deviation_{activity.id}")
            model.add(deviation == starts[key] - approved_start[activity.id]).only_enforce_if(method_literal)
            model.add(deviation == 0).only_enforce_if(method_literal.Not())
            movement = model.new_int_var(0, horizon, f"movement_{activity.id}")
            model.add_abs_equality(movement, deviation)
            moved = model.new_bool_var(f"moved_{activity.id}")
            model.add(movement >= moved)
            model.add(movement <= horizon * moved)
            movement_vars.append(movement)
            moved_literals.append(moved)

    materially_moved = model.new_int_var(0, len(moved_literals), "materially_moved")
    model.add(materially_moved == sum(moved_literals))
    movement_bound = len(movement_vars) * horizon
    absolute_movement = model.new_int_var(0, movement_bound, "absolute_movement")
    model.add(absolute_movement == sum(movement_vars))

    maximum_shift = model.new_int_var(0, horizon, "maximum_shift")
    if movement_vars:
        model.add_max_equality(maximum_shift, movement_vars)
    else:
        model.add(maximum_shift == 0)

    method_tie = sum(
        method_index * selected_method[(package.id, method.id)]
        for package in case.packages
        for method_index, method in enumerate(package.methods)
    )
    mode_tie = sum(
        mode_index * selected_mode[(package.id, method.id, activity.id, mode.id)]
        for package in case.packages
        for method in package.methods
        for activity in method.activities
        for mode_index, mode in enumerate(activity.modes)
    )
    canonical_tie = sum(active_starts) * 100 + method_tie * 10 + mode_tie

    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    stages: list[tuple[str, str]] = []
    started = perf_counter()

    def solve_stage(name: str, objective: cp_model.LinearExpr) -> int:
        model.minimize(objective)
        status = solver.solve(model)
        status_name = solver.status_name(status)
        stages.append((name, status_name))
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            raise SchedulingError(f"objective-policy {name}: {status_name}")
        if status != cp_model.OPTIMAL:
            raise SchedulingError(f"objective-policy {name}: optimality not proven")
        return solver.value(objective)

    best_lateness = solve_stage("protected_commitment", protected_lateness)
    model.add(protected_lateness == best_lateness)

    best_finish = solve_stage("controlling_finish", final_finish)
    allowed_finish = best_finish + delta_finish
    model.add(final_finish <= allowed_finish)

    best_method_changes = solve_stage("structural_stability", method_changes)
    model.add(method_changes == best_method_changes)

    best_moved = solve_stage("material_movement_count", materially_moved)
    model.add(materially_moved == best_moved)

    best_movement = solve_stage("absolute_start_movement", absolute_movement)
    model.add(absolute_movement == best_movement)

    solve_stage("canonical_tie_break", canonical_tie)
    solve_ms = (perf_counter() - started) * 1000

    methods: list[tuple[str, str]] = []
    entries: list[CandidateEntry] = []
    for package in case.packages:
        method = next(
            method
            for method in package.methods
            if solver.value(selected_method[(package.id, method.id)])
        )
        methods.append((package.id, method.id))
        for activity in method.activities:
            mode = next(
                mode
                for mode in activity.modes
                if solver.value(selected_mode[(package.id, method.id, activity.id, mode.id)])
            )
            key = (package.id, method.id, activity.id)
            entries.append(
                CandidateEntry(
                    package.id,
                    method.id,
                    activity.id,
                    mode.id,
                    solver.value(starts[key]),
                    solver.value(ends[key]),
                )
            )

    return PolicyDecision(
        delta_finish=delta_finish,
        methods=tuple(methods),
        entries=tuple(sorted(entries, key=lambda item: (item.start, item.finish, item.activity_id))),
        vector=ObjectiveVector(
            protected_lateness=solver.value(protected_lateness),
            finish=solver.value(final_finish),
            method_changes=solver.value(method_changes),
            materially_moved_activities=solver.value(materially_moved),
            maximum_activity_shift=solver.value(maximum_shift),
            absolute_start_movement=solver.value(absolute_movement),
        ),
        best_finish=best_finish,
        allowed_finish=allowed_finish,
        stage_statuses=tuple(stages),
        solve_ms=solve_ms,
    )


def weighted_comparisons(alternatives: tuple[Alternative, ...]) -> tuple[WeightedDecision, ...]:
    profiles = (
        ("finish-heavy", (100, 5, 1, 1)),
        ("stability-heavy", (10, 100, 5, 1)),
    )
    decisions: list[WeightedDecision] = []
    best_lateness = min(item.vector.protected_lateness for item in alternatives)
    eligible = tuple(item for item in alternatives if item.vector.protected_lateness == best_lateness)
    for name, (finish_w, method_w, moved_w, movement_w) in profiles:
        def score(item: Alternative) -> int:
            vector = item.vector
            return (
                finish_w * vector.finish
                + method_w * vector.method_changes
                + moved_w * vector.materially_moved_activities
                + movement_w * vector.absolute_start_movement
            )

        selected = min(
            eligible,
            key=lambda item: (score(item), _canonical_alternative_key(item)),
        )
        decisions.append(WeightedDecision(name, selected.methods, selected.vector, score(selected)))
    return tuple(decisions)


def _same_policy_choice(candidate: PolicyDecision, oracle: Alternative) -> bool:
    return candidate.methods == oracle.methods and candidate.vector.as_tuple() == oracle.vector.as_tuple()


def run_experiment() -> ExperimentResult:
    case, baseline, recovery = build_objective_case()
    approved_methods, approved_schedule = build_approved_plan(case, baseline)
    alternatives = enumerate_recovery_alternatives(
        case,
        recovery,
        approved_methods,
        approved_schedule,
    )
    fastest = min(
        alternatives,
        key=lambda item: (
            item.vector.protected_lateness,
            item.vector.finish,
            _canonical_alternative_key(item),
        ),
    )
    oracle_delta0 = select_oracle(alternatives, 0)
    oracle_delta1 = select_oracle(alternatives, 1)
    candidate_delta0 = solve_policy_candidate(
        case,
        recovery,
        approved_methods,
        approved_schedule,
        0,
    )
    candidate_delta1 = solve_policy_candidate(
        case,
        recovery,
        approved_methods,
        approved_schedule,
        1,
    )
    repeat_delta1 = solve_policy_candidate(
        case,
        recovery,
        approved_methods,
        approved_schedule,
        1,
    )
    deterministic_repeat = candidate_delta1.signature == repeat_delta1.signature
    weighted = weighted_comparisons(alternatives)

    delta_transition = (
        candidate_delta0.vector.finish == candidate_delta0.best_finish
        and candidate_delta1.vector.finish == candidate_delta0.best_finish + 1
        and candidate_delta1.vector.method_changes < candidate_delta0.vector.method_changes
        and candidate_delta0.methods != candidate_delta1.methods
    )
    falsified = not (
        _same_policy_choice(candidate_delta0, oracle_delta0)
        and _same_policy_choice(candidate_delta1, oracle_delta1)
        and delta_transition
        and deterministic_repeat
        and all(status == "OPTIMAL" for _, status in candidate_delta0.stage_statuses)
        and all(status == "OPTIMAL" for _, status in candidate_delta1.stage_statuses)
    )
    return ExperimentResult(
        case=case,
        approved_methods=approved_methods,
        approved_schedule=approved_schedule,
        recovery=recovery,
        alternatives=alternatives,
        fastest=fastest,
        oracle_delta0=oracle_delta0,
        oracle_delta1=oracle_delta1,
        candidate_delta0=candidate_delta0,
        candidate_delta1=candidate_delta1,
        weighted=weighted,
        deterministic_repeat=deterministic_repeat,
        falsified=falsified,
    )


def _methods(methods: tuple[tuple[str, str], ...]) -> str:
    return ", ".join(
        f"{package}={method}"
        for package, method in methods
        if package in {"WP-B", "WP-C", "WP-D"}
    )


def _vector(vector: ObjectiveVector) -> str:
    return (
        f"lateness={vector.protected_lateness}h, finish=H{vector.finish}, "
        f"method_changes={vector.method_changes}, moved={vector.materially_moved_activities}, "
        f"max_shift={vector.maximum_activity_shift}h, total_movement={vector.absolute_start_movement}h"
    )


def render(result: ExperimentResult) -> str:
    delta0 = result.candidate_delta0
    delta1 = result.candidate_delta1
    lines = [
        "OBJECTIVE-POLICY FALSIFICATION EXPERIMENT",
        (
            f"{result.case.possible_activity_count} possible activities; "
            f"{len(result.alternatives)} feasible authorised fixed-network recoveries."
        ),
        f"Approved plan: {_methods(result.approved_methods)}; finish H{result.approved_schedule.objective_finish}",
        f"Protected handoff policy: no lateness beyond H{PROTECTED_HANDOFF} when avoidable.",
        f"Disruption: {result.recovery.reason}",
        "",
        "EXHAUSTIVE ORACLE",
        f"Fastest feasible recovery: {_methods(result.fastest.methods)}; {_vector(result.fastest.vector)}",
        f"Delta=0 oracle: {_methods(result.oracle_delta0.methods)}; {_vector(result.oracle_delta0.vector)}",
        f"Delta=1 oracle: {_methods(result.oracle_delta1.methods)}; {_vector(result.oracle_delta1.vector)}",
        "",
        "ASPIRATION-BOUNDED CANDIDATE",
        (
            f"Delta=0: best finish H{delta0.best_finish}, allowed <=H{delta0.allowed_finish}; "
            f"selected {_methods(delta0.methods)}; {_vector(delta0.vector)}"
        ),
        (
            f"Delta=1: best finish H{delta1.best_finish}, allowed <=H{delta1.allowed_finish}; "
            f"selected {_methods(delta1.methods)}; {_vector(delta1.vector)}"
        ),
        f"Delta=0 matches exhaustive oracle: {_same_policy_choice(delta0, result.oracle_delta0)}",
        f"Delta=1 matches exhaustive oracle: {_same_policy_choice(delta1, result.oracle_delta1)}",
        f"Repeated Delta=1 solve is canonical: {result.deterministic_repeat}",
        "",
        "EXPLICIT DECISION REASON",
        (
            f"Fastest achievable finish is H{delta1.best_finish}. Policy permits recovery through "
            f"H{delta1.allowed_finish}. Both the fastest and approved-method recovery fit that envelope."
        ),
        (
            f"The H{delta1.vector.finish} recovery is selected because it changes "
            f"{delta1.vector.method_changes} approved methods versus "
            f"{delta0.vector.method_changes} in the H{delta0.vector.finish} fastest recovery."
        ),
        "Changing only Delta from 1h to 0h removes that concession and restores the true fastest recovery.",
        "",
        "WEIGHTED-SCORE SENSITIVITY",
    ]
    for item in result.weighted:
        lines.append(
            f"{item.profile}: {_methods(item.methods)}; score={item.score}; {_vector(item.vector)}"
        )
    lines.extend(
        (
            "",
            (
                "FALSIFICATION RESULT: FALSIFIED"
                if result.falsified
                else (
                    "FALSIFICATION RESULT: NOT FALSIFIED — an explicit 1h finish envelope "
                    "selects the structurally stable authorised recovery, while Delta=0 restores "
                    "the mathematically fastest recovery; both decisions match exhaustive enumeration."
                )
            ),
            (
                "Interpretation: this supports aspiration-bounded objective policy as a bounded "
                "planning hypothesis. It does not justify a permanent PlanningPolicy schema or a "
                "large multi-objective framework yet."
            ),
        )
    )
    return "\n".join(lines)


def main() -> int:
    result = run_experiment()
    print(render(result))
    return 1 if result.falsified else 0


if __name__ == "__main__":
    raise SystemExit(main())
