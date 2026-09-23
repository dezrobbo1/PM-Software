"""Native-model integration of the bounded Work–Method–Execution hypothesis.

This is a convergence experiment, not a new planning theory.  The existing
work_method_experiment remains the exhaustive oracle.  This module translates
that same bounded case into the owning PM-Software Project / WorkPackage /
ExecutionMethod model and calls the normal native scheduler.
"""
from __future__ import annotations

from dataclasses import dataclass

from deterministic_scheduling_core.project import (
    Activity,
    ExecutionMethod,
    ExecutionMode,
    Project,
    ResourceRequirement,
    WorkPackage,
)
from deterministic_scheduling_core.scheduling import ScheduleResult, schedule_project
from deterministic_scheduling_core.work_method_experiment import (
    ExperimentCase,
    Scenario,
    build_case,
    fixed_network_oracle,
)


@dataclass(frozen=True, slots=True)
class ScenarioIntegrationResult:
    scenario_id: str
    oracle_finish: int
    oracle_methods: tuple[tuple[str, str], ...]
    native: ScheduleResult

    @property
    def matches_oracle(self) -> bool:
        return (
            self.native.objective_finish == self.oracle_finish
            and self.native.selected_methods == self.oracle_methods
        )


@dataclass(frozen=True, slots=True)
class IntegrationResult:
    scenarios: tuple[ScenarioIntegrationResult, ...]

    @property
    def falsified(self) -> bool:
        return any(not item.matches_oracle for item in self.scenarios)


def _latest(base: int | None, override: int | None) -> int | None:
    if base is None:
        return override
    if override is None:
        return base
    return min(base, override)


def build_native_structural_project(
    case: ExperimentCase,
    scenario: Scenario,
) -> Project:
    """Represent all authorised structures once in the owning native model."""

    not_before = dict(scenario.not_before)
    latest_finish = dict(scenario.latest_finish)
    activities: list[Activity] = []
    packages: list[WorkPackage] = []

    for package in case.packages:
        methods: list[ExecutionMethod] = []
        for method in package.methods:
            methods.append(
                ExecutionMethod(
                    id=method.id,
                    name=method.name,
                    activity_ids=tuple(spec.id for spec in method.activities),
                    completion_activity_id=method.completion_id,
                )
            )
            for spec in method.activities:
                activities.append(
                    Activity(
                        id=spec.id,
                        name=spec.name,
                        modes=spec.modes,
                        predecessors=spec.predecessors,
                        not_before=not_before.get(spec.id, 0),
                        latest_finish=_latest(
                            spec.latest_finish,
                            latest_finish.get(spec.id),
                        ),
                        exclusion_groups=spec.exclusion_groups,
                        kind=spec.kind,
                    )
                )
        packages.append(
            WorkPackage(
                id=package.id,
                name=package.name,
                methods=tuple(methods),
                predecessors=package.predecessors,
            )
        )

    resources = {resource.id: resource for resource in case.resources}
    for index, outage in enumerate(scenario.outages, 1):
        resource = resources[outage.resource_id]
        activities.append(
            Activity(
                id=f"OUTAGE-{scenario.id}-{index}",
                name=outage.reason,
                modes=(
                    ExecutionMode(
                        "OUTAGE",
                        outage.finish - outage.start,
                        (
                            ResourceRequirement(
                                outage.resource_id,
                                resource.capacity,
                            ),
                        ),
                    ),
                ),
                frozen_start=outage.start,
            )
        )

    return Project(
        id=f"native-work-method-{scenario.id}",
        name=f"Native Work-Method integration / scenario {scenario.id}",
        activities=tuple(activities),
        resources=case.resources,
        objective_activity_id="F4",
        work_packages=tuple(packages),
    )


def run_experiment() -> IntegrationResult:
    case = build_case()
    scenarios: list[ScenarioIntegrationResult] = []
    for scenario in case.scenarios:
        oracle_methods, oracle_schedule, _ = fixed_network_oracle(case, scenario)
        project = build_native_structural_project(case, scenario)
        native = schedule_project(project)
        repeated = schedule_project(project)
        if native.selected_methods != repeated.selected_methods or native.entries != repeated.entries:
            raise AssertionError(f"scenario {scenario.id}: native structural solve is not canonical")
        scenarios.append(
            ScenarioIntegrationResult(
                scenario.id,
                oracle_schedule.objective_finish,
                oracle_methods,
                native,
            )
        )
    return IntegrationResult(tuple(scenarios))


def render(result: IntegrationResult) -> str:
    lines = [
        "NATIVE WORK-METHOD INTEGRATION",
        (
            "Existing exhaustive fixed-network oracle versus the owning "
            "Project/WorkPackage/ExecutionMethod scheduler."
        ),
    ]
    for item in result.scenarios:
        methods = ", ".join(
            f"{package}={method}"
            for package, method in item.native.selected_methods
            if package in {"WP-B", "WP-C", "WP-D"}
        )
        lines.append(
            f"Scenario {item.scenario_id}: oracle H{item.oracle_finish}; "
            f"native H{item.native.objective_finish}; {methods}; "
            f"{'MATCH' if item.matches_oracle else 'MISMATCH'}"
        )
    lines.append(
        "RESULT: "
        + (
            "FALSIFIED"
            if result.falsified
            else (
                "NOT FALSIFIED — the owning native scheduler selected the same "
                "authorised structure and controlling finish as exhaustive "
                "fixed-network enumeration in all three bounded scenarios."
            )
        )
    )
    return "\n".join(lines)


def main() -> None:
    print(render(run_experiment()))


if __name__ == "__main__":
    main()
