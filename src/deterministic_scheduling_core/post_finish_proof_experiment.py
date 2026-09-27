"""Bounded post-finish proof anatomy; never imported by production scheduling."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import platform
import subprocess
from time import perf_counter

import ortools
from ortools.sat.python import cp_model

from deterministic_scheduling_core.canonical_cost_experiment import build_density_ladder, build_stage_ladder
from deterministic_scheduling_core.converged_scale_experiment import build_problem as scale_problem
from deterministic_scheduling_core.factored_finish_search_experiment import build_group_stress
from deterministic_scheduling_core.native_work_method_time import build_problem as small_problem, solve_fixed_controls
from deterministic_scheduling_core.professional_scale_challenge import run_challenge
from deterministic_scheduling_core.professional_workface_experiment import build_problem as professional_problem
from deterministic_scheduling_core.project.work_method_time import input_hash
from deterministic_scheduling_core.scheduling.canonical_batching import CanonicalDigit, build_lexicographic_blocks
from deterministic_scheduling_core.scheduling.work_method_time import (
    _canonical_block_stages, _compile_work_method_time, _new_solver,
    schedule_work_method_time, validate_plan,
)


BASE_HASHES = {
    "small_named": "d54db4bc5f6cdd64b1ca3d8fd3f92b9f45103cae2230685e81363936db746761",
    "professional": "733a4023ff6c78735aa4ccc5d8003a1f31ecde80f3851ffadbd4dadfa2100acb",
    "64_48": "0698e2c95e7aed5ee35d7d343349e77b88e39121bfbad41fa865c6818d923410",
}


def _shape(model):
    return {"variables": len(model.proto.variables), "constraints": len(model.proto.constraints),
            "proto_sha256": sha256(str(model.proto).encode()).hexdigest(),
            "objective_absent": not model.has_objective()}


def _proof(context, expression, kind, value):
    model = context.clone()
    if kind == "optimization":
        model.minimize(expression)
    else:
        model.add(expression <= value - (kind == "better"))
    solver = _new_solver()
    start = perf_counter()
    status = solver.solve(model)
    elapsed = (perf_counter() - start) * 1000
    accepted = (cp_model.INFEASIBLE,) if kind == "better" else (
        (cp_model.OPTIMAL,) if kind == "optimization" else (cp_model.OPTIMAL, cp_model.FEASIBLE))
    if status not in accepted:
        raise AssertionError(f"{kind}: expected {accepted}, observed {solver.status_name(status)}")
    actual = solver.value(expression) if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) else None
    if kind == "optimization" and actual != value:
        raise AssertionError(f"stage optimum {actual} != authoritative {value}")
    if kind == "at_value" and actual > value:
        raise AssertionError("feasibility witness exceeds authoritative optimum")
    p = solver.response_proto
    return {"status": "INFEASIBLE" if status == cp_model.INFEASIBLE else "SAT" if kind != "optimization" else "OPTIMAL",
            "value": actual, "bound": None if kind == "optimization" else value - (kind == "better"),
            "deterministic_time": float(p.deterministic_time), "elapsed_wall_ms": elapsed,
            "solver_wall_time_ms": float(p.wall_time) * 1000,
            "branches": int(p.num_branches), "conflicts": int(p.num_conflicts),
            "binary_propagations": int(p.num_binary_propagations),
            "integer_propagations": int(p.num_integer_propagations),
            "variables": len(model.proto.variables), "constraints": len(model.proto.constraints)}


def _anatomy(context, expression, optimum, preceding):
    # Clone identity is established *before* adding the three mutually exclusive deltas.
    identities = [_shape(context.clone()) for _ in range(3)]
    if len({json.dumps(item, sort_keys=True) for item in identities}) != 1 or not identities[0]["objective_absent"]:
        raise AssertionError("diagnostic stage contexts differ before objective/bound insertion")
    return {"context": identities[0], "preceding_fixed_stages": preceding,
            "optimization": _proof(context, expression, "optimization", optimum),
            "at_value": _proof(context, expression, "at_value", optimum),
            "one_better": _proof(context, expression, "better", optimum)}


def _pipeline(metrics):
    keys = ("input_copy_ms", "validation_ms", "productive_case_compile_ms", "placement_generation_ms",
            "cp_model_assembly_ms", "finish_lower_bound_derivation_ms", "finish_search_wall_ms",
            "canonical_block_assembly_ms", "result_extraction_ms", "independent_allocation_ms",
            "stored_plan_validation_ms")
    phases = {k: metrics[k] for k in keys}
    phases["global_timing_wall_ms"] = metrics["stage_metrics"][1]["elapsed_wall_ms"]
    phases["canonical_proof_wall_ms"] = sum(s["elapsed_wall_ms"] for s in metrics["stage_metrics"][2:])
    # build_ms and solve_ms are overlapping summaries; they are deliberately excluded.
    residual = metrics["end_to_end_ms"] - sum(phases.values())
    if residual < -0.01:
        raise AssertionError(f"intentional wall-clock double count: {residual}")
    return {"non_overlapping_ms": phases, "residual_ms": residual,
            "end_to_end_ms": metrics["end_to_end_ms"],
            "overlapping_summaries_not_added": {"build_ms": metrics["build_ms"], "solve_ms": metrics["solve_ms"]}}


def inspect_case(name, problem, *, anatomy=True):
    source_hash = input_hash(problem)
    production = schedule_work_method_time(problem)
    plan, metrics = production.plan, production.metrics
    validate_plan(problem, plan)
    if input_hash(problem) != source_hash:
        raise AssertionError("source changed during public calculation")
    if name in BASE_HASHES and plan["plan_hash"] != BASE_HASHES[name]:
        raise AssertionError(f"merged-main production plan identity changed: {name}")
    compiled = _compile_work_method_time(problem)
    if compiled.placement_count != metrics["placement_alternatives"]:
        raise AssertionError("diagnostic model differs from production placement shape")
    F, G = plan["objective"]
    blocks = build_lexicographic_blocks(CanonicalDigit(s.name, s.maximum) for s in compiled.stages[2:])
    if len(blocks) != metrics["canonical_block_count"]:
        raise AssertionError("block partition differs from production")
    inventory = []
    for i, (block, document, stage_metric) in enumerate(zip(blocks, metrics["canonical_blocks"], metrics["stage_metrics"][2:])):
        if block.to_document() != {k: v for k, v in document.items() if k != "solved_value"}:
            raise AssertionError("canonical block inventory differs from production")
        digits = [d.name for d in block.digits]
        inventory.append({"index": i, "name": block.name, "value": document["solved_value"],
                          "maximum": block.maximum, "safety_bound": block.safety_bound,
                          "stage_model_variables": metrics["variables"],
                          "stage_model_constraints": metrics["constraints"] - len(blocks) + i,
                          "digits": document["digits"], "digit_count": len(digits),
                          "first_digit": digits[0], "last_digit": digits[-1],
                          "digit_types": {prefix: sum(n.startswith(prefix + ":") for n in digits)
                                          for prefix in ("method", "mode", "placement")},
                          "production_cost": stage_metric})
    if [d["name"] for b in inventory for d in b["digits"]] != [d["name"] for d in metrics["canonical_digits"]]:
        raise AssertionError("canonical digit lost, repeated or reordered")
    row = {"name": name, "source_input_hash": source_hash, "plan_hash": plan["plan_hash"],
           "objective": [F, G], "physical_status": plan["physical_status"],
           "canonical_vector": metrics["canonical_vector"],
           "shape": {k: metrics[k] for k in ("placement_alternatives", "workface_intervals", "variables", "constraints")},
           "finish": {"queries": metrics["finish_query_metrics"], "lower_bound": metrics["finish_lower_bound"],
                      "stage": metrics["stage_metrics"][0]},
           "global_timing_production": metrics["stage_metrics"][1],
           "global_stage_shape": {"variables": metrics["base_variables"],
                                  "constraints": metrics["base_constraints"] + 1},
           "blocks": inventory, "pipeline_wall": _pipeline(metrics),
           "post_finish_deterministic": {
               "global": metrics["stage_metrics"][1]["deterministic_time"],
               "canonical": sum(s["deterministic_time"] for s in metrics["stage_metrics"][2:])}}
    if anatomy:
        # Global A/B/C starts from one context after the exact finish equality.
        compiled.model.add(compiled.stages[0].expression == F)
        row["global_anatomy"] = _anatomy(compiled.model, compiled.stages[1].expression, G, 1)
        if (row["global_anatomy"]["context"]["variables"] != row["global_stage_shape"]["variables"] or
            row["global_anatomy"]["context"]["constraints"] != row["global_stage_shape"]["constraints"]):
            raise AssertionError("global production and diagnostic stage shapes differ")
        # Production assembles digits only after proving/fixing global timing.
        compiled.model.add(compiled.stages[1].expression == G)
        stages = _canonical_block_stages(compiled, blocks)
        row["block_anatomy"] = []
        for i, (stage, block) in enumerate(zip(stages, inventory)):
            row["block_anatomy"].append({"name": stage.name,
                **_anatomy(compiled.model, stage.expression, block["value"], i + 2)})
            if (row["block_anatomy"][-1]["context"]["variables"] != block["stage_model_variables"] or
                row["block_anatomy"][-1]["context"]["constraints"] != block["stage_model_constraints"]):
                raise AssertionError("block production and diagnostic stage shapes differ")
            compiled.model.add(stage.expression == block["value"])
        # Fresh stage optimisation is compared to actual production stage values.
        row["fresh_vs_sequence"] = {
            "global_value_equal": row["global_anatomy"]["optimization"]["value"] == G,
            "block_values_equal": all(a["optimization"]["value"] == b["value"] for a, b in zip(row["block_anatomy"], inventory)),
            "production_deterministic": [s["deterministic_time"] for s in metrics["stage_metrics"][1:]],
            "fresh_deterministic": [row["global_anatomy"]["optimization"]["deterministic_time"],
                                    *(b["optimization"]["deterministic_time"] for b in row["block_anatomy"])],
        }
    if input_hash(problem) != source_hash:
        raise AssertionError("source changed during diagnostic calculation")
    return row


def run_evidence(source_sha):
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if actual != source_sha:
        raise AssertionError("evidence SHA does not match checked-out HEAD")
    controls = [inspect_case("small_named", small_problem()),
                inspect_case("professional", professional_problem(workface=True, deadline=True)),
                inspect_case("anonymous_group", build_group_stress())]
    primary = inspect_case("64_48", scale_problem())
    fixed = solve_fixed_controls(small_problem())
    if fixed["best"]["objective"][0] != controls[0]["objective"][0] or primary["objective"][0] != 19:
        raise AssertionError("independent fixed-network or primary finish mismatch")
    activity = [inspect_case(f"activity_{n}", build_stage_ladder(n), anatomy=False) for n in (8, 16, 32, 48, 64)]
    density = [inspect_case(f"density_{h}", build_density_ladder(h), anatomy=False) for h in (16, 64, 192, 480)]
    classifier = run_challenge()
    if classifier["authoritative_first_failure"]["class"] != "ADMISSION_BOUND" or classifier["diagnostic_faithful_projection"]["raw_generated_placements"] != 64068 or classifier["diagnostic_faithful_projection"]["placement_alternatives"] != 64032:
        raise AssertionError("professional classifier changed")
    g, c = primary["post_finish_deterministic"].values()
    block_costs = [b["production_cost"]["deterministic_time"] for b in primary["blocks"]]
    if c > g and max(block_costs) > sum(block_costs) / 2:
        solver_class = "S-B — canonical block 000 dominates the post-finish solver family"
    elif c > g:
        solver_class = "S-C — canonical proof distributed across blocks"
    else:
        solver_class = "S-A — global timing exceeds combined canonical proof"
    phases = primary["pipeline_wall"]["non_overlapping_ms"]
    build = sum(phases[k] for k in ("input_copy_ms", "validation_ms", "productive_case_compile_ms", "placement_generation_ms", "cp_model_assembly_ms", "finish_lower_bound_derivation_ms", "canonical_block_assembly_ms"))
    solver_wall = sum(phases[k] for k in ("finish_search_wall_ms", "global_timing_wall_ms", "canonical_proof_wall_ms"))
    after = sum(phases[k] for k in ("result_extraction_ms", "independent_allocation_ms", "stored_plan_validation_ms"))
    pipeline_class = "P-A — solver wall dominated" if solver_wall > max(build, after) else "P-B — model construction dominated" if build > after else "P-C — post-solve dominated"
    return {"milestone": "post-finish-proof-cost-decomposition-v0", "source_sha": actual,
            "runtime": {"python": platform.python_version(), "ortools": ortools.__version__},
            "baseline_hashes_verified": BASE_HASHES, "primary": primary,
            "independent_fixed_network": {"objective": fixed["best"]["objective"], "branches": len(fixed["branches"])},
            "controls": controls, "activity_ladder": activity, "density_ladder": density,
            "professional_classifier": classifier,
            "solver_classification": solver_class, "pipeline_classification": pipeline_class,
            "pipeline_family_wall_ms": {"pre_solver_and_assembly": build, "solver": solver_wall, "post_solver": after},
            "next_recommendation": "Interpret post-finish solver proof against complete wall pipeline before selecting another architecture experiment."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    data = run_evidence(args.source_sha)
    from pathlib import Path
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
