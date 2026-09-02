from __future__ import annotations

import unittest

from deterministic_scheduling_core.gate1_experiment import (
    RESOURCE_IDS,
    SAMPLE_ACTIVITIES,
    feasibility_errors,
    render_comparison,
    run_gate1_experiment,
)


class Gate1ExperimentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.comparison = run_gate1_experiment()

    def test_sample_has_real_resource_sequencing_choices(self) -> None:
        self.assertEqual(18, len(SAMPLE_ACTIVITIES))
        self.assertGreaterEqual(len(RESOURCE_IDS), 2)
        for resource_id in RESOURCE_IDS:
            assigned = [
                activity
                for activity in SAMPLE_ACTIVITIES
                if resource_id in activity.resources
            ]
            self.assertGreater(len(assigned), 1, resource_id)

    def test_both_schedules_are_feasible(self) -> None:
        for result in (
            self.comparison.baseline,
            self.comparison.experimental,
        ):
            with self.subTest(method=result.method):
                self.assertEqual((), feasibility_errors(SAMPLE_ACTIVITIES, result))

    def test_cp_sat_finds_the_shorter_38_hour_schedule(self) -> None:
        self.assertEqual(48, self.comparison.baseline.makespan)
        self.assertEqual(38, self.comparison.experimental.makespan)
        self.assertEqual("OPTIMAL", self.comparison.experimental.solver_status)

    def test_output_exposes_comparison_resources_and_waiting(self) -> None:
        output = render_comparison(self.comparison)
        self.assertIn("Baseline makespan: 48 hours", output)
        self.assertIn("Experimental makespan: 38 hours", output)
        self.assertIn("Improvement: 10 hours", output)
        self.assertIn("resource wait", output)
        self.assertIn("A11", output)
        self.assertIn("MECH,CRANE", output)


if __name__ == "__main__":
    unittest.main()
