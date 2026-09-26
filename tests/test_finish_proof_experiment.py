"""Exact status and model-identity checks; elapsed times are observations only."""
import unittest
import json
import os
from pathlib import Path

from deterministic_scheduling_core.finish_proof_experiment import (
    BASE_HASHES, _census, _fix_decisions, _identity, _selected_network, run_experiment,
)
from deterministic_scheduling_core.converged_scale_experiment import build_problem
from deterministic_scheduling_core.scheduling.work_method_time import (
    _compile_work_method_time, schedule_work_method_time,
)


class FinishProofDecompositionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = run_experiment()
        target = os.environ.get("FINISH_PROOF_EVIDENCE_OUTPUT")
        if target:
            Path(target).write_text(json.dumps(cls.report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def test_finish_anatomy_and_independent_control(self):
        report = self.report
        self.assertEqual(report["authoritative_finish"], 19)
        self.assertTrue(report["independent_control_matches_policy"])
        self.assertEqual(report["normal_finish_optimisation"]["status"], "OPTIMAL")
        self.assertEqual(report["normal_finish_optimisation"]["finish"], 19)
        for name, rows in report["decision_freedom_ladder"].items():
            with self.subTest(name=name):
                self.assertEqual([r["proof"]["status"] for r in rows], ["OPTIMAL", "INFEASIBLE"])
                self.assertLessEqual(rows[0]["proof"]["finish"], 19)
                self.assertEqual([r["base"] for r in rows], [report["base_model"]] * 2)
                for row in rows:
                    self.assertGreaterEqual(row["proof"]["deterministic_time"], 0)
                    self.assertGreater(row["proof"]["constraints"], row["base"]["base_constraints"])
        self.assertEqual([r["proof"]["status"] for r in report["pruned_selected_network"]["bounds"]],
                         ["OPTIMAL", "INFEASIBLE"])
        self.assertNotEqual(report["pruned_selected_network"]["base"], report["base_model"])

    def test_named_fix_preserves_anonymous_group_and_inactive_alternatives(self):
        problem = build_problem()
        plan = schedule_work_method_time(problem).plan
        compiled = _compile_work_method_time(problem)
        before = _identity(compiled)
        count = _fix_decisions(compiled, plan, 3)
        self.assertGreaterEqual(count, len(plan["selected_methods"]) + len(plan["selected_modes"]))
        self.assertEqual(before["base_variables"], len(compiled.model.proto.variables))
        self.assertEqual(before["placement_alternatives"], compiled.placement_count)
        self.assertEqual(before["base_constraints"] + count, len(compiled.model.proto.constraints))
        pruned = _selected_network(problem, plan)
        self.assertEqual({a["id"] for a in pruned.project["activities"]},
                         {a["activity_id"] for a in plan["entries"]})
        self.assertEqual(set(pruned.project["activities"][0]["modes"][0]),
                         set(next(a for a in problem.project["activities"]
                                  if a["id"] == pruned.project["activities"][0]["id"])["modes"][0]))

    def test_census_and_ladders(self):
        report = self.report
        census = report["placement_census"]
        self.assertEqual(census["total_surviving"], 5626)
        self.assertEqual(census["total_surviving"], report["base_model"]["placement_alternatives"])
        self.assertEqual(census["unique_temporal_patterns_within_activity_mode"]
                         + census["named_assignment_expansion"]
                         + census["solver_internal_anonymous_witness_expansion"], census["total_surviving"])
        self.assertEqual(census["selected_placements"] + census["mode_inactive_placements"]
                         + census["structural_inactive_placements"], census["total_surviving"])
        self.assertEqual({int(n) for n in report["activity_ladder"]}, {8, 16, 32, 48, 64})
        self.assertEqual({r["base"]["placement_alternatives"]
                          for r in report["activity_ladder"].values()}, {8, 16, 32, 48, 64})
        self.assertEqual({int(h): row["base"]["placement_alternatives"]
                          for h, row in report["density_ladder"].items()},
                         {16: 129, 64: 513, 192: 1537, 480: 3841})
        for row in report["density_ladder"].values():
            self.assertEqual(row["base"]["declared_activities"], 8)
            self.assertEqual([r["proof"]["status"] for r in row["bounds"]], ["OPTIMAL", "INFEASIBLE"])
            self.assertTrue(row["source_unchanged"])

    def test_professional_and_production_identity(self):
        report = self.report
        self.assertEqual(report["production_plan_hashes"], BASE_HASHES)
        self.assertTrue(report["source_unchanged"])
        self.assertEqual(report["professional_semantics"]["selected_methods"]["BUILD"], "ALT")
        self.assertEqual(report["professional_semantics"]["selected_methods"]["CREW"], "FAST")
        self.assertEqual([r["proof"]["status"] for r in report["professional_semantics"]["bounds"]],
                         ["OPTIMAL", "INFEASIBLE"])
        suspended = report["professional_semantics"]["suspended_workface"]
        self.assertEqual(suspended["productive_periods"], [[0, 2], [4, 6]])
        self.assertEqual(suspended["envelope"], [0, 6])
        self.assertGreaterEqual(suspended["next_entry_start"], 6)
        self.assertTrue(suspended["source_unchanged"])
        classifier = report["professional_scale"]
        self.assertTrue(classifier["faithful_projection_valid"])
        self.assertEqual(classifier["authoritative_first_failure"]["class"], "ADMISSION_BOUND")
        self.assertEqual(classifier["diagnostic_faithful_projection"]["placement_limit"], 20_000)


if __name__ == "__main__":
    unittest.main()
