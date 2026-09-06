from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from deterministic_scheduling_core.errors import SchedulingError
from deterministic_scheduling_core.native_planning_workflow import main, parse_time, run_demo, show
from deterministic_scheduling_core.project.planning_workspace import (
    accept_report, load, new_demo_workspace, report_unavailable, save, set_processing, state_hash,
)
from deterministic_scheduling_core.scheduling.planning_workspace import approve, propose, validate_plan


class NativePlanningWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        workspace = new_demo_workspace()
        propose(workspace)
        approve(workspace, "planner")
        cls.baseline = workspace

    def setUp(self):
        self.workspace = deepcopy(self.baseline)

    def accept_outage(self, resource="M2", start=20, finish=34):
        event = report_unavailable(self.workspace, resource, start, finish, "supervisor", "synthetic availability change")
        accept_report(self.workspace, event, "planner")
        return event

    def test_initial_plan_integrates_modes_calendars_and_physical_allocation(self):
        plan = self.workspace["approved_plan"]
        self.assertEqual(plan["project_finish"], 30)
        self.assertEqual(plan["selected_modes"]["A03"], "SPECIALIST")
        self.assertEqual(plan["physical_status"], "PROVEN_FEASIBLE")
        self.assertTrue(plan["pooled_riggers"])
        validate_plan(self.workspace, plan)
        repair = next(e for e in plan["entries"] if e["activity_id"] == "A03")
        self.assertEqual(repair["periods"], [[20, 24], [25, 27]])
        self.assertEqual(dict(repair["assignments"]), {"MECH": "M1", "SPECIALIST": "M2"})

    def test_reported_outage_does_not_mutate_trusted_input_or_approved_plan(self):
        before = deepcopy(self.workspace["approved_plan"])
        before_hash = state_hash(self.workspace)
        report_unavailable(self.workspace, "M2", 20, 34, "supervisor", "unverified")
        self.assertEqual(state_hash(self.workspace), before_hash)
        self.assertEqual(self.workspace["approved_plan"], before)
        proposal = propose(self.workspace)
        self.assertEqual(proposal["entries"], before["entries"])
        self.assertEqual(proposal["selected_modes"], before["selected_modes"])
        self.assertEqual(self.workspace["approved_plan"], before)

    def test_acceptance_replans_without_silently_approving_recovery(self):
        before = deepcopy(self.workspace["approved_plan"])
        self.accept_outage()
        self.assertIn("STALE", show(self.workspace))
        plan = propose(self.workspace)
        self.assertEqual(plan["selected_modes"]["A03"], "NORMAL")
        self.assertEqual(plan["project_finish"], 65)
        self.assertEqual(plan["physical_status"], "PROVEN_FEASIBLE")
        self.assertEqual(self.workspace["approved_plan"], before)
        validate_plan(self.workspace, plan)
        approve(self.workspace, "planner")
        self.assertEqual(self.workspace["plan_history"], [before])
        self.assertIsNone(self.workspace["proposal"])
        self.assertEqual(self.workspace["approved_plan"]["project_finish"], 65)

    def test_native_json_can_be_edited_without_changing_python(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "workspace.json"
            save(self.workspace, path)
            raw = json.loads(path.read_text())
            raw["project"]["activities"][2]["modes"][0]["processing_ticks"] = 1
            path.write_text(json.dumps(raw))
            reopened = load(path)
            plan = propose(reopened)
            self.assertEqual(plan["selected_modes"]["A03"], "NORMAL")
            self.assertLess(plan["project_finish"], self.baseline["approved_plan"]["project_finish"])
            self.assertEqual(reopened["approved_plan"], self.baseline["approved_plan"])

    def test_stale_proposal_cannot_be_approved_after_input_edit(self):
        propose(self.workspace)
        stale = deepcopy(self.workspace["proposal"])
        set_processing(self.workspace, "A03", "NORMAL", 1)
        self.workspace["proposal"] = stale
        with self.assertRaisesRegex(ValueError, "stale"):
            approve(self.workspace, "planner")
        self.assertEqual(self.workspace["approved_plan"], self.baseline["approved_plan"])

    def test_output_edit_is_not_an_approved_planning_decision(self):
        propose(self.workspace)
        self.workspace["proposal"]["entries"][0]["start"] += 1
        with self.assertRaisesRegex(ValueError, "edited"):
            approve(self.workspace, "planner")

    def test_accepted_infeasibility_preserves_fact_and_previous_plan(self):
        event = self.accept_outage(start=0, finish=144)
        before = deepcopy(self.workspace["approved_plan"])
        with self.assertRaises(SchedulingError):
            propose(self.workspace)
        self.assertEqual(self.workspace["reports"][0]["id"], event)
        self.assertEqual(self.workspace["reports"][0]["status"], "ACCEPTED")
        self.assertEqual(self.workspace["approved_plan"], before)
        self.assertIsNone(self.workspace["proposal"])
        self.assertIn("STALE", show(self.workspace))

    def test_loss_of_rigger_interchangeability_uses_physical_assignments(self):
        self.accept_outage(resource="R1", start=16, finish=22)
        plan = propose(self.workspace)
        self.assertFalse(plan["pooled_riggers"])
        for entry in plan["entries"]:
            if entry["activity_id"] in {"A05", "A06"}:
                self.assertIsNotNone(dict(entry["assignments"])["RIGGER"])
        validate_plan(self.workspace, plan)

    def test_recovery_repeats_with_same_input_order_and_environment(self):
        self.accept_outage()
        first = deepcopy(propose(self.workspace))
        second = propose(self.workspace)
        self.assertEqual(first["plan_hash"], second["plan_hash"])
        self.assertEqual(first["objective"], second["objective"])
        self.assertIn("same-environment", second["solver"]["repeatability"])

    def test_full_lifecycle_round_trip_retains_inputs_approval_and_history(self):
        with TemporaryDirectory() as directory, redirect_stdout(StringIO()) as output:
            path = Path(directory) / "demo.json"
            result = run_demo(path)
            self.assertEqual(result, load(path))
            self.assertEqual(len(result["plan_history"]), 1)
            self.assertEqual(result["reports"][0]["status"], "ACCEPTED")
            self.assertEqual(result["approved_plan"]["selected_modes"]["A03"], "NORMAL")
            self.assertIn("approved plan and trusted input hash unchanged", output.getvalue())
            self.assertIn("full JSON round-trip identical: True", output.getvalue())

    def test_cli_edits_and_runs_real_planning_loop(self):
        with TemporaryDirectory() as directory, redirect_stdout(StringIO()):
            path = str(Path(directory) / "cli.json")
            for args in (
                ["init", path], ["set-work", path, "A03", "NORMAL", "--hours", "6"],
                ["plan", path], ["approve", path, "--by", "planner"],
                ["report-unavailable", path, "--resource", "M2", "--start", "1@10:00", "--finish", "1@17:00", "--by", "supervisor", "--reason", "test"],
                ["accept-report", path, "E001", "--by", "planner"],
                ["plan", path], ["approve", path, "--by", "planner"], ["show", path],
            ):
                with self.subTest(args=args):
                    self.assertEqual(main(args), 0)
            self.assertEqual(load(path)["approved_plan"]["project_finish"], 65)
            self.assertEqual(main(["init", path]), 1)
            self.assertEqual(load(path)["approved_plan"]["project_finish"], 65)

    def test_relative_time_and_double_acceptance_are_explicit(self):
        self.assertEqual(parse_time("2@08:30"), 65)
        event = self.accept_outage()
        with self.assertRaisesRegex(ValueError, "awaiting acceptance"):
            accept_report(self.workspace, event, "planner")


if __name__ == "__main__":
    unittest.main()
