"""Accepted-history composition for the bounded Work-Method/productive-time path.

This module compiles already-validated execution history into hard planning
constraints, then delegates the remaining structural/mode/resource/timing choice
to the existing joint Work-Method/productive-time scheduler. It is deliberately
bounded and does not replace the accepted-progress v2 workspace.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

from deterministic_scheduling_core.project.model import WorkPackage
from deterministic_scheduling_core.project.planning_workspace import (
    STATUS_SCHEMA,
    current_status_records,
    digest,
    state_hash,
    validate as validate_workspace,
    validate_accepted_history,
)
from deterministic_scheduling_core.project.work_method_time import (
    WorkMethodTimeProject,
    input_hash,
    materialise,
    membership,
)
from .work_method_time import (
    WorkMethodTimeResult,
    schedule_work_method_time,
    validate_plan as validate_future_plan,
    validate_problem,
)

PLAN_SCHEMA = "pm-native-accepted-work-method-time-plan/0"
POLICY = "accepted-history-hard-then-work-method-time/0"


@dataclass(frozen=True)
class AcceptedWorkMethodTimeResult:
    plan: dict
    metrics: dict


def _plan_hash(plan: dict) -> str:
    return digest({key: value for key, value in plan.items() if key != "plan_hash"})


def _fixed_methods(problem: WorkMethodTimeProject, reference_plan: dict, states: dict) -> dict[str, str]:
    members = membership(problem)
    fixed: dict[str, str] = {}
    for activity_id, record in states.items():
        if record["execution_state"] == "NOT_STARTED" or activity_id not in members:
            continue
        package_id, method_id = members[activity_id]
        if reference_plan["selected_methods"].get(package_id) != method_id:
            raise ValueError(
                f"{activity_id}: accepted history does not belong to the reference method"
            )
        prior = fixed.get(package_id)
        if prior is not None and prior != method_id:
            raise ValueError(f"{package_id}: accepted history spans competing methods")
        fixed[package_id] = method_id
    return fixed


def validate_input(
    problem: WorkMethodTimeProject,
    reference_plan: dict,
    status_workspace: dict,
) -> tuple[dict, dict[str, str]]:
    """Validate the bounded seam without scheduling or rewriting either input."""
    validate_problem(problem)
    validate_future_plan(problem, reference_plan)
    if status_workspace.get("schema") != STATUS_SCHEMA:
        raise ValueError("accepted-history composition requires a version-two status workspace")
    validate_workspace(status_workspace)

    expected = materialise(problem, reference_plan["selected_methods"])
    if status_workspace["project"] != expected["project"]:
        raise ValueError("status workspace must be the reference plan's selected native structure")
    if status_workspace["reports"] != expected["reports"]:
        raise ValueError("status workspace and Work-Method input must share the same report state")

    states = validate_accepted_history(status_workspace, require_complete=True)
    active_ids = {activity["id"] for activity in expected["project"]["activities"]}
    if set(states) != active_ids:
        raise ValueError("status workspace must cover exactly the reference selected structure")

    if states[problem.project["objective_activity_id"]]["execution_state"] == "COMPLETED":
        raise ValueError("the controlling activity is already completed; no future recovery remains")

    for activity_id, record in states.items():
        if record["execution_state"] != "IN_PROGRESS":
            continue
        if record["remaining_processing_ticks"] <= 0:
            raise ValueError("this bounded composition requires positive remainder for in-progress work")
        mode = record["execution_context"]["mode"]
        if mode.get("continuity", "SUSPENDABLE_AT_AVAILABILITY_GAPS") == "CONTINUOUS":
            raise ValueError("continuous in-progress structural composition is not in this bounded slice")

    fixed = _fixed_methods(problem, reference_plan, states)
    return states, fixed


def _compile_future_problem(
    problem: WorkMethodTimeProject,
    reference_plan: dict,
    status_workspace: dict,
    *,
    fixed_methods_override: dict[str, str] | None = None,
) -> tuple[WorkMethodTimeProject, dict[str, str], dict]:
    """Project accepted history into hard future-planning constraints.

    Completed activities remain only as zero-work timing anchors at their accepted
    finish. In-progress activities retain their begun mode and named resources,
    but their future processing comes from the independently accepted remaining
    estimate. Untouched packages retain every authorised structural alternative.
    """
    states, derived_fixed = validate_input(problem, reference_plan, status_workspace)
    fixed = derived_fixed if fixed_methods_override is None else dict(fixed_methods_override)

    packages: list[WorkPackage] = []
    excluded: set[str] = set()
    for package in problem.work_packages:
        if package.id in fixed:
            method = package.method_by_id.get(fixed[package.id])
            if method is None:
                raise ValueError(f"{package.id}: fixed history names an unauthorised method")
            packages.append(WorkPackage(package.id, package.name, (method,), package.predecessors))
            for other in package.methods:
                if other.id != method.id:
                    excluded.update(other.activity_ids)
        else:
            packages.append(package)

    project = deepcopy(problem.project)
    project["activities"] = [
        deepcopy(activity)
        for activity in project["activities"]
        if activity["id"] not in excluded
    ]
    status_point = status_workspace["execution"]["status_point"]

    for activity in project["activities"]:
        activity_id = activity["id"]
        record = states.get(activity_id)
        if record and record["execution_state"] == "COMPLETED":
            historical_mode = deepcopy(record["execution_context"]["mode"])
            historical_mode["processing_ticks"] = 0
            historical_mode["requirements"] = []
            if "resource_groups" in project:
                historical_mode["group_requirements"] = []
            else:
                historical_mode.pop("group_requirements", None)
            activity["modes"] = [historical_mode]
            envelope = (
                record["actual_finish"]
                if record["actual_finish"] is not None
                else record["actual_start"]
            )
            if envelope is None:
                raise ValueError(f"{activity_id}: completed history has no timing envelope")
            activity["not_before"] = envelope
            continue

        if record and record["execution_state"] == "IN_PROGRESS":
            matches = [mode for mode in activity["modes"] if mode["id"] == record["mode_id"]]
            if len(matches) != 1:
                raise ValueError(f"{activity_id}: begun mode is no longer uniquely authorised")
            mode = deepcopy(matches[0])
            mode["processing_ticks"] = record["remaining_processing_ticks"]
            assignments = dict(record["named_assignments"])
            expected_slots = {requirement["id"] for requirement in mode.get("requirements", [])}
            if set(assignments) != expected_slots:
                raise ValueError(f"{activity_id}: begun named assignments no longer match its mode")
            for requirement in mode.get("requirements", []):
                requirement["eligible_resource_ids"] = [assignments[requirement["id"]]]
            activity["modes"] = [mode]

        activity["not_before"] = max(activity.get("not_before", 0), status_point)

    compiled = WorkMethodTimeProject(project, tuple(packages), problem.reports)
    validate_problem(compiled)
    return compiled, fixed, states


def _actual_group_demands(record: dict | None) -> list[list]:
    if not record or not record.get("execution_context"):
        return []
    return [
        [demand["group_id"], demand["demand"]]
        for demand in record["execution_context"]["mode"].get("group_requirements", [])
    ]


def _original_mode(problem: WorkMethodTimeProject, activity_id: str, mode_id: str) -> dict:
    activity = next(activity for activity in problem.project["activities"] if activity["id"] == activity_id)
    return next(mode for mode in activity["modes"] if mode["id"] == mode_id)


def _compose_entry(
    problem: WorkMethodTimeProject,
    states: dict,
    future_entry: dict,
) -> dict:
    activity_id = future_entry["activity_id"]
    record = states.get(activity_id)
    execution_state = record["execution_state"] if record else "NOT_STARTED"
    selected_mode = future_entry["mode_id"]

    actual_start = record["actual_start"] if record else None
    actual_finish = record["actual_finish"] if record else None
    actual_periods = deepcopy(record["actual_periods"]) if record else []
    actual_assignments = deepcopy(record["named_assignments"]) if record else []
    actual_group_demands = _actual_group_demands(record)

    if execution_state == "COMPLETED":
        envelope = actual_finish if actual_finish is not None else actual_start
        return {
            "activity_id": activity_id,
            "work_package_id": future_entry["work_package_id"],
            "method_id": future_entry["method_id"],
            "mode_id": selected_mode,
            "execution_state": execution_state,
            "status_update_id": record["id"],
            "start": envelope,
            "finish": envelope,
            "periods": [],
            "assignments": [],
            "group_demands": [],
            "actual_start": actual_start,
            "actual_finish": actual_finish,
            "actual_periods": actual_periods,
            "actual_assignments": actual_assignments,
            "actual_group_demands": actual_group_demands,
            "forecast_start": None,
            "forecast_finish": None,
            "forecast_periods": [],
            "remaining_processing_ticks": 0,
        }

    if execution_state == "IN_PROGRESS":
        remaining = record["remaining_processing_ticks"]
    else:
        remaining = _original_mode(problem, activity_id, selected_mode)["processing_ticks"]

    return {
        "activity_id": activity_id,
        "work_package_id": future_entry["work_package_id"],
        "method_id": future_entry["method_id"],
        "mode_id": selected_mode,
        "execution_state": execution_state,
        "status_update_id": record["id"] if record else None,
        "start": future_entry["start"],
        "finish": future_entry["finish"],
        "periods": deepcopy(future_entry["periods"]),
        "assignments": deepcopy(future_entry["assignments"]),
        "group_demands": deepcopy(future_entry["group_demands"]),
        "actual_start": actual_start,
        "actual_finish": actual_finish,
        "actual_periods": actual_periods,
        "actual_assignments": actual_assignments,
        "actual_group_demands": actual_group_demands,
        "forecast_start": future_entry["start"],
        "forecast_finish": future_entry["finish"],
        "forecast_periods": deepcopy(future_entry["periods"]),
        "remaining_processing_ticks": remaining,
    }


def validate_plan(
    problem: WorkMethodTimeProject,
    reference_plan: dict,
    status_workspace: dict,
    plan: dict,
) -> str:
    """Validate stored history + future output without re-solving."""
    states, derived_fixed = validate_input(problem, reference_plan, status_workspace)
    if not isinstance(plan, dict) or set(plan) != {
        "schema", "source_input_hash", "status_state_hash", "reference_plan_hash",
        "status_point", "policy", "fixed_methods", "selected_methods",
        "selected_modes", "entries", "objective", "physical_status",
        "history_status", "future_plan", "solver", "plan_hash",
    } or plan["schema"] != PLAN_SCHEMA:
        raise ValueError("unsupported accepted Work-Method plan")
    if plan["plan_hash"] != _plan_hash(plan):
        raise ValueError("accepted Work-Method plan hash mismatch")
    if plan["source_input_hash"] != input_hash(problem):
        raise ValueError("accepted Work-Method plan belongs to different structural inputs")
    if plan["status_state_hash"] != state_hash(status_workspace):
        raise ValueError("accepted Work-Method plan belongs to different accepted history")
    if plan["reference_plan_hash"] != reference_plan["plan_hash"]:
        raise ValueError("accepted Work-Method plan belongs to a different reference plan")
    if plan["status_point"] != status_workspace["execution"]["status_point"] or plan["policy"] != POLICY:
        raise ValueError("accepted Work-Method status point or policy mismatch")
    if plan["fixed_methods"] != derived_fixed:
        raise ValueError("accepted history method locks were altered")

    compiled, fixed, _ = _compile_future_problem(
        problem, reference_plan, status_workspace, fixed_methods_override=derived_fixed
    )
    validate_future_plan(compiled, plan["future_plan"])
    future = plan["future_plan"]
    for key in ("selected_methods", "selected_modes", "objective", "physical_status", "solver"):
        if plan[key] != future[key]:
            raise ValueError(f"accepted Work-Method {key} disagrees with the future proof")
    for package_id, method_id in fixed.items():
        if plan["selected_methods"].get(package_id) != method_id:
            raise ValueError(f"{package_id}: accepted begun method was changed")

    future_entries = {entry["activity_id"]: entry for entry in future["entries"]}
    entries = {entry.get("activity_id"): entry for entry in plan["entries"]}
    if len(entries) != len(plan["entries"]) or set(entries) != set(future_entries):
        raise ValueError("accepted Work-Method entries must cover exactly the selected future structure")

    executed = {
        activity_id
        for activity_id, record in states.items()
        if record["execution_state"] != "NOT_STARTED"
    }
    if not executed <= set(entries):
        raise ValueError("selected structure discarded accepted execution history")

    for activity_id, future_entry in future_entries.items():
        entry = entries[activity_id]
        expected = _compose_entry(problem, states, future_entry)
        if entry != expected:
            raise ValueError(f"{activity_id}: accepted/history forecast composition was altered")
        record = states.get(activity_id)
        if record and record["execution_state"] == "COMPLETED":
            envelope = (
                record["actual_finish"]
                if record["actual_finish"] is not None
                else record["actual_start"]
            )
            if (
                future_entry["start"] != envelope
                or future_entry["finish"] != envelope
                or future_entry["periods"] != []
            ):
                raise ValueError(f"{activity_id}: completed history anchor moved")
        if record and record["execution_state"] == "IN_PROGRESS":
            if future_entry["mode_id"] != record["mode_id"]:
                raise ValueError(f"{activity_id}: begun mode was changed")
            if dict(future_entry["assignments"]) != dict(record["named_assignments"]):
                raise ValueError(f"{activity_id}: begun named resource was changed")
            if future_entry["start"] < status_workspace["execution"]["status_point"]:
                raise ValueError(f"{activity_id}: future remainder starts before the status point")
            if entry["group_demands"] != entry["actual_group_demands"]:
                raise ValueError(f"{activity_id}: begun group quantity changed across the boundary")

    if plan["history_status"] != "INDEPENDENTLY_VALIDATED":
        raise ValueError("accepted history validation status is missing")
    return "PROVEN_FEASIBLE"


def schedule_accepted_work_method_time(
    problem: WorkMethodTimeProject,
    reference_plan: dict,
    status_workspace: dict,
) -> AcceptedWorkMethodTimeResult:
    """Calculate a structural recovery without mutating accepted history."""
    source_hash = input_hash(problem)
    accepted_hash = state_hash(status_workspace)
    compiled, fixed, states = _compile_future_problem(problem, reference_plan, status_workspace)
    future: WorkMethodTimeResult = schedule_work_method_time(compiled)

    plan = {
        "schema": PLAN_SCHEMA,
        "source_input_hash": source_hash,
        "status_state_hash": accepted_hash,
        "reference_plan_hash": reference_plan["plan_hash"],
        "status_point": status_workspace["execution"]["status_point"],
        "policy": POLICY,
        "fixed_methods": fixed,
        "selected_methods": deepcopy(future.plan["selected_methods"]),
        "selected_modes": deepcopy(future.plan["selected_modes"]),
        "entries": [
            _compose_entry(problem, states, entry)
            for entry in future.plan["entries"]
        ],
        "objective": deepcopy(future.plan["objective"]),
        "physical_status": future.plan["physical_status"],
        "history_status": "INDEPENDENTLY_VALIDATED",
        "future_plan": deepcopy(future.plan),
        "solver": deepcopy(future.plan["solver"]),
    }
    plan["plan_hash"] = _plan_hash(plan)
    validate_plan(problem, reference_plan, status_workspace, plan)

    if input_hash(problem) != source_hash or state_hash(status_workspace) != accepted_hash:
        raise AssertionError("accepted-history composition mutated its inputs")

    metrics = {
        **future.metrics,
        "fixed_method_count": len(fixed),
        "accepted_history_count": sum(
            record["execution_state"] != "NOT_STARTED" for record in states.values()
        ),
    }
    return AcceptedWorkMethodTimeResult(plan, metrics)
