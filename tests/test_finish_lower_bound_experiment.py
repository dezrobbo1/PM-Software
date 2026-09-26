"""Admissibility, identical-model proof, and production-isolation controls."""
import inspect
import json
import os
from pathlib import Path
import subprocess
import unittest

from deterministic_scheduling_core import finish_lower_bound_experiment as experiment
from deterministic_scheduling_core.finish_proof_experiment import BASE_HASHES
from deterministic_scheduling_core.converged_scale_experiment import build_problem
from deterministic_scheduling_core.project.work_method_time import input_hash
from deterministic_scheduling_core.scheduling import work_method_time


class FinishLowerBoundTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = experiment.run_experiment(source_sha=os.getenv("SOURCE_HEAD_SHA"))
        expected = os.getenv("SOURCE_HEAD_SHA")
        if expected:
            actual = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
            if cls.result["source_sha"] != actual:
                raise AssertionError("result SHA differs from checked-out HEAD")
        output = os.getenv("FINISH_LB_EVIDENCE_OUTPUT")
        if output:
            target = Path(output)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(cls.result, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def test_verified_production_and_independent_policy(self):
        r = self.result
        self.assertEqual(r["production_hashes"], BASE_HASHES)
        self.assertEqual(r["anchor"]["finish"], 19)
        self.assertTrue(r["independent_policy_control"])
        self.assertEqual([r["anchor"]["base"][k] for k in
                          ("declared_activities", "authorised_structures", "placement_alternatives",
                           "base_variables", "base_constraints", "workface_intervals")],
                         [64, 16, 5626, 5832, 3860, 0])

    def test_budget_samples_and_oracle_injection(self):
        r = self.result
        p = r["objective_progression"]
        self.assertEqual(p[-1]["status"], "OPTIMAL")
        self.assertEqual((p[-1]["incumbent"], p[-1]["best_objective_bound"]), (19, 19))
        self.assertEqual(p[-1]["integer_gap"], 0)
        self.assertTrue(all(v["status"] in {"UNKNOWN", "FEASIBLE", "OPTIMAL"} for v in p))
        self.assertEqual(set(r["oracle_injection"]), {"0", "11", "15", "17", "18", "19"})
        base = r["anchor"]["base"]
        for lower, row in r["oracle_injection"].items():
            with self.subTest(lower=lower):
                self.assertEqual((row["status"], row["finish"], row["injected_lower_bound"]),
                                 ("OPTIMAL", 19, int(lower)))
                self.assertEqual(row["pre_control_base"], base)
                self.assertEqual(row["bound_constraints"], 1)
                for counter in ("deterministic_time", "branches", "conflicts", "binary_propagations",
                                "integer_propagations", "best_objective_bound"):
                    self.assertIn(counter, row)

    def test_bounds_are_admissible_and_monotone_on_every_retained_case(self):
        r = self.result
        rows = [r["anchor"], *r["controls"].values(), *r["method_controls"].values(),
                *r["activity_ladder"].values(), *r["density_ladder"].values()]
        for row in rows:
            with self.subTest(finish=row["finish"], input=row["base"]["proto_text_sha256"]):
                self.assertEqual(list(row["bounds"]), ["LB0", "LB1", "LB2", "LB3"])
                values = [x["value"] for x in row["bounds"].values()]
                self.assertEqual(values, sorted(values))
                self.assertLessEqual(values[-1], row["finish"])
                self.assertTrue(row["source_unchanged"])
                for bound in row["bounds"].values():
                    self.assertEqual(bound["gap_ticks"], row["finish"] - bound["value"])
                    self.assertGreaterEqual(bound["derivation_wall_ms"], 0)

    def test_injected_proofs_and_total_cost_are_recorded(self):
        r = self.result
        for row in (r["anchor"], *r["activity_ladder"].values(), *r["density_ladder"].values()):
            self.assertEqual(row["baseline_finish_proof"]["finish"], row["finish"])
            for name, entry in row["injected"].items():
                proof = entry["proof"]
                self.assertEqual((proof["status"], proof["finish"]), ("OPTIMAL", row["finish"]))
                self.assertEqual(proof["pre_control_base"], row["base"])
                self.assertEqual(proof["injected_lower_bound"], row["bounds"][name]["value"])
                self.assertGreaterEqual(entry["total_observed_wall_ms"], proof["observed_wall_ms"])
                self.assertGreaterEqual(entry["total_with_shared_domain_compilation_wall_ms"],
                                        entry["total_observed_wall_ms"] + proof["compiler_build_wall_ms"])
                self.assertEqual(entry["derivation_solver_deterministic_time"], 0)

    def test_method_and_selected_network_diagnostics(self):
        r = self.result
        anchor = r["anchor"]["base"]
        union = r["method_controls"]["same_union_methods_fixed"]
        pruned = r["method_controls"]["selected_network_pruned"]
        self.assertEqual(union["base"], anchor)
        self.assertGreater(union["baseline_finish_proof"]["method_fix_constraints"], 0)
        self.assertEqual(pruned["baseline_finish_proof"]["method_fix_constraints"], 0)
        self.assertEqual((union["finish"], pruned["finish"]), (19, 19))
        for row in (union, pruned):
            self.assertEqual(row["baseline_finish_proof"]["finish"], 19)
            self.assertTrue(all(proof["finish"] == 19 for proof in row["injected"].values()))

    def test_adversarial_professional_named_and_anonymous_controls(self):
        controls = self.result["controls"]
        self.assertEqual(controls["professional"]["finish"], 7)
        self.assertEqual(controls["suspended_workface"]["finish"], 7)
        self.assertEqual(controls["anonymous_group"]["finish"], 5)
        self.assertLess(controls["professional"]["bounds"]["LB3"]["value"], 7)
        self.assertLess(controls["anonymous_group"]["bounds"]["LB3"]["value"], 5)
        self.assertEqual(controls["small"]["plan_hash"], BASE_HASHES["small"])
        self.assertEqual(controls["professional"]["plan_hash"], BASE_HASHES["professional"])
        self.assertNotIn("C_ALT", {e["activity_id"] for e in controls["professional"]["entries"]})
        suspended = {e["activity_id"]: e for e in controls["suspended_workface"]["entries"]}
        self.assertEqual(suspended["A_FAST"]["periods"], [[0, 2], [4, 6]])
        self.assertGreaterEqual(suspended["B"]["start"], suspended["A_FAST"]["finish"])
        self.assertTrue(any(e["assignments"] for e in controls["small"]["entries"]))
        self.assertEqual([controls["professional"]["bounds"][name]["value"]
                          for name in ("LB1", "LB2", "LB3")], [4, 6, 6])

    def test_ladders_classification_admission_and_source_isolation(self):
        r = self.result
        self.assertEqual([(n, r["activity_ladder"][str(n)]["finish"],
                           r["activity_ladder"][str(n)]["base"]["placement_alternatives"])
                          for n in (8, 16, 32, 48, 64)], [(n, n, n) for n in (8, 16, 32, 48, 64)])
        self.assertEqual([r["density_ladder"][str(h)]["base"]["placement_alternatives"]
                          for h in (16, 64, 192, 480)], [129, 513, 1537, 3841])
        self.assertEqual(r["professional_scale"]["authoritative_first_failure"]["class"],
                         "ADMISSION_BOUND")
        self.assertEqual(r["classification"]["category"], "E")
        self.assertNotIn("finish_lower_bound_experiment", inspect.getsource(work_method_time))
        problem = build_problem()
        before = input_hash(problem)
        first = experiment.derive_bounds(problem, work_method_time._compile_work_method_time(problem))
        second = experiment.derive_bounds(problem, work_method_time._compile_work_method_time(problem))
        self.assertEqual({k: v["value"] for k, v in first.items()},
                         {k: v["value"] for k, v in second.items()})
        self.assertEqual(before, input_hash(problem))


if __name__ == "__main__":
    unittest.main()
