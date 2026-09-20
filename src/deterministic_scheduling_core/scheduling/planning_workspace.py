"""Bounded native workflow compiler, reusing PR #24's placements and exact checker.

Finite activity-mode combinations are enumerated; each graph is solved by CP-SAT.
This is not the final solver architecture or a structural Work-Method compiler.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, replace
from itertools import combinations, product
from math import comb, prod

import ortools
from ortools.sat.python import cp_model

from deterministic_scheduling_core.errors import SchedulingError
from deterministic_scheduling_core.project.planning_workspace import (
    POLICY, SCHEMA, GROUP_SCHEMA, STATUS_SCHEMA, Workspace, current_status_records,
    digest, now, state_hash, trusted_input, validate, validate_accepted_history, validate_group_allocation,
)
from deterministic_scheduling_core import resource_assignment_experiment as ra
from deterministic_scheduling_core.working_time_experiment import SUSPENDABLE, WorkCalendar


def _group_slots(project: dict, mode: dict) -> tuple[ra.RequirementSlot, ...]:
    """Anonymous compilation only, never planner-maintained identities."""
    groups = {g["id"]: (i, g) for i, g in enumerate(project.get("resource_groups", []))}
    slots = []
    for demand in mode.get("group_requirements", []):
        index, group = groups[demand["group_id"]]
        prefix = f"@group/{index}/"
        eligible = tuple(f"{prefix}{n}" for n in range(group["capacity"]))
        slots.extend(ra.RequirementSlot(f"{prefix}{n}", (prefix,), eligible) for n in range(demand["demand"]))
    return tuple(slots)


def _case(workspace: Workspace, selected: dict[str, str]) -> ra.ExperimentCase:
    project = workspace["project"]
    activities = []
    for activity in project["activities"]:
        mode = next(m for m in activity["modes"] if m["id"] == selected[activity["id"]])
        requirements = tuple(ra.RequirementSlot(r["id"], tuple(r["pool_ids"]), tuple(r["eligible_resource_ids"])) for r in mode.get("requirements", [])) + _group_slots(project, mode)
        activities.append(ra.ActivitySpec(
            activity["id"], activity["name"], mode["processing_ticks"], mode["calendar_id"],
            requirements, tuple(activity.get("predecessors", [])), activity.get("not_before", 0),
            mode.get("continuity", SUSPENDABLE),
        ))
    return ra.ExperimentCase(
        tuple(WorkCalendar(c["id"], tuple(tuple(w) for w in c["daily_windows"])) for c in project["calendars"]),
        tuple(ra.PhysicalResource(r["id"], tuple(r["capabilities"]), r["calendar_id"], 1) for r in project["resources"])
        + tuple(ra.PhysicalResource(f"@group/{i}/{n}", (f"@group/{i}/",), g["calendar_id"], 1)
                for i, g in enumerate(project.get("resource_groups", [])) for n in range(g["capacity"])),
        tuple(ra.AvailabilityException(r["resource_id"], r["start"], r["finish"], r["reason"]) for r in workspace["reports"] if r["status"] == "ACCEPTED"),
        tuple(activities), project["objective_activity_id"], project["horizon_ticks"],
    )


def _future_case(workspace: Workspace, selected: dict[str, str], states: dict[str, dict]) -> ra.ExperimentCase:
    """Compile only work that is still executable at or after status point."""
    project = workspace["project"]
    status_point = workspace["execution"]["status_point"]
    activities = []
    for activity in project["activities"]:
        record = states[activity["id"]]
        if record["execution_state"] == "COMPLETED":
            continue
        mode = next(mode for mode in activity["modes"] if mode["id"] == selected[activity["id"]])
        if record["execution_state"] == "IN_PROGRESS":
            accepted_mode = record["execution_context"]["mode"]
            for field in ("requirements", "group_requirements", "continuity"):
                if mode.get(field, [] if field != "continuity" else SUSPENDABLE) != accepted_mode.get(field, [] if field != "continuity" else SUSPENDABLE):
                    raise ValueError(f"{activity['id']}: begun mode {field} changed; correct the accepted assertion instead of reinterpreting begun work")
        named = []
        fixed = dict(record["named_assignments"]) if record["execution_state"] == "IN_PROGRESS" else {}
        for requirement in mode.get("requirements", []):
            eligible = [fixed[requirement["id"]]] if requirement["id"] in fixed else requirement["eligible_resource_ids"]
            named.append(ra.RequirementSlot(requirement["id"], tuple(requirement["pool_ids"]), tuple(eligible)))
        processing = record["remaining_processing_ticks"] if record["execution_state"] == "IN_PROGRESS" else mode["processing_ticks"]
        predecessors = tuple(
            predecessor for predecessor in activity.get("predecessors", [])
            if states[predecessor]["execution_state"] != "COMPLETED"
        )
        activities.append(ra.ActivitySpec(
            activity["id"], activity["name"], processing, mode["calendar_id"],
            tuple(named) + _group_slots(project, mode), predecessors,
            max(activity.get("not_before", 0), status_point),
            mode.get("continuity", SUSPENDABLE),
        ))
    if project["objective_activity_id"] not in {activity.id for activity in activities}:
        raise ValueError("the controlling activity is already COMPLETED; there is no future recovery to calculate")
    return ra.ExperimentCase(
        tuple(WorkCalendar(calendar["id"], tuple(tuple(window) for window in calendar["daily_windows"])) for calendar in project["calendars"]),
        tuple(ra.PhysicalResource(resource["id"], tuple(resource["capabilities"]), resource["calendar_id"], 1) for resource in project["resources"])
        + tuple(ra.PhysicalResource(f"@group/{index}/{unit}", (f"@group/{index}/",), group["calendar_id"], 1)
                for index, group in enumerate(project.get("resource_groups", [])) for unit in range(group["capacity"])),
        tuple(ra.AvailabilityException(report["resource_id"], report["start"], report["finish"], report["reason"])
              for report in workspace["reports"] if report["status"] == "ACCEPTED"),
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


def _group_placements(case: ra.ExperimentCase, activity: ra.ActivitySpec, approach: str):
    """Keep one anonymous set for all segments; quotient out within-crew permutations.

    This is the existing finite-placement compiler, with disjoint group sets as
    an additional input. No dates are repaired after solving. Anonymous sets
    carry capacity/continuity constraints but never preservation penalties.
    """
    named = tuple(r for r in activity.requirements if not r.id.startswith("@group/"))
    blocks = {}
    for r in activity.requirements[len(named):]:
        blocks.setdefault(r.pool_ids[0], []).append(r)
    count = prod(comb(len(rs[0].eligible_resource_ids), len(rs)) for rs in blocks.values())
    named_choices = ra._assignment_combinations(replace(activity, requirements=named), approach)
    if count * len(named_choices) > 64:
        raise ValueError("bounded group compiler supports at most 64 physical assignment/set combinations per activity-mode")
    group_choices = [tuple(combinations(rs[0].eligible_resource_ids, len(rs))) for rs in blocks.values()]
    candidates = []
    for named_assignment in named_choices:
        for sets in product(*group_choices):
            assignments = named_assignment + tuple(unit for units in sets for unit in units)
            eligible = ra._eligible_execution_slots(case, activity, approach, assignments)
            for start in range(activity.not_before, case.horizon + 1):
                periods = ra._periods_from_start(start, activity.processing_ticks, eligible, activity.continuity, case.horizon)
                if periods is not None:
                    candidates.append(ra.CandidatePlacement(start, periods[-1][1] if periods else start, periods, assignments))
    return tuple(candidates)


def _solve_case(case: ra.ExperimentCase, pooled: bool, approved: dict | None, grouped: bool = False,
                status_workspace: Workspace | None = None):
    model = cp_model.CpModel()
    starts, ends, choices = {}, {}, {}
    named_intervals = {resource.id: [] for resource in case.resources}
    pooled_intervals = []
    assignment_changes = []
    states = current_status_records(status_workspace) if status_workspace else {}
    groups = status_workspace["project"].get("resource_groups", []) if status_workspace else []
    group_intervals = {}
    # Historical group allocations are existential witnesses, never worker
    # records. Couple begun future choices to the same set across the boundary.
    for activity_id, record in states.items():
        if record["execution_state"] != "COMPLETED":
            continue
        context = record["execution_context"]
        past_groups = {g["id"]: g for g in context["resource_groups"]}
        for demand in context["mode"].get("group_requirements", []):
            gid, quantity = demand["group_id"], demand["demand"]
            capacity = past_groups[gid]["capacity"]
            if comb(capacity, quantity) > 64:
                raise ValueError("bounded historical group proof supports at most 64 allocation sets")
            literals = []
            for index, units in enumerate(combinations(range(capacity), quantity)):
                literal = model.new_bool_var(f"history_{activity_id}_{gid}_{index}")
                literals.append(literal)
                for unit in units:
                    for segment, (start, finish) in enumerate(record["actual_periods"]):
                        interval = model.new_optional_interval_var(start, finish - start, finish, literal,
                            f"history_{activity_id}_{gid}_{index}_{unit}_{segment}")
                        group_intervals.setdefault((gid, unit), []).append(interval)
            model.add_exactly_one(literals)
    reference = {}
    if approved:
        reference = {
            entry["activity_id"]: {**entry, "start": entry.get("forecast_start", entry["start"])}
            for entry in approved["entries"]
            if entry.get("forecast_start", entry.get("start")) is not None
        }
    for activity in case.activities:
        placements = (_group_placements if grouped else ra._candidate_placements)(case, activity, "C" if pooled else "B")
        record = states.get(activity.id)
        if record and record["execution_state"] == "IN_PROGRESS":
            if activity.continuity == "CONTINUOUS" and record["actual_periods"] and activity.processing_ticks:
                placements = tuple(p for p in placements if p.start == record["actual_periods"][-1][1])
            historical_groups = {g["id"]: g for g in record["execution_context"]["resource_groups"]}
            placements = tuple(p for p in placements if all(
                int(resource.rsplit("/", 1)[1]) < historical_groups[groups[int(req.id.split("/")[1])]["id"]]["capacity"]
                for req, resource in zip(activity.requirements, p.assignments) if req.id.startswith("@group/")))
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
                if not (grouped and requirement.id.startswith("@group/")) and requirement.id in old_assignments and old_assignments[requirement.id] != resource_id:
                    changes += 1
                for segment, (start, finish) in enumerate(placement.periods):
                    interval = model.new_optional_interval_var(start, finish - start, finish, literal,
                        f"use_{activity.id}_{index}_{requirement.id}_{segment}")
                    if resource_id is None:
                        pooled_intervals.append(interval)
                    else:
                        named_intervals[resource_id].append(interval)
                    if status_workspace and requirement.id.startswith("@group/"):
                        gid = groups[int(requirement.id.split("/")[1])]["id"]
                        unit = int(resource_id.rsplit("/", 1)[1])
                        group_intervals.setdefault((gid, unit), []).append(interval)
                if record and record["execution_state"] == "IN_PROGRESS" and requirement.id.startswith("@group/"):
                    gid = groups[int(requirement.id.split("/")[1])]["id"]
                    unit = int(resource_id.rsplit("/", 1)[1])
                    for segment, (start, finish) in enumerate(record["actual_periods"]):
                        interval = model.new_optional_interval_var(start, finish - start, finish, literal,
                            f"past_use_{activity.id}_{index}_{requirement.id}_{segment}")
                        group_intervals.setdefault((gid, unit), []).append(interval)
            assignment_changes.append(changes * literal)
        model.add_exactly_one(literals)
    for activity in case.activities:
        for predecessor in activity.predecessors:
            model.add(starts[activity.id] >= ends[predecessor])
    for intervals in named_intervals.values():
        if intervals:
            model.add_no_overlap(intervals)
    for intervals in group_intervals.values():
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
    timing_ids = [a["id"] for a in status_workspace["project"]["activities"]] if status_workspace else [a.id for a in case.activities]
    timing = sum((index + 1) * starts[activity_id] for index, activity_id in enumerate(timing_ids) if activity_id in starts)
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


def _status_entry(activity: dict, mode: dict, record: dict, future: ra.ScheduledEntry | None) -> dict:
    actual_periods = deepcopy(record["actual_periods"])
    forecast_periods = [list(period) for period in future.periods] if future else []
    forecast_start = future.start if future else None
    forecast_finish = future.finish if future else None
    if future:
        assignments = [list(pair) for pair in future.assignments if not pair[0].startswith("@group/")]
        group_demands = [[demand["group_id"], demand["demand"]] for demand in mode.get("group_requirements", [])]
    else:
        assignments, group_demands = [], []
    context_mode = record["execution_context"]["mode"] if record["execution_context"] else None
    actual_group_demands = (
        [[demand["group_id"], demand["demand"]] for demand in context_mode.get("group_requirements", [])]
        if context_mode else []
    )
    envelope = forecast_start if forecast_start is not None else (record["actual_finish"] if record["actual_finish"] is not None else record["actual_start"])
    return {
        "activity_id": activity["id"],
        "execution_state": record["execution_state"],
        "status_update_id": record["id"],
        "start": envelope,
        "finish": forecast_finish if forecast_finish is not None else envelope,
        "periods": forecast_periods,
        "assignments": assignments,
        "group_demands": group_demands,
        "actual_start": record["actual_start"],
        "actual_finish": record["actual_finish"],
        "actual_periods": actual_periods,
        "actual_assignments": deepcopy(record["named_assignments"]),
        "actual_group_demands": actual_group_demands,
        "forecast_start": forecast_start,
        "forecast_finish": forecast_finish,
        "forecast_periods": forecast_periods,
        "remaining_processing_ticks": record["remaining_processing_ticks"] if record["execution_state"] == "IN_PROGRESS" else (0 if record["execution_state"] == "COMPLETED" else mode["processing_ticks"]),
    }


def _propose_statused(workspace: Workspace) -> dict:
    states = validate_accepted_history(workspace, require_complete=True)
    activities = workspace["project"]["activities"]
    mode_options = []
    for activity in activities:
        record = states[activity["id"]]
        if record["execution_state"] == "COMPLETED":
            mode_options.append([record["execution_context"]["mode"]])
        elif record["execution_state"] == "IN_PROGRESS":
            matches = [mode for mode in activity["modes"] if mode["id"] == record["mode_id"]]
            if not matches:
                raise ValueError(f"{activity['id']}: its accepted begun mode is no longer authorised")
            mode_options.append(matches)
        else:
            mode_options.append(activity["modes"])
    if prod(len(options) for options in mode_options) > 16:
        raise ValueError("this POC supports at most 16 authorised activity-mode combinations")
    approved = workspace["approved_plan"]
    alternatives, candidates = [], []
    calls = 0
    for modes in product(*mode_options):
        selected = {activity["id"]: mode["id"] for activity, mode in zip(activities, modes)}
        case = _future_case(workspace, selected, states)
        pooled = _can_pool(case, workspace["project"].get("pool_riggers", False))
        result = _solve_case(case, pooled, approved, grouped=True, status_workspace=workspace)
        if result is None:
            alternatives.append({"modes": selected, "status": "INFEASIBLE"})
            continue
        future_entries, check, values, stage_calls = result
        calls += stage_calls
        mode_changes = sum(approved["selected_modes"].get(key) != value for key, value in selected.items()) if approved else 0
        objective = (values[0], mode_changes, values[1], values[2], values[3])
        alternatives.append({"modes": selected, "status": "OPTIMAL", "objective": list(objective)})
        candidates.append((objective, tuple(selected.values()), selected, future_entries, check, pooled))
    if not candidates:
        workspace["proposal"] = None
        raise SchedulingError("no executable future remainder within the declared horizon; accepted history, remaining estimates and prior approved plan are retained")
    objective, _, selected, future_entries, check, pooled = min(candidates, key=lambda candidate: (candidate[0], candidate[1]))
    future_by_id = {entry.activity_id: entry for entry in future_entries}
    entries = []
    for activity in activities:
        record = states[activity["id"]]
        mode = (record["execution_context"]["mode"] if record["execution_state"] == "COMPLETED"
                else next(mode for mode in activity["modes"] if mode["id"] == selected[activity["id"]]))
        entries.append(_status_entry(activity, mode, record, future_by_id.get(activity["id"])))
    plan = {
        "source_state_hash": state_hash(workspace),
        "source_snapshot": trusted_input(workspace),
        "reference_plan_hash": approved["plan_hash"] if approved else None,
        "selected_modes": selected,
        "entries": entries,
        "objective": list(objective),
        "project_finish": objective[0],
        "policy": POLICY,
        "pooled_riggers": pooled,
        "allocation_witness": [list(row) for row in check.allocation if not row[1].startswith("@group/")],
        "physical_status": check.exact_status,
        "history_status": "INDEPENDENTLY_VALIDATED",
        "status_point": workspace["execution"]["status_point"],
        "alternatives": alternatives,
        "group_proof": "accepted group history and future quantity are validated without exposing anonymous units; future periods also have an exact global fixed-unit feasibility proof",
        "solver": {
            "name": "CP-SAT", "version": ortools.__version__, "workers": 1, "seed": 0,
            "compiler": "native-workflow/status-2", "feasible_branch_solver_calls": calls,
            "proof": "all feasible permitted future mode combinations and objective stages proven optimal",
            "repeatability": "same-environment observation only; equivalent assignments need not be unique",
        },
    }
    import json
    plan = json.loads(json.dumps(plan))
    plan["plan_hash"] = _plan_hash(plan)
    validate_plan(workspace, plan)
    workspace["proposal"] = plan
    return plan


def propose(workspace: Workspace) -> dict:
    """Calculate from accepted inputs only; never overwrite the approved plan."""
    validate(workspace)
    if workspace["schema"] == STATUS_SCHEMA:
        return _propose_statused(workspace)
    activities = workspace["project"]["activities"]
    if prod(len(a["modes"]) for a in activities) > 16:
        raise ValueError("this POC supports at most 16 authorised activity-mode combinations")
    approved = workspace["approved_plan"]
    grouped = workspace["schema"] == GROUP_SCHEMA
    alternatives, candidates = [], []
    calls = 0
    for modes in product(*(a["modes"] for a in activities)):
        selected = {a["id"]: mode["id"] for a, mode in zip(activities, modes)}
        case = _case(workspace, selected)
        pooled = _can_pool(case, workspace["project"].get("pool_riggers", False))
        result = _solve_case(case, pooled, approved, grouped)
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
    if grouped:
        plan["solver"]["compiler"] = "native-workflow/groups-1"
        plan["group_proof"] = "aggregate productive-period capacity plus exact global fixed anonymous allocation; no real-person assignment"
        for entry, activity in zip(plan["entries"], activities):
            mode = next(m for m in activity["modes"] if m["id"] == selected[activity["id"]])
            entry["assignments"] = [pair for pair in entry["assignments"] if not pair[0].startswith("@group/")]
            entry["group_demands"] = [[r["group_id"], r["demand"]] for r in mode.get("group_requirements", [])]
        plan["allocation_witness"] = [row for row in plan["allocation_witness"] if not row[1].startswith("@group/")]
    # Store JSON-shaped values even before the first save/reopen.
    import json
    plan = json.loads(json.dumps(plan))
    plan["plan_hash"] = _plan_hash(plan)
    if grouped:
        validate_plan(workspace, plan)
    workspace["proposal"] = plan
    return plan


def validate_plan(workspace: Workspace, plan: dict) -> None:
    validate(workspace)
    if workspace["schema"] == STATUS_SCHEMA:
        _validate_status_plan(workspace, plan)
        return
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
    grouped = workspace["schema"] == GROUP_SCHEMA
    if grouped:
        _check_group_occupancy(workspace["project"], plan)
    entries = []
    for entry in plan["entries"]:
        periods = tuple(tuple(p) for p in entry["periods"])
        activity = case.activity_by_id[entry["activity_id"]]
        if any(type(tick) is not int for tick in (entry["start"], entry["finish"], *(tick for period in periods for tick in period))):
            raise ValueError("execution times must be integer 30-minute ticks")
        assignments = list(entry["assignments"])
        if grouped:
            assignments += [(r.id, None) for r in activity.requirements if r.id.startswith("@group/")]
        if sorted(slot for slot, _ in assignments) != sorted(r.id for r in activity.requirements):
            raise ValueError("assignments must cover each requirement slot exactly")
        submitted = dict(assignments)
        for requirement in activity.requirements:
            if submitted[requirement.id] is None and not ((grouped and requirement.id.startswith("@group/")) or (plan["pooled_riggers"] and requirement.pool_ids == ("RIGGER",) and _can_pool(case, True))):
                raise ValueError("only declared interchangeable groups or eligible legacy RIGGER slots may be deferred")
        if entry["start"] < activity.not_before or entry["finish"] > case.horizon:
            raise ValueError("plan lies outside native time boundaries")
        if periods and (entry["start"] != periods[0][0] or entry["finish"] != periods[-1][1]):
            raise ValueError("execution envelope disagrees with productive periods")
        if not periods and entry["start"] != entry["finish"]:
            raise ValueError("milestone has nonzero elapsed span")
        if any(start >= end for start, end in periods) or any(a[1] > b[0] for a, b in zip(periods, periods[1:])):
            raise ValueError("invalid execution periods")
        eligible = ra._eligible_execution_slots(case, activity, "C" if plan["pooled_riggers"] else "B",
                                                tuple(submitted[r.id] for r in activity.requirements))
        if periods != ra._periods_from_start(entry["start"], activity.processing_ticks, eligible, activity.continuity, case.horizon):
            raise ValueError("execution periods disagree with productive work and permitted calendar suspension")
        entries.append(ra.ScheduledEntry(entry["activity_id"], entry["start"], entry["finish"], periods,
                                        tuple(tuple(a) for a in assignments)))
    check = ra.check_fixed_schedule(case, tuple(entries))
    if not check.physically_assignable:
        raise ValueError(f"proposal is not physically assignable: {check.reason}")
    if plan["project_finish"] != next(e.finish for e in entries if e.activity_id == case.objective_activity_id):
        raise ValueError("controlling finish disagrees with execution")


def _validate_status_plan(workspace: Workspace, plan: dict) -> None:
    states = validate_accepted_history(workspace, require_complete=True)
    if plan["source_state_hash"] != state_hash(workspace) or plan["source_snapshot"] != trusted_input(workspace):
        raise ValueError("proposal is stale; recalculate from current accepted inputs")
    if plan["plan_hash"] != _plan_hash(plan):
        raise ValueError("stored proposal was edited; recalculate rather than editing solver output")
    project = workspace["project"]
    activities = project["activities"]
    ids = [activity["id"] for activity in activities]
    entries_by_id = {entry.get("activity_id"): entry for entry in plan["entries"]}
    if set(plan["selected_modes"]) != set(ids) or set(entries_by_id) != set(ids) or len(entries_by_id) != len(plan["entries"]):
        raise ValueError("plan does not cover the native project exactly")
    if plan.get("status_point") != workspace["execution"]["status_point"]:
        raise ValueError("plan status point disagrees with accepted project state")
    for activity in activities:
        selected = plan["selected_modes"][activity["id"]]
        record = states[activity["id"]]
        if record["execution_state"] != "COMPLETED" and selected not in {mode["id"] for mode in activity["modes"]}:
            raise ValueError("plan selected an unauthorised mode")
        if record["execution_state"] in {"IN_PROGRESS", "COMPLETED"} and selected != record["mode_id"]:
            raise ValueError(f"{activity['id']}: begun mode was silently changed")
    case = _future_case(workspace, plan["selected_modes"], states)
    status_point = workspace["execution"]["status_point"]
    submitted_future = []
    for activity in activities:
        activity_id = activity["id"]
        entry = entries_by_id[activity_id]
        record = states[activity_id]
        mode = (record["execution_context"]["mode"] if record["execution_state"] == "COMPLETED"
                else next(mode for mode in activity["modes"] if mode["id"] == plan["selected_modes"][activity_id]))
        context_mode = record["execution_context"]["mode"] if record["execution_context"] else None
        expected_actual_groups = [[demand["group_id"], demand["demand"]] for demand in context_mode.get("group_requirements", [])] if context_mode else []
        expected_actual = {
            "execution_state": record["execution_state"], "status_update_id": record["id"],
            "actual_start": record["actual_start"], "actual_finish": record["actual_finish"],
            "actual_periods": record["actual_periods"], "actual_assignments": record["named_assignments"],
            "actual_group_demands": expected_actual_groups,
        }
        for key, expected in expected_actual.items():
            if entry.get(key) != expected:
                raise ValueError(f"{activity_id}: plan rewrites accepted {key}")
        if record["execution_state"] == "COMPLETED":
            if entry.get("forecast_start") is not None or entry.get("forecast_finish") is not None or entry.get("forecast_periods") != [] or entry.get("periods") != [] or entry.get("assignments") != [] or entry.get("group_demands") != []:
                raise ValueError(f"{activity_id}: COMPLETED work cannot have a future remainder")
            if entry.get("remaining_processing_ticks") != 0:
                raise ValueError(f"{activity_id}: completed work must expose zero future processing")
            expected_envelope = record["actual_finish"] if record["actual_finish"] is not None else record["actual_start"]
            if entry.get("start") != expected_envelope or entry.get("finish") != expected_envelope:
                raise ValueError(f"{activity_id}: completed entry envelope disagrees with accepted history")
            continue
        spec = case.activity_by_id[activity_id]
        periods = entry.get("forecast_periods")
        if periods != entry.get("periods") or entry.get("start") != entry.get("forecast_start") or entry.get("finish") != entry.get("forecast_finish"):
            raise ValueError(f"{activity_id}: forecast fields disagree with the calculated entry")
        if not isinstance(periods, list) or any(not isinstance(period, list) or len(period) != 2 for period in periods):
            raise ValueError("forecast periods must be start/finish pairs")
        values = [entry.get("forecast_start"), entry.get("forecast_finish"), *(tick for period in periods for tick in period)]
        if any(type(value) is not int for value in values):
            raise ValueError("future execution times must be integer 30-minute ticks")
        if entry["forecast_start"] < status_point or entry["forecast_start"] < spec.not_before or entry["forecast_finish"] > case.horizon:
            raise ValueError("future execution lies outside the status/horizon boundaries")
        if (record["execution_state"] == "IN_PROGRESS" and spec.continuity == "CONTINUOUS"
                and record["actual_periods"] and spec.processing_ticks
                and entry["forecast_start"] != record["actual_periods"][-1][1]):
            raise ValueError(f"{activity_id}: continuous begun work cannot restart across an execution gap")
        if periods and (entry["forecast_start"] != periods[0][0] or entry["forecast_finish"] != periods[-1][1]):
            raise ValueError("future execution envelope disagrees with productive periods")
        if not periods and entry["forecast_start"] != entry["forecast_finish"]:
            raise ValueError("future milestone has nonzero elapsed span")
        assignments = entry.get("assignments")
        if not isinstance(assignments, list) or any(not isinstance(pair, list) or len(pair) != 2 for pair in assignments):
            raise ValueError("future assignments must be requirement/resource pairs")
        assignments = [tuple(pair) for pair in assignments]
        assignments += [(requirement.id, None) for requirement in spec.requirements if requirement.id.startswith("@group/")]
        if sorted(slot for slot, _ in assignments) != sorted(requirement.id for requirement in spec.requirements):
            raise ValueError("future assignments must cover every named and internal group slot exactly")
        submitted = dict(assignments)
        for requirement in spec.requirements:
            resource_id = submitted[requirement.id]
            if resource_id is None and not (requirement.id.startswith("@group/") or (plan["pooled_riggers"] and requirement.pool_ids == ("RIGGER",) and _can_pool(case, True))):
                raise ValueError("only a declared interchangeable group or eligible legacy RIGGER slot may be deferred")
        eligible = ra._eligible_execution_slots(case, spec, "C" if plan["pooled_riggers"] else "B", tuple(submitted[requirement.id] for requirement in spec.requirements))
        expected_periods = ra._periods_from_start(entry["forecast_start"], spec.processing_ticks, eligible, spec.continuity, case.horizon)
        if tuple(tuple(period) for period in periods) != expected_periods:
            raise ValueError("future periods disagree with remaining productive work and permitted calendar suspension")
        expected_remaining = record["remaining_processing_ticks"] if record["execution_state"] == "IN_PROGRESS" else mode["processing_ticks"]
        if entry.get("remaining_processing_ticks") != expected_remaining:
            raise ValueError(f"{activity_id}: future processing does not match the accepted remaining estimate")
        expected_groups = [[demand["group_id"], demand["demand"]] for demand in mode.get("group_requirements", [])]
        if entry.get("group_demands") != expected_groups:
            raise ValueError("submitted future group demands disagree with the begun/current authorised mode")
        submitted_future.append(ra.ScheduledEntry(activity_id, entry["forecast_start"], entry["forecast_finish"], tuple(tuple(period) for period in periods), tuple(assignments)))
    _check_status_group_occupancy(project, plan, states)
    check = ra.check_fixed_schedule(case, tuple(submitted_future))
    if not check.physically_assignable:
        raise ValueError(f"future proposal is not physically assignable: {check.reason}")
    _check_status_group_no_handover(workspace, plan, states)
    objective = next(entry for entry in submitted_future if entry.activity_id == case.objective_activity_id)
    if plan["project_finish"] != objective.finish or plan.get("physical_status") != ra.EXACT_FEASIBLE:
        raise ValueError("controlling finish or physical status disagrees with independent validation")


def _check_status_group_occupancy(project: dict, plan: dict, states: dict[str, dict]) -> None:
    groups = {group["id"]: group for group in project.get("resource_groups", [])}
    calendars = {calendar["id"]: WorkCalendar(calendar["id"], tuple(tuple(window) for window in calendar["daily_windows"])).slots(project["horizon_ticks"])
                 for calendar in project["calendars"]}
    occupancy: dict[tuple[str, int], int] = {}
    for entry in plan["entries"]:
        if states[entry["activity_id"]]["execution_state"] == "COMPLETED":
            continue
        for group_id, demand in entry["group_demands"]:
            if group_id not in groups:
                raise ValueError("future group requirement refers to an unknown group")
            for start, finish in entry["forecast_periods"]:
                for tick in range(start, finish):
                    if tick not in calendars[groups[group_id]["calendar_id"]]:
                        raise ValueError(f"group {group_id} executes outside its current calendar")
                    key = (group_id, tick)
                    occupancy[key] = occupancy.get(key, 0) + demand
                    if occupancy[key] > groups[group_id]["capacity"]:
                        raise ValueError(f"group {group_id} capacity exceeded at tick {tick}")


def _check_status_group_no_handover(workspace: Workspace, plan: dict, states: dict[str, dict]) -> None:
    """Prove a fixed anonymous unit set exists, without persisting unit identities."""
    current_groups = {group["id"]: group for group in workspace["project"].get("resource_groups", [])}
    entries = {entry["activity_id"]: entry for entry in plan["entries"]}
    tasks: dict[str, list[tuple[str, int, frozenset[int], int]]] = {}
    for activity in workspace["project"]["activities"]:
        activity_id = activity["id"]
        record = states[activity_id]
        entry = entries[activity_id]
        actual_demands = {group_id: demand for group_id, demand in entry["actual_group_demands"]}
        future_demands = {group_id: demand for group_id, demand in entry["group_demands"]}
        for group_id in set(actual_demands) | set(future_demands):
            if actual_demands.get(group_id, future_demands.get(group_id)) != future_demands.get(group_id, actual_demands.get(group_id)):
                raise ValueError(f"{activity_id}: begun group quantity changed across the status boundary")
            occupied = frozenset(
                tick for start, finish in entry["actual_periods"] + entry["forecast_periods"]
                for tick in range(start, finish)
            )
            if not occupied:
                continue
            historical_groups = {group["id"]: group for group in (record["execution_context"] or {}).get("resource_groups", [])}
            capacity = current_groups[group_id]["capacity"] if entry["forecast_periods"] else historical_groups[group_id]["capacity"]
            if entry["forecast_periods"] and group_id in historical_groups:
                capacity = min(capacity, historical_groups[group_id]["capacity"])
            demand = actual_demands[group_id] if group_id in actual_demands else future_demands[group_id]
            tasks.setdefault(group_id, []).append((activity_id, demand, occupied, capacity))
    validate_group_allocation(tasks, "accepted and future productive periods")


def _check_group_occupancy(project: dict, plan: dict) -> None:
    """Direct submitted-period audit, independent of anonymous compiler choices."""
    groups = {g["id"]: g for g in project["resource_groups"]}
    calendars = {c["id"]: WorkCalendar(c["id"], tuple(tuple(w) for w in c["daily_windows"])).slots(project["horizon_ticks"])
                 for c in project["calendars"]}
    activities = {a["id"]: a for a in project["activities"]}
    occupancy = {}
    for entry in plan["entries"]:
        a = activities[entry["activity_id"]]
        mode = next(m for m in a["modes"] if m["id"] == plan["selected_modes"][a["id"]])
        expected = [[r["group_id"], r["demand"]] for r in mode.get("group_requirements", [])]
        submitted = entry.get("group_demands")
        if (not isinstance(submitted, list) or any(not isinstance(row, list) or len(row) != 2
                or not isinstance(row[0], str) or type(row[1]) is not int for row in submitted)
                or submitted != expected):
            raise ValueError("submitted group demands disagree with authorised mode requirements")
        for gid, demand in expected:
            for start, finish in entry["periods"]:
                if type(start) is not int or type(finish) is not int or not 0 <= start < finish <= project["horizon_ticks"]:
                    raise ValueError("invalid group productive periods")
                for tick in range(start, finish):
                    if tick not in calendars[groups[gid]["calendar_id"]]:
                        raise ValueError(f"group {gid} executes outside its calendar")
                    key = (gid, tick)
                    occupancy[key] = occupancy.get(key, 0) + demand
                    if occupancy[key] > groups[gid]["capacity"]:
                        raise ValueError(f"group {gid} capacity exceeded at tick {tick}")


def validate_stored_plans(workspace: Workspace) -> None:
    """Validate persisted output against its own inputs, never optimise or rebase.

    Integrity is independent of whether current inputs still match. Approval
    provenance is retained; the existing hash deliberately excludes its metadata.
    """
    if not isinstance(workspace["plan_history"], list):
        raise ValueError("stored plan_history must be a list")
    records = [("approved_plan", workspace["approved_plan"]), ("proposal", workspace["proposal"])]
    records.extend((f"plan_history[{index}]", plan) for index, plan in enumerate(workspace["plan_history"]))
    for label, plan in records:
        if plan is None and label in {"approved_plan", "proposal"}:
            continue
        try:
            if not isinstance(plan, dict):
                raise ValueError("plan must be an object")
            for key, kind in {"source_snapshot": dict, "source_state_hash": str, "plan_hash": str,
                              "selected_modes": dict, "entries": list, "alternatives": list,
                              "allocation_witness": list, "objective": list, "solver": dict,
                              "physical_status": str, "pooled_riggers": bool}.items():
                if not isinstance(plan[key], kind):
                    raise ValueError(f"{key} has an invalid shape")
            snapshot = plan["source_snapshot"]
            historical = {"schema": snapshot.get("workspace_schema", SCHEMA), "project": snapshot["project"], "reports": snapshot["accepted_reports"],
                          "approved_plan": None, "proposal": None, "plan_history": []}
            if historical["schema"] == STATUS_SCHEMA:
                historical["execution"] = {
                    "status_point": snapshot["execution"]["status_point"],
                    "updates": snapshot["execution"]["accepted_updates"],
                }
            validate_plan(historical, plan)
            if plan["policy"] != POLICY or not plan["objective"] or plan["objective"][0] != plan["project_finish"]:
                raise ValueError("policy or objective finish disagrees with the stored plan")
            if plan["physical_status"] != ra.EXACT_FEASIBLE:
                raise ValueError("physical status disagrees with the successful physical check")
            # Validate the displayed deferred-allocation witness as submitted too.
            witnessed = deepcopy(plan)
            witness = {(a, slot): resource for a, slot, resource in plan["allocation_witness"]}
            expected = {(e["activity_id"], slot) for e in plan["entries"] for slot, _ in e["assignments"]}
            if set(witness) != expected or len(witness) != len(plan["allocation_witness"]):
                raise ValueError("allocation witness must cover every slot exactly")
            for entry in witnessed["entries"]:
                for assignment in entry["assignments"]:
                    resource = witness[(entry["activity_id"], assignment[0])]
                    if resource is None or assignment[1] not in (None, resource):
                        raise ValueError("allocation witness contradicts a named assignment")
                    assignment[1] = resource
            if historical["schema"] == STATUS_SCHEMA:
                historical_states = current_status_records(historical, require_complete=True)
                witness_case = _future_case(historical, plan["selected_modes"], historical_states)
                witness_entries = tuple(
                    ra.ScheduledEntry(e["activity_id"], e["forecast_start"], e["forecast_finish"],
                                      tuple(tuple(p) for p in e["forecast_periods"]), tuple(tuple(a) for a in e["assignments"])
                                      + tuple((r.id, None) for r in witness_case.activity_by_id[e["activity_id"]].requirements if r.id.startswith("@group/")))
                    for e in witnessed["entries"] if e["activity_id"] in witness_case.activity_by_id
                )
            else:
                witness_case = _case(historical, plan["selected_modes"])
                witness_entries = tuple(ra.ScheduledEntry(e["activity_id"], e["start"], e["finish"],
                                        tuple(tuple(p) for p in e["periods"]), tuple(tuple(a) for a in e["assignments"])
                                        + tuple((r.id, None) for r in witness_case.activity_by_id[e["activity_id"]].requirements
                                                if historical["schema"] == GROUP_SCHEMA and r.id.startswith("@group/")))
                                        for e in witnessed["entries"])
            witness_check = ra.check_fixed_schedule(witness_case, witness_entries)
            if not witness_check.physically_assignable:
                raise ValueError(f"invalid allocation witness: {witness_check.reason}")
            for alternative in plan["alternatives"]:
                if not isinstance(alternative["modes"], dict) or alternative["status"] not in {"OPTIMAL", "INFEASIBLE"}:
                    raise ValueError("invalid evaluated alternative")
                if alternative["status"] == "OPTIMAL" and (not isinstance(alternative["objective"], list) or not alternative["objective"] or type(alternative["objective"][0]) is not int):
                    raise ValueError("invalid alternative objective")
            if label != "proposal" and (not isinstance(plan["approved_by"], str) or not plan["approved_by"].strip() or not isinstance(plan["approved_at"], str) or not plan["approved_at"]):
                raise ValueError("approval actor and timestamp are required")
        except (AttributeError, IndexError, KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"stored {label}: {exc}") from exc


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
