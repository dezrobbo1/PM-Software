"""Small dependency-free loopback service for the native planning trial."""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import secrets
from pathlib import Path
from threading import RLock
from typing import Any
from urllib.parse import urlsplit

from deterministic_scheduling_core.errors import SchedulingError
from deterministic_scheduling_core.project.planning_workspace import (
    Workspace,
    accept_report,
    digest,
    new_blank_workspace,
    new_demo_workspace,
    replace_project,
    report_unavailable,
    state_hash,
    trusted_input,
    validate,
)
from deterministic_scheduling_core.scheduling.planning_workspace import approve, propose

MAX_BODY_BYTES = 2 * 1024 * 1024
ASSET_DIR = Path(__file__).parent


def _plan_status(workspace: Workspace, plan: dict | None) -> str:
    if plan is None:
        return "NONE"
    return "CURRENT" if plan.get("source_state_hash") == state_hash(workspace) and plan.get("source_snapshot") == trusted_input(workspace) else "STALE"


def _comparison(workspace: Workspace) -> dict[str, Any] | None:
    old = workspace.get("approved_plan")
    new = workspace.get("proposal")
    if not old or not new:
        return None
    old_entries = {entry["activity_id"]: entry for entry in old["entries"]}
    new_entries = {entry["activity_id"]: entry for entry in new["entries"]}
    changed_modes, changed_assignments, changed_periods, unchanged = [], [], [], []
    activity_ids = list(old["selected_modes"])
    activity_ids.extend(activity_id for activity_id in new["selected_modes"] if activity_id not in old["selected_modes"])
    for activity_id in activity_ids:
        old_entry, new_entry = old_entries.get(activity_id), new_entries.get(activity_id)
        mode_changed = old["selected_modes"].get(activity_id) != new["selected_modes"].get(activity_id)
        assignment_changed = old_entry != new_entry and (old_entry is None or new_entry is None or old_entry["assignments"] != new_entry["assignments"])
        period_changed = old_entry != new_entry and (old_entry is None or new_entry is None or old_entry["periods"] != new_entry["periods"])
        if mode_changed:
            changed_modes.append({"activity_id": activity_id, "old": old["selected_modes"].get(activity_id), "new": new["selected_modes"].get(activity_id)})
        if assignment_changed:
            changed_assignments.append({"activity_id": activity_id, "old": old_entry["assignments"], "new": new_entry["assignments"]})
        if period_changed:
            changed_periods.append({"activity_id": activity_id, "old": old_entry["periods"], "new": new_entry["periods"]})
        if old_entry is not None and new_entry is not None and not mode_changed and not assignment_changed and not period_changed:
            unchanged.append(activity_id)
    return {
        "old_finish": old["project_finish"],
        "new_finish": new["project_finish"],
        "changed_modes": changed_modes,
        "changed_assignments": changed_assignments,
        "changed_periods": changed_periods,
        "unchanged_activity_ids": unchanged,
    }


def _view(session: "BrowserSession") -> dict[str, Any]:
    workspace = deepcopy(session.workspace)
    return {
        "revision": session.revision,
        "dirty": session.dirty,
        "source": session.source,
        "trusted_input_hash": state_hash(workspace),
        "approved_status": _plan_status(workspace, workspace.get("approved_plan")),
        "proposal_status": _plan_status(workspace, workspace.get("proposal")),
        "comparison": _comparison(workspace),
        "workspace": workspace,
    }


def _validate_trial_size(workspace: Workspace) -> None:
    count = len(workspace["project"]["activities"])
    if not 8 <= count <= 15:
        raise ValueError("the browser trial supports projects with 8 to 15 activities")


def _body_integer(body: dict[str, Any], key: str) -> int:
    value = body[key]
    if type(value) is not int:
        raise ValueError(f"{key} must be an integer number of 30-minute ticks")
    return value


@dataclass
class BrowserSession:
    workspace: Workspace = field(default_factory=new_demo_workspace)
    revision: int = 0
    dirty: bool = False
    source: str = "Built-in example"
    lock: RLock = field(default_factory=RLock)


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, BrowserSession] = {}
        self._lock = RLock()

    def get(self, session_id: str | None) -> tuple[str, BrowserSession, bool]:
        with self._lock:
            if session_id and session_id in self._sessions:
                return session_id, self._sessions[session_id], False
            session_id = secrets.token_urlsafe(24)
            session = BrowserSession()
            self._sessions[session_id] = session
            return session_id, session, True


class TrialServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, server_address: tuple[str, int], handler: type[BaseHTTPRequestHandler]):
        super().__init__(server_address, handler)
        self.sessions = SessionStore()


class TrialHandler(BaseHTTPRequestHandler):
    server: TrialServer

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} - {format % args}")

    def _headers(self, status: int, content_type: str, length: int, session_id: str | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        if session_id:
            self.send_header("Set-Cookie", f"pm_trial_session={session_id}; HttpOnly; SameSite=Strict; Path=/")
        self.end_headers()

    def _json(self, value: Any, status: int = HTTPStatus.OK, session_id: str | None = None) -> None:
        body = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
        self._headers(status, "application/json; charset=utf-8", len(body), session_id)
        self.wfile.write(body)

    def _error(self, message: str, status: int, session: BrowserSession | None = None, session_id: str | None = None) -> None:
        value: dict[str, Any] = {"ok": False, "error": message}
        if session:
            value["state"] = _view(session)
        self._json(value, status, session_id)

    def _safe_request(self) -> bool:
        host = self.headers.get("Host", "").split(":", 1)[0].strip("[]")
        if host not in {"127.0.0.1", "localhost"}:
            self._error("this trial server accepts loopback requests only", HTTPStatus.FORBIDDEN)
            return False
        origin = self.headers.get("Origin")
        if origin and urlsplit(origin).hostname not in {"127.0.0.1", "localhost"}:
            self._error("cross-origin requests are not accepted", HTTPStatus.FORBIDDEN)
            return False
        return True

    def _session(self) -> tuple[str, BrowserSession, bool]:
        session_id = None
        for cookie in self.headers.get("Cookie", "").split(";"):
            key, _, value = cookie.strip().partition("=")
            if key == "pm_trial_session":
                session_id = value
        return self.server.sessions.get(session_id)

    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("invalid content length") from exc
        if length <= 0 or length > MAX_BODY_BYTES:
            raise ValueError("request body must be present and no larger than 2 MiB")
        try:
            value = json.loads(self.rfile.read(length))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("request body must be valid JSON") from exc
        if not isinstance(value, dict):
            raise ValueError("request body must be a JSON object")
        return value

    def do_GET(self) -> None:
        if not self._safe_request():
            return
        path = urlsplit(self.path).path
        session_id, session, created = self._session()
        if path == "/api/state":
            with session.lock:
                self._json({"ok": True, "state": _view(session)}, session_id=session_id if created else None)
            return
        if path == "/favicon.ico":
            self._headers(HTTPStatus.NO_CONTENT, "image/x-icon", 0, session_id if created else None)
            return
        assets = {
            "/": ("index.html", "text/html; charset=utf-8"),
            "/index.html": ("index.html", "text/html; charset=utf-8"),
            "/app.js": ("app.js", "text/javascript; charset=utf-8"),
            "/styles.css": ("styles.css", "text/css; charset=utf-8"),
        }
        if path not in assets:
            self._error("not found", HTTPStatus.NOT_FOUND, session_id=session_id if created else None)
            return
        filename, content_type = assets[path]
        body = (ASSET_DIR / filename).read_bytes()
        self._headers(HTTPStatus.OK, content_type, len(body), session_id if created else None)
        self.wfile.write(body)

    def do_POST(self) -> None:
        if not self._safe_request():
            return
        session_id, session, created = self._session()
        try:
            body = self._read_json()
        except ValueError as exc:
            self._error(str(exc), HTTPStatus.BAD_REQUEST, session, session_id if created else None)
            return
        path = urlsplit(self.path).path
        with session.lock:
            if body.get("revision") != session.revision:
                self._error("workspace changed in another request; review the current state and try again", HTTPStatus.CONFLICT, session, session_id if created else None)
                return
            before = digest(session.workspace)
            try:
                payload = self._dispatch(path, body, session)
            except (KeyError, TypeError, ValueError, SchedulingError) as exc:
                if digest(session.workspace) != before:
                    session.revision += 1
                    session.dirty = True
                status = HTTPStatus.UNPROCESSABLE_ENTITY if isinstance(exc, SchedulingError) else HTTPStatus.BAD_REQUEST
                self._error(str(exc), status, session, session_id if created else None)
                return
            self._json({"ok": True, "state": _view(session), **payload}, session_id=session_id if created else None)

    def _dispatch(self, path: str, body: dict[str, Any], session: BrowserSession) -> dict[str, Any]:
        dirty = True
        payload: dict[str, Any] = {}
        if path == "/api/load-example":
            session.workspace = new_demo_workspace()
            session.source = "Built-in example"
            dirty = False
        elif path == "/api/new":
            session.workspace = new_blank_workspace()
            session.source = "New unsaved project"
        elif path == "/api/open":
            workspace = deepcopy(body["workspace"])
            validate(workspace)
            _validate_trial_size(workspace)
            session.workspace = workspace
            session.source = str(body.get("filename") or "Opened workspace")[:120]
            dirty = False
        elif path == "/api/project":
            candidate = deepcopy(session.workspace)
            replace_project(candidate, body["project"])
            _validate_trial_size(candidate)
            session.workspace = candidate
        elif path == "/api/invalidate-proposal":
            if session.workspace.get("proposal") is not None:
                session.workspace["proposal"] = None
            else:
                dirty = session.dirty
        elif path == "/api/calculate":
            propose(session.workspace)
        elif path == "/api/approve":
            approve(session.workspace, str(body.get("actor", "")))
        elif path == "/api/report":
            report_id = report_unavailable(
                session.workspace,
                str(body["resource_id"]),
                _body_integer(body, "start"),
                _body_integer(body, "finish"),
                str(body.get("reporter", "")),
                str(body.get("reason", "")),
            )
            payload["report_id"] = report_id
        elif path == "/api/accept":
            accept_report(session.workspace, str(body["report_id"]), str(body.get("actor", "")))
        elif path == "/api/export":
            validate(session.workspace)
            payload["filename"] = f"{session.workspace['project']['id']}.pm-workspace.json"
            payload["workspace_json"] = json.dumps(session.workspace, indent=2, ensure_ascii=False) + "\n"
            dirty = False
        else:
            raise ValueError("unknown API action")
        session.revision += 1
        session.dirty = dirty
        return payload


def create_server(port: int = 8765) -> TrialServer:
    """Create a loopback-only server; port zero requests an ephemeral port."""
    return TrialServer(("127.0.0.1", port), TrialHandler)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the PM-Software native planning trial UI on loopback")
    parser.add_argument("--port", type=int, default=8765, help="loopback port (default: 8765)")
    args = parser.parse_args(argv)
    server = create_server(args.port)
    address = f"http://127.0.0.1:{server.server_port}"
    print(f"PM-Software native planning trial: {address}", flush=True)
    print("Press Ctrl+C to stop. Workspace persistence uses browser download/upload.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping native planning trial.", flush=True)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
