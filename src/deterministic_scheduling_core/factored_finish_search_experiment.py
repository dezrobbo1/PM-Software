"""Experimental exact finish search and anonymous-group factoring; never production.

The R1 compiler reuses source validation, productive-case compilation, raw
placement generation, canonical block mathematics and independent plan
validation. Its alternate assembly is intentionally local to this experiment.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from copy import deepcopy
from hashlib import sha256
import json
from math import prod
from pathlib import Path
import platform
from time import perf_counter

import ortools
from ortools.sat.python import cp_model

from deterministic_scheduling_core.canonical_cost_experiment import build_density_ladder, build_stage_ladder, semantic_plan
from deterministic_scheduling_core.converged_scale_experiment import build_problem as scale_problem
from deterministic_scheduling_core.finish_proof_experiment import BASE_HASHES
from deterministic_scheduling_core.native_work_method_time import build_problem as small_problem
from deterministic_scheduling_core.project.work_method_time import WorkMethodTimeProject
from deterministic_scheduling_core.professional_scale_challenge import run_challenge, build_professional_projection
from deterministic_scheduling_core.professional_workface_experiment import build_problem as professional_problem
from deterministic_scheduling_core.project.work_method_time import input_hash, membership
from deterministic_scheduling_core.scheduling.canonical_batching import CanonicalDigit, build_lexicographic_blocks
from deterministic_scheduling_core.scheduling.planning_workspace import _group_placements
from deterministic_scheduling_core.scheduling.work_method_time import (
    _CompiledWorkMethodTime, _Stage, _canonical_block_stages, _compile_work_method_time,
    _extract_plan, _mode_cases, _new_solver, _solve_compiled_stages, schedule_work_method_time,
    validate_plan, validate_problem,
)


def _placement_key(placement, slots):
    """Retain named identity because it can change productive opportunities."""
    return (placement.start, placement.finish, placement.periods,
            tuple((r.id, rid) for r, rid in zip(slots, placement.assignments)
                  if not r.id.startswith("@group/")))


def _group_witness(placement, slots):
    return tuple((r.id, rid) for r, rid in zip(slots, placement.assignments)
                 if r.id.startswith("@group/"))


def _placements(environment, spec, activity):
    raw = _group_placements(environment, spec, "B")
    eligible = (p for p in raw if p.finish <= activity.get("latest_finish", environment.horizon))
    return tuple(sorted(eligible, key=lambda p: (
        p.start, p.finish, p.periods, tuple("" if r is None else r for r in p.assignments))))


def model_census(compiled, *, representation=None):
    proto = compiled.model.proto
    result = {
        "proto_text_sha256": sha256(str(proto).encode()).hexdigest(),
        "proto_text_bytes": len(str(proto).encode()),
        "variables": len(proto.variables), "constraints": len(proto.constraints),
        "bool_vars": sum(tuple(v.domain) == (0, 1) for v in proto.variables),
        "int_vars": sum(tuple(v.domain) != (0, 1) for v in proto.variables),
        "optional_intervals": sum(c.has_interval() and len(c.enforcement_literal) > 0 for c in proto.constraints),
        "no_overlap_constraints": sum(c.has_no_overlap() for c in proto.constraints),
        "cumulative_constraints": sum(c.has_cumulative() for c in proto.constraints),
        "flattened_placements": compiled.placement_count,
        "declared_activities": len(compiled.source["activities"]),
        "authorised_structures": prod(len(p.methods) for p in compiled.problem.work_packages),
        "workface_intervals": compiled.workface_interval_count,
        "method_choices": sum(len(p.methods) for p in compiled.problem.work_packages),
        "mode_choices": sum(len(a["modes"]) for a in compiled.source["activities"]),
        "build_ms": (compiled.built_at - compiled.started_at) * 1000,
        "placement_generation_ms": compiled.compile_metrics["placement_generation_ms"],
    }
    if representation is not None:
        result.update(representation)
    return result


def compile_factored(problem):
    """Alternate exact assembly: temporal/named literals plus whole-activity sets.

    A conjunction is present for every legacy placement with a nonempty group
    witness. Both sums (by temporal and by witness) enforce one single set for
    every productive segment. Their actual cross-product cost is counted.
    """
    started = perf_counter()
    problem = deepcopy(problem)
    validate_problem(problem)
    environment, specs = _mode_cases(problem)
    model = cp_model.CpModel()
    source = problem.project
    members = membership(problem)
    methods = {(p.id, m.id): model.new_bool_var(f"method_{i}_{j}")
               for i, p in enumerate(problem.work_packages) for j, m in enumerate(p.methods)}
    for package in problem.work_packages:
        model.add_exactly_one(methods[package.id, m.id] for m in package.methods)
    starts, ends, presence, modes, choices = {}, {}, {}, {}, {}
    occupied = {r.id: [] for r in environment.resources}
    workfaces = defaultdict(list)
    raw_count = face_count = generation_ms = 0
    temporal_count = witness_count = pair_count = actual_face_intervals = 0
    rank_rows = []
    for ai, activity in enumerate(source["activities"]):
        aid = activity["id"]
        present = methods[members[aid]] if aid in members else model.new_constant(1)
        presence[aid] = present
        starts[aid] = model.new_int_var(0, environment.horizon, f"start_{ai}")
        ends[aid] = model.new_int_var(0, environment.horizon, f"end_{ai}")
        choices[aid] = []
        timing_terms = []
        for mi, mode in enumerate(activity["modes"]):
            mid = mode["id"]
            mode_var = model.new_bool_var(f"mode_{ai}_{mi}")
            modes[aid, mid] = mode_var
            spec = specs[aid, mid]
            t0 = perf_counter()
            placements = _placements(environment, spec, activity)
            generation_ms += (perf_counter() - t0) * 1000
            raw_count += len(placements)
            face_count += sum(p.start < p.finish for p in placements) * len(activity.get("exclusion_groups", []))
            if raw_count > 20_000 or face_count > 20_000:
                raise ValueError("retained placement/workface admission exceeded")
            grouped = defaultdict(list)
            witnesses = set()
            for pi, placement in enumerate(placements):
                key = _placement_key(placement, spec.requirements)
                witness = _group_witness(placement, spec.requirements)
                grouped[key].append((pi, placement, witness))
                if witness:
                    witnesses.add(witness)
            temporal_vars = {key: model.new_bool_var(f"temporal_{ai}_{mi}_{i}")
                             for i, key in enumerate(grouped)}
            temporal_count += len(temporal_vars)
            model.add(sum(temporal_vars.values()) == mode_var)
            witness_vars = {w: model.new_bool_var(f"witness_{ai}_{mi}_{i}")
                            for i, w in enumerate(sorted(witnesses))}
            witness_count += len(witness_vars)
            if witness_vars:
                model.add(sum(witness_vars.values()) == mode_var)
            witness_pairs = defaultdict(list)
            rank_literals = {}
            for key, variants in grouped.items():
                temporal = temporal_vars[key]
                start, finish, periods, named = key
                timing_terms.append((start, finish, temporal))
                if start < finish:
                    for face in activity.get("exclusion_groups", []):
                        actual_face_intervals += 1
                        workfaces[face].append(model.new_optional_interval_var(
                            start, finish - start, finish, temporal, f"face_{ai}_{mi}_{start}_{face}"))
                for slot, rid in named:
                    for si, (begin, end) in enumerate(periods):
                        occupied[rid].append(model.new_optional_interval_var(
                            begin, end - begin, end, temporal, f"named_{ai}_{mi}_{start}_{slot}_{si}"))
                pair_literals = []
                for pi, placement, witness in variants:
                    if witness:
                        pair = model.new_bool_var(f"pair_{ai}_{mi}_{pi}")
                        pair_count += 1
                        pair_literals.append(pair)
                        witness_pairs[witness].append(pair)
                        model.add(pair <= temporal)
                        model.add(pair <= witness_vars[witness])
                        # The two equalities below ensure pair == temporal AND witness
                        # for compatible pairs, and prohibit incompatible combinations.
                        for ri, rid in witness:
                            for si, (begin, end) in enumerate(placement.periods):
                                occupied[rid].append(model.new_optional_interval_var(
                                    begin, end - begin, end, pair,
                                    f"group_{ai}_{mi}_{pi}_{ri}_{si}"))
                    else:
                        pair = temporal
                    rank_literals[pi] = pair
                    rank_rows.append((aid, mid, pi, key, witness))
                if pair_literals:
                    model.add(sum(pair_literals) == temporal)
            for witness, lit in witness_vars.items():
                model.add(sum(witness_pairs[witness]) == lit)
            for pi, placement in enumerate(placements):
                choices[aid].append((rank_literals[pi], mid, placement))
        model.add(sum(modes[aid, m["id"]] for m in activity["modes"]) == present)
        model.add(starts[aid] == sum(start * lit for start, _, lit in timing_terms))
        model.add(ends[aid] == sum(end * lit for _, end, lit in timing_terms))
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
                for prior in packages[predecessor].methods:
                    for root in roots:
                        model.add(starts[root] >= ends[prior.completion_activity_id]).only_enforce_if(
                            [methods[package.id, method.id], methods[predecessor, prior.id]])
    for intervals in (*occupied.values(), *workfaces.values()):
        if intervals:
            model.add_no_overlap(intervals)
    timing = sum((i + 1) * starts[a["id"]] for i, a in enumerate(source["activities"]))
    stages = [_Stage("finish", "finish", ends[source["objective_activity_id"]], environment.horizon),
              _Stage("global_start_timing", "global_timing", timing,
                     environment.horizon * sum(range(1, len(source["activities"]) + 1)))]
    stages.extend(_Stage(f"method:{p.id}", "method_canonical",
                         sum(i * methods[p.id, m.id] for i, m in enumerate(p.methods)), len(p.methods) - 1)
                  for p in problem.work_packages)
    stages.extend(_Stage(f"mode:{a['id']}", "mode_canonical",
                         sum((i + 1) * modes[a["id"], m["id"]] for i, m in enumerate(a["modes"])), len(a["modes"]))
                  for a in source["activities"])
    stages.extend(_Stage(f"placement:{a['id']}", "placement_canonical",
                         sum((i + 1) * lit for i, (lit, _, _) in enumerate(choices[a["id"]])), len(choices[a["id"]]))
                  for a in source["activities"])
    built = perf_counter()
    compiled = _CompiledWorkMethodTime(problem, environment, specs, model, source, members, methods, starts,
                                        ends, modes, choices, tuple(stages), raw_count, face_count,
                                        started, built, {"placement_generation_ms": generation_ms})
    representation = {"temporal_named_choices": temporal_count, "anonymous_witness_choices": witness_count,
                      "conjunction_pair_vars": pair_count,
                      "actual_workface_intervals": actual_face_intervals,
                      "retained_flattened_workface_bound_count": face_count,
                      "flattened_rank_rows": len(rank_rows),
                      "rank_mapping_sha256": sha256(repr(rank_rows).encode()).hexdigest()}
    return compiled, representation


def _stats(solver, status, elapsed_ms, *, bound=None, finish=None):
    response = solver.response_proto
    return {"bound": bound, "status": solver.status_name(status), "feasible_finish": finish,
            "wall_observation_ms": elapsed_ms, "solver_wall_ms": float(response.wall_time) * 1000,
            "deterministic_time": float(response.deterministic_time),
            "branches": int(response.num_branches), "conflicts": int(response.num_conflicts),
            "binary_propagations": int(response.num_binary_propagations),
            "integer_propagations": int(response.num_integer_propagations)}


def _search_finish(compiled):
    """Exact monotone integer search; no authoritative F is passed in."""
    base = compiled.model
    if base.has_objective():
        raise AssertionError("S1 requires an objective-free compiler base")
    finish_index = compiled.ends[compiled.source["objective_activity_id"]].index
    trace = []
    cache = {}

    def query(bound):
        if bound in cache:
            return cache[bound]
        model = base.clone()
        finish = model.get_int_var_from_proto_index(finish_index)
        model.add(finish <= bound)
        solver = _new_solver()
        started = perf_counter()
        status = solver.solve(model)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE, cp_model.INFEASIBLE):
            raise AssertionError(f"finish-bound query did not close: {solver.status_name(status)}")
        feasible = status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        row = _stats(solver, status, (perf_counter() - started) * 1000,
                     bound=bound, finish=int(solver.value(finish)) if feasible else None)
        trace.append(row)
        cache[bound] = feasible
        return feasible

    lower, upper = 0, compiled.environment.horizon
    if not query(upper):
        raise AssertionError("no feasible schedule by the admitted horizon")
    while lower < upper:
        middle = (lower + upper) // 2
        if query(middle):
            upper = middle
        else:
            lower = middle + 1
    optimum = lower
    if not query(optimum) or (optimum > 0 and query(optimum - 1)):
        raise AssertionError("bounded search failed to prove integer optimum")
    return {"initial_lower": 0, "initial_upper": compiled.environment.horizon,
            "exact_finish": optimum, "trace": trace, "query_count": len(trace),
            "total_deterministic_time": sum(row["deterministic_time"] for row in trace),
            "total_wall_observation_ms": sum(row["wall_observation_ms"] for row in trace),
            "finish_feasible": True, "one_tick_better_infeasible": optimum == 0 or not cache[optimum - 1]}


def _plan_signature(plan):
    return sha256(json.dumps(semantic_plan(plan), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _rank_check(reference, challenger):
    """Compare every original sorted alternative, not only the chosen rank."""
    if list(reference.choices) != list(challenger.choices):
        raise AssertionError("activity rank domains differ")
    count = 0
    for aid in reference.choices:
        lhs, rhs = reference.choices[aid], challenger.choices[aid]
        if len(lhs) != len(rhs):
            raise AssertionError(f"{aid}: placement rank count changed")
        for rank, ((_, m0, p0), (_, m1, p1)) in enumerate(zip(lhs, rhs), 1):
            if m0 != m1 or p0 != p1:
                raise AssertionError(f"{aid}: flattened rank {rank} changed")
            count += 1
    return {"all_ranks_match": True, "compared_flattened_ranks": count}


def _complete(compiled, *, search):
    """Prove all original policy stages; S1 fixes its discovered finish first."""
    base = model_census(compiled)
    started = perf_counter()
    trace = _search_finish(compiled) if search else None
    if trace is None:
        solver, first, first_metrics = _solve_compiled_stages(compiled, compiled.stages[:1])
    else:
        compiled.model.add(compiled.stages[0].expression == trace["exact_finish"])
        solver = _new_solver()
        first = [{"stage": "finish", "value": trace["exact_finish"], "status": "OPTIMAL",
                  "proof": "exact satisfiable F and infeasible F-1 integer bound queries"}]
        first_metrics = []
    solver, timing, timing_metrics = _solve_compiled_stages(compiled, compiled.stages[1:2], solver=solver)
    blocks = build_lexicographic_blocks(CanonicalDigit(s.name, s.maximum) for s in compiled.stages[2:])
    stages = _canonical_block_stages(compiled, blocks)
    solver, canonical, block_metrics = _solve_compiled_stages(compiled, stages, solver=solver)
    proof = first + timing + canonical
    block_documents = [{**block.to_document(), "solved_value": solved["value"]}
                       for block, solved in zip(blocks, canonical)]
    plan, validation = _extract_plan(compiled, solver, proof,
                                     compiler="experimental-factored-finish-search/0",
                                     canonical_blocks=block_documents)
    validate_plan(compiled.problem, plan)
    stages_metrics = first_metrics + timing_metrics + block_metrics
    vector = [{"name": s.name, "value": int(solver.value(s.expression))} for s in compiled.stages]
    if trace is not None and vector[0]["value"] != trace["exact_finish"]:
        raise AssertionError("full-policy completion did not attain searched finish")
    return {"finish": vector[0]["value"], "search": trace, "base": base,
            "stage_metrics": stages_metrics, "solver_calls": len(stages_metrics) + (trace["query_count"] if trace else 0),
            "solve_deterministic_time": sum(r["deterministic_time"] for r in stages_metrics)
                                        + (trace["total_deterministic_time"] if trace else 0),
            "canonical_vector": vector, "semantic_plan_sha256": _plan_signature(plan),
            "semantic_plan": semantic_plan(plan),
            "physical_status": plan["physical_status"], "independent_validation_ms": validation,
            "end_to_end_wall_observation_ms": (perf_counter() - started) * 1000,
            "block_count": len(blocks)}


def _bounds(compiled, finish):
    """Independent objective-free F/F-1 witnesses for either representation."""
    result = []
    index = compiled.ends[compiled.source["objective_activity_id"]].index
    for bound in (finish, finish - 1):
        model = compiled.model.clone()
        model.add(model.get_int_var_from_proto_index(index) <= bound)
        solver = _new_solver()
        started = perf_counter()
        status = solver.solve(model)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE, cp_model.INFEASIBLE):
            raise AssertionError("inconclusive F/F-1 proof")
        result.append(_stats(solver, status, (perf_counter() - started) * 1000, bound=bound,
                             finish=int(solver.value(model.get_int_var_from_proto_index(index)))
                             if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) else None))
    if result[0]["status"] not in ("OPTIMAL", "FEASIBLE") or result[1]["status"] != "INFEASIBLE":
        raise AssertionError("representation differs on F/F-1 feasibility")
    return result


def _matrix(problem, *, authority=None):
    before = input_hash(problem)
    authoritative = authority or schedule_work_method_time(problem)
    reference = _compile_work_method_time(problem)
    challenger, representation = compile_factored(problem)
    rank = _rank_check(reference, challenger)
    census = {"R0": model_census(reference), "R1": model_census(challenger, representation=representation)}
    results = {}
    for representation_name, compile_again in (("R0", _compile_work_method_time),
                                                ("R1", lambda p: compile_factored(p)[0])):
        for strategy, search in (("S0", False), ("S1", True)):
            results[f"{representation_name}/{strategy}"] = _complete(compile_again(problem), search=search)
            if results[f"{representation_name}/{strategy}"]["base"]["proto_text_sha256"] != (
                census[representation_name]["proto_text_sha256"]
            ):
                raise AssertionError("matrix cell did not start from its declared representation base")
            if results[f"{representation_name}/{strategy}"]["finish"] != authoritative.plan["objective"][0]:
                raise AssertionError("matrix finish changed")
    sem = _plan_signature(authoritative.plan)
    expected_vector = [{"name": "finish", "value": authoritative.plan["objective"][0]},
                       {"name": "global_start_timing", "value": authoritative.plan["objective"][1]}]
    expected_vector.extend({"name": d["name"], "value": d["value"]}
                           for d in authoritative.metrics["canonical_vector"])
    for name, cell in results.items():
        if cell["semantic_plan_sha256"] != sem or cell["canonical_vector"] != expected_vector:
            raise AssertionError(f"{name}: exact semantic plan or canonical vector differs")
    if before != input_hash(problem):
        raise AssertionError("experiment mutated source input")
    bound_results = {name: _bounds(compiler(problem), authoritative.plan["objective"][0])
                     for name, compiler in (("R0", _compile_work_method_time),
                                            ("R1", lambda p: compile_factored(p)[0]))}
    return {"authoritative_finish": authoritative.plan["objective"][0],
            "authoritative_hash": authoritative.plan["plan_hash"], "model_census": census,
            "rank": rank, "cells": results, "independent_bounds": bound_results,
            "semantic_equal": True, "canonical_equal": True, "physical_equal": True,
            "source_unchanged": True}


def build_group_stress():
    """Three pairwise conflicting, noncontiguous work sets form an odd cycle."""
    activities = []
    for aid, calendar, not_before in (("A", "A", 0), ("B", "B", 0), ("C", "C", 1)):
        activities.append({"id": aid, "name": aid, "not_before": not_before,
                           "modes": [{"id": "GROUP", "processing_ticks": 2, "calendar_id": calendar,
                                      "continuity": "SUSPENDABLE_AT_AVAILABILITY_GAPS",
                                      "requirements": [], "group_requirements": [{"group_id": "CREW", "demand": 1}]}]})
    activities.append({"id": "DONE", "name": "Handoff", "predecessors": ["A", "B", "C"],
                       "modes": [{"id": "FIXED", "processing_ticks": 0, "calendar_id": "ALWAYS",
                                  "continuity": "SUSPENDABLE_AT_AVAILABILITY_GAPS",
                                  "requirements": [], "group_requirements": []}]})
    return WorkMethodTimeProject({
        "id": "anonymous-set-odd-cycle", "name": "Whole-activity witness stress", "horizon_ticks": 6,
        "calendars": [{"id": "A", "daily_windows": [[0, 1], [2, 3], [4, 6]]},
                      {"id": "B", "daily_windows": [[0, 2], [4, 6]]},
                      {"id": "C", "daily_windows": [[1, 3], [4, 6]]},
                      {"id": "ALWAYS", "daily_windows": [[0, 6]]}],
        "resources": [], "resource_groups": [{"id": "CREW", "name": "Interchangeable crew",
                                              "capacity": 2, "calendar_id": "ALWAYS",
                                              "disjoint": True, "interchangeable": True}],
        "activities": activities, "objective_activity_id": "DONE", "pool_riggers": False,
    })


def _stress_fixed_start_status(compiler, problem):
    compiled = compiler(problem)
    for aid, start in (("A", 0), ("B", 0), ("C", 1)):
        compiled.model.add(compiled.starts[aid] == start)
    solver = _new_solver()
    status = solver.solve(compiled.model)
    if status != cp_model.INFEASIBLE:
        raise AssertionError("odd-cycle group witness invalidly changes identity between segments")
    return solver.status_name(status)


def independent_group_oracle(problem):
    """Direct raw-tick, two-colour exhaustive control; no candidate helper or CP-SAT."""
    options = {}
    for activity in problem.project["activities"][:-1]:
        cal = next(c for c in problem.project["calendars"] if c["id"] == activity["modes"][0]["calendar_id"])
        available = {tick for left, right in cal["daily_windows"] for tick in range(left, right)}
        rows = []
        for start in range(activity.get("not_before", 0), 7):
            if start not in available:
                continue
            ticks = tuple(t for t in sorted(available) if t >= start)[:2]
            if len(ticks) != 2:
                continue
            periods = []
            for tick in ticks:
                if periods and periods[-1][1] == tick:
                    periods[-1] = (periods[-1][0], tick + 1)
                else:
                    periods.append((tick, tick + 1))
            for unit in (0, 1):
                rows.append((start, ticks[-1] + 1, tuple(periods), unit, ticks))
        options[activity["id"]] = sorted(rows, key=lambda r: (r[0], r[1], r[2], r[3]))
    from itertools import product
    best = None
    feasible = 0
    feasible_ranks = set()
    temporal_without_witness = 0
    for choices in product(*(options[aid] for aid in ("A", "B", "C"))):
        finish = max(row[1] for row in choices)
        if finish > 6:
            continue
        units = [row[3] for row in choices]
        ticks = [set(row[4]) for row in choices]
        if any(ticks[i] & ticks[j] and units[i] == units[j]
               for i in range(3) for j in range(i + 1, 3)):
            temporal_without_witness += 1
            continue
        for done in range(finish, 7):
            feasible += 1
            timing = sum((i + 1) * choices[i][0] for i in range(3)) + 4 * done
            ranks = tuple(options[aid].index(choices[i]) + 1 for i, aid in enumerate(("A", "B", "C")))
            feasible_ranks.add((*ranks, done + 1))
            key = (done, timing, (1, 1, 1, 1), (*ranks, done + 1))
            if best is None or key < best:
                best = key
    # At these fixed starts, the three sets meet pairwise across distinct ticks.
    fixed = [r for r in product(*(options[aid] for aid in ("A", "B", "C")))
             if (r[0][0], r[1][0], r[2][0]) == (0, 0, 1)]
    if not fixed or any(all(not (set(row[i][4]) & set(row[j][4]) and row[i][3] == row[j][3])
                            for i in range(3) for j in range(i + 1, 3)) for row in fixed):
        raise AssertionError("raw odd-cycle oracle did not exclude every two-colour combination")
    return {"best_policy": best, "feasible_complete_choices": feasible,
            "feasible_rank_tuples": sorted(feasible_ranks),
            "rejected_group_witness_choices": temporal_without_witness,
            "fixed_start_combinations_rejected": len(fixed)}


def _enumerate_stress_ranks(compiled):
    """Exhaustive solution collection is a control, never a production solve."""
    class Collector(cp_model.CpSolverSolutionCallback):
        def __init__(self):
            super().__init__()
            self.ranks = set()

        def on_solution_callback(self):
            self.ranks.add(tuple(next(i for i, (lit, _, _) in enumerate(compiled.choices[aid], 1)
                                      if self.value(lit)) for aid in ("A", "B", "C", "DONE")))

    solver = _new_solver()
    solver.parameters.enumerate_all_solutions = True
    result = Collector()
    status = solver.solve(compiled.model, result)
    if status != cp_model.OPTIMAL:
        raise AssertionError("stress solution enumeration was not complete")
    return {"status": solver.status_name(status), "ranks": sorted(result.ranks),
            "deterministic_time": float(solver.response_proto.deterministic_time)}


def _ladder(problem):
    original_hash = input_hash(problem)
    r0 = _compile_work_method_time(problem)
    optimum_solver, proof, stages = _solve_compiled_stages(r0, r0.stages[:1])
    f = proof[0]["value"]
    r1 = _compile_work_method_time(problem)
    search = _search_finish(r1)
    if search["exact_finish"] != f or original_hash != input_hash(problem):
        raise AssertionError("S0/S1 ladder optimum or source changed")
    return {"activities": len(problem.project["activities"]), "placements": r0.placement_count,
            "S0": stages[0], "S1": search, "exact_finish": f}


def _professional_census():
    problem = build_professional_projection()
    environment, specs = _mode_cases(problem)  # Diagnostic only: no admission or solver call.
    raw = eligible = temporal = witnesses = pairs = 0
    for activity in problem.project["activities"]:
        for mode in activity["modes"]:
            spec = specs[activity["id"], mode["id"]]
            candidates = _group_placements(environment, spec, "B")
            raw += len(candidates)
            surviving = [p for p in candidates if p.finish <= activity.get("latest_finish", environment.horizon)]
            eligible += len(surviving)
            temporal += len({_placement_key(p, spec.requirements) for p in surviving})
            witnesses += len({_group_witness(p, spec.requirements) for p in surviving
                              if _group_witness(p, spec.requirements)})
            pairs += sum(bool(_group_witness(p, spec.requirements)) for p in surviving)
    return {"raw_flattened": raw, "eligible_flattened": eligible, "temporal_named_choices": temporal,
            "anonymous_witness_choices": witnesses, "conjunction_pair_vars_if_admitted": pairs,
            "model_not_built_or_solved": True}


def run_experiment(*, source_sha=None):
    started = perf_counter()
    sources = {"small": small_problem(), "professional": professional_problem(workface=True, deadline=True),
               "scale_64_48": scale_problem()}
    hashes = {name: input_hash(problem) for name, problem in sources.items()}
    production = {name: schedule_work_method_time(problem) for name, problem in sources.items()}
    if {name: result.plan["plan_hash"] for name, result in production.items()} != BASE_HASHES:
        raise AssertionError("base-main production plan identity changed")
    anchor = _matrix(sources["scale_64_48"], authority=production["scale_64_48"])
    named = _matrix(sources["small"], authority=production["small"])
    professional = _matrix(sources["professional"], authority=production["professional"])
    suspended_source = professional_problem(workface=True, deadline=False)
    suspended = _matrix(suspended_source)
    a = next(e for e in suspended["cells"]["R1/S1"]["semantic_plan"]["entries"]
             if e["activity_id"] == "A_FAST")
    b = next(e for e in suspended["cells"]["R1/S1"]["semantic_plan"]["entries"]
             if e["activity_id"] == "B")
    if a["periods"] != [[0, 2], [4, 6]] or b["start"] < a["finish"]:
        raise AssertionError("factored workface occupancy did not include suspension gap")
    stress_source = build_group_stress()
    stress = _matrix(stress_source)
    oracle = independent_group_oracle(stress_source)
    policy = stress["cells"]["R0/S0"]["canonical_vector"]
    key = (policy[0]["value"], policy[1]["value"],
           tuple(v["value"] for v in policy if v["name"].startswith("mode:")),
           tuple(v["value"] for v in policy if v["name"].startswith("placement:")))
    if key != tuple(oracle["best_policy"]):
        raise AssertionError("independent raw tick + group witness oracle disagrees with CP-SAT")
    stress["independent_oracle"] = oracle
    enumerated = {"R0": _enumerate_stress_ranks(_compile_work_method_time(stress_source)),
                  "R1": _enumerate_stress_ranks(compile_factored(stress_source)[0])}
    if any(row["ranks"] != oracle["feasible_rank_tuples"] for row in enumerated.values()):
        raise AssertionError("factored/legacy feasible complete choices differ from direct enumeration")
    stress["complete_feasible_rank_sets"] = {
        name: {"count": len(row["ranks"]), "status": row["status"],
               "sha256": sha256(repr(row["ranks"]).encode()).hexdigest(),
               "deterministic_time": row["deterministic_time"]} for name, row in enumerated.items()}
    stress["fixed_starts"] = {"R0": _stress_fixed_start_status(_compile_work_method_time, stress_source),
                              "R1": _stress_fixed_start_status(lambda p: compile_factored(p)[0], stress_source)}
    activity_ladder = {str(n): _ladder(build_stage_ladder(n)) for n in (8, 16, 32, 48, 64)}
    density_ladder = {str(h): _ladder(build_density_ladder(h)) for h in (16, 64, 192, 480)}
    classification = run_challenge()
    diagnostic_census = _professional_census()
    if classification["authoritative_first_failure"]["class"] != "ADMISSION_BOUND" or (
        classification["diagnostic_faithful_projection"]["raw_generated_placements"],
        classification["diagnostic_faithful_projection"]["placement_alternatives"]
    ) != (64_068, 64_032) or (diagnostic_census["raw_flattened"], diagnostic_census["eligible_flattened"]) != (64_068, 64_032):
        raise AssertionError("professional 160/120 classification changed")
    if any(hashes[name] != input_hash(problem) for name, problem in sources.items()):
        raise AssertionError("experiment changed source")
    return {"milestone": "exact-finish-search-factored-placement-v0", "source_sha": source_sha,
            "runtime": {"python": platform.python_version(), "ortools": ortools.__version__},
            "production_hashes": BASE_HASHES, "authoritative_finish": anchor["authoritative_finish"],
            "matrix": anchor, "named_resource_control": named,
            "professional_control": professional, "suspended_workface_control": suspended,
            "group_stress_control": stress, "activity_ladder": activity_ladder,
            "density_ladder": density_ladder, "professional_scale": classification,
            "professional_factored_diagnostic_census": diagnostic_census,
            "classification": {"category": "E", "reason": "Bound search incurs extra full-model queries; factoring "
                               "retains pair literals and adds witness/temporal literals and constraints. "
                               "Neither demonstrates a material independent model/proof advantage on the anchor.",
                               "recommended_next_milestone": "Investigate objective lower-bound propagation with exact controls "
                               "before considering production representation or policy changes."},
            "end_to_end_wall_observation_ms": (perf_counter() - started) * 1000}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--source-sha")
    args = parser.parse_args()
    result = run_experiment(source_sha=args.source_sha)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "finish": result["authoritative_finish"],
                      "classification": result["classification"]["category"]}))


if __name__ == "__main__":
    main()
