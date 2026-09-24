"""Headless Work-Method/productive-time convergence evidence and fixed controls.

The candidate lives in scheduling.work_method_time. This module owns synthetic
fixtures and an independently constructed, time-indexed explicit-assignment
control. No expected finish or solved reference is an input to the candidate.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, replace
from itertools import product
import json
from pathlib import Path
from time import perf_counter

from ortools.sat.python import cp_model

from deterministic_scheduling_core import resource_assignment_experiment as ra
from deterministic_scheduling_core.errors import SchedulingError
from deterministic_scheduling_core.project.model import ExecutionMethod, WorkPackage
from deterministic_scheduling_core.project.work_method_time import (
    WorkMethodTimeProject, input_hash, materialise, method_selections, to_document,
)
from deterministic_scheduling_core.resource_allocation_repair_experiment import check_allocation
from deterministic_scheduling_core.scheduling.planning_workspace import _case
from deterministic_scheduling_core.scheduling.work_method_time import (
    policy_key, schedule_work_method_time, validate_plan, validate_problem,
)


def _mode(mid, work, requirements=(), groups=(), calendar="DAY", continuity="SUSPENDABLE_AT_AVAILABILITY_GAPS"):
    return {"id": mid, "processing_ticks": work, "calendar_id": calendar,
            "continuity": continuity, "requirements": list(requirements), "group_requirements": list(groups)}


def _slot(sid, capability, eligible):
    return {"id": sid, "pool_ids": [capability], "eligible_resource_ids": list(eligible)}


def build_problem() -> WorkMethodTimeProject:
    """Thirteen declared activities, two structures, three active mode branches."""
    mech = _slot("MECH", "MECH", ("M1", "M2"))
    specialist = _slot("SPECIALIST", "SPECIALIST", ("M2",))
    crane = _slot("CRANE", "CRANE", ("C04",))
    inspect = _slot("INSPECT", "INSPECT", ("M2",))
    rig = {"group_id": "RIGGING", "demand": 1}
    activities = [
        {"id": "RELEASE", "name": "Release workfront", "not_before": 20,
         "modes": [_mode("FIXED", 0, calendar="ALWAYS")]},
        {"id": "L1", "name": "Lift complete component", "modes": [
            _mode("NORMAL", 6, (mech, crane)), _mode("FAST", 4, (mech, specialist, crane))]},
        {"id": "L2", "name": "Prepare lifted component", "predecessors": ["L1"],
         "modes": [_mode("FIXED", 1, (mech,))]},
        {"id": "S1", "name": "Separate component", "modes": [_mode("FIXED", 4, (mech,))]},
        {"id": "S2", "name": "Remove segments", "predecessors": ["S1"],
         "modes": [_mode("FIXED", 5, (mech,))]},
        {"id": "P1", "name": "Parallel specialist verification", "modes": [_mode("FIXED", 4, (specialist,))]},
        {"id": "R1", "name": "First rigging preparation", "modes": [_mode("FIXED", 2, groups=(rig,))]},
        {"id": "R2", "name": "Second rigging preparation", "modes": [_mode("FIXED", 2, groups=(rig,))]},
        {"id": "R_END", "name": "Rigging preparations ready", "predecessors": ["R1", "R2"],
         "modes": [_mode("FIXED", 0, calendar="ALWAYS")]},
        {"id": "C_SERVICE", "name": "Crane-only check during suspension", "not_before": 24,
         "modes": [_mode("FIXED", 1, (crane,), calendar="ALWAYS")]},
        {"id": "SUPPORT_END", "name": "Support work complete", "predecessors": ["P1", "R_END", "C_SERVICE"],
         "modes": [_mode("FIXED", 0, calendar="ALWAYS")]},
        {"id": "QA", "name": "Uninterrupted quality check", "modes": [_mode("FIXED", 2, (inspect,), continuity="CONTINUOUS")]},
        {"id": "DONE", "name": "Return to service", "predecessors": ["QA"],
         "modes": [_mode("FIXED", 0, calendar="ALWAYS")]},
    ]
    project = {"id": "wm-time-demo", "name": "Headless structural productive plan", "horizon_ticks": 96,
               "calendars": [{"id": "DAY", "daily_windows": [[14, 24], [25, 34]]},
                             {"id": "ALWAYS", "daily_windows": [[0, 48]]}],
               "resources": [{"id": "M1", "capabilities": ["MECH"], "calendar_id": "DAY"},
                             {"id": "M2", "capabilities": ["MECH", "SPECIALIST", "INSPECT"], "calendar_id": "DAY"},
                             {"id": "C04", "capabilities": ["CRANE"], "calendar_id": "ALWAYS"}],
               "resource_groups": [{"id": "RIGGING", "name": "Interchangeable rigging capacity", "capacity": 2,
                                    "calendar_id": "DAY", "disjoint": True, "interchangeable": True}],
               "activities": activities, "objective_activity_id": "DONE", "pool_riggers": False}
    packages = (
        WorkPackage("RELEASE_WORK", "Release", (ExecutionMethod("FIXED", "Release", ("RELEASE",), "RELEASE"),)),
        WorkPackage("REMOVE", "Required component removal", (
            ExecutionMethod("LIFT", "Whole-component lift", ("L1", "L2"), "L2"),
            ExecutionMethod("SEGMENTED", "Segmented removal", ("S1", "S2"), "S2")), ("RELEASE_WORK",)),
        WorkPackage("SUPPORT", "Required support work", (ExecutionMethod("FIXED", "Support",
            ("P1", "R1", "R2", "R_END", "C_SERVICE", "SUPPORT_END"), "SUPPORT_END"),), ("RELEASE_WORK",)),
        WorkPackage("HANDOFF", "Required handoff", (ExecutionMethod("FIXED", "Quality and handoff",
            ("QA", "DONE"), "DONE"),), ("REMOVE", "SUPPORT")),
    )
    return WorkMethodTimeProject(project, packages)


def crane_outage(problem: WorkMethodTimeProject, *, accepted: bool) -> WorkMethodTimeProject:
    report = {"id": "E1", "resource_id": "C04", "start": 20, "finish": 29,
              "reason": "Synthetic crane unavailability", "reported_by": "operations",
              "status": "ACCEPTED" if accepted else "REPORTED",
              "accepted_by": "planner" if accepted else None}
    return replace(problem, project=deepcopy(problem.project), reports=(report,))


def _fixed_network(case, weights):
    """Separate control: explicit B placements and per-tick resource inequalities.

    No optional-method constraints or candidate solver are reused. The existing
    calendar/placement generator is shared; the tiny Python enumeration in tests
    supplies a stronger independent end-to-end oracle for its own small profile.
    """
    model = cp_model.CpModel()
    choices, starts, finishes = {}, {}, {}
    occupancy = {}
    for ai, activity in enumerate(case.activities):
        options = ra._candidate_placements(case, activity, "B")
        if not options:
            return None, 0
        choices[activity.id] = []
        for pi, placement in enumerate(options):
            literal = model.new_bool_var(f"fixed_{ai}_{pi}")
            choices[activity.id].append((literal, placement))
            for rid in placement.assignments:
                for start, finish in placement.periods:
                    for tick in range(start, finish):
                        occupancy.setdefault((rid, tick), []).append(literal)
        model.add_exactly_one([literal for literal, _ in choices[activity.id]])
        starts[activity.id] = sum(lit * p.start for lit, p in choices[activity.id])
        finishes[activity.id] = sum(lit * p.finish for lit, p in choices[activity.id])
    for activity in case.activities:
        for predecessor in activity.predecessors:
            model.add(starts[activity.id] >= finishes[predecessor])
    for literals in occupancy.values():
        model.add(sum(literals) <= 1)
    timing = sum(weights[aid] * start for aid, start in starts.items())
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    values = []
    for expression in (finishes[case.objective_activity_id], timing):
        model.minimize(expression)
        status = solver.solve(model)
        if status == cp_model.INFEASIBLE:
            return None, len(values) + 1
        if status != cp_model.OPTIMAL:
            raise SchedulingError(f"fixed control has no proven optimum: {solver.status_name(status)}")
        value = solver.value(expression)
        values.append(value)
        model.add(expression == value)
    entries = []
    for activity in case.activities:
        placement = next(p for lit, p in choices[activity.id] if solver.value(lit))
        entries.append(ra.ScheduledEntry(activity.id, placement.start, placement.finish, placement.periods,
                                         tuple((r.id, rid) for r, rid in zip(activity.requirements, placement.assignments))))
    check = check_allocation(case, tuple(entries))
    if check.status != ra.EXACT_FEASIBLE or not ra.check_fixed_schedule(case, tuple(entries)).physically_assignable:
        raise AssertionError("fixed control failed physical validation")
    return {"objective": values, "entries": [asdict(e) for e in entries],
            "physical_status": check.status}, 2


def solve_fixed_controls(problem: WorkMethodTimeProject) -> dict:
    validate_problem(problem)
    started = perf_counter()
    weights = {a["id"]: i + 1 for i, a in enumerate(problem.project["activities"])}
    branches, feasible, solver_calls = [], [], 0
    for methods in method_selections(problem):
        workspace = materialise(problem, methods)
        activities = workspace["project"]["activities"]
        for modes in product(*(a["modes"] for a in activities)):
            if len(branches) >= 128:
                raise ValueError("the evidence control is bounded to 128 fixed method/mode networks")
            selected = {a["id"]: m["id"] for a, m in zip(activities, modes)}
            result, calls = _fixed_network(_case(workspace, selected), weights)
            solver_calls += calls
            branch = {"methods": methods, "modes": selected,
                      "status": "OPTIMAL" if result is not None else "INFEASIBLE"}
            if result is not None:
                branch.update(result)
                feasible.append(branch)
            branches.append(branch)
    best = min(feasible, key=lambda b: policy_key(problem, b["methods"], b["modes"], b["objective"])) if feasible else None
    return {"best": best, "branches": branches, "solver_calls": solver_calls,
            "end_to_end_ms": (perf_counter() - started) * 1000}


def run_comparison() -> dict:
    baseline = build_problem()
    scenarios = {"normal": baseline, "reported_outage": crane_outage(baseline, accepted=False),
                 "accepted_outage": crane_outage(baseline, accepted=True)}
    evidence = {}
    for name, problem in scenarios.items():
        before = input_hash(problem)
        control = solve_fixed_controls(problem)
        result = schedule_work_method_time(problem)
        repeated = schedule_work_method_time(problem)
        validate_plan(problem, result.plan)
        best = control["best"]
        matched = best is not None and policy_key(problem, result.plan["selected_methods"],
                    result.plan["selected_modes"], result.plan["objective"]) == policy_key(
                    problem, best["methods"], best["modes"], best["objective"])
        evidence[name] = {"input": to_document(problem), "source_unchanged": before == input_hash(problem),
                          "control": control, "candidate": asdict(result), "matches_full_policy": matched,
                          "repeat_plan_matches": result.plan == repeated.plan}
    passed = all(e["matches_full_policy"] and e["source_unchanged"] and e["repeat_plan_matches"]
                 for e in evidence.values())
    return {"milestone": "headless-work-method-productive-time-v0", "cases": evidence,
            "evidence_valid": passed,
            "boundary": "future-only composition, not accepted-history integration or production-scale certification"}


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run_comparison()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print("HEADLESS WORK-METHOD + PRODUCTIVE-TIME INTEGRATION")
    for name, evidence in result["cases"].items():
        plan = evidence["candidate"]["plan"]
        print(f"{name}: {plan['selected_methods']}; modes={plan['selected_modes']}; "
              f"objective={plan['objective']}; match={evidence['matches_full_policy']}; "
              f"repeat={evidence['repeat_plan_matches']}")
        print(json.dumps(evidence["candidate"]["metrics"], sort_keys=True))
    print(result["boundary"])
    if not result["evidence_valid"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
