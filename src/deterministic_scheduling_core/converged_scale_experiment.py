"""Materially larger falsification case for the converged native scheduling path.

The fixture intentionally reaches beyond the former 32-activity composition
boundary while keeping structural enumeration bounded at 16 authorised method
combinations. It exercises future planning, accepted-history recovery and one
rolling structural-status handover/advance in the same native model family.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path

from deterministic_scheduling_core.native_work_method_time import solve_fixed_controls
from deterministic_scheduling_core.project.model import ExecutionMethod, WorkPackage
from deterministic_scheduling_core.project.planning_workspace import (
    accept_status_update,
    current_status_records,
    enable_status_tracking,
    report_status_update,
    state_hash,
    validate_accepted_history,
)
from deterministic_scheduling_core.project.rolling_structural_status import (
    to_document as cycle_to_document,
)
from deterministic_scheduling_core.project.work_method_time import (
    WorkMethodTimeProject,
    input_hash,
    materialise,
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
    validate_problem,
)

STATUS_T1 = 8
STATUS_T2 = 18
OUTAGE_START = 8
OUTAGE_FINISH = 18


def _slot(slot_id: str, capability: str, eligible: tuple[str, ...]) -> dict:
    return {
        "id": slot_id,
        "pool_ids": [capability],
        "eligible_resource_ids": list(eligible),
    }


def _mode(
    mode_id: str,
    work: int,
    *,
    requirements: tuple[dict, ...] = (),
    groups: tuple[dict, ...] = (),
    calendar: str = "SHIFT",
) -> dict:
    return {
        "id": mode_id,
        "processing_ticks": work,
        "calendar_id": calendar,
        "continuity": "SUSPENDABLE_AT_AVAILABILITY_GAPS",
        "requirements": [deepcopy(requirement) for requirement in requirements],
        "group_requirements": [deepcopy(group) for group in groups],
    }


def _chain(
    package_number: int,
    suffix: str,
    durations: tuple[int, ...],
    *,
    flexible_standard: bool = False,
    crane_at: int | None = None,
    objective_last: bool = False,
) -> tuple[list[dict], tuple[str, ...], str]:
    """Create one method chain with sparse named/group resource semantics."""
    activities: list[dict] = []
    ids: list[str] = []
    prior: str | None = None
    tech = _slot("TECH", "TECH", ("M1",))
    inspect = _slot("INSPECT", "INSPECT", ("I1",))
    crane = _slot("CRANE", "CRANE", ("C04",))
    mech = {"group_id": "MECH_POOL", "demand": 1}
    rig = {"group_id": "RIGGING", "demand": 1}

    for index, duration in enumerate(durations, 1):
        aid = "DONE" if objective_last and index == len(durations) else f"P{package_number:02d}{suffix}{index:02d}"
        ids.append(aid)

        requirements: tuple[dict, ...] = ()
        groups: tuple[dict, ...] = ()
        modes: list[dict]

        if package_number == 2 and suffix == "A" and index == 1:
            duration = 3
            requirements = (tech,)
        elif package_number == 3 and suffix == "A" and index == 1:
            duration = 3
            requirements = (inspect,)
        elif crane_at == index:
            requirements = (crane,)
        elif index == 2:
            groups = (mech,)
        elif (suffix == "A" and index == 5) or (suffix == "B" and index == 3):
            groups = (rig,)

        if package_number == 1 and suffix == "A" and index == 3:
            modes = [
                _mode("NORMAL", 2, groups=(mech,)),
                _mode("FAST", 1, requirements=(tech,)),
            ]
        elif package_number == 5 and suffix == "A" and index == 4:
            modes = [
                _mode("NORMAL", 2, groups=(rig,)),
                _mode("FAST", 1, requirements=(inspect,)),
            ]
        else:
            modes = [_mode("FIXED", duration, requirements=requirements, groups=groups)]

        activity = {
            "id": aid,
            "name": f"WP-{package_number:02d} {suffix} step {index}",
            "modes": modes,
        }
        if prior is not None:
            activity["predecessors"] = [prior]
        activities.append(activity)
        prior = aid

    return activities, tuple(ids), ids[-1]


def build_problem(*, accepted_outage: bool = False) -> WorkMethodTimeProject:
    """Build 64 declared activities / 48 baseline-active / 16 structures."""
    activities: list[dict] = []
    packages: list[WorkPackage] = []
    flexible = {2, 4, 6, 7}

    for package_number in range(1, 8):
        package_id = f"WP-{package_number:02d}"
        if package_number in flexible:
            standard_durations = (1, 1, 1, 1, 1, 1)
            crane_at = 3 if package_number == 7 else None
            standard, standard_ids, standard_end = _chain(
                package_number,
                "A",
                standard_durations,
                flexible_standard=True,
                crane_at=crane_at,
            )
            alternative, alternative_ids, alternative_end = _chain(
                package_number,
                "B",
                (2, 2, 2, 2),
            )
            activities.extend(standard)
            activities.extend(alternative)
            packages.append(
                WorkPackage(
                    package_id,
                    f"Work package {package_number}",
                    (
                        ExecutionMethod("STANDARD", "Standard method", standard_ids, standard_end),
                        ExecutionMethod("ALTERNATIVE", "Alternative method", alternative_ids, alternative_end),
                    ),
                )
            )
        else:
            fixed, fixed_ids, fixed_end = _chain(package_number, "A", (1, 1, 1, 1, 1, 1))
            activities.extend(fixed)
            packages.append(
                WorkPackage(
                    package_id,
                    f"Work package {package_number}",
                    (ExecutionMethod("FIXED", "Fixed method", fixed_ids, fixed_end),),
                )
            )

    handoff, handoff_ids, handoff_end = _chain(
        8,
        "A",
        (1, 1, 1, 1, 1, 0),
        objective_last=True,
    )
    activities.extend(handoff)
    packages.append(
        WorkPackage(
            "WP-08",
            "Protected controlling handoff",
            (ExecutionMethod("HANDOFF", "Project handoff", handoff_ids, handoff_end),),
            tuple(f"WP-{index:02d}" for index in range(1, 8)),
        )
    )

    roots = {
        "P01A01": 0,
        "P02A01": 4,
        "P02B01": 4,
        "P03A01": 6,
        "P04A01": 2,
        "P04B01": 2,
        "P05A01": 3,
        "P06A01": 5,
        "P06B01": 5,
        "P07A01": 4,
        "P07B01": 4,
    }
    for activity in activities:
        if activity["id"] in roots:
            activity["not_before"] = roots[activity["id"]]

    project = {
        "id": "converged-scale-64",
        "name": "Converged native scale falsification",
        "horizon_ticks": 64,
        "calendars": [
            {"id": "SHIFT", "daily_windows": [[0, 30], [32, 48]]},
            {"id": "ALWAYS", "daily_windows": [[0, 48]]},
        ],
        "resources": [
            {"id": "M1", "capabilities": ["TECH"], "calendar_id": "SHIFT"},
            {"id": "I1", "capabilities": ["INSPECT"], "calendar_id": "SHIFT"},
            {"id": "C04", "capabilities": ["CRANE"], "calendar_id": "ALWAYS"},
        ],
        "resource_groups": [
            {
                "id": "MECH_POOL",
                "name": "Interchangeable mechanical capacity",
                "capacity": 2,
                "calendar_id": "SHIFT",
                "disjoint": True,
                "interchangeable": True,
            },
            {
                "id": "RIGGING",
                "name": "Interchangeable rigging capacity",
                "capacity": 2,
                "calendar_id": "SHIFT",
                "disjoint": True,
                "interchangeable": True,
            },
        ],
        "activities": activities,
        "objective_activity_id": "DONE",
        "pool_riggers": False,
    }
    reports = ()
    if accepted_outage:
        reports = ({
            "id": "C04-T1",
            "resource_id": "C04",
            "start": OUTAGE_START,
            "finish": OUTAGE_FINISH,
            "reason": "Accepted C04 outage for scale recovery",
            "reported_by": "operations",
            "status": "ACCEPTED",
            "accepted_by": "planner",
        },)
    return WorkMethodTimeProject(project, tuple(packages), reports)


def _accept(workspace: dict, activity_id: str, execution_state: str, **values) -> None:
    update_id = report_status_update(
        workspace,
        activity_id,
        execution_state,
        "scale-field-planner",
        "converged scale falsification accepted status",
        **values,
    )
    accept_status_update(workspace, update_id, "scale-schedule-acceptor")


def build_t1_status(
    current_problem: WorkMethodTimeProject,
    reference_plan: dict,
) -> dict:
    """Status the baseline-selected structure at T1 with two begun activities."""
    workspace = materialise(current_problem, reference_plan["selected_methods"])
    enable_status_tracking(workspace, STATUS_T1)
    active_ids = {activity["id"] for activity in workspace["project"]["activities"]}

    for activity_id in sorted(active_ids):
        if activity_id == "P01A01":
            _accept(
                workspace,
                activity_id,
                "COMPLETED",
                actual_start=0,
                actual_finish=2,
                actual_periods=[[0, 2]],
                mode_id="FIXED",
                named_assignments=[],
                remaining_processing_ticks=0,
            )
        elif activity_id == "P02A01":
            _accept(
                workspace,
                activity_id,
                "IN_PROGRESS",
                actual_start=6,
                actual_finish=None,
                actual_periods=[[6, 8]],
                mode_id="FIXED",
                named_assignments=[["TECH", "M1"]],
                remaining_processing_ticks=2,
            )
        elif activity_id == "P03A01":
            _accept(
                workspace,
                activity_id,
                "IN_PROGRESS",
                actual_start=6,
                actual_finish=None,
                actual_periods=[[6, 8]],
                mode_id="FIXED",
                named_assignments=[["INSPECT", "I1"]],
                remaining_processing_ticks=1,
            )
        else:
            _accept(workspace, activity_id, "NOT_STARTED")

    validate_accepted_history(workspace, require_complete=True)
    return workspace


def _t2_assertions(cycle) -> dict:
    """Complete prior begun roots and begin the newly selected WP-07 alternative."""
    states = current_status_records(cycle.status_workspace, require_complete=True)
    assertions: dict[str, dict] = {}
    for activity_id, record in states.items():
        if record["execution_state"] == "COMPLETED":
            continue
        if activity_id == "P02A01":
            assertions[activity_id] = {
                "execution_state": "COMPLETED",
                "reason": "T2 scale cycle completes begun WP-02 root",
                "actual_start": 6,
                "actual_finish": 10,
                "actual_periods": [[6, 8], [8, 10]],
                "mode_id": "FIXED",
                "named_assignments": [["TECH", "M1"]],
                "remaining_processing_ticks": 0,
            }
        elif activity_id == "P03A01":
            assertions[activity_id] = {
                "execution_state": "COMPLETED",
                "reason": "T2 scale cycle completes begun WP-03 root",
                "actual_start": 6,
                "actual_finish": 9,
                "actual_periods": [[6, 8], [8, 9]],
                "mode_id": "FIXED",
                "named_assignments": [["INSPECT", "I1"]],
                "remaining_processing_ticks": 0,
            }
        elif activity_id == "P07B01":
            assertions[activity_id] = {
                "execution_state": "IN_PROGRESS",
                "reason": "T2 scale cycle begins recovered WP-07 alternative",
                "actual_start": 16,
                "actual_finish": None,
                "actual_periods": [[16, 18]],
                "mode_id": "FIXED",
                "named_assignments": [],
                "remaining_processing_ticks": 3,
            }
        else:
            assertions[activity_id] = {
                "execution_state": "NOT_STARTED",
                "reason": "T2 scale cycle confirms activity remains not started",
            }
    return assertions


def _illegal_no_lock(cycle) -> dict:
    loose_problem, _, _ = _compile_future_problem(
        cycle.current_problem,
        cycle.reference_problem,
        cycle.reference_plan,
        cycle.status_workspace,
        fixed_methods_override={},
    )
    return schedule_work_method_time(loose_problem).plan


def run_experiment() -> dict:
    reference_problem = build_problem()
    validate_problem(reference_problem)
    source_hash = input_hash(reference_problem)

    baseline_control = solve_fixed_controls(reference_problem)
    baseline_candidate = schedule_work_method_time(reference_problem)
    baseline_repeat = schedule_work_method_time(reference_problem)
    validate_plan(reference_problem, baseline_candidate.plan)

    best = baseline_control["best"]
    baseline_match = best is not None and policy_key(
        reference_problem,
        baseline_candidate.plan["selected_methods"],
        baseline_candidate.plan["selected_modes"],
        baseline_candidate.plan["objective"],
    ) == policy_key(
        reference_problem,
        best["methods"],
        best["modes"],
        best["objective"],
    )

    current_problem = build_problem(accepted_outage=True)
    t1_status = build_t1_status(current_problem, baseline_candidate.plan)
    t1_status_hash = state_hash(t1_status)
    recovery = schedule_accepted_work_method_time(
        current_problem,
        reference_problem,
        baseline_candidate.plan,
        t1_status,
    )
    recovery_repeat = schedule_accepted_work_method_time(
        current_problem,
        reference_problem,
        baseline_candidate.plan,
        t1_status,
    )

    t1_cycle = promote_structural_recovery_to_status_cycle(
        current_problem,
        reference_problem,
        baseline_candidate.plan,
        t1_status,
        recovery.plan,
        asserted_by="scale-t1-planner",
        accepted_by="scale-t1-acceptor",
    )
    t2_cycle = advance_structural_status_cycle(
        t1_cycle,
        STATUS_T2,
        _t2_assertions(t1_cycle),
        asserted_by="scale-t2-planner",
        accepted_by="scale-t2-acceptor",
    )
    t2_recovery = calculate_structural_recovery(t2_cycle)
    t2_repeat = calculate_structural_recovery(t2_cycle)
    t2_illegal = _illegal_no_lock(t2_cycle)

    baseline_active = len(baseline_candidate.plan["entries"])
    declared = len(reference_problem.project["activities"])
    branch_count = len(baseline_control["branches"])
    t2_states = current_status_records(t2_cycle.status_workspace, require_complete=True)

    result = {
        "milestone": "converged-native-scale-falsification-v0",
        "shape": {
            "declared_activities": declared,
            "baseline_active_activities": baseline_active,
            "work_packages": len(reference_problem.work_packages),
            "authorised_structures": 16,
            "fixed_control_branches": branch_count,
        },
        "baseline": {
            "input_hash": source_hash,
            "selected_methods": deepcopy(baseline_candidate.plan["selected_methods"]),
            "selected_modes": deepcopy(baseline_candidate.plan["selected_modes"]),
            "objective": deepcopy(baseline_candidate.plan["objective"]),
            "candidate_metrics": deepcopy(baseline_candidate.metrics),
            "control_solver_calls": baseline_control["solver_calls"],
            "control_end_to_end_ms": baseline_control["end_to_end_ms"],
            "matches_control": baseline_match,
            "repeat_plan_matches": baseline_candidate.plan == baseline_repeat.plan,
            "solver_stages": len(baseline_candidate.plan["solver"]["stages"]),
            "plan": deepcopy(baseline_candidate.plan),
        },
        "t1_recovery": {
            "selected_methods": deepcopy(recovery.plan["selected_methods"]),
            "objective": deepcopy(recovery.plan["objective"]),
            "fixed_methods": deepcopy(recovery.plan["fixed_methods"]),
            "metrics": deepcopy(recovery.metrics),
            "repeat_plan_matches": recovery.plan == recovery_repeat.plan,
            "status_unchanged": state_hash(t1_status) == t1_status_hash,
            "plan": deepcopy(recovery.plan),
        },
        "t2": {
            "selected_methods": deepcopy(t2_recovery.plan["selected_methods"]),
            "objective": deepcopy(t2_recovery.plan["objective"]),
            "fixed_methods": deepcopy(t2_recovery.plan["fixed_methods"]),
            "metrics": deepcopy(t2_recovery.metrics),
            "repeat_plan_matches": t2_recovery.plan == t2_repeat.plan,
            "illegal_selected_methods": deepcopy(t2_illegal["selected_methods"]),
            "illegal_objective": deepcopy(t2_illegal["objective"]),
            "plan": deepcopy(t2_recovery.plan),
            "cycle_document": cycle_to_document(t2_cycle),
            "wp07_state": {
                "execution_state": t2_states["P07B01"]["execution_state"],
                "actual_periods": deepcopy(t2_states["P07B01"]["actual_periods"]),
                "remaining_processing_ticks": t2_states["P07B01"]["remaining_processing_ticks"],
            },
        },
        "source_unchanged": input_hash(reference_problem) == source_hash,
        "reference_document": to_document(reference_problem),
    }

    result["evidence_valid"] = all((
        declared == 64,
        baseline_active == 48,
        branch_count == 64,
        baseline_match,
        result["baseline"]["repeat_plan_matches"],
        baseline_candidate.plan["selected_methods"]["WP-02"] == "STANDARD",
        baseline_candidate.plan["selected_methods"]["WP-04"] == "STANDARD",
        baseline_candidate.plan["selected_methods"]["WP-06"] == "STANDARD",
        baseline_candidate.plan["selected_methods"]["WP-07"] == "STANDARD",
        recovery.plan["fixed_methods"]["WP-02"] == "STANDARD",
        recovery.plan["selected_methods"]["WP-02"] == "STANDARD",
        recovery.plan["selected_methods"]["WP-07"] == "ALTERNATIVE",
        result["t1_recovery"]["repeat_plan_matches"],
        result["t1_recovery"]["status_unchanged"],
        t2_recovery.plan["fixed_methods"]["WP-07"] == "ALTERNATIVE",
        t2_recovery.plan["selected_methods"]["WP-07"] == "ALTERNATIVE",
        t2_illegal["selected_methods"]["WP-07"] == "STANDARD",
        t2_illegal["objective"][0] < t2_recovery.plan["objective"][0],
        result["t2"]["repeat_plan_matches"],
        result["source_unchanged"],
    ))
    result["boundary"] = (
        "64 declared / 48 baseline-active activities, 16 structures, accepted recovery and one rolling status cycle; "
        "this is a bounded falsification case, not production-scale certification"
    )
    return result


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
    print(
        f"shape={result['shape']}; baseline={result['baseline']['selected_methods']} "
        f"objective={result['baseline']['objective']} stages={result['baseline']['solver_stages']}"
    )
    print(
        f"T1 recovery={result['t1_recovery']['selected_methods']} "
        f"objective={result['t1_recovery']['objective']}"
    )
    print(
        f"T2 recovery={result['t2']['selected_methods']} objective={result['t2']['objective']}; "
        f"illegal={result['t2']['illegal_selected_methods']} objective={result['t2']['illegal_objective']}"
    )
    print(json.dumps({
        "baseline_candidate_metrics": result["baseline"]["candidate_metrics"],
        "baseline_control_ms": result["baseline"]["control_end_to_end_ms"],
        "t1_metrics": result["t1_recovery"]["metrics"],
        "t2_metrics": result["t2"]["metrics"],
    }, sort_keys=True))
    print(result["boundary"])
    if not result["evidence_valid"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
