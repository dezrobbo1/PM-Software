"""First bounded exact professional 160/120 W1 solve; never a production dependency.

Run with --source-sha recorded before installation and --output outside the repo.
The checkpoint is atomically rewritten after every finished solver call.
"""
from __future__ import annotations

import argparse
from copy import copy
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import subprocess
from time import perf_counter
from unittest.mock import patch

import ortools
from ortools.sat.python import cp_model

from deterministic_scheduling_core.errors import SchedulingError
from deterministic_scheduling_core.professional_scale_challenge import build_professional_projection
from deterministic_scheduling_core.project.work_method_time import input_hash, materialise, method_selections
from deterministic_scheduling_core.scheduling import work_method_time as production
from deterministic_scheduling_core.scheduling import finish_search
from deterministic_scheduling_core.scheduling.canonical_batching import build_lexicographic_blocks, CanonicalDigit
from deterministic_scheduling_core.scheduling.finish_lower_bound import authorised_precedence_lower_bound
from deterministic_scheduling_core.scheduling.finish_search import prove_finish
from deterministic_scheduling_core.w1_model_integration_experiment import (
    BASE_MAIN as PR52_BASE, _blocks, _snapshot, compact_row_map, compile_compact,
    validate_experimental, w1_domain,
)

MERGED_BASE = "166d6e209f5fd29795cc92108d42ed5e17225751"
EXPECTED_INPUT_HASH = "92a2a346a64d916ff2f8346bd016915553737f3c9d71423157f5579defc0cc46"
EXPECTED_PRE = (8308, 7952)
EXPECTED_POST = (8640, 8284)
EXPECTED_DOMAIN = (64068, 64032, 7812, 6705, 409, 332, 26)


def _checkpoint(path: Path, result: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _stable_result(document):
    """Compare proved policy and physical signature, never noisy wall observations."""
    return ({key: value for key, value in document.items()
             if key != "extraction_validation_wall_ms"} if document else None)


def _head(source_sha: str):
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if source_sha != actual:
        raise ValueError("recorded pre-install SHA does not match HEAD")
    for args in (["git", "diff", "--quiet"], ["git", "diff", "--cached", "--quiet"]):
        if subprocess.run(args, check=False).returncode:
            raise ValueError("tracked worktree changed since checkout")


def _model_shape(compiled, blocks):
    before = _snapshot(compiled)
    context = copy(compiled)
    context.model = compiled.model.clone()
    production._canonical_block_stages(context, blocks)
    after = _snapshot(context)
    if ((before["variables"], before["constraints"]) != EXPECTED_PRE or
            (after["variables"], after["constraints"]) != EXPECTED_POST or
            compiled.model.has_objective()):
        raise AssertionError("professional compact proto differs from frozen PR #52")
    return before, after


def prepare():
    """Assert every frozen source/domain/model fact before the first solver call."""
    problem = build_professional_projection()
    source = input_hash(problem)
    if source != EXPECTED_INPUT_HASH:
        raise AssertionError("professional source hash changed")
    validate_experimental(problem)
    try:
        production.validate_problem(problem)
    except ValueError as exc:
        if "1..64 declared activities" not in str(exc):
            raise
        rejection = str(exc)
    else:
        raise AssertionError("production admitted 160 activities")
    started = perf_counter()
    indexed, allowed, details, structures = w1_domain(problem)
    compiled, ranked = compile_compact(problem, indexed, allowed)
    compact_row_map(compiled, ranked, indexed, allowed)
    blocks = _blocks(compiled)
    before, after = _model_shape(compiled, blocks)
    resource_intervals = sum(segments for aid, rows in indexed.items() for row in rows
                             if row.rank in allowed[aid] for _, segments in row.resource_intervals)
    raw = sum(item["raw"] for item in details)
    eligible = sum(map(len, indexed.values()))
    actual_domain = (raw, eligible, compiled.placement_count, resource_intervals,
                     compiled.workface_interval_count, len(compiled.stages) - 2, len(blocks))
    if (actual_domain != EXPECTED_DOMAIN or structures != 16 or
            len(problem.project["activities"]) != 160 or len(problem.work_packages) != 12 or
            sum(len(p.methods) > 1 for p in problem.work_packages) != 4 or
            any(len(materialise(problem, selection)["project"]["activities"]) != 120
                for selection in method_selections(problem)) or
            input_hash(problem) != source):
        raise AssertionError("professional domain/structure differs from frozen PR #52")
    evidence = {"professional_input_hash": source, "production_rejection": rejection,
                "domain": {"declared": 160, "active_per_structure": 120,
                    "work_packages": 12, "flexible_work_packages": 4,
                    "authorised_structures": structures, "u0_raw": raw, "u0_eligible": eligible,
                    "w1_retained": compiled.placement_count, "resource_optional_intervals": resource_intervals,
                    "workface_optional_intervals": compiled.workface_interval_count,
                    "canonical_digits": len(compiled.stages) - 2, "canonical_blocks": len(blocks)},
                "model": {"pre_canonical": before, "post_witness": after},
                "model_build_wall_ms": (perf_counter() - started) * 1000}
    return problem, indexed, allowed, compiled, ranked, blocks, evidence


def _experimental_validate(problem, plan):
    """Use the same physical checker and stored-plan checks with only the 64 cap lifted."""
    validate_experimental(problem)
    if (not isinstance(plan, dict) or set(plan) != {
            "schema", "input_hash", "policy", "selected_methods", "selected_modes", "entries",
            "objective", "pooled_riggers", "allocation_witness", "physical_status", "solver", "plan_hash"}
            or plan["schema"] != production.PLAN_SCHEMA or
            plan["input_hash"] != input_hash(problem) or plan["policy"] != production.POLICY or
            plan["plan_hash"] != production._hash_plan(plan) or
            plan["physical_status"] != production.ra.EXACT_FEASIBLE):
        raise ValueError("experimental stored plan integrity failed")
    production._validate_physics(problem, plan)
    return production.ra.EXACT_FEASIBLE


def _validate_solution(problem, indexed, allowed, compiled, ranked, blocks, solver, plan, vector):
    """Cross-check exact original ranks, digits, structure and independent physics."""
    if _experimental_validate(problem, plan) != production.ra.EXACT_FEASIBLE:
        raise AssertionError("independent physical validation failed")
    active = {a["id"] for a in materialise(problem, plan["selected_methods"])["project"]["activities"]}
    if len(active) != 120 or set(plan["selected_modes"]) != active:
        raise AssertionError("incorrect active structure or modes")
    if set(plan["selected_methods"]) != {p.id for p in problem.work_packages} or any(
            choice not in {m.id for m in p.methods}
            for p in problem.work_packages for choice in [plan["selected_methods"][p.id]]):
        raise AssertionError("unauthorised selected method")
    rank_map = {}
    for activity in problem.project["activities"]:
        aid = activity["id"]
        rows = [row for row in ranked[aid] if solver.value(row[1])]
        if len(rows) != (1 if aid in active else 0):
            raise AssertionError("inactive alternative activated or active activity missing")
        rank = rows[0][0] if rows else 0
        if rank and (rank not in allowed[aid] or rank > len(indexed[aid])):
            raise AssertionError("selected rank not in original retained U0 domain")
        if rank and (rows[0][2] != plan["selected_modes"][aid] or
                     solver.value(compiled.starts[aid]) != indexed[aid][rank - 1].start or
                     solver.value(compiled.ends[aid]) != indexed[aid][rank - 1].finish):
            raise AssertionError("selected original row differs from solver/plan")
        if not rank and (solver.value(compiled.starts[aid]) or solver.value(compiled.ends[aid])):
            raise AssertionError("inactive activity leaks into timing")
        rank_map[aid] = rank
    expected = {f"method:{p.id}": next(i for i, m in enumerate(p.methods)
                if m.id == plan["selected_methods"][p.id]) for p in problem.work_packages}
    expected.update({f"mode:{a['id']}": next((i + 1 for i, m in enumerate(a["modes"])
                if m["id"] == plan["selected_modes"].get(a["id"])), 0)
                for a in problem.project["activities"]})
    expected.update({f"placement:{aid}": rank for aid, rank in rank_map.items()})
    if (len(vector) != len(expected) or any(
            item["value"] != expected[item["name"]] or
            item["maximum"] != compiled.stages[i + 2].maximum
            for i, item in enumerate(vector)) or
            [item["name"] for item in vector] != [s.name for s in compiled.stages[2:]] or
            sum(len(block.digits) for block in blocks) != len(vector)):
        raise AssertionError("canonical policy/ranks differ from extracted plan")
    signature = sha256(json.dumps({"objective": plan["objective"],
        "methods": plan["selected_methods"], "modes": plan["selected_modes"],
        "original_ranks": rank_map, "canonical": vector, "entries": plan["entries"],
        "witness": plan["allocation_witness"]}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return rank_map, signature


def _run_policy(problem, indexed, allowed, compiled, ranked, blocks, outcome, persist):
    """Same LB1 search/production solver parameters and exact policy; trace every call."""
    lb1, structures = authorised_precedence_lower_bound(problem)
    outcome["finish_proof"] = {"lb1": lb1, "structures": structures, "queries": [],
                               "shared_budget": production.MAX_DETERMINISTIC_TIME_PER_STAGE}
    persist()
    current_bound = {"value": None}
    exact_search = finish_search.exact_bound_search

    def traced_search(lower, horizon, query):
        def traced_query(bound):
            current_bound["value"] = bound
            return query(bound)
        return exact_search(lower, horizon, traced_query)

    def tracked_solver():
        solver = production._new_solver()
        original = solver.solve

        def solve(model, *args, **kwargs):
            bound = current_bound["value"]
            if bound is None:
                raise AssertionError("finish solve without a declared bound")
            budget = float(solver.parameters.max_deterministic_time)
            started = perf_counter()
            status = original(model, *args, **kwargs)
            proto = solver.response_proto
            record = {"bound": bound, "status": solver.status_name(status),
                      "result": ("SAT" if status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
                                 else "INFEASIBLE" if status == cp_model.INFEASIBLE else "UNKNOWN"),
                      "budget_before": budget, "deterministic_time": float(proto.deterministic_time),
                      "wall_ms": (perf_counter() - started) * 1000,
                      "solver_wall_ms": float(proto.wall_time) * 1000}
            outcome["finish_proof"]["queries"].append(record)
            outcome["finish_proof"]["remaining_budget_observed"] = max(0.0,
                budget - float(proto.deterministic_time))
            persist()
            return status

        solver.solve = solve
        return solver

    try:
        with patch.object(finish_search, "exact_bound_search", traced_search):
            finish, queries, remaining, digest = prove_finish(compiled, lb1,
                new_solver=tracked_solver, budget=production.MAX_DETERMINISTIC_TIME_PER_STAGE)
    except SchedulingError as exc:
        outcome["stopped_stage"] = "finish"
        outcome["error"] = str(exc)
        outcome["classification"] = ("MODEL_INFEASIBLE" if str(exc).startswith("INFEASIBLE:")
                                     else "EXACT_FINISH_NOT_PROVEN_WITHIN_DECLARED_BUDGET"
                                     if str(exc).startswith("UNKNOWN:")
                                     else "MODEL_OR_VALIDATION_DEFECT")
        persist()
        return None
    outcome["finish_proof"].update({"status": "PROVEN_EXACT", "finish": finish,
        "remaining_budget": remaining, "deterministic_time": sum(q["deterministic_time"] for q in queries),
        "base_proto_digest": digest})
    finish_document = {"stage": "finish", "value": finish, "status": "PROVEN_EXACT",
        "proof_kind": "lb1-seeded-sat-search/0",
        "lower_bound": {"kind": "authorised-precedence-relaxation/0", "value": lb1},
        "queries": [{"bound": row["bound"], "result": row["result"]} for row in queries]}
    compiled.model.add(compiled.stages[0].expression == finish)
    persist()
    solver = production._new_solver()
    outcome["lower_policy"] = {"stages": [], "total_blocks": len(blocks),
                               "completed_blocks": 0}
    persist()
    proofs = []

    def solve_stage(stage):
        compiled.model.minimize(stage.expression)
        started = perf_counter()
        status = solver.solve(compiled.model)
        proto = solver.response_proto
        record = {"stage": stage.name, "type": stage.stage_type,
            "status": solver.status_name(status), "deterministic_time": float(proto.deterministic_time),
            "solver_wall_ms": float(proto.wall_time) * 1000,
            "wall_ms": (perf_counter() - started) * 1000,
            "budget": production.MAX_DETERMINISTIC_TIME_PER_STAGE}
        if status == cp_model.OPTIMAL:
            value = int(solver.value(stage.expression))
            record["value"] = value
            proofs.append({"stage": stage.name, "value": value, "status": "OPTIMAL"})
            compiled.model.add(stage.expression == value)
            if stage.stage_type == "canonical_block":
                outcome["lower_policy"]["completed_blocks"] += 1
        else:
            outcome["stopped_stage"] = stage.name
            outcome["classification"] = ("MODEL_OR_VALIDATION_DEFECT" if status in (
                cp_model.MODEL_INVALID, cp_model.INFEASIBLE) else
                "EXACT_FINISH_PROVEN_LOWER_POLICY_INCOMPLETE")
            outcome["error"] = f"{solver.status_name(status)}: {stage.name} not proven OPTIMAL"
        outcome["lower_policy"]["stages"].append(record)
        persist()
        return status == cp_model.OPTIMAL

    if not solve_stage(compiled.stages[1]):
        return None
    block_stages = production._canonical_block_stages(compiled, blocks)
    outcome.setdefault("model", {})["post_witness_after_stage_fixing"] = _snapshot(compiled)
    persist()
    for stage in block_stages:
        if not solve_stage(stage):
            return None

    documents = [{**block.to_document(), "solved_value": proof["value"]}
                 for block, proof in zip(blocks, proofs[1:])]
    vector = [{"name": stage.name, "value": int(solver.value(stage.expression)),
               "maximum": stage.maximum} for stage in compiled.stages[2:]]
    outcome["stopped_stage"] = "extraction_and_independent_validation"
    persist()
    with patch.object(production, "validate_plan", _experimental_validate):
        plan, validation = production._extract_plan(compiled, solver,
            [finish_document, *proofs], compiler="experimental-w1-professional-160/0",
            canonical_blocks=documents)
    rank_map, signature = _validate_solution(problem, indexed, allowed, compiled,
        ranked, blocks, solver, plan, vector)
    outcome["result"] = {"objective": plan["objective"],
        "selected_methods": plan["selected_methods"], "selected_modes": plan["selected_modes"],
        "selected_original_placement_ranks": rank_map, "canonical_vector": vector,
        "physical_validation": plan["physical_status"],
        "stored_plan_validation": "PROVEN_FEASIBLE_EXPERIMENTAL_ONLY",
        "plan_signature": signature, "extraction_validation_wall_ms": validation}
    outcome["classification"] = "COMPLETE_EXACT_POLICY_PROVEN"
    outcome["stopped_stage"] = None
    persist()
    return outcome["result"]


def run(source_sha: str, output: Path, *, repeat_on_success=True, controls=True):
    """One declared-budget attempt, with repeat only following complete exact success."""
    started = perf_counter()
    _head(source_sha)
    result = {"source_sha": source_sha, "base_main": MERGED_BASE,
        "runtime": {"python": platform.python_version(), "ortools": ortools.__version__,
                    "platform": platform.platform()},
        "classification": "PREPARATION_IN_PROGRESS", "stopped_stage": "preparation",
        "finish_proof": {"queries": []}, "lower_policy": {"stages": [], "completed_blocks": 0},
        "solver_calls": 0, "deterministic_time": 0.0}

    def persist():
        result["solver_calls"] = len(result.get("finish_proof", {}).get("queries", [])) + len(
            result.get("lower_policy", {}).get("stages", []))
        result["deterministic_time"] = sum(q.get("deterministic_time", 0)
            for q in result.get("finish_proof", {}).get("queries", [])) + sum(
            s.get("deterministic_time", 0) for s in result.get("lower_policy", {}).get("stages", []))
        result["observed_wall_ms"] = (perf_counter() - started) * 1000
        _checkpoint(output, result)

    persist()
    try:
        problem, indexed, allowed, compiled, ranked, blocks, preparation = prepare()
        result.update(preparation)
        result["classification"] = "SOLVE_IN_PROGRESS"
        result["stopped_stage"] = "finish"
        persist()
        solution = _run_policy(problem, indexed, allowed, compiled, ranked, blocks, result, persist)
        if solution and repeat_on_success:
            result["repeatability"] = {"status": "RUNNING"}
            persist()
            repeated = {"finish_proof": {"queries": []}, "lower_policy": {"stages": []}}
            second_problem, second_indexed, second_allowed, second_compiled, second_ranked, second_blocks, second_preparation = prepare()
            if second_preparation["professional_input_hash"] != preparation["professional_input_hash"]:
                raise AssertionError("repeat source differs")
            second = _run_policy(second_problem, second_indexed, second_allowed,
                second_compiled, second_ranked, second_blocks, repeated, lambda: None)
            matches = _stable_result(second) == _stable_result(solution)
            result["repeatability"] = {"status": "EXACT_MATCH" if matches else "MISMATCH",
                                      "second_classification": repeated.get("classification"),
                                      "second_solver_calls": len(repeated["finish_proof"]["queries"]) +
                                          len(repeated["lower_policy"]["stages"]),
                                      "second_deterministic_time": sum(q.get("deterministic_time", 0)
                                          for q in repeated["finish_proof"]["queries"]) +
                                          sum(s.get("deterministic_time", 0)
                                          for s in repeated["lower_policy"]["stages"])}
            if not matches:
                raise AssertionError("same-environment complete policy did not repeat")
            persist()
        elif solution is None:
            result["repeatability"] = {"status": "NOT_APPLICABLE_INCOMPLETE"}
        if controls:
            # Existing PR #52 control suite is run separately before the first solve;
            # record its source-bound command result in CI rather than solve it again here.
            result["admitted_controls"] = "PR52_FOCUSED_TESTS_REQUIRED_IN_CI"
        result["structural_oracle"] = {"status": "NOT_RUN_UNLESS_JOINT_COMPLETE" if not solution
            else "STRUCTURAL_ORACLE_INCONCLUSIVE", "reason": "No bounded independent 16-structure exact oracle exists in this experiment."}
    except Exception as exc:
        result["classification"] = "MODEL_OR_VALIDATION_DEFECT"
        result["error"] = f"{type(exc).__name__}: {exc}"
        persist()
    _head(source_sha)
    persist()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.source_sha, args.output)
    print(json.dumps({"source_sha": result["source_sha"], "classification": result["classification"],
        "finish": result.get("finish_proof", {}).get("finish"),
        "completed_blocks": result.get("lower_policy", {}).get("completed_blocks"),
        "solver_calls": result["solver_calls"]}))
    # Incomplete and infeasible results remain valuable uploaded evidence,
    # but the exact-solve workflow must never report them as a green proof.
    if result["classification"] != "COMPLETE_EXACT_POLICY_PROVEN":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
