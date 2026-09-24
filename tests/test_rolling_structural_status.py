"""Tests for structural recovery handover and repeated rolling status."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from ortools.sat.python import cp_model

from deterministic_scheduling_core.accepted_work_method_time_experiment import (
    build_problem,
    build_status_workspace,
)
from deterministic_scheduling_core.project.planning_workspace import (
    current_status_records,
    state_hash,
)
from deterministic_scheduling_core.project.rolling_structural_status import (
    load as load_cycle,
    save as save_cycle,
    to_document as cycle_to_document,
)
from deterministic_scheduling_core.rolling_structural_status_experiment import (
    _t2_assertions,
    run_experiment,
)
from deterministic_scheduling_core.scheduling.accepted_work_method_time import (
    schedule_accepted_work_method_time,
)
from deterministic_scheduling_core.scheduling.rolling_structural_status import (
    advance_structural_status_cycle,
    promote_structural_recovery_to_status_cycle,
    validate_cycle,
)
from deterministic_scheduling_core.scheduling.work_method_time import (
    schedule_work_method_time,
)


class RollingStructuralStatusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = run_experiment()

    def test_t1_promotion_replaces_only_unexecuted_structure(self):
        t1 = self.evidence["t1"]
        self.assertEqual(t1["selected_methods"]["REMOVE"], "LIFT")
        self.assertEqual(t1["selected_methods"]["RESTORE"], "MANUAL")
        self.assertNotIn("REST_CRANE", t1["activity_ids"])
        self.assertIn("REST_MAN1", t1["activity_ids"])
        self.assertIn("REST_MAN2", t1["activity_ids"])
        self.assertEqual(t1["states"]["PREP"]["state"], "COMPLETED")
        self.assertEqual(t1["states"]["PREP"]["actual_periods"], [[0, 2]])
        self.assertEqual(t1["states"]["LIFT"]["state"], "IN_PROGRESS")
        self.assertEqual(t1["states"]["LIFT"]["actual_periods"], [[2, 4]])
        self.assertEqual(t1["states"]["REST_MAN1"]["state"], "NOT_STARTED")
        self.assertEqual(t1["states"]["REST_MAN2"]["state"], "NOT_STARTED")
        self.assertEqual(len(t1["lineage"]), 1)

    def test_promotion_preserves_accepted_executed_records_byte_for_byte(self):
        problem = build_problem()
        reference = schedule_work_method_time(problem).plan
        status = build_status_workspace(problem, reference)
        recovery = schedule_accepted_work_method_time(
            problem, problem, reference, status
        ).plan

        before = deepcopy(status)
        executed = {"PREP", "LIFT"}
        expected_updates = [
            deepcopy(update)
            for update in status["execution"]["updates"]
            if update["status"] == "ACCEPTED" and update["activity_id"] in executed
        ]

        with patch.object(
            cp_model.CpSolver,
            "solve",
            side_effect=AssertionError("promotion must not schedule"),
        ):
            cycle = promote_structural_recovery_to_status_cycle(
                problem,
                problem,
                reference,
                status,
                recovery,
                asserted_by="planner",
                accepted_by="acceptor",
            )

        retained = [
            update
            for update in cycle.status_workspace["execution"]["updates"]
            if update["activity_id"] in executed
        ]
        self.assertEqual(retained, expected_updates)
        self.assertEqual(status, before)
        self.assertEqual(state_hash(status), state_hash(before))

    def test_newly_selected_activities_get_explicit_boundary_status(self):
        problem = build_problem()
        reference = schedule_work_method_time(problem).plan
        status = build_status_workspace(problem, reference)
        recovery = schedule_accepted_work_method_time(
            problem, problem, reference, status
        ).plan
        cycle = promote_structural_recovery_to_status_cycle(
            problem,
            problem,
            reference,
            status,
            recovery,
            asserted_by="planner",
            accepted_by="acceptor",
        )
        states = current_status_records(cycle.status_workspace, require_complete=True)

        self.assertNotIn("REST_CRANE", states)
        for activity_id in ("REST_MAN1", "REST_MAN2"):
            self.assertEqual(states[activity_id]["execution_state"], "NOT_STARTED")
            self.assertEqual(
                states[activity_id]["occurred_at"],
                cycle.status_workspace["execution"]["status_point"],
            )
            self.assertIn(recovery["plan_hash"], states[activity_id]["reason"])

    def test_t2_started_new_method_becomes_hard_even_when_switching_is_shorter(self):
        t2 = self.evidence["t2"]
        self.assertEqual(t2["fixed_methods"]["REMOVE"], "LIFT")
        self.assertEqual(t2["fixed_methods"]["RESTORE"], "MANUAL")
        self.assertEqual(t2["selected_methods"]["RESTORE"], "MANUAL")
        self.assertEqual(t2["illegal_selected_methods"]["RESTORE"], "CRANE")
        self.assertLess(t2["illegal_finish"], t2["finish"])
        self.assertEqual(t2["states"]["REST_MAN1"]["state"], "IN_PROGRESS")
        self.assertEqual(t2["states"]["REST_MAN1"]["actual_periods"], [[4, 6]])
        self.assertEqual(t2["states"]["LIFT"]["remaining"], 2)
        self.assertTrue(t2["repeat"])

    def test_t3_completed_method_remains_hard(self):
        t3 = self.evidence["t3"]
        self.assertEqual(t3["fixed_methods"]["REMOVE"], "LIFT")
        self.assertEqual(t3["fixed_methods"]["RESTORE"], "MANUAL")
        self.assertEqual(t3["selected_methods"]["RESTORE"], "MANUAL")
        self.assertEqual(t3["illegal_selected_methods"]["RESTORE"], "CRANE")
        self.assertLess(t3["illegal_finish"], t3["finish"])
        self.assertEqual(t3["states"]["LIFT"]["state"], "COMPLETED")
        self.assertEqual(t3["states"]["REST_MAN1"]["state"], "COMPLETED")
        self.assertEqual(t3["states"]["LIFT"]["actual_periods"], [[2, 4], [4, 6], [6, 8]])
        self.assertEqual(t3["states"]["REST_MAN1"]["actual_periods"], [[4, 6], [6, 8]])
        self.assertEqual(len(t3["lineage"]), 2)
        self.assertTrue(t3["repeat"])

    def test_advance_returns_new_cycle_without_mutating_promoted_cycle(self):
        problem = build_problem()
        reference = schedule_work_method_time(problem).plan
        status = build_status_workspace(problem, reference)
        recovery = schedule_accepted_work_method_time(
            problem, problem, reference, status
        ).plan
        cycle = promote_structural_recovery_to_status_cycle(
            problem,
            problem,
            reference,
            status,
            recovery,
            asserted_by="planner",
            accepted_by="acceptor",
        )
        before = cycle_to_document(cycle)

        advanced = advance_structural_status_cycle(
            cycle,
            6,
            _t2_assertions(),
            asserted_by="t2-planner",
            accepted_by="t2-acceptor",
        )

        self.assertEqual(cycle_to_document(cycle), before)
        self.assertEqual(cycle.status_workspace["execution"]["status_point"], 4)
        self.assertEqual(advanced.status_workspace["execution"]["status_point"], 6)
        self.assertEqual(advanced.lineage, cycle.lineage)

    def test_final_cycle_round_trips_and_validates_without_recalculation(self):
        document = self.evidence["cycle_document"]

        with TemporaryDirectory() as directory:
            path = Path(directory) / "rolling-structural-status.json"
            # Reconstruct through the public document functions before saving.
            from deterministic_scheduling_core.project.rolling_structural_status import from_document
            cycle = from_document(deepcopy(document))
            save_cycle(cycle, path)

            with patch.object(
                cp_model.CpSolver,
                "solve",
                side_effect=AssertionError("cycle reopen/validation must not schedule"),
            ):
                reopened = load_cycle(path)
                validate_cycle(reopened)

        self.assertEqual(cycle_to_document(reopened), document)

    def test_experiment_preserves_source_and_prior_t1_status(self):
        self.assertTrue(self.evidence["evidence_valid"])
        self.assertTrue(self.evidence["source_unchanged"])
        self.assertTrue(self.evidence["prior_t1_status_unchanged"])


if __name__ == "__main__":
    unittest.main()
