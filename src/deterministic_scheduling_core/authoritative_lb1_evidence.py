"""Source-bound, future-only adoption comparison; never imported by production."""
from __future__ import annotations

import argparse
import json
import platform
import subprocess
from pathlib import Path

import ortools

from deterministic_scheduling_core.canonical_cost_experiment import (
    build_density_ladder, build_stage_ladder, semantic_plan,
)
from deterministic_scheduling_core.converged_scale_experiment import build_problem as scale_problem
from deterministic_scheduling_core.factored_finish_search_experiment import build_group_stress
from deterministic_scheduling_core.native_work_method_time import (
    build_problem as small_problem, solve_fixed_controls,
)
from deterministic_scheduling_core.professional_scale_challenge import run_challenge
from deterministic_scheduling_core.professional_workface_experiment import build_problem as professional_problem
from deterministic_scheduling_core.project.work_method_time import input_hash
from deterministic_scheduling_core.scheduling.work_method_time import (
    _schedule_work_method_time_batched, schedule_work_method_time, validate_plan,
)


def _comparison(name, problem):
    source = input_hash(problem)
    new = schedule_work_method_time(problem)
    old = _schedule_work_method_time_batched(problem)
    same = semantic_plan(new.plan) == semantic_plan(old.plan)
    same_digits = new.metrics["canonical_vector"] == old.metrics["canonical_vector"]
    if not same or not same_digits or input_hash(problem) != source:
        raise AssertionError(f"exact S2/S0 adoption equality failed: {name}")
    validate_plan(problem, new.plan)
    validate_plan(problem, old.plan)
    rows = new.metrics["finish_query_metrics"]
    return {
        "name": name, "source_input_hash": source,
        "declared_activities": len(problem.project["activities"]),
        "active_activities": len(new.plan["entries"]),
        "placements": new.metrics["placement_alternatives"],
        "finish": new.plan["objective"][0], "lb1": new.metrics["finish_lower_bound"],
        "exact_semantic_match": same, "exact_canonical_match": same_digits,
        "physical_status": new.plan["physical_status"],
        "s2": {
            "plan_hash": new.plan["plan_hash"], "compiler": new.plan["solver"]["compiler"],
            "finish_queries": [{"bound": q["bound"], "result": q["result"],
                                "solver_status": q["solver_status"],
                                "deterministic_time": q["deterministic_time"],
                                "elapsed_wall_ms": q["elapsed_wall_ms"]} for q in rows],
            "finish_budget_remaining": new.metrics["finish_remaining_deterministic_budget"],
            "lb_derivation_ms": new.metrics["finish_lower_bound_derivation_ms"],
            "finish_deterministic_time": new.metrics["finish_search_deterministic_time"],
            "global_timing_deterministic_time": new.metrics["stage_metrics"][1]["deterministic_time"],
            "canonical_deterministic_time": sum(s["deterministic_time"] for s in new.metrics["stage_metrics"][2:]),
            "total_deterministic_time": sum(s["deterministic_time"] for s in new.metrics["stage_metrics"]),
            "solver_calls": new.metrics["solver_calls"],
            "policy_stages": new.metrics["policy_stage_count"],
            "model_builds": new.metrics["model_builds"],
            "end_to_end_ms": new.metrics["end_to_end_ms"],
        },
        "s0": {
            "plan_hash": old.plan["plan_hash"],
            "finish_deterministic_time": old.metrics["stage_metrics"][0]["deterministic_time"],
            "total_deterministic_time": sum(s["deterministic_time"] for s in old.metrics["stage_metrics"]),
            "solver_calls": old.metrics["solver_calls"], "end_to_end_ms": old.metrics["end_to_end_ms"],
        },
    }


def run_evidence(source_sha):
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if source_sha != actual:
        raise AssertionError("source SHA does not equal checked-out HEAD")
    small = small_problem()
    fixed = solve_fixed_controls(small)
    cases = [_comparison("small_named", small),
             _comparison("professional", professional_problem(workface=True, deadline=True)),
             _comparison("anonymous_group", build_group_stress()),
             _comparison("64_48", scale_problem())]
    if fixed["best"] is None or fixed["best"]["objective"][0] != cases[0]["finish"]:
        raise AssertionError("fixed-network control disagrees with the authoritative finish")
    activity = [_comparison(f"activity_{n}", build_stage_ladder(n)) for n in (8, 16, 32, 48, 64)]
    density = [_comparison(f"density_{h}", build_density_ladder(h)) for h in (16, 64, 192, 480)]
    classifier = run_challenge()
    if (classifier["authoritative_first_failure"]["class"] != "ADMISSION_BOUND" or
        classifier["diagnostic_faithful_projection"]["raw_generated_placements"] != 64068 or
        classifier["diagnostic_faithful_projection"]["placement_alternatives"] != 64032):
        raise AssertionError("professional classification changed")
    return {
        "milestone": "authoritative-lb1-seeded-exact-finish-v0", "source_sha": actual,
        "runtime": {"python": platform.python_version(), "ortools": ortools.__version__},
        "historical_s0_hashes": {c["name"]: c["s0"]["plan_hash"] for c in cases if c["name"] in ("small_named", "professional", "64_48")},
        "independent_small_control": {"objective": fixed["best"]["objective"], "branch_count": len(fixed["branches"])},
        "cases": cases, "activity_ladder": activity, "density_ladder": density,
        "professional_classifier": classifier,
        "classification": "A — adoption proven (subject to exact-head regression and review)",
        "next_question": "Re-evaluate admitted placement/model representation only after exact-head adoption verification.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = run_evidence(args.source_sha)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
