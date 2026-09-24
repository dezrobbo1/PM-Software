"""Materially larger falsification of the converged native headless path.

The fixture intentionally reaches the new bounded admission edge:
64 declared activities, 48 active under the baseline structure, 8 Work Packages,
4 flexible structural decisions / 16 authorised structures, productive calendars,
named resources, anonymous pooled capacity, one activity-mode choice, accepted
execution history, structural recovery, promotion and one rolling status advance.

This is evidence, not a production benchmark.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
from time import perf_counter

from itertools import product
from deterministic_scheduling_core.project.model import ExecutionMethod, WorkPackage
from deterministic_scheduling_core.project.planning_workspace import (
    accept_status_update,
    current_status_records,
    enable_status_tracking,
    report_status_update,
    state_hash,
    validate_accepted_history,
)
from deterministic_scheduling_core.project.work_method_time import (
    WorkMethodTimeProject,
    input_hash,
    materialise,
    membership,
    to_document,
)
from deterministic_scheduling_core.scheduling.accepted_work_method_time import (
    _compile_future_problem,
    schedule_accepted_work_method_time,
)
from deterministic_scheduling_core.scheduling.rolling_structural_status import (
    advance_structural_status_cycle,
    calculate_structural_recovery,
    promote_structural_recovery_to_status_cycle,
)
from deterministic_scheduling_core.scheduling.work_method_time import (
    policy_key,
    schedule_work_method_time,
    validate_plan,
)


DECLARED_ACTIVITIES = 64
BASELINE_ACTIVE_ACTIVITIES = 48
PACKAGE_COUNT = 8
FLEXIBLE_PACKAGE_COUNT = 4
AUTHORISED_STRUCTURES = 16


def _slot(slot_id: str, capability: str, resource_id: str) -> dict:
    return {
        "id": slot_id,
        "pool_ids": [capability],
        "eligible_resource_ids": [resource_id],
    }


def _mode(
    mode_id: str,
    work: int,
    requirements: tuple[dict, ...] = (),
    groups: tuple[dict, ...] = (),
) -> dict:
    return {
        "id": mode_id,
        "processing_ticks": work,
        "calendar_id": "SHIFT",
        "continuity": "SUSPENDABLE_AT_AVAILABILITY_GAPS",
        "requirements": [deepcopy(requirement) for requirement in requirements],
        "group_requirements": [deepcopy(group) for group in groups],
    }


def _activity(
    activity_id: str,
    name: str,
    work: int,
    predecessor: str | None,
    *,
    kind: str,
    crane: bool = False,
    multimode: bool = False,
) -> dict:
    requirements: tuple[dict, ...] = ()
    groups: tuple[dict, ...] = ()
    if kind == "M1":
        requirements = (_slot("MECH", "MECH", "M1"),)
    elif kind == "M2":
        requirements = (_slot("MECH", "MECH", "M2"),)
    elif kind == "M3":
        requirements = (_slot("MECH", "MECH", "M3"),)
    elif kind == "QA":
        requirements = (_slot("QA", "QA", "Q1"),)
    elif kind == "RIG":
        groups = ({"group_id": "RIGGING", "demand": 1},)
    if crane:
        requirements = requirements + (_slot("CRANE", "CRANE", "C04"),)

    modes = [_mode("NORMAL", work, requirements, groups)]
    if multimode:
        modes.append(_mode("FAST", max(1, work - 1), requirements, groups))

    activity = {"id": activity_id, "name": name, "modes": modes}
    if predecessor is not None:
        activity["predecessors"] = [predecessor]
    return activity


def _chain(
    package_id: str,
    method_id: str,
    count: int,
    durations: tuple[int, ...],
    *,
    crane_index: int | None,
    multimode_index: int | None = None,
) -> tuple[list[dict], ExecutionMethod]:
    suffix = "A" if method_id in {"FIXED", "CRANE"} else "B"
    activities = []
    predecessor = None
    kinds = ("M1", "RIG", "M2", "QA", "M3", "M1")
    for index in range(1, count + 1):
        activity_id = f"{package_id}{suffix}{index:02d}"
        activities.append(_activity(
            activity_id,
            f"{package_id} {method_id} step {index}",
            durations[index - 1],
            predecessor,
            kind=kinds[(index - 1) % len(kinds)],
            crane=crane_index == index,
            multimode=multimode_index == index,
        ))
        predecessor = activity_id
    return activities, ExecutionMethod(
        method_id,
        f"{package_id} {method_id}",
        tuple(activity["id"] for activity in activities),
        activities[-1]["id"],
    )


def build_problem() -> WorkMethodTimeProject:
    """64 declared / 48 baseline-active activities with exactly 16 structures."""
    activities: list[dict] = []
    packages: list[WorkPackage] = []
    flexible = {2, 4, 6, 7}

    for number in range(1, PACKAGE_COUNT + 1):
        package_id = f"WP{number:02d}"
        predecessors = () if number == 1 else (f"WP{number - 1:02d}",)
        if number in flexible:
            a_activities, method_a = _chain(
                package_id,
                "CRANE",
                6,
                (2, 2, 2, 2, 3, 1),
                crane_index=5,
                multimode_index=3 if number == 4 else None,
            )
            b_activities, method_b = _chain(
                package_id,
                "MANUAL",
                4,
                (4, 4, 4, 4),
                crane_index=None,
            )
            activities.extend(a_activities)
            activities.extend(b_activities)
            packages.append(WorkPackage(
                package_id,
                f"Work package {number}",
                (method_a, method_b),
                predecessors,
            ))
        else:
            fixed_activities, method = _chain(
                package_id,
                "FIXED",
                6,
                (2, 2, 2, 2, 2, 2),
                crane_index=None,
            )
            activities.extend(fixed_activities)
            packages.append(WorkPackage(
                package_id,
                f"Work package {number}",
                (method,),
                predecessors,
            ))

    project = {
        "id": "converged-native-scale",
        "name": "64-declared converged native scale falsification",
        "horizon_ticks": 192,
        "calendars": [
            {"id": "SHIFT", "daily_windows": [[6, 22], [24, 40]]},
        ],
        "resources": [
            {"id": "M1", "capabilities": ["MECH"], "calendar_id": "SHIFT"},
            {"id": "M2", "capabilities": ["MECH"], "calendar_id": "SHIFT"},
            {"id": "M3", "capabilities": ["MECH"], "calendar_id": "SHIFT"},
            {"id": "Q1", "capabilities": ["QA"], "calendar_id": "SHIFT"},
            {"id": "C04", "capabilities": ["CRANE"], "calendar_id": "SHIFT"},
        ],
        "resource_groups": [{
            "id": "RIGGING",
            "name": "Interchangeable rigging pool",
            "capacity": 2,
            "calendar_id": "SHIFT",
            "disjoint": True,
            "interchangeable": True,
        }],
        "activities": activities,
        "objective_activity_id": packages[-1].methods[0].completion_activity_id,
        "pool_riggers": False,
    }
    problem = WorkMethodTimeProject(project, tuple(packages))
    assert len(activities) == DECLARED_ACTIVITIES
    return problem


def _entry_map(plan: dict) -> dict[str, dict]:
    return {entry["activity_id"]: entry for entry in plan["entries"]}


def _processing(problem: WorkMethodTimeProject, activity_id: str, mode_id: str) -> int:
    activity = next(item for item in problem.project["activities"] if item["id"] == activity_id)
    return next(mode["processing_ticks"] for mode in activity["modes"] if mode["id"] == mode_id)


def _productive(periods: list[list[int]]) -> int:
    return sum(finish - start for start, finish in periods)


def _clip_periods(periods: list[list[int]], boundary: int) -> list[list[int]]:
    clipped = []
    for start, finish in periods:
        if start >= boundary:
            break
        clipped.append([start, min(finish, boundary)])
        if finish >= boundary:
            break
    return clipped


def _accept(workspace: dict, activity_id: str, state: str, **values) -> None:
    update_id = report_status_update(
        workspace,
        activity_id,
        state,
        "scale-planner",
        "64-activity converged scale fixture",
        **values,
    )
    accept_status_update(workspace, update_id, "scale-acceptor")


def _status_point(reference_plan: dict) -> tuple[int, str]:
    target = next(
        entry
        for entry in reference_plan["entries"]
        if entry["activity_id"] == "WP02A05"
    )
    start, finish = target["periods"][0]
    if finish - start < 2:
        raise AssertionError("scale fixture needs an interior status tick")
    return start + 1, target["activity_id"]


def _outage_window(reference_plan: dict) -> tuple[int, int]:
    target = next(
        entry
        for entry in reference_plan["entries"]
        if entry["activity_id"] == "WP04A05"
    )
    start = target["periods"][0][0]
    return max(0, start - 1), start + 12


def _with_accepted_outage(problem: WorkMethodTimeProject, reference_plan: dict) -> WorkMethodTimeProject:
    start, finish = _outage_window(reference_plan)
    report = {
        "id": "SCALE-C04-OUTAGE",
        "resource_id": "C04",
        "start": start,
        "finish": finish,
        "reason": "Accepted scale-fixture crane outage",
        "reported_by": "operations",
        "status": "ACCEPTED",
        "accepted_by": "planner",
    }
    return WorkMethodTimeProject(
        deepcopy(problem.project),
        problem.work_packages,
        (report,),
    )


def build_status_workspace(
    current_problem: WorkMethodTimeProject,
    reference_plan: dict,
) -> tuple[dict, str]:
    """Build complete accepted T1 status from the reference schedule."""
    status_point, target_id = _status_point(reference_plan)
    workspace = materialise(current_problem, reference_plan["selected_methods"])
    enable_status_tracking(workspace, status_point)
    entries = _entry_map(reference_plan)

    for activity in workspace["project"]["activities"]:
        aid = activity["id"]
        entry = entries[aid]
        if entry["finish"] <= status_point:
            _accept(
                workspace,
                aid,
                "COMPLETED",
                actual_start=entry["start"],
                actual_finish=entry["finish"],
                actual_periods=deepcopy(entry["periods"]),
                mode_id=entry["mode_id"],
                named_assignments=deepcopy(entry["assignments"]),
                remaining_processing_ticks=0,
            )
        elif aid == target_id:
            actual_periods = _clip_periods(entry["periods"], status_point)
            revised_remaining = (
                _processing(current_problem, aid, entry["mode_id"])
                - _productive(actual_periods)
                + 2
            )
            _accept(
                workspace,
                aid,
                "IN_PROGRESS",
                actual_start=entry["start"],
                actual_finish=None,
                actual_periods=actual_periods,
                mode_id=entry["mode_id"],
                named_assignments=deepcopy(entry["assignments"]),
                remaining_processing_ticks=revised_remaining,
            )
        else:
            _accept(workspace, aid, "NOT_STARTED")

    validate_accepted_history(workspace, require_complete=True)
    return workspace, target_id


def _active_count(problem: WorkMethodTimeProject, methods: dict[str, str]) -> int:
    return len(materialise(problem, methods)["project"]["activities"])


def _calendar_slots(problem: WorkMethodTimeProject, calendar_id: str) -> set[int]:
    calendar = next(item for item in problem.project["calendars"] if item["id"] == calendar_id)
    horizon = problem.project["horizon_ticks"]
    slots: set[int] = set()
    for base in range(0, horizon + 48, 48):
        for start, finish in calendar["daily_windows"]:
            slots.update(range(base + start, min(base + finish, horizon)))
    return {tick for tick in slots if 0 <= tick < horizon}


def _eligible_slots(problem: WorkMethodTimeProject, mode: dict) -> set[int]:
    slots = _calendar_slots(problem, mode["calendar_id"])
    resources = {resource["id"]: resource for resource in problem.project["resources"]}
    for requirement in mode.get("requirements", []):
        eligible = requirement["eligible_resource_ids"]
        if len(eligible) != 1:
            raise AssertionError("scale oracle intentionally supports singleton named eligibility")
        resource = resources[eligible[0]]
        slots &= _calendar_slots(problem, resource["calendar_id"])
        for report in problem.reports:
            if (
                report["status"] == "ACCEPTED"
                and report["resource_id"] == resource["id"]
            ):
                slots.difference_update(range(report["start"], report["finish"]))
    groups = {group["id"]: group for group in problem.project.get("resource_groups", [])}
    for demand in mode.get("group_requirements", []):
        slots &= _calendar_slots(problem, groups[demand["group_id"]]["calendar_id"])
    return slots


def _periods_from_ticks(ticks: list[int]) -> list[list[int]]:
    if not ticks:
        return []
    periods: list[list[int]] = []
    start = previous = ticks[0]
    for tick in ticks[1:]:
        if tick != previous + 1:
            periods.append([start, previous + 1])
            start = tick
        previous = tick
    periods.append([start, previous + 1])
    return periods


def _earliest_periods(
    problem: WorkMethodTimeProject,
    mode: dict,
    work: int,
    earliest: int,
) -> tuple[int, int, list[list[int]]] | None:
    if work == 0:
        return earliest, earliest, []
    eligible = sorted(tick for tick in _eligible_slots(problem, mode) if tick >= earliest)
    if len(eligible) < work:
        return None
    chosen = eligible[:work]
    periods = _periods_from_ticks(chosen)
    return periods[0][0], periods[-1][1], periods


def solve_serial_control(
    problem: WorkMethodTimeProject,
    *,
    states: dict[str, dict] | None = None,
    status_point: int = 0,
) -> dict:
    """Independent pure-Python oracle for this deliberately serial scale fixture.

    It enumerates the 16 authorised structures and the single activity-mode
    branch, then places productive ticks directly from declared calendars and
    accepted outages. It does not call CP-SAT, the candidate placement compiler,
    or the accepted-progress proposal solver.
    """
    states = {} if states is None else states
    member_map = membership(problem)
    fixed_methods: dict[str, str] = {}
    for activity_id, record in states.items():
        if record["execution_state"] == "NOT_STARTED" or activity_id not in member_map:
            continue
        package_id, method_id = member_map[activity_id]
        fixed_methods[package_id] = method_id

    weights = {activity["id"]: index + 1 for index, activity in enumerate(problem.project["activities"])}
    by_id = {activity["id"]: activity for activity in problem.project["activities"]}
    packages = problem.work_packages
    branches = []
    best = None
    best_key = None

    for chosen_methods in product(*(package.methods for package in packages)):
        methods = {
            package.id: method.id
            for package, method in zip(packages, chosen_methods)
        }
        if any(methods[package_id] != method_id for package_id, method_id in fixed_methods.items()):
            continue

        active_ids = [
            activity_id
            for method in chosen_methods
            for activity_id in method.activity_ids
        ]
        mode_options = []
        for activity_id in active_ids:
            record = states.get(activity_id)
            if record and record["execution_state"] in {"IN_PROGRESS", "COMPLETED"}:
                mode_options.append([record["mode_id"]])
            else:
                mode_options.append([mode["id"] for mode in by_id[activity_id]["modes"]])

        for mode_ids in product(*mode_options):
            modes = dict(zip(active_ids, mode_ids))
            prior_finish = 0
            timing = 0
            entries = []
            feasible = True

            for activity_id in active_ids:
                activity = by_id[activity_id]
                mode_id = modes[activity_id]
                mode = next(mode for mode in activity["modes"] if mode["id"] == mode_id)
                record = states.get(activity_id)

                if record and record["execution_state"] == "COMPLETED":
                    start = finish = record["actual_finish"]
                    periods = []
                else:
                    work = (
                        record["remaining_processing_ticks"]
                        if record and record["execution_state"] == "IN_PROGRESS"
                        else mode["processing_ticks"]
                    )
                    earliest = max(
                        prior_finish,
                        status_point if states else 0,
                        activity.get("not_before", 0),
                    )
                    placed = _earliest_periods(problem, mode, work, earliest)
                    if placed is None:
                        feasible = False
                        break
                    start, finish, periods = placed

                prior_finish = max(prior_finish, finish)
                timing += weights[activity_id] * start
                entries.append({
                    "activity_id": activity_id,
                    "mode_id": mode_id,
                    "start": start,
                    "finish": finish,
                    "periods": periods,
                })

            if not feasible:
                branches.append({"methods": methods, "modes": modes, "status": "INFEASIBLE"})
                continue

            objective = [prior_finish, timing]
            key = policy_key(problem, methods, modes, objective)
            branch = {
                "methods": methods,
                "modes": modes,
                "status": "OPTIMAL_BY_SERIAL_ORACLE",
                "objective": objective,
                "entries": entries,
            }
            branches.append(branch)
            if best_key is None or key < best_key:
                best_key = key
                best = branch

    return {
        "best": best,
        "branches": branches,
        "enumerated_branches": len(branches),
        "oracle": "pure-python-serial-productive-time/0",
    }


def _rolling_target(cycle, switched_package: str) -> tuple[int, str]:
    package = next(p for p in cycle.current_problem.work_packages if p.id == switched_package)
    selected = cycle.reference_plan["selected_methods"][switched_package]
    method = package.method_by_id[selected]
    entries = _entry_map(cycle.reference_plan)
    target_id = method.activity_ids[-1]
    target = entries[target_id]
    start, finish = target["periods"][0]
    if finish - start < 2:
        raise AssertionError("rolling target needs an interior productive tick")
    return start + 1, target_id


def _advance_assertions(cycle, new_status_point: int, target_id: str) -> dict:
    """Project the prior validated reference schedule into one reviewed status advance."""
    states = current_status_records(cycle.status_workspace, require_complete=True)
    entries = _entry_map(cycle.reference_plan)
    assertions = {}

    for activity_id, prior in states.items():
        if prior["execution_state"] == "COMPLETED":
            continue
        entry = entries[activity_id]

        if prior["execution_state"] == "IN_PROGRESS":
            future_actual = _clip_periods(entry["periods"], new_status_point)
            actual_periods = deepcopy(prior["actual_periods"]) + future_actual
            if entry["finish"] <= new_status_point:
                assertions[activity_id] = {
                    "execution_state": "COMPLETED",
                    "reason": "scale T2 accepted completion",
                    "actual_start": prior["actual_start"],
                    "actual_finish": entry["finish"],
                    "actual_periods": actual_periods,
                    "mode_id": prior["mode_id"],
                    "named_assignments": deepcopy(prior["named_assignments"]),
                    "remaining_processing_ticks": 0,
                }
            else:
                executed_future = _productive(future_actual)
                assertions[activity_id] = {
                    "execution_state": "IN_PROGRESS",
                    "reason": "scale T2 accepted continuation",
                    "actual_start": prior["actual_start"],
                    "actual_finish": None,
                    "actual_periods": actual_periods,
                    "mode_id": prior["mode_id"],
                    "named_assignments": deepcopy(prior["named_assignments"]),
                    "remaining_processing_ticks": max(
                        1, prior["remaining_processing_ticks"] - executed_future
                    ),
                }
            continue

        if entry["finish"] <= new_status_point:
            assertions[activity_id] = {
                "execution_state": "COMPLETED",
                "reason": "scale T2 accepted completed work",
                "actual_start": entry["start"],
                "actual_finish": entry["finish"],
                "actual_periods": deepcopy(entry["periods"]),
                "mode_id": entry["mode_id"],
                "named_assignments": deepcopy(entry["assignments"]),
                "remaining_processing_ticks": 0,
            }
        elif activity_id == target_id:
            actual_periods = _clip_periods(entry["periods"], new_status_point)
            assertions[activity_id] = {
                "execution_state": "IN_PROGRESS",
                "reason": "scale T2 newly selected method has begun",
                "actual_start": entry["start"],
                "actual_finish": None,
                "actual_periods": actual_periods,
                "mode_id": entry["mode_id"],
                "named_assignments": deepcopy(entry["assignments"]),
                "remaining_processing_ticks": (
                    _processing(cycle.current_problem, activity_id, entry["mode_id"])
                    - _productive(actual_periods)
                ),
            }
        else:
            assertions[activity_id] = {
                "execution_state": "NOT_STARTED",
                "reason": "scale T2 work has not started",
            }
    return assertions


def _illegal_no_method_locks(cycle) -> dict:
    loose_problem, _, _ = _compile_future_problem(
        cycle.current_problem,
        cycle.reference_problem,
        cycle.reference_plan,
        cycle.status_workspace,
        fixed_methods_override={},
    )
    return schedule_work_method_time(loose_problem).plan


def run_experiment() -> dict:
    started = perf_counter()
    reference_problem = build_problem()
    source_hash = input_hash(reference_problem)

    control_started = perf_counter()
    baseline_control = solve_serial_control(reference_problem)
    control_ms = (perf_counter() - control_started) * 1000

    baseline_result = schedule_work_method_time(reference_problem)
    baseline_repeat = schedule_work_method_time(reference_problem)
    validate_plan(reference_problem, baseline_result.plan)
    baseline_plan = baseline_result.plan
    best = baseline_control["best"]
    baseline_matches_control = (
        best is not None
        and policy_key(
            reference_problem,
            baseline_plan["selected_methods"],
            baseline_plan["selected_modes"],
            baseline_plan["objective"],
        )
        == policy_key(
            reference_problem,
            best["methods"],
            best["modes"],
            best["objective"],
        )
    )

    current_problem = _with_accepted_outage(reference_problem, baseline_plan)
    status_workspace, in_progress_activity = build_status_workspace(
        current_problem,
        baseline_plan,
    )
    t1_hash = state_hash(status_workspace)

    recovery_result = schedule_accepted_work_method_time(
        current_problem,
        reference_problem,
        baseline_plan,
        status_workspace,
    )
    recovery_repeat = schedule_accepted_work_method_time(
        current_problem,
        reference_problem,
        baseline_plan,
        status_workspace,
    )
    recovery_plan = recovery_result.plan

    history_control_started = perf_counter()
    history_control = solve_serial_control(
        current_problem,
        states=current_status_records(status_workspace, require_complete=True),
        status_point=status_workspace["execution"]["status_point"],
    )
    history_control_ms = (perf_counter() - history_control_started) * 1000
    history_best = history_control["best"]
    recovery_matches_control = (
        history_best is not None
        and history_best["methods"] == recovery_plan["selected_methods"]
        and history_best["objective"][0] == recovery_plan["objective"][0]
    )

    switched = [
        package.id
        for package in current_problem.work_packages
        if baseline_plan["selected_methods"][package.id]
        != recovery_plan["selected_methods"][package.id]
    ]
    if not switched:
        raise AssertionError("scale disturbance failed to force any structural recovery")

    cycle = promote_structural_recovery_to_status_cycle(
        current_problem,
        reference_problem,
        baseline_plan,
        status_workspace,
        recovery_plan,
        asserted_by="scale-t1-planner",
        accepted_by="scale-t1-acceptor",
    )
    target_package = switched[0]
    t2_status_point, rolling_target = _rolling_target(cycle, target_package)
    assertions = _advance_assertions(cycle, t2_status_point, rolling_target)
    t2_cycle = advance_structural_status_cycle(
        cycle,
        t2_status_point,
        assertions,
        asserted_by="scale-t2-planner",
        accepted_by="scale-t2-acceptor",
    )
    t2_result = calculate_structural_recovery(t2_cycle)
    t2_repeat = calculate_structural_recovery(t2_cycle)
    t2_illegal = _illegal_no_method_locks(t2_cycle)

    t2_control_started = perf_counter()
    t2_control = solve_serial_control(
        t2_cycle.current_problem,
        states=current_status_records(t2_cycle.status_workspace, require_complete=True),
        status_point=t2_cycle.status_workspace["execution"]["status_point"],
    )
    t2_control_ms = (perf_counter() - t2_control_started) * 1000
    t2_best = t2_control["best"]
    t2_matches_control = (
        t2_best is not None
        and t2_best["methods"] == t2_result.plan["selected_methods"]
        and t2_best["objective"][0] == t2_result.plan["objective"][0]
    )

    t2_states = current_status_records(t2_cycle.status_workspace, require_complete=True)
    target_method = t2_result.plan["selected_methods"][target_package]

    evidence = {
        "milestone": "converged-native-scale-falsification-v0",
        "shape": {
            "declared_activities": len(reference_problem.project["activities"]),
            "baseline_active_activities": _active_count(
                reference_problem, baseline_plan["selected_methods"]
            ),
            "work_packages": len(reference_problem.work_packages),
            "flexible_packages": sum(
                len(package.methods) > 1 for package in reference_problem.work_packages
            ),
            "authorised_structures": 16,
            "horizon_ticks": reference_problem.project["horizon_ticks"],
        },
        "baseline": {
            "selected_methods": deepcopy(baseline_plan["selected_methods"]),
            "objective": deepcopy(baseline_plan["objective"]),
            "candidate_metrics": deepcopy(baseline_result.metrics),
            "control_enumerated_branches": baseline_control["enumerated_branches"],
            "control_ms": control_ms,
            "matches_control": baseline_matches_control,
            "repeat": baseline_plan == baseline_repeat.plan,
            "all_stages_optimal": all(
                stage["status"] == "OPTIMAL"
                for stage in baseline_plan["solver"]["stages"]
            ),
        },
        "t1": {
            "status_state_hash": t1_hash,
            "in_progress_activity": in_progress_activity,
            "selected_methods": deepcopy(recovery_plan["selected_methods"]),
            "objective": deepcopy(recovery_plan["objective"]),
            "switched_packages": switched,
            "candidate_metrics": deepcopy(recovery_result.metrics),
            "control_ms": history_control_ms,
            "matches_control": recovery_matches_control,
            "repeat": recovery_plan == recovery_repeat.plan,
        },
        "t2": {
            "status_point": t2_status_point,
            "rolling_target": rolling_target,
            "target_package": target_package,
            "target_method": target_method,
            "target_state": t2_states[rolling_target]["execution_state"],
            "selected_methods": deepcopy(t2_result.plan["selected_methods"]),
            "fixed_methods": deepcopy(t2_result.plan["fixed_methods"]),
            "objective": deepcopy(t2_result.plan["objective"]),
            "illegal_selected_methods": deepcopy(t2_illegal["selected_methods"]),
            "illegal_objective": deepcopy(t2_illegal["objective"]),
            "candidate_metrics": deepcopy(t2_result.metrics),
            "control_ms": t2_control_ms,
            "matches_control": t2_matches_control,
            "repeat": t2_result.plan == t2_repeat.plan,
            "lineage_count": len(t2_cycle.lineage),
        },
        "immutability": {
            "source_unchanged": input_hash(reference_problem) == source_hash,
            "t1_history_unchanged": state_hash(status_workspace) == t1_hash,
        },
        "end_to_end_ms": (perf_counter() - started) * 1000,
    }

    evidence["evidence_valid"] = all((
        evidence["shape"]["declared_activities"] == DECLARED_ACTIVITIES,
        evidence["shape"]["baseline_active_activities"] == BASELINE_ACTIVE_ACTIVITIES,
        evidence["shape"]["work_packages"] == PACKAGE_COUNT,
        evidence["shape"]["flexible_packages"] == FLEXIBLE_PACKAGE_COUNT,
        evidence["shape"]["authorised_structures"] == AUTHORISED_STRUCTURES,
        evidence["baseline"]["matches_control"],
        evidence["baseline"]["repeat"],
        evidence["baseline"]["all_stages_optimal"],
        evidence["t1"]["matches_control"],
        evidence["t1"]["repeat"],
        len(switched) >= 1,
        evidence["t2"]["target_state"] in {"IN_PROGRESS", "COMPLETED"},
        evidence["t2"]["fixed_methods"].get(target_package) == target_method,
        evidence["t2"]["selected_methods"].get(target_package) == target_method,
        evidence["t2"]["matches_control"],
        evidence["t2"]["repeat"],
        evidence["t2"]["lineage_count"] == 1,
        evidence["immutability"]["source_unchanged"],
        evidence["immutability"]["t1_history_unchanged"],
    ))
    evidence["boundary"] = (
        "64 declared / 48 active bounded falsification; not production-scale certification, "
        "not adaptive-repair integration, and not permission to raise other limits without evidence"
    )
    return evidence


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    result = run_experiment()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    print("CONVERGED NATIVE SCALE FALSIFICATION")
    print(json.dumps(result["shape"], sort_keys=True))
    print(
        "baseline:",
        result["baseline"]["selected_methods"],
        "objective=", result["baseline"]["objective"],
        "match=", result["baseline"]["matches_control"],
        "repeat=", result["baseline"]["repeat"],
    )
    print(
        "T1:",
        result["t1"]["selected_methods"],
        "switches=", result["t1"]["switched_packages"],
        "objective=", result["t1"]["objective"],
        "match=", result["t1"]["matches_control"],
    )
    print(
        "T2:",
        result["t2"]["selected_methods"],
        "target=", result["t2"]["target_package"],
        result["t2"]["target_method"],
        result["t2"]["target_state"],
        "objective=", result["t2"]["objective"],
        "illegal=", result["t2"]["illegal_selected_methods"],
        result["t2"]["illegal_objective"],
        "match=", result["t2"]["matches_control"],
    )
    print("baseline metrics:", json.dumps(result["baseline"]["candidate_metrics"], sort_keys=True))
    print("T1 metrics:", json.dumps(result["t1"]["candidate_metrics"], sort_keys=True))
    print("T2 metrics:", json.dumps(result["t2"]["candidate_metrics"], sort_keys=True))
    print(result["boundary"])
    if not result["evidence_valid"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
