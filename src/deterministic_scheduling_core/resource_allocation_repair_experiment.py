"""Bounded pooled-master repair, not a new public engine/resource architecture.

The master projects all admitted B placements to identity-free execution patterns.
An independent, pattern-aware whole-activity allocator proves each candidate.
Only proven impossible combinations generate no-goods; every iteration solves
finish and timing afresh. No B result or hard-coded M1/M2 repair enters the loop.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from hashlib import sha256
from itertools import product
import json
from pathlib import Path
import sys
from time import perf_counter

import ortools
from ortools.sat.python import cp_model

from deterministic_scheduling_core import resource_assignment_experiment as ra
from deterministic_scheduling_core.errors import SchedulingError
from deterministic_scheduling_core.working_time_experiment import (
    CONTINUOUS, SUSPENDABLE, WorkCalendar,
)

OPTIMAL = "PROVEN_OPTIMAL"
INFEASIBLE = ra.EXACT_INFEASIBLE
INCONCLUSIVE = ra.EXACT_INCONCLUSIVE
FEASIBLE = ra.EXACT_FEASIBLE


@dataclass(frozen=True)
class Allocation:
    status: str
    witness: tuple[tuple[str, str, str], ...]
    nodes: int
    reason: str


@dataclass(frozen=True)
class RepairResult:
    status: str
    entries: tuple[ra.ScheduledEntry, ...]
    allocation: tuple[tuple[str, str, str], ...]
    objective: tuple[int, int] | None
    cuts: tuple[tuple[ra.ScheduledEntry, ...], ...]
    trace: tuple[dict, ...]
    metrics: dict
    reason: str
    case_hash: str
    signature: str


def _digest(value) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def pattern(entry) -> tuple:
    return entry.start, entry.finish, entry.periods


def _profile(case: ra.ExperimentCase) -> None:
    """Reject unsupported data rather than claim a proof outside this experiment."""
    if type(case.horizon) is not int or case.horizon <= 0:
        raise ValueError("positive integer horizon required")
    if not case.activities or len(case.activity_by_id) != len(case.activities):
        raise ValueError("nonempty unique activity IDs required")
    if len(case.resource_by_id) != len(case.resources):
        raise ValueError("duplicate resource ID")
    if len(case.calendar_by_id) != len(case.calendars):
        raise ValueError("duplicate calendar ID")
    if case.objective_activity_id not in case.activity_by_id:
        raise ValueError("unknown controlling activity")
    for resource in case.resources:
        if type(resource.capacity) is not int or resource.capacity != 1:
            raise ValueError("this experiment requires capacity-one physical resources")
        if resource.calendar_id not in case.calendar_by_id:
            raise ValueError("unknown resource calendar")
    for activity in case.activities:
        if (type(activity.processing_ticks) is not int or activity.processing_ticks < 0
                or type(activity.not_before) is not int or activity.not_before < 0):
            raise ValueError("nonnegative integer work and release required")
        if activity.continuity not in {CONTINUOUS, SUSPENDABLE}:
            raise ValueError("unsupported continuity")
        if activity.calendar_id not in case.calendar_by_id:
            raise ValueError("unknown activity calendar")
        if any(p not in case.activity_by_id for p in activity.predecessors):
            raise ValueError("unknown predecessor")
        if activity.processing_ticks == 0 and activity.requirements:
            raise ValueError("milestones have no resource slots in this profile")
        if len({r.id for r in activity.requirements}) != len(activity.requirements):
            raise ValueError("duplicate requirement ID")
        for requirement in activity.requirements:
            if not requirement.pool_ids or not requirement.eligible_resource_ids:
                raise ValueError("explicit capability and eligibility required")
            for rid in requirement.eligible_resource_ids:
                if rid not in case.resource_by_id or not set(requirement.pool_ids) <= set(case.resource_by_id[rid].capabilities):
                    raise ValueError("eligible resources must possess every required capability")
    for outage in case.exceptions:
        if (outage.resource_id not in case.resource_by_id or type(outage.start) is not int
                or type(outage.finish) is not int or not 0 <= outage.start < outage.finish <= case.horizon):
            raise ValueError("invalid availability exception")


def project_placements(case: ra.ExperimentCase) -> tuple[dict, int, int]:
    """Existential projection, including resource-dependent suspension patterns.

    Preprocessing still enumerates local assignment tuples. Count them openly:
    zero assignment literals in the master does NOT mean no identity work/data.
    This uses the established placement compiler, not the solved B reference.
    """
    _profile(case)
    catalog = {}
    variants = omitted_by_old_pool = 0
    for activity in case.activities:
        explicit = ra._candidate_placements(case, activity, "B")
        keys = sorted({pattern(p) for p in explicit})
        variants += len(explicit)
        legacy = {pattern(p) for p in ra._candidate_placements(case, activity, "A")}
        omitted_by_old_pool += len(set(keys) - legacy)
        catalog[activity.id] = tuple(
            ra.ScheduledEntry(activity.id, start, finish, periods,
                              tuple((r.id, None) for r in activity.requirements))
            for start, finish, periods in keys
        )
    return catalog, variants, omitted_by_old_pool


def _resource_time(case: ra.ExperimentCase, rid: str) -> set[int]:
    """Checker-side availability from source calendars/outages, not placements."""
    resource = case.resource_by_id[rid]
    slots = set(case.calendar_by_id[resource.calendar_id].slots(case.horizon))
    for outage in case.exceptions:
        if outage.resource_id == rid:
            slots -= set(range(outage.start, outage.finish))
    return slots


def check_allocation(case: ra.ExperimentCase, entries: tuple[ra.ScheduledEntry, ...],
                     *, max_nodes: int | None = None, complete: bool = True) -> Allocation:
    """Independent finite global assignment proof, including no voluntary gaps.

    The old fixed checker proves occupancy/availability but does not require its
    chosen witness to explain each suspension gap. Here an assigned resource must
    support exactly the submitted productive pattern, not merely its occupied
    slots. Conflict reduction may check a subset; it never presents it as a plan.
    """
    if max_nodes is not None and (type(max_nodes) is not int or max_nodes < 0):
        raise ValueError("max_nodes must be nonnegative or None")
    ids = [e.activity_id for e in entries]
    if len(ids) != len(set(ids)) or any(a not in case.activity_by_id for a in ids):
        return Allocation(INFEASIBLE, (), 0, "duplicate or unknown activities")
    if complete and set(ids) != set(case.activity_by_id):
        return Allocation(INFEASIBLE, (), 0, "incomplete project coverage")
    by_id = {e.activity_id: e for e in entries}
    available = {r.id: _resource_time(case, r.id) for r in case.resources}
    domains = []
    for entry in entries:
        activity = case.activity_by_id[entry.activity_id]
        if (type(entry.start) is not int or type(entry.finish) is not int
                or not activity.not_before <= entry.start <= entry.finish <= case.horizon):
            return Allocation(INFEASIBLE, (), 0, "invalid execution boundary")
        if any(entry.start < by_id[p].finish for p in activity.predecessors if p in by_id):
            return Allocation(INFEASIBLE, (), 0, "precedence violation")
        last = entry.start
        occupied = set()
        for start, finish in entry.periods:
            if type(start) is not int or type(finish) is not int or not last <= start < finish <= entry.finish:
                return Allocation(INFEASIBLE, (), 0, "invalid productive periods")
            occupied.update(range(start, finish))
            last = finish
        if len(occupied) != activity.processing_ticks:
            return Allocation(INFEASIBLE, (), 0, "wrong productive work")
        if occupied and (min(occupied) != entry.start or max(occupied) + 1 != entry.finish):
            return Allocation(INFEASIBLE, (), 0, "incorrect start/finish envelope")
        if not occupied and entry.start != entry.finish:
            return Allocation(INFEASIBLE, (), 0, "milestone has elapsed occupancy")
        submitted = dict(entry.assignments)
        if len(submitted) != len(entry.assignments) or set(submitted) != {r.id for r in activity.requirements}:
            return Allocation(INFEASIBLE, (), 0, "incorrect requirement coverage")
        candidates = []
        choices = [tuple(sorted(set(r.eligible_resource_ids))) for r in activity.requirements]
        for assignment in product(*choices):
            if len(set(assignment)) != len(assignment):
                continue
            if any(submitted[r.id] is not None and submitted[r.id] != rid
                   for r, rid in zip(activity.requirements, assignment)):
                continue
            allowed = set(case.calendar_by_id[activity.calendar_id].slots(case.horizon))
            for rid in assignment:
                allowed &= available[rid]
            if not occupied <= allowed:
                continue
            envelope = set(range(entry.start, entry.finish))
            if activity.continuity == CONTINUOUS and occupied != envelope:
                continue
            if activity.continuity == SUSPENDABLE and occupied != allowed & envelope:
                continue
            candidates.append(assignment)
        if not candidates:
            return Allocation(INFEASIBLE, (), 0, f"{activity.id}: no assignment supports this exact pattern")
        if activity.requirements:
            domains.append((entry, occupied, tuple(candidates)))
    domains.sort(key=lambda row: (len(row[2]), -len(row[1]), row[0].activity_id))
    used = {rid: set() for rid in available}
    allocation = []
    nodes = 0
    limited = False

    def search(index: int) -> bool:
        nonlocal nodes, limited
        if index == len(domains):
            return True
        if max_nodes is not None and nodes >= max_nodes:
            limited = True
            return False
        nodes += 1
        entry, occupied, candidates = domains[index]
        activity = case.activity_by_id[entry.activity_id]
        for assignment in candidates:
            if any(occupied & used[rid] for rid in assignment):
                continue
            for requirement, rid in zip(activity.requirements, assignment):
                used[rid].update(occupied)
                allocation.append((activity.id, requirement.id, rid))
            if search(index + 1):
                return True
            for rid in reversed(assignment):
                used[rid].difference_update(occupied)
                allocation.pop()
            if limited:
                return False
        return False

    if search(0):
        return Allocation(FEASIBLE, tuple(sorted(allocation)), nodes, "exact pattern-aware no-handover allocation")
    return Allocation(INCONCLUSIVE if limited else INFEASIBLE, (), nodes,
                      "allocation search limit" if limited else "all consistent whole-activity allocations exhausted")


def _master(case, catalog, cuts):
    """Rebuild without the previous iteration's objective equalities."""
    started = perf_counter()
    model = cp_model.CpModel()
    starts, finishes, literals = {}, {}, {}
    for activity in case.activities:
        options = catalog[activity.id]
        starts[activity.id] = model.new_int_var(0, case.horizon, f"start_{activity.id}")
        finishes[activity.id] = model.new_int_var(0, case.horizon, f"finish_{activity.id}")
        choices = []
        for index, entry in enumerate(options):
            literal = model.new_bool_var(f"pattern_{activity.id}_{index}")
            literals[(activity.id, pattern(entry))] = literal
            choices.append(literal)
            model.add(starts[activity.id] == entry.start).only_enforce_if(literal)
            model.add(finishes[activity.id] == entry.finish).only_enforce_if(literal)
        model.add_exactly_one(choices)
    for activity in case.activities:
        for predecessor in activity.predecessors:
            model.add(starts[activity.id] >= finishes[predecessor])
    # Capability constraints are necessary relaxations, never assignment proofs.
    terms = {}
    for activity in case.activities:
        demand = {}
        for requirement in activity.requirements:
            for pool in set(requirement.pool_ids):
                demand[pool] = demand.get(pool, 0) + 1
        for entry in catalog[activity.id]:
            literal = literals[(activity.id, pattern(entry))]
            for start, finish in entry.periods:
                for tick in range(start, finish):
                    for pool, quantity in demand.items():
                        terms.setdefault((pool, tick), []).append(quantity * literal)
    availability = {r.id: _resource_time(case, r.id) for r in case.resources}
    for (pool, tick), demands in sorted(terms.items()):
        capacity = sum(pool in r.capabilities and tick in availability[r.id] for r in case.resources)
        model.add(sum(demands) <= capacity)
    for cut in cuts:
        model.add(sum(literals[(e.activity_id, pattern(e))] for e in cut) <= len(cut) - 1)
    metrics = {"build_ms": (perf_counter() - started) * 1000,
               "variables": len(model.proto.variables), "constraints": len(model.proto.constraints),
               "assignment_variables": 0, "solver_calls": 0, "solve_ms": 0.0}
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    timing = sum((i + 1) * starts[a.id] for i, a in enumerate(case.activities))
    objective = []
    for expression in (finishes[case.objective_activity_id], timing):
        model.minimize(expression)
        started = perf_counter()
        status = solver.solve(model)
        metrics["solve_ms"] += (perf_counter() - started) * 1000
        metrics["solver_calls"] += 1
        if status == cp_model.MODEL_INVALID:
            raise SchedulingError("repair master MODEL_INVALID: " + model.validate())
        if status == cp_model.INFEASIBLE:
            return INFEASIBLE, (), None, metrics
        if status != cp_model.OPTIMAL:
            return INCONCLUSIVE, (), None, metrics
        value = solver.value(expression)
        objective.append(value)
        model.add(expression == value)
    entries = tuple(next(e for e in catalog[a.id] if solver.value(literals[(a.id, pattern(e))]))
                    for a in case.activities)
    return OPTIMAL, entries, tuple(objective), metrics


def solve_repair(case: ra.ExperimentCase, *, max_iterations: int = 64,
                 max_search_nodes: int | None = None) -> RepairResult:
    """Find a proven executable optimum or return an explicit bounded failure."""
    if type(max_iterations) is not int or max_iterations <= 0:
        raise ValueError("max_iterations must be positive")
    if max_search_nodes is not None and (type(max_search_nodes) is not int or max_search_nodes < 0):
        raise ValueError("max_search_nodes must be nonnegative or None")
    beginning = perf_counter()
    catalog, variants, omitted = project_placements(case)
    metrics = {"preprocess_ms": (perf_counter() - beginning) * 1000,
               "local_assignment_placements": variants,
               "projected_patterns": sum(map(len, catalog.values())),
               "patterns_missing_from_legacy_pool": omitted,
               "solver_calls": 0, "checker_calls": 0, "checker_nodes": 0,
               "checker_ms": 0.0, "build_ms": 0.0, "solve_ms": 0.0,
               "max_variables": 0, "max_constraints": 0, "assignment_variables": 0}
    cuts, trace = [], []
    case_hash = _digest(asdict(case))

    def check(entries, complete=True):
        start = perf_counter()
        result = check_allocation(case, entries, max_nodes=max_search_nodes, complete=complete)
        metrics["checker_ms"] += (perf_counter() - start) * 1000
        metrics["checker_calls"] += 1
        metrics["checker_nodes"] += result.nodes
        return result

    def finish(status, reason, entries=(), allocation=(), objective=None):
        metrics["elapsed_ms"] = (perf_counter() - beginning) * 1000
        metrics["iterations"] = len(trace)
        payload = {"case_hash": case_hash, "status": status, "objective": objective,
                   "entries": [asdict(e) for e in entries], "allocation": allocation}
        return RepairResult(status, entries, allocation, objective, tuple(cuts), tuple(trace),
                            dict(metrics), reason, case_hash, _digest(payload))

    if any(not options for options in catalog.values()):
        return finish(INFEASIBLE, "an activity has no admissible physical placement within the horizon")
    for iteration in range(max_iterations):
        status, entries, objective, measured = _master(case, catalog, cuts)
        for key in ("solver_calls", "build_ms", "solve_ms"):
            metrics[key] += measured[key]
        for key in ("variables", "constraints"):
            metrics["max_" + key] = max(metrics["max_" + key], measured[key])
        row = {"iteration": iteration + 1, "master_status": status, "objective": objective,
               "candidate": [asdict(e) for e in entries]}
        trace.append(row)
        if status != OPTIMAL:
            return finish(status, "no feasible master remains" if status == INFEASIBLE else "master optimum unproved")
        proof = check(entries)
        row.update(checker_status=proof.status, checker_reason=proof.reason)
        if proof.status == INCONCLUSIVE:
            return finish(INCONCLUSIVE, "allocation search limit; no cut inferred")
        if proof.status == FEASIBLE:
            return finish(OPTIMAL, "feasible witness attains the proven relaxation optimum after sound cuts",
                          entries, proof.witness, objective)
        # Deletion-based conflict extraction: every retained core is proven.
        # An inconclusive reduction keeps the larger already-proven core.
        core = tuple(e for e in entries if case.activity_by_id[e.activity_id].requirements)
        for entry in sorted(core, key=lambda e: e.activity_id):
            smaller = tuple(e for e in core if e.activity_id != entry.activity_id)
            if smaller and check(smaller, complete=False).status == INFEASIBLE:
                core = smaller
        if not core or core in cuts:
            raise AssertionError("feedback must exclude a new nonempty proven allocation conflict")
        cuts.append(core)
        row["cut"] = [asdict(e) for e in core]
    return finish(INCONCLUSIVE, "repair iteration budget reached; no executable plan claimed")


def build_continuity_case(horizon: int = 6) -> ra.ExperimentCase:
    """Schedulable variant; the original negative regression is not altered."""
    calendar = WorkCalendar("TEST", ((0, horizon),))
    resources = (ra.PhysicalResource("M1", ("MECH",), "TEST"),
                 ra.PhysicalResource("M2", ("MECH",), "TEST"))
    def req(*ids):
        return (ra.RequirementSlot("MECH", ("MECH",), ids),)
    activities = (
        ra.ActivitySpec("X", "Long no-handover job", 4, "TEST", req("M1", "M2")),
        ra.ActivitySpec("Y", "M1 only", 2, "TEST", req("M1")),
        ra.ActivitySpec("Z", "M2 only, released later", 2, "TEST", req("M2"), not_before=2),
        ra.ActivitySpec("DONE", "All work complete", 0, "TEST", predecessors=("X", "Y", "Z")),
    )
    return ra.ExperimentCase((calendar,), resources, (), activities, "DONE", horizon)


def build_calendar_case() -> ra.ExperimentCase:
    """Aggregate availability misses a legitimate resource-specific gap."""
    calendar = WorkCalendar("TEST", ((0, 8),))
    resources = (ra.PhysicalResource("E", ("MECH",), "TEST"),
                 ra.PhysicalResource("L", ("MECH", "INSPECT"), "TEST"),
                 ra.PhysicalResource("R1", ("RIGGER",), "TEST"),
                 ra.PhysicalResource("R2", ("RIGGER",), "TEST"))
    req = ra.RequirementSlot
    activities = (
        ra.ActivitySpec("FLEX", "Suspendable mechanical work", 4, "TEST", (req("MECH", ("MECH",), ("E", "L")),)),
        ra.ActivitySpec("INSPECT", "L-only inspection", 2, "TEST", (req("INSPECT", ("INSPECT",), ("L",)),), not_before=2),
        ra.ActivitySpec("RIG1", "Interchangeable lift 1", 2, "TEST", (req("RIGGER", ("RIGGER",), ("R1", "R2")),)),
        ra.ActivitySpec("RIG2", "Interchangeable lift 2", 2, "TEST", (req("RIGGER", ("RIGGER",), ("R1", "R2")),)),
        ra.ActivitySpec("DONE", "Handoff", 0, "TEST", predecessors=("FLEX", "INSPECT", "RIG1", "RIG2")),
    )
    exceptions = (ra.AvailabilityException("E", 2, 4, "mid-window outage"),
                  ra.AvailabilityException("L", 0, 2, "later availability"))
    return ra.ExperimentCase((calendar,), resources, exceptions, activities, "DONE", 8)


def classify_outcomes(results: dict) -> tuple[bool, str]:
    """A valid inconclusive experiment is not a successful architectural result."""
    valid = bool(results)
    for record in results.values():
        candidate = record["candidate"]
        valid &= (record["source_unchanged"] and record["repeat_signature_matches"]
                  and record["repeat_trace_matches"] and record["repeat_objective_matches"]
                  and record["reference"]["checker"]["status"] == FEASIBLE)
        if candidate["status"] == OPTIMAL:
            valid &= record["matches_reference"]
        elif candidate["status"] == INCONCLUSIVE:
            valid &= (not candidate["entries"] and not candidate["allocation"]
                      and candidate["objective"] is None and not record["matches_reference"])
        else:
            # These comparison cases all have a separately verified feasible B.
            # A claimed infeasibility here would be contradictory, not a pass.
            valid = False
    if not valid:
        return False, "EVIDENCE_FAILURE"
    if all(r["matches_reference"] for r in results.values()):
        return True, "NOT_FALSIFIED_FOR_TESTED_PROFILE"
    return True, "INCONCLUSIVE_WITHIN_DECLARED_LIMITS"


def run_experiment() -> dict:
    """Measure all approaches; derive conclusions only from returned evidence."""
    results = {}
    for name, case in (("overlap", ra.build_case()), ("continuity", build_continuity_case()),
                       ("calendar", build_calendar_case())):
        before = _digest(asdict(case))
        started = perf_counter()
        reference = ra.solve_approach(case, "B")
        reference_ms = (perf_counter() - started) * 1000
        reference_check = check_allocation(case, reference.entries)
        candidate = solve_repair(case)
        repeated = solve_repair(case)
        if candidate.status == OPTIMAL:
            witness = {(a, r): rid for a, r, rid in candidate.allocation}
            named = tuple(replace(e, assignments=tuple((r, witness[(e.activity_id, r)])
                                                       for r, _ in e.assignments)) for e in candidate.entries)
            legacy_check = ra.check_fixed_schedule(case, named)
            validated = legacy_check.exact_status == FEASIBLE and check_allocation(case, named).status == FEASIBLE
        else:
            validated = False
        matched = (candidate.status == OPTIMAL and reference_check.status == FEASIBLE
                   and candidate.objective == reference.objective_result and validated)
        record = {"case": asdict(case), "source_unchanged": before == _digest(asdict(case)),
                  "planner_facts": dict(ra._planner_facts(case)),
                  "reference": {"objective": reference.objective_result,
                                "entries": [asdict(e) for e in reference.entries],
                                "checker": asdict(reference_check), "metrics": asdict(reference.metrics),
                                "end_to_end_ms": reference_ms},
                  "candidate": asdict(candidate), "matches_reference": matched,
                  "repeat_signature_matches": candidate.signature == repeated.signature,
                  "repeat_trace_matches": candidate.trace == repeated.trace,
                  "repeat_objective_matches": candidate.objective == repeated.objective}
        if name == "overlap":
            selective = ra.solve_approach(case, "C")
            record["selective_control"] = {"objective": selective.objective_result,
                                           "metrics": asdict(selective.metrics),
                                           "physically_assignable": selective.checker.physically_assignable}
        results[name] = record
    evidence_valid, conclusion = classify_outcomes(results)
    return {"experiment": "headless-resource-allocation-repair-v0", "ortools": ortools.__version__,
            "resolution": "existing 30-minute ticks", "cases": results,
            "evidence_valid": evidence_valid, "conclusion": conclusion,
            "boundary": "identity-free master still enumerates local identity-dependent placements; no universal architecture or performance superiority claimed"}


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run_experiment()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print("HEADLESS RESOURCE ALLOCATION REPAIR V0")
    for name, record in result["cases"].items():
        candidate = record["candidate"]
        print(f"{name}: B={record['reference']['objective']}; repair={candidate['objective']}; "
              f"status={candidate['status']}; match={record['matches_reference']}; "
              f"repeat={record['repeat_signature_matches']}")
        print("candidate_costs=" + json.dumps(candidate["metrics"], sort_keys=True))
        print("reference_costs=" + json.dumps({**record["reference"]["metrics"],
              "end_to_end_ms": record["reference"]["end_to_end_ms"]}, sort_keys=True))
        print(f"initial={candidate['trace'][0]['objective'] if candidate['trace'] else None}; "
              f"last_relaxation={candidate['trace'][-1]['objective'] if candidate['trace'] else None}; "
              f"cuts={len(candidate['cuts'])}")
    print(result["conclusion"])
    print(result["boundary"])
    # Hypothesis support is separate from evidence integrity/CI success.
    if not result["evidence_valid"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
