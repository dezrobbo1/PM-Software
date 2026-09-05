from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
import xml.etree.ElementTree as ET

from ortools.sat.python import cp_model

from deterministic_scheduling_core.errors import SchedulingError


MSPDI_NS = "http://schemas.microsoft.com/project"
NS = {"m": MSPDI_NS}
DEFAULT_SCOPE = "Remove Calciner Isolation Blanks"
DEFAULT_HANDOFF = "Stage 2 Detag Complete"
UNIT_SCALE = 100


@dataclass(frozen=True, slots=True)
class ResourceUse:
    uid: str
    name: str
    demand: int


@dataclass(frozen=True, slots=True)
class WorkspaceActivity:
    uid: str
    source_id: int
    name: str
    source_start: int
    duration: int
    predecessors: tuple[str, ...]
    resources: tuple[ResourceUse, ...]


@dataclass(frozen=True, slots=True)
class WorkspaceResource:
    uid: str
    name: str
    capacity: int


@dataclass(frozen=True, slots=True)
class WorkspaceInput:
    source_path: Path
    project_name: str
    project_finish: datetime
    scope_name: str
    handoff_name: str
    origin: datetime
    handoff_source: int
    handoff_predecessors: tuple[str, ...]
    activities: tuple[WorkspaceActivity, ...]
    resources: tuple[WorkspaceResource, ...]

    @property
    def activity_by_uid(self) -> dict[str, WorkspaceActivity]:
        return {activity.uid: activity for activity in self.activities}

    @property
    def resource_by_uid(self) -> dict[str, WorkspaceResource]:
        return {resource.uid: resource for resource in self.resources}


@dataclass(frozen=True, slots=True)
class CapacityConflict:
    resource_uid: str
    resource_name: str
    start: int
    finish: int
    demand: int
    capacity: int
    activity_names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ScheduledActivity:
    activity: WorkspaceActivity
    start: int
    finish: int


@dataclass(frozen=True, slots=True)
class WorkspaceResult:
    source: WorkspaceInput
    conflicts: tuple[CapacityConflict, ...]
    entries: tuple[ScheduledActivity, ...]
    revised_handoff: int
    solver_status: str

    @property
    def by_uid(self) -> dict[str, ScheduledActivity]:
        return {entry.activity.uid: entry for entry in self.entries}

    @property
    def movements(self) -> tuple[ScheduledActivity, ...]:
        return tuple(
            entry
            for entry in self.entries
            if entry.start != entry.activity.source_start
        )


def _text(element: ET.Element, tag: str, default: str | None = None) -> str | None:
    child = element.find(f"m:{tag}", NS)
    if child is None or child.text is None:
        return default
    return child.text


def _required_text(element: ET.Element, tag: str, context: str) -> str:
    value = _text(element, tag)
    if value is None:
        raise SchedulingError(f"{context}: missing {tag}")
    return value


def _parse_datetime(value: str, context: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise SchedulingError(f"{context}: invalid datetime {value!r}") from exc


def _scaled_units(value: str | None, context: str) -> int:
    if value is None:
        raise SchedulingError(f"{context}: missing units")
    try:
        scaled = Decimal(value) * UNIT_SCALE
    except InvalidOperation as exc:
        raise SchedulingError(f"{context}: invalid units {value!r}") from exc
    integral = scaled.to_integral_value()
    if scaled != integral or integral <= 0:
        raise SchedulingError(f"{context}: unsupported units {value!r}")
    return int(integral)


def _find_unique_task(tasks: tuple[ET.Element, ...], name: str) -> ET.Element:
    matches = [task for task in tasks if _text(task, "Name", "") == name]
    if len(matches) != 1:
        raise SchedulingError(
            f"expected exactly one task named {name!r}; found {len(matches)}"
        )
    return matches[0]


def _validate_internal_link(link: ET.Element, context: str) -> None:
    relationship_type = _text(link, "Type", "1")
    lag = _text(link, "LinkLag", "0")
    if relationship_type != "1" or lag != "0":
        raise SchedulingError(
            f"{context}: Prototype 1 currently supports only zero-lag FS links "
            f"inside the selected decision area"
        )


def load_workspace(
    source_path: str | Path,
    *,
    scope_name: str = DEFAULT_SCOPE,
    handoff_name: str = DEFAULT_HANDOFF,
) -> WorkspaceInput:
    path = Path(source_path)
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise SchedulingError(f"cannot read MSPDI XML {path}: {exc}") from exc

    if root.tag != f"{{{MSPDI_NS}}}Project":
        raise SchedulingError("Prototype 1 expects Microsoft Project MSPDI XML")

    tasks = tuple(root.findall("./m:Tasks/m:Task", NS))
    resources = tuple(root.findall("./m:Resources/m:Resource", NS))
    assignments = tuple(root.findall("./m:Assignments/m:Assignment", NS))

    scope = _find_unique_task(tasks, scope_name)
    handoff = _find_unique_task(tasks, handoff_name)
    scope_wbs = _required_text(scope, "WBS", scope_name)

    selected = tuple(
        task
        for task in tasks
        if _text(task, "Summary", "0") == "0"
        and (_text(task, "WBS", "") or "").startswith(f"{scope_wbs}.")
    )
    if not selected:
        raise SchedulingError(f"{scope_name!r}: no leaf activities found")

    selected_uids = {_required_text(task, "UID", scope_name) for task in selected}
    task_by_uid = {
        _required_text(task, "UID", "task"): task
        for task in tasks
    }
    resource_by_uid = {
        _required_text(resource, "UID", "resource"): resource
        for resource in resources
    }

    assignments_by_task: dict[str, list[ET.Element]] = {}
    for assignment in assignments:
        task_uid = _text(assignment, "TaskUID")
        if task_uid in selected_uids:
            assignments_by_task.setdefault(task_uid, []).append(assignment)

    starts = [
        _parse_datetime(_required_text(task, "Start", "task"), "task Start")
        for task in selected
    ]
    origin = min(starts)

    used_resource_uids: set[str] = set()
    activities: list[WorkspaceActivity] = []
    for task in selected:
        uid = _required_text(task, "UID", "task")
        name = _required_text(task, "Name", uid)
        source_id = int(_required_text(task, "ID", name))
        start = _parse_datetime(_required_text(task, "Start", name), f"{name} Start")
        finish = _parse_datetime(_required_text(task, "Finish", name), f"{name} Finish")
        duration = int((finish - start).total_seconds() // 60)
        if duration < 0:
            raise SchedulingError(f"{name}: finish precedes start")
        source_start = int((start - origin).total_seconds() // 60)

        predecessors: list[str] = []
        for link in task.findall("m:PredecessorLink", NS):
            predecessor_uid = _text(link, "PredecessorUID")
            if predecessor_uid in selected_uids:
                _validate_internal_link(link, name)
                predecessors.append(predecessor_uid)

        activity_resources: list[ResourceUse] = []
        for assignment in assignments_by_task.get(uid, []):
            resource_uid = _required_text(assignment, "ResourceUID", name)
            resource = resource_by_uid.get(resource_uid)
            if resource is None:
                raise SchedulingError(f"{name}: unknown resource UID {resource_uid}")
            resource_name = _required_text(resource, "Name", resource_uid)
            demand = _scaled_units(_text(assignment, "Units"), f"{name}/{resource_name}")
            activity_resources.append(ResourceUse(resource_uid, resource_name, demand))
            used_resource_uids.add(resource_uid)

        activities.append(
            WorkspaceActivity(
                uid=uid,
                source_id=source_id,
                name=name,
                source_start=source_start,
                duration=duration,
                predecessors=tuple(predecessors),
                resources=tuple(activity_resources),
            )
        )

    workspace_resources: list[WorkspaceResource] = []
    for resource_uid in sorted(used_resource_uids, key=int):
        resource = resource_by_uid[resource_uid]
        name = _required_text(resource, "Name", resource_uid)
        capacity = _scaled_units(_text(resource, "MaxUnits"), name)
        workspace_resources.append(WorkspaceResource(resource_uid, name, capacity))

    handoff_source_dt = _parse_datetime(
        _required_text(handoff, "Start", handoff_name), f"{handoff_name} Start"
    )
    handoff_source = int((handoff_source_dt - origin).total_seconds() // 60)
    handoff_predecessors: list[str] = []
    for link in handoff.findall("m:PredecessorLink", NS):
        predecessor_uid = _text(link, "PredecessorUID")
        if predecessor_uid in selected_uids:
            _validate_internal_link(link, handoff_name)
            handoff_predecessors.append(predecessor_uid)
    if not handoff_predecessors:
        raise SchedulingError(
            f"{handoff_name!r}: no predecessor links from the selected decision area"
        )

    project_finish = _parse_datetime(
        _required_text(root, "FinishDate", "Project"), "Project FinishDate"
    )
    project_name = _text(root, "Title") or _text(root, "Name") or path.name

    return WorkspaceInput(
        source_path=path,
        project_name=project_name,
        project_finish=project_finish,
        scope_name=scope_name,
        handoff_name=handoff_name,
        origin=origin,
        handoff_source=handoff_source,
        handoff_predecessors=tuple(handoff_predecessors),
        activities=tuple(sorted(activities, key=lambda item: item.source_id)),
        resources=tuple(workspace_resources),
    )


def source_capacity_conflicts(workspace: WorkspaceInput) -> tuple[CapacityConflict, ...]:
    conflicts: list[CapacityConflict] = []
    for resource in workspace.resources:
        relevant = [
            (activity.source_start, activity.source_start + activity.duration, use.demand, activity.name)
            for activity in workspace.activities
            for use in activity.resources
            if use.uid == resource.uid and activity.duration > 0
        ]
        if not relevant:
            continue
        points = sorted({point for start, finish, _, _ in relevant for point in (start, finish)})
        open_conflict: CapacityConflict | None = None
        for left, right in zip(points, points[1:]):
            active = [
                (demand, name)
                for start, finish, demand, name in relevant
                if start < right and finish > left
            ]
            demand = sum(item[0] for item in active)
            if demand > resource.capacity:
                names = tuple(sorted(item[1] for item in active))
                if (
                    open_conflict is not None
                    and open_conflict.finish == left
                    and open_conflict.demand == demand
                ):
                    merged_names = tuple(sorted(set(open_conflict.activity_names) | set(names)))
                    open_conflict = CapacityConflict(
                        resource.uid,
                        resource.name,
                        open_conflict.start,
                        right,
                        demand,
                        resource.capacity,
                        merged_names,
                    )
                    conflicts[-1] = open_conflict
                else:
                    open_conflict = CapacityConflict(
                        resource.uid,
                        resource.name,
                        left,
                        right,
                        demand,
                        resource.capacity,
                        names,
                    )
                    conflicts.append(open_conflict)
            else:
                open_conflict = None
    return tuple(conflicts)


def _revised_capacity_errors(
    workspace: WorkspaceInput, entries: tuple[ScheduledActivity, ...]
) -> tuple[str, ...]:
    errors: list[str] = []
    by_uid = {entry.activity.uid: entry for entry in entries}
    for activity in workspace.activities:
        entry = by_uid[activity.uid]
        if entry.start < activity.source_start:
            errors.append(f"{activity.name}: moved earlier than source readiness")
        if entry.finish - entry.start != activity.duration:
            errors.append(f"{activity.name}: duration changed")
        for predecessor_uid in activity.predecessors:
            if by_uid[predecessor_uid].finish > entry.start:
                errors.append(f"{activity.name}: predecessor finishes after revised start")

    for resource in workspace.resources:
        points = sorted(
            {
                point
                for entry in entries
                for use in entry.activity.resources
                if use.uid == resource.uid
                for point in (entry.start, entry.finish)
            }
        )
        for left, right in zip(points, points[1:]):
            demand = sum(
                use.demand
                for entry in entries
                for use in entry.activity.resources
                if use.uid == resource.uid and entry.start < right and entry.finish > left
            )
            if demand > resource.capacity:
                errors.append(
                    f"{resource.name}: revised demand {demand / UNIT_SCALE:g} exceeds "
                    f"capacity {resource.capacity / UNIT_SCALE:g} at M{left}-M{right}"
                )
    return tuple(errors)


def solve_workspace(workspace: WorkspaceInput) -> WorkspaceResult:
    horizon = max(
        workspace.handoff_source,
        max(activity.source_start + activity.duration for activity in workspace.activities),
    ) + 24 * 60

    model = cp_model.CpModel()
    starts: dict[str, cp_model.IntVar] = {}
    ends: dict[str, cp_model.IntVar] = {}
    intervals: dict[str, cp_model.IntervalVar] = {}

    for activity in workspace.activities:
        starts[activity.uid] = model.new_int_var(
            activity.source_start, horizon, f"start_{activity.uid}"
        )
        ends[activity.uid] = model.new_int_var(0, horizon, f"end_{activity.uid}")
        intervals[activity.uid] = model.new_interval_var(
            starts[activity.uid],
            activity.duration,
            ends[activity.uid],
            f"interval_{activity.uid}",
        )

    for activity in workspace.activities:
        for predecessor_uid in activity.predecessors:
            model.add(starts[activity.uid] >= ends[predecessor_uid])

    for resource in workspace.resources:
        resource_intervals: list[cp_model.IntervalVar] = []
        demands: list[int] = []
        for activity in workspace.activities:
            demand = sum(use.demand for use in activity.resources if use.uid == resource.uid)
            if demand:
                resource_intervals.append(intervals[activity.uid])
                demands.append(demand)
        if resource_intervals:
            model.add_cumulative(resource_intervals, demands, resource.capacity)

    handoff = model.new_int_var(workspace.handoff_source, horizon, "handoff")
    for predecessor_uid in workspace.handoff_predecessors:
        model.add(handoff >= ends[predecessor_uid])

    movement = sum(
        starts[activity.uid] - activity.source_start
        for activity in workspace.activities
    )
    movement_bound = len(workspace.activities) * horizon
    model.minimize(handoff * (movement_bound + 1) + movement)

    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    status = solver.solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise SchedulingError(f"Prototype 1 found no feasible revision: {solver.status_name(status)}")

    entries = tuple(
        ScheduledActivity(
            activity=activity,
            start=solver.value(starts[activity.uid]),
            finish=solver.value(ends[activity.uid]),
        )
        for activity in workspace.activities
    )
    errors = _revised_capacity_errors(workspace, entries)
    if errors:
        raise SchedulingError("; ".join(errors))

    return WorkspaceResult(
        source=workspace,
        conflicts=source_capacity_conflicts(workspace),
        entries=entries,
        revised_handoff=solver.value(handoff),
        solver_status=solver.status_name(status),
    )


def run_workspace(
    source_path: str | Path,
    *,
    scope_name: str = DEFAULT_SCOPE,
    handoff_name: str = DEFAULT_HANDOFF,
) -> WorkspaceResult:
    return solve_workspace(
        load_workspace(source_path, scope_name=scope_name, handoff_name=handoff_name)
    )


def _at(workspace: WorkspaceInput, minute: int) -> datetime:
    return workspace.origin + timedelta(minutes=minute)


def _clock(workspace: WorkspaceInput, minute: int) -> str:
    return _at(workspace, minute).strftime("%Y-%m-%d %H:%M")


def _units(value: int) -> str:
    number = value / UNIT_SCALE
    return f"{number:g}"


def render_workspace(result: WorkspaceResult) -> str:
    workspace = result.source
    lines = [
        "PROTOTYPE 1 — REAL SCHEDULE DECISION WORKSPACE",
        f"Project: {workspace.project_name}",
        f"Source: {workspace.source_path}",
        f"Decision area: {workspace.scope_name}",
        f"Activities: {len(workspace.activities)}",
        "",
        "RESOURCE CONFLICTS IN SOURCE PLAN",
    ]

    if not result.conflicts:
        lines.append("- none detected in the selected decision area")
    else:
        for conflict in result.conflicts:
            lines.extend(
                (
                    f"{conflict.resource_name}",
                    f"  Window: {_clock(workspace, conflict.start)} -> {_clock(workspace, conflict.finish)}",
                    f"  Required: {_units(conflict.demand)}",
                    f"  Available: {_units(conflict.capacity)}",
                    "  Active work: " + "; ".join(conflict.activity_names),
                )
            )

    lines.extend(("", "PROPOSED REVISION"))
    if not result.movements:
        lines.append("- no activity movement required")
    else:
        for entry in sorted(result.movements, key=lambda item: item.activity.source_id):
            delay = entry.start - entry.activity.source_start
            lines.extend(
                (
                    entry.activity.name,
                    f"  {_clock(workspace, entry.activity.source_start)} -> {_clock(workspace, entry.start)} (+{delay} min)",
                )
            )

    handoff_delay = result.revised_handoff - workspace.handoff_source
    lines.extend(
        (
            "",
            workspace.handoff_name,
            f"  Source: {_clock(workspace, workspace.handoff_source)}",
            f"  Revised: {_clock(workspace, result.revised_handoff)} "
            + ("UNCHANGED" if handoff_delay == 0 else f"(+{handoff_delay} min)"),
            "",
            "PROJECT COMPLETION IMPACT",
        )
    )
    if handoff_delay == 0:
        lines.append(
            f"UNCHANGED — controlling handoff is preserved; downstream schedule remains untouched at source project finish {workspace.project_finish:%Y-%m-%d %H:%M}."
        )
    else:
        lines.append(
            f"AT RISK — controlling handoff moves by +{handoff_delay} min; source project finish is {workspace.project_finish:%Y-%m-%d %H:%M}."
        )

    moved_uids = {entry.activity.uid for entry in result.movements}
    lines.extend(
        (
            "",
            f"Activities moved: {len(moved_uids)}",
            f"Other activities moved: 0",
            f"Solver: {result.solver_status}",
            "Source starts are treated as not-before boundaries; Prototype 1 does not reschedule work outside the selected decision area.",
        )
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run Prototype 1 against a real Microsoft Project MSPDI XML schedule."
    )
    parser.add_argument("xml", help="Path to Microsoft Project XML/MSPDI file")
    parser.add_argument("--scope", default=DEFAULT_SCOPE, help="Exact summary-task name for the bounded decision area")
    parser.add_argument("--handoff", default=DEFAULT_HANDOFF, help="Exact controlling handoff/milestone task name")
    args = parser.parse_args(argv)

    try:
        result = run_workspace(args.xml, scope_name=args.scope, handoff_name=args.handoff)
    except SchedulingError as exc:
        parser.error(str(exc))
    print(render_workspace(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
