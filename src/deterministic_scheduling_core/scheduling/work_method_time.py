"""Joint authorised structure, productive placements and selective allocation.

This owns a bounded future-only composition path. Existing elapsed scheduling and
accepted-progress workspaces remain unchanged. Controls live outside this module.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from math import prod
from time import perf_counter

import ortools
from ortools.sat.python import cp_model

from deterministic_scheduling_core import resource_assignment_experiment as ra
from deterministic_scheduling_core.errors import SchedulingError
from deterministic_scheduling_core.project.model import WorkPackage
from deterministic_scheduling_core.project.planning_workspace import digest, validate as validate_workspace
from deterministic_scheduling_core.project.work_method_time import (
    WorkMethodTimeProject, from_document, input_hash, materialise, membership,
    method_selections, structural_view, to_document,
)
from deterministic_scheduling_core.resource_allocation_repair_experiment import check_allocation
from .engine import validate_project
from .planning_workspace import _can_pool, _case, _group_placements

PLAN_SCHEMA = "pm-native-work-method-time-plan/0"
POLICY = "finish-global-start-timing-declared-methods-declared-modes-canonical-placement/0"


@dataclass(frozen=True)
class WorkMethodTimeResult:
    plan: dict
    metrics: dict


def validate_problem(problem: WorkMethodTimeProject) -> None:
    """Use the existing two native validators; reject unsupported composition.

    Enumerating graph projections here checks admission only. The candidate does
    not solve or rank those graphs separately. All definitions, including inactive
    methods, are validated; infeasible availability is not malformed structure.
    """
    if not isinstance(problem, WorkMethodTimeProject):
        raise ValueError("expected WorkMethodTimeProject, not a statused workspace")
    from_document(to_document(problem))
    source = problem.project
    if not isinstance(source.get("activities"), list) or not 1 <= len(source["activities"]) <= 32:
        raise ValueError("bounded composition requires 1..32 declared activities")
    if type(source.get("horizon_ticks")) is not int or not 1 <= source["horizon_ticks"] <= 480:
        raise ValueError("bounded composition requires a 1..480 tick horizon")
    if any(not isinstance(p, WorkPackage) for p in problem.work_packages):
        raise ValueError("structure must use native WorkPackage definitions")
    if prod(len(p.methods) for p in problem.work_packages) > 16:
        raise ValueError("bounded admission supports at most 16 authorised structures")
    for package in problem.work_packages:
        if not isinstance(package.id, str) or not package.id.strip():
            raise ValueError("nonempty work-package ID required")
        for method in package.methods:
            if not isinstance(method.id, str) or not method.id.strip():
                raise ValueError("nonempty execution-method ID required")
    validate_project(structural_view(problem))
    for selected in method_selections(problem):
        validate_workspace(materialise(problem, selected))


def _mode_cases(problem: WorkMethodTimeProject):
    """Reuse native productive compilation, with no fixed-method solve."""
    source = problem.project
    union_workspace = {"project": source, "reports": list(problem.reports)}
    first = {a["id"]: a["modes"][0]["id"] for a in source["activities"]}
    environment = _case(union_workspace, first)
    specs = {}
    for activity in source["activities"]:
        for mode in activity["modes"]:
            selected = {**first, activity["id"]: mode["id"]}
            specs[activity["id"], mode["id"]] = _case(union_workspace, selected).activity_by_id[activity["id"]]
    # Interchangeability must hold across every possible mode, not only a guessed
    # selected branch. Group quantities use the existing disjoint group compiler.
    pool_case = replace(environment, activities=tuple(specs.values()))
    pooled = _can_pool(pool_case, source.get("pool_riggers", False))
    return environment, specs, pooled


def policy_key(problem: WorkMethodTimeProject, selected_methods: dict,
               selected_modes: dict, objective) -> tuple:
    """Comparable policy, independent of inactive-method placeholders in controls."""
    methods = tuple(next(i for i, m in enumerate(p.methods) if m.id == selected_methods[p.id])
                    for p in problem.work_packages)
    modes = tuple(next(i + 1 for i, m in enumerate(a["modes"]) if m["id"] == selected_modes[a["id"]])
                  if a["id"] in selected_modes else 0 for a in problem.project["activities"])
    return tuple(objective), methods, modes


def _hash_plan(plan: dict) -> str:
    return digest({key: value for key, value in plan.items() if key != "plan_hash"})


def _validate_physics(problem: WorkMethodTimeProject, plan: dict):
    selected_methods, selected_modes = plan["selected_methods"], plan["selected_modes"]
    workspace = materialise(problem, selected_methods)
    active = {a["id"]: a for a in workspace["project"]["activities"]}
    if not isinstance(selected_modes, dict) or set(selected_modes) != set(active):
        raise ValueError("selected modes must cover exactly the active structure")
    for aid, mode_id in selected_modes.items():
        if mode_id not in {m["id"] for m in active[aid]["modes"]}:
            raise ValueError(f"{aid}: unauthorised activity mode")
    case = _case(workspace, selected_modes)
    _, _, pooled = _mode_cases(problem)
    if type(plan["pooled_riggers"]) is not bool or plan["pooled_riggers"] != pooled:
        raise ValueError("incorrect selective resource boundary")
    entries = plan["entries"]
    if not isinstance(entries, list) or len(entries) != len(active) or {
        e["activity_id"] for e in entries
    } != set(active):
        raise ValueError("entries must cover exactly the selected method activities")
    witness = {}
    for row in plan["allocation_witness"]:
        if not isinstance(row, list) or len(row) != 3 or not all(isinstance(v, str) for v in row):
            raise ValueError("invalid named allocation witness")
        key = row[0], row[1]
        if key in witness:
            raise ValueError("duplicate allocation witness slot")
        witness[key] = row[2]
    expected_named = {(a.id, r.id) for a in case.activities for r in a.requirements
                      if not r.id.startswith("@group/")}
    if set(witness) != expected_named:
        raise ValueError("named witness must cover exactly the active named requirements")
    members = membership(problem)
    raw = []
    for entry in entries:
        if set(entry) != {"activity_id", "mode_id", "work_package_id", "method_id",
                          "start", "finish", "periods", "assignments", "group_demands"}:
            raise ValueError("unsupported plan entry fields")
        aid = entry["activity_id"]
        if (entry["mode_id"] != selected_modes[aid]
                or (entry["work_package_id"], entry["method_id"]) != members.get(aid, (None, None))):
            raise ValueError("entry has incorrect mode/structure ownership")
        mode = next(m for m in active[aid]["modes"] if m["id"] == selected_modes[aid])
        expected_demands = [[d["group_id"], d["demand"]] for d in mode.get("group_requirements", [])]
        if entry["group_demands"] != expected_demands:
            raise ValueError("incorrect native group quantities")
        spec = case.activity_by_id[aid]
        named = tuple(r for r in spec.requirements if not r.id.startswith("@group/"))
        assignments = dict(entry["assignments"])
        if len(assignments) != len(entry["assignments"]) or set(assignments) != {r.id for r in named}:
            raise ValueError("incorrect named requirement coverage")
        for requirement in named:
            rid = assignments[requirement.id]
            deferred = pooled and requirement.pool_ids == ("RIGGER",)
            if deferred != (rid is None):
                raise ValueError("only verified interchangeable riggers may defer identity")
            if rid is not None and rid != witness[aid, requirement.id]:
                raise ValueError("submitted allocation and witness disagree")
        raw.append(ra.ScheduledEntry(aid, entry["start"], entry["finish"],
                                    tuple(tuple(p) for p in entry["periods"]),
                                    tuple((r.id, None if r.id.startswith("@group/") else witness[aid, r.id])
                                          for r in spec.requirements)))
    check = check_allocation(case, tuple(raw))
    if check.status != ra.EXACT_FEASIBLE:
        raise ValueError(f"independent physical validation failed: {check.reason}")
    # Cross-check the independently allocated group units with the older checker.
    allocated = {(aid, slot): rid for aid, slot, rid in check.witness}
    explicit = tuple(replace(e, assignments=tuple((slot, allocated[e.activity_id, slot])
                                                  for slot, _ in e.assignments)) for e in raw)
    legacy = ra.check_fixed_schedule(case, explicit)
    if not legacy.physically_assignable:
        raise ValueError(f"existing physical checker rejected result: {legacy.reason}")
    weights = {a["id"]: i + 1 for i, a in enumerate(problem.project["activities"])}
    by_id = {e.activity_id: e for e in raw}
    objective = [by_id[case.objective_activity_id].finish,
                 sum(weights[e.activity_id] * e.start for e in raw)]
    if plan["objective"] != objective:
        raise ValueError("incorrect finish/global timing objective")
    return check


def validate_plan(problem: WorkMethodTimeProject, plan: dict) -> str:
    """Validate structure, accounting and executability without solving a schedule.

    A hash is identity/integrity evidence, not authentication or an independent
    optimality certificate. Optimality is reported by the producing solver stages.
    """
    validate_problem(problem)
    if not isinstance(plan, dict) or set(plan) != {
        "schema", "input_hash", "policy", "selected_methods", "selected_modes", "entries",
        "objective", "pooled_riggers", "allocation_witness", "physical_status", "solver", "plan_hash"
    } or plan["schema"] != PLAN_SCHEMA:
        raise ValueError("unsupported composition plan")
    if plan["input_hash"] != input_hash(problem) or plan["policy"] != POLICY:
        raise ValueError("plan belongs to different inputs or policy")
    if plan["plan_hash"] != _hash_plan(plan):
        raise ValueError("composition plan hash mismatch")
    if plan["physical_status"] != ra.EXACT_FEASIBLE:
        raise ValueError("plan does not claim a physical witness")
    _validate_physics(problem, plan)
    return ra.EXACT_FEASIBLE


def schedule_work_method_time(problem: WorkMethodTimeProject) -> WorkMethodTimeResult:
    """Calculate one joint structural/productive plan without mutating its input."""
    started = perf_counter()
    problem = deepcopy(problem)
    validate_problem(problem)
    environment, specs, pooled = _mode_cases(problem)
    model = cp_model.CpModel()
    source = problem.project
    members = membership(problem)
    methods = {(p.id, m.id): model.new_bool_var(f"method_{i}_{j}")
               for i, p in enumerate(problem.work_packages) for j, m in enumerate(p.methods)}
    for package in problem.work_packages:
        model.add_exactly_one([methods[package.id, m.id] for m in package.methods])
    starts, ends, presence, mode_vars, choices = {}, {}, {}, {}, {}
    named_intervals = {r.id: [] for r in environment.resources}
    pooled_intervals = []
    placement_count = 0
    for ai, activity in enumerate(source["activities"]):
        aid = activity["id"]
        present = methods[members[aid]] if aid in members else model.new_constant(1)
        presence[aid] = present
        starts[aid] = model.new_int_var(0, environment.horizon, f"start_{ai}")
        ends[aid] = model.new_int_var(0, environment.horizon, f"end_{ai}")
        choices[aid] = []
        for mi, mode in enumerate(activity["modes"]):
            mid = mode["id"]
            mode_var = model.new_bool_var(f"mode_{ai}_{mi}")
            mode_vars[aid, mid] = mode_var
            spec = specs[aid, mid]
            placements = _group_placements(environment, spec, "C" if pooled else "B")
            placements = tuple(sorted(placements, key=lambda p: (
                p.start, p.finish, p.periods, tuple("" if r is None else r for r in p.assignments))))
            placement_count += len(placements)
            if placement_count > 20000:
                raise ValueError("bounded composition supports at most 20000 placement alternatives")
            literals = []
            for pi, placement in enumerate(placements):
                literal = model.new_bool_var(f"place_{ai}_{mi}_{pi}")
                literals.append(literal)
                choices[aid].append((literal, mid, placement))
                for ri, (requirement, rid) in enumerate(zip(spec.requirements, placement.assignments)):
                    for si, (start, finish) in enumerate(placement.periods):
                        interval = model.new_optional_interval_var(start, finish - start, finish, literal,
                                                                   f"use_{ai}_{mi}_{pi}_{ri}_{si}")
                        (pooled_intervals if rid is None else named_intervals[rid]).append(interval)
            # Empty local availability disables only this mode/method.
            model.add(sum(literals) == mode_var)
        model.add(sum(mode_vars[aid, m["id"]] for m in activity["modes"]) == present)
        model.add(starts[aid] == sum(p.start * lit for lit, _, p in choices[aid]))
        model.add(ends[aid] == sum(p.finish * lit for lit, _, p in choices[aid]))
    for activity in source["activities"]:
        for predecessor in activity.get("predecessors", []):
            model.add(starts[activity["id"]] >= ends[predecessor]).only_enforce_if(presence[activity["id"]])
    by_id = {a["id"]: a for a in source["activities"]}
    packages = {p.id: p for p in problem.work_packages}
    for package in problem.work_packages:
        for method in package.methods:
            ids = set(method.activity_ids)
            roots = [aid for aid in method.activity_ids if not set(by_id[aid].get("predecessors", [])) & ids]
            for predecessor in package.predecessors:
                for prior_method in packages[predecessor].methods:
                    for root in roots:
                        model.add(starts[root] >= ends[prior_method.completion_activity_id]).only_enforce_if(
                            [methods[package.id, method.id], methods[predecessor, prior_method.id]])
    for intervals in named_intervals.values():
        if intervals:
            model.add_no_overlap(intervals)
    if pooled_intervals:
        model.add_cumulative(pooled_intervals, [1] * len(pooled_intervals), 2)
    timing = sum((i + 1) * starts[a["id"]] for i, a in enumerate(source["activities"]))
    stages = [("finish", ends[source["objective_activity_id"]]), ("global_start_timing", timing)]
    stages.extend((f"method:{p.id}", sum(i * methods[p.id, m.id] for i, m in enumerate(p.methods)))
                  for p in problem.work_packages)
    stages.extend((f"mode:{a['id']}", sum((i + 1) * mode_vars[a["id"], m["id"]]
                                         for i, m in enumerate(a["modes"]))) for a in source["activities"])
    stages.extend((f"placement:{a['id']}", sum((i + 1) * lit for i, (lit, _, _) in enumerate(choices[a["id"]])))
                  for a in source["activities"])
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    built = perf_counter()
    proof = []
    for name, expression in stages:
        model.minimize(expression)
        status = solver.solve(model)
        if status == cp_model.INFEASIBLE:
            raise SchedulingError("INFEASIBLE: no executable authorised structure within the declared horizon")
        if status != cp_model.OPTIMAL:
            raise SchedulingError(f"{solver.status_name(status)}: {name} is not proven optimal; no authoritative plan returned")
        value = solver.value(expression)
        proof.append({"stage": name, "value": value, "status": "OPTIMAL"})
        model.add(expression == value)
    solved = perf_counter()
    selected_methods = {p.id: next(m.id for m in p.methods if solver.value(methods[p.id, m.id]))
                        for p in problem.work_packages}
    selected_modes, entries, raw = {}, [], []
    for activity in source["activities"]:
        aid = activity["id"]
        selected = [(mid, placement) for lit, mid, placement in choices[aid] if solver.value(lit)]
        if not selected:
            continue
        mid, placement = selected[0]
        selected_modes[aid] = mid
        spec = specs[aid, mid]
        mode = next(m for m in activity["modes"] if m["id"] == mid)
        assignments = tuple((r.id, rid) for r, rid in zip(spec.requirements, placement.assignments))
        raw.append(ra.ScheduledEntry(aid, placement.start, placement.finish, placement.periods, assignments))
        owner = members.get(aid, (None, None))
        entries.append({"activity_id": aid, "mode_id": mid, "work_package_id": owner[0], "method_id": owner[1],
                        "start": placement.start, "finish": placement.finish,
                        "periods": [list(p) for p in placement.periods],
                        "assignments": [[slot, rid] for slot, rid in assignments if not slot.startswith("@group/")],
                        "group_demands": [[d["group_id"], d["demand"]] for d in mode.get("group_requirements", [])]})
    fixed_case = _case(materialise(problem, selected_methods), selected_modes)
    check = check_allocation(fixed_case, tuple(raw))
    if check.status != ra.EXACT_FEASIBLE:
        raise SchedulingError(f"joint result failed independent allocation: {check.reason}")
    plan = {"schema": PLAN_SCHEMA, "input_hash": input_hash(problem), "policy": POLICY,
            "selected_methods": selected_methods, "selected_modes": selected_modes, "entries": entries,
            "objective": [proof[0]["value"], proof[1]["value"]], "pooled_riggers": pooled,
            "allocation_witness": [list(row) for row in check.witness if not row[1].startswith("@group/")],
            "physical_status": check.status,
            "solver": {"name": "CP-SAT", "version": ortools.__version__, "workers": 1, "seed": 0,
                       "compiler": "native-work-method-time/0", "stages": proof,
                       "repeatability": "canonical stage ordering in the same declared environment; not a cross-version guarantee"}}
    plan["plan_hash"] = _hash_plan(plan)
    validate_plan(problem, plan)
    return WorkMethodTimeResult(plan, {
        "model_builds": 1, "solver_calls": len(stages), "placement_alternatives": placement_count,
        "variables": len(model.proto.variables), "constraints": len(model.proto.constraints),
        "build_ms": (built - started) * 1000, "solve_ms": (solved - built) * 1000,
        "end_to_end_ms": (perf_counter() - started) * 1000,
    })
