"""Exact four-cell policy and bounded independent physical controls."""
import inspect
import json
import os
from pathlib import Path
import subprocess
import unittest

from deterministic_scheduling_core import factored_finish_search_experiment as experiment
from deterministic_scheduling_core import scheduling
from deterministic_scheduling_core.converged_scale_experiment import build_problem
from deterministic_scheduling_core.finish_proof_experiment import BASE_HASHES
from deterministic_scheduling_core.resource_assignment_experiment import EXACT_FEASIBLE
from deterministic_scheduling_core.scheduling import work_method_time


class FactoredFinishSearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = experiment.run_experiment(source_sha=os.getenv("SOURCE_HEAD_SHA"))
        if os.getenv("SOURCE_HEAD_SHA"):
            actual_head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
            if cls.result["source_sha"] != actual_head:
                raise AssertionError("evidence JSON source SHA must match checked-out PR head")
        output = os.getenv("FACTORED_FINISH_EVIDENCE_OUTPUT")
        if output:
            path = Path(output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(cls.result, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def test_base_and_complete_policy_matrix(self):
        r = self.result
        self.assertEqual(r["production_hashes"], BASE_HASHES)
        self.assertEqual(r["authoritative_finish"], 19)
        matrix = r["matrix"]
        self.assertEqual(set(matrix["cells"]), {"R0/S0", "R0/S1", "R1/S0", "R1/S1"})
        self.assertEqual({cell["finish"] for cell in matrix["cells"].values()}, {19})
        self.assertEqual({cell["semantic_plan_sha256"] for cell in matrix["cells"].values()},
                         {matrix["cells"]["R0/S0"]["semantic_plan_sha256"]})
        self.assertEqual({json.dumps(cell["canonical_vector"]) for cell in matrix["cells"].values()},
                         {json.dumps(matrix["cells"]["R0/S0"]["canonical_vector"])})
        self.assertTrue(matrix["semantic_equal"] and matrix["canonical_equal"] and matrix["physical_equal"])
        self.assertTrue(matrix["rank"]["all_ranks_match"])
        self.assertEqual(matrix["rank"]["compared_flattened_ranks"], 5626)
        self.assertTrue(matrix["source_unchanged"])

    def test_model_census_is_honest_about_cross_product(self):
        r0, r1 = (self.result["matrix"]["model_census"][name] for name in ("R0", "R1"))
        self.assertEqual((r0["flattened_placements"], r0["variables"], r0["constraints"]), (5626, 5832, 3860))
        self.assertEqual(r1["temporal_named_choices"], 4024)
        self.assertEqual(r1["flattened_rank_rows"], r0["flattened_placements"])
        self.assertEqual(r1["conjunction_pair_vars"], 3204)
        self.assertGreater(r1["conjunction_pair_vars"], 0)
        self.assertGreater(r1["variables"], r0["variables"])
        self.assertGreater(r1["constraints"], r0["constraints"])
        self.assertEqual(r1["workface_intervals"], r0["workface_intervals"])

    def test_exact_unknown_optimum_trace_and_bounds(self):
        matrix = self.result["matrix"]
        for name, cell in matrix["cells"].items():
            with self.subTest(name=name):
                self.assertEqual(cell["physical_status"], EXACT_FEASIBLE)
                self.assertGreater(cell["solver_calls"], 0)
                self.assertGreaterEqual(cell["solve_deterministic_time"], 0)
                if name.endswith("S1"):
                    search = cell["search"]
                    self.assertEqual(search["initial_lower"], 0)
                    self.assertEqual(search["initial_upper"], build_problem().project["horizon_ticks"])
                    self.assertEqual(search["exact_finish"], 19)
                    self.assertTrue(search["finish_feasible"] and search["one_tick_better_infeasible"])
                    self.assertEqual(search["query_count"], len(search["trace"]))
                    self.assertIn(19, [row["bound"] for row in search["trace"]])
                    self.assertIn(18, [row["bound"] for row in search["trace"]])
                    self.assertEqual(next(row for row in search["trace"] if row["bound"] == 18)["status"],
                                     "INFEASIBLE")
        for row in matrix["independent_bounds"].values():
            self.assertEqual(row[0]["feasible_finish"], 19)
            self.assertEqual(row[1]["status"], "INFEASIBLE")

    def test_independent_group_odd_cycle_exact_feasible_set(self):
        stress = self.result["group_stress_control"]
        oracle = stress["independent_oracle"]
        self.assertEqual(stress["fixed_starts"], {"R0": "INFEASIBLE", "R1": "INFEASIBLE"})
        self.assertEqual(oracle["best_policy"][0], stress["authoritative_finish"])
        self.assertGreater(oracle["rejected_group_witness_choices"], 0)
        self.assertEqual(oracle["fixed_start_combinations_rejected"], 8)
        for evidence in stress["complete_feasible_rank_sets"].values():
            self.assertEqual(evidence["count"], oracle["feasible_complete_choices"])
            self.assertEqual(evidence["status"], "OPTIMAL")
        self.assertEqual(stress["complete_feasible_rank_sets"]["R0"]["sha256"],
                         stress["complete_feasible_rank_sets"]["R1"]["sha256"])

    def test_professional_named_and_ladders(self):
        r = self.result
        self.assertTrue(r["named_resource_control"]["semantic_equal"])
        self.assertTrue(r["professional_control"]["semantic_equal"])
        self.assertTrue(r["suspended_workface_control"]["semantic_equal"])
        self.assertTrue(r["group_stress_control"]["semantic_equal"])
        self.assertEqual([r["activity_ladder"][str(n)]["placements"] for n in (8, 16, 32, 48, 64)],
                         [8, 16, 32, 48, 64])
        self.assertEqual([r["density_ladder"][str(h)]["placements"] for h in (16, 64, 192, 480)],
                         [129, 513, 1537, 3841])
        for row in (*r["activity_ladder"].values(), *r["density_ladder"].values()):
            self.assertEqual(row["S1"]["exact_finish"], row["exact_finish"])
            self.assertTrue(row["S1"]["one_tick_better_infeasible"])
        census = r["professional_factored_diagnostic_census"]
        self.assertEqual((census["raw_flattened"], census["eligible_flattened"]), (64068, 64032))
        self.assertTrue(census["model_not_built_or_solved"])
        self.assertEqual(r["professional_scale"]["authoritative_first_failure"]["class"], "ADMISSION_BOUND")

    def test_repeatability_and_production_isolation(self):
        problem = build_problem()
        first = experiment._search_finish(work_method_time._compile_work_method_time(problem))
        second = experiment._search_finish(work_method_time._compile_work_method_time(problem))
        def proof(trace):
            return [(row["bound"], row["status"], row["feasible_finish"],
                     row["deterministic_time"], row["branches"], row["conflicts"])
                    for row in trace["trace"]]
        self.assertEqual(proof(first), proof(second))
        self.assertNotIn("factored_finish_search_experiment", inspect.getsource(work_method_time))
        self.assertEqual(self.result["classification"]["category"], "E")


if __name__ == "__main__":
    unittest.main()
