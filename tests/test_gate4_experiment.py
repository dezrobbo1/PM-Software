from __future__ import annotations

import unittest

from deterministic_scheduling_core.gate3_experiment import (
    capacity_feasibility_errors,
    operational_constraint_errors,
)
from deterministic_scheduling_core.gate4_experiment import (
    CRANE_OUTAGE,
    STATUS_HOUR,
    _equipment_outage_errors,
    render_comparison,
    run_gate4_experiment,
)


class Gate4ExperimentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.comparison = run_gate4_experiment()

    def test_crane_outage_moves_direct_activity_and_project_finish_one_hour(self) -> None:
        comparison = self.comparison
        self.assertEqual(17, comparison.approved.makespan)
        self.assertEqual(18, comparison.revised.makespan)
        self.assertEqual((5, 8), (
            comparison.approved.by_id["O03"].start,
            comparison.approved.by_id["O03"].finish,
        ))
        self.assertEqual((6, 9), (
            comparison.revised.by_id["O03"].start,
            comparison.revised.by_id["O03"].finish,
        ))

    def test_started_work_is_frozen_at_status_point(self) -> None:
        comparison = self.comparison
        for activity_id, approved in comparison.approved.by_id.items():
            if approved.start < STATUS_HOUR:
                revised = comparison.revised.by_id[activity_id]
                with self.subTest(activity_id=activity_id):
                    self.assertEqual(
                        (approved.start, approved.finish),
                        (revised.start, revised.finish),
                    )

    def test_revised_plan_respects_resources_operational_constraints_and_outage(self) -> None:
        revised = self.comparison.revised
        self.assertEqual((), capacity_feasibility_errors(revised))
        self.assertEqual((), operational_constraint_errors(revised))
        self.assertEqual((), _equipment_outage_errors(revised, CRANE_OUTAGE))

    def test_stability_objective_preserves_unaffected_future_work(self) -> None:
        comparison = self.comparison
        self.assertEqual(
            ("O03", "O04", "O08", "O09", "O10"),
            comparison.moved_activity_ids,
        )
        self.assertEqual(("O05",), comparison.preserved_future_activity_ids)
        self.assertEqual(5, comparison.total_start_movement)
        self.assertEqual(
            (5, 8),
            (
                comparison.revised.by_id["O05"].start,
                comparison.revised.by_id["O05"].finish,
            ),
        )

    def test_output_explains_root_cause_propagation_and_preservation(self) -> None:
        output = render_comparison(self.comparison)
        self.assertIn("CRANE-C04 unavailable H05-H06", output)
        self.assertIn("Direct cause: O03", output)
        self.assertIn("O04, O08, O09 and O10 each move one hour", output)
        self.assertIn("O05 remains at H05-H08", output)
        self.assertIn("Approved finish: H17", output)
        self.assertIn("Revised finish: H18", output)
        self.assertIn("Total future start movement: 5 hour(s)", output)


if __name__ == "__main__":
    unittest.main()
