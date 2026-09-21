"""Small native JSON workspace. No external-format or solver types live here."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from itertools import combinations
from math import comb
import json
from pathlib import Path
from typing import Any

SCHEMA = "pm-native-planning-workspace/0"
GROUP_SCHEMA = "pm-native-planning-workspace/1"
STATUS_SCHEMA = "pm-native-planning-workspace/2"
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
    if workspace.get("schema") not in {SCHEMA, GROUP_SCHEMA, STATUS_SCHEMA}:
        raise ValueError(f"expected schema {SCHEMA}, {GROUP_SCHEMA} or {STATUS_SCHEMA}")
    if workspace["schema"] != STATUS_SCHEMA and "execution" in workspace:
        raise ValueError("execution fields require an explicit version-two workspace")
    grouped = workspace["schema"] in {GROUP_SCHEMA, STATUS_SCHEMA}
    project = workspace["project"]
    allowed = {"id", "name", "horizon_ticks", "calendars", "resources", "activities", "objective_activity_id", "pool_riggers"}
    if grouped:
        allowed.add("resource_groups")
    if set(project) - allowed:
        raise ValueError(f"unsupported project fields: {sorted(set(project) - allowed)}")
    horizon = project["horizon_ticks"]
    _integer(horizon, "horizon_ticks", 1)
    if not project["activities"]:
        raise ValueError("project needs activities")
    calendars = _ids(project["calendars"], "calendar")
    resources = _ids(project["resources"], "resource")
    groups = project["resource_groups"] if grouped else []
    group_ids = _ids(groups, "resource group")
    if group_ids & resources:
        raise ValueError("resource groups and named resources must have distinct IDs; overlap is unsupported")
    by_group = {g["id"]: g for g in groups}
    for group in groups:
        if set(group) != {"id", "name", "capacity", "calendar_id", "disjoint", "interchangeable"}:
            raise ValueError("resource groups require ID, name, capacity, calendar and declarations; member lists/overlap are unsupported")
        _integer(group["capacity"], "group capacity", 1)
        if not isinstance(group["name"], str) or not group["name"].strip() or group["calendar_id"] not in calendars:
            raise ValueError("resource group needs a display name and known calendar")
        if group["disjoint"] is not True or group["interchangeable"] is not True:
            raise ValueError("groups must be declared disjoint from every other group and named resource, and internally interchangeable")
    if len(groups) > 8 or sum(g["capacity"] for g in groups) > 32:
        raise ValueError("bounded group profile supports at most 8 groups and 32 total capacity units")
    activities = _ids(project["activities"], "activity")
    for calendar in project["calendars"]:
        for start, finish in calendar["daily_windows"]:
            _integer(start, "calendar start")
            _integer(finish, "calendar finish", 1)
            if not start < finish <= 48:
                raise ValueError("calendar windows must lie within a 48-tick day")
    for resource in project["resources"]:
        if grouped and (resource["id"].startswith("@group/") or set(resource) - {"id", "capabilities", "calendar_id", "capacity"}):
            raise ValueError("named resources cannot declare group membership or use reserved internal IDs")
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
            mode_fields = {"id", "processing_ticks", "calendar_id", "continuity", "requirements"}
            if grouped:
                mode_fields.add("group_requirements")
            if set(mode) - mode_fields:
                raise ValueError(f"unsupported mode fields on {activity['id']}/{mode['id']}")
            _integer(mode["processing_ticks"], "processing_ticks")
            if mode["calendar_id"] not in calendars:
                raise ValueError("unknown mode calendar")
            if mode.get("continuity", "SUSPENDABLE_AT_AVAILABILITY_GAPS") not in {"CONTINUOUS", "SUSPENDABLE_AT_AVAILABILITY_GAPS"}:
                raise ValueError("unsupported continuity rule")
            requirements = mode.get("requirements", [])
            _ids(requirements, "requirement")
            demands = mode.get("group_requirements", [])
            if not isinstance(demands, list):
                raise ValueError("group_requirements must be an array")
            seen_groups = set()
            for demand in demands:
                if set(demand) != {"group_id", "demand"} or demand["group_id"] not in by_group:
                    raise ValueError("group requirement needs a known group_id and demand only")
                gid = demand["group_id"]
                _integer(demand["demand"], "group demand", 1)
                if gid in seen_groups or demand["demand"] > by_group[gid]["capacity"]:
                    raise ValueError(f"group {gid}: use one quantity row; demand must not exceed available capacity")
                seen_groups.add(gid)
            if (requirements or demands) and not mode["processing_ticks"]:
                raise ValueError("zero-work milestones cannot consume resources in this POC")
            for requirement in requirements:
                if grouped and (requirement["id"].startswith("@group/") or set(requirement) != {"id", "pool_ids", "eligible_resource_ids"}):
                    raise ValueError("named slots require explicit eligibility; reserved IDs/group membership are unsupported")
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
    if workspace["schema"] == STATUS_SCHEMA:
        _validate_execution(workspace)
        # Import and edits must not trust assertions that acceptance
        # would reject. Missing activity statuses still remain UNKNOWN.
        validate_accepted_history(workspace, require_complete=False)


EXECUTION_STATES = {"NOT_STARTED", "IN_PROGRESS", "COMPLETED"}


def _pairs(value: Any, label: str) -> list[list[str]]:
    if not isinstance(value, list) or any(
        not isinstance(row, list) or len(row) != 2
        or not all(isinstance(item, str) and item for item in row)
        for row in value
    ):
        raise ValueError(f"{label} must be an array of nonempty string pairs")
    if len({row[0] for row in value}) != len(value):
        raise ValueError(f"{label} requirement IDs must be unique")
    return value


def _validate_execution(workspace: Workspace) -> None:
    execution = workspace.get("execution")
    if not isinstance(execution, dict) or set(execution) != {"status_point", "updates"}:
        raise ValueError("version two requires execution status_point and updates")
    status_point = execution["status_point"]
    _integer(status_point, "status_point")
    if status_point > workspace["project"]["horizon_ticks"]:
        raise ValueError("status_point must lie inside the planning horizon")
    updates = execution["updates"]
    if not isinstance(updates, list):
        raise ValueError("execution updates must be an array")
    update_ids = _ids(updates, "status update")
    activity_ids = {activity["id"] for activity in workspace["project"]["activities"]}
    by_id = {update["id"]: update for update in updates}
    allowed = {
        "id", "activity_id", "status", "execution_state", "actual_start",
        "actual_finish", "actual_periods", "mode_id", "named_assignments",
        "remaining_processing_ticks", "occurred_at", "asserted_by", "asserted_at",
        "accepted_by", "accepted_at", "supersedes_update_id", "reason",
        "execution_context",
    }
    for update in updates:
        if set(update) != allowed:
            raise ValueError(f"status update {update.get('id', '<unknown>')} has unsupported or missing fields")
        if update["activity_id"] not in activity_ids:
            raise ValueError("status update refers to an unknown activity")
        if update["status"] not in {"REPORTED", "ACCEPTED"} or update["execution_state"] not in EXECUTION_STATES:
            raise ValueError("status update needs an explicit lifecycle and execution state")
        _integer(update["occurred_at"], "status occurrence")
        if update["occurred_at"] > status_point:
            raise ValueError("status occurrence cannot be after the accepted status point")
        if not isinstance(update["asserted_by"], str) or not update["asserted_by"].strip() or not isinstance(update["asserted_at"], str) or not update["asserted_at"]:
            raise ValueError("status update needs assertion provenance")
        if not isinstance(update["reason"], str) or not update["reason"].strip():
            raise ValueError("status update needs a reason")
        if update["status"] == "ACCEPTED":
            if not isinstance(update["accepted_by"], str) or not update["accepted_by"].strip() or not isinstance(update["accepted_at"], str) or not update["accepted_at"]:
                raise ValueError("accepted status update needs acceptance provenance")
        elif update["accepted_by"] is not None or update["accepted_at"] is not None:
            raise ValueError("reported status update cannot carry acceptance provenance")
        supersedes = update["supersedes_update_id"]
        if supersedes is not None:
            if supersedes not in update_ids or supersedes == update["id"]:
                raise ValueError("superseded status update must exist and be different")
            if by_id[supersedes]["activity_id"] != update["activity_id"]:
                raise ValueError("a correction can supersede only the same activity")
        periods = update["actual_periods"]
        if not isinstance(periods, list):
            raise ValueError("actual_periods must be an array")
        previous_finish = -1
        for period in periods:
            if not isinstance(period, list) or len(period) != 2:
                raise ValueError("actual period must be a start/finish pair")
            start, finish = period
            _integer(start, "actual period start")
            _integer(finish, "actual period finish", 1)
            if start >= finish or finish > status_point or start < previous_finish:
                raise ValueError("actual periods must be ordered, disjoint and no later than the status point")
            previous_finish = finish
        actual_start, actual_finish = update["actual_start"], update["actual_finish"]
        if actual_start is not None:
            _integer(actual_start, "actual_start")
            if actual_start > status_point or (periods and actual_start > periods[0][0]):
                raise ValueError("actual_start must precede accepted productive history")
        if actual_finish is not None:
            _integer(actual_finish, "actual_finish")
            if actual_finish > status_point or (actual_start is not None and actual_finish < actual_start) or (periods and actual_finish < periods[-1][1]):
                raise ValueError("actual_finish must contain accepted productive history before the status point")
        _pairs(update["named_assignments"], "named_assignments")
        state = update["execution_state"]
        remaining = update["remaining_processing_ticks"]
        if state == "NOT_STARTED":
            if any(value not in (None, [], {}) for value in (actual_start, actual_finish, periods, update["mode_id"], update["named_assignments"], remaining, update["execution_context"])):
                raise ValueError("NOT_STARTED cannot carry accepted execution history")
        else:
            if not isinstance(update["mode_id"], str) or not update["mode_id"] or not isinstance(update["execution_context"], dict):
                raise ValueError("begun work needs its accepted mode and execution context")
            if actual_start is None:
                raise ValueError("begun work needs an actual_start")
            if state == "IN_PROGRESS":
                _integer(remaining, "remaining_processing_ticks")
                if actual_finish is not None:
                    raise ValueError("IN_PROGRESS cannot carry an actual_finish")
            else:
                if remaining != 0 or actual_finish is None:
                    raise ValueError("COMPLETED needs explicit actual_finish and zero remaining work")
    # Accepted supersession is resolved by identity, never by occurrence time.
    accepted = [update for update in updates if update["status"] == "ACCEPTED"]
    accepted_ids = {update["id"] for update in accepted}
    for update in accepted:
        if update["supersedes_update_id"] is not None and update["supersedes_update_id"] not in accepted_ids:
            raise ValueError("an accepted correction must supersede an accepted assertion")
    for update in updates:
        visited = set()
        cursor = update["id"]
        while cursor is not None:
            if cursor in visited:
                raise ValueError("status supersession cycle")
            visited.add(cursor)
            cursor = by_id[cursor]["supersedes_update_id"]
    parents = [update["supersedes_update_id"] for update in accepted if update["supersedes_update_id"] is not None]
    if len(parents) != len(set(parents)):
        raise ValueError("competing accepted corrections fork the same assertion")
    current_status_records(workspace, require_complete=False)


def trusted_input(workspace: Workspace) -> dict:
    result = {
        "project": deepcopy(workspace["project"]),
        "accepted_reports": [deepcopy(r) for r in workspace["reports"] if r["status"] == "ACCEPTED"],
        "policy": POLICY,
    }
    # Version zero's source snapshots/hashes remain byte-for-byte meaningful.
    if workspace["schema"] in {GROUP_SCHEMA, STATUS_SCHEMA}:
        result["workspace_schema"] = workspace["schema"]
    if workspace["schema"] == STATUS_SCHEMA:
        result["execution"] = {
            "status_point": workspace["execution"]["status_point"],
            "accepted_updates": [deepcopy(update) for update in workspace["execution"]["updates"] if update["status"] == "ACCEPTED"],
        }
    return result


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
    report_id = _next_record_id(workspace["reports"], "E")
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


def _next_record_id(records: list[dict], prefix: str) -> str:
    used = {record.get("id") for record in records}
    number = 1
    while f"{prefix}{number:03d}" in used:
        number += 1
    return f"{prefix}{number:03d}"


def enable_status_tracking(workspace: Workspace, status_point: int) -> None:
    """Explicitly opt a legacy workspace into accepted-progress semantics.

    Existing approved plans retain their original snapshots and hashes.  This
    operation changes current trusted input, so any calculated proposal is
    discarded while the last approval remains available as stale history.
    """
    if workspace.get("schema") == STATUS_SCHEMA:
        raise ValueError("status tracking is already enabled")
    if workspace.get("schema") not in {SCHEMA, GROUP_SCHEMA}:
        raise ValueError("only a valid version-zero or version-one workspace can be statused")
    _integer(status_point, "status_point")
    candidate = deepcopy(workspace)
    if candidate["schema"] == SCHEMA:
        candidate["project"]["resource_groups"] = []
        for activity in candidate["project"]["activities"]:
            for mode in activity["modes"]:
                mode["group_requirements"] = []
    candidate["schema"] = STATUS_SCHEMA
    candidate["execution"] = {"status_point": status_point, "updates": []}
    candidate["proposal"] = None
    validate(candidate)
    workspace.clear()
    workspace.update(candidate)


def current_status_records(workspace: Workspace, *, require_complete: bool = False) -> dict[str, dict]:
    """Return accepted, non-superseded assertions by activity identity."""
    if workspace.get("schema") != STATUS_SCHEMA:
        raise ValueError("accepted execution state requires a version-two workspace")
    accepted = [update for update in workspace["execution"]["updates"] if update["status"] == "ACCEPTED"]
    superseded = {update["supersedes_update_id"] for update in accepted if update["supersedes_update_id"] is not None}
    current: dict[str, dict] = {}
    for update in accepted:
        if update["id"] in superseded:
            continue
        activity_id = update["activity_id"]
        if activity_id in current:
            raise ValueError(f"activity {activity_id} has competing accepted status assertions")
        current[activity_id] = update
    if require_complete:
        expected = {activity["id"] for activity in workspace["project"]["activities"]}
        missing = sorted(expected - set(current))
        if missing:
            raise ValueError(f"authoritative statused recovery requires an explicit status for every activity; UNKNOWN: {', '.join(missing)}")
    return current


def _context_for_update(workspace: Workspace, activity: dict, mode: dict, named_assignments: list[list[str]]) -> dict:
    project = workspace["project"]
    calendars = {calendar["id"]: calendar for calendar in project["calendars"]}
    resources = {resource["id"]: resource for resource in project["resources"]}
    groups = {group["id"]: group for group in project.get("resource_groups", [])}
    resource_ids = {resource_id for _, resource_id in named_assignments}
    calendar_ids = {mode["calendar_id"]}
    for resource_id in resource_ids:
        calendar_ids.add(resources[resource_id]["calendar_id"])
    for demand in mode.get("group_requirements", []):
        calendar_ids.add(groups[demand["group_id"]]["calendar_id"])
    return {
        "activity_id": activity["id"],
        "mode": deepcopy(mode),
        "calendars": [deepcopy(calendars[key]) for key in sorted(calendar_ids)],
        "named_resources": [deepcopy(resources[key]) for key in sorted(resource_ids)],
        "resource_groups": [deepcopy(groups[demand["group_id"]]) for demand in mode.get("group_requirements", [])],
        "accepted_outages": [deepcopy(report) for report in workspace["reports"]
                             if report["status"] == "ACCEPTED" and report["resource_id"] in resource_ids],
    }


def report_status_update(
    workspace: Workspace,
    activity_id: str,
    execution_state: str,
    actor: str,
    reason: str,
    *,
    actual_start: int | None = None,
    actual_finish: int | None = None,
    actual_periods: list[list[int]] | None = None,
    mode_id: str | None = None,
    named_assignments: list[list[str]] | None = None,
    remaining_processing_ticks: int | None = None,
    occurred_at: int | None = None,
    supersedes_update_id: str | None = None,
) -> str:
    """Record a reviewable assertion without changing trusted project state."""
    if workspace.get("schema") != STATUS_SCHEMA:
        raise ValueError("enable status tracking before recording execution")
    if execution_state not in EXECUTION_STATES:
        raise ValueError("execution_state must be NOT_STARTED, IN_PROGRESS or COMPLETED")
    if not actor.strip() or not reason.strip():
        raise ValueError("status update needs an asserting actor and reason")
    activity = next((item for item in workspace["project"]["activities"] if item["id"] == activity_id), None)
    if activity is None:
        raise ValueError("unknown activity")
    periods = deepcopy(actual_periods or [])
    assignments = deepcopy(named_assignments or [])
    mode = None
    context = None
    if execution_state != "NOT_STARTED":
        prior = next((item for item in workspace["execution"]["updates"] if item["id"] == supersedes_update_id), None)
        same_choices = (prior and prior["status"] == "ACCEPTED" and prior["activity_id"] == activity_id
                        and prior["mode_id"] == mode_id
                        and sorted(_pairs(prior["named_assignments"], "named_assignments")) == sorted(_pairs(assignments, "named_assignments"))
                        and prior["execution_context"])
        mode = next((item for item in activity["modes"] if item["id"] == mode_id), None)
        if mode is None and same_choices and execution_state == "COMPLETED":
            mode = prior["execution_context"]["mode"]
        if mode is None:
            raise ValueError("begun work needs an authorised current mode")
        if same_choices:
            # Revising an estimate must not recapture today's forecast calendar
            # as the historical calendar of work that already happened.
            context = deepcopy(prior["execution_context"])
        else:
            context = _context_for_update(workspace, activity, mode, assignments)
    update_id = _next_record_id(workspace["execution"]["updates"], "U")
    record = {
        "id": update_id,
        "activity_id": activity_id,
        "status": "REPORTED",
        "execution_state": execution_state,
        "actual_start": actual_start,
        "actual_finish": actual_finish,
        "actual_periods": periods,
        "mode_id": mode_id if execution_state != "NOT_STARTED" else None,
        "named_assignments": assignments,
        "remaining_processing_ticks": remaining_processing_ticks if execution_state != "NOT_STARTED" else None,
        "occurred_at": workspace["execution"]["status_point"] if occurred_at is None else occurred_at,
        "asserted_by": actor,
        "asserted_at": now(),
        "accepted_by": None,
        "accepted_at": None,
        "supersedes_update_id": supersedes_update_id,
        "reason": reason,
        "execution_context": context,
    }
    candidate = deepcopy(workspace)
    candidate["execution"]["updates"].append(record)
    validate(candidate)
    workspace["execution"]["updates"] = candidate["execution"]["updates"]
    return update_id



def _validate_historical_execution_context(
    activity_id: str,
    update: dict,
    context: Any,
    horizon: int,
) -> tuple[dict, dict[str, dict], dict[str, dict], dict[str, dict]]:
    """Validate captured history as native domain data before trusting it."""
    required_context = {"activity_id", "mode", "calendars", "named_resources", "resource_groups"}
    if (not isinstance(context, dict) or not required_context <= set(context)
            or set(context) - required_context - {"accepted_outages"} or context["activity_id"] != activity_id):
        raise ValueError(f"{activity_id}: invalid accepted execution context")

    mode = context["mode"]
    mode_fields = {"id", "processing_ticks", "calendar_id", "continuity", "requirements", "group_requirements"}
    if (not isinstance(mode, dict) or not {"id", "processing_ticks", "calendar_id"} <= set(mode)
            or set(mode) - mode_fields or mode.get("id") != update["mode_id"]):
        raise ValueError(f"{activity_id}: accepted mode context disagrees")
    if not isinstance(mode["id"], str) or not mode["id"].strip():
        raise ValueError(f"{activity_id}: historical mode ID must be nonempty")
    _integer(mode["processing_ticks"], f"{activity_id} historical processing_ticks")
    if not isinstance(mode["calendar_id"], str) or not mode["calendar_id"].strip():
        raise ValueError(f"{activity_id}: historical mode needs a calendar")
    if mode.get("continuity", "SUSPENDABLE_AT_AVAILABILITY_GAPS") not in {
        "CONTINUOUS", "SUSPENDABLE_AT_AVAILABILITY_GAPS"
    }:
        raise ValueError(f"{activity_id}: unsupported historical continuity rule")

    captured_calendars = context["calendars"]
    if not isinstance(captured_calendars, list):
        raise ValueError(f"{activity_id}: historical calendars must be an array")
    calendars: dict[str, dict] = {}
    for calendar in captured_calendars:
        # The merged v2 project contract permits calendar metadata. Preserve it
        # verbatim; executable eligibility depends only on ID and windows.
        if not isinstance(calendar, dict) or not {"id", "daily_windows"} <= set(calendar):
            raise ValueError(f"{activity_id}: invalid historical calendar snapshot")
        calendar_id = calendar["id"]
        if not isinstance(calendar_id, str) or not calendar_id.strip() or calendar_id in calendars:
            raise ValueError(f"{activity_id}: historical calendar IDs must be nonempty and unique")
        windows = calendar["daily_windows"]
        if not isinstance(windows, list):
            raise ValueError(f"{activity_id}: historical calendar windows must be an array")
        for window in windows:
            if not isinstance(window, list) or len(window) != 2:
                raise ValueError(f"{activity_id}: historical calendar window must be a start/finish pair")
            start, finish = window
            _integer(start, f"{activity_id} historical calendar start")
            _integer(finish, f"{activity_id} historical calendar finish", 1)
            if not start < finish <= 48:
                raise ValueError(f"{activity_id}: historical calendar windows must lie within a 48-tick day")
        calendars[calendar_id] = calendar

    captured_resources = context["named_resources"]
    if not isinstance(captured_resources, list):
        raise ValueError(f"{activity_id}: historical named resources must be an array")
    resources: dict[str, dict] = {}
    for resource in captured_resources:
        allowed = {"id", "capabilities", "calendar_id", "capacity"}
        if (not isinstance(resource, dict) or not {"id", "capabilities", "calendar_id"} <= set(resource)
                or set(resource) - allowed):
            raise ValueError(f"{activity_id}: invalid historical named-resource snapshot")
        resource_id = resource["id"]
        capabilities = resource["capabilities"]
        if (not isinstance(resource_id, str) or not resource_id.strip() or resource_id.startswith("@group/")
                or resource_id in resources):
            raise ValueError(f"{activity_id}: historical named-resource IDs must be nonempty, unique and non-anonymous")
        # Legacy v2 also accepts strings via set(capabilities). Retain their
        # character-set meaning and captured representation without coercion.
        if (not isinstance(capabilities, (list, str)) or not capabilities
                or any(not isinstance(capability, str) or not capability.strip() for capability in capabilities)):
            raise ValueError(f"{activity_id}/{resource_id}: historical capabilities must be nonempty strings")
        # Match the existing v2 project boundary without rewriting captured values.
        if resource.get("capacity", 1) != 1:
            raise ValueError(f"{activity_id}/{resource_id}: historical named resources have capacity one")
        if (not isinstance(resource["calendar_id"], str) or not resource["calendar_id"].strip()
                or resource["calendar_id"] not in calendars):
            raise ValueError(f"{activity_id}/{resource_id}: historical resource calendar is missing")
        resources[resource_id] = resource

    captured_groups = context["resource_groups"]
    if not isinstance(captured_groups, list):
        raise ValueError(f"{activity_id}: historical resource groups must be an array")
    groups: dict[str, dict] = {}
    for group in captured_groups:
        required = {"id", "name", "capacity", "calendar_id", "disjoint", "interchangeable"}
        if not isinstance(group, dict) or set(group) != required:
            raise ValueError(f"{activity_id}: invalid historical resource-group snapshot")
        group_id = group["id"]
        if (not isinstance(group_id, str) or not group_id.strip() or group_id in groups
                or group_id in resources):
            raise ValueError(f"{activity_id}: historical group IDs must be nonempty, unique and distinct from named resources")
        _integer(group["capacity"], f"{activity_id}/{group_id} historical group capacity", 1)
        if (not isinstance(group["name"], str) or not group["name"].strip()
                or not isinstance(group["calendar_id"], str) or not group["calendar_id"].strip()
                or group["calendar_id"] not in calendars):
            raise ValueError(f"{activity_id}/{group_id}: historical group needs a name and known calendar")
        if group["disjoint"] is not True or group["interchangeable"] is not True:
            raise ValueError(f"{activity_id}/{group_id}: historical groups must remain disjoint and interchangeable")
        groups[group_id] = group
    if len(groups) > 8 or sum(group["capacity"] for group in groups.values()) > 32:
        raise ValueError(f"{activity_id}: historical group context exceeds the bounded native capacity profile")

    requirements = mode.get("requirements", [])
    if not isinstance(requirements, list):
        raise ValueError(f"{activity_id}: historical named requirements must be an array")
    requirement_ids: set[str] = set()
    for requirement in requirements:
        if not isinstance(requirement, dict) or set(requirement) != {"id", "pool_ids", "eligible_resource_ids"}:
            raise ValueError(f"{activity_id}: invalid historical named requirement")
        requirement_id = requirement["id"]
        pools = requirement["pool_ids"]
        eligible = requirement["eligible_resource_ids"]
        if (not isinstance(requirement_id, str) or not requirement_id.strip()
                or requirement_id.startswith("@group/") or requirement_id in requirement_ids):
            raise ValueError(f"{activity_id}: historical requirement IDs must be nonempty, unique and non-anonymous")
        if (not isinstance(pools, list) or not pools
                or any(not isinstance(value, str) or not value.strip() for value in pools)):
            raise ValueError(f"{activity_id}/{requirement_id}: historical qualifications must be nonempty strings")
        if (not isinstance(eligible, list) or not eligible
                or any(not isinstance(value, str) or not value.strip() for value in eligible)
                or len(eligible) != len(set(eligible))):
            raise ValueError(f"{activity_id}/{requirement_id}: historical eligibility must be nonempty and unique")
        requirement_ids.add(requirement_id)

    demands = mode.get("group_requirements", [])
    if not isinstance(demands, list):
        raise ValueError(f"{activity_id}: historical group requirements must be an array")
    demanded_groups: set[str] = set()
    for demand in demands:
        if not isinstance(demand, dict) or set(demand) != {"group_id", "demand"}:
            raise ValueError(f"{activity_id}: invalid historical group requirement")
        group_id = demand["group_id"]
        if not isinstance(group_id, str) or not group_id.strip() or group_id not in groups:
            raise ValueError(f"{activity_id}: historical group context is missing")
        _integer(demand["demand"], f"{activity_id}/{group_id} historical group demand", 1)
        if group_id in demanded_groups or demand["demand"] > groups[group_id]["capacity"]:
            raise ValueError(f"{activity_id}/{group_id}: historical group demand is invalid")
        demanded_groups.add(group_id)

    if (requirements or demands) and mode["processing_ticks"] == 0:
        raise ValueError(f"{activity_id}: zero-work historical modes cannot consume resources")
    if mode["calendar_id"] not in calendars:
        raise ValueError(f"{activity_id}: historical activity calendar is missing")

    assignments = dict(_pairs(update["named_assignments"], "named_assignments"))
    if set(resources) != set(assignments.values()):
        raise ValueError(f"{activity_id}: historical named-resource context must match accepted assignments exactly")
    if set(groups) != demanded_groups:
        raise ValueError(f"{activity_id}: historical group context must match the begun mode exactly")
    required_calendar_ids = {mode["calendar_id"]}
    required_calendar_ids.update(resource["calendar_id"] for resource in resources.values())
    required_calendar_ids.update(group["calendar_id"] for group in groups.values())
    if set(calendars) != required_calendar_ids:
        raise ValueError(f"{activity_id}: historical calendar context must match the begun execution choices exactly")

    # Validate captured outage structure for superseded provenance as well.
    # Applying its availability to actual execution belongs to current history.
    outages = context.get("accepted_outages", [])
    if not isinstance(outages, list):
        raise ValueError(f"{activity_id}: historical accepted outages must be an array")
    for outage in outages:
        if (not isinstance(outage, dict) or outage.get("status") != "ACCEPTED"
                or outage.get("resource_id") not in assignments.values() or not outage.get("accepted_by")):
            raise ValueError(f"{activity_id}: invalid historical accepted outage")
        _integer(outage.get("start"), "historical outage start")
        _integer(outage.get("finish"), "historical outage finish", 1)
        if outage["start"] >= outage["finish"]:
            raise ValueError(f"{activity_id}: invalid historical outage interval")

    return mode, calendars, resources, groups

def _daily_slots(calendar: dict, horizon: int) -> set[int]:
    return {
        day * 48 + tick
        for day in range((horizon + 47) // 48)
        for start, finish in calendar["daily_windows"]
        for tick in range(start, finish)
        if day * 48 + tick < horizon
    }


def validate_accepted_history(workspace: Workspace, *, require_complete: bool = False) -> dict[str, dict]:
    """Validate accepted facts against their captured historical context."""
    current = current_status_records(workspace, require_complete=require_complete)
    horizon = workspace["project"]["horizon_ticks"]
    contexts = {
        update["id"]: _validate_historical_execution_context(
            update["activity_id"], update, update["execution_context"], horizon
        )
        for update in workspace["execution"]["updates"]
        if update["status"] == "ACCEPTED" and update["execution_state"] != "NOT_STARTED"
    }
    named_occupancy: dict[tuple[str, int], str] = {}
    group_occupancy: dict[tuple[str, int], int] = {}
    group_capacity: dict[tuple[str, int], int] = {}
    group_tasks: dict[str, list[tuple[str, int, frozenset[int], int]]] = {}
    for activity_id, update in current.items():
        if update["execution_state"] == "NOT_STARTED":
            continue
        context = update["execution_context"]
        mode, calendars, resources, groups = contexts[update["id"]]
        activity_slots = _daily_slots(calendars[mode["calendar_id"]], horizon)
        joint_slots = set(activity_slots)
        occupied = [tick for start, finish in update["actual_periods"] for tick in range(start, finish)]
        if update["execution_state"] == "COMPLETED" and mode["processing_ticks"] > 0 and not occupied:
            continuity = mode.get("continuity", "SUSPENDABLE_AT_AVAILABILITY_GAPS")
            raise ValueError(f"{activity_id}: completed {continuity} productive work needs at least one actual period")
        if any(tick not in activity_slots for tick in occupied):
            raise ValueError(f"{activity_id}: accepted productive history lies outside its historical activity calendar")
        requirements = {requirement["id"]: requirement for requirement in mode.get("requirements", [])}
        assignments = dict(_pairs(update["named_assignments"], "named_assignments"))
        if set(assignments) != set(requirements):
            raise ValueError(f"{activity_id}: accepted named assignments must cover the begun mode exactly")
        if len(set(assignments.values())) != len(assignments):
            raise ValueError(f"{activity_id}: simultaneous slots require distinct accepted named resources")
        for requirement_id, resource_id in assignments.items():
            if resource_id.startswith("@group/"):
                raise ValueError("anonymous compiler units cannot be accepted as historical worker identities")
            requirement = requirements[requirement_id]
            if resource_id not in requirement["eligible_resource_ids"] or resource_id not in resources:
                raise ValueError(f"{activity_id}/{requirement_id}: accepted named assignment is ineligible")
            resource = resources[resource_id]
            if not set(requirement["pool_ids"]) <= set(resource["capabilities"]):
                raise ValueError(f"{activity_id}/{requirement_id}: accepted named resource lacks historical qualifications")
            if resource["calendar_id"] not in calendars:
                raise ValueError(f"{activity_id}/{requirement_id}: historical resource calendar is missing")
            resource_slots = _daily_slots(calendars[resource["calendar_id"]], horizon)
            joint_slots.intersection_update(resource_slots)
            if any(tick not in resource_slots for tick in occupied):
                raise ValueError(f"{activity_id}/{requirement_id}: accepted history lies outside historical resource availability")
            for tick in occupied:
                key = (resource_id, tick)
                if key in named_occupancy:
                    raise ValueError(f"accepted named resource {resource_id} is double-booked at tick {tick}")
                named_occupancy[key] = activity_id
        for demand in mode.get("group_requirements", []):
            group_id, quantity = demand["group_id"], demand["demand"]
            if group_id not in groups or groups[group_id]["calendar_id"] not in calendars:
                raise ValueError(f"{activity_id}: historical group context is missing")
            group = groups[group_id]
            slots = _daily_slots(calendars[group["calendar_id"]], horizon)
            joint_slots.intersection_update(slots)
            if any(tick not in slots for tick in occupied):
                raise ValueError(f"{activity_id}: accepted group work lies outside its historical calendar")
            for tick in occupied:
                key = (group_id, tick)
                group_occupancy[key] = group_occupancy.get(key, 0) + quantity
                group_capacity[key] = min(group_capacity.get(key, group["capacity"]), group["capacity"])
                if group_occupancy[key] > group_capacity[key]:
                    raise ValueError(f"accepted group {group_id} capacity is exceeded at tick {tick}")
            if occupied:
                group_tasks.setdefault(group_id, []).append((activity_id, quantity, frozenset(occupied), group["capacity"]))
        # Old v2 snapshots have no captured outages; never retrofit today's
        # availability into them or rewrite their hashes.
        for outage in context.get("accepted_outages", []):
            joint_slots.difference_update(range(outage["start"], outage["finish"]))
        if any(tick not in joint_slots for tick in occupied):
            raise ValueError(f"{activity_id}: accepted work contradicts captured historical availability")
        if mode.get("continuity") == "CONTINUOUS":
            end = update["actual_finish"] if update["execution_state"] == "COMPLETED" else workspace["execution"]["status_point"]
            if occupied != list(range(update["actual_start"], end)):
                raise ValueError(f"{activity_id}: continuous actual periods must fill the actual envelope through completion or the status point")
        elif occupied or (update["execution_state"] == "IN_PROGRESS" and update["remaining_processing_ticks"] > 0):
            # Positive remaining work cannot hide an arbitrary suspension before
            # the status boundary. Zero remaining is still not completion, but
            # does not assert that productive work continued until that point.
            end = (workspace["execution"]["status_point"]
                   if update["execution_state"] == "IN_PROGRESS" and update["remaining_processing_ticks"] > 0
                   else occupied[-1] + 1)
            expected = sorted(tick for tick in joint_slots if update["actual_start"] <= tick < end)
            if occupied != expected:
                raise ValueError(f"{activity_id}: historical suspension gap contains executable productive time")
    validate_group_allocation(group_tasks, "accepted history")
    if require_complete:
        for activity in workspace["project"]["activities"]:
            record = current[activity["id"]]
            if record["execution_state"] in {"IN_PROGRESS", "COMPLETED"}:
                for predecessor in activity.get("predecessors", []):
                    if current[predecessor]["execution_state"] != "COMPLETED":
                        raise ValueError(f"{activity['id']}: begun work requires predecessor {predecessor} to be explicitly COMPLETED")
                    if current[predecessor]["actual_finish"] > record["actual_start"]:
                        raise ValueError(f"{activity['id']}: out-of-sequence actual start before predecessor {predecessor} finish is unsupported")
    return current


def validate_group_allocation(tasks: dict[str, list[tuple[str, int, frozenset[int], int]]], label: str) -> None:
    """Prove fixed anonymous sets exist; never persist their identities."""
    for group_id, group_tasks in tasks.items():
        used: dict[int, set[int]] = {}
        ordered = sorted(group_tasks, key=lambda task: (-len(task[2]), -task[1], task[0]))
        if any(comb(capacity, demand) > 64 for _, demand, _, capacity in ordered):
            raise ValueError("bounded historical group proof supports at most 64 allocation sets")

        def assign(index: int) -> bool:
            if index == len(ordered):
                return True
            _, demand, occupied, capacity = ordered[index]
            for units in combinations(range(capacity), demand):
                if any(occupied & used.get(unit, set()) for unit in units):
                    continue
                for unit in units:
                    used.setdefault(unit, set()).update(occupied)
                if assign(index + 1):
                    return True
                for unit in units:
                    used[unit].difference_update(occupied)
            return False

        if not assign(0):
            raise ValueError(f"{label}: group {group_id} has no consistent anonymous no-handover allocation")


def accept_status_update(workspace: Workspace, update_id: str, actor: str) -> None:
    """Accept a reported assertion atomically and stale, but never approve, plans."""
    if not actor.strip():
        raise ValueError("status acceptance needs an actor")
    candidate = deepcopy(workspace)
    update = next((item for item in candidate.get("execution", {}).get("updates", []) if item["id"] == update_id), None)
    if update is None or update["status"] != "REPORTED":
        raise ValueError("status update must exist and be awaiting acceptance")
    if update["supersedes_update_id"] is not None:
        current = current_status_records(candidate)
        prior = current.get(update["activity_id"])
        if prior is None or prior["id"] != update["supersedes_update_id"]:
            raise ValueError("a correction must supersede the current accepted assertion")
    elif update["activity_id"] in current_status_records(candidate):
        raise ValueError("a new accepted assertion must explicitly supersede the current one")
    update.update(status="ACCEPTED", accepted_by=actor, accepted_at=now())
    candidate["proposal"] = None
    validate(candidate)
    workspace.clear()
    workspace.update(candidate)


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


def replace_project(workspace: Workspace, project: dict) -> None:
    """Apply edited native inputs atomically and invalidate any old proposal."""
    candidate = deepcopy(workspace)
    candidate["project"] = deepcopy(project)
    candidate["proposal"] = None
    validate(candidate)
    workspace["project"] = candidate["project"]
    workspace["proposal"] = None


def new_blank_workspace() -> Workspace:
    """Return an eight-activity native starter that is editable without JSON."""
    activities = []
    for index in range(1, 9):
        identifier = f"N{index:02d}"
        activities.append({
            "id": identifier,
            "name": "Controlling handoff" if index == 8 else f"Activity {index}",
            "predecessors": [] if index == 1 else [f"N{index - 1:02d}"],
            "not_before": 0,
            "modes": [{
                "id": "FIXED",
                "processing_ticks": 0 if index == 8 else 2,
                "calendar_id": "DAY",
                "continuity": "SUSPENDABLE_AT_AVAILABILITY_GAPS",
                "requirements": [],
            }],
        })
    workspace = {
        "schema": GROUP_SCHEMA,
        "project": {
            "id": "new-native-project",
            "name": "New native project",
            "horizon_ticks": 144,
            "objective_activity_id": "N08",
            "pool_riggers": False,
            "calendars": [
                {"id": "DAY", "daily_windows": [[14, 24], [25, 34]]},
                {"id": "NIGHT", "daily_windows": [[36, 48]]},
            ],
            "resources": [],
            "resource_groups": [],
            "activities": activities,
        },
        "reports": [],
        "approved_plan": None,
        "proposal": None,
        "plan_history": [],
    }
    validate(workspace)
    return workspace


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
