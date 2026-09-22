"""Regression tests for the bounded headless rolling-status experiment."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from deterministic_scheduling_core.project.planning_workspace import (
    accept_report,
    advance_status_point,
    current_status_records,
    load,
    report_unavailable,
    save,
    state_hash,
)
from deterministic_scheduling_core.rolling_status_experiment import (
    _t1_workspace,
    run_experiment,
)
from deterministic_scheduling_core.scheduling.planning_workspace import validate_stored_plans


class RollingStatusExperimentTests(unittest.TestCase):
    def test_three_status_points_preserve_history_and_recover_from_explicit_remainder(self):
        result = run_experiment()

        self.assertEqual(result["baseline_finish"], 30)
        self.assertEqual(result["t1"]["project_finish"], 30)
        self.assertEqual(result["t1"]["a03_actual"], [[20, 22]])
        self.assertEqual(result["t1"]["a03_forecast"], [[22, 24], [25, 27]])
        self.assertEqual(result["t1"]["remaining_ticks"], 4)

        self.assertEqual(result["t2"]["project_finish"], 30)
        self.assertEqual(result["t2"]["a03_actual"], [[20, 22], [22, 23]])
        self.assertEqual(result["t2"]["a03_forecast"], [[23, 24], [25, 27]])
        self.assertEqual(result["t2"]["remaining_ticks"], 3)

        self.assertEqual(result["t3"]["project_finish"], 31)
        self.assertEqual(result["t3"]["a03_actual"], [[20, 22], [22, 23], [23, 24]])
        self.assertEqual(result["t3"]["a03_forecast"], [[25, 28]])
        self.assertEqual(result["t3"]["remaining_ticks"], 3)

        self.assertEqual(result["accepted_update_count"], 14)
        self.assertEqual(result["plan_history_count"], 3)

    def test_advance_is_atomic_when_an_open_activity_is_not_re_attested(self):
        workspace, _, _ = _t1_workspace()
        before = deepcopy(workspace)

        with self.assertRaisesRegex(ValueError, "explicit re-attestation"):
            advance_status_point(
                workspace,
                23,
                {
                    "A03": {
                        "execution_state": "IN_PROGRESS",
                        "reason": "T2 progress",
                        "actual_start": 20,
                        "actual_finish": None,
                        "actual_periods": [[20, 22], [22, 23]],
                        "mode_id": "SPECIALIST",
                        "named_assignments": [["MECH", "M1"], ["SPECIALIST", "M2"]],
                        "remaining_processing_ticks": 3,
                    },
                    "A04": {
                        "execution_state": "NOT_STARTED",
                        "reason": "T2 not started",
                    },
                },
                asserted_by="t2-planner",
                accepted_by="t2-acceptor",
            )

        self.assertEqual(workspace, before)

    def test_advance_rejects_rewriting_prior_productive_history(self):
        workspace, _, _ = _t1_workspace()
        before_hash = state_hash(workspace)

        with self.assertRaisesRegex(ValueError, "exact prefix"):
            advance_status_point(
                workspace,
                23,
                {
                    "A03": {
                        "execution_state": "IN_PROGRESS",
                        "reason": "invalid rewritten history",
                        "actual_start": 20,
                        "actual_finish": None,
                        "actual_periods": [[20, 23]],
                        "mode_id": "SPECIALIST",
                        "named_assignments": [["MECH", "M1"], ["SPECIALIST", "M2"]],
                        "remaining_processing_ticks": 3,
                    },
                    "A04": {
                        "execution_state": "NOT_STARTED",
                        "reason": "T2 not started",
                    },
                    "A08": {
                        "execution_state": "NOT_STARTED",
                        "reason": "T2 not started",
                    },
                },
                asserted_by="t2-planner",
                accepted_by="t2-acceptor",
            )

        self.assertEqual(state_hash(workspace), before_hash)
        self.assertEqual(workspace["execution"]["status_point"], 22)

    def test_advance_rejects_changed_historical_context_without_reinterpreting_history(self):
        workspace, _, _ = _t1_workspace()
        outage = report_unavailable(
            workspace,
            "M2",
            22,
            23,
            "operations",
            "newly accepted outage across the next status interval",
        )
        accept_report(workspace, outage, "planner")
        before = deepcopy(workspace)

        with self.assertRaisesRegex(ValueError, "changed historical execution context"):
            advance_status_point(
                workspace,
                23,
                {
                    "A03": {
                        "execution_state": "IN_PROGRESS",
                        "reason": "T2 preserves the pre-outage actual history",
                        "actual_start": 20,
                        "actual_finish": None,
                        "actual_periods": [[20, 22]],
                        "mode_id": "SPECIALIST",
                        "named_assignments": [["MECH", "M1"], ["SPECIALIST", "M2"]],
                        "remaining_processing_ticks": 4,
                    },
                    "A04": {
                        "execution_state": "NOT_STARTED",
                        "reason": "T2 not started",
                    },
                    "A08": {
                        "execution_state": "NOT_STARTED",
                        "reason": "T2 not started",
                    },
                },
                asserted_by="t2-planner",
                accepted_by="t2-acceptor",
            )

        self.assertEqual(workspace, before)

    def test_final_rolling_state_round_trips_without_recalculation(self):
        result = run_experiment()
        workspace = result["workspace"]
        expected_hash = state_hash(workspace)
        expected_plan_hash = workspace["approved_plan"]["plan_hash"]
        expected_a03 = deepcopy(current_status_records(workspace)["A03"])

        with TemporaryDirectory() as directory:
            path = Path(directory) / "rolling-status.json"
            save(workspace, path)
            reopened = load(path)
            validate_stored_plans(reopened)

        self.assertEqual(reopened, workspace)
        self.assertEqual(state_hash(reopened), expected_hash)
        self.assertEqual(reopened["approved_plan"]["plan_hash"], expected_plan_hash)
        self.assertEqual(current_status_records(reopened)["A03"], expected_a03)


if __name__ == "__main__":
    unittest.main()
