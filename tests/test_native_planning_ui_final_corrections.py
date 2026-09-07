from __future__ import annotations

from copy import deepcopy
from http.cookiejar import CookieJar
import json
from threading import Thread
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener

from deterministic_scheduling_core.native_planning_ui import server as ui_server
from deterministic_scheduling_core.native_planning_ui.server import create_server


class NativePlanningUiFinalCorrectionsTests(unittest.TestCase):
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

    def post(self, path, payload=None):
        body = {"revision": self.state["revision"], **(payload or {})}
        request = Request(
            self.base + path,
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "Origin": self.base},
            method="POST",
        )
        try:
            with self.opener.open(request, timeout=30) as response:
                result = json.loads(response.read())
                self.state = result["state"]
                return response.status, result
        except HTTPError as error:
            result = json.loads(error.read())
            if "state" in result:
                self.state = result["state"]
            return error.code, result

    def assert_unchanged(self, before):
        self.assertEqual(self.state["revision"], before["revision"])
        self.assertEqual(self.state["workspace"], before["workspace"])
        self.assertEqual(self.state["dirty"], before["dirty"])

    def test_open_rejects_resource_without_capabilities_before_adoption(self):
        before = deepcopy(self.state)
        workspace = deepcopy(before["workspace"])
        workspace["project"]["resources"].append({"id": "UNUSED", "calendar_id": "DAY"})

        status, result = self.post("/api/open", {"workspace": workspace, "filename": "missing-capabilities.json"})

        self.assertEqual(status, 400)
        self.assertIn("at least one explicit capability", result["error"])
        self.assert_unchanged(before)

    def test_project_replacement_rejects_resource_without_capabilities_before_adoption(self):
        before = deepcopy(self.state)
        project = deepcopy(before["workspace"]["project"])
        project["resources"].append({"id": "UNUSED", "calendar_id": "DAY"})

        status, result = self.post("/api/project", {"project": project})

        self.assertEqual(status, 400)
        self.assertIn("at least one explicit capability", result["error"])
        self.assert_unchanged(before)

    def test_open_and_project_replacement_enforce_whole_day_horizon_limit(self):
        for horizon in (49, 15 * 48):
            with self.subTest(horizon=horizon, route="open"):
                before = deepcopy(self.state)
                workspace = deepcopy(before["workspace"])
                workspace["project"]["horizon_ticks"] = horizon
                status, result = self.post("/api/open", {"workspace": workspace, "filename": "bad-horizon.json"})
                self.assertEqual(status, 400)
                self.assertIn("1 to 14 whole relative days", result["error"])
                self.assert_unchanged(before)

            with self.subTest(horizon=horizon, route="project"):
                before = deepcopy(self.state)
                project = deepcopy(before["workspace"]["project"])
                project["horizon_ticks"] = horizon
                status, result = self.post("/api/project", {"project": project})
                self.assertEqual(status, 400)
                self.assertIn("1 to 14 whole relative days", result["error"])
                self.assert_unchanged(before)

    def test_open_and_project_reject_string_requirement_collections_before_adoption(self):
        for field in ("pool_ids", "eligible_resource_ids"):
            for route in ("open", "project"):
                with self.subTest(field=field, route=route):
                    before = deepcopy(self.state)
                    project = deepcopy(before["workspace"]["project"])
                    project["resources"].append({"id": "X", "capabilities": ["Q"], "calendar_id": "DAY"})
                    requirement = project["activities"][1]["modes"][0]["requirements"][0]
                    requirement["pool_ids"] = ["Q"]
                    requirement["eligible_resource_ids"] = ["X"]
                    requirement[field] = "Q" if field == "pool_ids" else "X"

                    if route == "open":
                        workspace = deepcopy(before["workspace"])
                        workspace["project"] = project
                        status, result = self.post("/api/open", {"workspace": workspace, "filename": "string-collection.json"})
                    else:
                        status, result = self.post("/api/project", {"project": project})

                    self.assertEqual(status, 400)
                    self.assertIn("non-empty JSON array of strings", result["error"])
                    self.assert_unchanged(before)

    def test_open_and_project_bound_assignment_combinations_before_calculation(self):
        status, result = self.post("/api/new")
        self.assertEqual(status, 200, result.get("error"))
        project = deepcopy(self.state["workspace"]["project"])
        resource_ids = [f"R{index}" for index in range(8)]
        project["resources"] = [
            {"id": resource_id, "capabilities": ["X"], "calendar_id": "DAY"}
            for resource_id in resource_ids
        ]
        project["activities"][0]["modes"][0]["requirements"] = [
            {"id": f"SLOT{index}", "pool_ids": ["X"], "eligible_resource_ids": list(resource_ids)}
            for index in range(4)
        ]

        for route in ("project", "open"):
            with self.subTest(route=route):
                before = deepcopy(self.state)
                if route == "project":
                    status, result = self.post("/api/project", {"project": project})
                else:
                    workspace = deepcopy(before["workspace"])
                    workspace["project"] = project
                    status, result = self.post("/api/open", {"workspace": workspace, "filename": "too-many-assignments.json"})
                self.assertEqual(status, 400)
                self.assertIn("64 physical assignment combinations", result["error"])
                self.assert_unchanged(before)

    def test_saved_workspace_with_historical_extra_resource_reopens(self):
        workspace = deepcopy(self.state["workspace"])
        del workspace["project"]["activities"][0]["modes"][0]["requirements"]
        workspace["project"]["resources"].append({"id": "crew:1", "capabilities": ["MECH"], "calendar_id": "DAY"})
        status, result = self.post("/api/open", {"workspace": workspace, "filename": "optional.json"})
        self.assertEqual(status, 200, result.get("error"))
        self.post("/api/calculate")
        self.post("/api/approve", {"actor": "trial-planner"})

        project = deepcopy(self.state["workspace"]["project"])
        project["activities"][0]["modes"][0]["requirements"] = []
        project["resources"] = [resource for resource in project["resources"] if resource["id"] != "crew:1"]
        status, result = self.post("/api/project", {"project": project})
        self.assertEqual(status, 200, result.get("error"))
        self.post("/api/calculate")
        status, exported = self.post("/api/export")
        self.assertEqual(status, 200, exported.get("error"))
        saved = json.loads(exported["workspace_json"])

        self.post("/api/new")
        status, result = self.post("/api/open", {"workspace": saved, "filename": "optional-reopened.json"})
        self.assertEqual(status, 200, result.get("error"))
        self.assertEqual(self.state["workspace"], saved)

    def test_history_growth_stops_before_save_becomes_unreopenable(self):
        status, result = self.post("/api/calculate")
        self.assertEqual(status, 200, result.get("error"))
        status, result = self.post("/api/approve", {"actor": "trial-planner"})
        self.assertEqual(status, 200, result.get("error"))
        # Exercise real solves/approvals with a smaller transport budget so the
        # regression reaches the boundary without hundreds of solver calls.
        limit = 3 * len(json.dumps(self.state["workspace"]).encode()) + 4096
        with patch.object(ui_server, "MAX_BODY_BYTES", limit):
            stopped = False
            for _ in range(12):
                for route, payload in (("/api/calculate", {}), ("/api/approve", {"actor": "trial-planner"})):
                    before = deepcopy(self.state)
                    status, result = self.post(route, payload)
                    if status == 400:
                        self.assertIn("save/reopen size limit", result["error"])
                        self.assertEqual(self.state, before)
                        stopped = True
                        break
                    self.assertEqual(status, 200, result.get("error"))
                if stopped:
                    break
            self.assertTrue(stopped, "history growth must stop before producing an unreopenable save")
            self.assertGreater(len(self.state["workspace"]["plan_history"]), 0)
            retained = deepcopy(self.state["workspace"])
            status, exported = self.post("/api/export")
            self.assertEqual(status, 200, exported.get("error"))
            saved = json.loads(exported["workspace_json"])
            self.assertEqual(saved, retained)
            status, result = self.post("/api/new")
            self.assertEqual(status, 200, result.get("error"))
            # Include renamed Unicode filename metadata, not just workspace size.
            payload = {"workspace": saved, "filename": "é" * 100 + ".json"}
            wire = json.dumps({"revision": self.state["revision"], **payload}).encode()
            self.assertLessEqual(len(wire), limit)
            with patch.object(ui_server, "propose", side_effect=AssertionError("open must not solve")):
                status, result = self.post("/api/open", payload)
            self.assertEqual(status, 200, result.get("error"))
            self.assertEqual(self.state["workspace"], retained)
            self.assertFalse(self.state["dirty"])

    def test_approval_size_overflow_preserves_proposal_and_revision(self):
        status, result = self.post("/api/calculate")
        self.assertEqual(status, 200, result.get("error"))
        before = deepcopy(self.state)
        reopen_body = {
            "workspace": before["workspace"],
            "filename": f"{before['workspace']['project']['id']}.pm-workspace.json",
        }
        limit = len(json.dumps(reopen_body).encode()) + 4096 + 16
        with patch.object(ui_server, "MAX_BODY_BYTES", limit):
            status, result = self.post("/api/approve", {"actor": "planner-" + "x" * 512})
        self.assertEqual(status, 400)
        self.assertIn("save/reopen size limit", result["error"])
        self.assertEqual(self.state, before)
        status, result = self.post("/api/approve", {"actor": "trial-planner"})
        self.assertEqual(status, 200, result.get("error"))
        self.assertIsNotNone(self.state["workspace"]["approved_plan"])

    def test_export_above_real_two_mib_limit_does_not_claim_saved(self):
        status, result = self.post("/api/calculate")
        self.assertEqual(status, 200, result.get("error"))
        status, result = self.post("/api/approve", {"actor": "trial-planner"})
        self.assertEqual(status, 200, result.get("error"))
        # Model oversized in-memory history from an older build. Normal history
        # growth is exercised through actual HTTP calculations/approvals above.
        session = next(iter(self.server.sessions._sessions.values()))
        record = session.workspace["approved_plan"]
        copies = ui_server.MAX_BODY_BYTES // len(json.dumps(record).encode()) + 2
        with session.lock:
            session.workspace["plan_history"] = [deepcopy(record) for _ in range(copies)]
            session.dirty = True
        self.state = self.get_json("/api/state")["state"]
        before = deepcopy(self.state)
        self.assertGreater(len(json.dumps(before["workspace"]).encode()), 2 * 1024 * 1024)
        status, result = self.post("/api/export")
        self.assertEqual(status, 400)
        self.assertIn("save/reopen size limit", result["error"])
        self.assertNotIn("workspace_json", result)
        self.assertEqual(self.state, before)
        self.assertTrue(self.state["dirty"])


if __name__ == "__main__":
    unittest.main()
