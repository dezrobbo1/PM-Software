"""Exact W1 model integration falsification. Never imported by production.

The compact assembly below is a bounded experimental copy of the placement and
constraint assembly in scheduling.work_method_time._compile_work_method_time.
Every generated original placement is checked against the PR #51 Row before a
literal is created. All non-placement constraints and policy stages match the
production compiler; tests compare the resulting full semantic plans.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from hashlib import sha256
import json
from math import prod
import platform
import subprocess
from tempfile import NamedTemporaryFile
from time import perf_counter
from pathlib import Path

import ortools
from ortools.sat.python import cp_model

from deterministic_scheduling_core.converged_scale_experiment import build_problem as scale_problem
from deterministic_scheduling_core.factored_finish_search_experiment import build_group_stress
from deterministic_scheduling_core.native_work_method_time import build_problem as small_problem, solve_fixed_controls
from deterministic_scheduling_core.professional_scale_challenge import build_professional_projection
from deterministic_scheduling_core.professional_workface_experiment import build_problem as professional_problem
from deterministic_scheduling_core.professional_admission_architecture import (
    BASE_HASHES, census, domains, inspect as domain_inspect, window_prune,
)
from deterministic_scheduling_core.errors import SchedulingError
from deterministic_scheduling_core.project.model import WorkPackage
from deterministic_scheduling_core.project.planning_workspace import validate as validate_workspace
from deterministic_scheduling_core.project.work_method_time import (
    WorkMethodTimeProject, from_document, input_hash, materialise, membership,
    method_selections, structural_view, to_document,
)
from deterministic_scheduling_core.scheduling.engine import validate_project
from deterministic_scheduling_core.scheduling.planning_workspace import _group_placements
from deterministic_scheduling_core.scheduling.canonical_batching import CanonicalDigit, build_lexicographic_blocks
from deterministic_scheduling_core.scheduling.finish_lower_bound import authorised_precedence_lower_bound
from deterministic_scheduling_core.scheduling.finish_search import prove_finish
from deterministic_scheduling_core.scheduling.work_method_time import (
    MAX_DETERMINISTIC_TIME_PER_STAGE, MAX_WORKFACE_INTERVALS, _CompiledWorkMethodTime,
    _Stage, _canonical_block_stages, _compile_work_method_time, _extract_plan,
    _mode_cases, _new_solver, _solve_compiled_stages, policy_key,
    schedule_work_method_time, validate_plan, validate_problem,
)

BASE_MAIN = "1e127d14f625a19c98410211980494cc44b3abfb"


def validate_experimental(problem: WorkMethodTimeProject, *, limit: int = 160) -> None:
    """Reproduce production admission, replacing only the declared count cap."""
    if limit != 160:
        raise AssertionError("experimental activity limit must stay 160")
    if not isinstance(problem, WorkMethodTimeProject):
        raise ValueError("expected WorkMethodTimeProject, not a statused workspace")
    from_document(to_document(problem))
    source = problem.project
    if not isinstance(source.get("activities"), list) or not 1 <= len(source["activities"]) <= limit:
        raise ValueError("experimental composition requires 1..160 declared activities")
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
        validate_workspace(materialise(problem, selected), allow_future_constraints=True)
    members = membership(problem)
    fixed_packages = {package.id for package in problem.work_packages if len(package.methods) == 1}
    for activity in source["activities"]:
        latest = activity.get("latest_finish")
        owner = members.get(activity["id"])
        if latest is not None and (owner is None or owner[0] in fixed_packages):
            if activity.get("not_before", 0) + min(m["processing_ticks"] for m in activity["modes"]) > latest:
                raise ValueError(f"{activity['id']}: fixed activity cannot finish by latest_finish from not_before")


def w1_domain(problem):
    """Reuse PR #51 domains and W1, unioning all authorised structures."""
    indexed, detail = domains(problem)
    retained = {aid: set() for aid in indexed}
    selections = list(method_selections(problem))
    for selected in selections:
        allowed, _ = window_prune(materialise(problem, selected)["project"], indexed)
        for aid, ranks in allowed.items():
            retained[aid].update(ranks)
    return indexed, retained, detail, len(selections)


def _snapshot(compiled):
    """Actual CP-SAT proto counts at a named assembly boundary."""
    proto = compiled.model.proto
    with NamedTemporaryFile(suffix=".pb") as artifact:
        if not compiled.model.export_to_file(artifact.name):
            raise AssertionError("OR-Tools could not serialize the actual model proto")
        serialized_bytes = Path(artifact.name).stat().st_size
    return {"variables": len(proto.variables), "constraints": len(proto.constraints),
            "serialized_bytes": serialized_bytes}


def _same_placement(row, aid, mid, rank, placement):
    return (row.aid == aid and row.mode == mid and row.rank == rank and
            row.start == placement.start and row.finish == placement.finish and
            row.periods == placement.periods and row.assignments == placement.assignments)

def compile_compact(problem, indexed, allowed):
    """Assemble retained choices only, preserving the original U0 rank and policy."""
    started = perf_counter()
    problem = deepcopy(problem)
    input_copy_ms = (perf_counter() - started) * 1000
    validation_started = perf_counter()
    validate_experimental(problem)
    validation_ms = (perf_counter() - validation_started) * 1000
    cases_started = perf_counter()
    environment, specs = _mode_cases(problem)
    productive_case_compile_ms = (perf_counter() - cases_started) * 1000
    assembly_started = perf_counter()
    model = cp_model.CpModel()
    source = problem.project
    members = membership(problem)
    methods = {(p.id, m.id): model.new_bool_var(f"method_{i}_{j}")
               for i, p in enumerate(problem.work_packages) for j, m in enumerate(p.methods)}
    for package in problem.work_packages:
        model.add_exactly_one([methods[package.id, m.id] for m in package.methods])
    starts, ends, presence, mode_vars, choices = {}, {}, {}, {}, {}
    ranked_choices = {}
    named_intervals = {r.id: [] for r in environment.resources}
    workface_intervals = {}
    placement_count = 0
    workface_interval_count = 0
    placement_generation_ms = 0.0
    for ai, activity in enumerate(source["activities"]):
        aid = activity["id"]
        present = methods[members[aid]] if aid in members else model.new_constant(1)
        presence[aid] = present
        starts[aid] = model.new_int_var(0, environment.horizon, f"start_{ai}")
        ends[aid] = model.new_int_var(0, environment.horizon, f"end_{ai}")
        choices[aid] = []
        ranked_choices[aid] = []
        original_rank_cursor = 1
        for mi, mode in enumerate(activity["modes"]):
            mid = mode["id"]
            mode_var = model.new_bool_var(f"mode_{ai}_{mi}")
            mode_vars[aid, mid] = mode_var
            spec = specs[aid, mid]
            placement_started = perf_counter()
            placements = _group_placements(environment, spec, "B")
            if "latest_finish" in activity:
                placements = tuple(p for p in placements if p.finish <= activity["latest_finish"])
            placements = tuple(sorted(placements, key=lambda p: (
                p.start, p.finish, p.periods, tuple("" if r is None else r for r in p.assignments))))
            placement_generation_ms += (perf_counter() - placement_started) * 1000
            for pi, placement in enumerate(placements):
                rank = original_rank_cursor + pi
                if rank > len(indexed[aid]) or not _same_placement(
                        indexed[aid][rank - 1], aid, mid, rank, placement):
                    raise AssertionError(f"{aid}/{mid}/{rank}: original U0 row identity differs")
            original_rank_cursor += len(placements)
            selected_placements = tuple((original_rank_cursor - len(placements) + pi, placement)
                                        for pi, placement in enumerate(placements)
                                        if original_rank_cursor - len(placements) + pi in allowed[aid])
            placement_count += len(selected_placements)
            if placement_count > 20000:
                raise ValueError("bounded composition supports at most 20000 placement alternatives")
            # Multiple group names multiply optional intervals per placement.
            # Bound that expansion before constructing any of this mode's intervals.
            active_placements = sum(p.start < p.finish for _, p in selected_placements)
            workface_interval_count += active_placements * len(activity.get("exclusion_groups", []))
            if workface_interval_count > MAX_WORKFACE_INTERVALS:
                raise ValueError("bounded composition supports at most 20000 workface intervals")
            literals = []
            for rank, placement in selected_placements:
                literal = model.new_bool_var(f"place_{ai}_{mi}_original_{rank}")
                literals.append(literal)
                choices[aid].append((literal, mid, placement))
                ranked_choices[aid].append((rank, literal, mid, placement))
                if placement.start < placement.finish:
                    for group in activity.get("exclusion_groups", []):
                        workface_intervals.setdefault(group, []).append(model.new_optional_interval_var(
                            placement.start, placement.finish - placement.start, placement.finish, literal,
                            f"workface_{ai}_{mi}_original_{rank}_{group}"))
                for ri, (requirement, rid) in enumerate(zip(spec.requirements, placement.assignments)):
                    for si, (start, finish) in enumerate(placement.periods):
                        interval = model.new_optional_interval_var(start, finish - start, finish, literal,
                                                                   f"use_{ai}_{mi}_original_{rank}_{ri}_{si}")
                        if rid is None:
                            raise SchedulingError("internal error: explicit composition deferred a named assignment")
                        named_intervals[rid].append(interval)
            # Empty local availability disables only this mode/method.
            model.add(sum(literals) == mode_var)
        if original_rank_cursor != len(indexed[aid]) + 1:
            raise AssertionError(f"{aid}: incomplete U0 row correspondence")
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
    for intervals in workface_intervals.values():
        if intervals:
            model.add_no_overlap(intervals)
    timing = sum((i + 1) * starts[a["id"]] for i, a in enumerate(source["activities"]))
    stages = [
        _Stage("finish", "finish", ends[source["objective_activity_id"]], environment.horizon),
        _Stage(
            "global_start_timing",
            "global_timing",
            timing,
            environment.horizon * sum(range(1, len(source["activities"]) + 1)),
        ),
    ]
    stages.extend(
        _Stage(
            f"method:{package.id}",
            "method_canonical",
            sum(i * methods[package.id, method.id] for i, method in enumerate(package.methods)),
            len(package.methods) - 1,
        )
        for package in problem.work_packages
    )
    stages.extend(
        _Stage(
            f"mode:{activity['id']}",
            "mode_canonical",
            sum((i + 1) * mode_vars[activity["id"], mode["id"]]
                for i, mode in enumerate(activity["modes"])),
            len(activity["modes"]),
        )
        for activity in source["activities"]
    )
    stages.extend(
        _Stage(
            f"placement:{activity['id']}",
            "placement_canonical",
            sum(rank * literal for rank, literal, _, _ in ranked_choices[activity["id"]]),
            len(indexed[activity["id"]]),
        )
        for activity in source["activities"]
    )
    built = perf_counter()
    compiled = _CompiledWorkMethodTime(
        problem=problem,
        environment=environment,
        specs=specs,
        model=model,
        source=source,
        members=members,
        methods=methods,
        starts=starts,
        ends=ends,
        mode_vars=mode_vars,
        choices=choices,
        stages=tuple(stages),
        placement_count=placement_count,
        workface_interval_count=workface_interval_count,
        started_at=started,
        built_at=built,
        compile_metrics={
            "input_copy_ms": input_copy_ms,
            "validation_ms": validation_ms,
            "productive_case_compile_ms": productive_case_compile_ms,
            "placement_generation_ms": placement_generation_ms,
            "cp_model_assembly_ms": max(
                0.0,
                (built - assembly_started) * 1000 - placement_generation_ms,
            ),
            "base_variables": len(model.proto.variables),
            "base_constraints": len(model.proto.constraints),
        },
    )
    return compiled, ranked_choices


def production_row_map(compiled, indexed):
    """Check every original production choice against its full PR #51 identity."""
    result = {}
    for activity in compiled.source["activities"]:
        aid = activity["id"]
        rows = compiled.choices[aid]
        if len(rows) != len(indexed[aid]):
            raise AssertionError(f"{aid}: production U0 choice count differs")
        mapped = {}
        for rank, (literal, mode, placement) in enumerate(rows, 1):
            if not _same_placement(indexed[aid][rank - 1], aid, mode, rank, placement):
                raise AssertionError(f"{aid}/{rank}: production U0 identity differs")
            mapped[rank] = literal
        result[aid] = mapped
    if sum(len(mapping) for mapping in result.values()) != compiled.placement_count:
        raise AssertionError("production U0 inventory is not bijective")
    return result


def compact_row_map(compiled, ranked, indexed, allowed):
    """Check compact literals are exactly the retained original rank subset."""
    result = {}
    for aid in indexed:
        rows = ranked[aid]
        mapping = {}
        for rank, literal, mid, placement in rows:
            if rank in mapping or not _same_placement(indexed[aid][rank - 1], aid, mid, rank, placement):
                raise AssertionError(f"{aid}/{rank}: duplicate or mismatched compact choice")
            mapping[rank] = literal
        if set(mapping) != allowed[aid] or list(mapping) != sorted(mapping):
            raise AssertionError(f"{aid}: compact model invented, lost or reordered an original row")
        result[aid] = mapping
    if sum(map(len, result.values())) != compiled.placement_count:
        raise AssertionError("compact U1 inventory is not bijective")
    return result


def _blocks(compiled):
    return build_lexicographic_blocks(
        CanonicalDigit(stage.name, stage.maximum) for stage in compiled.stages[2:])


def execute_policy(compiled, *, extract=True, compiler="experimental-w1-rank-preserving/0"):
    """Use the production LB1, finish, timing, block and extraction helpers."""
    base = _snapshot(compiled)
    lower, structures = authorised_precedence_lower_bound(compiled.problem)
    finish, queries, remaining, digest = prove_finish(
        compiled, lower, new_solver=_new_solver, budget=MAX_DETERMINISTIC_TIME_PER_STAGE)
    query_time = sum(q["deterministic_time"] for q in queries)
    query_wall = sum(q["elapsed_wall_ms"] for q in queries)
    finish_proof = {"stage": "finish", "value": finish, "status": "PROVEN_EXACT",
        "proof_kind": "lb1-seeded-sat-search/0",
        "lower_bound": {"kind": "authorised-precedence-relaxation/0", "value": lower},
        "queries": [{"bound": q["bound"], "result": q["result"]} for q in queries]}
    compiled.model.add(compiled.stages[0].expression == finish)
    solver, timing_proof, timing_metrics = _solve_compiled_stages(
        compiled, compiled.stages[1:2], cumulative_wall_ms=query_wall,
        cumulative_deterministic_time=query_time)
    blocks = _blocks(compiled)
    block_stages = _canonical_block_stages(compiled, blocks)
    post_witness = _snapshot(compiled)
    solver, canonical_proofs, canonical_metrics = _solve_compiled_stages(
        compiled, block_stages, solver=solver,
        cumulative_wall_ms=timing_metrics[-1]["cumulative_wall_ms"],
        cumulative_deterministic_time=timing_metrics[-1]["cumulative_deterministic_time"])
    final = _snapshot(compiled)
    block_documents = [{**block.to_document(), "solved_value": proof["value"]}
                       for block, proof in zip(blocks, canonical_proofs)]
    vector = [{"name": stage.name, "value": solver.value(stage.expression),
               "maximum": stage.maximum} for stage in compiled.stages[2:]]
    result = {"objective": [finish, timing_proof[0]["value"]], "lower_bound": lower,
        "authorised_structures": structures, "queries": queries, "remaining_budget": remaining,
        "base_digest": digest, "base": base, "post_witness": post_witness, "final": final,
        "canonical_vector": vector, "canonical_blocks": block_documents,
        "solver_calls": len(queries) + len(timing_metrics) + len(canonical_metrics),
        "deterministic_time": query_time + sum(m["deterministic_time"] for m in
            [*timing_metrics, *canonical_metrics]),
        "solver_wall_ms": query_wall + sum(m["elapsed_wall_ms"] for m in
            [*timing_metrics, *canonical_metrics]),
        "placement_alternatives": compiled.placement_count,
        "workface_intervals": compiled.workface_interval_count}
    if extract:
        plan, validation = _extract_plan(compiled, solver,
            [finish_proof, *timing_proof, *canonical_proofs],
            compiler=compiler, canonical_blocks=block_documents)
        result.update({"plan": plan, "validation": validation,
            "selected_methods": plan["selected_methods"], "selected_modes": plan["selected_modes"]})
    else:
        result["starts"] = {a["id"]: solver.value(compiled.starts[a["id"]])
                            for a in compiled.source["activities"]}
        result["finishes"] = {a["id"]: solver.value(compiled.ends[a["id"]])
                             for a in compiled.source["activities"]}
    return result, solver


def _semantic_plan(plan):
    """Exclude proof identity/hash only, retaining all schedule and physics fields."""
    return {key: value for key, value in plan.items() if key not in ("solver", "plan_hash")}


def _selected_ranks(result, mapping, solver):
    return {aid: next((rank for rank, literal in rows.items() if solver.value(literal)), 0)
            for aid, rows in mapping.items()}


def admitted_comparison(problem, *, shadow=False):
    """Run P0/E1 and optionally E0 against one admitted, source-immutable case."""
    before = input_hash(problem)
    authority = schedule_work_method_time(problem)
    indexed, allowed, _, structures = w1_domain(problem)
    p0 = _compile_work_method_time(problem)
    production_map = production_row_map(p0, indexed)
    p0_result, p0_solver = execute_policy(p0, compiler="native-work-method-time-lb1-seeded/0")
    if p0_result["plan"] != authority.plan:
        raise AssertionError("replayed unmodified production compiler differs from public authority")
    p0_ranks = _selected_ranks(p0_result, production_map, p0_solver)
    if any(rank not in allowed[aid] for aid, rank in p0_ranks.items() if rank):
        raise AssertionError("production selected a W1-removed placement")
    compact_start = perf_counter()
    compact, ranked = compile_compact(problem, indexed, allowed)
    compact_build_ms = (perf_counter() - compact_start) * 1000
    compact_map = compact_row_map(compact, ranked, indexed, allowed)
    e1, e1_solver = execute_policy(compact)
    e1_ranks = _selected_ranks(e1, compact_map, e1_solver)
    if (_semantic_plan(authority.plan) != _semantic_plan(e1["plan"]) or
            p0_result["canonical_vector"] != e1["canonical_vector"] or
            p0_result["canonical_blocks"] != e1["canonical_blocks"] or
            p0_ranks != e1_ranks):
        raise AssertionError("compact W1 model changed the exact production policy")
    result = {"production_hash": authority.plan["plan_hash"],
        "source_unchanged": input_hash(problem) == before,
        "structures": structures, "u0": sum(map(len, indexed.values())),
        "u1": sum(map(len, allowed.values())), "disabled": sum(map(len, indexed.values())) -
              sum(map(len, allowed.values())),
        "p0": {k: v for k, v in p0_result.items() if k != "plan"},
        "e1": {k: v for k, v in e1.items() if k != "plan"},
        "e1_build_ms": compact_build_ms,
        "original_rank_mapping": {"all_u0_rows_match": True, "all_u1_rows_match": True,
            "retained_original_ranks": {aid: sorted(ranks) for aid, ranks in allowed.items()},
            "selected_p0": p0_ranks, "selected_e1": e1_ranks},
        "semantic_equal": True, "physical_equal": True, "canonical_equal": True}
    if shadow:
        e0_model = _compile_work_method_time(problem)
        e0_map = production_row_map(e0_model, indexed)
        disabled = []
        for aid, rows in e0_map.items():
            for rank, literal in rows.items():
                if rank not in allowed[aid]:
                    e0_model.model.add(literal == 0)
                    disabled.append((aid, rank))
        # Adding each equality above preserves every original variable and
        # canonical rank; no removed literal is renumbered or deleted.
        if len(disabled) != result["disabled"] or (
                len(e0_model.model.proto.variables) != p0_result["base"]["variables"] or
                len(e0_model.model.proto.constraints) != p0_result["base"]["constraints"] + len(disabled)):
            raise AssertionError("E0 disabled the wrong production U0 choices")
        e0, e0_solver = execute_policy(e0_model)
        e0_ranks = _selected_ranks(e0, e0_map, e0_solver)
        if (_semantic_plan(authority.plan) != _semantic_plan(e0["plan"]) or
                p0_result["canonical_vector"] != e0["canonical_vector"] or p0_ranks != e0_ranks):
            raise AssertionError("E0 disabling falsified W1 semantics")
        result["e0"] = {k: v for k, v in e0.items() if k != "plan"}
        result["e0"].update({"disabled_rows": len(disabled), "selected_original_ranks": e0_ranks,
                              "semantic_equal_p0": True})
    return result


def low_density_case(count):
    """One forced placement per activity; chain expectations need no solver."""
    if count not in (65, 96, 128, 160):
        raise ValueError("ladder permits only the four declared activity counts")
    activities = []
    for index in range(count):
        row = {"id": f"A{index:03d}", "name": f"Activity {index}",
               "not_before": index, "latest_finish": index + 1,
               "modes": [{"id": "FIXED", "processing_ticks": 1,
                          "calendar_id": "ALL", "continuity": "CONTINUOUS",
                          "requirements": []}]}
        if index:
            row["predecessors"] = [f"A{index - 1:03d}"]
        activities.append(row)
    return WorkMethodTimeProject({"id": f"w1-activity-{count}",
        "name": f"Experimental low-density {count} activity chain",
        "horizon_ticks": count, "calendars": [{"id": "ALL", "daily_windows": [[0, 48]]}],
        "resources": [], "activities": activities,
        "objective_activity_id": activities[-1]["id"], "pool_riggers": False})


def activity_ladder():
    """Solve only low-density synthetic >64 cases under experimental admission."""
    result = []
    for count in (65, 96, 128, 160):
        problem = low_density_case(count)
        source = input_hash(problem)
        try:
            validate_problem(problem)
        except ValueError as exc:
            if "1..64 declared activities" not in str(exc):
                raise AssertionError("production rejected a different contract") from exc
            rejection = str(exc)
        else:
            raise AssertionError("production admitted an experimental >64 fixture")
        validate_experimental(problem)
        indexed, allowed, _, structures = w1_domain(problem)
        if structures != 1 or sum(map(len, indexed.values())) != count or (
                any(len(rows) != 1 or rows[0].rank != 1 or allowed[aid] != {1}
                    for aid, rows in indexed.items())):
            raise AssertionError("activity ladder is not one forced placement per activity")
        compiled, ranked = compile_compact(problem, indexed, allowed)
        compact_row_map(compiled, ranked, indexed, allowed)
        proof, solver = execute_policy(compiled, extract=False)
        expected_starts = {f"A{index:03d}": index for index in range(count)}
        expected_finishes = {aid: start + 1 for aid, start in expected_starts.items()}
        if proof["starts"] != expected_starts or proof["finishes"] != expected_finishes or (
                proof["objective"] != [count, sum((i + 1) * i for i in range(count))]) or (
                any(v["value"] != 1 for v in proof["canonical_vector"]
                    if v["name"].startswith("placement:"))):
            raise AssertionError("low-density proof disagrees with independent chain formula")
        if input_hash(problem) != source:
            raise AssertionError("activity ladder source mutated")
        result.append({"declared": count, "production_rejection": rejection,
            "experimental_admission": True, "one_placement_per_activity": True,
            "expected_finish": count, "actual_objective": proof["objective"],
            "starts_equal_independent_formula": True, "all_original_placement_ranks_one": True,
            "base": proof["base"], "post_witness": proof["post_witness"],
            "final": proof["final"], "solver_calls": proof["solver_calls"],
            "deterministic_time": proof["deterministic_time"],
            "solver_wall_ms": proof["solver_wall_ms"]})
    return result


def professional_assembly():
    """Build the faithful compact 160/120 model; never invoke any solver."""
    problem = build_professional_projection()
    before = input_hash(problem)
    try:
        validate_problem(problem)
    except ValueError as exc:
        if "1..64 declared activities" not in str(exc):
            raise
        production_rejection = str(exc)
    else:
        raise AssertionError("production unexpectedly admitted 160 declarations")
    validate_experimental(problem)
    pr51 = domain_inspect(problem)
    indexed, allowed, detail, structures = w1_domain(problem)
    started = perf_counter()
    compiled, ranked = compile_compact(problem, indexed, allowed)
    build_ms = (perf_counter() - started) * 1000
    compact_row_map(compiled, ranked, indexed, allowed)
    pre = _snapshot(compiled)
    if pre["constraints"] <= 0 or compiled.model.has_objective():
        raise AssertionError("professional assembly lacks a valid objective-free model")
    blocks = _blocks(compiled)
    _canonical_block_stages(compiled, blocks)
    post = _snapshot(compiled)
    intervals = sum(c.has_interval() for c in compiled.model.proto.constraints)
    resource_intervals = sum(sum(segments for _, segments in row.resource_intervals)
                          for rows in indexed.values() for row in rows if row.rank in allowed[row.aid])
    if (len(problem.project["activities"]) != 160 or structures != 16 or
            any(len(materialise(problem, selection)["project"]["activities"]) != 120
                for selection in method_selections(problem)) or
            compiled.placement_count != pr51["u1"]["flattened"] or
            compiled.workface_interval_count != pr51["u1"]["model_pressure"]["workface_optional_intervals_exact"] or
            resource_intervals != pr51["u1"]["model_pressure"]["resource_optional_intervals_exact"] or
            intervals != resource_intervals + compiled.workface_interval_count or
            len(compiled.stages[2:]) != pr51["u1"]["model_pressure"]["canonical_digit_count"] or
            len(blocks) != pr51["u1"]["model_pressure"]["canonical_block_count"] or
            compiled.placement_count > 20000 or compiled.workface_interval_count > 20000 or
            input_hash(problem) != before):
        raise AssertionError("professional W1 assembly differs from exact PR #51 source/domain")
    return {"declared": 160, "active_per_structure": 120, "work_packages": 12,
        "flexible_packages": 4, "authorised_structures": structures,
        "source_hash": before, "production_rejection": production_rejection,
        "u0_raw": sum(item["raw"] for item in detail),
        "u0_eligible": sum(map(len, indexed.values())),
        "retained_placements": compiled.placement_count,
        "resource_optional_intervals": resource_intervals,
        "workface_optional_intervals": compiled.workface_interval_count,
        "proto_optional_intervals": intervals,
        "canonical_digits": len(compiled.stages[2:]), "canonical_blocks": len(blocks),
        "pre_canonical": pre, "post_witness": post, "build_wall_ms": build_ms,
        "pr51_reconciliation": reconcile_pressure(pr51["u1"]["model_pressure"], pre, post,
            compiled, pure_assembly=True),
        "solve_invoked": False}


def _package_root_arcs(compiled):
    """Count package-root constraints exactly as the bounded assembly emits them."""
    by_id = {a["id"]: a for a in compiled.source["activities"]}
    packages = {p.id: p for p in compiled.problem.work_packages}
    return sum(len([aid for aid in method.activity_ids
                    if not set(by_id[aid].get("predecessors", [])) & set(method.activity_ids)])
               * sum(len(packages[pred].methods) for pred in package.predecessors)
               for package in compiled.problem.work_packages for method in package.methods)


def reconcile_pressure(estimate, pre, post, compiled, *, pure_assembly=False):
    """Explain differences between PR #51 mechanical estimates and actual protos."""
    estimated_variables = estimate["pre_canonical_base_variable_estimate"]
    estimated_constraints = estimate["pre_canonical_base_constraint_estimate_excluding_union_package_arcs"]
    arcs = _package_root_arcs(compiled)
    if (pre["variables"] != estimated_variables or
            pre["constraints"] != estimated_constraints + arcs):
        raise AssertionError("PR #51 pre-canonical estimate differs beyond package-root arcs")
    witnesses = estimate["canonical_digit_count"]
    stage_fixings = 0 if pure_assembly else 2  # exact finish and exact timing
    if (post["variables"] != pre["variables"] + witnesses or
            post["constraints"] != pre["constraints"] + witnesses + stage_fixings):
        raise AssertionError("canonical witness/stage fixing proto growth unexplained")
    return {"pr51_estimate_kind": estimate["measurement_kind"],
        "estimated_pre_variables": estimated_variables,
        "estimated_pre_constraints_excluding_package_root_arcs": estimated_constraints,
        "actual_package_root_arcs": arcs, "actual_pre": pre,
        "canonical_witness_intvars": witnesses, "canonical_witness_equalities": witnesses,
        "stage_fixing_equalities": stage_fixings, "actual_post_witness": post,
        "exact_reconciliation": True,
        "note": "PR #51 excluded union package-root arcs. Admitted post-witness snapshots also include two prior stage-fixing equalities; the unsolved 160/120 snapshot includes none."}


def fixed_network_prefix(authority):
    """Independent fixed-network evidence is confined to methods/modes/F/G."""
    fixed = solve_fixed_controls(scale_problem())
    best = fixed["best"]
    if best is None:
        raise AssertionError("no independent 64/48 fixed network")
    result = {"fixed_networks": len(fixed["branches"]), "objective": best["objective"],
        "selected_methods_equal": best["methods"] == authority["selected_methods"],
        "selected_modes_equal": best["modes"] == authority["selected_modes"],
        "finish_equal": best["objective"][0] == authority["objective"][0],
        "global_timing_equal": best["objective"][1] == authority["objective"][1],
        "placement_canonical_checked": False,
        "comparison_scope": "method/mode/objective policy prefix only"}
    if result["fixed_networks"] != 64 or not all(result[k] for k in (
            "selected_methods_equal", "selected_modes_equal", "finish_equal", "global_timing_equal")):
        raise AssertionError("fixed-network prefix disagrees with authority")
    return result


def run_evidence(source_sha):
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if actual != source_sha:
        raise AssertionError("evidence source SHA differs from checked-out HEAD")
    started = perf_counter()
    anchor = admitted_comparison(scale_problem(), shadow=True)
    if (anchor["production_hash"] != BASE_HASHES["64_48"] or
            anchor["p0"]["objective"] != [19, 14674] or
            anchor["e1"]["base"]["variables"] >= anchor["p0"]["base"]["variables"] or
            anchor["e1"]["base"]["constraints"] >= anchor["p0"]["base"]["constraints"]):
        raise AssertionError("64/48 identity/model falsification")
    controls = {}
    for label, problem in (
            ("small", small_problem()),
            ("professional", professional_problem(workface=True, deadline=True)),
            ("anonymous_group", build_group_stress())):
        controls[label] = admitted_comparison(problem)
        expected = BASE_HASHES.get("small_named" if label == "small" else label)
        if expected is not None and controls[label]["production_hash"] != expected:
            raise AssertionError(f"{label}: merged-main production hash changed")
    indexed, allowed, _, _ = w1_domain(scale_problem())
    anchor["e1"]["pr51_estimate_reconciliation"] = reconcile_pressure(
        census(scale_problem(), indexed, allowed)["model_pressure"],
        anchor["e1"]["base"], anchor["e1"]["post_witness"],
        compile_compact(scale_problem(), indexed, allowed)[0])
    ladder = activity_ladder()
    professional = professional_assembly()
    if professional["retained_placements"] != 7812:
        raise AssertionError("professional U1 differs from corrected PR #51")
    return {"source_sha": actual, "verified_base_main": BASE_MAIN,
        "runtime": {"python": platform.python_version(), "ortools": ortools.__version__},
        "exact_semantic_facts": {"production_hashes": BASE_HASHES,
            "anchor": {k: v for k, v in anchor.items() if k != "e1_build_ms"},
            "controls": controls, "fixed_network_prefix": fixed_network_prefix(anchor["p0"]),
            "activity_admission_ladder": ladder, "professional_assembly": professional,
            "classification": "A_W1_MODEL_INTEGRATION_PROVEN",
            "first_exact_professional_160_120_solve_experiment": "READY",
            "recommendation": "Next bounded experiment: first exact 160/120 solve on the experimental W1 architecture; do not change production admission."},
        "wall_observations": {"e1_anchor_build_ms": anchor["e1_build_ms"],
            "professional_assembly_build_ms": professional["build_wall_ms"],
            "experiment_end_to_end_ms": (perf_counter() - started) * 1000},
        "no_professional_solve": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--source-sha", required=True)
    args = parser.parse_args()
    result = run_evidence(args.source_sha)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"source_sha": result["source_sha"],
        "classification": result["exact_semantic_facts"]["classification"],
        "professional": result["exact_semantic_facts"]["professional_assembly"]["pre_canonical"]}))


if __name__ == "__main__":
    main()
