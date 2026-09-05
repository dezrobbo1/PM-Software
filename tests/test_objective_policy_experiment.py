from __future__ import annotations

import unittest

from deterministic_scheduling_core.objective_policy_experiment import run_experiment


class ObjectivePolicyExperimentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = run_experiment()

    def test_case_reuses_bounded_work_method_problem(self) -> None:
        self.assertEqual(self.result.case.possible_activity_count, 33)
        self.assertEqual(len(self.result.alternatives), 8)
        self.assertEqual(self.result.approved_schedule.objective_finish, 37)

    def test_recovery_contains_one_hour_finish_vs_structure_tradeoff(self) -> None:
        fast = self.result.oracle_delta0
        stable = self.result.oracle_delta1
        self.assertEqual(fast.vector.protected_lateness, 0)
        self.assertEqual(stable.vector.protected_lateness, 0)
        self.assertEqual(fast.vector.finish, 41)
        self.assertEqual(stable.vector.finish, 42)
        self.assertEqual(fast.methods_by_package["WP-C"], "SEGMENTED")
        self.assertEqual(stable.methods_by_package["WP-C"], "CRANE")
        self.assertGreater(fast.vector.method_changes, stable.vector.method_changes)

    def test_delta_zero_restores_fastest_plan(self) -> None:
        decision = self.result.candidate_delta0
        self.assertEqual(decision.vector.finish, decision.best_finish)
        self.assertEqual(decision.allowed_finish, decision.best_finish)
        self.assertEqual(decision.methods, self.result.oracle_delta0.methods)
        self.assertEqual(decision.vector.as_tuple(), self.result.oracle_delta0.vector.as_tuple())

    def test_one_hour_envelope_selects_stable_recovery(self) -> None:
        decision = self.result.candidate_delta1
        self.assertEqual(decision.allowed_finish, decision.best_finish + 1)
        self.assertEqual(decision.methods, self.result.oracle_delta1.methods)
        self.assertEqual(decision.vector.as_tuple(), self.result.oracle_delta1.vector.as_tuple())
        self.assertEqual(decision.vector.method_changes, 0)

    def test_policy_stages_are_proven_and_reproducible(self) -> None:
        self.assertTrue(self.result.deterministic_repeat)
        self.assertTrue(
            all(status == "OPTIMAL" for _, status in self.result.candidate_delta0.stage_statuses)
        )
        self.assertTrue(
            all(status == "OPTIMAL" for _, status in self.result.candidate_delta1.stage_statuses)
        )

    def test_weighted_profiles_expose_hidden_tradeoff_policy(self) -> None:
        selections = {item.profile: item.methods for item in self.result.weighted}
        self.assertNotEqual(selections["finish-heavy"], selections["stability-heavy"])

    def test_hypothesis_is_not_falsified(self) -> None:
        self.assertFalse(self.result.falsified)


if __name__ == "__main__":
    unittest.main()
