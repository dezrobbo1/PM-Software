"""Bounded placement/build cost measurement and exact canonical batching control."""
from __future__ import annotations

from math import prod
from pathlib import Path
from time import perf_counter
import argparse
import json
import platform

import ortools

from deterministic_scheduling_core.converged_scale_experiment import (
    build_problem as build_converged_problem,
)
from deterministic_scheduling_core.native_work_method_time import (
    build_problem as build_small_problem,
)
from deterministic_scheduling_core.professional_workface_experiment import (
    build_problem as build_professional_semantics_problem,
)
from deterministic_scheduling_core.professional_scale_challenge import run_challenge
from deterministic_scheduling_core.project.planning_workspace import digest
from deterministic_scheduling_core.project.work_method_time import (
    WorkMethodTimeProject,
    input_hash,
)
from deterministic_scheduling_core.scheduling.work_method_time import (
    WorkMethodTimeResult,
    _compile_work_method_time,
    _schedule_work_method_time_batched,
    _schedule_work_method_time_sequential_oracle,
    _solve_compiled_stages,
    schedule_work_method_time,
    validate_plan,
)
from deterministic_scheduling_core.scheduling.canonical_batching import (
    MAX_SAFE_BLOCK_VALUE, CanonicalBlock, CanonicalDigit, build_lexicographic_blocks,
)


def schedule_batched_challenger(
    problem: WorkMethodTimeProject,
    *,
    safety_bound: int = MAX_SAFE_BLOCK_VALUE,
) -> WorkMethodTimeResult:
    """Compatibility wrapper for the historical PR #42 experiment only."""
    return _schedule_work_method_time_batched(
        problem, safety_bound=safety_bound, compiler="canonical-batching-challenger/0",
    )


def semantic_plan(plan: dict) -> dict:
    """Project a plan onto persisted scheduling semantics, excluding proof metadata."""
    return {key: value for key, value in plan.items() if key not in {"solver", "plan_hash"}}


def build_stage_ladder(activity_count: int) -> WorkMethodTimeProject:
    """Grow activity/stage count while retaining one placement per activity."""
    if activity_count not in {8, 16, 32, 48, 64}:
        raise ValueError("stage ladder supports 8, 16, 32, 48 or 64 activities")
    activities = []
    for index in range(activity_count):
        row = {
            "id": f"S{index:02d}",
            "name": f"Stage sentinel {index + 1}",
            "not_before": index,
            "latest_finish": index + 1,
            "modes": [{
                "id": "FIXED",
                "processing_ticks": 1,
                "calendar_id": "ALWAYS",
                "continuity": "SUSPENDABLE_AT_AVAILABILITY_GAPS",
                "requirements": [],
            }],
        }
        if index:
            row["predecessors"] = [f"S{index - 1:02d}"]
        activities.append(row)
    return WorkMethodTimeProject({
        "id": f"stage-ladder-{activity_count}",
        "name": f"Canonical stage ladder {activity_count}",
        "horizon_ticks": activity_count,
        "calendars": [{"id": "ALWAYS", "daily_windows": [[0, 48]]}],
        "resources": [],
        "activities": activities,
        "objective_activity_id": activities[-1]["id"],
        "pool_riggers": False,
    })


def build_density_ladder(horizon: int) -> WorkMethodTimeProject:
    """Keep eight activities and stage count fixed while placement density grows."""
    if horizon not in {16, 64, 192, 480}:
        raise ValueError("density ladder supports horizons 16, 64, 192 or 480")
    activities = [{
        "id": f"W{index}",
        "name": f"Parallel work {index + 1}",
        "modes": [{
            "id": "FIXED",
            "processing_ticks": 1,
            "calendar_id": "ALWAYS",
            "continuity": "SUSPENDABLE_AT_AVAILABILITY_GAPS",
            "requirements": [],
        }],
    } for index in range(7)]
    activities.append({
        "id": "DONE",
        "name": "Handoff",
        "predecessors": [f"W{index}" for index in range(7)],
        "modes": [{
            "id": "FIXED",
            "processing_ticks": 0,
            "calendar_id": "ALWAYS",
            "continuity": "SUSPENDABLE_AT_AVAILABILITY_GAPS",
            "requirements": [],
        }],
    })
    return WorkMethodTimeProject({
        "id": f"density-ladder-{horizon}",
        "name": f"Placement density ladder horizon {horizon}",
        "horizon_ticks": horizon,
        "calendars": [{"id": "ALWAYS", "daily_windows": [[0, 48]]}],
        "resources": [],
        "activities": activities,
        "objective_activity_id": "DONE",
        "pool_riggers": False,
    })


def fixture_matrix() -> tuple[tuple[str, str, WorkMethodTimeProject], ...]:
    return (
        ("small_existing", "anchor", build_small_problem()),
        ("professional_semantics_small", "anchor",
         build_professional_semantics_problem(workface=True, deadline=True)),
        ("converged_64_48", "anchor", build_converged_problem()),
        *((f"stage_{count}", "stage_ladder", build_stage_ladder(count))
          for count in (8, 16, 32, 48, 64)),
        *((f"density_{horizon}", "placement_ladder", build_density_ladder(horizon))
          for horizon in (16, 64, 192, 480)),
    )


def _stage_aggregates(metrics: dict) -> dict:
    aggregates = {}
    for stage in metrics["stage_metrics"]:
        row = aggregates.setdefault(stage["stage_type"], {
            "stages": 0,
            "elapsed_wall_ms": 0.0,
            "deterministic_time": 0.0,
        })
        row["stages"] += 1
        row["elapsed_wall_ms"] += stage["elapsed_wall_ms"]
        row["deterministic_time"] += stage["deterministic_time"]
    return aggregates


def _shape(problem: WorkMethodTimeProject, plan: dict) -> dict:
    return {
        "declared_activities": len(problem.project["activities"]),
        "active_activities": len(plan["entries"]),
        "work_packages": len(problem.work_packages),
        "authorised_structures": prod(len(package.methods) for package in problem.work_packages),
    }


def _cost_summary(metrics: dict) -> dict:
    return {
        "total_stages": metrics["solver_calls"],
        "stage_costs": _stage_aggregates(metrics),
        "stage_evidence": metrics["stage_metrics"],
        "input_copy_ms": metrics["input_copy_ms"],
        "validation_ms": metrics["validation_ms"],
        "productive_case_compile_ms": metrics["productive_case_compile_ms"],
        "placement_generation_ms": metrics["placement_generation_ms"],
        "cp_model_assembly_ms": metrics["cp_model_assembly_ms"],
        "canonical_block_assembly_ms": metrics.get("canonical_block_assembly_ms", 0.0),
        "build_ms": metrics["build_ms"],
        "solve_ms": metrics["solve_ms"],
        "result_extraction_ms": metrics["result_extraction_ms"],
        "independent_allocation_ms": metrics["independent_allocation_ms"],
        "stored_plan_validation_ms": metrics["stored_plan_validation_ms"],
        "independent_validation_ms": metrics["independent_validation_ms"],
        "end_to_end_ms": metrics["end_to_end_ms"],
        "total_deterministic_time": sum(
            stage["deterministic_time"] for stage in metrics["stage_metrics"]
        ),
    }


def run_fixed_model_stage_prefix_ladder() -> dict:
    """Measure proof-count growth on one fixed 64-activity compiled model.

    These are diagnostic policy-prefix proofs, not complete challenger plans. The
    base model, placement set and declared activities remain identical in every
    row; only the number of adjacent authoritative stages proved is increased.
    """
    problem = build_stage_ladder(64)
    before = input_hash(problem)
    rows = []
    for canonical_stage_count in (16, 32, 64, 96, 128):
        compiled = _compile_work_method_time(problem)
        stages = compiled.stages[:2 + canonical_stage_count]
        _, _, stage_metrics = _solve_compiled_stages(compiled, stages)
        rows.append({
            "canonical_stages_proven": canonical_stage_count,
            "total_stages": len(stages),
            "declared_activities": len(problem.project["activities"]),
            "placement_alternatives": compiled.placement_count,
            "base_variables": compiled.compile_metrics["base_variables"],
            "base_constraints": compiled.compile_metrics["base_constraints"],
            "build_ms": (compiled.built_at - compiled.started_at) * 1000,
            "solve_ms": sum(stage["elapsed_wall_ms"] for stage in stage_metrics),
            "deterministic_time": sum(
                stage["deterministic_time"] for stage in stage_metrics
            ),
            "stage_evidence": stage_metrics,
        })
    fixed_shape = len({
        (
            row["declared_activities"],
            row["placement_alternatives"],
            row["base_variables"],
            row["base_constraints"],
        )
        for row in rows
    }) == 1
    return {
        "purpose": "isolate sequential proof-stage count on a fixed compiled model",
        "complete_policy_only_in_final_row": True,
        "rows": rows,
        "fixed_model_shape": fixed_shape,
        "source_unchanged": input_hash(problem) == before,
        "evidence_valid": (
            fixed_shape
            and input_hash(problem) == before
            and all(all(stage["status"] == "OPTIMAL" for stage in row["stage_evidence"])
                    for row in rows)
        ),
    }


def _classify_cost_outcome(cases: list[dict], evidence_valid: bool) -> tuple[str, str, dict]:
    """Classify this bounded run from direct measured-cost comparisons."""
    scale = next(case for case in cases if case["name"] == "converged_64_48")
    sequential = scale["sequential"]
    challenger = scale["challenger"]
    global_proof_ms = sum(
        sequential["stage_costs"][stage_type]["elapsed_wall_ms"]
        for stage_type in ("finish", "global_timing")
    )
    lower_canonical_ms = sum(
        sequential["stage_costs"][stage_type]["elapsed_wall_ms"]
        for stage_type in ("method_canonical", "mode_canonical", "placement_canonical")
    )
    challenger_block_ms = challenger["stage_costs"]["canonical_block"]["elapsed_wall_ms"]
    placement_generation_ms = sequential["placement_generation_ms"]
    cp_model_assembly_ms = sequential["cp_model_assembly_ms"]
    placement_and_model_assembly_ms = placement_generation_ms + cp_model_assembly_ms
    construction_dominant_component = (
        "placement_generation"
        if placement_generation_ms >= cp_model_assembly_ms
        else "cp_model_assembly"
    )
    predicates = {
        "sequential_solve_exceeds_build": sequential["solve_ms"] > sequential["build_ms"],
        "lower_canonical_exceeds_global_proofs": lower_canonical_ms > global_proof_ms,
        "blocks_reduce_lower_canonical_cost": challenger_block_ms < lower_canonical_ms,
        "challenger_reduces_solver_calls": challenger["total_stages"] < sequential["total_stages"],
        "challenger_reduces_solve_wall": challenger["solve_ms"] < sequential["solve_ms"],
        "challenger_reduces_end_to_end_wall": (
            challenger["end_to_end_ms"] < sequential["end_to_end_ms"]
        ),
    }
    basis = {
        "fixture": "converged_64_48",
        "sequential_solve_share_of_end_to_end": (
            sequential["solve_ms"] / sequential["end_to_end_ms"]
        ),
        "lower_canonical_share_of_sequential_solve": (
            lower_canonical_ms / sequential["solve_ms"]
        ),
        "solver_calls": [sequential["total_stages"], challenger["total_stages"]],
        "placement_generation_ms": placement_generation_ms,
        "cp_model_assembly_ms": cp_model_assembly_ms,
        "placement_and_model_assembly_ms": placement_and_model_assembly_ms,
        "construction_dominant_component": construction_dominant_component,
        "solve_wall_speedup": scale["ratios"]["solve_wall_speedup"],
        "end_to_end_speedup": scale["ratios"]["end_to_end_speedup"],
        "measured_predicates": predicates,
        "decision_rule": (
            "A requires every measured predicate; D next rejects a challenger that does not "
            "reduce calls or observed total cost; B then requires combined placement generation "
            "and CP-model assembly to exceed solving; "
            "other exact mixed evidence is C. Correctness failure is E."
        ),
        "note": (
            "This is a bounded exact-head observation, not a universal threshold or "
            "cross-environment performance guarantee."
        ),
    }
    if not evidence_valid:
        return (
            "E_NEW_CORRECTNESS_FAILURE",
            "classify and fix the exact-equivalence failure before scale optimisation",
            basis,
        )
    if all(predicates.values()):
        return (
            "A_CANONICAL_PROOF_DOMINATED",
            "investigate the bounded placement/model-size and finish/global-proof interaction",
            basis,
        )
    if (challenger["total_stages"] >= sequential["total_stages"]
            or challenger["end_to_end_ms"] >= sequential["end_to_end_ms"]):
        return (
            "D_CHALLENGER_NOT_JUSTIFIED",
            "treat this wall observation as diagnostic; do not change the authoritative proof policy without correctness evidence",
            basis,
        )
    if placement_and_model_assembly_ms > sequential["solve_ms"]:
        if construction_dominant_component == "placement_generation":
            recommendation = (
                "investigate an alternative exact placement representation and generation "
                "strategy"
            )
        else:
            recommendation = (
                "investigate an alternative exact placement representation and CP-model "
                "assembly strategy"
            )
        return (
            "B_PLACEMENT_GENERATION_DOMINATED",
            recommendation,
            basis,
        )
    return (
        "C_MIXED_BOTTLENECK",
        "choose the first intervention from the measured dominant cost and dependency order",
        basis,
    )


def run_cost_decomposition() -> dict:
    """Compare authoritative batching with the retained sequential oracle.

    The historical ``challenger`` output key is retained for PR #42 evidence
    consumers; it now describes the authoritative batched run.
    """
    cases = []
    for name, family, problem in fixture_matrix():
        before = input_hash(problem)
        sequential = _schedule_work_method_time_sequential_oracle(problem)
        challenger = schedule_work_method_time(problem)
        repeat = schedule_work_method_time(problem)
        validate_plan(problem, sequential.plan)
        validate_plan(problem, challenger.plan)
        semantic_equal = semantic_plan(sequential.plan) == semantic_plan(challenger.plan)
        sequential_vector = [
            {
                "name": stage["stage"],
                "stage_type": stage["stage_type"],
                "value": stage["value"],
                "maximum": stage["maximum"],
            }
            for stage in sequential.metrics["stage_metrics"][2:]
        ]
        exact_policy = all(
            sequential.plan[key] == challenger.plan[key]
            for key in (
                "selected_methods", "selected_modes", "objective", "entries",
                "allocation_witness", "physical_status",
            )
        )
        sequential_cost = _cost_summary(sequential.metrics)
        challenger_cost = _cost_summary(challenger.metrics)
        cases.append({
            "name": name,
            "family": family,
            "roles": {"sequential": "legacy_oracle", "challenger": "authoritative_batching"},
            "authoritative_plan_hash": challenger.plan["plan_hash"],
            "authoritative_semantic_digest": digest(semantic_plan(challenger.plan)),
            "sequential_oracle_semantic_digest": digest(semantic_plan(sequential.plan)),
            "shape": {
                **_shape(problem, sequential.plan),
                "placement_alternatives": sequential.metrics["placement_alternatives"],
                "workface_intervals": sequential.metrics["workface_intervals"],
                "base_variables": sequential.metrics["base_variables"],
                "base_constraints": sequential.metrics["base_constraints"],
                "sequential_variables": sequential.metrics["variables"],
                "sequential_constraints": sequential.metrics["constraints"],
                "challenger_variables": challenger.metrics["variables"],
                "challenger_constraints": challenger.metrics["constraints"],
            },
            "sequential": sequential_cost,
            "challenger": {
                **challenger_cost,
                "blocks": challenger.metrics["canonical_blocks"],
                "canonical_vector": challenger.metrics["canonical_vector"],
            },
            "ratios": {
                "solver_call_reduction": (
                    sequential.metrics["solver_calls"] / challenger.metrics["solver_calls"]
                ),
                "solve_wall_speedup": (
                    sequential.metrics["solve_ms"] / challenger.metrics["solve_ms"]
                    if challenger.metrics["solve_ms"] else None
                ),
                "end_to_end_speedup": (
                    sequential.metrics["end_to_end_ms"] / challenger.metrics["end_to_end_ms"]
                    if challenger.metrics["end_to_end_ms"] else None
                ),
            },
            "equivalence": {
                "exact_policy_match": exact_policy,
                "exact_canonical_vector_match": (
                    sequential_vector == challenger.metrics["canonical_vector"]
                ),
                "exact_semantic_plan_match": semantic_equal,
                "physical_status_match": (
                    sequential.plan["physical_status"] == challenger.plan["physical_status"]
                ),
                "repeat_plan_identical": challenger.plan == repeat.plan,
                "source_unchanged": input_hash(problem) == before,
            },
        })
    fixed_model_stage_prefix = run_fixed_model_stage_prefix_ladder()
    professional_scale = run_challenge()
    professional_scale_valid = (
        professional_scale["evidence_valid"]
        and professional_scale["authoritative_first_failure"]["class"] == "ADMISSION_BOUND"
        and professional_scale["faithful_projection_valid"]
        and professional_scale["diagnostic_faithful_projection"]["raw_generated_placements"] == 64068
        and professional_scale["diagnostic_faithful_projection"]["placement_alternatives"] == 64032
    )
    evidence_valid = (
        all(all(case["equivalence"].values()) for case in cases)
        and fixed_model_stage_prefix["evidence_valid"]
        and professional_scale_valid
    )
    classification, recommendation, classification_basis = _classify_cost_outcome(
        cases,
        evidence_valid,
    )
    return {
        "milestone": "authoritative-canonical-batching-v0-follow-up",
        "measurement_roles": {"sequential": "legacy_oracle", "challenger": "authoritative_batching"},
        "measurement_note": (
            "wall-clock values are observations from this run; deterministic_time is the "
            "OR-Tools proof counter returned by each solve and is not wall time"
        ),
        "runtime": {
            "python": platform.python_version(),
            "ortools": ortools.__version__,
            "platform": platform.platform(),
        },
        "integer_safety_bound": MAX_SAFE_BLOCK_VALUE,
        "cases": cases,
        "fixed_model_stage_prefix_ladder": fixed_model_stage_prefix,
        "professional_scale_follow_up": professional_scale,
        "evidence_valid": evidence_valid,
        "classification_basis": classification_basis,
        "classification": classification,
        "recommended_next_milestone": recommendation,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run_cost_decomposition()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    if not result["evidence_valid"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
