from __future__ import annotations

from copy import deepcopy
from http.cookiejar import CookieJar
import json
from threading import Thread
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener

from deterministic_scheduling_core.native_planning_ui.server import create_server, _comparison
from deterministic_scheduling_core.project.planning_workspace import new_demo_workspace, accept_report, report_unavailable
from deterministic_scheduling_core.scheduling.planning_workspace import propose, approve, _plan_hash


class NativePlanningUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.saved = new_demo_workspace()
        propose(cls.saved)
        approve(cls.saved, "original-planner")
        cls.stale = deepcopy(cls.saved)
        event = report_unavailable(cls.stale, "M2", 20, 34, "supervisor", "synthetic outage")
        accept_report(cls.stale, event, "accepting-planner")
        cls.recovery = deepcopy(cls.stale)
        propose(cls.recovery)
        approve(cls.recovery, "recovery-planner")

    def setUp(self):
        self.server = create_server(0)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.opener = build_opener(HTTPCookieProcessor(CookieJar()))
        self.state = self.get_json("/api/state")["state"]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def get_json(self, path):
        with self.opener.open(self.base + path, timeout=10) as response:
            return json.loads(response.read())

    def post(self, path, payload=None, revision=None):
        body = {"revision": self.state["revision"] if revision is None else revision, **(payload or {})}
        request = Request(
            self.base + path,
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "Origin": self.base},
            method="POST",
        )
        try:
            with self.opener.open(request, timeout=30) as response:
                result = json.loads(response.read())
        except HTTPError as error:
            result = json.loads(error.read())
            if "state" in result:
                self.state = result["state"]
            return error.code, result
        self.state = result["state"]
        return 200, result

    def test_assets_and_loopback_headers_are_served_without_remote_runtime(self):
        with self.opener.open(self.base + "/", timeout=10) as response:
            html = response.read().decode()
            self.assertIn("Native planning trial", html)
            self.assertIn("default-src 'self'", response.headers["Content-Security-Policy"])
            self.assertNotIn("https://", html)
        with self.opener.open(self.base + "/app.js", timeout=10) as response:
            script = response.read().decode()
            self.assertIn("/api/calculate", script)
            self.assertNotIn("CP-SAT", script)

    def test_full_example_lifecycle_and_export_reopen_preserve_state(self):
        status, _ = self.post("/api/calculate")
        self.assertEqual(status, 200)
        proposal = self.state["workspace"]["proposal"]
        self.assertEqual(proposal["selected_modes"]["A03"], "SPECIALIST")
        self.assertEqual(proposal["project_finish"], 30)
        self.assertEqual(proposal["physical_status"], "PROVEN_FEASIBLE")

        calculated_revision = self.state["revision"]
        self.post("/api/approve", {"actor": "browser-planner"})
        approved_before = deepcopy(self.state["workspace"]["approved_plan"])
        status, _ = self.post("/api/approve", {"actor": "browser-planner"}, revision=calculated_revision)
        self.assertEqual(status, 409)
        self.assertEqual(self.state["workspace"]["approved_plan"], approved_before)
        self.assertEqual(self.state["workspace"]["plan_history"], [])
        trusted_before = self.state["trusted_input_hash"]
        self.post("/api/report", {
            "resource_id": "M2", "start": 20, "finish": 34,
            "reporter": "browser-supervisor", "reason": "synthetic browser test",
        })
        self.assertEqual(self.state["trusted_input_hash"], trusted_before)
        self.assertEqual(self.state["workspace"]["approved_plan"], approved_before)
        self.assertEqual(self.state["workspace"]["reports"][0]["status"], "REPORTED")

        self.post("/api/accept", {"report_id": "E001", "actor": "browser-planner"})
        self.assertEqual(self.state["approved_status"], "STALE")
        self.post("/api/calculate")
        recovery = self.state["workspace"]["proposal"]
        self.assertEqual(recovery["selected_modes"]["A03"], "NORMAL")
        self.assertEqual(recovery["project_finish"], 65)
        specialist = next(a for a in recovery["alternatives"] if a["modes"]["A03"] == "SPECIALIST")
        self.assertEqual(specialist["objective"][0], 71)
        self.assertIsNone(recovery.get("approved_by"))
        self.assertEqual(self.state["comparison"]["changed_modes"][0]["activity_id"], "A03")

        self.post("/api/approve", {"actor": "browser-planner"})
        self.assertEqual(len(self.state["workspace"]["plan_history"]), 1)
        self.assertEqual(self.state["workspace"]["approved_plan"]["project_finish"], 65)
        _, exported = self.post("/api/export")
        saved = json.loads(exported["workspace_json"])
        self.assertFalse(self.state["dirty"])

        self.post("/api/new")
        self.assertNotEqual(self.state["workspace"]["project"]["id"], saved["project"]["id"])
        self.post("/api/open", {"workspace": saved, "filename": exported["filename"]})
        self.assertEqual(self.state["workspace"], saved)
        self.assertEqual(len(self.state["workspace"]["plan_history"]), 1)
        self.assertIsNone(self.state["workspace"]["proposal"])

    def test_project_edit_invalidates_proposal_and_stale_revision_cannot_approve(self):
        self.post("/api/calculate")
        old_revision = self.state["revision"]
        project = deepcopy(self.state["workspace"]["project"])
        project["activities"][0]["modes"][0]["processing_ticks"] = 6
        self.post("/api/project", {"project": project})
        self.assertIsNone(self.state["workspace"]["proposal"])
        status, result = self.post("/api/approve", {"actor": "browser-planner"}, revision=old_revision)
        self.assertEqual(status, 409)
        self.assertIn("another request", result["error"])
        self.assertIsNone(self.state["workspace"]["approved_plan"])
        self.post("/api/calculate")
        first_entry = next(e for e in self.state["workspace"]["proposal"]["entries"] if e["activity_id"] == "A01")
        self.assertEqual(sum(finish - start for start, finish in first_entry["periods"]), 6)

    def test_invalid_and_infeasible_requests_retain_prior_approval(self):
        self.post("/api/calculate")
        self.post("/api/approve", {"actor": "browser-planner"})
        approved = deepcopy(self.state["workspace"]["approved_plan"])

        invalid = deepcopy(self.state["workspace"]["project"])
        invalid["activities"][0]["predecessors"] = ["MISSING"]
        status, result = self.post("/api/project", {"project": invalid})
        self.assertEqual(status, 400)
        self.assertIn("unknown predecessor", result["error"])
        self.assertEqual(self.state["workspace"]["approved_plan"], approved)

        self.post("/api/report", {
            "resource_id": "M2", "start": 0, "finish": 144,
            "reporter": "browser-supervisor", "reason": "synthetic full-horizon outage",
        })
        self.post("/api/accept", {"report_id": "E001", "actor": "browser-planner"})
        status, result = self.post("/api/calculate")
        self.assertEqual(status, 422)
        self.assertIn("no executable plan", result["error"])
        self.assertEqual(self.state["workspace"]["reports"][0]["status"], "ACCEPTED")
        self.assertEqual(self.state["workspace"]["approved_plan"], approved)
        self.assertEqual(self.state["approved_status"], "STALE")

    def test_new_workspace_enforces_bounded_activity_count(self):
        self.post("/api/new")
        self.assertEqual(len(self.state["workspace"]["project"]["activities"]), 8)
        project = deepcopy(self.state["workspace"]["project"])
        project["activities"].pop()
        project["objective_activity_id"] = "N07"
        status, result = self.post("/api/project", {"project": project})
        self.assertEqual(status, 400)
        self.assertIn("8 to 15", result["error"])

    def test_refresh_reads_state_without_calculating_or_approving(self):
        initial_revision = self.state["revision"]
        first = self.get_json("/api/state")["state"]
        second = self.get_json("/api/state")["state"]
        self.assertEqual(first, second)
        self.assertEqual(second["revision"], initial_revision)
        self.assertIsNone(second["workspace"]["proposal"])
        self.assertIsNone(second["workspace"]["approved_plan"])

    def test_comparison_tolerates_activities_added_then_removed_after_approval(self):
        self.post("/api/new")
        project = deepcopy(self.state["workspace"]["project"])
        project["activities"].append({
            "id": "N09", "name": "Temporary approved activity", "predecessors": ["N07"], "not_before": 0,
            "modes": [{
                "id": "FIXED", "processing_ticks": 2, "calendar_id": "DAY",
                "continuity": "SUSPENDABLE_AT_AVAILABILITY_GAPS", "requirements": [],
            }],
        })
        next(a for a in project["activities"] if a["id"] == "N08")["predecessors"] = ["N09"]
        self.post("/api/project", {"project": project})
        self.post("/api/calculate")
        self.post("/api/approve", {"actor": "browser-planner"})

        project = deepcopy(self.state["workspace"]["project"])
        project["activities"] = [a for a in project["activities"] if a["id"] != "N09"]
        next(a for a in project["activities"] if a["id"] == "N08")["predecessors"] = ["N07"]
        self.post("/api/project", {"project": project})
        status, _ = self.post("/api/calculate")
        self.assertEqual(status, 200)
        removed = next(item for item in self.state["comparison"]["changed_modes"] if item["activity_id"] == "N09")
        self.assertEqual(removed, {"activity_id": "N09", "old": "FIXED", "new": None})

    def test_moved_empty_milestone_is_a_timing_change(self):
        old = {"selected_modes": {"HANDOFF": "FIXED"}, "project_finish": 30,
               "entries": [{"activity_id": "HANDOFF", "start": 30, "finish": 30, "periods": [], "assignments": []}]}
        new = deepcopy(old)
        new["entries"][0].update(start=65, finish=65)
        new["project_finish"] = 65
        comparison = _comparison({"approved_plan": old, "proposal": new})
        self.assertNotIn("HANDOFF", comparison["unchanged_activity_ids"])
        change = comparison["changed_periods"][0]
        self.assertEqual((change["old_start"], change["old_finish"], change["new_start"], change["new_finish"]), (30, 30, 65, 65))
        self.assertEqual((change["old"], change["new"]), ([], []))
        self.assertEqual(_comparison({"approved_plan": old, "proposal": deepcopy(old)})["unchanged_activity_ids"], ["HANDOFF"])

    def test_valid_recovery_history_and_stale_approval_open_without_solving(self):
        for saved, status in [(self.recovery, "CURRENT"), (self.stale, "STALE")]:
            with self.subTest(status=status), patch("deterministic_scheduling_core.native_planning_ui.server.propose", side_effect=AssertionError("open must not solve")), patch("deterministic_scheduling_core.scheduling.planning_workspace._solve_case", side_effect=AssertionError("open must not optimise")):
                code, _ = self.post("/api/open", {"workspace": saved})
                self.assertEqual(code, 200)
                self.assertEqual(self.state["workspace"], saved)
                self.assertEqual(self.state["approved_status"], status)

    def assert_upload_rejected(self, saved):
        before = deepcopy(self.get_json("/api/state")["state"])
        code, result = self.post("/api/open", {"workspace": saved})
        self.assertEqual(code, 400, result)
        self.assertIn("stored", result["error"].lower())
        self.assertEqual(self.get_json("/api/state")["state"], before)
        code, _ = self.post("/api/export")
        self.assertEqual(code, 200, "previous workspace remains usable")

    def test_upload_rejects_changed_finish_without_replacing_dirty_session(self):
        self.post("/api/new")
        saved = deepcopy(self.saved)
        saved["approved_plan"]["project_finish"] += 1
        self.assert_upload_rejected(saved)

    def test_upload_rejects_malformed_stored_records_atomically(self):
        for location in ("approved_plan", "proposal", "plan_history"):
            for malformed in ([], {"entries": None}, "damaged"):
                with self.subTest(location=location, malformed=malformed):
                    saved = deepcopy(self.saved)
                    saved[location] = [malformed] if location == "plan_history" else malformed
                    self.assert_upload_rejected(saved)

    def test_upload_checks_physical_allocation_even_with_recomputed_hash(self):
        saved = deepcopy(self.saved)
        plan = saved["approved_plan"]
        entry = next(e for e in plan["entries"] if e["activity_id"] == "A03")
        entry["assignments"] = [["MECH", "M2"], ["SPECIALIST", "M2"]]
        plan["plan_hash"] = _plan_hash(plan)
        self.assert_upload_rejected(saved)

    def test_upload_rejects_invalid_history_and_snapshot_hash(self):
        for corruption in ("history", "snapshot"):
            with self.subTest(corruption=corruption):
                saved = deepcopy(self.recovery)
                if corruption == "history":
                    saved["plan_history"][0]["project_finish"] += 1
                else:
                    saved["approved_plan"]["source_state_hash"] = "wrong"
                    saved["approved_plan"]["plan_hash"] = _plan_hash(saved["approved_plan"])
                self.assert_upload_rejected(saved)

    def test_valid_stale_proposal_is_not_approvable_after_open(self):
        saved = deepcopy(self.stale)
        saved["proposal"] = deepcopy(self.saved["approved_plan"])
        saved["proposal"].pop("approved_by")
        saved["proposal"].pop("approved_at")
        code, _ = self.post("/api/open", {"workspace": saved})
        self.assertEqual(code, 200)
        self.assertEqual(self.state["proposal_status"], "STALE")
        code, _ = self.post("/api/approve", {"actor": "planner"})
        self.assertEqual(code, 400)

    def test_mutation_origin_host_and_content_type_are_exact_and_atomic(self):
        cases = [
            ({"Origin": self.base}, 200),
            ({}, 200),  # Explicit local non-browser policy: Origin may be absent.
            ({"Origin": f"http://127.0.0.1:{self.server.server_port + 1}"}, 403),
            ({"Origin": "null"}, 403),
            ({"Origin": self.base + "/path"}, 403),
            ({"Origin": self.base + ":bad"}, 403),
            ({"Origin": self.base.replace("http:", "https:")}, 403),
            ({"Host": "127.0.0.1:1"}, 403),
            ({"Host": "evil.example"}, 403),
            ({"Origin": self.base, "Content-Type": "text/plain"}, 415),
        ]
        for headers, expected in cases:
            with self.subTest(headers=headers):
                before = self.get_json("/api/state")["state"]
                request = Request(self.base + "/api/new", data=json.dumps({"revision": before["revision"]}).encode(),
                                  headers={"Content-Type": "application/json", **headers}, method="POST")
                try:
                    with self.opener.open(request, timeout=10) as response:
                        actual = response.status
                except HTTPError as error:
                    actual = error.code
                self.assertEqual(actual, expected)
                after = self.get_json("/api/state")["state"]
                if expected != 200:
                    self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
