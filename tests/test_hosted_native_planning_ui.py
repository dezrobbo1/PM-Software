from __future__ import annotations

import asyncio
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from starlette.requests import Request
from starlette.datastructures import Headers

from api.index import _origin_matches_https_host, action as http_action
from deterministic_scheduling_core.native_planning_ui.hosted import execute, initial_response
from deterministic_scheduling_core.native_planning_ui.server import (
    MAX_HOSTED_BODY_BYTES,
    MAX_WORKSPACE_BYTES,
)
from deterministic_scheduling_core.scheduling.planning_workspace import _plan_hash


class HostedNativePlanningUiTests(unittest.TestCase):
    def setUp(self):
        self.state = initial_response()["state"]

    def call(self, action, **payload):
        status, result = execute({
            "expected_revision": self.state["revision"],
            "state": {key: deepcopy(self.state[key]) for key in ("revision", "dirty", "source", "workspace")},
            "payload": {"action": action, **payload},
        })
        if "state" in result:
            self.state = result["state"]
        return status, result

    def http_call(self, body, *, origin="https://trial-abc.vercel.app", content_type="application/json"):
        raw = json.dumps(body).encode("utf-8")
        headers = [
            (b"host", b"trial-abc.vercel.app"),
            (b"origin", origin.encode("ascii")),
            (b"x-forwarded-proto", b"https"),
            (b"content-type", content_type.encode("ascii")),
            (b"content-length", str(len(raw)).encode("ascii")),
        ]
        delivered = False

        async def receive():
            nonlocal delivered
            if delivered:
                return {"type": "http.disconnect"}
            delivered = True
            return {"type": "http.request", "body": raw, "more_body": False}

        request = Request({
            "type": "http", "http_version": "1.1", "method": "POST",
            "scheme": "https", "path": "/api/planning", "raw_path": b"/api/planning",
            "query_string": b"", "headers": headers,
            "client": ("127.0.0.1", 12345), "server": ("trial-abc.vercel.app", 443),
        }, receive)
        response = asyncio.run(http_action(request))
        return response.status_code, json.loads(response.body)

    def test_stateless_calculate_and_authoritative_approve_round_trip(self):
        status, _ = self.call("calculate")
        self.assertEqual(status, 200)
        proposal = deepcopy(self.state["workspace"]["proposal"])
        self.assertEqual(proposal["selected_modes"]["A03"], "SPECIALIST")
        self.assertEqual(proposal["project_finish"], 30)
        self.assertEqual(proposal["physical_status"], "PROVEN_FEASIBLE")

        status, _ = self.call("approve", actor="hosted-planner")
        self.assertEqual(status, 200)
        self.assertEqual(self.state["workspace"]["approved_plan"]["plan_hash"], proposal["plan_hash"])
        self.assertIsNone(self.state["workspace"]["proposal"])

    def test_hosted_approval_rejects_client_rehashed_solver_output(self):
        self.call("calculate")
        submitted = deepcopy(self.state)
        submitted["workspace"]["proposal"]["solver"]["proof"] = "browser-authored claim"
        submitted["workspace"]["proposal"]["plan_hash"] = _plan_hash(submitted["workspace"]["proposal"])
        status, result = execute({
            "expected_revision": submitted["revision"],
            "state": {key: submitted[key] for key in ("revision", "dirty", "source", "workspace")},
            "payload": {"action": "approve", "actor": "hosted-planner"},
        })
        self.assertEqual(status, 400)
        self.assertIn("authoritative Python calculation", result["error"])
        self.assertIsNone(result["state"]["workspace"]["approved_plan"])

    def test_report_accept_and_recovery_are_complete_stateless_round_trips(self):
        self.call("calculate")
        self.call("approve", actor="hosted-planner")
        trusted_hash = self.state["trusted_input_hash"]
        approved_hash = self.state["workspace"]["approved_plan"]["plan_hash"]
        status, result = self.call(
            "report", resource_id="M2", start=20, finish=34,
            reporter="hosted-supervisor", reason="synthetic hosted outage",
        )
        self.assertEqual(status, 200)
        self.assertEqual(result["report_id"], "E001")
        self.assertEqual(self.state["trusted_input_hash"], trusted_hash)
        self.assertEqual(self.state["workspace"]["approved_plan"]["plan_hash"], approved_hash)
        self.call("accept", report_id="E001", actor="hosted-planner")
        self.assertEqual(self.state["approved_status"], "STALE")
        self.call("calculate")
        self.assertEqual(self.state["workspace"]["proposal"]["selected_modes"]["A03"], "NORMAL")
        self.assertEqual(self.state["workspace"]["proposal"]["project_finish"], 65)

    def test_failed_action_returns_original_submitted_workspace(self):
        self.call("calculate")
        self.call("approve", actor="hosted-planner")
        before = deepcopy(self.state)
        project = deepcopy(before["workspace"]["project"])
        project["activities"][0]["predecessors"] = ["MISSING"]
        status, result = self.call("project", project=project)
        self.assertEqual(status, 400)
        self.assertIn("unknown predecessor", result["error"])
        self.assertEqual(result["state"], before)

    def test_malformed_submitted_workspace_is_rejected_without_server_state(self):
        body = {
            "expected_revision": 0,
            "state": {"revision": 0, "dirty": False, "source": "test", "workspace": {"schema": "wrong"}},
            "payload": {"action": "calculate"},
        }
        status, result = execute(body)
        self.assertEqual(status, 400)
        self.assertIn("invalid submitted workspace state", result["error"])
        self.assertNotIn("state", result)

    def test_export_and_open_preserve_workspace_without_calculation(self):
        self.call("calculate")
        self.call("approve", actor="hosted-planner")
        self.call("report", resource_id="M2", start=20, finish=34,
                  reporter="hosted-supervisor", reason="synthetic hosted outage")
        self.call("accept", report_id="E001", actor="hosted-planner")
        self.call("calculate")
        self.call("approve", actor="hosted-planner")
        expected = deepcopy(self.state["workspace"])
        status, exported = self.call("export")
        self.assertEqual(status, 200)
        self.assertNotIn("workspace_json", exported)
        saved = deepcopy(exported["state"]["workspace"])
        self.assertEqual(saved, expected)
        self.call("new")
        with patch("deterministic_scheduling_core.native_planning_ui.hosted.propose",
                   side_effect=AssertionError("opening must not optimise")):
            status, _ = self.call("open", workspace=saved, filename=exported["filename"])
        self.assertEqual(status, 200)
        self.assertEqual(self.state["workspace"], expected)
        self.assertIsNone(self.state["workspace"]["proposal"])
        self.assertEqual(len(self.state["workspace"]["plan_history"]), 1)

    def test_near_limit_export_returns_workspace_once_below_hosted_response_limit(self):
        workspace = deepcopy(self.state["workspace"])
        workspace["reports"] = [
            {
                "id": f"E{index:06d}", "resource_id": "M2", "start": 20, "finish": 34,
                "reason": "x", "reported_by": "r", "reported_at": "s",
                "status": "REPORTED", "scheduling_role": "FORECAST_AVAILABILITY",
                "accepted_by": None, "accepted_at": None,
            }
            for index in range(8_800)
        ]
        body = {
            "expected_revision": self.state["revision"],
            "state": {
                "revision": self.state["revision"], "dirty": True,
                "source": "Near-limit export", "workspace": workspace,
            },
            "payload": {"action": "export"},
        }

        status, exported = self.http_call(body)

        self.assertEqual(status, 200)
        self.assertNotIn("workspace_json", exported)
        self.assertEqual(len(exported["state"]["workspace"]["reports"]), 8_800)
        self.assertFalse(exported["state"]["dirty"])
        response_bytes = len(json.dumps(exported, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
        self.assertLess(response_bytes, 9 * 1024 * 1024 // 2)
        duplicated = deepcopy(exported)
        duplicated["workspace_json"] = json.dumps(workspace, indent=2, ensure_ascii=False) + "\n"
        duplicated_bytes = len(json.dumps(duplicated, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
        self.assertGreater(duplicated_bytes, 9 * 1024 * 1024 // 2)

    def test_open_accepts_two_individually_bounded_workspaces_in_one_request(self):
        def expanded_workspace(marker):
            workspace = deepcopy(self.state["workspace"])
            workspace["reports"].append({
                "id": "E001", "resource_id": "M2", "start": 20, "finish": 34,
                "reason": marker + "x" * (3 * MAX_WORKSPACE_BYTES // 4),
                "reported_by": "hosted-size-regression", "reported_at": "synthetic",
                "status": "REPORTED", "scheduling_role": "FORECAST_AVAILABILITY",
                "accepted_by": None, "accepted_at": None,
            })
            return workspace

        current_workspace = expanded_workspace("current-")
        opened_workspace = expanded_workspace("opened-")
        body = {
            "expected_revision": self.state["revision"],
            "state": {
                "revision": self.state["revision"], "dirty": True,
                "source": "Current large workspace", "workspace": current_workspace,
            },
            "payload": {
                "action": "open", "workspace": opened_workspace,
                "filename": "selected-large-workspace.pm-workspace.json",
            },
        }
        wire_size = len(json.dumps(body).encode("utf-8"))
        self.assertGreater(wire_size, MAX_WORKSPACE_BYTES)
        self.assertLessEqual(wire_size, MAX_HOSTED_BODY_BYTES)

        with patch("deterministic_scheduling_core.native_planning_ui.hosted.propose",
                   side_effect=AssertionError("opening must not optimise")):
            status, result = self.http_call(body)

        self.assertEqual(status, 200, result.get("error"))
        self.assertEqual(result["state"]["workspace"], opened_workspace)
        self.assertEqual(result["state"]["source"], "selected-large-workspace.pm-workspace.json")
        self.assertEqual(result["state"]["revision"], self.state["revision"] + 1)

    def test_open_still_rejects_one_workspace_above_individual_limit_atomically(self):
        oversized = deepcopy(self.state["workspace"])
        oversized["reports"].append({
            "id": "E001", "resource_id": "M2", "start": 20, "finish": 34,
            "reason": "x" * MAX_WORKSPACE_BYTES,
            "reported_by": "hosted-size-regression", "reported_at": "synthetic",
            "status": "REPORTED", "scheduling_role": "FORECAST_AVAILABILITY",
            "accepted_by": None, "accepted_at": None,
        })
        body = {
            "expected_revision": self.state["revision"],
            "state": {key: deepcopy(self.state[key]) for key in ("revision", "dirty", "source", "workspace")},
            "payload": {"action": "open", "workspace": oversized, "filename": "too-large.json"},
        }
        before = deepcopy(body["state"])
        self.assertLessEqual(len(json.dumps(body).encode("utf-8")), MAX_HOSTED_BODY_BYTES)

        status, result = self.http_call(body)

        self.assertEqual(status, 400)
        self.assertIn("save/reopen size limit", result["error"])
        self.assertEqual(
            {key: result["state"][key] for key in ("revision", "dirty", "source", "workspace")},
            before,
        )

    def test_independent_initial_states_do_not_share_process_memory(self):
        first = initial_response()["state"]
        second = initial_response()["state"]
        first["workspace"]["project"]["name"] = "changed in one browser"
        self.assertNotEqual(first["workspace"], second["workspace"])
        self.assertEqual(second["workspace"]["project"]["name"], "Editable native repair plan")

    def test_independent_native_case_uses_existing_resource_and_mode_policy(self):
        self.call("new")
        project = deepcopy(self.state["workspace"]["project"])
        by_id = {activity["id"]: activity for activity in project["activities"]}
        for identifier, predecessors in {
            "N01": [], "N02": ["N01"], "N03": ["N01"], "N04": ["N02", "N03"],
            "N05": ["N02"], "N06": ["N04", "N05"], "N07": ["N06"], "N08": ["N07"],
        }.items():
            by_id[identifier]["predecessors"] = predecessors
            by_id[identifier]["name"] = f"Hosted independent {identifier}"
        mech = {"id": "MECH", "pool_ids": ["MECH"], "eligible_resource_ids": ["M1", "M2"]}
        rigger = {"id": "RIGGER", "pool_ids": ["RIGGER"], "eligible_resource_ids": ["R1", "R2"]}
        for identifier in ("N02", "N03"):
            by_id[identifier]["modes"][0].update(processing_ticks=6, requirements=[deepcopy(mech)])
        by_id["N05"]["modes"][0].update(processing_ticks=4, requirements=[rigger])
        by_id["N06"]["modes"].append({
            "id": "QUICK", "processing_ticks": 1, "calendar_id": "DAY",
            "continuity": "SUSPENDABLE_AT_AVAILABILITY_GAPS", "requirements": [],
        })
        status, result = self.call("project", project=project)
        self.assertEqual(status, 200, result.get("error"))
        status, result = self.call("calculate")
        self.assertEqual(status, 200, result.get("error"))
        plan = self.state["workspace"]["proposal"]
        entries = {entry["activity_id"]: entry for entry in plan["entries"]}
        self.assertEqual(plan["physical_status"], "PROVEN_FEASIBLE")
        self.assertEqual(plan["selected_modes"]["N06"], "QUICK")
        self.assertEqual(
            len({dict(entries[identifier]["assignments"])["MECH"] for identifier in ("N02", "N03")}),
            2,
        )
        self.assertEqual(len(entries["N05"]["periods"]), 2)

    def test_revision_mismatch_is_atomic(self):
        before = deepcopy(self.state)
        status, result = execute({
            "expected_revision": 99,
            "state": {key: deepcopy(before[key]) for key in ("revision", "dirty", "source", "workspace")},
            "payload": {"action": "new"},
        })
        self.assertEqual(status, 409)
        self.assertEqual(result["state"], before)

    def test_https_same_origin_check_is_exact(self):
        def headers(host="trial-abc.vercel.app", origin="https://trial-abc.vercel.app", proto="https"):
            return Headers({"Host": host, "Origin": origin, "X-Forwarded-Proto": proto})

        self.assertTrue(_origin_matches_https_host(headers()))
        self.assertFalse(_origin_matches_https_host(headers(origin="https://trial-abc.vercel.app:444")))
        self.assertFalse(_origin_matches_https_host(headers(origin="http://trial-abc.vercel.app", proto="http")))
        self.assertFalse(_origin_matches_https_host(Headers({
            "Host": "trial-abc.vercel.app", "X-Forwarded-Proto": "https",
        })))

    def test_https_same_origin_json_mutation_reaches_stateless_adapter(self):
        status, result = self.http_call({
            "expected_revision": self.state["revision"],
            "state": {key: deepcopy(self.state[key]) for key in ("revision", "dirty", "source", "workspace")},
            "payload": {"action": "calculate"},
        })
        self.assertEqual(status, 200)
        self.assertEqual(result["state"]["workspace"]["proposal"]["project_finish"], 30)
        self.assertGreaterEqual(result["runtime"]["server_elapsed_ms"], 0)

    def test_foreign_origin_and_non_json_requests_are_rejected_without_mutation(self):
        body = {
            "expected_revision": self.state["revision"],
            "state": {key: deepcopy(self.state[key]) for key in ("revision", "dirty", "source", "workspace")},
            "payload": {"action": "new"},
        }
        before = deepcopy(body)
        status, result = self.http_call(body, origin="https://other.example")
        self.assertEqual(status, 403)
        self.assertEqual(body, before)
        self.assertNotIn("state", result)

        status, result = self.http_call(body, content_type="text/plain")
        self.assertEqual(status, 415)
        self.assertEqual(body, before)
        self.assertNotIn("state", result)

        status, result = self.http_call(body)
        self.assertEqual(status, 200)
        self.assertEqual(result["state"]["revision"], self.state["revision"] + 1)


if __name__ == "__main__":
    unittest.main()
