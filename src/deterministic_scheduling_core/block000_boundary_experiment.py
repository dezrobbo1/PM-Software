"""One bounded method/mode proof-boundary experiment; never imported by production."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import platform
import statistics
import subprocess
from time import perf_counter

import ortools
from ortools.sat.python import cp_model

from deterministic_scheduling_core.canonical_cost_experiment import semantic_plan, build_stage_ladder, build_density_ladder
from deterministic_scheduling_core.converged_scale_experiment import build_problem as scale_problem
from deterministic_scheduling_core.native_work_method_time import build_problem as small_problem, solve_fixed_controls
from deterministic_scheduling_core.professional_workface_experiment import build_problem as professional_problem
from deterministic_scheduling_core.factored_finish_search_experiment import build_group_stress
from deterministic_scheduling_core.professional_scale_challenge import run_challenge
from deterministic_scheduling_core.project.work_method_time import input_hash
from deterministic_scheduling_core.post_finish_proof_experiment import BASE_HASHES, _anatomy, _shape
from deterministic_scheduling_core.scheduling.canonical_batching import (
    CanonicalDigit, MAX_SAFE_BLOCK_VALUE, build_lexicographic_blocks,
)
from deterministic_scheduling_core.scheduling.finish_lower_bound import authorised_precedence_lower_bound
from deterministic_scheduling_core.scheduling.finish_search import prove_finish
from deterministic_scheduling_core.scheduling.work_method_time import (
    MAX_DETERMINISTIC_TIME_PER_STAGE, _Stage, _canonical_block_stages,
    _compile_work_method_time, _extract_plan, _new_solver, _solve_compiled_stages,
    schedule_work_method_time,
)


def _blocks(compiled):
    return build_lexicographic_blocks(CanonicalDigit(s.name, s.maximum) for s in compiled.stages[2:])


def _split(block):
    names = [d.name.split(":", 1)[0] for d in block.digits]
    k = names.count("method")
    if not k or k == len(names) or names != ["method"] * k + ["mode"] * (len(names) - k):
        return None
    method = build_lexicographic_blocks(block.digits[:k])
    mode = build_lexicographic_blocks(block.digits[k:])
    if len(method) != 1 or len(mode) != 1:
        return None
    return method[0], mode[0]


def _numbers(block):
    coefficients = list(block.coefficients)
    return {"name": block.name, "digit_count": len(block.digits),
            "digits": block.to_document()["digits"],
            "radices": [d.maximum + 1 for d in block.digits],
            "maximum": block.maximum, "safety_bound": block.safety_bound,
            "largest_coefficient": max(coefficients), "smallest_nonzero_coefficient": min(coefficients),
            "coefficient_ratio": max(coefficients) // min(coefficients),
            "largest_coefficient_bits": max(coefficients).bit_length(),
            "encoded_domain_bits": block.maximum.bit_length()}


def _digit_vars(compiled, target):
    wanted = {"canonical_digit_" + d.name for d in target.digits}
    names = {v.name: compiled.model.get_int_var_from_proto_index(i)
             for i, v in enumerate(compiled.model.proto.variables) if v.name in wanted}
    if set(names) != wanted:
        raise AssertionError("production digit witnesses missing from experiment")
    return {d.name: names["canonical_digit_" + d.name] for d in target.digits}


def _substage(block, witnesses, name):
    return _Stage(name, "diagnostic_canonical_subblock",
                  sum(c * witnesses[d.name] for d, c in zip(block.digits, block.coefficients)), block.maximum)


def _one_satisfaction(model):
    solver = _new_solver()
    started = perf_counter()
    status = solver.solve(model)
    elapsed = (perf_counter() - started) * 1000
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise AssertionError("fixed-context SAT floor did not return a witness")
    response = solver.response_proto
    return {"status": "SAT", "deterministic_time": float(response.deterministic_time),
            "elapsed_wall_ms": elapsed, "solver_wall_ms": float(response.wall_time) * 1000,
            "branches": int(response.num_branches), "conflicts": int(response.num_conflicts),
            "binary_propagations": int(response.num_binary_propagations),
            "integer_propagations": int(response.num_integer_propagations)}


def _floors(context, stage, target, witnesses, values):
    definitions = {"context_sat": lambda m: None,
                   "target_value_fixed": lambda m: m.add(stage.expression == values["block"]),
                   "target_digits_fixed": lambda m: [m.add(witnesses[d.name] == values[d.name]) for d in target.digits]}
    rows = {}
    for name, modify in definitions.items():
        reps = []
        for _ in range(3):
            clone = context.clone()
            modify(clone)
            reps.append(_one_satisfaction(clone))
        walls = [r["elapsed_wall_ms"] for r in reps]
        rows[name] = {"model_delta_constraints": 0 if name == "context_sat" else 1 if name == "target_value_fixed" else len(target.digits),
                      "repetitions": reps, "wall_min_ms": min(walls),
                      "wall_median_ms": statistics.median(walls), "wall_max_ms": max(walls)}
    return rows


def _full_challenger(problem, strategy, expected, target_index):
    """Execute the real LB1/timing/all-canonical path with only target proof changed."""
    started = perf_counter()
    compiled = _compile_work_method_time(problem)
    blocks = _blocks(compiled)
    lower, _ = authorised_precedence_lower_bound(compiled.problem)
    finish, queries, _, _ = prove_finish(compiled, lower, new_solver=_new_solver,
                                          budget=MAX_DETERMINISTIC_TIME_PER_STAGE)
    if finish != expected.plan["objective"][0]:
        raise AssertionError("challenger finish diverged")
    compiled.model.add(compiled.stages[0].expression == finish)
    solver, timing, timing_metrics = _solve_compiled_stages(compiled, compiled.stages[1:2])
    if timing[0]["value"] != expected.plan["objective"][1]:
        raise AssertionError("challenger global timing diverged")
    stages = _canonical_block_stages(compiled, blocks)
    preceding_solver, preceding, preceding_metrics = _solve_compiled_stages(
        compiled, stages[:target_index], solver=solver)
    target = blocks[target_index]
    witnesses = _digit_vars(compiled, target)
    if strategy == "semantic_split":
        split = _split(target)
        if split is None:
            raise ValueError("target lacks a clean method-to-mode boundary")
        target_stages = tuple(_substage(b, witnesses, f"experiment:{name}")
                              for b, name in zip(split, ("methods", "modes")))
    elif strategy == "individual_digits":
        ordered = {s.name: s for s in compiled.stages[2:]}
        target_stages = tuple(ordered[d.name] for d in target.digits)
    else:
        raise ValueError(strategy)
    solver, target_proof, target_metrics = _solve_compiled_stages(compiled, target_stages, solver=preceding_solver)
    observed_target_value = solver.value(stages[target_index].expression)
    if observed_target_value != expected.metrics["canonical_blocks"][target_index]["solved_value"]:
        raise AssertionError("challenger target block rank diverged")
    solver, remainder, remainder_metrics = _solve_compiled_stages(
        compiled, stages[target_index + 1:], solver=solver)
    finish_proof = {"stage": "finish", "value": finish, "status": "PROVEN_EXACT",
                    "proof_kind": "lb1-seeded-sat-search/0",
                    "lower_bound": {"kind": "authorised-precedence-relaxation/0", "value": lower},
                    "queries": [{"bound": q["bound"], "result": q["result"]} for q in queries]}
    plan, extraction = _extract_plan(compiled, solver, [finish_proof, *timing, *preceding,
        *target_proof, *remainder], compiler=f"experiment-{strategy}/0")
    # _extract_plan already performs independent allocation and stored-plan
    # validation; repeating either here would inflate challenger wall cost.
    vector = [{"name": s.name, "value": solver.value(s.expression)} for s in compiled.stages[2:]]
    original = [{"name": v["name"], "value": v["value"]} for v in expected.metrics["canonical_vector"]]
    if semantic_plan(plan) != semantic_plan(expected.plan) or vector != original:
        raise AssertionError("complete semantic or canonical policy diverged")
    stage_metrics = [*timing_metrics, *preceding_metrics, *target_metrics, *remainder_metrics]
    return {"strategy": strategy, "finish": finish, "global_timing": timing[0]["value"],
            "semantic_equal": True, "canonical_equal": True, "physical_status": plan["physical_status"],
            "model_builds": 1, "solver_calls": len(queries) + len(stage_metrics),
            "finish_query_calls": len(queries), "global_timing_calls": 1,
            "target_calls": len(target_metrics), "other_canonical_calls": len(preceding_metrics) + len(remainder_metrics),
            "total_deterministic": sum(q["deterministic_time"] for q in queries) + sum(s["deterministic_time"] for s in stage_metrics),
            "total_solver_wall_ms": sum(q["elapsed_wall_ms"] for q in queries) + sum(s["elapsed_wall_ms"] for s in stage_metrics),
            "end_to_end_ms": (perf_counter() - started) * 1000,
            "extraction_validation_ms": extraction, "canonical_vector": vector,
            "target_stage_metrics": target_metrics, "all_stage_metrics": stage_metrics}


def inspect_primary(problem):
    source = input_hash(problem)
    production = schedule_work_method_time(problem)
    if production.plan["plan_hash"] != BASE_HASHES["64_48"] or production.plan["objective"][0] != 19:
        raise AssertionError("merged-main primary identity or finish changed")
    fixed = solve_fixed_controls(small_problem())
    if fixed["best"]["objective"][0] != schedule_work_method_time(small_problem()).plan["objective"][0]:
        raise AssertionError("independent fixed-network policy disagrees")
    canonical_metrics = production.metrics["stage_metrics"][2:]
    index = max(range(len(canonical_metrics)), key=lambda i: canonical_metrics[i]["deterministic_time"])
    compiled = _compile_work_method_time(problem)
    blocks = _blocks(compiled)
    target = blocks[index]
    split = _split(target)
    if split is None:
        return {"classification": "SEMANTIC_SPLIT_INAPPLICABLE", "target": target.to_document()}
    F, G = production.plan["objective"]
    compiled.model.add(compiled.stages[0].expression == F)
    compiled.model.add(compiled.stages[1].expression == G)
    stages = _canonical_block_stages(compiled, blocks)
    for i in range(index):
        compiled.model.add(stages[i].expression == production.metrics["canonical_blocks"][i]["solved_value"])
    context = compiled.model
    p0_value = production.metrics["canonical_blocks"][index]["solved_value"]
    p0 = _anatomy(context, stages[index].expression, p0_value, index + 2)
    witnesses = _digit_vars(compiled, target)
    method_stage, mode_stage = (_substage(b, witnesses, f"experiment:{name}")
                                for b, name in zip(split, ("methods", "modes")))
    production_digits = {d["name"]: d["value"] for d in production.metrics["canonical_vector"]}
    method_value = sum(c * production_digits[d.name] for d, c in zip(split[0].digits, split[0].coefficients))
    mode_value = sum(c * production_digits[d.name] for d, c in zip(split[1].digits, split[1].coefficients))
    method_anatomy = _anatomy(context, method_stage.expression, method_value, index + 2)
    mode_context = context.clone()
    mode_context.add(method_stage.expression == method_value)
    mode_anatomy = _anatomy(mode_context, mode_stage.expression, mode_value, index + 3)
    floor_values = {"block": p0_value, **production_digits}
    floors = _floors(context, stages[index], target, witnesses, floor_values)
    challenger = _full_challenger(problem, "semantic_split", production, index)
    individual = _full_challenger(problem, "individual_digits", production, index)
    if input_hash(problem) != source:
        raise AssertionError("diagnostics changed source")
    return {"source_input_hash": source, "production_hash": production.plan["plan_hash"],
            "F": F, "G": G, "placements": production.metrics["placement_alternatives"],
            "base_model": {k: production.metrics[k] for k in ("base_variables", "base_constraints")},
            "target_index": index, "target_name": target.name,
            "target_value": p0_value, "target_numerics": _numbers(target),
            "method_numerics": _numbers(split[0]), "mode_numerics": _numbers(split[1]),
            "p0_anatomy": p0, "method_anatomy": method_anatomy, "mode_anatomy": mode_anatomy,
            "floor": floors, "production": {"solver_calls": production.metrics["solver_calls"],
                 "model_builds": production.metrics["model_builds"],
                 "target_stage": canonical_metrics[index],
                 "total_deterministic": sum(s["deterministic_time"] for s in production.metrics["stage_metrics"]),
                 "total_solver_wall_ms": production.metrics["solve_ms"],
                 "end_to_end_ms": production.metrics["end_to_end_ms"],
                 "canonical_vector": production.metrics["canonical_vector"]},
            "p1": challenger, "p2": individual,
            "same_context_target": _shape(context), "same_context_mode": _shape(mode_context)}


def run_evidence(source_sha):
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if actual != source_sha:
        raise AssertionError("result source SHA differs from checked-out HEAD")
    primary = inspect_primary(scale_problem())
    if primary.get("classification") == "SEMANTIC_SPLIT_INAPPLICABLE":
        return {"source_sha": actual, "primary": primary, "classification": "SPLIT_INAPPLICABLE"}
    controls = {}
    for name, problem in (("small_named", small_problem()),
                          ("professional", professional_problem(workface=True, deadline=True)),
                          ("anonymous_group", build_group_stress())):
        source = input_hash(problem)
        result = schedule_work_method_time(problem)
        if name in BASE_HASHES and result.plan["plan_hash"] != BASE_HASHES[name]:
            raise AssertionError(f"production hash changed: {name}")
        blocks = _blocks(_compile_work_method_time(problem))
        split = _split(blocks[0])
        controls[name] = {"plan_hash": result.plan["plan_hash"], "objective": result.plan["objective"],
                          "physical_status": result.plan["physical_status"],
                          "split_applicable": split is not None,
                          "target_block_types": [d.name.split(":")[0] for d in blocks[0].digits]}
        if split is not None:
            controls[name]["p1"] = _full_challenger(problem, "semantic_split", result, 0)
        if input_hash(problem) != source:
            raise AssertionError("control source changed")
    activity = []
    for n in (8, 16, 32, 48, 64):
        r = schedule_work_method_time(build_stage_ladder(n))
        activity.append({"activities": n, "placements": r.metrics["placement_alternatives"],
                         "finish": r.plan["objective"][0], "target_deterministic": r.metrics["stage_metrics"][2]["deterministic_time"],
                         "total_wall_ms": r.metrics["end_to_end_ms"]})
    density = []
    for horizon in (16, 64, 192, 480):
        r = schedule_work_method_time(build_density_ladder(horizon))
        density.append({"horizon": horizon, "placements": r.metrics["placement_alternatives"],
                        "finish": r.plan["objective"][0], "target_deterministic": r.metrics["stage_metrics"][2]["deterministic_time"],
                        "total_wall_ms": r.metrics["end_to_end_ms"]})
    classifier = run_challenge()
    if classifier["authoritative_first_failure"]["class"] != "ADMISSION_BOUND" or classifier["diagnostic_faithful_projection"]["raw_generated_placements"] != 64068 or classifier["diagnostic_faithful_projection"]["placement_alternatives"] != 64032:
        raise AssertionError("160/120 classification changed")
    p0, p1 = primary["production"], primary["p1"]
    return {"source_sha": actual, "runtime": {"python": platform.python_version(), "ortools": ortools.__version__},
            "base_main": "4ad6b7afe02a969e5f0d4ff34a1c9b0b328334fd",
            "primary": primary, "controls": controls, "activity_ladder": activity,
            "density_ladder": density, "professional_classifier": classifier,
            "classification": "P1_USEFUL_DIAGNOSTIC" if p1["total_deterministic"] < p0["total_deterministic"] and p1["end_to_end_ms"] < p0["end_to_end_ms"] else "NO_COMPLETE_PATH_JUSTIFICATION",
            "recommendation": "Interpret complete-path and repeated floor wall evidence before any canonical implementation change; otherwise prioritize the 160/120 admission architecture."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    from pathlib import Path
    result = run_evidence(args.source_sha)
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
