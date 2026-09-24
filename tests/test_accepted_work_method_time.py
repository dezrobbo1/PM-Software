"""Tests for the bounded accepted-history + Work-Method composition experiment."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from unittest.mock import patch

from ortools.sat.python import cp_model

from deterministic_scheduling_core.accepted_work_method_time_experiment import (
    build_problem,
    build_status_workspace,
    run_experiment,
    solve_allowed_controls,
)
from deterministic_scheduling_core.project.planning_workspace import (
    accept_report,
    accept_status_update,
    current_status_records,
    load as load_workspace,
    report_status_update,
    report_unavailable,
    save as save_workspace,
    state_hash,
)
from deterministic_scheduling_core.project.work_method_time import (
    WorkMethodTimeProject,
    input_hash,
    load as load_problem,
    save as save_problem,
)
from deterministic_scheduling_core.scheduling.accepted_work_method_time import (
    schedule_accepted_work_method_time,
    validate_input,
    validate_plan,
)
from deterministic_scheduling_core.scheduling.work_method_time import schedule_work_method_time


def productive_ticks(periods):
    return sum(finish - start for start, finish in periods)


class AcceptedWorkMethodTimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = run_experiment()

    def test_reference_then_history_constrained_recovery_changes_only_untouched_structure(self):
        observation = self.evidence["observations"]
        self.assertEqual(observation["reference_finish"], 8)
        self.assertEqual(observation["reference_remove_method"], "LIFT")
        self.assertEqual(observation["reference_restore_method"], "CRANE")

        self.assertEqual(observation["recovery_finish"], 12)
        self.assertEqual(observation["recovery_remove_method"], "LIFT")
        self.assertEqual(observation["recovery_restore_method"], "MANUAL")
        self.assertEqual(
            self.evidence["candidate"]["plan"]["fixed_methods"]["REMOVE"],
            "LIFT",
        )

    def test_accepted_actual_and_remaining_forecast_are_separate(self):
        plan = self.evidence["candidate"]["plan"]
        by_id = {entry["activity_id"]: entry for entry in plan["entries"]}

        lift = by_id["LIFT"]
        self.assertEqual(lift["execution_state"], "IN_PROGRESS")
        self.assertEqual(lift["actual_periods"], [[2, 4]])
        self.assertEqual(productive_ticks(lift["actual_periods"]), 2)
        self.assertEqual(lift["remaining_processing_ticks"], 8)
        self.assertEqual(productive_ticks(lift["forecast_periods"]), 8)
        self.assertEqual(lift["forecast_periods"], [[4, 12]])
        self.assertEqual(dict(lift["actual_assignments"]), {"MECH": "M1", "CRANE": "C04"})
        self.assertEqual(dict(lift["assignments"]), {"MECH": "M1", "CRANE": "C04"})

        prep = by_id["PREP"]
        self.assertEqual(prep["execution_state"], "COMPLETED")
        self.assertEqual(prep["actual_periods"], [[0, 2]])
        self.assertIsNone(prep["forecast_start"])
        self.assertEqual(prep["forecast_periods"], [])
        self.assertEqual(prep["remaining_processing_ticks"], 0)

    def test_newly_selected_alternative_needs_no_fabricated_historical_status(self):
        problem = build_problem()
        reference = schedule_work_method_time(problem).plan
        status = build_status_workspace(problem, reference)
        states = current_status_records(status, require_complete=True)
        self.assertNotIn("REST_MAN1", states)
        self.assertNotIn("REST_MAN2", states)

        plan = schedule_accepted_work_method_time(problem, problem, reference, status).plan
        selected_ids = {entry["activity_id"] for entry in plan["entries"]}
        self.assertIn("REST_MAN1", selected_ids)
        self.assertIn("REST_MAN2", selected_ids)
        self.assertNotIn("REST_CRANE", selected_ids)
        by_id = {entry["activity_id"]: entry for entry in plan["entries"]}
        self.assertIsNone(by_id["REST_MAN1"]["status_update_id"])
        self.assertEqual(by_id["REST_MAN1"]["execution_state"], "NOT_STARTED")

    def test_completed_work_in_an_alternative_package_also_locks_its_method(self):
        problem = build_problem()
        reference = schedule_work_method_time(problem).plan
        status = build_status_workspace(problem, reference)
        prior = current_status_records(status, require_complete=True)["LIFT"]

        update_id = report_status_update(
            status,
            "LIFT",
            "COMPLETED",
            "field-planner",
            "explicit completion of the already begun lift method",
            actual_start=2,
            actual_finish=4,
            actual_periods=[[2, 4]],
            mode_id="FIXED",
            named_assignments=[["MECH", "M1"], ["CRANE", "C04"]],
            remaining_processing_ticks=0,
            supersedes_update_id=prior["id"],
        )
        accept_status_update(status, update_id, "schedule-acceptor")

        plan = schedule_accepted_work_method_time(problem, problem, reference, status).plan
        self.assertEqual(plan["fixed_methods"]["REMOVE"], "LIFT")
        self.assertEqual(plan["selected_methods"]["REMOVE"], "LIFT")
        lift = next(entry for entry in plan["entries"] if entry["activity_id"] == "LIFT")
        self.assertEqual(lift["execution_state"], "COMPLETED")
        self.assertEqual(lift["actual_periods"], [[2, 4]])
        self.assertEqual(lift["forecast_periods"], [])
        self.assertEqual(lift["remaining_processing_ticks"], 0)

    def test_candidate_matches_enumerated_history_permitted_structural_control(self):
        problem = build_problem()
        reference = schedule_work_method_time(problem).plan
        status = build_status_workspace(problem, reference)
        candidate = schedule_accepted_work_method_time(problem, problem, reference, status).plan
        control = solve_allowed_controls(problem, problem, reference, status)

        self.assertEqual(len(control["branches"]), 2)
        self.assertEqual(control["best"]["methods"], candidate["selected_methods"])
        self.assertEqual(control["best"]["project_finish"], candidate["objective"][0])
        self.assertEqual(control["best"]["methods"]["RESTORE"], "MANUAL")

    def test_illegal_unconstrained_counterfactual_is_better_only_by_erasing_begun_method(self):
        counterfactual = self.evidence["illegal_unconstrained_counterfactual"]
        candidate = self.evidence["candidate"]["plan"]

        self.assertEqual(counterfactual["selected_methods"]["REMOVE"], "SEGMENTED")
        self.assertEqual(counterfactual["selected_methods"]["RESTORE"], "CRANE")
        self.assertEqual(counterfactual["objective"][0], 11)
        self.assertEqual(candidate["selected_methods"]["REMOVE"], "LIFT")
        self.assertEqual(candidate["objective"][0], 12)
        self.assertLess(counterfactual["objective"][0], candidate["objective"][0])

    def test_inputs_are_immutable_and_complete_plan_repeats(self):
        self.assertTrue(self.evidence["evidence_valid"])
        self.assertTrue(self.evidence["source_unchanged"])
        self.assertTrue(self.evidence["history_unchanged"])
        self.assertTrue(self.evidence["repeat_plan_matches"])

    def test_status_workspace_must_be_reference_selected_structure_not_union(self):
        problem = build_problem()
        reference = schedule_work_method_time(problem).plan
        status = build_status_workspace(problem, reference)
        status["project"]["name"] = "Same valid selected network, altered source identity"
        with self.assertRaisesRegex(ValueError, "current projection of the reference selected structure"):
            validate_input(problem, problem, reference, status)

    def test_reported_and_accepted_current_outage_do_not_require_rebasing_reference_plan(self):
        reference_problem = build_problem()
        reference = schedule_work_method_time(reference_problem).plan
        status = build_status_workspace(reference_problem, reference)
        original_state_hash = state_hash(status)

        report_id = report_unavailable(
            status,
            "C04",
            6,
            8,
            "operations",
            "new crane outage reported after the reference plan",
        )
        self.assertEqual(state_hash(status), original_state_hash)
        current_problem = WorkMethodTimeProject(
            deepcopy(reference_problem.project),
            reference_problem.work_packages,
            tuple(deepcopy(status["reports"])),
        )
        self.assertNotEqual(input_hash(current_problem), input_hash(reference_problem))

        reported_plan = schedule_accepted_work_method_time(
            current_problem,
            reference_problem,
            reference,
            status,
        ).plan
        self.assertEqual(reported_plan["selected_methods"]["REMOVE"], "LIFT")
        self.assertEqual(reported_plan["selected_methods"]["RESTORE"], "MANUAL")
        self.assertEqual(reported_plan["objective"][0], 12)

        accept_report(status, report_id, "planner")
        current_problem = WorkMethodTimeProject(
            deepcopy(reference_problem.project),
            reference_problem.work_packages,
            tuple(deepcopy(status["reports"])),
        )
        accepted_plan = schedule_accepted_work_method_time(
            current_problem,
            reference_problem,
            reference,
            status,
        ).plan
        lift = next(entry for entry in accepted_plan["entries"] if entry["activity_id"] == "LIFT")
        self.assertEqual(accepted_plan["selected_methods"]["REMOVE"], "LIFT")
        self.assertEqual(accepted_plan["selected_methods"]["RESTORE"], "MANUAL")
        self.assertEqual(accepted_plan["objective"][0], 14)
        self.assertEqual(lift["forecast_periods"], [[4, 6], [8, 14]])
        self.assertEqual(reference["input_hash"], input_hash(reference_problem))

    def test_v0_reference_projection_survives_status_v2_normalisation(self):
        problem = build_problem()
        problem.project.pop("resource_groups")
        for activity in problem.project["activities"]:
            for mode in activity["modes"]:
                mode.pop("group_requirements", None)

        reference = schedule_work_method_time(problem).plan
        status = build_status_workspace(problem, reference)
        self.assertEqual(status["project"]["resource_groups"], [])
        self.assertTrue(
            all(
                "group_requirements" in mode
                for activity in status["project"]["activities"]
                for mode in activity["modes"]
            )
        )

        plan = schedule_accepted_work_method_time(
            problem,
            problem,
            reference,
            status,
        ).plan
        self.assertEqual(plan["selected_methods"]["REMOVE"], "LIFT")
        self.assertEqual(plan["selected_methods"]["RESTORE"], "MANUAL")
        self.assertEqual(plan["objective"][0], 12)

    def test_continuous_in_progress_is_explicitly_outside_first_slice(self):
        problem = build_problem()
        next(a for a in problem.project["activities"] if a["id"] == "LIFT")["modes"][0][
            "continuity"
        ] = "CONTINUOUS"
        reference = schedule_work_method_time(problem).plan
        status = build_status_workspace(problem, reference)
        with self.assertRaisesRegex(ValueError, "continuous in-progress"):
            validate_input(problem, problem, reference, status)

    def test_in_progress_anonymous_group_continuation_is_explicitly_outside_first_slice(self):
        problem = build_problem()
        problem.project["resource_groups"] = [{
            "id": "RIG",
            "name": "Interchangeable rigging",
            "capacity": 1,
            "calendar_id": "ALWAYS",
            "disjoint": True,
            "interchangeable": True,
        }]
        lift = next(a for a in problem.project["activities"] if a["id"] == "LIFT")
        lift["modes"][0]["group_requirements"] = [{"group_id": "RIG", "demand": 1}]
        reference = schedule_work_method_time(problem).plan
        status = build_status_workspace(problem, reference)
        with self.assertRaisesRegex(ValueError, "anonymous group continuation"):
            validate_input(problem, problem, reference, status)

    def test_save_reopen_and_plan_validation_do_not_recalculate(self):
        problem = build_problem()
        reference = schedule_work_method_time(problem).plan
        status = build_status_workspace(problem, reference)
        result = schedule_accepted_work_method_time(problem, problem, reference, status)
        source_hash = input_hash(problem)
        accepted_hash = state_hash(status)

        with TemporaryDirectory() as directory:
            directory = Path(directory)
            problem_path = directory / "problem.json"
            status_path = directory / "status.json"
            reference_path = directory / "reference.json"
            plan_path = directory / "plan.json"
            save_problem(problem, problem_path)
            save_workspace(status, status_path)
            reference_path.write_text(json.dumps(reference), encoding="utf-8")
            plan_path.write_text(json.dumps(result.plan), encoding="utf-8")

            with patch.object(
                cp_model.CpSolver,
                "solve",
                side_effect=AssertionError("reopen/validation must not schedule"),
            ):
                reopened_problem = load_problem(problem_path)
                reopened_status = load_workspace(status_path)
                reopened_reference = json.loads(reference_path.read_text(encoding="utf-8"))
                reopened_plan = json.loads(plan_path.read_text(encoding="utf-8"))
                self.assertEqual(
                    validate_plan(
                        reopened_problem,
                        reopened_problem,
                        reopened_reference,
                        reopened_status,
                        reopened_plan,
                    ),
                    "PROVEN_FEASIBLE",
                )

        self.assertEqual(input_hash(reopened_problem), source_hash)
        self.assertEqual(state_hash(reopened_status), accepted_hash)
        self.assertEqual(reopened_plan, result.plan)


if __name__ == "__main__":
    unittest.main()
