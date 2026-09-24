"""Bounded handover from structural recovery into repeated accepted status cycles."""
from __future__ import annotations

from copy import deepcopy

from deterministic_scheduling_core.project.planning_workspace import (
    accept_status_update,
    advance_status_point,
    current_status_records,
    enable_status_tracking,
    report_status_update,
    state_hash,
    validate as validate_workspace,
    validate_accepted_history,
)
from deterministic_scheduling_core.project.rolling_structural_status import (
    RollingStructuralStatusCycle,
)
from deterministic_scheduling_core.project.work_method_time import materialise
from .accepted_work_method_time import (
    AcceptedWorkMethodTimeResult,
    _compile_future_problem,
    schedule_accepted_work_method_time,
    validate_input,
    validate_plan as validate_accepted_plan,
)
from .work_method_time import validate_plan as validate_work_method_plan


def validate_cycle(cycle: RollingStructuralStatusCycle) -> None:
    """Validate one persisted structural-status cycle without scheduling."""
    if not isinstance(cycle, RollingStructuralStatusCycle):
        raise ValueError("expected RollingStructuralStatusCycle")
    validate_work_method_plan(cycle.reference_problem, cycle.reference_plan)
    validate_workspace(cycle.status_workspace)
    validate_input(
        cycle.current_problem,
        cycle.reference_problem,
        cycle.reference_plan,
        cycle.status_workspace,
    )
    if cycle.lineage:
        latest = cycle.lineage[-1]
        if latest["promoted_reference_plan_hash"] != cycle.reference_plan["plan_hash"]:
            raise ValueError("cycle reference plan disagrees with promotion lineage")
        if latest["selected_methods"] != cycle.reference_plan["selected_methods"]:
            raise ValueError("cycle selected structure disagrees with promotion lineage")


def calculate_structural_recovery(
    cycle: RollingStructuralStatusCycle,
) -> AcceptedWorkMethodTimeResult:
    """Calculate the current cycle without mutating its accepted status."""
    validate_cycle(cycle)
    return schedule_accepted_work_method_time(
        cycle.current_problem,
        cycle.reference_problem,
        cycle.reference_plan,
        cycle.status_workspace,
    )


def promote_structural_recovery_to_status_cycle(
    problem,
    reference_problem,
    reference_plan: dict,
    status_workspace: dict,
    recovery_plan: dict,
    *,
    asserted_by: str,
    accepted_by: str,
    prior_lineage: tuple[dict, ...] = (),
) -> RollingStructuralStatusCycle:
    """Make a validated structural recovery the active structure at the same status point.

    Executed accepted history is copied byte-for-byte. Retained NOT_STARTED
    assertions are copied when the activity remains selected. Unexecuted
    deselected alternatives are omitted. Newly selected activities receive an
    explicit accepted NOT_STARTED assertion at the current status boundary.
    """
    if not asserted_by.strip() or not accepted_by.strip():
        raise ValueError("structural promotion requires asserting and accepting actors")
    if prior_lineage:
        latest = prior_lineage[-1]
        if (
            latest.get("promoted_reference_plan_hash") != reference_plan.get("plan_hash")
            or latest.get("selected_methods") != reference_plan.get("selected_methods")
        ):
            raise ValueError("prior structural lineage does not lead to the supplied reference plan")
    pending_execution = [
        update
        for update in status_workspace.get("execution", {}).get("updates", [])
        if update.get("status") == "REPORTED"
    ]
    if pending_execution:
        raise ValueError(
            "structural promotion requires pending reported execution assertions to be resolved first"
        )
    validate_accepted_plan(
        problem,
        reference_problem,
        reference_plan,
        status_workspace,
        recovery_plan,
    )

    # This is the exact problem against which recovery_plan["future_plan"] was
    # proved. Reuse it as the next cycle's reference source without re-solving.
    next_reference_problem, _, _ = _compile_future_problem(
        problem,
        reference_problem,
        reference_plan,
        status_workspace,
    )
    next_reference_plan = deepcopy(recovery_plan["future_plan"])
    validate_work_method_plan(next_reference_problem, next_reference_plan)

    selected_methods = recovery_plan["selected_methods"]
    next_workspace = materialise(problem, selected_methods)
    status_point = status_workspace["execution"]["status_point"]
    enable_status_tracking(next_workspace, status_point)

    prior_states = current_status_records(status_workspace, require_complete=True)
    selected_ids = {activity["id"] for activity in next_workspace["project"]["activities"]}
    executed_ids = {
        activity_id
        for activity_id, record in prior_states.items()
        if record["execution_state"] != "NOT_STARTED"
    }
    if not executed_ids <= selected_ids:
        missing = sorted(executed_ids - selected_ids)
        raise ValueError(
            "structural promotion would discard accepted execution history: "
            + ", ".join(missing)
        )

    retained_ids = selected_ids & set(prior_states)
    next_workspace["execution"]["updates"] = deepcopy([
        update
        for update in status_workspace["execution"]["updates"]
        if update["status"] == "ACCEPTED" and update["activity_id"] in retained_ids
    ])
    validate_workspace(next_workspace)
    validate_accepted_history(next_workspace, require_complete=False)

    newly_selected = sorted(selected_ids - retained_ids)
    for activity_id in newly_selected:
        update_id = report_status_update(
            next_workspace,
            activity_id,
            "NOT_STARTED",
            asserted_by,
            f"selected by validated structural recovery {recovery_plan['plan_hash']}",
            occurred_at=status_point,
        )
        accept_status_update(next_workspace, update_id, accepted_by)

    validate_accepted_history(next_workspace, require_complete=True)
    prior_hash = state_hash(status_workspace)
    promoted_hash = state_hash(next_workspace)
    lineage = tuple(deepcopy(prior_lineage)) + ({
        "prior_status_state_hash": prior_hash,
        "recovery_plan_hash": recovery_plan["plan_hash"],
        "prior_reference_plan_hash": reference_plan["plan_hash"],
        "promoted_reference_plan_hash": next_reference_plan["plan_hash"],
        "promoted_status_state_hash": promoted_hash,
        "selected_methods": deepcopy(selected_methods),
    },)

    cycle = RollingStructuralStatusCycle(
        deepcopy(problem),
        next_reference_problem,
        next_reference_plan,
        next_workspace,
        lineage,
    )
    validate_cycle(cycle)

    # Promotion must never mutate the prior authoritative cycle.
    if state_hash(status_workspace) != prior_hash:
        raise AssertionError("structural promotion mutated prior accepted status")
    return cycle


def advance_structural_status_cycle(
    cycle: RollingStructuralStatusCycle,
    new_status_point: int,
    assertions: dict,
    *,
    asserted_by: str,
    accepted_by: str,
) -> RollingStructuralStatusCycle:
    """Advance time on the already-promoted selected structure."""
    validate_cycle(cycle)
    workspace = deepcopy(cycle.status_workspace)
    advance_status_point(
        workspace,
        new_status_point,
        assertions,
        asserted_by,
        accepted_by,
    )
    advanced = RollingStructuralStatusCycle(
        deepcopy(cycle.current_problem),
        deepcopy(cycle.reference_problem),
        deepcopy(cycle.reference_plan),
        workspace,
        deepcopy(cycle.lineage),
    )
    validate_cycle(advanced)
    return advanced
