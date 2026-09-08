"""Stateless request boundary for the hosted native-planning trial.

Every call receives the complete current browser state and returns a complete
replacement.  Vercel function instances therefore hold no authoritative
workspace state between invocations.
"""
from __future__ import annotations

from copy import deepcopy
from http import HTTPStatus
from typing import Any

from deterministic_scheduling_core.errors import SchedulingError
from deterministic_scheduling_core.project.planning_workspace import validate
from deterministic_scheduling_core.scheduling.planning_workspace import (
    propose,
    validate_plan,
    validate_stored_plans,
)

from .server import BrowserSession, _validate_trial_size, _view, dispatch_action

_ACTIONS = {
    "load-example",
    "new",
    "open",
    "project",
    "invalidate-proposal",
    "calculate",
    "approve",
    "report",
    "accept",
    "export",
}
_ACTION_FIELDS = {
    "load-example": {"action"},
    "new": {"action"},
    "open": {"action", "workspace", "filename"},
    "project": {"action", "project"},
    "invalidate-proposal": {"action"},
    "calculate": {"action"},
    "approve": {"action", "actor"},
    "report": {"action", "resource_id", "start", "finish", "reporter", "reason"},
    "accept": {"action", "report_id", "actor"},
    "export": {"action"},
}
_OPTIONAL_ACTION_FIELDS = {"open": {"filename"}}


def initial_response() -> dict[str, Any]:
    """Return unsolved example inputs without consulting process state."""
    return {"ok": True, "state": _view(BrowserSession())}


def _session_from_request(value: Any) -> BrowserSession:
    if not isinstance(value, dict) or set(value) != {"revision", "dirty", "source", "workspace"}:
        raise ValueError("state must contain exactly revision, dirty, source and workspace")
    revision = value["revision"]
    dirty = value["dirty"]
    source = value["source"]
    if type(revision) is not int or revision < 0:
        raise ValueError("state revision must be a non-negative integer")
    if type(dirty) is not bool:
        raise ValueError("state dirty must be true or false")
    if not isinstance(source, str) or not source.strip() or len(source) > 120:
        raise ValueError("state source must be a non-empty string of at most 120 characters")
    workspace = deepcopy(value["workspace"])
    validate(workspace)
    _validate_trial_size(workspace)
    validate_stored_plans(workspace)
    return BrowserSession(workspace=workspace, revision=revision, dirty=dirty, source=source)


def _replace_browser_proposal_with_authoritative_result(session: BrowserSession) -> None:
    """Re-solve before hosted approval; client output is never authoritative."""
    supplied = session.workspace.get("proposal")
    if supplied is None:
        raise ValueError("approval needs an actor and a calculated proposal")
    validate_plan(session.workspace, supplied)
    recalculated = deepcopy(session.workspace)
    recalculated["proposal"] = None
    authoritative = propose(recalculated)
    if authoritative["plan_hash"] != supplied["plan_hash"]:
        raise ValueError("proposal differs from the authoritative Python calculation; calculate again")
    session.workspace["proposal"] = authoritative


def execute(body: Any) -> tuple[int, dict[str, Any]]:
    """Validate and atomically execute one stateless hosted action."""
    if not isinstance(body, dict) or set(body) != {"expected_revision", "state", "payload"}:
        return HTTPStatus.BAD_REQUEST, {
            "ok": False,
            "error": "request must contain exactly expected_revision, state and payload",
        }
    try:
        session = _session_from_request(body["state"])
    except (AttributeError, IndexError, KeyError, TypeError, ValueError) as exc:
        return HTTPStatus.BAD_REQUEST, {"ok": False, "error": f"invalid submitted workspace state: {exc}"}

    original = _view(session)
    expected_revision = body["expected_revision"]
    if type(expected_revision) is not int or expected_revision != session.revision:
        return HTTPStatus.CONFLICT, {
            "ok": False,
            "error": "workspace revision changed before this action; the browser draft was retained",
            "state": original,
        }
    payload = body["payload"]
    if not isinstance(payload, dict):
        return HTTPStatus.BAD_REQUEST, {"ok": False, "error": "payload must be a JSON object", "state": original}
    action = payload.get("action")
    required = _ACTION_FIELDS.get(action, set()) - _OPTIONAL_ACTION_FIELDS.get(action, set())
    if action not in _ACTIONS or not required <= set(payload) <= _ACTION_FIELDS[action]:
        return HTTPStatus.BAD_REQUEST, {"ok": False, "error": "unknown or malformed hosted action", "state": original}

    candidate = BrowserSession(
        workspace=deepcopy(session.workspace),
        revision=session.revision,
        dirty=session.dirty,
        source=session.source,
    )
    try:
        if action == "approve":
            _replace_browser_proposal_with_authoritative_result(candidate)
        result = dispatch_action(f"/api/{action}", payload, candidate)
        # The complete authoritative workspace is already returned in state.
        # Repeating its indented JSON as a string can push an otherwise valid
        # near-limit export over Vercel's function response-size limit.
        if action == "export":
            result.pop("workspace_json", None)
    except (AttributeError, IndexError, KeyError, TypeError, ValueError, SchedulingError) as exc:
        status = HTTPStatus.UNPROCESSABLE_ENTITY if isinstance(exc, SchedulingError) else HTTPStatus.BAD_REQUEST
        return status, {"ok": False, "error": str(exc), "state": original}
    return HTTPStatus.OK, {"ok": True, "state": _view(candidate), **result}
