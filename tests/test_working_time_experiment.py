from dataclasses import replace
import unittest

from deterministic_scheduling_core.working_time_experiment import (
    TICKS_PER_DAY,
    Scenario,
    build_case,
    build_remaining_work_result,
    joint_calendar_slots,
    render,
    run_experiment,
    validate_physical_plan,
    validate_remaining_work,
)


class WorkingTimeExperimentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = run_experiment()
        cls.plans = cls.result.by_interpretation

    def test_fixture_has_bounded_research_shape(self) -> None:
        case = build_case()

        self.assertEqual(len(case.activities), 18)
        self.assertEqual(
            {resource.id for resource in case.resources},
            {"MECH_DAY", "NIGHT_MECH", "C04", "INSPECT"},
        )
        self.assertEqual(
            {mode.id for mode in case.activity_by_id["A15"].modes},
            {"CRANE", "SEGMENTED"},
        )

    def test_a_b_c_joint_activity_finishes_match_sentinel(self) -> None:
        self.assertEqual(self.plans["A"].by_id["A04"].start, 14)
        self.assertEqual(self.plans["B"].by_id["A04"].start, 14)
        self.assertEqual(self.plans["C"].by_id["A04"].start, 14)
        self.assertEqual(
            tuple(self.plans[item].by_id["A04"].finish for item in ("A", "B", "C")),
            (34, 35, 63),
        )

    def test_joint_calendar_intersection_has_only_nineteen_day_one_slots(self) -> None:
        case = build_case()
        mode = case.activity_by_id["A04"].modes[0]
        slots = joint_calendar_slots(case, mode)

        self.assertEqual(len([slot for slot in slots if slot < TICKS_PER_DAY]), 19)
        self.assertNotIn(24, slots)
        self.assertNotIn(34, slots)

    def test_suspendable_work_spans_only_explicit_calendar_gaps(self) -> None:
        periods = self.plans["C"].by_id["A04"].periods

        self.assertEqual(periods, ((14, 24), (25, 34), (62, 63)))

    def test_suspendable_activity_does_not_reserve_resources_in_gaps(self) -> None:
        occupied = {
            slot
            for start, finish in self.plans["C"].by_id["A04"].periods
            for slot in range(start, finish)
        }

        self.assertNotIn(24, occupied)
        self.assertNotIn(40, occupied)
        self.assertEqual(len(occupied), 20)

    def test_continuous_activity_waits_for_complete_joint_window(self) -> None:
        entry = self.plans["C"].by_id["A05"]

        self.assertEqual(len(entry.periods), 1)
        self.assertGreaterEqual(entry.start, 2 * TICKS_PER_DAY + 14)
        self.assertEqual(entry.finish - entry.start, 10)

    def test_outage_preserves_history_and_removes_availability_not_work(self) -> None:
        no_restart = self.result.outage_no_restart

        self.assertEqual(no_restart.actual_start, 14)
        self.assertEqual(no_restart.actual_periods, ((14, 20),))
        self.assertEqual(no_restart.actual_productive_ticks, 6)
        self.assertEqual(no_restart.remaining_productive_ticks, 14)
        self.assertEqual(no_restart.future_periods, ((28, 34), (62, 70)))
        self.assertEqual(no_restart.forecast_finish, 70)

    def test_explicit_restart_work_alone_increases_remaining_processing(self) -> None:
        no_restart = build_remaining_work_result(build_case())
        with_restart = build_remaining_work_result(build_case(), restart_hours=1)

        self.assertEqual(
            with_restart.actual_productive_ticks,
            no_restart.actual_productive_ticks,
        )
        self.assertEqual(
            with_restart.remaining_productive_ticks,
            no_restart.remaining_productive_ticks + 2,
        )
        self.assertEqual(with_restart.forecast_finish, 72)

    def test_independent_accounting_validator_catches_wrong_remaining_work(self) -> None:
        case = build_case()
        valid = build_remaining_work_result(case)
        invalid = replace(valid, remaining_productive_ticks=valid.remaining_productive_ticks + 2)

        self.assertTrue(validate_remaining_work(case, valid))
        self.assertFalse(validate_remaining_work(case, invalid))

    def test_authorised_mode_choice_responds_to_calendar_outage(self) -> None:
        self.assertEqual(self.result.normal_mode, "CRANE")
        self.assertEqual(self.result.outage_mode, "SEGMENTED")
        self.assertTrue(self.result.changed_state_plan.validation.valid)
        self.assertIn(
            self.result.changed_state_plan.by_id["A15"].mode_id,
            {mode.id for mode in self.result.case.activity_by_id["A15"].modes},
        )

    def test_independent_validator_exposes_a_and_b_controls(self) -> None:
        a = self.plans["A"].validation
        b = self.plans["B"].validation

        self.assertFalse(a.valid)
        self.assertGreater(a.non_working_slots, 0)
        self.assertFalse(b.valid)
        self.assertEqual(b.non_working_slots, 0)
        self.assertGreater(b.resource_calendar_violations, 0)

    def test_joint_interpretation_is_physically_executable(self) -> None:
        validation = self.plans["C"].validation

        self.assertTrue(validation.valid)
        self.assertEqual(validation.precedence_violations, 0)
        self.assertEqual(validation.capacity_violations, 0)
        self.assertEqual(validation.processing_total_violations, 0)
        self.assertEqual(validation.continuous_activity_violations, 0)

    def test_independent_validator_detects_forbidden_continuous_split(self) -> None:
        plan = self.plans["C"]
        entries = tuple(
            replace(
                entry,
                periods=(
                    (entry.start, entry.start + 8),
                    (entry.start + 9, entry.finish + 1),
                ),
            )
            if entry.activity_id == "A05"
            else entry
            for entry in plan.entries
        )

        validation = validate_physical_plan(
            self.result.case,
            "C",
            Scenario(plan.scenario_id),
            entries,
        )

        self.assertIn("A05", validation.invalid_activity_ids)
        self.assertEqual(validation.continuous_activity_violations, 1)

    def test_c_repeated_solve_is_canonical(self) -> None:
        self.assertTrue(self.result.repeat_canonical)
        self.assertEqual(self.plans["C"].signature, self.result.repeated_c_signature)

    def test_model_complexity_is_measured_from_generated_models(self) -> None:
        for plan in self.result.plans:
            with self.subTest(interpretation=plan.interpretation):
                self.assertGreater(plan.complexity.boolean_variables, 0)
                self.assertGreater(plan.complexity.optional_intervals, 0)
                self.assertGreater(plan.complexity.execution_segments, 0)
                self.assertGreater(plan.complexity.constraints, 0)
                self.assertEqual(plan.complexity.solver_calls, 1)
                self.assertGreater(plan.complexity.solve_ms, 0)

    def test_falsification_result_is_derived_from_measured_results(self) -> None:
        self.assertFalse(self.result.falsified)
        output = render(self.result)

        self.assertIn("FALSIFICATION RESULT: NOT FALSIFIED", output)
        self.assertIn("Availability loss alone adds no processing work", output)
        self.assertIn("A15=SEGMENTED", output)


if __name__ == "__main__":
    unittest.main()
