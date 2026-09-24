"""Bounded rolling structural-status handover experiment.

This composes PR #36's one-status structural recovery with the existing atomic
status-advancement transaction. It proves that a newly selected untouched method
can become the next active execution structure and, once execution begins, become
hard history on later cycles.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path

from deterministic_scheduling_core.accepted_work_method_time_experiment import (
    build_problem,
    build_status_workspace,
)
from deterministic_scheduling_core.project.planning_workspace import (
    current_status_records,
    state_hash,
)
from deterministic_scheduling_core.project.rolling_structural_status import (
    to_document as cycle_to_document,
)
from deterministic_scheduling_core.project.work_method_time import input_hash
from deterministic_scheduling_core.scheduling.accepted_work_method_time import (
    _compile_future_problem,
    schedule_accepted_work_method_time,
)
from deterministic_scheduling_core.scheduling.rolling_structural_status import (
    advance_structural_status_cycle,
    calculate_structural_recovery,
    promote_structural_recovery_to_status_cycle,
    validate_cycle,
)
from deterministic_scheduling_core.scheduling.work_method_time import (
    schedule_work_method_time,
)


def _illegal_counterfactual(cycle) -> dict:
    """Remove only accepted method locks; retain status/mode/resource facts."""
    loose_problem, _, _ = _compile_future_problem(
        cycle.current_problem,
        cycle.reference_problem,
        cycle.reference_plan,
        cycle.status_workspace,
        fixed_methods_override={},
    )
    return schedule_work_method_time(loose_problem).plan


def _t2_assertions() -> dict:
    return {
        "LIFT": {
            "execution_state": "IN_PROGRESS",
            "reason": "T2 reviewed lift progress and revised remaining work",
            "actual_start": 2,
            "actual_finish": None,
            "actual_periods": [[2, 4], [4, 6]],
            "mode_id": "FIXED",
            "named_assignments": [["MECH", "M1"], ["CRANE", "C04"]],
            "remaining_processing_ticks": 2,
        },
        "REST_MAN1": {
            "execution_state": "IN_PROGRESS",
            "reason": "T2 manual restore has begun",
            "actual_start": 4,
            "actual_finish": None,
            "actual_periods": [[4, 6]],
            "mode_id": "FIXED",
            "named_assignments": [["MECH", "M2"]],
            "remaining_processing_ticks": 2,
        },
        "REST_MAN2": {
            "execution_state": "NOT_STARTED",
            "reason": "T2 second manual stage has not started",
        },
        "DONE": {
            "execution_state": "NOT_STARTED",
            "reason": "T2 handoff has not started",
        },
    }


def _t3_assertions() -> dict:
    return {
        "LIFT": {
            "execution_state": "COMPLETED",
            "reason": "T3 lift is complete",
            "actual_start": 2,
            "actual_finish": 8,
            "actual_periods": [[2, 4], [4, 6], [6, 8]],
            "mode_id": "FIXED",
            "named_assignments": [["MECH", "M1"], ["CRANE", "C04"]],
            "remaining_processing_ticks": 0,
        },
        "REST_MAN1": {
            "execution_state": "COMPLETED",
            "reason": "T3 first manual restore stage is complete",
            "actual_start": 4,
            "actual_finish": 8,
            "actual_periods": [[4, 6], [6, 8]],
            "mode_id": "FIXED",
            "named_assignments": [["MECH", "M2"]],
            "remaining_processing_ticks": 0,
        },
        "REST_MAN2": {
            "execution_state": "NOT_STARTED",
            "reason": "T3 second manual stage has not started",
        },
        "DONE": {
            "execution_state": "NOT_STARTED",
            "reason": "T3 handoff has not started",
        },
    }


def run_experiment() -> dict:
    problem = build_problem()
    original_input_hash = input_hash(problem)

    reference_plan = schedule_work_method_time(problem).plan
    t1_status = build_status_workspace(problem, reference_plan)
    t1_status_hash = state_hash(t1_status)
    t1_recovery = schedule_accepted_work_method_time(
        problem,
        problem,
        reference_plan,
        t1_status,
    ).plan

    t1_cycle = promote_structural_recovery_to_status_cycle(
        problem,
        problem,
        reference_plan,
        t1_status,
        t1_recovery,
        asserted_by="t1-planner",
        accepted_by="t1-acceptor",
    )
    validate_cycle(t1_cycle)
    t1_promoted_hash = state_hash(t1_cycle.status_workspace)
    t1_states = current_status_records(t1_cycle.status_workspace, require_complete=True)

    t2_cycle = advance_structural_status_cycle(
        t1_cycle,
        6,
        _t2_assertions(),
        asserted_by="t2-planner",
        accepted_by="t2-acceptor",
    )
    t2_recovery_result = calculate_structural_recovery(t2_cycle)
    t2_recovery = t2_recovery_result.plan
    t2_repeat = calculate_structural_recovery(t2_cycle).plan
    t2_illegal = _illegal_counterfactual(t2_cycle)

    t2_promoted = promote_structural_recovery_to_status_cycle(
        t2_cycle.current_problem,
        t2_cycle.reference_problem,
        t2_cycle.reference_plan,
        t2_cycle.status_workspace,
        t2_recovery,
        asserted_by="t2-planner",
        accepted_by="t2-acceptor",
        prior_lineage=t2_cycle.lineage,
    )
    validate_cycle(t2_promoted)

    t3_cycle = advance_structural_status_cycle(
        t2_promoted,
        8,
        _t3_assertions(),
        asserted_by="t3-planner",
        accepted_by="t3-acceptor",
    )
    t3_recovery_result = calculate_structural_recovery(t3_cycle)
    t3_recovery = t3_recovery_result.plan
    t3_repeat = calculate_structural_recovery(t3_cycle).plan
    t3_illegal = _illegal_counterfactual(t3_cycle)

    t2_states = current_status_records(t2_cycle.status_workspace, require_complete=True)
    t3_states = current_status_records(t3_cycle.status_workspace, require_complete=True)
    t1_ids = {activity["id"] for activity in t1_cycle.status_workspace["project"]["activities"]}

    result = {
        "milestone": "rolling-structural-status-v0",
        "original_input_hash": original_input_hash,
        "reference_plan_hash": reference_plan["plan_hash"],
        "t1": {
            "prior_status_state_hash": t1_status_hash,
            "promoted_status_state_hash": t1_promoted_hash,
            "selected_methods": deepcopy(t1_cycle.reference_plan["selected_methods"]),
            "activity_ids": sorted(t1_ids),
            "lineage": deepcopy(t1_cycle.lineage),
            "states": {
                aid: {
                    "state": record["execution_state"],
                    "actual_periods": record["actual_periods"],
                    "remaining": record["remaining_processing_ticks"],
                }
                for aid, record in t1_states.items()
            },
        },
        "t2": {
            "status_state_hash": state_hash(t2_cycle.status_workspace),
            "selected_methods": deepcopy(t2_recovery["selected_methods"]),
            "finish": t2_recovery["objective"][0],
            "fixed_methods": deepcopy(t2_recovery["fixed_methods"]),
            "illegal_selected_methods": deepcopy(t2_illegal["selected_methods"]),
            "illegal_finish": t2_illegal["objective"][0],
            "repeat": t2_recovery == t2_repeat,
            "states": {
                aid: {
                    "state": record["execution_state"],
                    "actual_periods": record["actual_periods"],
                    "remaining": record["remaining_processing_ticks"],
                }
                for aid, record in t2_states.items()
            },
        },
        "t3": {
            "status_state_hash": state_hash(t3_cycle.status_workspace),
            "selected_methods": deepcopy(t3_recovery["selected_methods"]),
            "finish": t3_recovery["objective"][0],
            "fixed_methods": deepcopy(t3_recovery["fixed_methods"]),
            "illegal_selected_methods": deepcopy(t3_illegal["selected_methods"]),
            "illegal_finish": t3_illegal["objective"][0],
            "repeat": t3_recovery == t3_repeat,
            "lineage": deepcopy(t3_cycle.lineage),
            "states": {
                aid: {
                    "state": record["execution_state"],
                    "actual_periods": record["actual_periods"],
                    "remaining": record["remaining_processing_ticks"],
                }
                for aid, record in t3_states.items()
            },
        },
        "cycle_document": cycle_to_document(t3_cycle),
        "source_unchanged": input_hash(problem) == original_input_hash,
        "prior_t1_status_unchanged": state_hash(t1_status) == t1_status_hash,
    }

    result["evidence_valid"] = all((
        result["t1"]["selected_methods"]["REMOVE"] == "LIFT",
        result["t1"]["selected_methods"]["RESTORE"] == "MANUAL",
        "REST_CRANE" not in t1_ids,
        {"REST_MAN1", "REST_MAN2"} <= t1_ids,
        t1_states["REST_MAN1"]["execution_state"] == "NOT_STARTED",
        t1_states["REST_MAN2"]["execution_state"] == "NOT_STARTED",
        result["t2"]["fixed_methods"]["REMOVE"] == "LIFT",
        result["t2"]["fixed_methods"]["RESTORE"] == "MANUAL",
        result["t2"]["selected_methods"]["RESTORE"] == "MANUAL",
        result["t2"]["illegal_selected_methods"]["RESTORE"] == "CRANE",
        result["t2"]["illegal_finish"] < result["t2"]["finish"],
        result["t3"]["fixed_methods"]["REMOVE"] == "LIFT",
        result["t3"]["fixed_methods"]["RESTORE"] == "MANUAL",
        result["t3"]["selected_methods"]["RESTORE"] == "MANUAL",
        result["t3"]["illegal_selected_methods"]["RESTORE"] == "CRANE",
        result["t3"]["illegal_finish"] < result["t3"]["finish"],
        len(result["t3"]["lineage"]) == 2,
        result["t2"]["repeat"],
        result["t3"]["repeat"],
        result["source_unchanged"],
        result["prior_t1_status_unchanged"],
    ))
    result["boundary"] = (
        "structural recovery handover plus T1->T2->T3 status only; "
        "continuous begun work, anonymous-group cross-boundary identity, UI and production scale remain excluded"
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

    print("ROLLING STRUCTURAL STATUS")
    print(
        f"T1 promoted: {result['t1']['selected_methods']} "
        f"activities={result['t1']['activity_ids']}"
    )
    print(
        f"T2 recovery: {result['t2']['selected_methods']} finish={result['t2']['finish']}; "
        f"illegal={result['t2']['illegal_selected_methods']} finish={result['t2']['illegal_finish']}"
    )
    print(
        f"T3 recovery: {result['t3']['selected_methods']} finish={result['t3']['finish']}; "
        f"illegal={result['t3']['illegal_selected_methods']} finish={result['t3']['illegal_finish']}"
    )
    print(f"lineage={len(result['t3']['lineage'])}; {result['boundary']}")
    if not result["evidence_valid"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
