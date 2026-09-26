"""Tests for the 64-activity converged native scale falsification."""
from __future__ import annotations

from copy import deepcopy
import unittest
from unittest.mock import patch

from ortools.sat.python import cp_model

from deterministic_scheduling_core.converged_scale_experiment import (
    build_problem,
    run_experiment,
)
from deterministic_scheduling_core.project.rolling_structural_status import (
    from_document as cycle_from_document,
    to_document as cycle_to_document,
)
from deterministic_scheduling_core.scheduling.rolling_structural_status import (
    validate_cycle,
)
from deterministic_scheduling_core.scheduling.work_method_time import (
    validate_plan,
    validate_problem,
)


class ConvergedScaleExperimentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = run_experiment()

    def test_fixture_reaches_materially_larger_bounded_shape(self):
        shape = self.evidence["shape"]
        self.assertEqual(shape["declared_activities"], 64)
        self.assertEqual(shape["baseline_active_activities"], 48)
        self.assertEqual(shape["work_packages"], 8)
        self.assertEqual(shape["authorised_structures"], 16)
        self.assertEqual(shape["fixed_control_branches"], 64)

    def test_baseline_joint_candidate_matches_fixed_structural_control(self):
        baseline = self.evidence["baseline"]
        self.assertTrue(baseline["matches_control"])
        self.assertTrue(baseline["repeat_plan_matches"])
        self.assertEqual(baseline["selected_methods"]["WP-02"], "STANDARD")
        self.assertEqual(baseline["selected_methods"]["WP-04"], "STANDARD")
        self.assertEqual(baseline["selected_methods"]["WP-06"], "STANDARD")
        self.assertEqual(baseline["selected_methods"]["WP-07"], "STANDARD")
        self.assertEqual(baseline["plan"]["physical_status"], "PROVEN_FEASIBLE")

    def test_scale_metrics_are_captured_without_hiding_solver_shape(self):
        baseline = self.evidence["baseline"]
        metrics = baseline["candidate_metrics"]
        for key in (
            "placement_alternatives",
            "variables",
            "constraints",
            "build_ms",
            "solve_ms",
            "end_to_end_ms",
            "solver_calls",
        ):
            self.assertIn(key, metrics)
            self.assertGreater(metrics[key], 0)
        self.assertEqual(metrics["solver_calls"], baseline["solver_stages"])
        self.assertEqual(baseline["solver_stages"], 11)
        self.assertEqual(metrics["canonical_block_count"], 9)
        self.assertLessEqual(metrics["placement_alternatives"], 20000)

    def test_t1_recovery_locks_begun_package_and_changes_untouched_crane_package(self):
        recovery = self.evidence["t1_recovery"]
        self.assertEqual(recovery["fixed_methods"]["WP-02"], "STANDARD")
        self.assertEqual(recovery["selected_methods"]["WP-02"], "STANDARD")
        self.assertEqual(recovery["selected_methods"]["WP-07"], "ALTERNATIVE")
        self.assertTrue(recovery["repeat_plan_matches"])
        self.assertTrue(recovery["status_unchanged"])

    def test_t2_started_recovery_method_is_hard_despite_shorter_counterfactual(self):
        t2 = self.evidence["t2"]
        self.assertEqual(t2["fixed_methods"]["WP-07"], "ALTERNATIVE")
        self.assertEqual(t2["selected_methods"]["WP-07"], "ALTERNATIVE")
        self.assertEqual(t2["illegal_selected_methods"]["WP-07"], "STANDARD")
        self.assertLess(t2["illegal_objective"][0], t2["objective"][0])
        self.assertEqual(t2["wp07_state"]["execution_state"], "IN_PROGRESS")
        self.assertEqual(t2["wp07_state"]["actual_periods"], [[16, 18]])
        self.assertEqual(t2["wp07_state"]["remaining_processing_ticks"], 3)
        self.assertTrue(t2["repeat_plan_matches"])

    def test_baseline_plan_and_t2_cycle_validate_without_solver_calls(self):
        problem = build_problem()
        baseline_plan = deepcopy(self.evidence["baseline"]["plan"])
        cycle_document = deepcopy(self.evidence["t2"]["cycle_document"])

        with patch.object(
            cp_model.CpSolver,
            "solve",
            side_effect=AssertionError("reopen validation must not schedule"),
        ):
            self.assertEqual(validate_plan(problem, baseline_plan), "PROVEN_FEASIBLE")
            cycle = cycle_from_document(cycle_document)
            validate_cycle(cycle)

        self.assertEqual(cycle_to_document(cycle), cycle_document)

    def test_65_declared_activities_remain_outside_this_bounded_admission(self):
        problem = build_problem()
        extra = deepcopy(problem.project["activities"][0])
        extra["id"] = "OUTSIDE_65"
        problem.project["activities"].append(extra)
        with self.assertRaisesRegex(ValueError, "1..64 declared activities"):
            validate_problem(problem)

    def test_experiment_evidence_is_self_consistent(self):
        self.assertTrue(self.evidence["evidence_valid"])
        self.assertTrue(self.evidence["source_unchanged"])


if __name__ == "__main__":
    unittest.main()
