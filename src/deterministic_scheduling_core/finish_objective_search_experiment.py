"""R0-only finish objective and admissible-LB search controls; never production."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import platform
from time import perf_counter

import ortools
from ortools.sat.python import cp_model

from deterministic_scheduling_core.canonical_cost_experiment import (
    build_density_ladder, build_stage_ladder, semantic_plan,
)
from deterministic_scheduling_core.converged_scale_experiment import build_problem as scale_problem
from deterministic_scheduling_core.factored_finish_search_experiment import (
    _search_finish, build_group_stress,
)
from deterministic_scheduling_core.finish_lower_bound_experiment import _network_lower_bound
from deterministic_scheduling_core.finish_proof_experiment import BASE_HASHES, _identity
from deterministic_scheduling_core.native_work_method_time import (
    build_problem as small_problem, solve_fixed_controls,
)
from deterministic_scheduling_core.professional_scale_challenge import run_challenge
from deterministic_scheduling_core.professional_workface_experiment import build_problem as professional_problem
from deterministic_scheduling_core.project.work_method_time import input_hash
from deterministic_scheduling_core.scheduling.canonical_batching import CanonicalDigit, build_lexicographic_blocks
from deterministic_scheduling_core.scheduling.work_method_time import (
    _canonical_block_stages, _compile_work_method_time, _extract_plan, _new_solver,
    _solve_compiled_stages, policy_key, schedule_work_method_time, validate_plan,
)


def _direct_expression(compiled):
    aid = compiled.source["objective_activity_id"]
    # The unchanged production compiler already imposes this exact equality.
    return sum(placement.finish * literal for literal, _, placement in compiled.choices[aid])


def _semantic_digest(plan):
    return sha256(json.dumps(semantic_plan(plan), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _base_identity(compiled):
    return {**_identity(compiled), "source_input_hash": input_hash(compiled.problem),
            "objective_end_domain": list(compiled.model.proto.variables[
                compiled.ends[compiled.source["objective_activity_id"]].index].domain),
            "objective_placement_literals": len(compiled.choices[compiled.source["objective_activity_id"]])}


def _response(solver, status, started):
    result = solver.response_proto
    return {"status": solver.status_name(status), "deterministic_time": float(result.deterministic_time),
            "branches": int(result.num_branches), "conflicts": int(result.num_conflicts),
            "binary_propagations": int(result.num_binary_propagations),
            "integer_propagations": int(result.num_integer_propagations),
            "solver_wall_ms": float(result.wall_time) * 1000,
            "wall_observation_ms": (perf_counter() - started) * 1000,
            "objective_value": float(result.objective_value) if result.solution and
                                solver.status_name(status) in ("OPTIMAL", "FEASIBLE") else None,
            "best_objective_bound": float(result.best_objective_bound) if result.solution and
                                    solver.status_name(status) in ("OPTIMAL", "FEASIBLE") else None,
            "response_stats": solver.response_stats()}


class _Incumbents(cp_model.CpSolverSolutionCallback):
    """Supported callback observations; final solver status remains the certificate."""

    def __init__(self):
        super().__init__()
        self.rows = []

    def on_solution_callback(self):
        self.rows.append({"objective": float(self.objective_value),
                          "bound_at_incumbent": float(self.best_objective_bound),
                          "solver_wall_ms": float(self.wall_time) * 1000,
                          "deterministic_time": float(self.deterministic_time)})


def _complete(compiled, finish, first, *, solver=None):
    """Keep the authoritative global timing and exact canonical block order."""
    compiled.model.add(compiled.stages[0].expression == finish)
    solver = solver or _new_solver()
    solver, timing, timing_metrics = _solve_compiled_stages(compiled, compiled.stages[1:2], solver=solver)
    blocks = build_lexicographic_blocks(CanonicalDigit(s.name, s.maximum) for s in compiled.stages[2:])
    stages = _canonical_block_stages(compiled, blocks)
    solver, canonical, block_metrics = _solve_compiled_stages(compiled, stages, solver=solver)
    docs = [{**block.to_document(), "solved_value": proof["value"]}
            for block, proof in zip(blocks, canonical)]
    plan, validation = _extract_plan(compiled, solver, [first, *timing, *canonical],
                                     compiler="experimental-finish-objective-search/0",
                                     canonical_blocks=docs)
    validate_plan(compiled.problem, plan)
    vector = [{"name": stage.name, "value": int(solver.value(stage.expression))}
              for stage in compiled.stages]
    if vector[0]["value"] != finish or int(solver.value(_direct_expression(compiled))) != finish:
        raise AssertionError("objective end and direct placement expression disagree")
    return {"semantic_plan": semantic_plan(plan), "semantic_digest": _semantic_digest(plan),
            "canonical_vector": vector, "physical_status": plan["physical_status"],
            "validation": validation, "policy_proofs": timing_metrics + block_metrics,
            "policy_deterministic_time": sum(r["deterministic_time"] for r in timing_metrics + block_metrics)}


def _minimize(problem, formulation, expected_base):
    started = perf_counter()
    compiled = _compile_work_method_time(problem)
    build_ms = (perf_counter() - started) * 1000
    base = _base_identity(compiled)
    if base != expected_base or compiled.model.has_objective():
        raise AssertionError("objective variant did not begin at identical R0 base proto")
    obj = compiled.stages[0].expression if formulation == "C1_end" else _direct_expression(compiled)
    compiled.model.minimize(obj)
    solver = _new_solver()
    incumbents = _Incumbents()
    bound_events = []
    proof_started = perf_counter()
    # Public OR-Tools 9.15 callback: wall observations only, never proof claims.
    solver.best_bound_callback = lambda value: bound_events.append({
        "best_bound": float(value), "elapsed_wall_ms": (perf_counter() - proof_started) * 1000})
    status = solver.solve(compiled.model, incumbents)
    proof = _response(solver, status, proof_started)
    solver.best_bound_callback = None  # Keep subsequent timing/block bounds out of the finish trace.
    if status != cp_model.OPTIMAL:
        raise AssertionError(f"{formulation}: finish objective was not proven OPTIMAL")
    finish = int(solver.value(compiled.stages[0].expression))
    if int(solver.value(obj)) != finish or proof["objective_value"] != finish:
        raise AssertionError("C1/C2 algebraic identity failed at solved assignment")
    first = {"stage": "finish", "value": finish, "status": "OPTIMAL"}
    completed = _complete(compiled, finish, first, solver=solver)
    return {**completed, "finish": finish, "base": base, "formulation": formulation,
            "objective_delta": "minimize end variable" if formulation == "C1_end" else
                               "minimize existing placement-finish linear expression",
            "added_constraints_before_finish": 0,
            "model_build_wall_ms": build_ms, "finish_proof": proof,
            "incumbents": incumbents.rows, "bound_events": bound_events,
            "solver_calls": 1 + len(completed["policy_proofs"]),
            "total_deterministic_time": proof["deterministic_time"] + completed["policy_deterministic_time"],
            "end_to_end_wall_ms": (perf_counter() - started) * 1000}


def _query(compiled, bound, expected_base):
    if _base_identity(compiled) != expected_base:
        raise AssertionError("SAT queries did not share the identical starting compiler base")
    started = perf_counter()
    model = compiled.model.clone()
    finish = model.get_int_var_from_proto_index(
        compiled.ends[compiled.source["objective_activity_id"]].index)
    model.add(finish <= bound)
    clone_ms = (perf_counter() - started) * 1000
    if len(model.proto.constraints) != expected_base["base_constraints"] + 1:
        raise AssertionError("SAT query has more than its declared one bound constraint")
    solver = _new_solver()
    proof_started = perf_counter()
    status = solver.solve(model)
    stats = _response(solver, status, proof_started)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE, cp_model.INFEASIBLE):
        raise AssertionError(f"unclosed SAT bound {bound}: {stats['status']}")
    sat = status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    return {"bound": bound, "satisfaction_status": stats["status"],
            "sat": sat, "feasible_finish": int(solver.value(finish)) if sat else None,
            "bound_constraints": 1, "clone_wall_ms": clone_ms, **stats}


def _seeded_search(compiled, lower, expected_base):
    """SAT at L proves F=L; else double upward, bracket, bisect, verify F/F-1."""
    trace = []
    by_bound = {}

    def query(bound):
        if bound not in by_bound:
            by_bound[bound] = _query(compiled, bound, expected_base)
            trace.append(by_bound[bound])
        return by_bound[bound]["sat"]

    if query(lower):
        finish = lower
        hit = True
        bracket = [lower, lower]
    else:
        hit = False
        infeasible = lower
        step = 1
        horizon = compiled.environment.horizon
        while True:
            upper = min(horizon, lower + step)
            if query(upper):
                break
            if upper == horizon:
                raise AssertionError("no feasible finish in admitted horizon")
            infeasible = upper
            step *= 2
        bracket = [infeasible + 1, upper]
        while infeasible + 1 < upper:
            mid = (infeasible + upper) // 2
            if query(mid):
                upper = mid
            else:
                infeasible = mid
        finish = upper
        if not query(finish) or query(finish - 1):
            raise AssertionError("seeded search failed exact F / F-1 certification")
    return {"lower_bound": lower, "lower_bound_hit": hit, "exact_finish": finish,
            "bracket_after_stepping": bracket, "trace": trace, "query_count": len(trace),
            "query_deterministic_time": sum(r["deterministic_time"] for r in trace),
            "query_wall_observation_ms": sum(r["wall_observation_ms"] for r in trace),
            "clone_wall_ms": sum(r["clone_wall_ms"] for r in trace),
            "proof": "SAT at admissible LB, or SAT at F and UNSAT at F-1"}


def _derive(problem, bound_name, compiled=None):
    level = int(bound_name[-1])
    started = perf_counter()
    value, structures = _network_lower_bound(problem, level, compiled)
    return {"name": bound_name, "value": value,
            "derivation_wall_ms": (perf_counter() - started) * 1000,
            "enumerated_structures": structures,
            "placement_rows_used": compiled.placement_count if level == 3 else 0,
            "derivation_solver_deterministic_time": 0}


def _seeded(problem, bound_name, formulation, expected_base):
    started = perf_counter()
    compiled = _compile_work_method_time(problem)
    base_compile_ms = (perf_counter() - started) * 1000
    if _base_identity(compiled) != expected_base:
        raise AssertionError("S2 did not start from identical objective-free base proto")
    derived = _derive(problem, bound_name, compiled if bound_name == "LB3" else None)
    search = _seeded_search(compiled, derived["value"], expected_base)
    if search["exact_finish"] < derived["value"]:
        raise AssertionError("inadmissible LB: derived lower bound exceeds exact optimum")
    # The search bound is applied to the existing finish end variable for both
    # formulations; C2's direct expression is identically equal on every model
    # assignment, while the full-policy solve below checks it again.
    complete_started = perf_counter()
    fresh = _compile_work_method_time(problem)
    if _base_identity(fresh) != expected_base:
        raise AssertionError("policy completion did not start from identical base proto")
    completion_compile_ms = (perf_counter() - complete_started) * 1000
    first = {"stage": "finish", "value": search["exact_finish"], "status": "OPTIMAL",
             "proof": "admissible lower bound plus closed objective-free SAT/UNSAT queries"}
    completed = _complete(fresh, search["exact_finish"], first)
    return {**completed, "finish": search["exact_finish"], "base": expected_base,
            "formulation": formulation, "bound": derived, "search": search,
            "base_compile_wall_ms": base_compile_ms,
            "completion_compile_wall_ms": completion_compile_ms,
            "solver_calls": search["query_count"] + len(completed["policy_proofs"]),
            "total_deterministic_time": search["query_deterministic_time"] +
                                        completed["policy_deterministic_time"],
            "end_to_end_wall_ms": (perf_counter() - started) * 1000}


def _control(problem, *, formulations=("C1_end", "C2_direct"), all_bounds=True):
    started = perf_counter()
    original_hash = input_hash(problem)
    authority = schedule_work_method_time(problem)
    authoritative_digest = _semantic_digest(authority.plan)
    expected_vector = [{"name": "finish", "value": authority.plan["objective"][0]},
                       {"name": "global_start_timing", "value": authority.plan["objective"][1]}]
    expected_vector += [{"name": r["name"], "value": r["value"]}
                        for r in authority.metrics["canonical_vector"]]
    base = _base_identity(_compile_work_method_time(problem))
    matrix = {}
    for formulation in formulations:
        matrix[f"{formulation}/S0"] = _minimize(problem, formulation, base)
        names = ("LB1", "LB2", "LB3") if all_bounds and formulation == "C1_end" else ("LB1",)
        for bound_name in names:
            matrix[f"{formulation}/S2-{bound_name}"] = _seeded(problem, bound_name, formulation, base)
    for key, cell in matrix.items():
        if (cell["finish"] != authority.plan["objective"][0] or
                cell["semantic_digest"] != authoritative_digest or
                cell["canonical_vector"] != expected_vector or
                cell["physical_status"] != authority.plan["physical_status"]):
            raise AssertionError(f"{key}: complete policy or physical semantics differ")
    if input_hash(problem) != original_hash:
        raise AssertionError("source input mutated")
    return {"finish": authority.plan["objective"][0], "production_hash": authority.plan["plan_hash"],
            "base": base, "source_unchanged": True, "semantic_equal": True,
            "canonical_equal": True, "physical_equal": True, "cells": matrix,
            "end_to_end_wall_ms": (perf_counter() - started) * 1000}


def run_experiment(*, source_sha=None):
    fixtures = {"small": small_problem(), "professional": professional_problem(workface=True, deadline=True),
                "scale_64_48": scale_problem()}
    sources = {name: input_hash(p) for name, p in fixtures.items()}
    anchor = _control(fixtures["scale_64_48"])
    small = _control(fixtures["small"])
    professional = _control(fixtures["professional"])
    if {"small": small["production_hash"], "professional": professional["production_hash"],
        "scale_64_48": anchor["production_hash"]} != BASE_HASHES:
        raise AssertionError("verified merged-main production plan identity changed")
    if anchor["finish"] != 19 or tuple(anchor["base"][x] for x in
        ("placement_alternatives", "base_variables", "base_constraints")) != (5626, 5832, 3860):
        raise AssertionError("64/48 anchor shape or F changed")
    independent = solve_fixed_controls(fixtures["scale_64_48"])["best"]
    plan = schedule_work_method_time(fixtures["scale_64_48"]).plan
    if independent is None or policy_key(fixtures["scale_64_48"], plan["selected_methods"],
                                         plan["selected_modes"], plan["objective"]) != policy_key(
                                             fixtures["scale_64_48"], independent["methods"],
                                             independent["modes"], independent["objective"]):
        raise AssertionError("independent fixed-network control disagrees")
    group = _control(build_group_stress())
    suspended = _control(professional_problem(workface=True, deadline=False))
    activity = {str(n): _control(build_stage_ladder(n), formulations=("C1_end",), all_bounds=False)
                for n in (8, 16, 32, 48, 64)}
    density = {str(h): _control(build_density_ladder(h), formulations=("C1_end",), all_bounds=False)
               for h in (16, 64, 192, 480)}
    historical_started = perf_counter()
    historical = _search_finish(_compile_work_method_time(fixtures["scale_64_48"]))
    historical["end_to_end_wall_ms_including_compile"] = (perf_counter() - historical_started) * 1000
    if historical["exact_finish"] != anchor["finish"]:
        raise AssertionError("PR45 S1 historical helper differs on unchanged R0 model")
    classifier = run_challenge()
    projection = classifier["diagnostic_faithful_projection"]
    if classifier["authoritative_first_failure"]["class"] != "ADMISSION_BOUND" or (
            projection["raw_generated_placements"], projection["placement_alternatives"],
            projection["placement_limit"]) != (64068, 64032, 20000):
        raise AssertionError("professional classifier changed")
    if any(input_hash(p) != sources[name] for name, p in fixtures.items()):
        raise AssertionError("source inputs changed")
    return {"milestone": "exact-finish-objective-formulation-lb-seeded-search-v0",
            "source_sha": source_sha, "runtime": {"python": platform.python_version(),
                                                 "ortools": ortools.__version__},
            "production_hashes": BASE_HASHES, "independent_control": True,
            "anchor": anchor, "small_named": small, "professional": professional,
            "anonymous_group": group, "suspended_workface": suspended,
            "activity_ladder": activity, "density_ladder": density,
            "historical_S1_same_environment": historical, "professional_scale": classifier,
            "classification": {"category": "A", "name": "LB-seeded exact search justified in the admitted controls",
                               "recommended_next_milestone":
                                   "Prove production adoption of exact LB-seeded finish search while retaining "
                                   "the existing objective and full canonical policy; study the small-case overhead."}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-sha")
    args = parser.parse_args()
    result = run_experiment(source_sha=args.source_sha)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "finish": result["anchor"]["finish"],
                      "classification": result["classification"]["category"]}))


if __name__ == "__main__":
    main()
