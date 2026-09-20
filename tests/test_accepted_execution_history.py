"""Accepted history -> executable remainder semantic contract."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from deterministic_scheduling_core.errors import SchedulingError
from deterministic_scheduling_core.project.planning_workspace import (
    STATUS_SCHEMA,
    accept_report,
    accept_status_update,
    current_status_records,
    enable_status_tracking,
    load,
    new_blank_workspace,
    new_demo_workspace,
    replace_project,
    report_status_update,
    report_unavailable,
    save,
    state_hash,
    validate,
    validate_accepted_history,
)
from deterministic_scheduling_core.scheduling.planning_workspace import (
    _plan_hash,
    approve,
    propose,
    validate_plan,
    validate_stored_plans,
)
from deterministic_scheduling_core.native_planning_ui.server import BrowserSession, dispatch_action
from deterministic_scheduling_core.native_planning_ui.hosted import execute


def _accept(workspace, activity_id, state, **values):
    update_id = report_status_update(
        workspace, activity_id, state, "test-planner", values.pop("reason", "synthetic accepted status"), **values
    )
    accept_status_update(workspace, update_id, "accepting-planner")
    return update_id


def named_statused(*, outage=True, missing=None, remaining=4):
    workspace = new_demo_workspace()
    baseline = propose(workspace)
    approve(workspace, "baseline-planner")
    enable_status_tracking(workspace, 22)
    by_id = {entry["activity_id"]: entry for entry in baseline["entries"]}
    witness = {(activity, slot): resource for activity, slot, resource in baseline["allocation_witness"]}
    states = {
        "A01": "COMPLETED", "A02": "COMPLETED", "A03": "IN_PROGRESS", "A04": "NOT_STARTED",
        "A05": "COMPLETED", "A06": "COMPLETED", "A07": "COMPLETED", "A08": "NOT_STARTED",
    }
    for activity in workspace["project"]["activities"]:
        activity_id = activity["id"]
        if activity_id == missing:
            continue
        state = states[activity_id]
        if state == "NOT_STARTED":
            _accept(workspace, activity_id, state)
            continue
        entry = by_id[activity_id]
        assignments = [[slot, resource if resource is not None else witness[(activity_id, slot)]] for slot, resource in entry["assignments"]]
        values = dict(
            actual_start=entry["start"], actual_finish=entry["finish"], actual_periods=entry["periods"],
            mode_id=baseline["selected_modes"][activity_id], named_assignments=assignments,
            remaining_processing_ticks=0,
        )
        if activity_id == "A03":
            values.update(actual_start=20, actual_finish=None, actual_periods=[[20, 22]],
                          named_assignments=[["MECH", "M1"], ["SPECIALIST", "M2"]],
                          remaining_processing_ticks=remaining)
        _accept(workspace, activity_id, state, **values)
    if outage:
        report_id = report_unavailable(workspace, "M2", 22, 28, "test-planner", "synthetic accepted outage")
        accept_report(workspace, report_id, "accepting-planner")
    return workspace, baseline


def pooled_statused():
    workspace = new_blank_workspace()
    project = workspace["project"]
    project.update(id="synthetic-pooled-continuation", name="Synthetic pooled continuation", horizon_ticks=240,
                   objective_activity_id="N15", pool_riggers=False)
    project["calendars"] = [
        {"id": "STANDARD", "daily_windows": [[15, 31]]},
        {"id": "RESOURCE_DAY", "daily_windows": [[14, 34]]},
    ]
    project["resources"] = []
    project["resource_groups"] = [
        {"id": group_id, "name": group_id, "capacity": 2, "calendar_id": "RESOURCE_DAY", "disjoint": True, "interchangeable": True}
        for group_id in ("MTP", "ETP")
    ]
    durations = [6, 4, 8, 6, 4, 4, 0, 2, 6, 20, 6, 2, 0, 6, 0]
    predecessors = [[], [], [2], [3], [4], [5], [6], [], [8], [9], [10], [11], [12], [], [1, 7, 13, 14]]
    activities = []
    for number, (duration, prior) in enumerate(zip(durations, predecessors), 1):
        group_id = "ETP" if number in (2, 6, 10) else "MTP"
        demand = 1 if number in (2, 6) else 2
        activities.append({
            "id": f"N{number:02d}", "name": f"Synthetic operation {number}",
            "predecessors": [f"N{value:02d}" for value in prior], "not_before": 0,
            "modes": [{"id": "FIXED", "processing_ticks": duration, "calendar_id": "STANDARD",
                       "continuity": "SUSPENDABLE_AT_AVAILABILITY_GAPS", "requirements": [],
                       "group_requirements": [{"group_id": group_id, "demand": demand}] if duration else []}],
        })
    project["activities"] = activities
    validate(workspace)
    enable_status_tracking(workspace, 31)
    completed = {
        "N02": (15, 19), "N08": (15, 17), "N09": (17, 23), "N14": (23, 29),
    }
    in_progress = {
        "N03": ([29, 31], 6),
        "N10": ([23, 31], 16),
    }
    for activity in activities:
        activity_id = activity["id"]
        if activity_id in completed:
            start, finish = completed[activity_id]
            _accept(workspace, activity_id, "COMPLETED", actual_start=start, actual_finish=finish,
                    actual_periods=[[start, finish]], mode_id="FIXED", named_assignments=[], remaining_processing_ticks=0)
        elif activity_id in in_progress:
            period, remaining = in_progress[activity_id]
            _accept(workspace, activity_id, "IN_PROGRESS", actual_start=period[0], actual_finish=None,
                    actual_periods=[period], mode_id="FIXED", named_assignments=[], remaining_processing_ticks=remaining)
        else:
            _accept(workspace, activity_id, "NOT_STARTED")
    return workspace


class AcceptedExecutionHistoryTests(unittest.TestCase):
    def test_legacy_profiles_reject_mixed_execution_fields(self):
        for workspace in (new_demo_workspace(), new_blank_workspace()):
            workspace["execution"] = {"status_point": 22, "updates": []}
            with self.assertRaisesRegex(ValueError, "version two|version-two"):
                validate(workspace)

    def test_supersession_cycles_and_forks_are_rejected_on_open(self):
        workspace, _ = named_statused(outage=False)
        original = current_status_records(workspace)["A03"]
        correction = deepcopy(original)
        correction.update(id="U009", supersedes_update_id=original["id"])
        workspace["execution"]["updates"].append(correction)
        original["supersedes_update_id"] = correction["id"]
        with self.assertRaisesRegex(ValueError, "cycle"):
            validate(workspace)
        original["supersedes_update_id"] = None
        fork = deepcopy(correction)
        fork["id"] = "U010"
        workspace["execution"]["updates"].append(fork)
        with self.assertRaisesRegex(ValueError, "competing|fork"):
            validate(workspace)

    def test_estimate_correction_retains_history_after_future_calendar_edit(self):
        workspace, _ = named_statused(outage=False)
        prior = deepcopy(current_status_records(workspace)["A03"])
        project = deepcopy(workspace["project"])
        next(c for c in project["calendars"] if c["id"] == "DAY")["daily_windows"] = [[28, 34]]
        replace_project(workspace, project)
        _accept(workspace, "A03", "IN_PROGRESS", actual_start=20, actual_periods=[[20, 22]],
                mode_id="SPECIALIST", named_assignments=prior["named_assignments"],
                remaining_processing_ticks=6, supersedes_update_id=prior["id"])
        current = current_status_records(workspace)["A03"]
        self.assertEqual(current["execution_context"], prior["execution_context"])
        entry = next(e for e in propose(workspace)["entries"] if e["activity_id"] == "A03")
        self.assertEqual(entry["actual_periods"], [[20, 22]])
        self.assertEqual(entry["forecast_periods"], [[28, 34]])

    def test_historical_predecessor_finish_must_precede_actual_start(self):
        workspace, _ = named_statused(outage=False)
        prior = current_status_records(workspace)["A01"]
        _accept(workspace, "A01", "COMPLETED", actual_start=14, actual_finish=21,
                actual_periods=[[14, 16]], mode_id="FIXED", named_assignments=[],
                remaining_processing_ticks=0, supersedes_update_id=prior["id"])
        accepted = deepcopy(workspace["execution"])
        with self.assertRaisesRegex(ValueError, "predecessor.*finish|out-of-sequence"):
            propose(workspace)
        self.assertEqual(workspace["execution"], accepted)

    def test_continuous_begun_work_cannot_restart_after_outage(self):
        workspace, _ = named_statused()
        record = current_status_records(workspace)["A03"]
        record["execution_context"]["mode"]["continuity"] = "CONTINUOUS"
        activity = next(a for a in workspace["project"]["activities"] if a["id"] == "A03")
        next(m for m in activity["modes"] if m["id"] == "SPECIALIST")["continuity"] = "CONTINUOUS"
        with self.assertRaisesRegex((ValueError, SchedulingError), "continuous|CONTINUOUS|no executable"):
            propose(workspace)
        self.assertEqual(record["actual_periods"], [[20, 22]])

    def test_group_history_constrains_future_allocation_inside_solver(self):
        workspace = new_blank_workspace()
        p = workspace["project"]
        p.update(horizon_ticks=8, objective_activity_id="H", resources=[], pool_riggers=False)
        p["calendars"] = [{"id": "ALL", "daily_windows": [[0, 48]]},
                          {"id": "X", "daily_windows": [[0, 1], [4, 5], [6, 7]]},
                          {"id": "Y", "daily_windows": [[0, 1], [2, 3]]},
                          {"id": "Z", "daily_windows": [[2, 3], [4, 5], [6, 7]]}]
        p["resource_groups"] = [{"id": "G", "name": "G", "capacity": 2,
                                 "calendar_id": "ALL", "disjoint": True, "interchangeable": True}]
        p["activities"] = [{"id": aid, "name": aid, "predecessors": ["X", "Y", "Z"] if aid == "H" else [],
                            "not_before": 0, "modes": [{"id": "FIXED", "processing_ticks": 0 if aid == "H" else 2,
                            "calendar_id": "ALL" if aid == "H" else aid, "continuity": "SUSPENDABLE_AT_AVAILABILITY_GAPS",
                            "requirements": [], "group_requirements": [] if aid == "H" else [{"group_id": "G", "demand": 1}]}]}
                           for aid in ("X", "Y", "Z", "H")]
        enable_status_tracking(workspace, 4)
        _accept(workspace, "X", "IN_PROGRESS", actual_start=0, actual_periods=[[0, 1]], mode_id="FIXED", remaining_processing_ticks=1)
        _accept(workspace, "Y", "COMPLETED", actual_start=0, actual_finish=3, actual_periods=[[0, 1], [2, 3]], mode_id="FIXED", remaining_processing_ticks=0)
        _accept(workspace, "Z", "IN_PROGRESS", actual_start=2, actual_periods=[[2, 3]], mode_id="FIXED", remaining_processing_ticks=1)
        _accept(workspace, "H", "NOT_STARTED")
        plan = propose(workspace)
        self.assertEqual(plan["project_finish"], 7)
        entries = {e["activity_id"]: e for e in plan["entries"]}
        self.assertNotEqual(entries["X"]["forecast_periods"], entries["Z"]["forecast_periods"])
        validate_plan(workspace, plan)
        corrupted = deepcopy(plan)
        for e in corrupted["entries"]:
            if e["activity_id"] in ("X", "Z"):
                e.update(start=4, finish=5, forecast_start=4, forecast_finish=5, periods=[[4, 5]], forecast_periods=[[4, 5]])
        corrupted["plan_hash"] = _plan_hash(corrupted)
        with self.assertRaisesRegex(ValueError, "no-handover"):
            validate_plan(workspace, corrupted)

    def test_named_acceptance_control_is_exact_and_begun_mode_is_fixed(self):
        workspace, _ = named_statused()
        plan = propose(workspace)
        entries = {entry["activity_id"]: entry for entry in plan["entries"]}
        self.assertEqual(plan["project_finish"], 63)
        self.assertEqual(plan["selected_modes"]["A03"], "SPECIALIST")
        self.assertEqual(entries["A03"]["actual_periods"], [[20, 22]])
        self.assertEqual(entries["A03"]["forecast_periods"], [[28, 32]])
        self.assertEqual(entries["A04"]["forecast_periods"], [[32, 34]])
        self.assertEqual(entries["A08"]["forecast_periods"], [[62, 63]])
        self.assertEqual(entries["A03"]["actual_assignments"], [["MECH", "M1"], ["SPECIALIST", "M2"]])
        validate_plan(workspace, plan)

    def test_remaining_is_accepted_forecast_not_original_minus_actual(self):
        workspace, _ = named_statused(remaining=5)
        entry = next(entry for entry in propose(workspace)["entries"] if entry["activity_id"] == "A03")
        self.assertEqual(sum(finish - start for start, finish in entry["actual_periods"]), 2)
        self.assertEqual(sum(finish - start for start, finish in entry["forecast_periods"]), 5)
        self.assertNotEqual(6 - 2, 5)

    def test_status_floor_history_immutability_and_future_calendar_change(self):
        workspace, _ = named_statused(outage=False)
        project = deepcopy(workspace["project"])
        next(calendar for calendar in project["calendars"] if calendar["id"] == "DAY")["daily_windows"] = [[28, 34]]
        replace_project(workspace, project)
        entry = next(entry for entry in propose(workspace)["entries"] if entry["activity_id"] == "A03")
        self.assertEqual(entry["actual_periods"], [[20, 22]])
        self.assertGreaterEqual(entry["forecast_start"], 28)
        self.assertEqual(sum(finish - start for start, finish in entry["forecast_periods"]), 4)

    def test_missing_status_is_unknown_and_zero_remaining_is_not_completed(self):
        workspace, _ = named_statused(missing="A08")
        with self.assertRaisesRegex(ValueError, "UNKNOWN: A08"):
            propose(workspace)
        workspace, _ = named_statused(outage=False, remaining=0)
        plan = propose(workspace)
        entry = next(entry for entry in plan["entries"] if entry["activity_id"] == "A03")
        self.assertEqual(entry["execution_state"], "IN_PROGRESS")
        self.assertEqual(entry["forecast_periods"], [])
        self.assertEqual(entry["forecast_start"], 22)

    def test_named_assignment_is_fixed_for_begun_remainder(self):
        workspace, _ = named_statused(outage=False)
        project = deepcopy(workspace["project"])
        resource = next(resource for resource in project["resources"] if resource["id"] == "M1")
        resource["calendar_id"] = "NIGHT"
        replace_project(workspace, project)
        with self.assertRaises(SchedulingError):
            propose(workspace)
        current = current_status_records(workspace, require_complete=True)["A03"]
        self.assertEqual(dict(current["named_assignments"])["MECH"], "M1")

    def test_pooled_continuation_keeps_group_quantity_and_eight_hours(self):
        workspace = pooled_statused()
        plan = propose(workspace)
        entry = next(entry for entry in plan["entries"] if entry["activity_id"] == "N10")
        self.assertEqual(sum(finish - start for start, finish in entry["actual_periods"]), 8)
        self.assertEqual(sum(finish - start for start, finish in entry["forecast_periods"]), 16)
        self.assertEqual(entry["actual_group_demands"], [["ETP", 2]])
        self.assertEqual(entry["group_demands"], [["ETP", 2]])
        self.assertEqual(entry["actual_assignments"], [])
        self.assertFalse(any("@group/" in json.dumps(value) for value in (entry, plan["allocation_witness"])))
        self.assertIsNone(workspace["approved_plan"])
        validate_plan(workspace, plan)

    def test_group_capacity_and_calendar_gap_are_independently_checked(self):
        workspace = pooled_statused()
        plan = propose(workspace)
        entry = next(entry for entry in plan["entries"] if entry["activity_id"] == "N10")
        self.assertEqual(sum(finish - start for start, finish in entry["forecast_periods"]), 16)
        corrupted = deepcopy(plan)
        corrupted_entry = next(item for item in corrupted["entries"] if item["activity_id"] == "N10")
        corrupted_entry["group_demands"] = [["ETP", 3]]
        corrupted["plan_hash"] = _plan_hash(corrupted)
        with self.assertRaisesRegex(ValueError, "group demands|capacity"):
            validate_plan(workspace, corrupted)

    def test_superseding_correction_wins_by_identity_and_preserves_provenance(self):
        workspace, _ = named_statused(outage=False)
        first_plan = propose(workspace)
        approve(workspace, "recovery-planner")
        prior = current_status_records(workspace)["A03"]
        correction = report_status_update(
            workspace, "A03", "IN_PROGRESS", "correcting-planner", "correct remaining estimate",
            actual_start=20, actual_finish=None, actual_periods=[[20, 22]], mode_id="SPECIALIST",
            named_assignments=[["MECH", "M1"], ["SPECIALIST", "M2"]], remaining_processing_ticks=6,
            occurred_at=19, supersedes_update_id=prior["id"],
        )
        accept_status_update(workspace, correction, "accepting-planner")
        current = current_status_records(workspace, require_complete=True)["A03"]
        self.assertEqual(current["id"], correction)
        self.assertEqual(current["remaining_processing_ticks"], 6)
        self.assertIn(prior["id"], [update["id"] for update in workspace["execution"]["updates"]])
        self.assertNotEqual(workspace["approved_plan"]["source_state_hash"], state_hash(workspace))
        second_plan = propose(workspace)
        second = next(entry for entry in second_plan["entries"] if entry["activity_id"] == "A03")
        self.assertEqual(second["actual_periods"], [[20, 22]])
        self.assertEqual(sum(finish - start for start, finish in second["forecast_periods"]), 6)
        self.assertNotEqual(first_plan["plan_hash"], second_plan["plan_hash"])

    def test_acceptance_stales_without_auto_approval_and_failed_recovery_retains_facts(self):
        workspace = new_demo_workspace()
        propose(workspace); approve(workspace, "baseline-planner")
        old_approval = deepcopy(workspace["approved_plan"])
        enable_status_tracking(workspace, 22)
        update = report_status_update(workspace, "A01", "COMPLETED", "planner", "first fact",
                                      actual_start=14, actual_finish=16, actual_periods=[[14, 16]], mode_id="FIXED",
                                      named_assignments=[], remaining_processing_ticks=0)
        self.assertEqual(workspace["approved_plan"], old_approval)
        accept_status_update(workspace, update, "planner")
        self.assertEqual(workspace["approved_plan"], old_approval)
        self.assertIsNone(workspace["proposal"])
        self.assertNotEqual(workspace["approved_plan"]["source_state_hash"], state_hash(workspace))

        workspace, _ = named_statused(outage=False)
        accepted_before = deepcopy(workspace["execution"])
        old_approval = deepcopy(workspace["approved_plan"])
        outage = report_unavailable(workspace, "M2", 0, 144, "planner", "synthetic full-horizon outage")
        accept_report(workspace, outage, "planner")
        with self.assertRaises(SchedulingError):
            propose(workspace)
        self.assertEqual(workspace["execution"], accepted_before)
        self.assertEqual(workspace["approved_plan"], old_approval)
        self.assertIsNone(workspace["proposal"])

    def test_multiple_outages_coexist_and_reach_future_calculation(self):
        workspace, _ = named_statused(outage=False)
        ids = []
        for start, finish in ((22, 24), (25, 28)):
            report = report_unavailable(workspace, "M2", start, finish, "planner", "separate accepted outage")
            accept_report(workspace, report, "planner")
            ids.append(report)
        self.assertEqual(ids, ["E001", "E002"])
        self.assertEqual([(r["start"], r["finish"]) for r in workspace["reports"]], [(22, 24), (25, 28)])
        entry = next(entry for entry in propose(workspace)["entries"] if entry["activity_id"] == "A03")
        self.assertEqual(entry["forecast_periods"], [[28, 32]])

    def test_distinct_named_outages_and_actual_correction_survive_reopen(self):
        workspace, _ = named_statused(outage=False)
        for resource, start, finish in (("M1", 22, 26), ("M2", 26, 28)):
            identifier = report_unavailable(workspace, resource, start, finish, "planner", "synthetic distinct outage")
            accept_report(workspace, identifier, "planner")
        self.assertEqual(len({r["id"] for r in workspace["reports"]}), 2)
        plan = propose(workspace)
        self.assertEqual(next(e for e in plan["entries"] if e["activity_id"] == "A03")["forecast_periods"], [[28, 32]])
        approve(workspace, "test-only")
        prior = deepcopy(current_status_records(workspace)["A03"])
        _accept(workspace, "A03", "IN_PROGRESS", actual_start=21, actual_periods=[[21, 22]], mode_id="SPECIALIST",
                named_assignments=prior["named_assignments"], remaining_processing_ticks=4,
                occurred_at=20, supersedes_update_id=prior["id"])
        workspace["execution"]["updates"].reverse()
        self.assertEqual(current_status_records(workspace)["A03"]["actual_start"], 21)
        self.assertIn(prior, workspace["execution"]["updates"])
        propose(workspace)
        with TemporaryDirectory() as directory:
            destination = Path(directory) / "corrected.json"
            save(workspace, destination)
            reopened = load(destination)
            validate_stored_plans(reopened)
            self.assertEqual(reopened, workspace)

    def test_save_reopen_preserves_status_history_remaining_and_approvals(self):
        workspace, _ = named_statused()
        propose(workspace); approve(workspace, "recovery-planner")
        with TemporaryDirectory() as directory:
            path = Path(directory) / "statused.pm-workspace.json"
            save(workspace, path)
            reopened = load(path)
            validate_stored_plans(reopened)
            self.assertEqual(reopened, workspace)
            self.assertEqual(current_status_records(reopened)["A03"]["remaining_processing_ticks"], 4)
            self.assertEqual(reopened["approved_plan"]["entries"], workspace["approved_plan"]["entries"])

    def test_old_v0_and_v1_workspaces_remain_valid_and_unknown(self):
        version_zero = new_demo_workspace()
        version_one = new_blank_workspace()
        for workspace in (version_zero, version_one):
            validate(workspace)
            with self.assertRaisesRegex(ValueError, "version-two"):
                current_status_records(workspace)
            with TemporaryDirectory() as directory:
                path = Path(directory) / "legacy.json"
                save(workspace, path)
                self.assertEqual(load(path), workspace)

    def test_rehashed_history_and_future_boundary_corruption_is_rejected(self):
        workspace, _ = named_statused()
        plan = propose(workspace)
        corrupted = deepcopy(plan)
        entry = next(entry for entry in corrupted["entries"] if entry["activity_id"] == "A03")
        entry["actual_periods"] = [[21, 23]]
        corrupted["plan_hash"] = _plan_hash(corrupted)
        with self.assertRaisesRegex(ValueError, "rewrites accepted"):
            validate_plan(workspace, corrupted)
        corrupted = deepcopy(plan)
        entry = next(entry for entry in corrupted["entries"] if entry["activity_id"] == "A03")
        entry.update(start=20, finish=24, periods=[[20, 24]], forecast_start=20, forecast_finish=24, forecast_periods=[[20, 24]])
        corrupted["plan_hash"] = _plan_hash(corrupted)
        with self.assertRaisesRegex(ValueError, "status/horizon"):
            validate_plan(workspace, corrupted)

    def test_reported_update_does_not_change_trusted_state(self):
        workspace, _ = named_statused(outage=False)
        before = state_hash(workspace)
        current = current_status_records(workspace)["A03"]
        report_status_update(
            workspace, "A03", "IN_PROGRESS", "planner", "unaccepted draft correction",
            actual_start=20, actual_finish=None, actual_periods=[[20, 22]], mode_id="SPECIALIST",
            named_assignments=[["MECH", "M1"], ["SPECIALIST", "M2"]], remaining_processing_ticks=8,
            supersedes_update_id=current["id"],
        )
        self.assertEqual(state_hash(workspace), before)
        self.assertEqual(current_status_records(workspace)["A03"]["remaining_processing_ticks"], 4)

    def test_local_and_hosted_status_actions_use_the_same_atomic_workflow(self):
        session = BrowserSession()
        dispatch_action("/api/enable-status", {"status_point": 22}, session)
        payload = {
            "activity_id": "A01", "execution_state": "COMPLETED", "actor": "planner", "reason": "reviewed actual",
            "actual_start": 14, "actual_finish": 16, "actual_periods": [[14, 16]], "mode_id": "FIXED",
            "named_assignments": [], "remaining_processing_ticks": 0, "occurred_at": 16, "supersedes_update_id": None,
        }
        update_id = dispatch_action("/api/status-update", payload, session)["update_id"]
        self.assertEqual(current_status_records(session.workspace), {})
        dispatch_action("/api/accept-status", {"update_id": update_id, "actor": "planner"}, session)
        self.assertEqual(current_status_records(session.workspace)["A01"]["execution_state"], "COMPLETED")

        fresh = BrowserSession()
        state = {"revision": fresh.revision, "dirty": fresh.dirty, "source": fresh.source, "workspace": fresh.workspace}
        status, response = execute({"expected_revision": 0, "state": state, "payload": {"action": "enable-status", "status_point": 22}})
        self.assertEqual(status, 200, response)
        self.assertEqual(response["state"]["workspace"]["schema"], STATUS_SCHEMA)

        def hosted_action(view, action, **fields):
            submitted = {key: view[key] for key in ("revision", "dirty", "source", "workspace")}
            status, result = execute({"expected_revision": submitted["revision"], "state": submitted,
                                      "payload": {"action": action, **fields}})
            self.assertEqual(status, 200, result)
            return result

        reported = hosted_action(response["state"], "status-update", **payload)
        self.assertEqual(current_status_records(reported["state"]["workspace"]), {})
        accepted = hosted_action(reported["state"], "accept-status", update_id=reported["update_id"], actor="planner")
        self.assertEqual(current_status_records(accepted["state"]["workspace"])["A01"]["execution_state"], "COMPLETED")
        for workspace in (named_statused()[0], pooled_statused()):
            opened = hosted_action(accepted["state"], "open", workspace=workspace, filename="synthetic.json")
            calculated = hosted_action(opened["state"], "calculate")
            approved = hosted_action(calculated["state"], "approve", actor="hosted-adapter-test-only")
            exported = hosted_action(approved["state"], "export")
            reopened = hosted_action(exported["state"], "open", workspace=exported["state"]["workspace"], filename="reopened.json")
            self.assertEqual(reopened["state"]["workspace"], exported["state"]["workspace"])
            self.assertEqual(reopened["state"]["approved_status"], "CURRENT")


if __name__ == "__main__":
    unittest.main()
