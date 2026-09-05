from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
import xml.etree.ElementTree as ET

from deterministic_scheduling_core.errors import SchedulingError
from deterministic_scheduling_core.project.model import (
    Activity,
    ExecutionMode,
    Project,
    Resource,
    ResourceRequirement,
)

MSPDI_NS = "http://schemas.microsoft.com/project"
NS = {"m": MSPDI_NS}
UNIT_SCALE = 100


@dataclass(frozen=True, slots=True)
class ImportedDecisionArea:
    project: Project
    source_path: Path
    origin: datetime
    scope_name: str
    handoff_name: str
    source_project_finish: datetime


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


def _validate_zero_lag_fs(link: ET.Element, context: str) -> None:
    relationship_type = _text(link, "Type", "1")
    lag = _text(link, "LinkLag", "0")
    if relationship_type != "1" or lag != "0":
        raise SchedulingError(
            f"{context}: bounded MSPDI adapter currently supports only zero-lag FS links"
        )


def import_mspdi_decision_area(
    source_path: str | Path,
    *,
    scope_name: str,
    handoff_name: str,
) -> ImportedDecisionArea:
    """Translate one bounded MSPDI decision area into the native PM model.

    Microsoft Project fields stop at this adapter boundary. The scheduling engine
    receives only :class:`Project` and has no MSPDI dependency.
    """

    path = Path(source_path)
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise SchedulingError(f"cannot read MSPDI XML {path}: {exc}") from exc
    if root.tag != f"{{{MSPDI_NS}}}Project":
        raise SchedulingError("expected Microsoft Project MSPDI XML")

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
    resource_by_uid = {
        _required_text(resource, "UID", "resource"): resource
        for resource in resources
    }
    assignments_by_task: dict[str, list[ET.Element]] = {}
    for assignment in assignments:
        task_uid = _text(assignment, "TaskUID")
        if task_uid in selected_uids:
            assignments_by_task.setdefault(task_uid, []).append(assignment)

    origin = min(
        _parse_datetime(_required_text(task, "Start", "task"), "task Start")
        for task in selected
    )

    used_resources: set[str] = set()
    native_activities: list[Activity] = []
    for task in selected:
        uid = _required_text(task, "UID", "task")
        name = _required_text(task, "Name", uid)
        start = _parse_datetime(_required_text(task, "Start", name), f"{name} Start")
        finish = _parse_datetime(_required_text(task, "Finish", name), f"{name} Finish")
        duration = int((finish - start).total_seconds() // 60)
        if duration < 0:
            raise SchedulingError(f"{name}: finish precedes start")
        planned_start = int((start - origin).total_seconds() // 60)

        predecessors: list[str] = []
        for link in task.findall("m:PredecessorLink", NS):
            predecessor_uid = _text(link, "PredecessorUID")
            if predecessor_uid in selected_uids:
                _validate_zero_lag_fs(link, name)
                predecessors.append(predecessor_uid)

        requirements: list[ResourceRequirement] = []
        for assignment in assignments_by_task.get(uid, []):
            resource_uid = _required_text(assignment, "ResourceUID", name)
            resource = resource_by_uid.get(resource_uid)
            if resource is None:
                raise SchedulingError(f"{name}: unknown resource UID {resource_uid}")
            demand = _scaled_units(_text(assignment, "Units"), f"{name}/{resource_uid}")
            requirements.append(ResourceRequirement(resource_uid, demand))
            used_resources.add(resource_uid)

        native_activities.append(
            Activity(
                id=uid,
                name=name,
                modes=(
                    ExecutionMode(
                        id="SOURCE",
                        name="Imported source method",
                        duration=duration,
                        requirements=tuple(requirements),
                    ),
                ),
                predecessors=tuple(predecessors),
                not_before=planned_start,
                planned_start=planned_start,
                planned_mode_id="SOURCE",
            )
        )

    native_resources = tuple(
        Resource(
            id=resource_uid,
            name=_required_text(resource_by_uid[resource_uid], "Name", resource_uid),
            capacity=_scaled_units(
                _text(resource_by_uid[resource_uid], "MaxUnits"),
                _required_text(resource_by_uid[resource_uid], "Name", resource_uid),
            ),
        )
        for resource_uid in sorted(used_resources, key=lambda value: int(value))
    )

    handoff_start_dt = _parse_datetime(
        _required_text(handoff, "Start", handoff_name), f"{handoff_name} Start"
    )
    handoff_start = int((handoff_start_dt - origin).total_seconds() // 60)
    handoff_predecessors: list[str] = []
    for link in handoff.findall("m:PredecessorLink", NS):
        predecessor_uid = _text(link, "PredecessorUID")
        if predecessor_uid in selected_uids:
            _validate_zero_lag_fs(link, handoff_name)
            handoff_predecessors.append(predecessor_uid)
    if not handoff_predecessors:
        raise SchedulingError(
            f"{handoff_name!r}: no predecessor links from selected decision area"
        )
    handoff_uid = _required_text(handoff, "UID", handoff_name)
    native_activities.append(
        Activity(
            id=handoff_uid,
            name=handoff_name,
            kind="milestone",
            modes=(ExecutionMode("MILESTONE", 0, name="Milestone"),),
            predecessors=tuple(handoff_predecessors),
            not_before=handoff_start,
            planned_start=handoff_start,
            planned_mode_id="MILESTONE",
        )
    )

    source_finish = _parse_datetime(
        _required_text(root, "FinishDate", "Project"), "Project FinishDate"
    )
    project_name = _text(root, "Title") or _text(root, "Name") or path.name
    native_project = Project(
        id=f"mspdi:{path.stem}:{scope_name}",
        name=project_name,
        activities=tuple(native_activities),
        resources=native_resources,
        objective_activity_id=handoff_uid,
        time_unit="minute",
    )
    return ImportedDecisionArea(
        project=native_project,
        source_path=path,
        origin=origin,
        scope_name=scope_name,
        handoff_name=handoff_name,
        source_project_finish=source_finish,
    )
