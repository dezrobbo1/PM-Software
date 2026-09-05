import unittest

from deterministic_scheduling_core.criticality_semantics_experiment import (
    METHOD_SENSITIVE_ACTIVITY,
    REMOTE_METHOD_PACKAGE,
    RESOURCE_SENSITIVE_ACTIVITY,
    run_experiment,
)


class CriticalitySemanticsExperimentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = run_experiment()

    def test_approved_plan_hits_protected_handoff(self):
        self.assertEqual(self.result.approved_handoff, 60)

    def test_resource_sensitive_activity_has_phantom_logic_flexibility(self):
        item = self.result.resource_sensitive
        self.assertEqual(item.activity_id, RESOURCE_SENSITIVE_ACTIVITY)
        self.assertGreater(item.logic.total_float, 0)
        self.assertLess(item.fixed_structure_slack, item.logic.total_float)
        self.assertIsNotNone(item.first_method_change_delta)
        self.assertLessEqual(item.first_method_change_delta, item.logic.total_float)
        self.assertTrue(item.counterfactual.adaptive_feasible)
        self.assertGreater(item.counterfactual.adaptive_method_changes, 0)

    def test_logic_critical_activity_can_be_recovered_by_authorised_method_change(self):
        item = self.result.method_sensitive
        self.assertEqual(item.activity_id, METHOD_SENSITIVE_ACTIVITY)
        self.assertEqual(item.logic.total_float, 0)
        self.assertEqual(item.fixed_structure_slack, 0)
        self.assertFalse(item.counterfactual.fixed_structure_feasible)
        self.assertTrue(item.counterfactual.adaptive_feasible)
        self.assertLessEqual(item.counterfactual.adaptive_finish, 60)
        self.assertEqual(
            item.counterfactual.adaptive_methods_by_package[REMOTE_METHOD_PACKAGE],
            "SEGMENTED",
        )

    def test_execution_criticality_is_not_one_logic_path(self):
        self.assertNotIn(RESOURCE_SENSITIVE_ACTIVITY, self.result.logic_zero_float_ids)
        self.assertIn(METHOD_SENSITIVE_ACTIVITY, self.result.logic_zero_float_ids)
        self.assertFalse(self.result.falsified)

    def test_adaptive_counterfactual_is_canonical(self):
        self.assertTrue(self.result.repeated_adaptive_canonical)


if __name__ == "__main__":
    unittest.main()
