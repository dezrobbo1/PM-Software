"""Bounded native workflow compiler, reusing PR #24's placements and exact checker.

Finite activity-mode combinations are enumerated; each graph is solved by CP-SAT.
This is not the final solver architecture or a structural Work-Method compiler.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from itertools import product
from math import prod

import ortools
from ortools.sat.python import cp_model

from deterministic_scheduling_core.errors import SchedulingError
from deterministic_scheduling_core.project.planning_workspace import (
    POLICY, Workspace, digest, now, state_hash, trusted_input, validate,
)
from deterministic_scheduling_core import resource_assignment_experiment as ra
from deterministic_scheduling_core.working_time_experiment import SUSPENDABLE, WorkCalendar


def _case(workspace: Workspace, selected: dict[str, str]) -> ra.ExperimentCase:
    project = workspace["project"]
    activities = []
    for activity in project["activities"]:
        mode = next(m for m in activity["modes"] if m["id"] == selected[activity["id"]])
        requirements = tuple(ra.RequirementSlot(r["id"], tuple(r["pool_ids"]), tuple(r["eligible_resource_ids"])) for r in mode.get("requirements", []))
        activities.append(ra.ActivitySpec(
            activity["id"], activity["name"], mode["processing_ticks"], mode["calendar_id"],
            requirements, tuple(activity.get("predecessors", [])), activity.get("not_before", 0),
            mode.get("continuity", SUSPENDABLE),
        ))
    return ra.ExperimentCase(
        tuple(WorkCalendar(c["id"], tuple(tuple(w) for w in c["daily_windows"])) for c in project["calendars"]),
        tuple(ra.PhysicalResource(r["id"], tuple(r["capabilities"]), r["calendar_id"], 1) for r in project["resources"]),
        tuple(ra.AvailabilityException(r["resource_id"], r["start"], r["finish"], r["reason"]) for r in workspace["reports"] if r["status"] == "ACCEPTED"),
        tuple(activities), project["objective_activity_id"], project["horizon_ticks"],
    )


def _can_pool(case: ra.ExperimentCase, requested: bool) -> bool:
    """Use the existing two-rigger pool only while its interchangeability holds."""
    riggers = [r for r in case.resources if "RIGGER" in r.capabilities]
    if not requested or len(riggers) != 2 or any(r.capabilities != ("RIGGER",) for r in riggers):
        return False
    ids = {r.id for r in riggers}
    if ra._resource_slots(case, riggers[0].id) != ra._resource_slots(case, riggers[1].id):
        return False
    for activity in case.activities:
        for requirement in activity.requirements:
            if ids & set(requirement.eligible_resource_ids):
                if requirement.pool_ids != ("RIGGER",) or set(requirement.eligible_resource_ids) != ids:
                    return False
    return True


def _solve_case(case: ra.ExperimentCase, pooled: bool, approved: dict | None):
    model = cp_model.CpModel()
    starts, ends, choices = {}, {}, {}
    named_intervals = {resource.id: [] for resource in case.resources}
    pooled_intervals = []
    assignment_changes = []
    reference = {e["activity_id"]: e for e in approved["entries"]} if approved else {}
    for activity in case.activities:
        placements = ra._candidate_placements(case, activity, "C" if pooled else "B")
        if not placements:
            return None
        starts[activity.id] = model.new_int_var(0, case.horizon, f"start_{activity.id}")
        ends[activity.id] = model.new_int_var(0, case.horizon, f"end_{activity.id}")
        literals = []
        choices[activity.id] = []
        old_assignments = dict(reference.get(activity.id, {}).get("assignments", []))
        for index, placement in enumerate(placements):
            literal = model.new_bool_var(f"place_{activity.id}_{index}")
            literals.append(literal)
            choices[activity.id].append((literal, placement))
            model.add(starts[activity.id] == placement.start).only_enforce_if(literal)
            model.add(ends[activity.id] == placement.finish).only_enforce_if(literal)
            changes = 0
            for requirement, resource_id in zip(activity.requirements, placement.assignments):
                if requirement.id in old_assignments and old_assignments[requirement.id] != resource_id:
                    changes += 1
                for segment, (start, finish) in enumerate(placement.periods):
                    interval = model.new_optional_interval_var(start, finish - start, finish, literal,
                        f"use_{activity.id}_{index}_{requirement.id}_{segment}")
                    if resource_id is None:
                        pooled_intervals.append(interval)
                    else:
                        named_intervals[resource_id].append(interval)
            assignment_changes.append(changes * literal)
        model.add_exactly_one(literals)
    for activity in case.activities:
        for predecessor in activity.predecessors:
            model.add(starts[activity.id] >= ends[predecessor])
    for intervals in named_intervals.values():
        if intervals:
            model.add_no_overlap(intervals)
    if pooled_intervals:
        model.add_cumulative(pooled_intervals, [1] * len(pooled_intervals), 2)
    movements = []
    for activity_id, old in reference.items():
        if activity_id in starts:
            movement = model.new_int_var(0, case.horizon + abs(old["start"]), f"move_{activity_id}")
            model.add_abs_equality(movement, starts[activity_id] - old["start"])
            movements.append(movement)
    total_movement = sum(movements)
    total_assignment_changes = sum(assignment_changes)
    timing = sum((index + 1) * starts[a.id] for index, a in enumerate(case.activities))
    objectives = [ends[case.objective_activity_id]]
    if approved:
        objectives.extend((total_movement, total_assignment_changes))
    objectives.append(timing)
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    for objective in objectives:
        model.minimize(objective)
        status = solver.solve(model)
        if status == cp_model.INFEASIBLE:
            return None
        if status != cp_model.OPTIMAL:
            raise SchedulingError(f"workflow solve unproved: {solver.status_name(status)}")
        model.add(objective == solver.value(objective))
    entries = []
    for activity in case.activities:
        placement = next(p for literal, p in choices[activity.id] if solver.value(literal))
        entries.append(ra.ScheduledEntry(activity.id, placement.start, placement.finish, placement.periods,
            tuple((r.id, resource_id) for r, resource_id in zip(activity.requirements, placement.assignments))))
    check = ra.check_fixed_schedule(case, tuple(entries))
    if not check.physically_assignable:
        raise SchedulingError(f"independent allocation check failed: {check.reason}")
    return tuple(entries), check, (
        solver.value(ends[case.objective_activity_id]), solver.value(total_movement),
        solver.value(total_assignment_changes), solver.value(timing),
    ), len(objectives)


def _plan_hash(plan: dict) -> str:
    return digest({k: v for k, v in plan.items() if k not in {"plan_hash", "approved_by", "approved_at"}})


def propose(workspace: Workspace) -> dict:
    """Calculate from accepted inputs only; never overwrite the approved plan."""
    validate(workspace)
    activities = workspace["project"]["activities"]
    if prod(len(a["modes"]) for a in activities) > 16:
        raise ValueError("this POC supports at most 16 authorised activity-mode combinations")
    approved = workspace["approved_plan"]
    alternatives, candidates = [], []
    calls = 0
    for modes in product(*(a["modes"] for a in activities)):
        selected = {a["id"]: mode["id"] for a, mode in zip(activities, modes)}
        case = _case(workspace, selected)
        pooled = _can_pool(case, workspace["project"].get("pool_riggers", False))
        result = _solve_case(case, pooled, approved)
        if result is None:
            alternatives.append({"modes": selected, "status": "INFEASIBLE"})
            continue
        entries, check, values, stage_calls = result
        calls += stage_calls
        mode_changes = sum(approved["selected_modes"].get(key) != value for key, value in selected.items()) if approved else 0
        objective = (values[0], mode_changes, values[1], values[2], values[3])
        alternatives.append({"modes": selected, "status": "OPTIMAL", "objective": list(objective)})
        candidates.append((objective, tuple(selected.values()), selected, entries, check, pooled))
    if not candidates:
        workspace["proposal"] = None
        raise SchedulingError("no executable plan within the declared horizon; accepted facts and prior approved plan are retained")
    objective, _, selected, entries, check, pooled = min(candidates, key=lambda c: (c[0], c[1]))
    plan = {
        "source_state_hash": state_hash(workspace), "source_snapshot": trusted_input(workspace),
        "reference_plan_hash": approved["plan_hash"] if approved else None,
        "selected_modes": selected, "entries": [asdict(e) for e in entries],
        "objective": list(objective), "project_finish": objective[0], "policy": POLICY,
        "pooled_riggers": pooled, "allocation_witness": list(check.allocation),
        "physical_status": check.exact_status, "alternatives": alternatives,
        "solver": {"name": "CP-SAT", "version": ortools.__version__, "workers": 1, "seed": 0,
                   "compiler": "native-workflow/0", "feasible_branch_solver_calls": calls,
                   "proof": "all feasible mode combinations and objective stages proven optimal",
                   "repeatability": "same-environment observation only; equivalent assignments need not be unique"},
    }
    # Store JSON-shaped values even before the first save/reopen.
    import json
    plan = json.loads(json.dumps(plan))
    plan["plan_hash"] = _plan_hash(plan)
    workspace["proposal"] = plan
    return plan


def validate_plan(workspace: Workspace, plan: dict) -> None:
    validate(workspace)
    if plan["source_state_hash"] != state_hash(workspace) or plan["source_snapshot"] != trusted_input(workspace):
        raise ValueError("proposal is stale; recalculate from current accepted inputs")
    if plan["plan_hash"] != _plan_hash(plan):
        raise ValueError("stored proposal was edited; recalculate rather than editing solver output")
    ids = [a["id"] for a in workspace["project"]["activities"]]
    if set(plan["selected_modes"]) != set(ids) or sorted(e["activity_id"] for e in plan["entries"]) != sorted(ids):
        raise ValueError("plan does not cover the native project exactly")
    for activity in workspace["project"]["activities"]:
        if plan["selected_modes"][activity["id"]] not in {m["id"] for m in activity["modes"]}:
            raise ValueError("plan selected an unauthorised mode")
    case = _case(workspace, plan["selected_modes"])
    entries = []
    for entry in plan["entries"]:
        periods = tuple(tuple(p) for p in entry["periods"])
        activity = case.activity_by_id[entry["activity_id"]]
        if entry["start"] < activity.not_before or entry["finish"] > case.horizon:
            raise ValueError("plan lies outside native time boundaries")
        if periods and (entry["start"] != periods[0][0] or entry["finish"] != periods[-1][1]):
            raise ValueError("execution envelope disagrees with productive periods")
        if not periods and entry["start"] != entry["finish"]:
            raise ValueError("milestone has nonzero elapsed span")
        if any(start >= end for start, end in periods) or any(a[1] > b[0] for a, b in zip(periods, periods[1:])):
            raise ValueError("invalid execution periods")
        entries.append(ra.ScheduledEntry(entry["activity_id"], entry["start"], entry["finish"], periods,
                                        tuple(tuple(a) for a in entry["assignments"])))
    check = ra.check_fixed_schedule(case, tuple(entries))
    if not check.physically_assignable:
        raise ValueError(f"proposal is not physically assignable: {check.reason}")
    if plan["project_finish"] != next(e.finish for e in entries if e.activity_id == case.objective_activity_id):
        raise ValueError("controlling finish disagrees with execution")


def approve(workspace: Workspace, actor: str) -> None:
    if not actor.strip() or workspace["proposal"] is None:
        raise ValueError("approval needs an actor and a calculated proposal")
    plan = workspace["proposal"]
    validate_plan(workspace, plan)
    current = workspace["approved_plan"]
    if plan["reference_plan_hash"] != (current["plan_hash"] if current else None):
        raise ValueError("proposal was calculated against another approved reference")
    if current:
        workspace["plan_history"].append(deepcopy(current))
    workspace["approved_plan"] = deepcopy(plan)
    workspace["approved_plan"].update(approved_by=actor, approved_at=now())
    workspace["proposal"] = None
