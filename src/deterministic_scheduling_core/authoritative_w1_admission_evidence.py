"""Source-bound adoption evidence; diagnostic runner, never imported by production."""
from __future__ import annotations

import argparse
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import subprocess
from tempfile import NamedTemporaryFile
from time import perf_counter
from unittest.mock import patch

import ortools
from ortools.sat.python import cp_model

from deterministic_scheduling_core.converged_scale_experiment import build_problem as scale
from deterministic_scheduling_core.factored_finish_search_experiment import build_group_stress
from deterministic_scheduling_core.native_work_method_time import build_problem as small
from deterministic_scheduling_core.professional_workface_experiment import build_problem as professional
from deterministic_scheduling_core.professional_scale_challenge import build_professional_projection
from deterministic_scheduling_core.project.work_method_time import WorkMethodTimeProject, from_document, input_hash
from deterministic_scheduling_core.project.rolling_structural_status import from_document as cycle_from_document
from deterministic_scheduling_core.scheduling.accepted_work_method_time import validate_input as validate_accepted
from deterministic_scheduling_core.scheduling.rolling_structural_status import validate_cycle
from deterministic_scheduling_core.scheduling.canonical_batching import CanonicalDigit, build_lexicographic_blocks
from deterministic_scheduling_core.scheduling.work_method_time import (
    _canonical_block_stages, _compile_work_method_time, schedule_work_method_time,
    validate_plan, validate_problem,
)
from deterministic_scheduling_core.w1_model_integration_experiment import low_density_case

BASE = "fcce684febefc36be800b0c70a7d943089f10b7f"
ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/fixtures"


def _check_source(source_sha):
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if head != source_sha:
        raise ValueError("recorded source SHA differs from checkout HEAD")
    for args in (["git", "diff", "--quiet"], ["git", "diff", "--cached", "--quiet"]):
        if subprocess.run(args, cwd=ROOT, check=False).returncode:
            raise ValueError("tracked source changed after checkout")


def _save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".partial")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, path)


def _signature(plan):
    document = {k: v for k, v in plan.items() if k not in ("solver", "plan_hash")}
    return sha256(json.dumps(document, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _proto_bytes(model):
    with NamedTemporaryFile(suffix=".pb") as artifact:
        if not model.export_to_file(artifact.name):
            raise AssertionError("could not serialize the CP-SAT model")
        return Path(artifact.name).stat().st_size


def _cap_sentinels():
    source = deepcopy(low_density_case(65).project)
    source["horizon_ticks"] = 480
    for activity in source["activities"]:
        activity.pop("predecessors", None)
        activity["not_before"] = 0
        activity["latest_finish"] = 480
    source["activities"][-1]["predecessors"] = [a["id"] for a in source["activities"][:-1]]
    results = {}
    with patch.object(cp_model.CpSolver, "solve", side_effect=AssertionError("cap reached solver")):
        try:
            schedule_work_method_time(WorkMethodTimeProject(source))
        except ValueError as exc:
            assert "20000 placement alternatives" in str(exc)
            results["retained_placement_limit"] = str(exc)
        else:
            raise AssertionError("retained placement cap did not reject")
        source["activities"] = source["activities"][:45]
        source["objective_activity_id"] = source["activities"][-1]["id"]
        for activity in source["activities"]:
            activity["latest_finish"] = 400
            activity["exclusion_groups"] = ["FRONT", "REAR"]
        source["activities"][-1]["predecessors"] = [a["id"] for a in source["activities"][:-1]]
        try:
            schedule_work_method_time(WorkMethodTimeProject(source))
        except ValueError as exc:
            assert "20000 workface intervals" in str(exc)
            results["workface_interval_limit"] = str(exc)
        else:
            raise AssertionError("workface cap did not reject")
    results["solver_invoked"] = False
    return results


def run(source_sha, output):
    output = Path(output)
    result = {"source_sha": source_sha, "starting_main_sha": BASE,
              "runtime": {"python": platform.python_version(), "ortools": ortools.__version__,
                          "platform": platform.platform()}, "classification": "INCOMPLETE"}
    _save(output, result)
    try:
        _check_source(source_sha)
        baseline = json.loads((FIXTURES / "w1-adoption/pre-adoption.json").read_text())
        prior = json.loads((FIXTURES / "w1-adoption/pr53-exact-result.json").read_text())
        assert baseline["source_sha"] == BASE
        result["frozen_pre_adoption_hashes"] = {k: v["plan_hash"] for k, v in baseline["controls"].items()}
        result["predecessor_exact_source_sha"] = prior["source_sha"]
        result["historical_compatibility"] = []
        legacy = (("canonical-batching-legacy/small-sequential-plan.json", small()),
                  ("canonical-batching-legacy/professional-sequential-plan.json", professional(workface=True, deadline=True)),
                  ("lb1-seeded-legacy/small-batched-plan.json", small()),
                  ("lb1-seeded-legacy/professional-batched-plan.json", professional(workface=True, deadline=True)),
                  ("lb1-seeded-legacy/scale_64_48-batched-plan.json", scale()))
        with patch.object(cp_model.CpSolver, "solve", side_effect=AssertionError("historic validation invoked solver")):
            for name, case in legacy:
                plan = json.loads((FIXTURES / name).read_text())
                original = deepcopy(plan)
                assert validate_plan(case, plan) == "PROVEN_FEASIBLE" and plan == original
                result["historical_compatibility"].append({"fixture": name, "plan_hash": plan["plan_hash"],
                                                           "unchanged": True, "solver_invoked": False})
            for name in ("canonical-batching-legacy/accepted-sequential-reference.json",
                         "lb1-seeded-legacy/accepted-batched-reference.json"):
                item = json.loads((FIXTURES / name).read_text())
                source = from_document(item["source"])
                validate_accepted(source, source, item["reference_plan"], item["status_workspace"])
                result["historical_compatibility"].append({"fixture": name, "unchanged": True, "solver_invoked": False})
            for name in ("canonical-batching-legacy/rolling-sequential-cycle.json",
                         "lb1-seeded-legacy/rolling-batched-cycle.json"):
                validate_cycle(cycle_from_document(json.loads((FIXTURES / name).read_text())))
                result["historical_compatibility"].append({"fixture": name, "unchanged": True, "solver_invoked": False})
        _save(output, result)
        controls = {"small": small(), "professional": professional(workface=True, deadline=True),
                    "group_suspended": build_group_stress(), "64_48": scale()}
        result["admitted_controls"] = {}
        for name, problem in controls.items():
            t = perf_counter()
            current = schedule_work_method_time(problem)
            frozen = baseline["controls"][name]
            assert input_hash(problem) == frozen["input_hash"]
            assert {k: v for k, v in current.plan.items() if k not in ("solver", "plan_hash")} == frozen["semantic_plan"]
            assert current.metrics["canonical_vector"] == frozen["canonical_vector"]
            assert current.plan["solver"]["canonical_blocks"] == frozen["canonical_blocks"]
            assert validate_plan(problem, current.plan) == "PROVEN_FEASIBLE"
            result["admitted_controls"][name] = {
                "input_hash": input_hash(problem), "prior_plan_hash": frozen["plan_hash"],
                "new_plan_hash": current.plan["plan_hash"], "semantic_equal": True,
                "canonical_vector_equal": True, "physical_status": current.plan["physical_status"],
                "u0_raw": current.metrics["u0_raw_placements"],
                "u0_eligible": current.metrics["u0_eligible_placements"],
                "w1_retained": current.metrics["w1_retained_placements"],
                "wall_ms_observation": (perf_counter() - t) * 1000}
            _save(output, result)
        problem = build_professional_projection()
        source_hash = input_hash(problem)
        assert source_hash == prior["professional_input_hash"]
        compiled = _compile_work_method_time(problem, use_w1=True)
        proto = compiled.model.proto
        before = {"variables": len(proto.variables), "constraints": len(proto.constraints),
                  "bytes": _proto_bytes(compiled.model), "placement_literals": compiled.placement_count,
                  "resource_optional_intervals": compiled.compile_metrics["resource_optional_intervals"],
                  "workface_optional_intervals": compiled.workface_interval_count}
        assert (before["variables"], before["constraints"], compiled.placement_count,
                before["resource_optional_intervals"], before["workface_optional_intervals"]) == (8308, 7952, 7812, 6705, 409)
        blocks = build_lexicographic_blocks(tuple(CanonicalDigit(s.name, s.maximum) for s in compiled.stages[2:]))
        _canonical_block_stages(compiled, blocks)
        post = {"variables": len(proto.variables), "constraints": len(proto.constraints),
                "bytes": _proto_bytes(compiled.model), "canonical_digits": len(compiled.stages)-2,
                "canonical_blocks": len(blocks)}
        assert (post["variables"], post["constraints"], post["canonical_digits"], post["canonical_blocks"]) == (8640, 8284, 332, 26)
        result["professional_model"] = {"input_hash": source_hash, "pre_canonical": before,
                                        "post_witness": post}
        _save(output, result)
        result["professional_attempts"] = []
        for attempt in (1, 2):
            t = perf_counter()
            current = schedule_work_method_time(problem)
            metrics = current.metrics
            vector = [{k: digit[k] for k in ("name", "value", "maximum")}
                      for digit in metrics["canonical_vector"]]
            assert current.plan["objective"] == prior["result"]["objective"]
            assert current.plan["selected_methods"] == prior["result"]["selected_methods"]
            assert current.plan["selected_modes"] == prior["result"]["selected_modes"]
            assert vector == prior["result"]["canonical_vector"]
            ranks = {d["name"].removeprefix("placement:"): d["value"] for d in vector
                     if d["name"].startswith("placement:")}
            assert ranks == prior["result"]["selected_original_placement_ranks"]
            assert validate_plan(problem, current.plan) == "PROVEN_FEASIBLE"
            entry = {"attempt": attempt, "objective": current.plan["objective"],
                     "methods": current.plan["selected_methods"], "modes": current.plan["selected_modes"],
                     "original_placement_ranks": ranks, "canonical_vector": vector,
                     "plan_hash": current.plan["plan_hash"], "physical_signature": _signature(current.plan),
                     "physical_status": current.plan["physical_status"],
                     "finish_lower_bound": metrics["finish_lower_bound"],
                     "finish_queries": metrics["finish_query_metrics"],
                     "finish_remaining_budget": metrics["finish_remaining_deterministic_budget"],
                     "proof_stages": metrics["stage_metrics"], "solver_calls": metrics["solver_calls"],
                     "total_deterministic_time": sum(m["deterministic_time"] for m in metrics["stage_metrics"]),
                     "observed_wall_ms": (perf_counter()-t)*1000}
            result["professional_attempts"].append(entry)
            _save(output, result)
        a,b = result["professional_attempts"]
        assert all(a[k] == b[k] for k in ("objective", "methods", "modes", "original_placement_ranks",
                                        "canonical_vector", "plan_hash", "physical_signature"))
        result["admission_ladder"] = []
        for n in (65,96,128,160):
            case = low_density_case(n)
            current = schedule_work_method_time(case)
            expected = [n,sum((i+1)*i for i in range(n))]
            assert current.plan["objective"] == expected
            try:
                validate_accepted(case,case,{}, {})
            except ValueError as exc:
                accepted_boundary = str(exc)
            else:
                raise AssertionError("accepted history admitted >64")
            result["admission_ladder"].append({"activities": n, "objective": expected,
                                                "placement_count": current.metrics["placement_alternatives"],
                                                "accepted_history_rejection": accepted_boundary})
            _save(output, result)
        source = deepcopy(low_density_case(160).project)
        source["horizon_ticks"] = 161
        extra = deepcopy(source["activities"][-1]); extra.update(id="A160", name="Activity 160", predecessors=["A159"], not_before=160, latest_finish=161)
        source["activities"].append(extra); source["objective_activity_id"] = "A160"
        try:
            validate_problem(WorkMethodTimeProject(source))
        except ValueError as exc:
            result["rejected_161"] = str(exc)
        else:
            raise AssertionError("161 declarations admitted")
        assert "1..160" in result["rejected_161"]
        result["cap_sentinels"] = _cap_sentinels()
        _check_source(source_sha)
        result["classification"] = "A_W1_ADOPTION_AND_160_ADMISSION_PROVEN"
        _save(output, result)
        return result
    except BaseException as exc:
        result["classification"] = "INCOMPLETE_GATE_FAILURE"
        result["failure"] = {"type": type(exc).__name__, "message": str(exc)}
        _save(output, result)
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--output", required=True)
    options = parser.parse_args()
    run(options.source_sha, options.output)


if __name__ == "__main__":
    main()
