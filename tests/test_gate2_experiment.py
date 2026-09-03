from __future__ import annotations

import unittest

from deterministic_scheduling_core.gate2_experiment import (
    ACCELERATED_REPAIR,
    CASE_ACCELERATION_HELPS,
    CASE_ACCELERATION_HURTS,
    GATE2_CASES,
    NORMAL_REPAIR,
    feasibility_errors,
    render_gate2_experiment,
    run_gate2_experiment,
)


class Gate2ExperimentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.comparisons = run_gate2_experiment()
        cls.by_case = {comparison.case.id: comparison for comparison in cls.comparisons}

    def test_two_cases_change_only_the_competing_specialist_context(self) -> None:
        self.assertEqual(2, len(GATE2_CASES))
        for case in GATE2_CASES:
            target = next(activity for activity in case.activities if activity.id == "G02")
            self.assertEqual(
                {NORMAL_REPAIR.id, ACCELERATED_REPAIR.id},
                {mode.id for mode in target.modes},
            )

    def test_every_primary_schedule_is_feasible(self) -> None:
        for comparison in self.comparisons:
            for result in (comparison.local_greedy, comparison.global_optimiser):
                with self.subTest(case=comparison.case.id, method=result.method):
                    self.assertEqual((), feasibility_errors(comparison.case, result))

    def test_acceleration_is_correct_when_specialist_is_lightly_loaded(self) -> None:
        comparison = self.by_case[CASE_ACCELERATION_HELPS.id]
        self.assertEqual(16, comparison.local_greedy.makespan)
        self.assertEqual(16, comparison.global_optimiser.makespan)
        self.assertEqual("ACCELERATED", comparison.local_greedy.by_id["G02"].mode.id)
        self.assertEqual("ACCELERATED", comparison.global_optimiser.by_id["G02"].mode.id)
        self.assertEqual(
            {"NORMAL": 19, "ACCELERATED": 16},
            {item.mode.id: item.makespan for item in comparison.counterfactuals},
        )

    def test_global_choice_beats_local_greedy_when_specialist_is_critical_elsewhere(self) -> None:
        comparison = self.by_case[CASE_ACCELERATION_HURTS.id]
        self.assertEqual(22, comparison.local_greedy.makespan)
        self.assertEqual(19, comparison.global_optimiser.makespan)
        self.assertEqual("ACCELERATED", comparison.local_greedy.by_id["G02"].mode.id)
        self.assertEqual("NORMAL", comparison.global_optimiser.by_id["G02"].mode.id)
        self.assertEqual(
            {"NORMAL": 19, "ACCELERATED": 22},
            {item.mode.id: item.makespan for item in comparison.counterfactuals},
        )

    def test_output_explains_context_sensitive_decision(self) -> None:
        output = render_gate2_experiment(self.comparisons)
        self.assertIn("CASE G2-A", output)
        self.assertIn("CASE G2-B", output)
        self.assertIn("NORMAL = 8h MECH", output)
        self.assertIn("ACCELERATED = 5h MECH+SPEC", output)
        self.assertIn("despite local greedy choosing ACCELERATED", output)
        self.assertIn("recovering 3h", output)
        self.assertIn("not inherently the better project decision", output)


if __name__ == "__main__":
    unittest.main()
