import unittest

from deterministic_scheduling_core.gate5_experiment import (
    HANDOFF_ID,
    RESOURCE_CAPACITY,
    feasibility_errors,
    render_comparison,
    run_gate5_experiment,
)


class Gate5ExperimentTests(unittest.TestCase):
    def test_source_contains_real_declared_capacity_overload(self) -> None:
        comparison = run_gate5_experiment()
        self.assertTrue(comparison.source_violations)
        self.assertTrue(
            any(
                item.resource_id == "RES-B"
                and item.demand == 3
                and item.capacity == RESOURCE_CAPACITY["RES-B"] == 2
                for item in comparison.source_violations
            )
        )

    def test_revised_plan_is_capacity_and_precedence_feasible(self) -> None:
        comparison = run_gate5_experiment()
        self.assertEqual(feasibility_errors(comparison.revised), ())

    def test_revised_plan_preserves_real_handoff(self) -> None:
        comparison = run_gate5_experiment()
        self.assertEqual(comparison.source.handoff_finish, 600)
        self.assertEqual(comparison.revised.handoff_finish, 600)
        self.assertEqual(comparison.revised.by_id[HANDOFF_ID].finish, 600)

    def test_repair_is_bounded_and_stable(self) -> None:
        comparison = run_gate5_experiment()
        moved = {
            source.activity.id: revised.start - source.start
            for source, revised in zip(comparison.source.entries, comparison.revised.entries)
            if source.start != revised.start
        }
        self.assertEqual(moved, {"R11": 60, "R12": 180})

    def test_output_requires_practitioner_judgement(self) -> None:
        output = render_comparison(run_gate5_experiment())
        self.assertIn("REAL-WORLD PROOF", output)
        self.assertIn("raw source data is not committed", output)
        self.assertIn("practitioner judgement", output)
        self.assertIn("R11: M480 -> M540 (+60m)", output)
        self.assertIn("R12: M240 -> M420 (+180m)", output)


if __name__ == "__main__":
    unittest.main()
