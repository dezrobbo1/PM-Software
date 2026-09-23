"""Regression tests for the bounded headless rolling-status experiment."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from deterministic_scheduling_core.project import planning_workspace as native
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
from deterministic_scheduling_core.scheduling.planning_workspace import approve, propose, validate_stored_plans


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


class RollingStatusReviewTests(unittest.TestCase):
    @staticmethod
    def next_assertions(workspace, **changes):
        prior = current_status_records(workspace)["A03"]
        values = {key: deepcopy(prior[key]) for key in (
            "execution_state", "actual_start", "actual_finish", "actual_periods",
            "mode_id", "named_assignments", "remaining_processing_ticks",
        )}
        values.update(reason="reviewed next status", **changes)
        return {
            "A03": values,
            "A04": {"execution_state": "NOT_STARTED", "reason": "explicitly not started"},
            "A08": {"execution_state": "NOT_STARTED", "reason": "explicitly not started"},
        }

    @staticmethod
    def legacy_t1_workspace():
        """Generate the older optional-field shape before any hashes are created."""
        build_context = native._context_for_update

        def omit_outages(*args, **kwargs):
            context = build_context(*args, **kwargs)
            del context["accepted_outages"]
            return context

        # Only fixture construction is patched; advancement and reopen use real code.
        with patch.object(native, "_context_for_update", side_effect=omit_outages):
            workspace, _, _ = _t1_workspace()
        return workspace

    def test_completion_at_or_before_prior_status_requires_correction_atomically(self):
        for old_status, actual_finish, remaining in ((22, 22, 4), (25, 24, 2), (25, 25, 0)):
            with self.subTest(old_status=old_status, actual_finish=actual_finish, remaining=remaining):
                workspace, _, _ = _t1_workspace()
                if old_status != 22:
                    advance_status_point(
                        workspace, old_status,
                        self.next_assertions(workspace, actual_periods=[[20, 22], [22, 24]],
                                             remaining_processing_ticks=remaining),
                        "planner", "acceptor",
                    )
                propose(workspace)
                before = deepcopy(workspace)
                with self.assertRaisesRegex(ValueError, "prior status point.*correction"):
                    advance_status_point(
                        workspace, old_status + 1,
                        self.next_assertions(workspace, execution_state="COMPLETED",
                                             actual_finish=actual_finish, remaining_processing_ticks=0),
                        "planner", "acceptor",
                    )
                self.assertEqual(workspace, before)
                self.assertEqual(state_hash(workspace), state_hash(before))

    def test_completion_after_prior_status_preserves_history_and_stales_approval(self):
        for new_status in (23, 24):
            with self.subTest(new_status=new_status):
                workspace, _, _ = _t1_workspace()
                propose(workspace)
                before = deepcopy(workspace)
                ids = advance_status_point(
                    workspace, new_status,
                    self.next_assertions(workspace, execution_state="COMPLETED", actual_finish=23,
                                         actual_periods=[[20, 22], [22, 23]], remaining_processing_ticks=0),
                    "planner", "acceptor",
                )
                self.assertEqual(workspace["execution"]["updates"][:len(before["execution"]["updates"])],
                                 before["execution"]["updates"])
                self.assertEqual(workspace["approved_plan"], before["approved_plan"])
                self.assertEqual(workspace["plan_history"], before["plan_history"])
                self.assertIsNone(workspace["proposal"])
                self.assertNotEqual(state_hash(workspace), before["approved_plan"]["source_state_hash"])
                current = current_status_records(workspace)["A03"]
                self.assertEqual(current["id"], ids["A03"])
                self.assertEqual(current["execution_state"], "COMPLETED")
                self.assertEqual(current["actual_finish"], 23)
                self.assertEqual(current["execution_context"], current_status_records(before)["A03"]["execution_context"])
                plan = propose(workspace)
                entry = next(item for item in plan["entries"] if item["activity_id"] == "A03")
                self.assertEqual(entry["forecast_periods"], [])
                self.assertEqual(entry["actual_periods"], [[20, 22], [22, 23]])

    def test_completion_after_new_status_is_still_rejected_atomically(self):
        workspace, _, _ = _t1_workspace()
        before = deepcopy(workspace)
        with self.assertRaisesRegex(ValueError, "actual_finish"):
            advance_status_point(
                workspace, 23,
                self.next_assertions(workspace, execution_state="COMPLETED", actual_finish=24,
                                     actual_periods=[[20, 22], [22, 23]], remaining_processing_ticks=0),
                "planner", "acceptor",
            )
        self.assertEqual(workspace, before)

    def test_boundary_completion_remains_available_as_an_explicit_correction(self):
        workspace, _, _ = _t1_workspace()
        before = deepcopy(workspace)
        prior = deepcopy(current_status_records(workspace)["A03"])
        values = self.next_assertions(workspace, execution_state="COMPLETED", actual_finish=22,
                                      remaining_processing_ticks=0)["A03"]
        state = values.pop("execution_state")
        reason = values.pop("reason")
        update_id = native.report_status_update(
            workspace, "A03", state, "planner", reason,
            supersedes_update_id=prior["id"], **values,
        )
        self.assertEqual(state_hash(workspace), state_hash(before))
        native.accept_status_update(workspace, update_id, "acceptor")
        native.validate_accepted_history(workspace, require_complete=True)
        self.assertEqual(workspace["execution"]["status_point"], 22)
        self.assertIn(prior, workspace["execution"]["updates"])
        self.assertEqual(current_status_records(workspace)["A03"]["actual_finish"], 22)
        self.assertEqual(workspace["approved_plan"], before["approved_plan"])

    def test_omitted_and_empty_outages_advance_without_rewriting_saved_history(self):
        for omitted in (False, True):
            with self.subTest(omitted=omitted):
                workspace = self.legacy_t1_workspace() if omitted else _t1_workspace()[0]
                before = deepcopy(workspace)
                prior = deepcopy(current_status_records(workspace)["A03"])
                self.assertEqual("accepted_outages" not in prior["execution_context"], omitted)
                old_plans = deepcopy(workspace["plan_history"] + [workspace["approved_plan"]])
                old_hashes = [plan["plan_hash"] for plan in old_plans]
                with TemporaryDirectory() as directory:
                    source = Path(directory) / "source-v2.json"
                    save(workspace, source)
                    source_bytes = source.read_bytes()
                    reopened = load(source)
                    validate_stored_plans(reopened)
                    self.assertEqual(reopened, before)
                    self.assertEqual(state_hash(reopened), state_hash(before))
                    advance_status_point(
                        reopened, 23,
                        self.next_assertions(reopened, actual_periods=[[20, 22], [22, 23]],
                                             remaining_processing_ticks=3),
                        "planner", "acceptor",
                    )
                    self.assertEqual(reopened["execution"]["updates"][:len(before["execution"]["updates"])],
                                     before["execution"]["updates"])
                    self.assertEqual(reopened["approved_plan"], before["approved_plan"])
                    self.assertEqual(reopened["plan_history"], before["plan_history"])
                    self.assertEqual(current_status_records(reopened)["A03"]["execution_context"],
                                     prior["execution_context"])
                    plan = propose(reopened)
                    self.assertEqual(plan["project_finish"], 30)
                    approve(reopened, "recovery-approver")
                    self.assertEqual(reopened["plan_history"], old_plans)
                    self.assertEqual([plan["plan_hash"] for plan in reopened["plan_history"]], old_hashes)
                    destination = Path(directory) / "advanced-v2.json"
                    save(reopened, destination)
                    restored = load(destination)
                    validate_stored_plans(restored)
                    self.assertEqual(restored, reopened)
                    self.assertEqual(source.read_bytes(), source_bytes)

    def test_omitted_outages_do_not_mask_a_real_context_change(self):
        for change in ("outage", "calendar"):
            with self.subTest(change=change):
                workspace = self.legacy_t1_workspace()
                if change == "outage":
                    report_id = report_unavailable(workspace, "M2", 22, 23, "operations", "new outage")
                    accept_report(workspace, report_id, "planner")
                    assertions = self.next_assertions(workspace)
                else:
                    project = deepcopy(workspace["project"])
                    project["calendars"][0]["daily_windows"] = [[14, 24], [25, 33]]
                    native.replace_project(workspace, project)
                    assertions = self.next_assertions(workspace, actual_periods=[[20, 22], [22, 23]],
                                                       remaining_processing_ticks=3)
                before = deepcopy(workspace)
                with self.assertRaisesRegex(ValueError, "changed historical execution context"):
                    advance_status_point(workspace, 23, assertions, "planner", "acceptor")
                self.assertEqual(workspace, before)


if __name__ == "__main__":
    unittest.main()
