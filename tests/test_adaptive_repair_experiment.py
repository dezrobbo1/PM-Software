from __future__ import annotations

import unittest

from deterministic_scheduling_core.adaptive_repair_experiment import (
    CRANE_RESOURCE,
    PROTECTED_HANDOFF,
    SEED_ACTIVITY,
    build_case,
    run_experiment,
)


class AdaptiveRepairExperimentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = run_experiment()

    def test_case_has_bounded_professional_shape(self) -> None:
        case, _, _ = build_case()
        self.assertEqual(len(case.packages), 12)
        self.assertGreaterEqual(case.possible_activity_count, 100)
        self.assertLessEqual(case.possible_activity_count, 200)
        self.assertEqual(case.possible_activity_count, 160)
        self.assertEqual(case.fixed_network_count, 16)
        flexible = [package for package in case.packages if len(package.methods) > 1]
        self.assertEqual(len(flexible), 4)
        self.assertIn(CRANE_RESOURCE, {resource.id for resource in case.resources})
        groups = {
            group
            for package in case.packages
            for method in package.methods
            for activity in method.activities
            for group in activity.exclusion_groups
        }
        self.assertEqual(groups, {"WF-A", "WF-B"})

    def test_approved_plan_meets_protected_handoff(self) -> None:
        self.assertEqual(self.result.approved_schedule.objective_finish, PROTECTED_HANDOFF)
        self.assertEqual(dict(self.result.approved_methods)["WP-09"], "CRANE")

    def test_local_disturbance_has_remote_resource_coupling_without_precedence(self) -> None:
        case = self.result.case
        self.assertEqual(SEED_ACTIVITY, "P04A07")
        self.assertEqual(self.result.remote_resource_activity, "P09A07")
        self.assertEqual(self.result.remote_package, "WP-09")
        package_map = {package.id: package for package in case.packages}
        self.assertNotIn("WP-09", package_map["WP-04"].predecessors)
        self.assertNotIn("WP-04", package_map["WP-09"].predecessors)

    def test_fixed_local_repair_exposes_boundary_failure(self) -> None:
        self.assertFalse(self.result.fixed.feasible)
        self.assertEqual(self.result.fixed.free_activity_count, 5)
        self.assertEqual(self.result.fixed.free_method_count, 0)

    def test_adaptive_repair_matches_full_with_far_less_decision_freedom(self) -> None:
        full = self.result.full
        adaptive = self.result.adaptive
        self.assertTrue(full.feasible)
        self.assertTrue(adaptive.feasible)
        self.assertIsNotNone(full.selected)
        self.assertIsNotNone(adaptive.selected)
        assert full.selected is not None
        assert adaptive.selected is not None
        self.assertEqual(full.selected.vector.as_tuple(), adaptive.selected.vector.as_tuple())
        self.assertEqual(full.selected.methods, adaptive.selected.methods)
        self.assertEqual(dict(adaptive.selected.methods)["WP-09"], "SEGMENTED")
        self.assertEqual(adaptive.selected.vector.finish, PROTECTED_HANDOFF)
        self.assertLess(adaptive.free_activity_count, full.free_activity_count // 2)
        self.assertEqual(adaptive.free_method_count, 1)
        self.assertEqual(full.free_method_count, 4)

    def test_adaptive_expansion_is_semantic_and_canonical(self) -> None:
        trace = "\n".join(self.result.adaptive.expansion_trace)
        self.assertIn("C04", trace)
        self.assertIn("precedence", trace)
        self.assertIn("Work-Method", trace)
        self.assertIn("handover", trace)
        self.assertTrue(self.result.repeat_canonical)

    def test_hypothesis_is_not_falsified(self) -> None:
        self.assertFalse(self.result.falsified)


if __name__ == "__main__":
    unittest.main()
