from __future__ import annotations

import unittest

from deterministic_scheduling_core.trusted_state_experiment import (
    build_approved_project,
    build_field_events,
    project_trusted_state,
    run_experiment,
    run_trusted_pipeline,
)


class TrustedStateExperimentTests(unittest.TestCase):
    def test_reference_case_has_twenty_activities(self) -> None:
        project, schedule = build_approved_project()

        self.assertEqual(len(project.activities), 20)
        self.assertEqual(project.objective_activity_id, "A20")
        self.assertEqual(schedule.by_id["A07"].mode_id, "NO-WORK")
        self.assertGreater(schedule.objective_finish, 0)

    def test_unvalidated_reports_do_not_replace_authoritative_state(self) -> None:
        project, schedule = build_approved_project()
        events = build_field_events(project, schedule)

        reported_only = run_trusted_pipeline(project, schedule, (events[0], events[2], events[4], events[6]))

        self.assertEqual(reported_only.path.records, ())
        self.assertEqual(reported_only.trusted_state.accepted_event_ids, ())
        self.assertEqual(len(reported_only.provisional_records), 4)
        self.assertTrue(any(record.protective_gate for record in reported_only.provisional_records))
        self.assertEqual(
            reported_only.path.final_schedule.objective_finish,
            schedule.objective_finish,
        )

    def test_actual_history_uses_validated_correction(self) -> None:
        result = run_experiment()

        expected = result.approved_schedule.by_id["A05"].start + 2
        actuals = dict(result.candidate.trusted_state.actual_starts)

        self.assertEqual(actuals["A05"], expected)
        self.assertTrue(result.final_actual_start_is_correct)
        self.assertGreater(result.direct.corrected_authoritative_replans, 0)
        self.assertGreater(result.direct.corrected_report_start_movement, 0)
        self.assertEqual(result.candidate.path.untrusted_authoritative_replans, 0)

    def test_remaining_duration_stays_forecast_assumption(self) -> None:
        result = run_experiment()

        remaining = dict(result.candidate.trusted_state.remaining_durations)
        actuals = dict(result.candidate.trusted_state.actual_starts)

        self.assertIn("A08", remaining)
        self.assertNotIn("A08", actuals)
        self.assertTrue(result.forecast_duration_is_not_history)

    def test_emergent_scope_waits_for_approval(self) -> None:
        project, schedule = build_approved_project()
        events = build_field_events(project, schedule)

        before = run_trusted_pipeline(project, schedule, events[:-1])
        after = run_trusted_pipeline(project, schedule, events)

        self.assertEqual(before.path.final_schedule.by_id["A07"].mode_id, "NO-WORK")
        self.assertEqual(after.path.final_schedule.by_id["A07"].mode_id, "REPAIR")
        self.assertTrue(run_experiment().emergent_work_waited_for_approval)

    def test_final_trusted_state_is_independent_of_delivery_order(self) -> None:
        project, schedule = build_approved_project()
        events = build_field_events(project, schedule)
        reordered = tuple(reversed(events))

        normal_state = project_trusted_state(events)
        reversed_state = project_trusted_state(reordered)

        self.assertEqual(normal_state, reversed_state)
        self.assertTrue(run_experiment().replay_matches)

    def test_candidate_reaches_same_final_plan_without_untrusted_authoritative_replans(self) -> None:
        result = run_experiment()

        self.assertTrue(result.final_plans_match)
        self.assertEqual(result.candidate.path.untrusted_authoritative_replans, 0)
        self.assertGreater(result.direct.untrusted_authoritative_replans, 0)
        self.assertFalse(result.falsified)


if __name__ == "__main__":
    unittest.main()
