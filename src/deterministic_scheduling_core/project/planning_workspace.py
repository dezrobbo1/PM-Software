"""Small native JSON workspace. No external-format or solver types live here."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

SCHEMA = "pm-native-planning-workspace/0"
POLICY = "finish-mode-preservation-start-movement-assignment-preservation-timing/0"
Workspace = dict[str, Any]


def digest(value: Any) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _integer(value: Any, label: str, minimum: int = 0) -> None:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{label} must be an integer >= {minimum}")


def _ids(items: list[dict], label: str) -> set[str]:
    ids = [item["id"] for item in items]
    if any(not isinstance(item, str) or not item.strip() for item in ids) or len(ids) != len(set(ids)):
        raise ValueError(f"{label} IDs must be nonempty and unique")
    return set(ids)


def validate(workspace: Workspace) -> None:
    """Validate the deliberately small editable input, not a general project schema."""
    if workspace.get("schema") != SCHEMA:
        raise ValueError(f"expected schema {SCHEMA}")
    project = workspace["project"]
    allowed = {"id", "name", "horizon_ticks", "calendars", "resources", "activities", "objective_activity_id", "pool_riggers"}
    if set(project) - allowed:
        raise ValueError(f"unsupported project fields: {sorted(set(project) - allowed)}")
    horizon = project["horizon_ticks"]
    _integer(horizon, "horizon_ticks", 1)
    if not project["activities"]:
        raise ValueError("project needs activities")
    calendars = _ids(project["calendars"], "calendar")
    resources = _ids(project["resources"], "resource")
    activities = _ids(project["activities"], "activity")
    for calendar in project["calendars"]:
        for start, finish in calendar["daily_windows"]:
            _integer(start, "calendar start")
            _integer(finish, "calendar finish", 1)
            if not start < finish <= 48:
                raise ValueError("calendar windows must lie within a 48-tick day")
    for resource in project["resources"]:
        if resource["calendar_id"] not in calendars or resource.get("capacity", 1) != 1:
            raise ValueError("this workspace supports known calendars and capacity-one physical resources")
    by_resource = {resource["id"]: resource for resource in project["resources"]}
    for activity in project["activities"]:
        if set(activity) - {"id", "name", "modes", "predecessors", "not_before"}:
            raise ValueError(f"unsupported activity fields on {activity['id']}")
        if not activity["modes"]:
            raise ValueError("each activity needs an authorised mode")
        _ids(activity["modes"], "mode")
        _integer(activity.get("not_before", 0), "not_before")
        if not set(activity.get("predecessors", [])) <= activities:
            raise ValueError("unknown predecessor")
        for mode in activity["modes"]:
            if set(mode) - {"id", "processing_ticks", "calendar_id", "continuity", "requirements"}:
                raise ValueError(f"unsupported mode fields on {activity['id']}/{mode['id']}")
            _integer(mode["processing_ticks"], "processing_ticks")
            if mode["calendar_id"] not in calendars:
                raise ValueError("unknown mode calendar")
            if mode.get("continuity", "SUSPENDABLE_AT_AVAILABILITY_GAPS") not in {"CONTINUOUS", "SUSPENDABLE_AT_AVAILABILITY_GAPS"}:
                raise ValueError("unsupported continuity rule")
            requirements = mode.get("requirements", [])
            _ids(requirements, "requirement")
            if requirements and not mode["processing_ticks"]:
                raise ValueError("zero-work milestones cannot consume resources in this POC")
            for requirement in requirements:
                eligible = requirement["eligible_resource_ids"]
                if not eligible or len(eligible) != len(set(eligible)) or not set(eligible) <= resources:
                    raise ValueError("eligible resources must be nonempty, unique and known")
                capabilities = set(requirement["pool_ids"])
                if not capabilities or any(not capabilities <= set(by_resource[r]["capabilities"]) for r in eligible):
                    raise ValueError("explicit eligibility must satisfy every qualification for this slot")
    pending = {a["id"]: set(a.get("predecessors", [])) for a in project["activities"]}
    while pending:
        ready = {key for key, predecessors in pending.items() if not predecessors}
        if not ready:
            raise ValueError("precedence cycle")
        pending = {key: predecessors - ready for key, predecessors in pending.items() if key not in ready}
    if project["objective_activity_id"] not in activities:
        raise ValueError("unknown controlling activity")
    # All work must lead to the controlling handoff; no disconnected work is hidden.
    by_activity = {a["id"]: a for a in project["activities"]}
    ancestors: set[str] = set()
    frontier = [project["objective_activity_id"]]
    while frontier:
        current = frontier.pop()
        if current not in ancestors:
            ancestors.add(current)
            frontier.extend(by_activity[current].get("predecessors", []))
    if ancestors != activities:
        raise ValueError("every activity must feed the controlling handoff in this POC")
    _ids(workspace["reports"], "report")
    for report in workspace["reports"]:
        if report["resource_id"] not in resources or report["status"] not in {"REPORTED", "ACCEPTED"}:
            raise ValueError("unknown report resource or status")
        _integer(report["start"], "outage start")
        _integer(report["finish"], "outage finish", 1)
        if not report["start"] < report["finish"] <= horizon:
            raise ValueError("outage must lie inside the planning horizon")
        if not report["reason"].strip() or not report["reported_by"].strip():
            raise ValueError("report needs an actor and reason")
        if report["status"] == "ACCEPTED" and not report.get("accepted_by"):
            raise ValueError("accepted report needs an accepting actor")


def trusted_input(workspace: Workspace) -> dict:
    return {
        "project": deepcopy(workspace["project"]),
        "accepted_reports": [deepcopy(r) for r in workspace["reports"] if r["status"] == "ACCEPTED"],
        "policy": POLICY,
    }


def state_hash(workspace: Workspace) -> str:
    return digest(trusted_input(workspace))


def load(path: str | Path) -> Workspace:
    workspace = json.loads(Path(path).read_text(encoding="utf-8"))
    validate(workspace)
    return workspace


def save(workspace: Workspace, path: str | Path) -> None:
    validate(workspace)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.write_text(json.dumps(workspace, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(destination)


def report_unavailable(workspace: Workspace, resource_id: str, start: int, finish: int, actor: str, reason: str) -> str:
    report_id = f"E{len(workspace['reports']) + 1:03d}"
    candidate = deepcopy(workspace)
    candidate["reports"].append({
        "id": report_id, "resource_id": resource_id, "start": start, "finish": finish,
        "reason": reason, "reported_by": actor, "reported_at": now(), "status": "REPORTED",
        "scheduling_role": "FORECAST_AVAILABILITY", "accepted_by": None, "accepted_at": None,
    })
    validate(candidate)
    workspace["reports"] = candidate["reports"]
    return report_id


def accept_report(workspace: Workspace, report_id: str, actor: str) -> None:
    if not actor.strip():
        raise ValueError("acceptance needs an actor")
    report = next((r for r in workspace["reports"] if r["id"] == report_id), None)
    if report is None or report["status"] != "REPORTED":
        raise ValueError("report must exist and be awaiting acceptance")
    report.update(status="ACCEPTED", accepted_by=actor, accepted_at=now())
    workspace["proposal"] = None
    # Keep the old approved plan, now visibly stale, even if no recovery exists.


def set_processing(workspace: Workspace, activity_id: str, mode_id: str, ticks: int) -> None:
    _integer(ticks, "processing_ticks", 1)
    candidate = deepcopy(workspace)
    for activity in candidate["project"]["activities"]:
        for mode in activity["modes"]:
            if activity["id"] == activity_id and mode["id"] == mode_id:
                mode["processing_ticks"] = ticks
                validate(candidate)
                workspace["project"] = candidate["project"]
                workspace["proposal"] = None
                return
    raise ValueError("unknown activity/mode")


def new_demo_workspace() -> Workspace:
    """Example inputs only. Dates, allocations and selected modes are calculated."""
    def slot(identifier: str, capability: str, eligible: list[str]) -> dict:
        return {"id": identifier, "pool_ids": [capability], "eligible_resource_ids": eligible}

    mech = slot("MECH", "MECH", ["M1", "M2", "N1"])
    inspect = slot("INSPECT", "INSPECT", ["M2"])
    specialist = slot("SPECIALIST", "SPECIALIST", ["M2"])
    rigger = slot("RIGGER", "RIGGER", ["R1", "R2"])

    def mode(identifier: str, ticks: int, requirements: list[dict]) -> dict:
        return {"id": identifier, "processing_ticks": ticks, "calendar_id": "DAY", "requirements": requirements}

    def activity(identifier: str, name: str, ticks: int, requirements: list[dict], predecessors: list[str]) -> dict:
        return {"id": identifier, "name": name, "modes": [mode("FIXED", ticks, requirements)], "predecessors": predecessors}

    project = {
        "id": "native-recovery-demo", "name": "Editable native repair plan", "horizon_ticks": 144,
        "objective_activity_id": "A08", "pool_riggers": True,
        "calendars": [
            {"id": "DAY", "daily_windows": [[14, 24], [25, 34]]},
            {"id": "NIGHT", "daily_windows": [[36, 48]]},
        ],
        "resources": [
            {"id": "M1", "capabilities": ["MECH"], "calendar_id": "DAY"},
            {"id": "M2", "capabilities": ["MECH", "INSPECT", "SPECIALIST"], "calendar_id": "DAY"},
            {"id": "N1", "capabilities": ["MECH"], "calendar_id": "NIGHT"},
            {"id": "R1", "capabilities": ["RIGGER"], "calendar_id": "DAY"},
            {"id": "R2", "capabilities": ["RIGGER"], "calendar_id": "DAY"},
        ],
        "activities": [
            activity("A01", "Prepare workfront", 2, [], []),
            activity("A02", "Initial inspection", 4, [inspect], ["A01"]),
            {"id": "A03", "name": "Repair assembly", "predecessors": ["A02"], "modes": [
                mode("NORMAL", 12, [mech]), mode("SPECIALIST", 6, [mech, specialist])]},
            activity("A04", "Final inspection", 2, [inspect], ["A03"]),
            activity("A05", "Rigging branch one", 6, [rigger], ["A01"]),
            activity("A06", "Rigging branch two", 6, [rigger], ["A01"]),
            activity("A07", "Calibrate controls", 3, [mech], ["A01"]),
            activity("A08", "Hand back equipment", 1, [mech], ["A04", "A05", "A06", "A07"]),
        ],
    }
    workspace = {"schema": SCHEMA, "project": deepcopy(project), "reports": [], "approved_plan": None, "proposal": None, "plan_history": []}
    validate(workspace)
    return workspace
