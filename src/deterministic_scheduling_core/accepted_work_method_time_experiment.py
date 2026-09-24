"""Bounded accepted-history + Work-Method/productive-time composition experiment.

The experiment proves one seam only: accepted execution fixes historical
structural choices, while a completely untouched downstream package may still
choose another authorised method during recovery.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path

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
    method_selections,
    to_document,
)
from deterministic_scheduling_core.scheduling.accepted_work_method_time import (
    _compile_future_problem,
    schedule_accepted_work_method_time,
    validate_input,
    validate_plan,
)
from deterministic_scheduling_core.scheduling.planning_workspace import propose
from deterministic_scheduling_core.scheduling.work_method_time import (
    schedule_work_method_time,
    validate_plan as validate_reference_plan,
)


def _slot(slot_id: str, capability: str, eligible: tuple[str, ...]) -> dict:
    return {
        "id": slot_id,
        "pool_ids": [capability],
        "eligible_resource_ids": list(eligible),
    }


def _mode(
    mode_id: str,
    work: int,
    requirements: tuple[dict, ...] = (),
    *,
    calendar: str = "ALWAYS",
) -> dict:
    return {
        "id": mode_id,
        "processing_ticks": work,
        "calendar_id": calendar,
        "continuity": "SUSPENDABLE_AT_AVAILABILITY_GAPS",
        "requirements": [deepcopy(requirement) for requirement in requirements],
        "group_requirements": [],
    }


def build_problem() -> WorkMethodTimeProject:
    """Eight-activity structural case with a deliberately tempting illegal repair."""
    mech_m1 = _slot("MECH", "MECH", ("M1",))
    mech_m2 = _slot("MECH", "MECH", ("M2",))
    crane = _slot("CRANE", "CRANE", ("C04",))

    activities = [
        {
            "id": "PREP",
            "name": "Prepare workfront",
            "modes": [_mode("FIXED", 2, (mech_m1,))],
        },
        {
            "id": "LIFT",
            "name": "Lift component",
            "modes": [_mode("FIXED", 4, (mech_m1, crane))],
        },
        {
            "id": "SEG1",
            "name": "Segment component",
            "modes": [_mode("FIXED", 3, (mech_m1,))],
        },
        {
            "id": "SEG2",
            "name": "Remove segmented component",
            "predecessors": ["SEG1"],
            "modes": [_mode("FIXED", 4, (mech_m1,))],
        },
        {
            "id": "REST_CRANE",
            "name": "Crane-assisted restore",
            "not_before": 6,
            "modes": [_mode("FIXED", 2, (mech_m2, crane))],
        },
        {
            "id": "REST_MAN1",
            "name": "Manual restore stage one",
            "modes": [_mode("FIXED", 4, (mech_m2,))],
        },
        {
            "id": "REST_MAN2",
            "name": "Manual restore stage two",
            "predecessors": ["REST_MAN1"],
            "modes": [_mode("FIXED", 4, (mech_m2,))],
        },
        {
            "id": "DONE",
            "name": "Return to service",
            "modes": [_mode("FIXED", 0)],
        },
    ]

    project = {
        "id": "accepted-wm-demo",
        "name": "Accepted history with structural recovery",
        "horizon_ticks": 32,
        "calendars": [{"id": "ALWAYS", "daily_windows": [[0, 48]]}],
        "resources": [
            {"id": "M1", "capabilities": ["MECH"], "calendar_id": "ALWAYS"},
            {"id": "M2", "capabilities": ["MECH"], "calendar_id": "ALWAYS"},
            {"id": "C04", "capabilities": ["CRANE"], "calendar_id": "ALWAYS"},
        ],
        "resource_groups": [],
        "activities": activities,
        "objective_activity_id": "DONE",
        "pool_riggers": False,
    }
    packages = (
        WorkPackage(
            "PREP_WORK",
            "Preparation",
            (ExecutionMethod("FIXED", "Preparation", ("PREP",), "PREP"),),
        ),
        WorkPackage(
            "REMOVE",
            "Remove component",
            (
                ExecutionMethod("LIFT", "Lift complete component", ("LIFT",), "LIFT"),
                ExecutionMethod(
                    "SEGMENTED",
                    "Segmented removal",
                    ("SEG1", "SEG2"),
                    "SEG2",
                ),
            ),
            ("PREP_WORK",),
        ),
        WorkPackage(
            "RESTORE",
            "Restore system",
            (
                ExecutionMethod(
                    "CRANE",
                    "Crane-assisted restore",
                    ("REST_CRANE",),
                    "REST_CRANE",
                ),
                ExecutionMethod(
                    "MANUAL",
                    "Manual restore",
                    ("REST_MAN1", "REST_MAN2"),
                    "REST_MAN2",
                ),
            ),
            ("PREP_WORK",),
        ),
        WorkPackage(
            "HANDOFF",
            "Return to service",
            (ExecutionMethod("FIXED", "Handoff", ("DONE",), "DONE"),),
            ("REMOVE", "RESTORE"),
        ),
    )
    return WorkMethodTimeProject(project, packages)


def _accept(
    workspace: dict,
    activity_id: str,
    execution_state: str,
    **values,
) -> None:
    update_id = report_status_update(
        workspace,
        activity_id,
        execution_state,
        "field-planner",
        "bounded accepted-history composition fixture",
        **values,
    )
    accept_status_update(workspace, update_id, "schedule-acceptor")


def build_status_workspace(
    problem: WorkMethodTimeProject,
    reference_plan: dict,
    *,
    remaining_ticks: int = 8,
) -> dict:
    """Status only the reference-selected execution structure, never the union."""
    workspace = materialise(problem, reference_plan["selected_methods"])
    enable_status_tracking(workspace, 4)

    _accept(
        workspace,
        "PREP",
        "COMPLETED",
        actual_start=0,
        actual_finish=2,
        actual_periods=[[0, 2]],
        mode_id="FIXED",
        named_assignments=[["MECH", "M1"]],
        remaining_processing_ticks=0,
    )
    _accept(
        workspace,
        "LIFT",
        "IN_PROGRESS",
        actual_start=2,
        actual_finish=None,
        actual_periods=[[2, 4]],
        mode_id="FIXED",
        named_assignments=[["MECH", "M1"], ["CRANE", "C04"]],
        remaining_processing_ticks=remaining_ticks,
    )
    _accept(workspace, "REST_CRANE", "NOT_STARTED")
    _accept(workspace, "DONE", "NOT_STARTED")
    validate_accepted_history(workspace, require_complete=True)
    return workspace


def _control_workspace(
    problem: WorkMethodTimeProject,
    methods: dict[str, str],
    source_status: dict,
) -> dict:
    """Project the same executed facts onto one explicitly selected future network."""
    workspace = materialise(problem, methods)
    enable_status_tracking(workspace, source_status["execution"]["status_point"])
    source_states = current_status_records(source_status, require_complete=True)

    for activity in workspace["project"]["activities"]:
        activity_id = activity["id"]
        record = source_states.get(activity_id)
        if record and record["execution_state"] != "NOT_STARTED":
            _accept(
                workspace,
                activity_id,
                record["execution_state"],
                actual_start=record["actual_start"],
                actual_finish=record["actual_finish"],
                actual_periods=deepcopy(record["actual_periods"]),
                mode_id=record["mode_id"],
                named_assignments=deepcopy(record["named_assignments"]),
                remaining_processing_ticks=record["remaining_processing_ticks"],
            )
        else:
            _accept(workspace, activity_id, "NOT_STARTED")

    validate_accepted_history(workspace, require_complete=True)
    return workspace


def solve_allowed_controls(
    problem: WorkMethodTimeProject,
    reference_problem: WorkMethodTimeProject,
    reference_plan: dict,
    status_workspace: dict,
) -> dict:
    """Enumerate only structures permitted by accepted history, then use v2 recovery."""
    _, fixed = validate_input(problem, reference_problem, reference_plan, status_workspace)
    branches = []
    for methods in method_selections(problem):
        if any(methods[package_id] != method_id for package_id, method_id in fixed.items()):
            continue
        workspace = _control_workspace(problem, methods, status_workspace)
        plan = propose(workspace)
        branches.append(
            {
                "methods": methods,
                "project_finish": plan["project_finish"],
                "objective": plan["objective"],
                "physical_status": plan["physical_status"],
            }
        )

    if not branches:
        raise AssertionError("accepted-history control produced no permitted structure")

    package_order = {package.id: package for package in problem.work_packages}

    def order(branch):
        method_indexes = tuple(
            next(
                index
                for index, method in enumerate(package_order[package.id].methods)
                if method.id == branch["methods"][package.id]
            )
            for package in problem.work_packages
        )
        return branch["project_finish"], method_indexes

    return {"best": min(branches, key=order), "branches": branches}


def run_experiment() -> dict:
    problem = build_problem()
    source_hash = input_hash(problem)

    reference = schedule_work_method_time(problem).plan
    validate_reference_plan(problem, reference)
    status_workspace = build_status_workspace(problem, reference)
    accepted_hash = state_hash(status_workspace)

    candidate = schedule_accepted_work_method_time(problem, problem, reference, status_workspace)
    repeated = schedule_accepted_work_method_time(problem, problem, reference, status_workspace)
    validate_plan(problem, problem, reference, status_workspace, candidate.plan)

    controls = solve_allowed_controls(problem, problem, reference, status_workspace)

    # Deliberately illegal counterfactual: compile the same status information but
    # remove the hard method locks. This is evidence for why accepted history must
    # constrain structural choice; it is never returned as an authoritative plan.
    loose_problem, _, _ = _compile_future_problem(
        problem,
        problem,
        reference,
        status_workspace,
        fixed_methods_override={},
    )
    unconstrained = schedule_work_method_time(loose_problem).plan

    by_id = {entry["activity_id"]: entry for entry in candidate.plan["entries"]}
    states = current_status_records(status_workspace, require_complete=True)
    result = {
        "milestone": "accepted-history-work-method-composition-v0",
        "input": to_document(problem),
        "reference": reference,
        "status_state_hash": accepted_hash,
        "accepted_states": {
            activity_id: {
                "execution_state": record["execution_state"],
                "actual_periods": record["actual_periods"],
                "remaining_processing_ticks": record["remaining_processing_ticks"],
            }
            for activity_id, record in states.items()
        },
        "candidate": asdict(candidate),
        "control": controls,
        "illegal_unconstrained_counterfactual": {
            "selected_methods": unconstrained["selected_methods"],
            "objective": unconstrained["objective"],
        },
        "source_unchanged": source_hash == input_hash(problem),
        "history_unchanged": accepted_hash == state_hash(status_workspace),
        "repeat_plan_matches": candidate.plan == repeated.plan,
        "observations": {
            "reference_finish": reference["objective"][0],
            "reference_remove_method": reference["selected_methods"]["REMOVE"],
            "reference_restore_method": reference["selected_methods"]["RESTORE"],
            "recovery_finish": candidate.plan["objective"][0],
            "recovery_remove_method": candidate.plan["selected_methods"]["REMOVE"],
            "recovery_restore_method": candidate.plan["selected_methods"]["RESTORE"],
            "lift_actual_periods": by_id["LIFT"]["actual_periods"],
            "lift_remaining_ticks": by_id["LIFT"]["remaining_processing_ticks"],
            "lift_forecast_periods": by_id["LIFT"]["forecast_periods"],
        },
    }
    best = controls["best"]
    result["evidence_valid"] = all(
        (
            reference["selected_methods"]["REMOVE"] == "LIFT",
            reference["selected_methods"]["RESTORE"] == "CRANE",
            reference["objective"][0] == 8,
            candidate.plan["fixed_methods"]["REMOVE"] == "LIFT",
            candidate.plan["selected_methods"]["REMOVE"] == "LIFT",
            candidate.plan["selected_methods"]["RESTORE"] == "MANUAL",
            candidate.plan["objective"][0] == 12,
            best["methods"] == candidate.plan["selected_methods"],
            best["project_finish"] == candidate.plan["objective"][0],
            unconstrained["selected_methods"]["REMOVE"] == "SEGMENTED",
            unconstrained["selected_methods"]["RESTORE"] == "CRANE",
            unconstrained["objective"][0] == 11,
            result["source_unchanged"],
            result["history_unchanged"],
            result["repeat_plan_matches"],
        )
    )
    result["boundary"] = (
        "one status point; accepted begun method/mode/resources and completed history are hard, "
        "untouched packages may change method; rolling structural status remains a later experiment"
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

    observation = result["observations"]
    print("ACCEPTED HISTORY + WORK-METHOD COMPOSITION")
    print(
        f"reference: REMOVE={observation['reference_remove_method']} "
        f"RESTORE={observation['reference_restore_method']} "
        f"finish={observation['reference_finish']}"
    )
    print(
        f"recovery: REMOVE={observation['recovery_remove_method']} "
        f"RESTORE={observation['recovery_restore_method']} "
        f"finish={observation['recovery_finish']}"
    )
    print(
        "illegal unconstrained counterfactual: "
        f"{result['illegal_unconstrained_counterfactual']['selected_methods']} "
        f"finish={result['illegal_unconstrained_counterfactual']['objective'][0]}"
    )
    print(
        f"LIFT actual={observation['lift_actual_periods']} "
        f"remaining={observation['lift_remaining_ticks']} "
        f"forecast={observation['lift_forecast_periods']}"
    )
    print(result["boundary"])
    if not result["evidence_valid"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
