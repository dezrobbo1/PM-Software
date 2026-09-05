from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from time import perf_counter

from ortools.sat.python import cp_model

from deterministic_scheduling_core.errors import SchedulingError
from deterministic_scheduling_core.project.model import (
    Activity,
    ExecutionMode,
    Project,
    Resource,
    ResourceRequirement,
)
from deterministic_scheduling_core.scheduling import ScheduleResult, schedule_project


@dataclass(frozen=True, slots=True)
class ActivitySpec:
    id: str
    name: str
    modes: tuple[ExecutionMode, ...]
    predecessors: tuple[str, ...] = ()
    latest_finish: int | None = None
    exclusion_groups: tuple[str, ...] = ()
    kind: str = "task"


@dataclass(frozen=True, slots=True)
class MethodSpec:
    id: str
    name: str
    activities: tuple[ActivitySpec, ...]
    completion_id: str

    @property
    def roots(self) -> tuple[str, ...]:
        ids = {activity.id for activity in self.activities}
        return tuple(
            activity.id
            for activity in self.activities
            if not (set(activity.predecessors) & ids)
        )


@dataclass(frozen=True, slots=True)
class PackageSpec:
    id: str
    name: str
    methods: tuple[MethodSpec, ...]
    predecessors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Outage:
    resource_id: str
    start: int
    finish: int
    reason: str


@dataclass(frozen=True, slots=True)
class Scenario:
    id: str
    name: str
    not_before: tuple[tuple[str, int], ...] = ()
    latest_finish: tuple[tuple[str, int], ...] = ()
    outages: tuple[Outage, ...] = ()
    reason: str = ""


@dataclass(frozen=True, slots=True)
class ExperimentCase:
    resources: tuple[Resource, ...]
    packages: tuple[PackageSpec, ...]
    scenarios: tuple[Scenario, ...]

    @property
    def fixed_network_count(self) -> int:
        count = 1
        for package in self.packages:
            count *= len(package.methods)
        return count

    @property
    def possible_activity_count(self) -> int:
        return sum(
            len(method.activities)
            for package in self.packages
            for method in package.methods
        )


@dataclass(frozen=True, slots=True)
class CandidateEntry:
    package_id: str
    method_id: str
    activity_id: str
    mode_id: str
    start: int
    finish: int
    resources: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CandidateResult:
    scenario_id: str
    methods: tuple[tuple[str, str], ...]
    entries: tuple[CandidateEntry, ...]
    objective_finish: int
    solver_status: str
    solve_ms: float

    @property
    def methods_by_package(self) -> dict[str, str]:
        return dict(self.methods)

    @property
    def by_id(self) -> dict[str, CandidateEntry]:
        return {entry.activity_id: entry for entry in self.entries}


@dataclass(frozen=True, slots=True)
class ScenarioResult:
    scenario: Scenario
    oracle_methods: tuple[tuple[str, str], ...]
    oracle_schedule: ScheduleResult
    feasible_fixed_networks: int
    candidate: CandidateResult

    @property
    def matches_oracle(self) -> bool:
        return self.candidate.objective_finish == self.oracle_schedule.objective_finish


@dataclass(frozen=True, slots=True)
class ExperimentResult:
    case: ExperimentCase
    scenarios: tuple[ScenarioResult, ...]
    candidate_activity_facts: int
    enumerated_activity_facts: int
    candidate_relationship_facts: int
    enumerated_relationship_facts: int
    method_reselections: int
    falsified: bool

    @property
    def by_scenario(self) -> dict[str, ScenarioResult]:
        return {item.scenario.id: item for item in self.scenarios}


def _req(*resources: str) -> tuple[ResourceRequirement, ...]:
    return tuple(ResourceRequirement(resource) for resource in resources)


def _mode(duration: int, *resources: str, mode_id: str = "FIXED") -> tuple[ExecutionMode, ...]:
    return (ExecutionMode(mode_id, duration, _req(*resources)),)


def _qa(duration: int) -> tuple[ExecutionMode, ...]:
    return (
        ExecutionMode("QA-A", duration, _req("QA-A"), "Qualified inspector A"),
        ExecutionMode("QA-B", duration, _req("QA-B"), "Qualified inspector B"),
    )


def _a(
    activity_id: str,
    name: str,
    duration: int,
    *resources: str,
    pred: tuple[str, ...] = (),
    latest: int | None = None,
    groups: tuple[str, ...] = (),
    milestone: bool = False,
) -> ActivitySpec:
    return ActivitySpec(
        activity_id,
        name,
        _mode(
            duration,
            *resources,
            mode_id="MILESTONE" if milestone else "FIXED",
        ),
        pred,
        latest,
        groups,
        "milestone" if milestone else "task",
    )


def build_case() -> ExperimentCase:
    """Six work packages, three binary method choices and 33 possible activities."""

    packages = (
        PackageSpec(
            "WP-A",
            "Establish isolation",
            (
                MethodSpec(
                    "ISOLATE",
                    "Standard isolation",
                    (
                        _a("A1", "Permit and isolation release", 1),
                        _a("A2", "Set isolation", 1, "MECH", pred=("A1",)),
                        ActivitySpec("A3", "Verify isolation", _qa(1), ("A2",)),
                        _a("A4", "Release vessel workface", 1, pred=("A3",)),
                    ),
                    "A4",
                ),
            ),
        ),
        PackageSpec(
            "WP-B",
            "Gain vessel access",
            (
                MethodSpec(
                    "SCAFFOLD",
                    "Scaffold access",
                    (
                        _a("B1-1", "Mobilise scaffold crew", 1, "SCAFF"),
                        _a("B1-2", "Erect scaffold", 3, "SCAFF", pred=("B1-1",)),
                        ActivitySpec("B1-3", "Inspect scaffold", _qa(1), ("B1-2",)),
                        _a("B1-4", "Open vessel access", 1, "MECH", pred=("B1-3",)),
                    ),
                    "B1-4",
                ),
                MethodSpec(
                    "ROPE",
                    "Rope-access entry",
                    (
                        _a("B2-1", "Mobilise rope-access team", 2, "ROPE"),
                        _a("B2-2", "Establish rope-access anchors", 2, "ROPE", pred=("B2-1",)),
                        _a("B2-3", "Open vessel access by rope", 3, "ROPE", "MECH", pred=("B2-2",)),
                    ),
                    "B2-3",
                ),
            ),
            ("WP-A",),
        ),
        PackageSpec(
            "WP-C",
            "Remove component",
            (
                MethodSpec(
                    "CRANE",
                    "Full-component crane lift",
                    (
                        _a("C1-1", "Rig component", 1, "MECH"),
                        _a("C1-2", "Set crane for lift", 1, "CRANE", "MECH", pred=("C1-1",)),
                        _a("C1-3", "Full-component lift", 2, "CRANE", pred=("C1-2",)),
                        _a("C1-4", "Clear removed component", 1, "MECH", pred=("C1-3",)),
                    ),
                    "C1-4",
                ),
                MethodSpec(
                    "SEGMENTED",
                    "Segmented removal",
                    (
                        _a("C2-1", "Prepare segmented removal", 1, "MECH"),
                        _a(
                            "C2-2",
                            "Cut east segment",
                            3,
                            "MECH",
                            pred=("C2-1",),
                            groups=("WF-CUT",),
                        ),
                        _a(
                            "C2-3",
                            "Cut west segment",
                            3,
                            "MECH",
                            pred=("C2-1",),
                            groups=("WF-CUT",),
                        ),
                        _a(
                            "C2-4",
                            "Remove segmented component",
                            2,
                            "MECH",
                            pred=("C2-2", "C2-3"),
                        ),
                    ),
                    "C2-4",
                ),
            ),
            ("WP-B",),
        ),
        PackageSpec(
            "WP-D",
            "Repair component",
            (
                MethodSpec(
                    "NORMAL",
                    "Normal repair",
                    (
                        ActivitySpec("D1-1", "Inspect damage", _qa(1)),
                        _a("D1-2", "Normal mechanical repair", 8, "MECH", pred=("D1-1",)),
                        ActivitySpec("D1-3", "Verify repair", _qa(1), ("D1-2",)),
                    ),
                    "D1-3",
                ),
                MethodSpec(
                    "SPECIALIST",
                    "Specialist repair",
                    (
                        _a("D2-1", "Mobilise specialist", 2, "SPEC"),
                        _a(
                            "D2-2",
                            "Specialist-assisted repair",
                            4,
                            "MECH",
                            "SPEC",
                            pred=("D2-1",),
                        ),
                        ActivitySpec("D2-3", "Verify specialist repair", _qa(1), ("D2-2",)),
                    ),
                    "D2-3",
                ),
            ),
            ("WP-C",),
        ),
        PackageSpec(
            "WP-E",
            "Reinstall",
            (
                MethodSpec(
                    "REINSTALL",
                    "Standard reinstall",
                    (
                        _a("E1", "Prepare reinstall", 1, "MECH"),
                        _a("E2", "Reinstall component", 3, "MECH", "CRANE", pred=("E1",)),
                        _a("E3", "Align component", 2, "MECH", pred=("E2",)),
                        _a("E4", "Final torque", 1, "MECH", pred=("E3",)),
                    ),
                    "E4",
                ),
            ),
            ("WP-D",),
        ),
        PackageSpec(
            "WP-F",
            "Test and hand over",
            (
                MethodSpec(
                    "HANDOVER",
                    "Test and handover",
                    (
                        ActivitySpec("F1", "Final inspection", _qa(2)),
                        _a("F2", "Pressure test", 2, pred=("F1",)),
                        _a("F3", "De-isolate", 1, "MECH", pred=("F2",)),
                        _a(
                            "F4",
                            "Stage handoff",
                            0,
                            pred=("F3",),
                            latest=42,
                            milestone=True,
                        ),
                    ),
                    "F4",
                ),
            ),
            ("WP-E",),
        ),
    )

    scenarios = (
        Scenario(
            "A",
            "Normal resource availability",
            not_before=(("D2-1", 25),),
            reason="Baseline resource and permit conditions.",
        ),
        Scenario(
            "B",
            "Crane unavailable in the critical removal window",
            not_before=(("D2-1", 25),),
            outages=(Outage("CRANE", 10, 18, "Crane C04 unavailable"),),
            reason="Crane C04 is unavailable from H10 to H18.",
        ),
        Scenario(
            "C",
            "Specialist available earlier and scaffold permit narrows",
            not_before=(("D2-1", 10),),
            latest_finish=(("B1-4", 9),),
            reason=(
                "The specialist can mobilise from H10, but the scaffold method "
                "must have access open by H09."
            ),
        ),
    )

    return ExperimentCase(
        resources=(
            Resource("MECH", "Mechanical crew", 2),
            Resource("CRANE", "Crane C04", 1),
            Resource("SCAFF", "Scaffold crew", 1),
            Resource("ROPE", "Rope-access team", 1),
            Resource("SPEC", "Specialist", 1),
            Resource("QA-A", "Qualified inspector A", 1),
            Resource("QA-B", "Qualified inspector B", 1),
        ),
        packages=packages,
        scenarios=scenarios,
    )


def _method_choices(case: ExperimentCase) -> tuple[tuple[tuple[str, str], ...], ...]:
    return tuple(
        tuple((package.id, method_id) for package, method_id in zip(case.packages, chosen))
        for chosen in product(
            *(tuple(method.id for method in package.methods) for package in case.packages)
        )
    )


def _method(package: PackageSpec, method_id: str) -> MethodSpec:
    return next(method for method in package.methods if method.id == method_id)


def _latest(base: int | None, override: int | None) -> int | None:
    if base is None:
        return override
    if override is None:
        return base
    return min(base, override)


def materialize_fixed_project(
    case: ExperimentCase,
    scenario: Scenario,
    choices: tuple[tuple[str, str], ...],
) -> Project:
    """Build one of the eight conventional activity networks."""

    selected = dict(choices)
    completion = {
        package.id: _method(package, selected[package.id]).completion_id
        for package in case.packages
    }
    not_before = dict(scenario.not_before)
    latest_finish = dict(scenario.latest_finish)
    activities: list[Activity] = []

    for package in case.packages:
        method = _method(package, selected[package.id])
        local_ids = {activity.id for activity in method.activities}
        package_predecessors = tuple(completion[item] for item in package.predecessors)
        for spec in method.activities:
            predecessors = spec.predecessors
            if not (set(predecessors) & local_ids):
                predecessors = tuple(dict.fromkeys(predecessors + package_predecessors))
            activities.append(
                Activity(
                    spec.id,
                    spec.name,
                    spec.modes,
                    predecessors,
                    not_before.get(spec.id, 0),
                    _latest(spec.latest_finish, latest_finish.get(spec.id)),
                    spec.exclusion_groups,
                    kind=spec.kind,
                )
            )

    resources = {resource.id: resource for resource in case.resources}
    for index, outage in enumerate(scenario.outages, 1):
        resource = resources[outage.resource_id]
        activities.append(
            Activity(
                f"OUTAGE-{scenario.id}-{index}",
                outage.reason,
                (
                    ExecutionMode(
                        "OUTAGE",
                        outage.finish - outage.start,
                        (ResourceRequirement(outage.resource_id, resource.capacity),),
                    ),
                ),
                frozen_start=outage.start,
            )
        )

    return Project(
        id=f"fixed-{scenario.id}",
        name=f"Fixed network oracle / scenario {scenario.id}",
        activities=tuple(activities),
        resources=case.resources,
        objective_activity_id="F4",
    )


def fixed_network_oracle(
    case: ExperimentCase,
    scenario: Scenario,
) -> tuple[tuple[tuple[str, str], ...], ScheduleResult, int]:
    feasible: list[tuple[tuple[tuple[str, str], ...], ScheduleResult]] = []
    for choices in _method_choices(case):
        try:
            result = schedule_project(materialize_fixed_project(case, scenario, choices))
        except SchedulingError:
            continue
        feasible.append((choices, result))
    if not feasible:
        raise SchedulingError(f"scenario {scenario.id}: no fixed network is feasible")
    best = min(
        feasible,
        key=lambda item: (
            item[1].objective_finish,
            tuple(method_id for _, method_id in item[0]),
        ),
    )
    return best[0], best[1], len(feasible)


def _horizon(case: ExperimentCase, scenario: Scenario) -> int:
    anchors = (
        [0]
        + [value for _, value in scenario.not_before]
        + [value for _, value in scenario.latest_finish]
        + [outage.finish for outage in scenario.outages]
    )
    longest = sum(
        max(
            sum(max(mode.duration for mode in activity.modes) for activity in method.activities)
            for method in package.methods
        )
        for package in case.packages
    )
    return max(anchors) + longest + 50


def solve_candidate(case: ExperimentCase, scenario: Scenario) -> CandidateResult:
    """Select work-package methods, activity modes and timing in one CP-SAT model."""

    horizon = _horizon(case, scenario)
    model = cp_model.CpModel()
    not_before = dict(scenario.not_before)
    latest_finish = dict(scenario.latest_finish)

    selected_method: dict[tuple[str, str], cp_model.BoolVar] = {}
    selected_mode: dict[tuple[str, str, str, str], cp_model.BoolVar] = {}
    starts: dict[tuple[str, str, str], cp_model.IntVar] = {}
    ends: dict[tuple[str, str, str], cp_model.IntVar] = {}
    active_starts: list[cp_model.IntVar] = []
    intervals: dict[tuple[str, str, str, str], cp_model.IntervalVar] = {}
    package_finish: dict[str, cp_model.IntVar] = {}

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
                    intervals[(package.id, method.id, activity.id, mode.id)] = (
                        model.new_optional_interval_var(
                            start,
                            mode.duration,
                            end,
                            literal,
                            f"interval_{package.id}_{method.id}_{activity.id}_{mode.id}",
                        )
                    )
                    mode_literals.append(literal)
                model.add(sum(mode_literals) == method_literal)

                limit = _latest(activity.latest_finish, latest_finish.get(activity.id))
                if limit is not None:
                    model.add(end <= limit).only_enforce_if(method_literal)

                for predecessor in activity.predecessors:
                    if predecessor not in local_ids:
                        raise SchedulingError(
                            f"{package.id}/{method.id}: predecessor {predecessor} "
                            "must be inside the method for this bounded experiment"
                        )
                    model.add(
                        start >= ends[(package.id, method.id, predecessor)]
                    ).only_enforce_if(method_literal)

            model.add(
                package_finish[package.id]
                == ends[(package.id, method.id, method.completion_id)]
            ).only_enforce_if(method_literal)

            for root in method.roots:
                for predecessor_package in package.predecessors:
                    model.add(
                        starts[(package.id, method.id, root)]
                        >= package_finish[predecessor_package]
                    ).only_enforce_if(method_literal)

        model.add_exactly_one(method_literals)

    resource_intervals = {resource.id: [] for resource in case.resources}
    resource_demands = {resource.id: [] for resource in case.resources}
    resources = {resource.id: resource for resource in case.resources}

    for package in case.packages:
        for method in package.methods:
            for activity in method.activities:
                for mode in activity.modes:
                    interval = intervals[(package.id, method.id, activity.id, mode.id)]
                    for requirement in mode.requirements:
                        resource_intervals[requirement.resource_id].append(interval)
                        resource_demands[requirement.resource_id].append(requirement.demand)

    for index, outage in enumerate(scenario.outages, 1):
        start = model.new_int_var(outage.start, outage.start, f"outage_start_{index}")
        end = model.new_int_var(outage.finish, outage.finish, f"outage_end_{index}")
        interval = model.new_interval_var(
            start,
            outage.finish - outage.start,
            end,
            f"outage_{index}",
        )
        resource_intervals[outage.resource_id].append(interval)
        resource_demands[outage.resource_id].append(
            resources[outage.resource_id].capacity
        )

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
                for group in activity.exclusion_groups:
                    groups.setdefault(group, []).extend(
                        intervals[(package.id, method.id, activity.id, mode.id)]
                        for mode in activity.modes
                    )
    for group_intervals in groups.values():
        model.add_no_overlap(group_intervals)

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
    tie_bound = case.possible_activity_count * horizon + 1000
    model.minimize(
        package_finish["WP-F"] * (tie_bound + 1)
        + sum(active_starts)
        + method_tie
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
            f"scenario {scenario.id}: candidate is {solver.status_name(status)}"
        )

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
                if solver.value(
                    selected_mode[(package.id, method.id, activity.id, mode.id)]
                )
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
                    tuple(requirement.resource_id for requirement in mode.requirements),
                )
            )

    return CandidateResult(
        scenario.id,
        tuple(methods),
        tuple(sorted(entries, key=lambda item: (item.start, item.finish, item.activity_id))),
        solver.value(package_finish["WP-F"]),
        solver.status_name(status),
        solve_ms,
    )


def _relationship_facts(case: ExperimentCase) -> int:
    internal = sum(
        len(activity.predecessors)
        for package in case.packages
        for method in package.methods
        for activity in method.activities
    )
    package_links = sum(
        len(package.predecessors) * sum(len(method.roots) for method in package.methods)
        for package in case.packages
    )
    return internal + package_links


def _enumerated_facts(case: ExperimentCase) -> tuple[int, int]:
    scenario = case.scenarios[0]
    activities = 0
    relationships = 0
    for choices in _method_choices(case):
        project = materialize_fixed_project(case, scenario, choices)
        activities += len(project.activities)
        relationships += sum(len(activity.predecessors) for activity in project.activities)
    return activities, relationships


def _changes(a: CandidateResult, b: CandidateResult) -> tuple[tuple[str, str, str], ...]:
    before = a.methods_by_package
    after = b.methods_by_package
    return tuple(
        (package, before[package], after[package])
        for package in before
        if before[package] != after[package]
    )


def decision_explanations(
    baseline: CandidateResult,
    current: CandidateResult,
    scenario: Scenario,
) -> tuple[str, ...]:
    lines: list[str] = []
    for package, old, new in _changes(baseline, current):
        if package == "WP-C" and scenario.outages:
            outage = scenario.outages[0]
            lines.append(
                f"{package}: {old} -> {new}; {outage.resource_id} unavailable "
                f"H{outage.start}-H{outage.finish}, so the no-crane method avoids waiting."
            )
        elif package == "WP-B" and dict(scenario.latest_finish).get("B1-4") is not None:
            lines.append(
                f"{package}: {old} -> {new}; scaffold access cannot meet the "
                f"H{dict(scenario.latest_finish)['B1-4']} permit limit."
            )
        elif package == "WP-D":
            lines.append(
                f"{package}: {old} -> {new}; specialist availability from "
                f"H{dict(scenario.not_before)['D2-1']} makes the specialist method faster."
            )
    return tuple(lines)


def run_experiment() -> ExperimentResult:
    case = build_case()
    scenarios: list[ScenarioResult] = []
    for scenario in case.scenarios:
        oracle_methods, oracle_schedule, feasible = fixed_network_oracle(case, scenario)
        candidate = solve_candidate(case, scenario)
        scenarios.append(
            ScenarioResult(
                scenario,
                oracle_methods,
                oracle_schedule,
                feasible,
                candidate,
            )
        )

    baseline = scenarios[0].candidate
    reselections = sum(
        len(_changes(baseline, scenario.candidate))
        for scenario in scenarios[1:]
    )
    enumerated_activities, enumerated_relationships = _enumerated_facts(case)
    candidate_relationships = _relationship_facts(case)
    compact = (
        case.possible_activity_count < enumerated_activities
        and candidate_relationships < enumerated_relationships
    )
    falsified = (
        any(not scenario.matches_oracle for scenario in scenarios)
        or reselections == 0
        or not compact
    )
    return ExperimentResult(
        case,
        tuple(scenarios),
        case.possible_activity_count,
        enumerated_activities,
        candidate_relationships,
        enumerated_relationships,
        reselections,
        falsified,
    )


def _methods(methods: tuple[tuple[str, str], ...]) -> str:
    return ", ".join(
        f"{package}={method}"
        for package, method in methods
        if package in {"WP-B", "WP-C", "WP-D"}
    )


def render(result: ExperimentResult) -> str:
    lines = [
        "WORK-METHOD-EXECUTION FALSIFICATION EXPERIMENT",
        (
            f"6 work packages; {result.case.possible_activity_count} possible activities; "
            f"{result.case.fixed_network_count} authorised fixed-network structures."
        ),
        (
            "Control: exhaustively materialise and solve every fixed activity network. "
            "Candidate: hold all authorised methods once and select method + mode + timing jointly."
        ),
    ]
    baseline = result.scenarios[0].candidate

    for item in result.scenarios:
        lines.extend(
            (
                "",
                f"SCENARIO {item.scenario.id}: {item.scenario.name}",
                f"Context: {item.scenario.reason}",
                (
                    f"Control oracle: H{item.oracle_schedule.objective_finish}; "
                    f"{_methods(item.oracle_methods)}; "
                    f"{item.feasible_fixed_networks}/{result.case.fixed_network_count} networks feasible"
                ),
                (
                    f"Candidate: H{item.candidate.objective_finish}; "
                    f"{_methods(item.candidate.methods)}; "
                    f"{item.candidate.solver_status}; {item.candidate.solve_ms:.2f} ms"
                ),
                f"Matches exhaustive oracle: {'YES' if item.matches_oracle else 'NO'}",
            )
        )
        if item.scenario.id != "A":
            before = set(baseline.by_id)
            after = set(item.candidate.by_id)
            lines.append(
                f"Topology change vs A: -{len(before - after)} activities, "
                f"+{len(after - before)} activities"
            )
            for explanation in decision_explanations(
                baseline,
                item.candidate,
                item.scenario,
            ):
                lines.append(f"Decision: {explanation}")

    lines.extend(
        (
            "",
            "MODELLING COMPARISON",
            (
                f"Candidate: {result.candidate_activity_facts} activity facts; "
                f"{result.candidate_relationship_facts} relationship facts"
            ),
            (
                f"Eight fixed networks: {result.enumerated_activity_facts} activity facts; "
                f"{result.enumerated_relationship_facts} relationship facts"
            ),
            f"Method reselections under changed conditions: {result.method_reselections}",
            "",
            (
                "FALSIFICATION RESULT: FALSIFIED"
                if result.falsified
                else (
                    "FALSIFICATION RESULT: NOT FALSIFIED — the bounded Work-Method-Execution "
                    "model matched the exhaustive fixed-network oracle in every scenario, "
                    "reselected authorised structure without topology edits, and represented "
                    "the alternative space more compactly."
                )
            ),
            (
                "Interpretation: this supports the bounded planning hypothesis only; it does "
                "not justify unrestricted goal/state planning or make CP-SAT the final engine."
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
