"""Experimental admissible finish bounds; never imported by production scheduling."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
from time import perf_counter

import ortools
from ortools.sat.python import cp_model

from deterministic_scheduling_core import resource_assignment_experiment as ra
from deterministic_scheduling_core.canonical_cost_experiment import build_density_ladder, build_stage_ladder
from deterministic_scheduling_core.converged_scale_experiment import build_problem as scale_problem
from deterministic_scheduling_core.factored_finish_search_experiment import build_group_stress
from deterministic_scheduling_core.finish_proof_experiment import (
    BASE_HASHES, _fix_decisions, _identity, _selected_network,
)
from deterministic_scheduling_core.native_work_method_time import (
    build_problem as small_problem, solve_fixed_controls,
)
from deterministic_scheduling_core.professional_scale_challenge import run_challenge
from deterministic_scheduling_core.professional_workface_experiment import build_problem as professional_problem
from deterministic_scheduling_core.project.work_method_time import input_hash, materialise, method_selections
from deterministic_scheduling_core.scheduling.work_method_time import (
    _compile_work_method_time, _new_solver, policy_key, schedule_work_method_time,
)
from deterministic_scheduling_core.working_time_experiment import WorkCalendar, SUSPENDABLE


def _objective_proof(problem, lower=None, *, fixed_methods=None, expected_base=None):
    compile_started = perf_counter()
    compiled = _compile_work_method_time(problem)
    compiler_build_ms = (perf_counter() - compile_started) * 1000
    base = _identity(compiled)
    if expected_base is not None and base != expected_base:
        raise AssertionError("objective proof did not use identical pre-control base model")
    controls = _fix_decisions(compiled, fixed_methods, 1) if fixed_methods is not None else 0
    stage = compiled.stages[0].expression
    if lower is not None:
        compiled.model.add(stage >= lower)
    compiled.model.minimize(stage)
    solver = _new_solver()
    started = perf_counter()
    status = solver.solve(compiled.model)
    row = _statistics(solver, status, started, objective=True)
    if status != cp_model.OPTIMAL:
        raise AssertionError(f"finish objective did not prove optimality: {row['status']}")
    row.update({"finish": int(solver.value(stage)), "pre_control_base": base,
                "method_fix_constraints": controls,
                "bound_constraints": int(lower is not None), "injected_lower_bound": lower,
                "compiler_build_wall_ms": compiler_build_ms,
                "compile_plus_proof_wall_ms": compiler_build_ms + row["observed_wall_ms"]})
    return row


def _statistics(solver, status, started, *, objective):
    response = solver.response_proto
    incumbent = float(response.objective_value) if objective and response.solution else None
    bound = float(response.best_objective_bound) if objective else None
    return {
        "status": solver.status_name(status), "incumbent": incumbent,
        "best_objective_bound": bound,
        "integer_gap": (round(incumbent) - round(bound)) if incumbent is not None and bound is not None else None,
        "deterministic_time": float(response.deterministic_time),
        "branches": int(response.num_branches), "conflicts": int(response.num_conflicts),
        "binary_propagations": int(response.num_binary_propagations),
        "integer_propagations": int(response.num_integer_propagations),
        "solver_wall_ms": float(response.wall_time) * 1000,
        "observed_wall_ms": (perf_counter() - started) * 1000,
    }


def objective_progression(problem, budgets, expected_base, optimum):
    rows = []
    for budget in budgets:
        compiled = _compile_work_method_time(problem)
        if _identity(compiled) != expected_base:
            raise AssertionError("objective budget samples have different base models")
        compiled.model.minimize(compiled.stages[0].expression)
        solver = _new_solver()
        solver.parameters.max_deterministic_time = budget
        started = perf_counter()
        status = solver.solve(compiled.model)
        row = _statistics(solver, status, started, objective=True)
        row["budget_deterministic_time"] = budget
        if status == cp_model.OPTIMAL and row["incumbent"] != optimum:
            raise AssertionError("diagnostic optimum disagrees with authority")
        rows.append(row)
    if rows[-1]["status"] != "OPTIMAL" or rows[-1]["integer_gap"] != 0:
        raise AssertionError("last progression sample did not close the exact proof")
    return rows


def _network_lower_bound(problem, level, compiled=None):
    """Earliest finishes in every authorised network with joint conflicts removed.

    Each activity chooses its best local mode after its relaxed predecessors.
    Replacing a feasible full schedule by these earlier local completions cannot
    delay any successor. The minimum over all structures is therefore admissible.
    """
    source = problem.project
    horizon = source["horizon_ticks"]
    calendars = {c["id"]: WorkCalendar(c["id"], tuple(map(tuple, c["daily_windows"]))).slots(horizon)
                 for c in source["calendars"]} if level == 2 else {}
    options = {}
    if level == 3:
        if compiled is None:
            raise ValueError("LB3 requires current compiler placement domains")
        for activity in source["activities"]:
            aid = activity["id"]
            for mode in activity["modes"]:
                options[aid, mode["id"]] = tuple((placement.start, placement.finish)
                                                    for _, mid, placement in compiled.choices[aid]
                                                    if mid == mode["id"])
    best = None
    count = 0
    for selected in method_selections(problem):
        count += 1
        active = materialise(problem, selected)["project"]["activities"]
        by_id = {a["id"]: a for a in active}
        ends = {}
        visiting = set()

        def earliest(aid):
            if aid in ends:
                return ends[aid]
            if aid in visiting:
                raise AssertionError("validated input contains precedence cycle")
            visiting.add(aid)
            a = by_id[aid]
            predecessors = [earliest(p) for p in a.get("predecessors", [])]
            if any(value is None for value in predecessors):
                visiting.remove(aid)
                ends[aid] = None
                return None
            ready = max((a.get("not_before", 0), *predecessors))
            finishes = []
            for mode in a["modes"]:
                if level == 1:
                    finishes.append(ready + mode["processing_ticks"])
                elif level == 2:
                    slots = calendars[mode["calendar_id"]]
                    for start in range(ready, horizon + 1):
                        periods = ra._periods_from_start(start, mode["processing_ticks"], slots,
                                                         mode.get("continuity", SUSPENDABLE), horizon)
                        if periods is not None:
                            finishes.append(periods[-1][1] if periods else start)
                            break
                else:
                    finishes.extend(finish for start, finish in options[aid, mode["id"]]
                                    if start >= ready)
            visiting.remove(aid)
            ends[aid] = min(finishes) if finishes else None
            return ends[aid]

        # A structurally infeasible projection contributes no candidate.
        finish = earliest(source["objective_activity_id"])
        if finish is not None:
            best = finish if best is None else min(best, finish)
    if best is None:
        raise AssertionError("no relaxed structure can reach controlling finish")
    return best, count


def derive_bounds(problem, compiled=None):
    """LB0 local minimum; LB1 logic; LB2 activity calendar; LB3 full local domains."""
    started = perf_counter()
    objective = next(a for a in problem.project["activities"]
                     if a["id"] == problem.project["objective_activity_id"])
    rows = {"LB0": {"value": max(0, objective.get("not_before", 0))
                    + min(m["processing_ticks"] for m in objective["modes"]),
                    "derivation_wall_ms": (perf_counter() - started) * 1000,
                    "enumerated_structures": 0, "placement_domain_rows": 0}}
    for level in (1, 2, 3):
        started = perf_counter()
        value, structures = _network_lower_bound(problem, level, compiled)
        rows[f"LB{level}"] = {"value": value, "derivation_wall_ms": (perf_counter() - started) * 1000,
                              "enumerated_structures": structures,
                              "placement_domain_rows": compiled.placement_count if level == 3 else 0}
    values = [row["value"] for row in rows.values()]
    if values != sorted(values):
        raise AssertionError(f"declared strengthening order is violated: {values}")
    return rows


def _fixture(problem, *, exact_plan=None, injected=False):
    original = input_hash(problem)
    if exact_plan is None:
        exact_plan = schedule_work_method_time(problem).plan
    f = exact_plan["objective"][0]
    compile_started = perf_counter()
    compiled = _compile_work_method_time(problem)
    bound_domain_compilation_ms = (perf_counter() - compile_started) * 1000
    base = _identity(compiled)
    bounds = derive_bounds(problem, compiled)
    if any(row["value"] > f for row in bounds.values()):
        raise AssertionError(f"inadmissible derived lower bound: {bounds}, F={f}")
    for row in bounds.values():
        row["gap_ticks"] = f - row["value"]
    result = {"finish": f, "bounds": bounds, "base": base,
              "source_input_hash": original, "plan_hash": exact_plan["plan_hash"],
              "bound_domain_compilation_wall_ms": bound_domain_compilation_ms,
              "selected_methods": exact_plan["selected_methods"],
              "selected_modes": exact_plan["selected_modes"], "entries": exact_plan["entries"],
              "physical_status": exact_plan["physical_status"],
              "source_unchanged": original == input_hash(problem)}
    if injected:
        baseline = _objective_proof(problem, expected_base=base)
        if baseline["finish"] != f:
            raise AssertionError("fresh baseline finish changed")
        result["baseline_finish_proof"] = baseline
        result["injected"] = {}
        for name, row in bounds.items():
            proof = _objective_proof(problem, row["value"], expected_base=base)
            if proof["finish"] != f:
                raise AssertionError("valid bound changed optimum")
            result["injected"][name] = {
                "proof": proof, "derivation_wall_ms": row["derivation_wall_ms"],
                "total_observed_wall_ms": row["derivation_wall_ms"] + proof["observed_wall_ms"],
                "total_with_shared_domain_compilation_wall_ms": (
                    bound_domain_compilation_ms + row["derivation_wall_ms"]
                    + proof["compile_plus_proof_wall_ms"]),
                "derivation_solver_deterministic_time": 0,
            }
    return result


def run_experiment(*, source_sha=None):
    fixtures = {"small": small_problem(), "professional": professional_problem(workface=True, deadline=True),
                "scale_64_48": scale_problem()}
    originals = {name: input_hash(problem) for name, problem in fixtures.items()}
    production = {name: schedule_work_method_time(problem).plan for name, problem in fixtures.items()}
    hashes = {name: plan["plan_hash"] for name, plan in production.items()}
    if hashes != BASE_HASHES:
        raise AssertionError("verified-base production identity changed")
    anchor_problem = fixtures["scale_64_48"]
    anchor_plan = production["scale_64_48"]
    independent = solve_fixed_controls(anchor_problem)["best"]
    if independent is None or policy_key(anchor_problem, anchor_plan["selected_methods"],
                                         anchor_plan["selected_modes"], anchor_plan["objective"]) != policy_key(
                                             anchor_problem, independent["methods"], independent["modes"],
                                             independent["objective"]):
        raise AssertionError("independent fixed-network policy control disagrees")
    anchor = _fixture(anchor_problem, exact_plan=anchor_plan, injected=True)
    f = anchor["finish"]
    base = anchor["base"]
    if f != 19 or (base["placement_alternatives"], base["base_variables"],
                    base["base_constraints"]) != (5626, 5832, 3860):
        raise AssertionError("retained 64/48 base changed")
    progression = objective_progression(anchor_problem, (.001, .01, .1, .5, 2, 6, 20, 60), base, f)
    oracle = {}
    for lower in sorted({max(0, f - offset) for offset in (f, 8, 4, 2, 1, 0)}):
        row = _objective_proof(anchor_problem, lower, expected_base=base)
        if row["finish"] != f:
            raise AssertionError("oracle bound changed optimum")
        oracle[str(lower)] = row
    methods = {}
    for name, problem, fixed in (
        ("same_union_methods_fixed", anchor_problem, anchor_plan),
        ("selected_network_pruned", _selected_network(anchor_problem, anchor_plan), None),
    ):
        compiled = _compile_work_method_time(problem)
        row = _fixture(problem, injected=False)
        if row["finish"] != f:
            raise AssertionError("selected network/fixed method changed optimum")
        expected_base = base if fixed is not None else row["base"]
        if fixed is not None and row["base"] != base:
            raise AssertionError("method-fixed row is not the original union model")
        row["baseline_finish_proof"] = _objective_proof(problem, fixed_methods=fixed, expected_base=expected_base)
        row["injected"] = {key: _objective_proof(problem, value["value"],
                                                 fixed_methods=fixed, expected_base=expected_base)
                           for key, value in row["bounds"].items()}
        if row["baseline_finish_proof"]["finish"] != f or any(p["finish"] != f for p in row["injected"].values()):
            raise AssertionError("method-fixed objective differs from authority")
        methods[name] = row
    controls = {"small": _fixture(fixtures["small"], exact_plan=production["small"]),
                "professional": _fixture(fixtures["professional"], exact_plan=production["professional"]),
                "suspended_workface": _fixture(professional_problem(workface=True, deadline=False)),
                "anonymous_group": _fixture(build_group_stress())}
    stage = {str(n): _fixture(build_stage_ladder(n), injected=True) for n in (8, 16, 32, 48, 64)}
    density = {str(h): _fixture(build_density_ladder(h), injected=True) for h in (16, 64, 192, 480)}
    classifier = run_challenge()
    projection = classifier["diagnostic_faithful_projection"]
    if classifier["authoritative_first_failure"]["class"] != "ADMISSION_BOUND" or (
        projection["raw_generated_placements"], projection["placement_alternatives"],
        projection["placement_limit"]
    ) != (64068, 64032, 20000):
        raise AssertionError("professional scale classification changed")
    if any(originals[name] != input_hash(problem) for name, problem in fixtures.items()):
        raise AssertionError("source input changed")
    baseline_effort = anchor["baseline_finish_proof"]["deterministic_time"]
    oracle_effort = oracle[str(f)]["deterministic_time"]
    # This is an interpretation of this measured anchor, not a performance gate.
    classification = {
        "category": "E",
        "basis": "The inexpensive LB1 is already equal to F, but even diagnostic finish >= F "
                 "does not change the finish proof's deterministic effort on the retained model. "
                 "Budgeted diagnostic runs had no incumbent through 2 deterministic seconds and "
                 "closed both incumbent and bound by the first OPTIMAL sample; they cannot "
                 "establish an incumbent-before-bound bottleneck.",
        "baseline_finish_deterministic_time": baseline_effort,
        "oracle_finish_deterministic_time": oracle_effort,
        "recommended_next_milestone": "Investigate the finish objective/model formulation and CP-SAT "
                                      "presolve/search behaviour under exact controls; do not adopt a lower "
                                      "bound or change the production algorithm from this evidence.",
    }
    return {"milestone": "exact-controlling-finish-lower-bound-propagation-v0",
            "source_sha": source_sha, "runtime": {"python": platform.python_version(), "ortools": ortools.__version__},
            "production_hashes": hashes, "independent_policy_control": True,
            "anchor": anchor, "objective_progression": progression, "oracle_injection": oracle,
            "method_controls": methods, "controls": controls, "activity_ladder": stage,
            "density_ladder": density, "professional_scale": classifier,
            "classification": classification}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--source-sha")
    args = parser.parse_args()
    result = run_experiment(source_sha=args.source_sha)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "finish": result["anchor"]["finish"],
                      "classification": result["classification"]["category"]}))


if __name__ == "__main__":
    main()
