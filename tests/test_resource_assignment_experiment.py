from dataclasses import replace
import unittest

from deterministic_scheduling_core.resource_assignment_experiment import (
    EXACT_FEASIBLE,
    EXACT_INCONCLUSIVE,
    EXACT_INFEASIBLE,
    TICKS_PER_DAY,
    build_case,
    build_no_handover_regression,
    check_fixed_schedule,
    each_time_slice_is_assignable,
    render,
    run_experiment,
)


class ResourceAssignmentExperimentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = run_experiment()
        cls.plans = cls.result.by_approach

    def test_fixture_holds_one_physical_roster_across_approaches(self) -> None:
        case = build_case()

        self.assertEqual(len(case.activities), 14)
        self.assertEqual(
            {resource.id: resource.capabilities for resource in case.resources},
            {
                "M1": ("MECH",),
                "M2": ("MECH", "INSPECT", "SPECIALIST"),
                "N1": ("MECH",),
                "R1": ("RIGGER",),
                "R2": ("RIGGER",),
            },
        )
        self.assertTrue(all(resource.capacity == 1 for resource in case.resources))
        self.assertEqual(len(case.exceptions), 1)
        self.assertEqual(case.exceptions[0].resource_id, "M2")
        self.assertEqual(
            (case.exceptions[0].start, case.exceptions[0].finish),
            (TICKS_PER_DAY + 16, TICKS_PER_DAY + 20),
        )

    def test_requirement_meanings_remain_distinct(self) -> None:
        case = build_case()
        dual = case.activity_by_id["A09"].requirements
        two_people = case.activity_by_id["A13"].requirements
        alternative = case.activity_by_id["A08"].requirements[0]

        self.assertEqual(len(dual), 1)
        self.assertEqual(dual[0].pool_ids, ("MECH", "SPECIALIST"))
        self.assertEqual(dual[0].eligible_resource_ids, ("M2",))
        self.assertEqual(len(two_people), 2)
        self.assertEqual({item.id for item in two_people}, {"MECH", "INSPECT"})
        self.assertEqual(alternative.eligible_resource_ids, ("M1", "M2", "N1"))

    def test_independent_pools_produce_false_three_way_concurrency(self) -> None:
        plan = self.plans["A"]

        self.assertEqual(
            {plan.by_id[activity_id].start for activity_id in ("A01", "A02", "A03")},
            {14},
        )
        self.assertEqual(plan.checker.greedy_status, "FAILED")
        self.assertEqual(plan.checker.exact_status, EXACT_INFEASIBLE)
        self.assertIn("need 3 distinct resources", plan.checker.reason)
        self.assertEqual(plan.checker.capacity_violations, 1)

    def test_b_and_c_are_executable_and_policy_equivalent(self) -> None:
        b = self.plans["B"]
        c = self.plans["C"]

        self.assertEqual(b.checker.exact_status, EXACT_FEASIBLE)
        self.assertEqual(c.checker.exact_status, EXACT_FEASIBLE)
        self.assertEqual(b.objective_result, c.objective_result)
        self.assertEqual(b.project_finish, 75)
        self.assertEqual(b.identity_level_requirements, 11)
        self.assertEqual(c.identity_level_requirements, 9)
        self.assertEqual(c.deferred_requirements, 2)

    def test_scarce_specialist_has_valid_non_greedy_allocation(self) -> None:
        diagnostic = self.result.scarce_specialist_diagnostic

        self.assertEqual(diagnostic.greedy_status, "FAILED")
        self.assertEqual(diagnostic.exact_status, EXACT_FEASIBLE)
        self.assertIn(("A05", "MECH", "M1"), diagnostic.exact_allocation)
        self.assertIn(("A06", "SPECIALIST", "M2"), diagnostic.exact_allocation)

    def test_selected_resource_calendars_drive_execution_periods(self) -> None:
        c = self.plans["C"]

        self.assertEqual(dict(c.by_id["A08"].assignments)["MECH"], "N1")
        self.assertEqual(c.by_id["A08"].periods, ((36, 40),))
        self.assertEqual(dict(c.by_id["A09"].assignments)["DUAL"], "M2")
        self.assertEqual(c.by_id["A09"].periods, ((62, 64), (68, 72)))

    def test_suspension_gap_does_not_consume_m2_capacity(self) -> None:
        c = self.plans["C"]
        m2_entries = [
            entry
            for entry in c.entries
            if "M2" in dict(entry.assignments).values()
        ]
        occupied = {
            slot
            for entry in m2_entries
            for start, finish in entry.periods
            for slot in range(start, finish)
        }

        self.assertNotIn(TICKS_PER_DAY + 16, occupied)
        self.assertNotIn(TICKS_PER_DAY + 19, occupied)

    def test_interchangeable_riggers_are_named_only_in_b(self) -> None:
        b = self.plans["B"]
        c = self.plans["C"]

        self.assertEqual(
            {
                dict(b.by_id["A10"].assignments)["RIGGER"],
                dict(b.by_id["A11"].assignments)["RIGGER"],
            },
            {"R1", "R2"},
        )
        self.assertIsNone(dict(c.by_id["A10"].assignments)["RIGGER"])
        self.assertIsNone(dict(c.by_id["A11"].assignments)["RIGGER"])
        self.assertEqual(b.objective_result, c.objective_result)

    def test_checker_does_not_repair_wrong_named_assignment(self) -> None:
        plan = self.plans["B"]
        wrong_entries = tuple(
            replace(entry, assignments=(("MECH", "M1"),))
            if entry.activity_id == "A08"
            else entry
            for entry in plan.entries
        )

        check = check_fixed_schedule(self.result.case, wrong_entries)

        self.assertEqual(check.exact_status, EXACT_INFEASIBLE)
        self.assertGreater(check.calendar_violations, 0)
        self.assertFalse(check.allocation)

    def test_global_no_handover_regression_rejects_slice_feasible_plan(self) -> None:
        case, entries = build_no_handover_regression()

        self.assertTrue(each_time_slice_is_assignable(case, entries))
        check = check_fixed_schedule(case, entries)
        self.assertEqual(check.exact_status, EXACT_INFEASIBLE)
        self.assertIn("no-handover", check.reason)

    def test_search_limit_is_reported_as_inconclusive_not_infeasible(self) -> None:
        case, entries = build_no_handover_regression()

        check = check_fixed_schedule(case, entries, max_search_nodes=0)

        self.assertEqual(check.exact_status, EXACT_INCONCLUSIVE)
        self.assertIn("unproved", check.reason)

    def test_shared_capacity_diagnostic_removes_only_fixture_false_positive(self) -> None:
        diagnostic = self.result.shared_capacity_diagnostic

        self.assertEqual(diagnostic.checker.exact_status, EXACT_FEASIBLE)
        starts = {
            diagnostic.by_id[activity_id].start
            for activity_id in ("A01", "A02", "A03")
        }
        self.assertGreater(len(starts), 1)
        self.assertEqual(diagnostic.objective_result, self.plans["B"].objective_result)
        self.assertEqual(diagnostic.identity_level_requirements, 0)

    def test_c_repeats_canonical_result_in_same_environment(self) -> None:
        c = self.plans["C"]

        self.assertEqual(c.canonical_signature, self.result.repeated_c_signature)
        self.assertEqual(c.objective_result, self.result.repeated_c_objective)

    def test_model_and_planner_accounting_are_explicit(self) -> None:
        facts = dict(self.result.planner_facts)
        self.assertEqual(facts["physical resources"], 5)
        self.assertEqual(facts["resource capability memberships"], 7)
        self.assertEqual(facts["productive-work requirements"], 11)
        self.assertEqual(facts["eligible-resource memberships"], 23)

        for plan in (*self.result.plans, self.result.shared_capacity_diagnostic):
            with self.subTest(approach=plan.approach):
                self.assertEqual(plan.metrics.solver_calls, 2)
                self.assertGreater(plan.metrics.boolean_variables, 0)
                self.assertGreater(plan.metrics.constraints, 0)
                self.assertGreater(plan.metrics.model_build_ms, 0)
                self.assertGreater(plan.metrics.solve_ms, 0)
                self.assertEqual(plan.solver_status, "OPTIMAL/OPTIMAL")
                self.assertIn("proven optimal", plan.solver_proof)

    def test_render_reports_actual_conclusion_without_mandating_c(self) -> None:
        output = render(self.result)

        self.assertIn("C matches B's executable objective result", output)
        self.assertIn("does not prove that selective assignment", output)
        self.assertIn("A greedy attempt FAILED", output)
        self.assertIn("exact search PROVEN_INFEASIBLE", output)


if __name__ == "__main__":
    unittest.main()
