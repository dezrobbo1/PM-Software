from __future__ import annotations

from dataclasses import dataclass, replace

from deterministic_scheduling_core.adaptive_repair_experiment import (
    PROTECTED_HANDOFF,
    _possible_activity_ids,
    _solve_boundary,
    build_approved_plan,
    build_case,
)
from deterministic_scheduling_core.errors import SchedulingError
from deterministic_scheduling_core.project.model import Project
from deterministic_scheduling_core.work_method_experiment import ExperimentCase, Scenario, materialize_fixed_project


RESOURCE_SENSITIVE_ACTIVITY = "P04A07"
METHOD_SENSITIVE_ACTIVITY = "P09A07"
REMOTE_METHOD_PACKAGE = "WP-09"
MAX_PERTURBATION = 12


@dataclass(frozen=True, slots=True)
class LogicTiming:
    activity_id: str
    early_start: int
    early_finish: int
    late_start: int
    late_finish: int
    total_float: int

    @property
    def critical(self) -> bool:
        return self.total_float == 0


@dataclass(frozen=True, slots=True)
class Counterfactual:
    activity_id: str
    duration_increase: int
    fixed_structure_feasible: bool
    fixed_structure_finish: int | None
    adaptive_feasible: bool
    adaptive_finish: int | None
    adaptive_method_changes: int | None
    adaptive_methods: tuple[tuple[str, str], ...]

    @property
    def adaptive_methods_by_package(self) -> dict[str, str]:
        return dict(self.adaptive_methods)


@dataclass(frozen=True, slots=True)
class ActivityCriticalityResult:
    activity_id: str
    logic: LogicTiming
    fixed_structure_slack: int
    first_method_change_delta: int | None
    counterfactual: Counterfactual


@dataclass(frozen=True, slots=True)
class ExperimentResult:
    case: ExperimentCase
    baseline: Scenario
    approved_methods: tuple[tuple[str, str], ...]
    approved_handoff: int
    logic_zero_float_ids: tuple[str, ...]
    resource_sensitive: ActivityCriticalityResult
    method_sensitive: ActivityCriticalityResult
    repeated_adaptive_canonical: bool
    falsified: bool


def _selected_duration(project: Project, activity_id: str) -> int:
    activity = project.activity_by_id[activity_id]
    if len(activity.modes) != 1:
        raise SchedulingError(
            f"logic CPM experiment requires one selected mode per materialised activity: {activity_id}"
        )
    return activity.modes[0].duration


def _logic_cpm(project: Project, finish_target: int) -> dict[str, LogicTiming]:
    """CPM analysis of one selected activity structure, deliberately ignoring resources."""

    activities = project.activity_by_id
    successors: dict[str, list[str]] = {activity_id: [] for activity_id in activities}
    indegree = {activity_id: 0 for activity_id in activities}
    for activity in project.activities:
        for predecessor in activity.predecessors:
            successors[predecessor].append(activity.id)
            indegree[activity.id] += 1

    ready = sorted(activity_id for activity_id, count in indegree.items() if count == 0)
    order: list[str] = []
    while ready:
        activity_id = ready.pop(0)
        order.append(activity_id)
        for successor in sorted(successors[activity_id]):
            indegree[successor] -= 1
            if indegree[successor] == 0:
                ready.append(successor)
                ready.sort()

    if len(order) != len(activities):
        raise SchedulingError("logic CPM experiment requires an acyclic selected activity network")

    early_start: dict[str, int] = {}
    early_finish: dict[str, int] = {}
    for activity_id in order:
        activity = activities[activity_id]
        predecessor_finish = max(
            (early_finish[predecessor] for predecessor in activity.predecessors),
            default=0,
        )
        start = max(activity.not_before, predecessor_finish)
        early_start[activity_id] = start
        early_finish[activity_id] = start + _selected_duration(project, activity_id)

    objective_id = project.objective_activity_id
    if objective_id is None:
        raise SchedulingError("logic CPM experiment requires a controlling objective activity")
    if early_finish[objective_id] > finish_target:
        raise SchedulingError(
            f"logic CPM earliest finish H{early_finish[objective_id]} exceeds target H{finish_target}"
        )

    late_start: dict[str, int] = {}
    late_finish: dict[str, int] = {}
    for activity_id in reversed(order):
        if activity_id == objective_id:
            finish = finish_target
        elif successors[activity_id]:
            finish = min(late_start[successor] for successor in successors[activity_id])
        else:
            finish = finish_target
        duration = _selected_duration(project, activity_id)
        late_finish[activity_id] = finish
        late_start[activity_id] = finish - duration

    return {
        activity_id: LogicTiming(
            activity_id=activity_id,
            early_start=early_start[activity_id],
            early_finish=early_finish[activity_id],
            late_start=late_start[activity_id],
            late_finish=late_finish[activity_id],
            total_float=late_start[activity_id] - early_start[activity_id],
        )
        for activity_id in order
    }


def _increase_duration(case: ExperimentCase, activity_id: str, delta: int) -> ExperimentCase:
    matched = False
    packages = []
    for package in case.packages:
        methods = []
        for method in package.methods:
            activities = []
            for activity in method.activities:
                if activity.id != activity_id:
                    activities.append(activity)
                    continue
                matched = True
                activities.append(
                    replace(
                        activity,
                        modes=tuple(
                            replace(mode, duration=mode.duration + delta)
                            for mode in activity.modes
                        ),
                    )
                )
            methods.append(replace(method, activities=tuple(activities)))
        packages.append(replace(package, methods=tuple(methods)))
    if not matched:
        raise SchedulingError(f"unknown perturbation activity {activity_id}")
    return replace(case, packages=tuple(packages))


def _flexible_packages(case: ExperimentCase) -> set[str]:
    return {package.id for package in case.packages if len(package.methods) > 1}


def _counterfactual(
    case: ExperimentCase,
    baseline: Scenario,
    approved_methods: tuple[tuple[str, str], ...],
    approved_schedule,
    activity_id: str,
    delta: int,
) -> Counterfactual:
    changed = _increase_duration(case, activity_id, delta)
    free_activities = _possible_activity_ids(changed)

    fixed = _solve_boundary(
        "criticality-fixed",
        changed,
        baseline,
        approved_methods,
        approved_schedule,
        free_activities,
        set(),
    )
    adaptive = _solve_boundary(
        "criticality-adaptive",
        changed,
        baseline,
        approved_methods,
        approved_schedule,
        free_activities,
        _flexible_packages(changed),
    )

    return Counterfactual(
        activity_id=activity_id,
        duration_increase=delta,
        fixed_structure_feasible=fixed.feasible,
        fixed_structure_finish=None if fixed.vector is None else fixed.vector.finish,
        adaptive_feasible=adaptive.feasible,
        adaptive_finish=None if adaptive.vector is None else adaptive.vector.finish,
        adaptive_method_changes=(
            None if adaptive.vector is None else adaptive.vector.method_changes
        ),
        adaptive_methods=adaptive.methods,
    )


def _fixed_structure_slack(
    case: ExperimentCase,
    baseline: Scenario,
    approved_methods: tuple[tuple[str, str], ...],
    approved_schedule,
    activity_id: str,
) -> int:
    slack = 0
    for delta in range(1, MAX_PERTURBATION + 1):
        changed = _increase_duration(case, activity_id, delta)
        fixed = _solve_boundary(
            "criticality-fixed-slack",
            changed,
            baseline,
            approved_methods,
            approved_schedule,
            _possible_activity_ids(changed),
            set(),
        )
        if not fixed.feasible:
            return slack
        slack = delta
    return slack


def _first_method_change_delta(
    case: ExperimentCase,
    baseline: Scenario,
    approved_methods: tuple[tuple[str, str], ...],
    approved_schedule,
    activity_id: str,
    search_limit: int,
) -> int | None:
    for delta in range(1, search_limit + 1):
        changed = _increase_duration(case, activity_id, delta)
        adaptive = _solve_boundary(
            "criticality-method-threshold",
            changed,
            baseline,
            approved_methods,
            approved_schedule,
            _possible_activity_ids(changed),
            _flexible_packages(changed),
        )
        if adaptive.feasible and adaptive.methods != approved_methods:
            return delta
    return None


def _signature(counterfactual: Counterfactual) -> tuple[object, ...]:
    return (
        counterfactual.fixed_structure_feasible,
        counterfactual.fixed_structure_finish,
        counterfactual.adaptive_feasible,
        counterfactual.adaptive_finish,
        counterfactual.adaptive_method_changes,
        counterfactual.adaptive_methods,
    )


def run_experiment() -> ExperimentResult:
    case, baseline, _ = build_case()
    approved_methods, approved_schedule = build_approved_plan(case, baseline)
    selected_project = materialize_fixed_project(case, baseline, approved_methods)
    logic = _logic_cpm(selected_project, PROTECTED_HANDOFF)

    resource_logic = logic[RESOURCE_SENSITIVE_ACTIVITY]
    method_logic = logic[METHOD_SENSITIVE_ACTIVITY]

    resource_fixed_slack = _fixed_structure_slack(
        case,
        baseline,
        approved_methods,
        approved_schedule,
        RESOURCE_SENSITIVE_ACTIVITY,
    )
    resource_method_change = _first_method_change_delta(
        case,
        baseline,
        approved_methods,
        approved_schedule,
        RESOURCE_SENSITIVE_ACTIVITY,
        max(resource_logic.total_float, 1),
    )
    resource_delta = resource_method_change or max(1, resource_fixed_slack + 1)
    resource_counterfactual = _counterfactual(
        case,
        baseline,
        approved_methods,
        approved_schedule,
        RESOURCE_SENSITIVE_ACTIVITY,
        resource_delta,
    )

    method_fixed_slack = _fixed_structure_slack(
        case,
        baseline,
        approved_methods,
        approved_schedule,
        METHOD_SENSITIVE_ACTIVITY,
    )
    method_method_change = _first_method_change_delta(
        case,
        baseline,
        approved_methods,
        approved_schedule,
        METHOD_SENSITIVE_ACTIVITY,
        1,
    )
    method_counterfactual = _counterfactual(
        case,
        baseline,
        approved_methods,
        approved_schedule,
        METHOD_SENSITIVE_ACTIVITY,
        1,
    )
    repeated_method_counterfactual = _counterfactual(
        case,
        baseline,
        approved_methods,
        approved_schedule,
        METHOD_SENSITIVE_ACTIVITY,
        1,
    )

    resource_result = ActivityCriticalityResult(
        activity_id=RESOURCE_SENSITIVE_ACTIVITY,
        logic=resource_logic,
        fixed_structure_slack=resource_fixed_slack,
        first_method_change_delta=resource_method_change,
        counterfactual=resource_counterfactual,
    )
    method_result = ActivityCriticalityResult(
        activity_id=METHOD_SENSITIVE_ACTIVITY,
        logic=method_logic,
        fixed_structure_slack=method_fixed_slack,
        first_method_change_delta=method_method_change,
        counterfactual=method_counterfactual,
    )

    resource_divergence = (
        resource_logic.total_float > resource_fixed_slack
        and resource_method_change is not None
        and resource_method_change <= resource_logic.total_float
        and resource_counterfactual.adaptive_feasible
        and resource_counterfactual.adaptive_method_changes is not None
        and resource_counterfactual.adaptive_method_changes > 0
    )
    method_divergence = (
        method_logic.total_float == 0
        and method_fixed_slack == 0
        and not method_counterfactual.fixed_structure_feasible
        and method_counterfactual.adaptive_feasible
        and method_counterfactual.adaptive_finish is not None
        and method_counterfactual.adaptive_finish <= PROTECTED_HANDOFF
        and method_counterfactual.adaptive_methods_by_package.get(REMOTE_METHOD_PACKAGE)
        == "SEGMENTED"
    )
    repeated_adaptive_canonical = (
        _signature(method_counterfactual) == _signature(repeated_method_counterfactual)
    )

    falsified = not (
        approved_schedule.objective_finish == PROTECTED_HANDOFF
        and resource_divergence
        and method_divergence
        and repeated_adaptive_canonical
    )

    zero_float = tuple(
        sorted(activity_id for activity_id, timing in logic.items() if timing.critical)
    )
    return ExperimentResult(
        case=case,
        baseline=baseline,
        approved_methods=approved_methods,
        approved_handoff=approved_schedule.objective_finish,
        logic_zero_float_ids=zero_float,
        resource_sensitive=resource_result,
        method_sensitive=method_result,
        repeated_adaptive_canonical=repeated_adaptive_canonical,
        falsified=falsified,
    )


def _counterfactual_line(item: ActivityCriticalityResult) -> str:
    cf = item.counterfactual
    adaptive_method = cf.adaptive_methods_by_package.get(REMOTE_METHOD_PACKAGE, "n/a")
    fixed = (
        "INFEASIBLE"
        if not cf.fixed_structure_feasible
        else f"H{cf.fixed_structure_finish}"
    )
    adaptive = (
        "INFEASIBLE"
        if not cf.adaptive_feasible
        else f"H{cf.adaptive_finish}; {REMOTE_METHOD_PACKAGE}={adaptive_method}; "
        f"method_changes={cf.adaptive_method_changes}"
    )
    return (
        f"{item.activity_id}: logic_float={item.logic.total_float}h; "
        f"fixed_structure_slack={item.fixed_structure_slack}h; "
        f"test=+{cf.duration_increase}h; fixed={fixed}; adaptive={adaptive}"
    )


def render(result: ExperimentResult) -> str:
    resource = result.resource_sensitive
    method = result.method_sensitive
    lines = [
        "CRITICALITY SEMANTICS FALSIFICATION EXPERIMENT",
        (
            f"Selected approved structure from the 12-work-package adaptive-repair fixture; "
            f"approved handoff H{result.approved_handoff}."
        ),
        "Logic CPM deliberately ignores resource capacity and method reselection; counterfactual analysis uses the integrated resource/method scheduler and the existing repair policy.",
        "",
        "LOGIC CPM",
        (
            f"Zero-float activities in the selected logic structure: {len(result.logic_zero_float_ids)}; "
            f"{METHOD_SENSITIVE_ACTIVITY} float={method.logic.total_float}h; "
            f"{RESOURCE_SENSITIVE_ACTIVITY} float={resource.logic.total_float}h."
        ),
        "",
        "RESOURCE-SENSITIVE NON-CRITICAL ACTIVITY",
        _counterfactual_line(resource),
        (
            f"First authorised method reselection occurs at +{resource.first_method_change_delta}h, "
            f"before the {resource.logic.total_float}h logic float is exhausted."
        ),
        "Reason: extending the WP-04 C04 task reaches the approved WP-09 C04 occupancy; the resource coupling is not represented by the precedence-only CPM float.",
        "",
        "LOGIC-CRITICAL BUT ADAPTIVELY RECOVERABLE ACTIVITY",
        _counterfactual_line(method),
        "Reason: the approved WP-09 crane method has zero logic float, but a +1h duration increase can be absorbed by selecting the authorised SEGMENTED method instead of accepting a later handoff.",
        "",
        f"Repeated adaptive counterfactual is canonical: {result.repeated_adaptive_canonical}",
        "",
        (
            "FALSIFICATION RESULT: "
            + (
                "FALSIFIED — the bounded case did not demonstrate a material distinction between logic float and executable criticality."
                if result.falsified
                else "NOT FALSIFIED — logic CPM remains useful as a fixed-structure dependency analysis, but it is not executable slack or authoritative criticality once resource coupling and authorised method choices are active."
            )
        ),
        (
            "Interpretation: reserve 'critical path' and 'logic float' for the selected precedence structure. "
            "For execution control, expose counterfactual/policy criticality as an impact vector (finish/commitment effect, method reselection, schedule movement and causal constraint) rather than forcing every critical decision into one continuous path."
        ),
    ]
    return "\n".join(lines)


def main() -> None:
    print(render(run_experiment()))


if __name__ == "__main__":
    main()
