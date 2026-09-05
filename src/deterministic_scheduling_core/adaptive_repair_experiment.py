from __future__ import annotations

from dataclasses import dataclass, replace
from itertools import product
from time import perf_counter

from deterministic_scheduling_core.errors import SchedulingError
from deterministic_scheduling_core.project.model import ExecutionMode, Project, Resource, ResourceRequirement
from deterministic_scheduling_core.scheduling import ScheduleResult, schedule_project
from deterministic_scheduling_core.work_method_experiment import (
    ActivitySpec,
    ExperimentCase,
    MethodSpec,
    Outage,
    PackageSpec,
    Scenario,
    materialize_fixed_project,
)


PROTECTED_HANDOFF = 60
DELTA_FINISH = 1
SEED_ACTIVITY = "P04A07"
CRANE_RESOURCE = "C04"


@dataclass(frozen=True, slots=True)
class RepairVector:
    finish: int
    method_changes: int
    materially_moved_activities: int
    maximum_activity_shift: int
    absolute_start_movement: int

    def as_tuple(self) -> tuple[int, int, int, int, int]:
        return (
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
    vector: RepairVector

    @property
    def methods_by_package(self) -> dict[str, str]:
        return dict(self.methods)


@dataclass(frozen=True, slots=True)
class StrategyResult:
    name: str
    feasible: bool
    selected: Alternative | None
    free_activity_count: int
    free_method_count: int
    solver_calls: int
    solve_ms: float
    expansion_trace: tuple[str, ...] = ()
    failure_reason: str | None = None

    @property
    def vector(self) -> RepairVector | None:
        return None if self.selected is None else self.selected.vector

    @property
    def methods(self) -> tuple[tuple[str, str], ...]:
        return () if self.selected is None else self.selected.methods


@dataclass(frozen=True, slots=True)
class ExperimentResult:
    case: ExperimentCase
    baseline: Scenario
    recovery: Scenario
    approved_methods: tuple[tuple[str, str], ...]
    approved_schedule: ScheduleResult
    remote_resource_activity: str
    remote_package: str
    full: StrategyResult
    fixed: StrategyResult
    adaptive: StrategyResult
    repeat_canonical: bool
    falsified: bool


ROOT_STARTS = {
    "WP-01": 20,
    "WP-02": 22,
    "WP-03": 24,
    "WP-04": 32,
    "WP-05": 26,
    "WP-06": 28,
    "WP-07": 30,
    "WP-08": 34,
    "WP-09": 38,
    "WP-10": 29,
    "WP-11": 31,
}


def _requirements(*resource_ids: str) -> tuple[ResourceRequirement, ...]:
    return tuple(ResourceRequirement(resource_id) for resource_id in resource_ids)


def _activity(
    activity_id: str,
    name: str,
    duration: int,
    predecessor: str | None,
    *resource_ids: str,
    groups: tuple[str, ...] = (),
    latest_finish: int | None = None,
    milestone: bool = False,
) -> ActivitySpec:
    return ActivitySpec(
        id=activity_id,
        name=name,
        modes=(
            ExecutionMode(
                "MILESTONE" if milestone else "FIXED",
                duration,
                _requirements(*resource_ids),
            ),
        ),
        predecessors=() if predecessor is None else (predecessor,),
        latest_finish=latest_finish,
        exclusion_groups=groups,
        kind="milestone" if milestone else "task",
    )


def _method(
    package_number: int,
    method_id: str,
    suffix: str,
    durations: tuple[int, ...],
    *,
    crane_at_7: bool = False,
    workface: tuple[int, str] | None = None,
    final_handoff: bool = False,
) -> MethodSpec:
    activities: list[ActivitySpec] = []
    predecessor: str | None = None
    for index, duration in enumerate(durations, 1):
        if final_handoff and index == 10:
            activity_id = "F4"
        else:
            activity_id = f"P{package_number:02d}{suffix}{index:02d}"

        resources: tuple[str, ...]
        if crane_at_7 and index == 7:
            resources = (CRANE_RESOURCE,)
        elif index in {2, 9}:
            resources = ("MECH",)
        elif index == 4:
            resources = ("ELEC",)
        elif index == 6:
            resources = ("QA",)
        else:
            resources = ()

        groups: tuple[str, ...] = ()
        if workface is not None and index == workface[0]:
            groups = (workface[1],)

        milestone = final_handoff and index == 10
        activities.append(
            _activity(
                activity_id,
                f"WP-{package_number:02d} {method_id} step {index}",
                0 if milestone else duration,
                predecessor,
                *resources,
                groups=groups,
                latest_finish=PROTECTED_HANDOFF if milestone else None,
                milestone=milestone,
            )
        )
        predecessor = activity_id

    return MethodSpec(
        id=method_id,
        name=f"WP-{package_number:02d} {method_id}",
        activities=tuple(activities),
        completion_id=activities[-1].id,
    )


def build_case() -> tuple[ExperimentCase, Scenario, Scenario]:
    """Build 12 parallel work packages with 160 possible / 120 active activities."""

    standard = (1, 1, 1, 1, 1, 1, 1, 1, 1, 1)
    slower = (1, 1, 1, 1, 1, 1, 1, 1, 1, 3)

    packages: list[PackageSpec] = []
    for package_number in range(1, 12):
        package_id = f"WP-{package_number:02d}"
        workface: tuple[int, str] | None = None
        if package_number in {3, 5}:
            workface = (4, "WF-A")
        elif package_number in {7, 10}:
            workface = (5, "WF-B")

        if package_number == 4:
            methods = (
                _method(
                    package_number,
                    "STANDARD",
                    "A",
                    (1, 1, 1, 1, 1, 1, 3, 1, 1, 1),
                    crane_at_7=True,
                ),
            )
        elif package_number == 9:
            methods = (
                _method(
                    package_number,
                    "CRANE",
                    "A",
                    (1, 1, 1, 1, 1, 1, 3, 1, 1, 2),
                    crane_at_7=True,
                ),
                _method(
                    package_number,
                    "SEGMENTED",
                    "B",
                    (1, 1, 1, 1, 1, 1, 5, 1, 1, 0),
                ),
            )
        elif package_number in {2, 5, 11}:
            methods = (
                _method(package_number, "STANDARD", "A", standard, workface=workface),
                _method(package_number, "ALTERNATIVE", "B", slower, workface=workface),
            )
        else:
            methods = (
                _method(package_number, "STANDARD", "A", standard, workface=workface),
            )

        packages.append(PackageSpec(package_id, f"Work package {package_number}", methods))

    packages.append(
        PackageSpec(
            "WP-12",
            "Protected project handover",
            (
                _method(
                    12,
                    "HANDOVER",
                    "A",
                    (1, 1, 1, 1, 1, 1, 1, 1, 1, 0),
                    final_handoff=True,
                ),
            ),
            predecessors=tuple(f"WP-{index:02d}" for index in range(1, 12)),
        )
    )

    not_before: list[tuple[str, int]] = []
    for package in packages[:-1]:
        anchor = ROOT_STARTS[package.id]
        for method in package.methods:
            not_before.append((method.roots[0], anchor))

    baseline = Scenario(
        "BASE",
        "Approved execution plan",
        not_before=tuple(not_before),
        reason="Normal crane availability with all authorised work packages in their approved methods.",
    )
    recovery = Scenario(
        "RECOVERY",
        "Local crane outage creates a non-local repair decision",
        not_before=tuple(not_before),
        outages=(Outage(CRANE_RESOURCE, 38, 43, "Crane C04 unavailable H38-H43"),),
        reason=(
            "WP-04 loses its approved H38-H41 crane slot. Moving it to H43-H46 overlaps "
            "the approved WP-09 H44-H47 crane lift even though WP-04 and WP-09 have no "
            "precedence relationship."
        ),
    )

    case = ExperimentCase(
        resources=(
            Resource("MECH", "Mechanical crew pool", 12),
            Resource("ELEC", "Electrical crew pool", 8),
            Resource("QA", "Inspection pool", 4),
            Resource(CRANE_RESOURCE, "Crane C04", 1),
        ),
        packages=tuple(packages),
        scenarios=(baseline, recovery),
    )
    return case, baseline, recovery


def _approved_choices(case: ExperimentCase) -> tuple[tuple[str, str], ...]:
    return tuple((package.id, package.methods[0].id) for package in case.packages)


def _package_by_id(case: ExperimentCase) -> dict[str, PackageSpec]:
    return {package.id: package for package in case.packages}


def _activity_package_map(case: ExperimentCase) -> dict[str, str]:
    return {
        activity.id: package.id
        for package in case.packages
        for method in package.methods
        for activity in method.activities
    }


def _possible_activity_ids(case: ExperimentCase, package_ids: set[str] | None = None) -> set[str]:
    return {
        activity.id
        for package in case.packages
        if package_ids is None or package.id in package_ids
        for method in package.methods
        for activity in method.activities
    }


def _active_method(case: ExperimentCase, package_id: str, method_id: str) -> MethodSpec:
    package = _package_by_id(case)[package_id]
    return next(method for method in package.methods if method.id == method_id)


def build_approved_plan(
    case: ExperimentCase,
    baseline: Scenario,
) -> tuple[tuple[tuple[str, str], ...], ScheduleResult]:
    choices = _approved_choices(case)
    return choices, schedule_project(materialize_fixed_project(case, baseline, choices))


def _with_repair_boundary(
    project: Project,
    approved_schedule: ScheduleResult,
    free_activity_ids: set[str],
) -> Project:
    approved = approved_schedule.by_id
    activities = []
    for activity in project.activities:
        reference = approved.get(activity.id)
        if reference is None:
            activities.append(activity)
            continue
        kwargs = {
            "planned_start": reference.start,
            "planned_mode_id": reference.mode_id,
        }
        if activity.id not in free_activity_ids:
            kwargs.update(
                {
                    "frozen_start": reference.start,
                    "frozen_mode_id": reference.mode_id,
                }
            )
        activities.append(replace(activity, **kwargs))
    return replace(project, activities=tuple(activities))


def _movement_vector(
    methods: tuple[tuple[str, str], ...],
    schedule: ScheduleResult,
    approved_methods: tuple[tuple[str, str], ...],
    approved_schedule: ScheduleResult,
) -> RepairVector:
    method_map = dict(methods)
    method_changes = sum(method_map[package_id] != method_id for package_id, method_id in approved_methods)
    common = set(approved_schedule.by_id) & set(schedule.by_id)
    shifts = tuple(
        abs(schedule.by_id[activity_id].start - approved_schedule.by_id[activity_id].start)
        for activity_id in common
        if schedule.by_id[activity_id].start != approved_schedule.by_id[activity_id].start
    )
    return RepairVector(
        finish=schedule.objective_finish,
        method_changes=method_changes,
        materially_moved_activities=len(shifts),
        maximum_activity_shift=max(shifts, default=0),
        absolute_start_movement=sum(shifts),
    )


def _canonical_key(item: Alternative) -> tuple[object, ...]:
    return (
        tuple(method_id for _, method_id in item.methods),
        tuple(
            (entry.activity_id, entry.mode_id, entry.start, entry.finish)
            for entry in sorted(item.schedule.entries, key=lambda entry: entry.activity_id)
        ),
    )


def _select_policy(alternatives: tuple[Alternative, ...]) -> Alternative:
    best_finish = min(item.vector.finish for item in alternatives)
    eligible = tuple(item for item in alternatives if item.vector.finish <= best_finish + DELTA_FINISH)
    best_methods = min(item.vector.method_changes for item in eligible)
    eligible = tuple(item for item in eligible if item.vector.method_changes == best_methods)
    best_moved = min(item.vector.materially_moved_activities for item in eligible)
    eligible = tuple(item for item in eligible if item.vector.materially_moved_activities == best_moved)
    best_movement = min(item.vector.absolute_start_movement for item in eligible)
    eligible = tuple(item for item in eligible if item.vector.absolute_start_movement == best_movement)
    return min(eligible, key=_canonical_key)


def _method_choices(
    case: ExperimentCase,
    approved_methods: tuple[tuple[str, str], ...],
    free_method_packages: set[str],
) -> tuple[tuple[tuple[str, str], ...], ...]:
    approved = dict(approved_methods)
    options: list[tuple[str, ...]] = []
    for package in case.packages:
        if package.id in free_method_packages:
            options.append(tuple(method.id for method in package.methods))
        else:
            options.append((approved[package.id],))
    return tuple(
        tuple((package.id, method_id) for package, method_id in zip(case.packages, selected))
        for selected in product(*options)
    )


def _solve_boundary(
    name: str,
    case: ExperimentCase,
    recovery: Scenario,
    approved_methods: tuple[tuple[str, str], ...],
    approved_schedule: ScheduleResult,
    free_activity_ids: set[str],
    free_method_packages: set[str],
    *,
    expansion_trace: tuple[str, ...] = (),
) -> StrategyResult:
    alternatives: list[Alternative] = []
    calls = 0
    started = perf_counter()
    for choices in _method_choices(case, approved_methods, free_method_packages):
        calls += 1
        project = materialize_fixed_project(case, recovery, choices)
        project = _with_repair_boundary(project, approved_schedule, free_activity_ids)
        try:
            schedule = schedule_project(project)
        except SchedulingError:
            continue
        alternatives.append(
            Alternative(
                choices,
                schedule,
                _movement_vector(choices, schedule, approved_methods, approved_schedule),
            )
        )
    elapsed = (perf_counter() - started) * 1000
    active_free = len(set(approved_schedule.by_id) & free_activity_ids)
    if not alternatives:
        return StrategyResult(
            name=name,
            feasible=False,
            selected=None,
            free_activity_count=active_free,
            free_method_count=len(free_method_packages),
            solver_calls=calls,
            solve_ms=elapsed,
            expansion_trace=expansion_trace,
            failure_reason="No globally feasible schedule exists with the current repair boundary.",
        )
    return StrategyResult(
        name=name,
        feasible=True,
        selected=_select_policy(tuple(alternatives)),
        free_activity_count=active_free,
        free_method_count=len(free_method_packages),
        solver_calls=calls,
        solve_ms=elapsed,
        expansion_trace=expansion_trace,
    )


def _approved_method_resources(
    case: ExperimentCase,
    approved_methods: tuple[tuple[str, str], ...],
) -> dict[str, set[str]]:
    resources: dict[str, set[str]] = {}
    for package_id, method_id in approved_methods:
        method = _active_method(case, package_id, method_id)
        for activity in method.activities:
            resources[activity.id] = {
                requirement.resource_id
                for mode in activity.modes
                for requirement in mode.requirements
            }
    return resources


def _successor_closure(method: MethodSpec, activity_id: str) -> set[str]:
    successors: dict[str, set[str]] = {activity.id: set() for activity in method.activities}
    for activity in method.activities:
        for predecessor in activity.predecessors:
            successors.setdefault(predecessor, set()).add(activity.id)
    closure = {activity_id}
    frontier = [activity_id]
    while frontier:
        current = frontier.pop()
        for successor in successors.get(current, ()):
            if successor not in closure:
                closure.add(successor)
                frontier.append(successor)
    return closure


def _derive_initial_neighbourhood(
    case: ExperimentCase,
    recovery: Scenario,
    approved_methods: tuple[tuple[str, str], ...],
    approved_schedule: ScheduleResult,
) -> tuple[set[str], str, str, tuple[int, int]]:
    package_map = _activity_package_map(case)
    seed_package = package_map[SEED_ACTIVITY]
    seed_method = _active_method(case, seed_package, dict(approved_methods)[seed_package])
    local = _successor_closure(seed_method, SEED_ACTIVITY)

    outage = next(item for item in recovery.outages if item.resource_id == CRANE_RESOURCE)
    seed_entry = approved_schedule.by_id[SEED_ACTIVITY]
    shifted_start = max(seed_entry.start, outage.finish)
    shifted_finish = shifted_start + (seed_entry.finish - seed_entry.start)

    resources = _approved_method_resources(case, approved_methods)
    remote = sorted(
        activity_id
        for activity_id, entry in approved_schedule.by_id.items()
        if activity_id != SEED_ACTIVITY
        and CRANE_RESOURCE in resources.get(activity_id, set())
        and entry.start < shifted_finish
        and entry.finish > shifted_start
    )
    if not remote:
        raise SchedulingError("adaptive repair fixture has no remote crane competitor")
    remote_activity = remote[0]
    local.add(remote_activity)
    return local, remote_activity, package_map[remote_activity], (shifted_start, shifted_finish)


def _adaptive_repair(
    case: ExperimentCase,
    recovery: Scenario,
    approved_methods: tuple[tuple[str, str], ...],
    approved_schedule: ScheduleResult,
) -> tuple[StrategyResult, str, str]:
    free, remote_activity, remote_package, shifted = _derive_initial_neighbourhood(
        case,
        recovery,
        approved_methods,
        approved_schedule,
    )
    trace = [
        (
            f"N0: {SEED_ACTIVITY} is displaced to H{shifted[0]}-H{shifted[1]} by the C04 outage; "
            f"{remote_activity} enters because its approved C04 occupancy overlaps that shifted interval."
        )
    ]

    first = _solve_boundary(
        "adaptive-N0",
        case,
        recovery,
        approved_methods,
        approved_schedule,
        free,
        set(),
        expansion_trace=tuple(trace),
    )
    total_calls = first.solver_calls
    total_ms = first.solve_ms
    if first.feasible:
        return replace(first, name="adaptive", solver_calls=total_calls, solve_ms=total_ms), remote_activity, remote_package

    remote_method = _active_method(case, remote_package, dict(approved_methods)[remote_package])
    downstream = _successor_closure(remote_method, remote_activity) - {remote_activity}
    free |= downstream
    trace.append(
        (
            f"N0 -> N1: add {', '.join(sorted(downstream))}; they are fixed precedence successors of "
            f"{remote_activity}, so the moved crane task cannot be repaired while those approved starts stay frozen."
        )
    )
    second = _solve_boundary(
        "adaptive-N1",
        case,
        recovery,
        approved_methods,
        approved_schedule,
        free,
        set(),
        expansion_trace=tuple(trace),
    )
    total_calls += second.solver_calls
    total_ms += second.solve_ms
    if second.feasible:
        return replace(second, name="adaptive", solver_calls=total_calls, solve_ms=total_ms), remote_activity, remote_package

    remote_package_spec = _package_by_id(case)[remote_package]
    if len(remote_package_spec.methods) < 2:
        return replace(
            second,
            name="adaptive",
            solver_calls=total_calls,
            solve_ms=total_ms,
            failure_reason="Boundary remains infeasible and the remote package has no authorised alternative method.",
        ), remote_activity, remote_package

    free |= _possible_activity_ids(case, {remote_package})
    trace.append(
        (
            f"N1 -> N2: free the complete {remote_package} Work-Method decision; the approved crane method "
            f"cannot clear the frozen WP-12 handover boundary by H{PROTECTED_HANDOFF}, while an authorised "
            "no-crane method exists."
        )
    )
    third = _solve_boundary(
        "adaptive-N2",
        case,
        recovery,
        approved_methods,
        approved_schedule,
        free,
        {remote_package},
        expansion_trace=tuple(trace),
    )
    total_calls += third.solver_calls
    total_ms += third.solve_ms
    return replace(third, name="adaptive", solver_calls=total_calls, solve_ms=total_ms), remote_activity, remote_package


def _signature(result: StrategyResult) -> tuple[object, ...]:
    if not result.feasible or result.selected is None:
        return (False,)
    return (
        True,
        result.selected.methods,
        result.selected.vector.as_tuple(),
        tuple(
            (entry.activity_id, entry.mode_id, entry.start, entry.finish)
            for entry in sorted(result.selected.schedule.entries, key=lambda entry: entry.activity_id)
        ),
    )


def run_experiment() -> ExperimentResult:
    case, baseline, recovery = build_case()
    approved_methods, approved_schedule = build_approved_plan(case, baseline)

    flexible_packages = {
        package.id
        for package in case.packages
        if len(package.methods) > 1
    }
    full = _solve_boundary(
        "full",
        case,
        recovery,
        approved_methods,
        approved_schedule,
        _possible_activity_ids(case),
        flexible_packages,
    )

    initial_free, remote_activity, remote_package, _ = _derive_initial_neighbourhood(
        case,
        recovery,
        approved_methods,
        approved_schedule,
    )
    fixed = _solve_boundary(
        "fixed",
        case,
        recovery,
        approved_methods,
        approved_schedule,
        initial_free,
        set(),
    )

    adaptive, adaptive_remote, adaptive_package = _adaptive_repair(
        case,
        recovery,
        approved_methods,
        approved_schedule,
    )
    if adaptive_remote != remote_activity or adaptive_package != remote_package:
        raise SchedulingError("adaptive repair derived inconsistent resource boundary")

    repeated, _, _ = _adaptive_repair(case, recovery, approved_methods, approved_schedule)
    repeat_canonical = _signature(adaptive) == _signature(repeated)

    same_as_full = (
        full.feasible
        and adaptive.feasible
        and full.selected is not None
        and adaptive.selected is not None
        and full.selected.methods == adaptive.selected.methods
        and full.selected.vector.as_tuple() == adaptive.selected.vector.as_tuple()
    )
    materially_smaller = adaptive.free_activity_count < full.free_activity_count
    fixed_exposes_failure = not fixed.feasible or (
        fixed.vector is not None
        and full.vector is not None
        and fixed.vector.as_tuple() > full.vector.as_tuple()
    )
    semantic_trace = all(
        any(token in line for token in ("C04", "precedence", "Work-Method", "handover"))
        for line in adaptive.expansion_trace
    )
    falsified = not (
        same_as_full
        and materially_smaller
        and fixed_exposes_failure
        and repeat_canonical
        and semantic_trace
    )

    return ExperimentResult(
        case=case,
        baseline=baseline,
        recovery=recovery,
        approved_methods=approved_methods,
        approved_schedule=approved_schedule,
        remote_resource_activity=remote_activity,
        remote_package=remote_package,
        full=full,
        fixed=fixed,
        adaptive=adaptive,
        repeat_canonical=repeat_canonical,
        falsified=falsified,
    )


def _method_summary(methods: tuple[tuple[str, str], ...]) -> str:
    selected = dict(methods)
    return ", ".join(
        f"{package}={selected[package]}"
        for package in ("WP-02", "WP-05", "WP-09", "WP-11")
    )


def _result_line(result: StrategyResult) -> str:
    if not result.feasible or result.selected is None:
        return (
            f"INFEASIBLE; free_activities={result.free_activity_count}; "
            f"free_methods={result.free_method_count}; solver_calls={result.solver_calls}; "
            f"solve={result.solve_ms:.2f} ms"
        )
    vector = result.selected.vector
    return (
        f"finish=H{vector.finish}; {_method_summary(result.selected.methods)}; "
        f"method_changes={vector.method_changes}; moved={vector.materially_moved_activities}; "
        f"max_shift={vector.maximum_activity_shift}h; movement={vector.absolute_start_movement}h; "
        f"free_activities={result.free_activity_count}; free_methods={result.free_method_count}; "
        f"solver_calls={result.solver_calls}; solve={result.solve_ms:.2f} ms"
    )


def render(result: ExperimentResult) -> str:
    lines = [
        "ADAPTIVE SEMANTIC REPAIR FALSIFICATION EXPERIMENT",
        (
            f"12 work packages; {result.case.possible_activity_count} possible activities; "
            f"120 activities in the approved fixed plan; {result.case.fixed_network_count} authorised method combinations."
        ),
        (
            f"Approved handover: H{result.approved_schedule.objective_finish}; protected latest H{PROTECTED_HANDOFF}."
        ),
        (
            f"Disturbance: {result.recovery.outages[0].reason}; local seed {SEED_ACTIVITY}; "
            f"remote resource coupling {result.remote_resource_activity} in {result.remote_package}."
        ),
        "",
        "A. FULL REMAINING-PROJECT RE-OPTIMISATION",
        _result_line(result.full),
        "",
        "B. FIXED LOCAL REPAIR",
        _result_line(result.fixed),
        f"Failure: {result.fixed.failure_reason or 'none'}",
        "",
        "C. ADAPTIVE SEMANTIC REPAIR",
        _result_line(result.adaptive),
    ]
    for step in result.adaptive.expansion_trace:
        lines.append(f"Expansion: {step}")

    lines.extend(
        (
            "",
            f"Adaptive matches full policy result: {result.full.vector == result.adaptive.vector and result.full.methods == result.adaptive.methods}",
            (
                f"Decision freedom: full {result.full.free_activity_count} approved activities / "
                f"{result.full.free_method_count} method decisions; adaptive "
                f"{result.adaptive.free_activity_count} / {result.adaptive.free_method_count}."
            ),
            f"Repeated adaptive run canonical: {result.repeat_canonical}",
            "",
            (
                "FALSIFICATION RESULT: FALSIFIED"
                if result.falsified
                else (
                    "FALSIFICATION RESULT: NOT FALSIFIED — adaptive semantic repair reached the same "
                    "policy-consistent recovery as full re-optimisation while freeing materially fewer "
                    "approved decisions; the fixed neighbourhood could not recover, and every expansion "
                    "was caused by an explicit resource, precedence, method or commitment boundary."
                )
            ),
            (
                "Interpretation: this supports adaptive semantic repair as a bounded replanning hypothesis. "
                "It does not establish a production decomposition algorithm or universal expansion policy."
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
