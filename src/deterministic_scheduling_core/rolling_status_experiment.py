"""Headless rolling-status falsification experiment.

This experiment asks one bounded engine question:

Can an accepted-progress workspace advance through repeated status points while
preserving already accepted history, requiring explicit re-attestation of every
still-open activity, keeping remaining productive work independent from elapsed
actuals, and calculating each future remainder without UI state?

It deliberately stays inside the existing version-two accepted-progress model.
It does not add a general rolling-status schema or UI.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from deterministic_scheduling_core.project.planning_workspace import (
    STATUS_SCHEMA,
    accept_status_update,
    current_status_records,
    enable_status_tracking,
    new_demo_workspace,
    report_status_update,
    state_hash,
    validate_accepted_history,
)
from deterministic_scheduling_core.scheduling.planning_workspace import approve, propose


def _accept(
    workspace: dict[str, Any],
    activity_id: str,
    execution_state: str,
    *,
    actor: str,
    reason: str,
    supersedes_update_id: str | None = None,
    **values: Any,
) -> str:
    update_id = report_status_update(
        workspace,
        activity_id,
        execution_state,
        actor,
        reason,
        supersedes_update_id=supersedes_update_id,
        **values,
    )
    accept_status_update(workspace, update_id, f"{actor}-accept")
    return update_id


def _t1_workspace() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Create the accepted Day-1 11:00 control and approve its recovery."""
    workspace = new_demo_workspace()
    baseline = propose(workspace)
    approve(workspace, "baseline-planner")
    enable_status_tracking(workspace, 22)

    by_id = {entry["activity_id"]: entry for entry in baseline["entries"]}
    witness = {
        (activity_id, slot_id): resource_id
        for activity_id, slot_id, resource_id in baseline["allocation_witness"]
    }
    states = {
        "A01": "COMPLETED",
        "A02": "COMPLETED",
        "A03": "IN_PROGRESS",
        "A04": "NOT_STARTED",
        "A05": "COMPLETED",
        "A06": "COMPLETED",
        "A07": "COMPLETED",
        "A08": "NOT_STARTED",
    }

    for activity in workspace["project"]["activities"]:
        activity_id = activity["id"]
        state = states[activity_id]
        if state == "NOT_STARTED":
            _accept(
                workspace,
                activity_id,
                state,
                actor="t1-planner",
                reason="explicit T1 status",
            )
            continue

        entry = by_id[activity_id]
        assignments = [
            [
                slot_id,
                resource_id if resource_id is not None else witness[(activity_id, slot_id)],
            ]
            for slot_id, resource_id in entry["assignments"]
        ]
        values: dict[str, Any] = {
            "actual_start": entry["start"],
            "actual_finish": entry["finish"],
            "actual_periods": entry["periods"],
            "mode_id": baseline["selected_modes"][activity_id],
            "named_assignments": assignments,
            "remaining_processing_ticks": 0,
        }
        if activity_id == "A03":
            values.update(
                actual_start=20,
                actual_finish=None,
                actual_periods=[[20, 22]],
                mode_id="SPECIALIST",
                named_assignments=[["MECH", "M1"], ["SPECIALIST", "M2"]],
                remaining_processing_ticks=4,
            )
        _accept(
            workspace,
            activity_id,
            state,
            actor="t1-planner",
            reason="explicit T1 accepted execution",
            **values,
        )

    t1_plan = propose(workspace)
    approve(workspace, "t1-planner")
    return workspace, baseline, t1_plan


def _assert_in_progress_history_extension(prior: dict[str, Any], next_values: dict[str, Any]) -> None:
    """Require rolling status to append history rather than rewrite it."""
    next_state = next_values["execution_state"]
    if next_state not in {"IN_PROGRESS", "COMPLETED"}:
        raise ValueError("begun work cannot return to NOT_STARTED during status advancement")
    if next_values.get("actual_start") != prior["actual_start"]:
        raise ValueError("status advancement cannot rewrite an accepted actual start")
    if next_values.get("mode_id") != prior["mode_id"]:
        raise ValueError("status advancement cannot rewrite an accepted begun mode")
    if sorted(next_values.get("named_assignments", [])) != sorted(prior["named_assignments"]):
        raise ValueError("status advancement cannot rewrite accepted begun assignments")
    prior_periods = prior["actual_periods"]
    next_periods = next_values.get("actual_periods", [])
    if next_periods[: len(prior_periods)] != prior_periods:
        raise ValueError("status advancement must preserve accepted productive periods as an exact prefix")


def advance_status_atomically(
    workspace: dict[str, Any],
    new_status_point: int,
    assertions: dict[str, dict[str, Any]],
    *,
    actor: str,
) -> dict[str, str]:
    """Advance one bounded status cycle without exposing an invalid intermediate state.

    Every activity that was not already completed must be explicitly re-attested.
    Previously completed activities are immutable history and carry forward without
    another assertion.  New assertions supersede the previous current assertion.

    This helper is deliberately local to the experiment.  Its purpose is to test
    semantics before deciding whether the owning engine should adopt this API or a
    richer rolling-status representation.
    """
    if workspace.get("schema") != STATUS_SCHEMA:
        raise ValueError("rolling status requires a version-two accepted-progress workspace")
    old_status_point = workspace["execution"]["status_point"]
    if type(new_status_point) is not int or new_status_point <= old_status_point:
        raise ValueError("new status point must be an integer later than the current status point")
    if new_status_point > workspace["project"]["horizon_ticks"]:
        raise ValueError("new status point must lie inside the planning horizon")
    if not actor.strip():
        raise ValueError("status advancement needs an actor")

    prior_states = current_status_records(workspace, require_complete=True)
    required = {
        activity_id
        for activity_id, record in prior_states.items()
        if record["execution_state"] != "COMPLETED"
    }
    if set(assertions) != required:
        missing = sorted(required - set(assertions))
        extra = sorted(set(assertions) - required)
        raise ValueError(
            f"status advancement requires explicit re-attestation of every open activity; "
            f"missing={missing}, extra={extra}"
        )

    candidate = deepcopy(workspace)
    candidate["execution"]["status_point"] = new_status_point
    candidate["proposal"] = None
    accepted_ids: dict[str, str] = {}

    for activity_id in sorted(required):
        prior = prior_states[activity_id]
        values = deepcopy(assertions[activity_id])
        next_state = values.pop("execution_state")
        reason = values.pop("reason")
        if prior["execution_state"] == "IN_PROGRESS":
            _assert_in_progress_history_extension(
                prior,
                {"execution_state": next_state, **values},
            )
        update_id = _accept(
            candidate,
            activity_id,
            next_state,
            actor=actor,
            reason=reason,
            supersedes_update_id=prior["id"],
            occurred_at=new_status_point,
            **values,
        )
        accepted_ids[activity_id] = update_id

    validate_accepted_history(candidate, require_complete=True)
    workspace.clear()
    workspace.update(candidate)
    return accepted_ids


def _entry(plan: dict[str, Any], activity_id: str) -> dict[str, Any]:
    return next(entry for entry in plan["entries"] if entry["activity_id"] == activity_id)


def run_experiment() -> dict[str, Any]:
    workspace, baseline, t1_plan = _t1_workspace()

    if t1_plan["project_finish"] != 30:
        raise AssertionError(f"unexpected T1 finish: {t1_plan['project_finish']}")
    if _entry(t1_plan, "A03")["forecast_periods"] != [[22, 24], [25, 27]]:
        raise AssertionError("T1 A03 recovery no longer matches the bounded oracle")

    t1_a03 = deepcopy(current_status_records(workspace)["A03"])
    t1_approved_hash = workspace["approved_plan"]["plan_hash"]

    advance_status_atomically(
        workspace,
        23,
        {
            "A03": {
                "execution_state": "IN_PROGRESS",
                "reason": "T2 confirms one additional productive tick exactly as approved",
                "actual_start": 20,
                "actual_finish": None,
                "actual_periods": [[20, 22], [22, 23]],
                "mode_id": "SPECIALIST",
                "named_assignments": [["MECH", "M1"], ["SPECIALIST", "M2"]],
                "remaining_processing_ticks": 3,
            },
            "A04": {
                "execution_state": "NOT_STARTED",
                "reason": "T2 explicitly confirms final inspection has not started",
            },
            "A08": {
                "execution_state": "NOT_STARTED",
                "reason": "T2 explicitly confirms handback has not started",
            },
        },
        actor="t2-planner",
    )

    if t1_a03 not in workspace["execution"]["updates"]:
        raise AssertionError("T1 accepted A03 assertion was rewritten or removed")
    if workspace["approved_plan"]["plan_hash"] != t1_approved_hash:
        raise AssertionError("advancing status rewrote the previously approved recovery")
    if workspace["approved_plan"]["source_state_hash"] == state_hash(workspace):
        raise AssertionError("old approval did not become stale after T2 accepted facts")

    t2_plan = propose(workspace)
    if t2_plan["reference_plan_hash"] != t1_approved_hash:
        raise AssertionError("T2 recovery is not referenced to the approved T1 recovery")
    if t2_plan["project_finish"] != 30:
        raise AssertionError(f"execution exactly as approved should retain finish 30, got {t2_plan['project_finish']}")
    if _entry(t2_plan, "A03")["forecast_periods"] != [[23, 24], [25, 27]]:
        raise AssertionError("T2 forecast did not retain only the unexecuted slice of A03")
    approve(workspace, "t2-planner")

    t2_a03 = deepcopy(current_status_records(workspace)["A03"])
    t2_approved_hash = workspace["approved_plan"]["plan_hash"]

    advance_status_atomically(
        workspace,
        25,
        {
            "A03": {
                "execution_state": "IN_PROGRESS",
                "reason": "T3 accepts one extra tick of remaining productive work",
                "actual_start": 20,
                "actual_finish": None,
                "actual_periods": [[20, 22], [22, 23], [23, 24]],
                "mode_id": "SPECIALIST",
                "named_assignments": [["MECH", "M1"], ["SPECIALIST", "M2"]],
                "remaining_processing_ticks": 3,
            },
            "A04": {
                "execution_state": "NOT_STARTED",
                "reason": "T3 explicitly confirms final inspection has not started",
            },
            "A08": {
                "execution_state": "NOT_STARTED",
                "reason": "T3 explicitly confirms handback has not started",
            },
        },
        actor="t3-planner",
    )

    if t2_a03 not in workspace["execution"]["updates"]:
        raise AssertionError("T2 accepted A03 assertion was rewritten or removed")
    current_a03 = current_status_records(workspace)["A03"]
    if current_a03["actual_periods"] != [[20, 22], [22, 23], [23, 24]]:
        raise AssertionError("T3 actual history was not append-only")
    if current_a03["remaining_processing_ticks"] != 3:
        raise AssertionError("T3 accepted remainder was derived instead of independently retained")

    t3_plan = propose(workspace)
    if t3_plan["reference_plan_hash"] != t2_approved_hash:
        raise AssertionError("T3 recovery is not referenced to the approved T2 recovery")
    if t3_plan["project_finish"] != 31:
        raise AssertionError(f"the accepted extra remaining tick should move finish to 31, got {t3_plan['project_finish']}")
    if _entry(t3_plan, "A03")["forecast_periods"] != [[25, 28]]:
        raise AssertionError("T3 A03 recovery did not use the independently accepted three-tick remainder")
    if _entry(t3_plan, "A04")["forecast_periods"] != [[28, 30]]:
        raise AssertionError("T3 downstream inspection did not move with A03")
    if _entry(t3_plan, "A08")["forecast_periods"] != [[30, 31]]:
        raise AssertionError("T3 handback did not move with the accepted remainder")
    approve(workspace, "t3-planner")

    return {
        "baseline_finish": baseline["project_finish"],
        "t1": {
            "status_point": 22,
            "project_finish": t1_plan["project_finish"],
            "plan_hash": t1_approved_hash,
            "a03_actual": [[20, 22]],
            "a03_forecast": _entry(t1_plan, "A03")["forecast_periods"],
            "remaining_ticks": 4,
        },
        "t2": {
            "status_point": 23,
            "project_finish": t2_plan["project_finish"],
            "plan_hash": t2_approved_hash,
            "a03_actual": [[20, 22], [22, 23]],
            "a03_forecast": _entry(t2_plan, "A03")["forecast_periods"],
            "remaining_ticks": 3,
        },
        "t3": {
            "status_point": 25,
            "project_finish": t3_plan["project_finish"],
            "plan_hash": workspace["approved_plan"]["plan_hash"],
            "a03_actual": current_status_records(workspace)["A03"]["actual_periods"],
            "a03_forecast": _entry(t3_plan, "A03")["forecast_periods"],
            "remaining_ticks": 3,
        },
        "accepted_update_count": len(
            [item for item in workspace["execution"]["updates"] if item["status"] == "ACCEPTED"]
        ),
        "plan_history_count": len(workspace["plan_history"]),
        "final_state_hash": state_hash(workspace),
        "workspace": workspace,
    }


def main() -> None:
    result = run_experiment()
    print("Headless rolling-status experiment")
    for key in ("t1", "t2", "t3"):
        item = result[key]
        print(
            f"{key.upper()} status={item['status_point']} finish={item['project_finish']} "
            f"A03 actual={item['a03_actual']} forecast={item['a03_forecast']} "
            f"remaining={item['remaining_ticks']}"
        )
    print(
        f"accepted updates={result['accepted_update_count']} "
        f"approved-plan history={result['plan_history_count']}"
    )


if __name__ == "__main__":
    main()
