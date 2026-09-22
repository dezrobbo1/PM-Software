from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from deterministic_scheduling_core.native_planning_ui.hosted import execute, initial_response
from deterministic_scheduling_core.native_planning_ui.trial import (
    RECOVERED_FINISH,
    STARTING_FINISH,
    STATUS_POINT,
    TRIAL_ID,
    new_trial_workspace,
)
from deterministic_scheduling_core.project.planning_workspace import (
    accept_status_update,
    enable_status_tracking,
    report_status_update,
    state_hash,
    validate,
)
from deterministic_scheduling_core.scheduling.planning_workspace import (
    approve,
    propose,
    validate_plan,
    validate_stored_plans,
)


EXPECTED_START = {
    "A01": [[14, 16]], "A02": [[16, 20]], "A03": [[20, 22]],
    "A04": [[22, 24], [25, 34], [62, 63]], "A05": [[20, 24]],
    "A06": [[62, 66]], "A07": [[63, 67]], "A08": [[67, 69]],
    "A09": [[69, 72]], "A10": [],
}
EXPECTED_RECOVERY = {
    "A01": [], "A02": [], "A03": [], "A04": [[25, 34], [62, 67]],
    "A05": [], "A06": [[62, 66]], "A07": [[67, 71]],
    "A08": [[71, 72], [73, 74]], "A09": [[74, 77]], "A10": [],
}


def accept_briefing(workspace: dict) -> None:
    enable_status_tracking(workspace, STATUS_POINT)
    facts = {
        "A01": ("COMPLETED", [[14, 16]], 0),
        "A02": ("COMPLETED", [[16, 20]], 0),
        "A03": ("COMPLETED", [[20, 22]], 0),
        "A04": ("IN_PROGRESS", [[22, 24]], 14),
        "A05": ("COMPLETED", [[20, 24]], 0),
        "A06": ("NOT_STARTED", [], 4),
        "A07": ("NOT_STARTED", [], 4),
        "A08": ("NOT_STARTED", [], 2),
        "A09": ("NOT_STARTED", [], 3),
        "A10": ("NOT_STARTED", [], 0),
    }
    for activity_id, (execution_state, periods, remaining) in facts.items():
        begun = execution_state != "NOT_STARTED"
        update_id = report_status_update(
            workspace, activity_id, execution_state, "trial-planner",
            "Synthetic practitioner-trial field briefing",
            actual_start=periods[0][0] if begun else None,
            actual_finish=periods[-1][1] if execution_state == "COMPLETED" else None,
            actual_periods=periods,
            mode_id="FIXED" if begun else None,
            named_assignments=[] if begun else None,
            remaining_processing_ticks=remaining,
        )
        accept_status_update(workspace, update_id, "trial-planner")


class PlannerUpdateRecoveryTrialTests(unittest.TestCase):
    def test_owner_package_contains_source_bound_pristine_workspace(self):
        from tools.build_planner_update_recovery_trial_package import build

        with tempfile.TemporaryDirectory() as directory:
            archive_path = build(Path(directory), "test-source-sha")
            with zipfile.ZipFile(archive_path) as archive:
                root = f"{TRIAL_ID}/"
                manifest = json.loads(archive.read(root + "BUILD-SOURCE-MANIFEST.json"))
                packaged = json.loads(archive.read(root + "pristine-starting-workspace.pm-workspace.json"))
                self.assertEqual(manifest["source_sha"], "test-source-sha")
                self.assertEqual(packaged, new_trial_workspace())
                self.assertTrue({root + "participant-brief.md", root + "facilitator-observation.md", root + "exit-gate.md"} <= set(archive.namelist()))

    def test_pristine_trial_is_an_independently_valid_approved_plan(self):
        workspace = new_trial_workspace()
        validate(workspace)
        validate_stored_plans(workspace)
        self.assertIsNone(workspace["proposal"])
        self.assertEqual(workspace["approved_plan"]["project_finish"], STARTING_FINISH)
        self.assertEqual(
            {entry["activity_id"]: entry["periods"] for entry in workspace["approved_plan"]["entries"]},
            EXPECTED_START,
        )
        self.assertEqual(workspace["approved_plan"]["physical_status"], "PROVEN_FEASIBLE")

    def test_current_semantics_represent_briefing_and_pin_deterministic_recovery(self):
        workspace = new_trial_workspace()
        approved_hash = workspace["approved_plan"]["plan_hash"]
        accept_briefing(workspace)
        self.assertNotEqual(workspace["approved_plan"]["source_state_hash"], state_hash(workspace))

        first = deepcopy(propose(workspace))
        workspace["proposal"] = None
        second = propose(workspace)
        self.assertEqual(first, second)
        self.assertEqual(second["project_finish"], RECOVERED_FINISH)
        self.assertEqual(
            {entry["activity_id"]: entry["forecast_periods"] for entry in second["entries"]},
            EXPECTED_RECOVERY,
        )
        a04 = next(entry for entry in second["entries"] if entry["activity_id"] == "A04")
        self.assertEqual(a04["actual_periods"], [[22, 24]])
        self.assertEqual(a04["remaining_processing_ticks"], 14)
        self.assertEqual(a04["group_demands"], [["MECH", 2]])
        self.assertEqual(next(entry for entry in second["entries"] if entry["activity_id"] == "A06")["forecast_periods"], EXPECTED_START["A06"])
        self.assertEqual(workspace["approved_plan"]["plan_hash"], approved_hash)
        validate_plan(workspace, second)

    def test_save_reopen_preserves_trusted_history_and_approved_recovery(self):
        workspace = new_trial_workspace()
        accept_briefing(workspace)
        propose(workspace)
        approve(workspace, "trial-planner")
        serialized = json.dumps(workspace, indent=2, ensure_ascii=False) + "\n"
        reopened = json.loads(serialized)
        validate(reopened)
        validate_stored_plans(reopened)
        self.assertEqual(reopened, workspace)
        self.assertIsNone(reopened["proposal"])
        self.assertEqual(reopened["approved_plan"]["project_finish"], RECOVERED_FINISH)
        self.assertEqual(len(reopened["execution"]["updates"]), 10)

    def test_trial_uses_the_normal_solver_path(self):
        workspace = new_trial_workspace()
        accept_briefing(workspace)
        with patch(
            "deterministic_scheduling_core.scheduling.planning_workspace._solve_case",
            wraps=__import__(
                "deterministic_scheduling_core.scheduling.planning_workspace",
                fromlist=["_solve_case"],
            )._solve_case,
        ) as solve:
            propose(workspace)
        self.assertTrue(solve.called)
        self.assertNotIn("trial", workspace)

    def test_two_hosted_participants_start_identically_and_remain_independent(self):
        state_a = initial_response()["state"]
        state_b = initial_response()["state"]

        def call(state, action, **payload):
            status, result = execute({
                "expected_revision": state["revision"],
                "state": {key: deepcopy(state[key]) for key in ("revision", "dirty", "source", "workspace")},
                "payload": {"action": action, **payload},
            })
            self.assertEqual(status, 200, result.get("error"))
            return result["state"]

        state_a = call(state_a, "load-trial")
        state_b = call(state_b, "load-trial")
        self.assertEqual(state_a["workspace"], state_b["workspace"])
        pristine_b = deepcopy(state_b["workspace"])
        state_a = call(state_a, "enable-status", status_point=STATUS_POINT)
        self.assertEqual(state_b["workspace"], pristine_b)
        state_b = call(state_b, "export")
        self.assertEqual(state_b["workspace"], pristine_b)
        self.assertNotEqual(state_a["workspace"], state_b["workspace"])
        self.assertEqual(state_a["trial"]["id"], TRIAL_ID)


if __name__ == "__main__":
    unittest.main()
