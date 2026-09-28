"""No-solve, exact placement-domain census for the 160/120 professional fixture.

The production compiler and admission limits are intentionally untouched.  W1
removes only placements lacking support under finish-to-start logic after
relaxing *all* inter-activity physical conflicts.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
from hashlib import sha256
from itertools import product
import json
import platform
import statistics
import subprocess
from time import perf_counter

import ortools

from deterministic_scheduling_core.converged_scale_experiment import build_problem as scale_problem
from deterministic_scheduling_core.factored_finish_search_experiment import build_group_stress
from deterministic_scheduling_core.native_work_method_time import build_problem as small_problem, solve_fixed_controls
from deterministic_scheduling_core.professional_scale_challenge import build_professional_projection, run_challenge
from deterministic_scheduling_core.professional_workface_experiment import build_problem as professional_problem
from deterministic_scheduling_core.project.model import ExecutionMethod, WorkPackage
from deterministic_scheduling_core.project.work_method_time import (
    WorkMethodTimeProject, input_hash, materialise, membership, method_selections,
)
from deterministic_scheduling_core.scheduling.canonical_batching import CanonicalDigit, build_lexicographic_blocks
from deterministic_scheduling_core.scheduling.planning_workspace import _group_placements
from deterministic_scheduling_core.scheduling.work_method_time import (
    MAX_WORKFACE_INTERVALS, _mode_cases, policy_key, schedule_work_method_time,
    validate_plan, validate_problem,
)

BASE_HASHES = {
    "small_named": "d54db4bc5f6cdd64b1ca3d8fd3f92b9f45103cae2230685e81363936db746761",
    "professional": "733a4023ff6c78735aa4ccc5d8003a1f31ecde80f3851ffadbd4dadfa2100acb",
    "64_48": "0698e2c95e7aed5ee35d7d343349e77b88e39121bfbad41fa865c6818d923410",
}


@dataclass(frozen=True)
class Row:
    aid: str
    mode: str
    rank: int  # The original 1-based production canonical digit, before W1.
    start: int
    finish: int
    periods: tuple
    named: tuple
    assignments: tuple
    resource_intervals: tuple[tuple[str, int], ...]
    workface_groups: tuple[str, ...]

    @property
    def temporal(self):
        return self.start, self.finish, self.periods

    @property
    def temporal_named(self):
        return self.start, self.finish, self.periods, self.named


def domains(problem):
    """Generate and sort exactly as the owning compiler, before admission."""
    environment, specs = _mode_cases(problem)
    indexed, detail = {}, []
    owner = membership(problem)
    for activity in problem.project["activities"]:
        aid = activity["id"]
        rows = []
        for mode in activity["modes"]:
            mid = mode["id"]
            spec = specs[aid, mid]
            raw = _group_placements(environment, spec, "B")
            eligible = tuple(sorted(
                (p for p in raw if p.finish <= activity.get("latest_finish", environment.horizon)),
                key=lambda p: (p.start, p.finish, p.periods,
                               tuple("" if r is None else r for r in p.assignments)),
            ))
            mode_rows = []
            for placement in eligible:
                # One internal group-unit set remains fixed across all periods.
                named = tuple((r.id, rid) for r, rid in zip(spec.requirements, placement.assignments)
                              if not r.id.startswith("@group/"))
                intervals = tuple((rid, len(placement.periods)) for rid in placement.assignments)
                mode_rows.append(Row(aid, mid, len(rows) + len(mode_rows) + 1,
                    placement.start, placement.finish, placement.periods, named,
                    placement.assignments, intervals,
                    tuple(activity.get("exclusion_groups", ())) if placement.start < placement.finish else ()))
            rows.extend(mode_rows)
            temporal = {r.temporal for r in mode_rows}
            temporal_named = {r.temporal_named for r in mode_rows}
            detail.append({"activity": aid, "mode": mid, "work_package": owner.get(aid, (None, None))[0],
                "method": owner.get(aid, (None, None))[1], "processing_ticks": mode["processing_ticks"],
                "not_before": activity.get("not_before", 0), "latest_finish": activity.get("latest_finish"),
                "exclusion_groups": activity.get("exclusion_groups", []),
                "named_requirements": [r.id for r in spec.requirements if not r.id.startswith("@group/")],
                "group_requirements": mode.get("group_requirements", []),
                "raw": len(raw), "eligible": len(mode_rows), "temporal": len(temporal),
                "temporal_named": len(temporal_named),
                "anonymous_witness_expansion": len(mode_rows) - len(temporal_named),
                "unique_full_assignment_signatures": len({(r.temporal, r.assignments) for r in mode_rows})})
        indexed[aid] = tuple(rows)
    return indexed, detail


def _arcs(project):
    """Read materialised activity arcs, including package predecessor roots."""
    return tuple((pred, a["id"]) for a in project["activities"] for pred in a.get("predecessors", ()))


def window_prune(project, indexed):
    """Arc support to a fixpoint on the relaxed placement domains.

Every removed row lacks a predecessor/successor supporter in a necessary FS
constraint. This is sound but need not find *all* globally unreachable rows in
a general precedence DAG. Physical conflicts are never used to remove rows.
    """
    active = {a["id"] for a in project["activities"]}
    arcs = _arcs(project)
    if any(p not in active or c not in active for p, c in arcs):
        raise AssertionError("materialised precedence arc references an inactive activity")
    eligible = {aid: set(range(1, len(indexed[aid]) + 1)) for aid in active}
    loops = 0
    while True:
        loops += 1
        if any(not ranks for ranks in eligible.values()):
            return {aid: set() for aid in active}, loops
        lo_finish = {aid: min(indexed[aid][rank - 1].finish for rank in ranks)
                     for aid, ranks in eligible.items()}
        hi_start = {aid: max(indexed[aid][rank - 1].start for rank in ranks)
                    for aid, ranks in eligible.items()}
        next_allowed = {aid: ranks.copy() for aid, ranks in eligible.items()}
        for pred, child in arcs:
            next_allowed[child] = {rank for rank in next_allowed[child]
                if indexed[child][rank - 1].start >= lo_finish[pred]}
            next_allowed[pred] = {rank for rank in next_allowed[pred]
                if indexed[pred][rank - 1].finish <= hi_start[child]}
        if next_allowed == eligible:
            return eligible, loops
        eligible = next_allowed


def _rank_digest(indexed, allowed):
    rank_pairs = [[aid, rank] for aid in indexed for rank in sorted(allowed.get(aid, ()))]
    return sha256(json.dumps(rank_pairs, separators=(",", ":")).encode()).hexdigest()


def _identity_digest(indexed, allowed):
    """Fingerprint original ordered rows, including internal witness identity."""
    digest = sha256()
    for aid in indexed:
        for rank in sorted(allowed.get(aid, ())):
            row = indexed[aid][rank - 1]
            digest.update(json.dumps([aid, rank, row.mode, row.start, row.finish,
                row.periods, row.assignments], separators=(",", ":")).encode() + b"\n")
    return digest.hexdigest()


def census(problem, indexed, allowed, *, raw=None, selected=None, rank_map=False):
    """Mechanically count current compiler literals/intervals; never assemble it."""
    activities = [a for a in problem.project["activities"] if a["id"] in allowed]
    source = problem.project
    rows = [indexed[a["id"]][rank - 1] for a in activities
            for rank in sorted(allowed[a["id"]])]
    temporal = {(r.aid, r.mode, r.temporal) for r in rows}
    temporal_named = {(r.aid, r.mode, r.temporal_named) for r in rows}
    named, group, workface = Counter(), Counter(), Counter()
    internal_group_units = set()
    group_ids = {f"@group/{i}/": g["id"] for i, g in enumerate(source.get("resource_groups", []))}
    for row in rows:
        for rid, segments in row.resource_intervals:
            for prefix, group_id in group_ids.items():
                if rid.startswith(prefix):
                    group[group_id] += segments
                    internal_group_units.add(rid)
                    break
            else:
                named[rid] += segments
        workface.update(row.workface_groups)
    modes = sum(len(a["modes"]) for a in activities)
    packages = len(problem.work_packages)
    method_count = sum(len(p.methods) for p in problem.work_packages) if selected is None else packages
    predecessor_arcs = sum(len(a.get("predecessors", ())) for a in activities)
    if selected is not None:
        predecessor_arcs = len(_arcs(materialise(problem, selected)["project"]))
    method_digits = [CanonicalDigit(f"method:{p.id}", len(p.methods) - 1 if selected is None else 0)
                     for p in problem.work_packages]
    mode_digits = [CanonicalDigit(f"mode:{a['id']}", len(a["modes"])) for a in activities]
    placement_digits = [CanonicalDigit(f"placement:{a['id']}", len(indexed[a["id"]]))
                        for a in activities]
    # Original production ranks, including pruned holes, remain digit maxima.
    blocks = build_lexicographic_blocks([*method_digits, *mode_digits, *placement_digits])
    intervals = sum(named.values()) + sum(group.values()) + sum(workface.values())
    pressure = {"measurement_kind": "mechanically_derived_no_proto", "declared_activities": len(source["activities"]),
        "active_activities": len(activities), "method_boolvars": method_count,
        "mode_boolvars": modes, "placement_boolvars": len(rows),
        "start_end_intvars": 2 * len(activities),
        "base_variable_estimate": method_count + modes + len(rows) + 2 * len(activities),
        "resource_optional_intervals_exact": sum(named.values()) + sum(group.values()),
        "workface_optional_intervals_exact": sum(workface.values()),
        "interval_constraints_exact": intervals,
        "named_no_overlap_buckets": len(named),
        "anonymous_no_overlap_buckets": len(internal_group_units),
        "workface_no_overlap_buckets": len(workface),
        "precedence_arcs": predecessor_arcs, "canonical_digit_count": len(method_digits + mode_digits + placement_digits),
        "canonical_block_count": len(blocks),
        "base_linear_constraint_estimate": packages + modes + 3 * len(activities) + predecessor_arcs,
        "base_constraint_estimate_excluding_union_package_arcs":
            packages + modes + 3 * len(activities) + predecessor_arcs + intervals + len(named) + len(workface) +
            sum(r["capacity"] for r in source.get("resource_groups", []) if r["id"] in group),
        "estimate_note": "Selected structures are projections, not production protos. Union package-root arcs and constant variables are excluded from the constraint/variable estimates."}
    result = {"flattened": len(rows), "temporal_patterns": len(temporal),
        "temporal_named_patterns": len(temporal_named),
        "anonymous_witness_expansion": len(rows) - len(temporal_named),
        "named_resource_intervals": dict(sorted(named.items())),
        "group_resource_intervals": dict(sorted(group.items())),
        "workface_intervals_by_group": dict(sorted(workface.items())),
        "rank_digest": _rank_digest(indexed, allowed),
        "original_row_identity_digest": _identity_digest(indexed, allowed),
        "model_pressure": pressure}
    if raw is not None:
        result["raw_placements"] = raw
    if rank_map:
        result["retained_original_ranks"] = {aid: sorted(allowed[aid]) for aid in indexed if aid in allowed}
    return result


def tiny_problem():
    """Two alternatives, a calendar gap, FS chain, not_before and a deadline."""
    mode = lambda duration: {"id": "FIXED", "processing_ticks": duration,
        "calendar_id": "GAP", "continuity": "SUSPENDABLE_AT_AVAILABILITY_GAPS",
        "requirements": [], "group_requirements": []}
    project = {"id": "tiny-window", "name": "Tiny independent domain oracle", "horizon_ticks": 8,
        "calendars": [{"id": "GAP", "daily_windows": [[0, 2], [4, 8]]}],
        "resources": [], "activities": [
            {"id": "A", "name": "Predecessor", "not_before": 1, "modes": [mode(1)]},
            {"id": "B", "name": "Fast alternative", "latest_finish": 6, "modes": [mode(1)]},
            {"id": "C", "name": "Slow alternative", "latest_finish": 7, "modes": [mode(2)]},
            {"id": "DONE", "name": "Handoff", "latest_finish": 8, "modes": [mode(1)]}],
        "objective_activity_id": "DONE", "pool_riggers": False}
    packages = (
        WorkPackage("START", "Start", (ExecutionMethod("FIXED", "Start", ("A",), "A"),)),
        WorkPackage("CHOICE", "Choice", (ExecutionMethod("FAST", "Fast", ("B",), "B"),
                                            ExecutionMethod("SLOW", "Slow", ("C",), "C")), ("START",)),
        WorkPackage("HANDOFF", "Handoff", (ExecutionMethod("FIXED", "Handoff", ("DONE",), "DONE"),), ("CHOICE",)))
    return WorkMethodTimeProject(project, packages)


def tiny_oracle(problem, indexed):
    """Enumerate Cartesian placement tuples independently of W1 propagation."""
    evidence = []
    for selected in method_selections(problem):
        projected = materialise(problem, selected)["project"]
        aids = [a["id"] for a in projected["activities"]]
        # Independent of W1's arc-reading helper and propagation implementation.
        arcs = [(predecessor, row["id"]) for row in projected["activities"]
                for predecessor in row.get("predecessors", [])]
        valid = [set() for _ in aids]
        candidates = [indexed[aid] for aid in aids]
        feasible = 0
        for choice in product(*candidates):
            picked = {aid: row for aid, row in zip(aids, choice)}
            if all(picked[p].finish <= picked[c].start for p, c in arcs):
                feasible += 1
                for i, row in enumerate(choice):
                    valid[i].add(row.rank)
        allowed, loops = window_prune(projected, indexed)
        exact = {aid: sorted(ranks) for aid, ranks in zip(aids, valid)}
        actual = {aid: sorted(allowed[aid]) for aid in aids}
        if actual != exact:
            raise AssertionError("tiny exhaustive relaxed schedules disagree with W1")
        evidence.append({"methods": selected, "complete_precedence_schedules": feasible,
            "surviving_original_ranks": exact, "propagation_rounds": loops})
    return evidence


def inspect(problem):
    """Perform one bounded domain census; never call 160/120 scheduling."""
    before = input_hash(problem)
    start = perf_counter()
    indexed, detail = domains(problem)
    generation_ms = (perf_counter() - start) * 1000
    raw = sum(d["raw"] for d in detail)
    eligible = sum(d["eligible"] for d in detail)
    selection_rows = list(method_selections(problem))
    owner = membership(problem)
    membership_counts = Counter(aid for selection in selection_rows for aid in (
        a["id"] for a in materialise(problem, selection)["project"]["activities"]))
    all_allowed = {aid: set(range(1, len(rows) + 1)) for aid, rows in indexed.items()}
    union = census(problem, indexed, all_allowed, raw=raw)
    structures, retained_union = [], {aid: set() for aid in indexed}
    pruning_start = perf_counter()
    for selected in selection_rows:
        projected = materialise(problem, selected)["project"]
        active = {a["id"] for a in projected["activities"]}
        unpruned = census(problem, indexed, {aid: all_allowed[aid] for aid in indexed if aid in active},
            raw=sum(d["raw"] for d in detail if d["activity"] in active), selected=selected)
        allowed, loops = window_prune(projected, indexed)
        for aid, ranks in allowed.items():
            retained_union[aid].update(ranks)
        pruned = census(problem, indexed, allowed, selected=selected, rank_map=True)
        if any(not ranks <= all_allowed[aid] for aid, ranks in allowed.items()):
            raise AssertionError("W1 invented a placement rank")
        structures.append({"methods": selected, "active_activities": len(active),
            "s0": unpruned, "s1": pruned, "propagation_rounds": loops,
            "removed": unpruned["flattened"] - pruned["flattened"]})
    pruning_ms = (perf_counter() - pruning_start) * 1000
    u1 = census(problem, indexed, retained_union, rank_map=True)
    if sum(len(r) for r in indexed.values()) != eligible or union["flattened"] != eligible:
        raise AssertionError("union census does not reconcile to generated placements")
    if input_hash(problem) != before:
        raise AssertionError("diagnostic changed its source")
    ownership = {aid: {"structures": membership_counts[aid], "placement_rows": len(indexed[aid]),
                       "work_package": owner.get(aid, (None, None))[0],
                       "method": owner.get(aid, (None, None))[1]}
                 for aid in indexed}
    fixed_packages = {p.id for p in problem.work_packages if len(p.methods) == 1}
    kinds = {"always_potentially_active": sum(len(indexed[aid]) for aid in indexed
                                      if membership_counts[aid] == len(selection_rows)),
             "optional_structural": sum(len(indexed[aid]) for aid in indexed
                                     if membership_counts[aid] < len(selection_rows)),
             "fixed_single_method_package": sum(len(indexed[aid]) for aid in indexed
                                     if owner.get(aid, (None, None))[0] in fixed_packages),
             "alternative_method_package": sum(len(indexed[aid]) for aid in indexed
                                     if owner.get(aid, (None, None))[0] not in fixed_packages and aid in owner),
             "outside_package": sum(len(indexed[aid]) for aid in indexed if aid not in owner)}
    return {"source_hash": before, "declared_activities": len(indexed),
        "authorised_structures": len(structures), "u0": union, "u1": u1,
        "mode_anatomy": detail, "ownership": ownership, "ownership_totals": kinds,
        "structures": structures, "s0_counts": [s["s0"]["flattened"] for s in structures],
        "s1_counts": [s["s1"]["flattened"] for s in structures],
        "s0_distribution": {"min": min(s["s0"]["flattened"] for s in structures),
                            "median": statistics.median(s["s0"]["flattened"] for s in structures),
                            "max": max(s["s0"]["flattened"] for s in structures)},
        "s1_distribution": {"min": min(s["s1"]["flattened"] for s in structures),
                            "median": statistics.median(s["s1"]["flattened"] for s in structures),
                            "max": max(s["s1"]["flattened"] for s in structures)},
        "wall_observations_ms": {"placement_generation": generation_ms, "structure_pruning": pruning_ms},
        "source_unchanged": True}


def run_evidence(source_sha):
    """Source-bind all exact counts and controls to the checked-out head."""
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if source_sha != actual:
        raise AssertionError("evidence source SHA differs from checked-out HEAD")
    professional = build_professional_projection()
    shape = run_challenge()
    primary = inspect(professional)
    if primary["declared_activities"] != 160 or primary["authorised_structures"] != 16 or (
            primary["u0"]["raw_placements"], primary["u0"]["flattened"]) != (64068, 64032):
        raise AssertionError("retained 160/120 professional source census changed")
    if any(s["active_activities"] != 120 for s in primary["structures"]):
        raise AssertionError("a selected professional structure is not 120 activities")
    controls = {}
    for name, fixture in (("small_named", small_problem()),
                          ("professional", professional_problem(workface=True, deadline=True)),
                          ("64_48", scale_problem()), ("anonymous_group", build_group_stress())):
        result = schedule_work_method_time(fixture)
        if name in BASE_HASHES and result.plan["plan_hash"] != BASE_HASHES[name]:
            raise AssertionError(f"{name}: merged-main plan hash changed")
        validate_plan(fixture, result.plan)
        observed = inspect(fixture)
        indexed, _ = domains(fixture)
        original = {aid: [row.rank for row in indexed[aid]
            if row.mode == e["mode_id"] and row.start == e["start"] and row.finish == e["finish"] and
               row.periods == tuple(map(tuple, e["periods"])) and
               row.named == tuple(map(tuple, e["assignments"]))]
            for e in result.plan["entries"] for aid in [e["activity_id"]]}
        if any(not ranks or any(rank not in observed["u1"]["retained_original_ranks"][aid]
                                for rank in ranks) for aid, ranks in original.items()):
            raise AssertionError(f"{name}: production placement pruned")
        controls[name] = {"plan_hash": result.plan["plan_hash"], "objective": result.plan["objective"],
            "selected_ranks_survive": True, "selected_original_ranks": original,
            "u0": observed["u0"]["flattened"], "u1": observed["u1"]["flattened"],
            "structures": len(observed["structures"])}
    fixed = solve_fixed_controls(scale_problem())
    authority = schedule_work_method_time(scale_problem()).plan
    if fixed["best"] is None or policy_key(scale_problem(), authority["selected_methods"],
            authority["selected_modes"], authority["objective"]) != policy_key(scale_problem(),
            fixed["best"]["methods"], fixed["best"]["modes"], fixed["best"]["objective"]):
        raise AssertionError("independent 64/48 network policy differs")
    tiny = tiny_problem()
    tiny_rows, _ = domains(tiny)
    tiny_result = tiny_oracle(tiny, tiny_rows)
    s1 = primary["s1_distribution"]
    u0, u1 = primary["u0"]["flattened"], primary["u1"]["flattened"]
    if u1 <= 20000:
        classification, ready, next_step = "A_UNION_PRUNING", "READY", "Falsify/adopt exact union-safe pruning before any activity-admission change."
    elif s1["max"] <= 20000:
        classification, ready, next_step = "B_STRUCTURAL_CONDITIONING", "READY", "Test exact 16-structure conditioned scheduling on 64/48 before attempting 160/120."
    elif u1 - primary["u1"]["temporal_named_patterns"] > primary["u1"]["temporal_named_patterns"]:
        classification, ready, next_step = "D_GROUP_WITNESS", "NOT_READY", "Investigate an exact whole-activity anonymous witness representation."
    elif s1["min"] > 20000:
        classification, ready, next_step = "C_TEMPORAL_PLACEMENTS", "NOT_READY", "Investigate exact temporal-placement representation/preprocessing; do not raise admission."
    else:
        classification, ready, next_step = "G_MIXED_PRESSURE", "NOT_READY", "Investigate the remaining placement and interval pressure in fixed structures."
    return {"source_sha": actual, "base_main": "8a8a2cfae650afc2a064ab7900e358917aea9817",
        "runtime": {"python": platform.python_version(), "ortools": ortools.__version__},
        "production_hashes": BASE_HASHES, "professional_shape": shape["shape"],
        "professional_classifier": shape["authoritative_first_failure"],
        "primary": primary, "controls": controls,
        "independent_64_48": {"fixed_networks": len(fixed["branches"]),
            "objective": fixed["best"]["objective"], "full_policy_equal": True},
        "tiny_oracle": tiny_result,
        "w1_contract": "Repeated FS arc support on current exact local placement domains; all inter-activity resource/workface conflicts relaxed. Every deletion is unsupported by a necessary FS arc; no completeness claim for arbitrary DAGs.",
        "rank_contract": "Every S1/U1 row is indexed by its original U0 one-based per-activity canonical placement rank; retained arrays are sorted original ranks and are never compacted.",
        "decomposition_equivalence": "Enumerate all 16 structures; solve each exactly under finish, the ORIGINAL UNION DECLARED-ORDER global timing weights (inactive starts contribute zero), modes and original placement ranks. Lexicographically select (finish, that union-weighted global timing, declared method digits, mode digits, original placement digits). This equals the integrated policy if all subproblems close exactly; reindexing the active network changes policy.",
        "no_solve_proto": {"performed": False, "reason": "The production compiler enforces 64 activities before model assembly; exact no-solve assembly would require duplicating that compiler or bypassing its public admission."},
        "classification": classification, "first_exact_160_120_solve": ready,
        "recommendation": next_step, "no_professional_solve": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = run_evidence(args.source_sha)
    from pathlib import Path
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
