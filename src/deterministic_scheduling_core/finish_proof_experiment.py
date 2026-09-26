"""Read-only finish-proof diagnostics on fresh copies of the production compiler.

No diagnostic result is an authoritative schedule. The public batched scheduler
and its plan format are deliberately outside this experiment's implementation.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
import json
from math import prod
from pathlib import Path
import platform
from time import perf_counter

import ortools
from ortools.sat.python import cp_model

from deterministic_scheduling_core.canonical_cost_experiment import build_density_ladder, build_stage_ladder
from deterministic_scheduling_core.converged_scale_experiment import build_problem as build_scale
from deterministic_scheduling_core.native_work_method_time import solve_fixed_controls
from deterministic_scheduling_core.professional_scale_challenge import run_challenge
from deterministic_scheduling_core.professional_workface_experiment import build_problem as build_professional
from deterministic_scheduling_core.project.work_method_time import WorkMethodTimeProject, input_hash, materialise
from deterministic_scheduling_core.scheduling.planning_workspace import _group_placements
from deterministic_scheduling_core.scheduling.work_method_time import (
    _compile_work_method_time, _new_solver, policy_key, schedule_work_method_time, validate_plan,
)


BASE_HASHES = {
    "small": "458a5927a645fb2eed8a8ac432c0262d2bfcf23d3ae222a4e9f32d4682569ab5",
    "professional": "61add1ea57ede769cb676aa11f93b31eb5696f8f691b22b22a38b9f146172a7d",
    "scale_64_48": "88f125d76b5cdbe4f18e14834767e964e5b29f2db21a2c839481e1399e21f63f",
}


def _identity(compiled):
    """Text proto digest is stable within one installed OR-Tools environment."""
    proto = compiled.model.proto
    return {
        "proto_text_sha256": sha256(str(proto).encode("utf-8")).hexdigest(),
        "declared_activities": len(compiled.source["activities"]),
        "authorised_structures": prod(len(p.methods) for p in compiled.problem.work_packages),
        "placement_alternatives": compiled.placement_count,
        "workface_intervals": compiled.workface_interval_count,
        "base_variables": len(proto.variables), "base_constraints": len(proto.constraints),
    }


def _proof(compiled, *, bound=None):
    model = compiled.model
    assert not model.has_objective(), "diagnostics must begin with an objective-free base model"
    if bound is None:
        model.minimize(compiled.stages[0].expression)
    else:
        model.add(compiled.stages[0].expression <= bound)
    solver = _new_solver()
    started = perf_counter()
    status = solver.solve(model)
    response = solver.response_proto
    result = {
        "question": "minimise_finish" if bound is None else "finish_at_most",
        "bound": bound, "status": solver.status_name(status),
        "finish": int(solver.value(compiled.stages[0].expression)) if status == cp_model.OPTIMAL else None,
        "wall_observation_ms": (perf_counter() - started) * 1000,
        "solver_wall_ms": float(response.wall_time) * 1000,
        "deterministic_time": float(response.deterministic_time),
        "num_branches": int(response.num_branches), "num_conflicts": int(response.num_conflicts),
        "num_binary_propagations": int(response.num_binary_propagations),
        "num_integer_propagations": int(response.num_integer_propagations),
        "variables": len(model.proto.variables), "constraints": len(model.proto.constraints),
    }
    if status not in (cp_model.OPTIMAL, cp_model.INFEASIBLE):
        raise AssertionError(f"diagnostic solve did not close: {result}")
    return result


def _fix_decisions(compiled, plan, level):
    """Constrain choices in the union model without removing inactive alternatives."""
    count = 0
    if level >= 1:
        for pid, mid in plan["selected_methods"].items():
            compiled.model.add(compiled.methods[pid, mid] == 1)
            count += 1
    if level >= 2:
        for aid, mid in plan["selected_modes"].items():
            compiled.model.add(compiled.mode_vars[aid, mid] == 1)
            count += 1
    if level >= 3:
        entries = {entry["activity_id"]: entry for entry in plan["entries"]}
        for aid, mid in plan["selected_modes"].items():
            target = dict(entries[aid]["assignments"])
            slots = compiled.specs[aid, mid].requirements
            for lit, choice_mid, placement in compiled.choices[aid]:
                if choice_mid != mid:
                    continue
                named = {slot.id: rid for slot, rid in zip(slots, placement.assignments)
                         if not slot.id.startswith("@group/")}
                if named != target:
                    compiled.model.add(lit == 0)
                    count += 1
    return count


def _two_bounds(problem, finish, plan=None, level=0):
    rows = []
    for bound in (finish, finish - 1):
        compiled = _compile_work_method_time(problem)
        base = _identity(compiled)
        added = _fix_decisions(compiled, plan, level) if plan is not None else 0
        result = _proof(compiled, bound=bound)
        rows.append({"base": base, "control_constraints": added,
                     "bound_constraints": 1, "proof": result})
    if rows[0]["proof"]["status"] != "OPTIMAL" or rows[0]["proof"]["finish"] > finish:
        raise AssertionError("known optimum is not attainable under diagnostic controls")
    if rows[1]["proof"]["status"] != "INFEASIBLE":
        raise AssertionError("one-tick-better bound did not prove infeasible")
    return rows


def _fixed_optimum(problem, finish, plan, level, expected_base):
    compiled = _compile_work_method_time(problem)
    if _identity(compiled) != expected_base:
        raise AssertionError("fixed optimization did not begin from identical base proto")
    added = _fix_decisions(compiled, plan, level)
    proof = _proof(compiled)
    if proof["status"] != "OPTIMAL" or proof["finish"] != finish:
        raise AssertionError("fixed optimization changed exact minimum finish")
    return {"base": expected_base, "control_constraints": added, "proof": proof}


def _selected_network(problem, plan):
    """Prune structural and mode alternatives; preserve every timing alternative."""
    project = deepcopy(problem.project)
    active = {a["id"] for a in materialise(problem, plan["selected_methods"])["project"]["activities"]}
    selected = plan["selected_modes"]
    by_entry = {e["activity_id"]: e for e in plan["entries"]}
    project["activities"] = [a for a in project["activities"] if a["id"] in active]
    for activity in project["activities"]:
        activity["modes"] = [m for m in activity["modes"] if m["id"] == selected[activity["id"]]]
        assignments = dict(by_entry[activity["id"]]["assignments"])
        for mode in activity["modes"]:
            for requirement in mode.get("requirements", []):
                if requirement["id"] in assignments:
                    requirement["eligible_resource_ids"] = [assignments[requirement["id"]]]
    packages = tuple(replace(p, methods=tuple(m for m in p.methods
                             if m.id == plan["selected_methods"][p.id])) for p in problem.work_packages)
    return WorkMethodTimeProject(project, packages, deepcopy(problem.reports))


def _census(compiled, plan):
    selected_methods = plan["selected_methods"]
    selected_modes = plan["selected_modes"]
    rows = []
    for activity in compiled.source["activities"]:
        aid = activity["id"]
        active = aid not in compiled.members or compiled.members[aid][1] == selected_methods[compiled.members[aid][0]]
        for mode in activity["modes"]:
            mid = mode["id"]
            spec = compiled.specs[aid, mid]
            raw = _group_placements(compiled.environment, spec, "B")
            surviving = [p for p in raw if p.finish <= activity.get("latest_finish", compiled.environment.horizon)]
            patterns = defaultdict(set)
            named_by_temporal = defaultdict(set)
            named = set()
            full = set()
            for placement in surviving:
                temporal = (placement.start, placement.finish, tuple(placement.periods))
                named_sig = tuple((r.id, rid) for r, rid in zip(spec.requirements, placement.assignments)
                                  if not r.id.startswith("@group/"))
                patterns[temporal].add(placement.assignments)
                named_by_temporal[temporal].add(named_sig)
                named.add(named_sig)
                full.add(placement.assignments)
            counts = [len(variants) for variants in patterns.values()]
            rows.append({"activity_id": aid, "mode_id": mid,
                         "selected": active and selected_modes.get(aid) == mid,
                         "structural_inactive": not active,
                         "mode_inactive": active and selected_modes.get(aid) != mid,
                         "raw": len(raw), "surviving": len(surviving),
                         "unique_starts": len({p.start for p in surviving}),
                         "unique_envelopes": len({(p.start, p.finish) for p in surviving}),
                         "unique_temporal_patterns": len(patterns),
                         "named_temporal_pairs": sum(map(len, named_by_temporal.values())),
                         "unique_named_signatures": len(named),
                         "unique_internal_signatures": len(full),
                         "max_assignment_variants_per_temporal_pattern": max(counts, default=0),
                         "mean_assignment_variants_per_temporal_pattern": sum(counts) / len(counts) if counts else 0})
    total = sum(r["surviving"] for r in rows)
    if total != compiled.placement_count:
        raise AssertionError(f"census/compiler disagreement: {total} != {compiled.placement_count}")
    temporal_total = sum(r["unique_temporal_patterns"] for r in rows)
    named_temporal_total = sum(r["named_temporal_pairs"] for r in rows)
    return {"rows": rows, "total_raw": sum(r["raw"] for r in rows),
            "total_surviving": total,
            "unique_temporal_patterns_within_activity_mode": temporal_total,
            "named_temporal_pairs": named_temporal_total,
            "named_assignment_expansion": named_temporal_total - temporal_total,
            "solver_internal_anonymous_witness_expansion": total - named_temporal_total,
            "structural_inactive_placements": sum(r["surviving"] for r in rows if r["structural_inactive"]),
            "mode_inactive_placements": sum(r["surviving"] for r in rows if r["mode_inactive"]),
            "selected_placements": sum(r["surviving"] for r in rows if r["selected"]),
            "anonymous_group_units_are_internal_witnesses": True}


def _ladder(problem, *, density):
    source_hash = input_hash(problem)
    compiled = _compile_work_method_time(problem)
    base = _identity(compiled)
    optimum = _proof(compiled)
    if optimum["status"] != "OPTIMAL":
        raise AssertionError("ladder optimum not proved")
    result = {"base": base, "finish_optimisation": optimum,
              "source_unchanged": source_hash == input_hash(problem)}
    if density:
        result["bounds"] = _two_bounds(problem, optimum["finish"])
        if any(r["base"] != base for r in result["bounds"]):
            raise AssertionError("density controls used different base models")
    return result


def run_experiment(*, include_classifier=True):
    from deterministic_scheduling_core.native_work_method_time import build_problem as build_small
    fixtures = {"small": build_small(), "professional": build_professional(workface=True, deadline=True),
                "scale_64_48": build_scale()}
    source_hashes = {name: input_hash(p) for name, p in fixtures.items()}
    plans = {name: schedule_work_method_time(p).plan for name, p in fixtures.items()}
    for name, plan in plans.items():
        validate_plan(fixtures[name], plan)
        if plan["plan_hash"] != BASE_HASHES[name]:
            raise AssertionError(f"base-main production plan hash changed: {name}")
    problem = fixtures["scale_64_48"]
    plan = plans["scale_64_48"]
    finish = plan["objective"][0]
    independent = solve_fixed_controls(problem)["best"]
    if independent is None or policy_key(problem, plan["selected_methods"], plan["selected_modes"], plan["objective"]) != policy_key(problem, independent["methods"], independent["modes"], independent["objective"]):
        raise AssertionError("64/48 independent fixed-network control disagrees with authority")
    compiled = _compile_work_method_time(problem)
    base = _identity(compiled)
    census = _census(compiled, plan)
    normal = _proof(compiled)
    if normal["status"] != "OPTIMAL" or normal["finish"] != finish:
        raise AssertionError("fresh finish optimisation disagrees with authoritative finish")
    ladder = {name: _two_bounds(problem, finish, plan, level)
              for level, name in enumerate(("full", "methods", "methods_modes", "methods_modes_named"))}
    for level, (name, rows) in enumerate(ladder.items()):
        # A bounded feasibility query and a minimum proof are distinct questions.
        # Record both before attributing any objective cost to a decision family.
        rows[0]["fixed_finish_optimisation"] = (
            {"base": base, "control_constraints": 0, "proof": normal}
            if level == 0 else _fixed_optimum(problem, finish, plan, level, base))
    if any(r["base"] != base for rows in ladder.values() for r in rows):
        raise AssertionError("union-model controls do not share the exact compiled base proto")
    pruned_problem = _selected_network(problem, plan)
    pruned = _two_bounds(pruned_problem, finish)
    pruned_optimisation = _proof(_compile_work_method_time(pruned_problem))
    if pruned_optimisation["status"] != "OPTIMAL" or pruned_optimisation["finish"] != finish:
        raise AssertionError("selected-network minimum finish differs from authority")
    professional = plans["professional"]
    professional_finish = professional["objective"][0]
    professional_bounds = _two_bounds(fixtures["professional"], professional_finish, professional, 3)
    suspended_problem = build_professional(workface=True)
    suspended_hash = input_hash(suspended_problem)
    suspended_plan = schedule_work_method_time(suspended_problem).plan
    suspended_bounds = _two_bounds(suspended_problem, suspended_plan["objective"][0], suspended_plan, 3)
    a_fast = next(e for e in suspended_plan["entries"] if e["activity_id"] == "A_FAST")
    b_workface = next(e for e in suspended_plan["entries"] if e["activity_id"] == "B")
    if a_fast["periods"] != [[0, 2], [4, 6]] or a_fast["finish"] > b_workface["start"]:
        raise AssertionError("suspended productive execution did not occupy complete workface envelope")
    if not any(e["activity_id"] == "B" and e["finish"] <= 3 for e in professional["entries"]):
        raise AssertionError("professional deadline not exercised")
    active_entries = professional["entries"]
    by_id = {a["id"]: a for a in fixtures["professional"].project["activities"]}
    if any(set(by_id[x["activity_id"]].get("exclusion_groups", [])) & set(by_id[y["activity_id"]].get("exclusion_groups", []))
           and x["start"] < y["finish"] and y["start"] < x["finish"]
           for i, x in enumerate(active_entries) for y in active_entries[i + 1:]):
        raise AssertionError("professional workface envelopes overlap")
    stage = {str(n): _ladder(build_stage_ladder(n), density=False) for n in (8, 16, 32, 48, 64)}
    density = {str(h): _ladder(build_density_ladder(h), density=True) for h in (16, 64, 192, 480)}
    classifier = run_challenge() if include_classifier else None
    if classifier and (classifier["authoritative_first_failure"]["class"] != "ADMISSION_BOUND"
                       or not classifier["faithful_projection_valid"]
                       or classifier["diagnostic_faithful_projection"]["raw_generated_placements"] != 64068
                       or classifier["diagnostic_faithful_projection"]["placement_alternatives"] != 64032):
        raise AssertionError("professional-scale classification changed")
    return {"milestone": "controlling-finish-proof-cost-decomposition-v0",
            "runtime": {"python": platform.python_version(), "ortools": ortools.__version__},
            "authoritative_finish": finish, "base_model": base,
            "normal_finish_optimisation": normal, "decision_freedom_ladder": ladder,
            "pruned_selected_network": {"base": pruned[0]["base"], "bounds": pruned,
                                         "finish_optimisation": pruned_optimisation,
                                         "input_hash": input_hash(pruned_problem)},
            "placement_census": census, "activity_ladder": stage, "density_ladder": density,
            "professional_semantics": {"bounds": professional_bounds,
                                        "selected_methods": professional["selected_methods"],
                                        "entries": professional["entries"],
                                        "suspended_workface": {"bounds": suspended_bounds,
                                                               "productive_periods": a_fast["periods"],
                                                               "envelope": [a_fast["start"], a_fast["finish"]],
                                                               "next_entry_start": b_workface["start"],
                                                               "source_unchanged": suspended_hash == input_hash(suspended_problem)}},
            "production_plan_hashes": {name: p["plan_hash"] for name, p in plans.items()},
            "source_unchanged": all(source_hashes[name] == input_hash(p) for name, p in fixtures.items()),
            "independent_control_matches_policy": True,
            "classification": {
                "category": "D",
                "basis": "The explicit F-1 bound is closed in presolve; finish optimization retains "
                         "material deterministic cost after fixing methods/modes and pruning the selected "
                         "network; fixed-activity placement-density controls show increasing model cost. "
                         "Named assignment choice is absent in this anchor.",
                "next_question": "Exact factored temporal placement/model representation and objective lower bounds",
            },
            "professional_scale": classifier}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run_experiment()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"result": str(args.output), "finish": result["authoritative_finish"],
                      "model": result["base_model"], "production_hashes": result["production_plan_hashes"]}))


if __name__ == "__main__":
    main()
