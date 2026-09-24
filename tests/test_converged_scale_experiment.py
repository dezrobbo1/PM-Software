"""Tests for the 64-declared converged native scale falsification."""
from __future__ import annotations

import unittest

from deterministic_scheduling_core.converged_scale_experiment import (
    AUTHORISED_STRUCTURES,
    BASELINE_ACTIVE_ACTIVITIES,
    DECLARED_ACTIVITIES,
    FLEXIBLE_PACKAGE_COUNT,
    PACKAGE_COUNT,
    build_problem,
    run_experiment,
)
from deterministic_scheduling_core.scheduling.work_method_time import validate_problem


class ConvergedScaleExperimentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = run_experiment()

    def test_fixture_hits_materially_larger_bounded_shape(self):
        shape = self.result["shape"]
        self.assertEqual(shape["declared_activities"], DECLARED_ACTIVITIES)
        self.assertEqual(shape["baseline_active_activities"], BASELINE_ACTIVE_ACTIVITIES)
        self.assertEqual(shape["work_packages"], PACKAGE_COUNT)
        self.assertEqual(shape["flexible_packages"], FLEXIBLE_PACKAGE_COUNT)
        self.assertEqual(shape["authorised_structures"], AUTHORISED_STRUCTURES)
        self.assertEqual(DECLARED_ACTIVITIES, 64)
        self.assertEqual(BASELINE_ACTIVE_ACTIVITIES, 48)
        self.assertEqual(AUTHORISED_STRUCTURES, 16)

    def test_baseline_matches_fixed_structural_control_and_is_canonical(self):
        baseline = self.result["baseline"]
        self.assertTrue(baseline["matches_control"])
        self.assertTrue(baseline["repeat"])
        self.assertTrue(baseline["all_stages_optimal"])
        self.assertGreater(baseline["candidate_metrics"]["placement_alternatives"], 0)
        self.assertGreater(baseline["candidate_metrics"]["variables"], 0)
        self.assertGreater(baseline["candidate_metrics"]["constraints"], 0)
        self.assertGreater(baseline["control_solver_calls"], 0)

    def test_accepted_history_recovery_matches_control_and_switches_untouched_structure(self):
        t1 = self.result["t1"]
        self.assertTrue(t1["matches_control"])
        self.assertTrue(t1["repeat"])
        self.assertGreaterEqual(len(t1["switched_packages"]), 1)
        self.assertTrue(t1["in_progress_activity"].startswith("WP02"))

    def test_promoted_recovery_survives_one_rolling_status_advance(self):
        t2 = self.result["t2"]
        self.assertTrue(t2["matches_control"])
        self.assertTrue(t2["repeat"])
        self.assertEqual(t2["lineage_count"], 1)
        self.assertIn(t2["target_state"], {"IN_PROGRESS", "COMPLETED"})
        self.assertEqual(
            t2["fixed_methods"][t2["target_package"]],
            t2["target_method"],
        )
        self.assertEqual(
            t2["selected_methods"][t2["target_package"]],
            t2["target_method"],
        )

    def test_inputs_and_prior_accepted_history_are_immutable(self):
        self.assertTrue(self.result["immutability"]["source_unchanged"])
        self.assertTrue(self.result["immutability"]["t1_history_unchanged"])
        self.assertTrue(self.result["evidence_valid"])

    def test_activity_admission_is_bounded_at_64_not_silently_unlimited(self):
        problem = build_problem()
        validate_problem(problem)
        extra = {
            "id": "OVER_LIMIT",
            "name": "Admission boundary sentinel",
            "modes": [{
                "id": "NORMAL",
                "processing_ticks": 1,
                "calendar_id": "SHIFT",
                "continuity": "SUSPENDABLE_AT_AVAILABILITY_GAPS",
                "requirements": [],
                "group_requirements": [],
            }],
        }
        problem.project["activities"].append(extra)
        with self.assertRaisesRegex(ValueError, "1..64 declared activities"):
            validate_problem(problem)


if __name__ == "__main__":
    unittest.main()
