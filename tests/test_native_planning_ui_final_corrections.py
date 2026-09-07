from __future__ import annotations

from copy import deepcopy
from http.cookiejar import CookieJar
import json
from threading import Thread
import unittest
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener

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


if __name__ == "__main__":
    unittest.main()
