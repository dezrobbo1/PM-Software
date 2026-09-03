from __future__ import annotations

import unittest

from deterministic_scheduling_core.gate3_experiment import (
    ACTIVITIES,
    PERMIT_WINDOWS,
    RESOURCE_IDS,
    WORKFACE_EXCLUSIONS,
    capacity_feasibility_errors,
    operational_constraint_errors,
    render_comparison,
    run_gate3_experiment,
)


class Gate3ExperimentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.comparison = run_gate3_experiment()

    def test_case_is_small_but_contains_real_operational_facts(self) -> None:
        self.assertEqual(10, len(ACTIVITIES))
        self.assertIn("CRANE-C04", RESOURCE_IDS)
        self.assertEqual(1, len(PERMIT_WINDOWS))
        self.assertEqual(1, len(WORKFACE_EXCLUSIONS))
        crane_jobs = [
            activity.id
            for activity in ACTIVITIES
            if "CRANE-C04" in activity.resources
        ]
        self.assertEqual(["O03", "O06"], crane_jobs)

    def test_capacity_only_schedule_is_resource_feasible_but_operationally_invalid(self) -> None:
        result = self.comparison.capacity_only
        self.assertEqual((), capacity_feasibility_errors(result))
        errors = operational_constraint_errors(result)
        self.assertGreaterEqual(len(errors), 1)
        self.assertEqual(errors, self.comparison.capacity_only_operational_errors)
        self.assertTrue(any("permit/access" in error for error in errors))
        self.assertTrue(any("WF-EXCHANGER" in error for error in errors))

    def test_operational_schedule_respects_window_workface_and_resources(self) -> None:
        result = self.comparison.operational
        self.assertEqual((), capacity_feasibility_errors(result))
        self.assertEqual((), operational_constraint_errors(result))
        lift = result.by_id["O03"]
        self.assertGreaterEqual(lift.start, 4)
        self.assertLessEqual(lift.finish, 9)
        scaffold = result.by_id["O02"]
        self.assertTrue(
            scaffold.finish <= lift.start or lift.finish <= scaffold.start,
            (scaffold, lift),
        )

    def test_operational_reality_changes_the_plan_by_one_hour(self) -> None:
        self.assertEqual(16, self.comparison.capacity_only.makespan)
        self.assertEqual(17, self.comparison.operational.makespan)
        self.assertEqual("OPTIMAL", self.comparison.capacity_only.solver_status)
        self.assertEqual("OPTIMAL", self.comparison.operational.solver_status)
        self.assertEqual(3, self.comparison.capacity_only.by_id["O03"].start)
        self.assertEqual(5, self.comparison.operational.by_id["O03"].start)
        self.assertEqual(1, self.comparison.operational.by_id["O06"].start)

    def test_output_explains_why_shorter_resource_schedule_is_not_executable(self) -> None:
        output = render_comparison(self.comparison)
        self.assertIn("Capacity-only makespan: 16 hours", output)
        self.assertIn("Operationally feasible makespan: 17 hours", output)
        self.assertIn("outside Exchanger heavy-lift permit/access window", output)
        self.assertIn("WF-EXCHANGER", output)
        self.assertIn("inside the H04-H09 permit/access window", output)
        self.assertIn("two explicit operational facts", output)


if __name__ == "__main__":
    unittest.main()
