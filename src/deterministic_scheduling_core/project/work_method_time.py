"""Portable, future-only composition of two existing native model vocabularies.

WorkPackage/ExecutionMethod own structure; the productive project's existing
processing_ticks/calendars/requirements own execution. This is not an accepted-
progress workspace and does not migrate or reinterpret any older native file.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from itertools import product
import json
from pathlib import Path
from typing import Any, Iterator

from .model import Activity, ExecutionMethod, ExecutionMode, Project, WorkPackage
from .planning_workspace import GROUP_SCHEMA, SCHEMA, digest

DOCUMENT_SCHEMA = "pm-native-work-method-time/0"


@dataclass(frozen=True)
class WorkMethodTimeProject:
    """Existing productive project definitions plus authorised native structure.

    `project.activities` contains the union of method activities, not a selected
    executable network. `reports` retains the existing REPORTED/ACCEPTED outage
    records; only ACCEPTED records affect execution opportunities. No actuals,
    reference approvals or recovery-policy semantics belong to this profile.
    """

    project: dict[str, Any]
    work_packages: tuple[WorkPackage, ...] = ()
    reports: tuple[dict[str, Any], ...] = ()


def to_document(problem: WorkMethodTimeProject) -> dict:
    """Copy the portable input without selecting structure or calling a solver."""
    return json.loads(json.dumps({
        "schema": DOCUMENT_SCHEMA,
        "project": problem.project,
        "work_packages": [asdict(package) for package in problem.work_packages],
        "reports": problem.reports,
    }))


def from_document(document: dict) -> WorkMethodTimeProject:
    """Decode this profile only; scheduling admission performs semantic validation."""
    if not isinstance(document, dict) or set(document) != {
        "schema", "project", "work_packages", "reports"
    } or document["schema"] != DOCUMENT_SCHEMA:
        raise ValueError(f"expected an exact {DOCUMENT_SCHEMA} document")
    if not isinstance(document["project"], dict) or not isinstance(document["reports"], list):
        raise ValueError("project must be an object and reports an array")
    if not isinstance(document["work_packages"], list):
        raise ValueError("work_packages must be an array")
    packages = []
    for package in document["work_packages"]:
        if not isinstance(package, dict) or set(package) != {"id", "name", "methods", "predecessors"}:
            raise ValueError("unsupported work-package fields")
        if not isinstance(package["methods"], list) or not isinstance(package["predecessors"], list):
            raise ValueError("methods and package predecessors must be arrays")
        methods = []
        for method in package["methods"]:
            if not isinstance(method, dict) or set(method) != {
                "id", "name", "activity_ids", "completion_activity_id"
            } or not isinstance(method["activity_ids"], list):
                raise ValueError("unsupported execution-method fields")
            methods.append(ExecutionMethod(method["id"], method["name"],
                                           tuple(method["activity_ids"]), method["completion_activity_id"]))
        packages.append(WorkPackage(package["id"], package["name"], tuple(methods),
                                    tuple(package["predecessors"])))
    return WorkMethodTimeProject(deepcopy(document["project"]), tuple(packages),
                                 tuple(deepcopy(document["reports"])))


def save(problem: WorkMethodTimeProject, path: str | Path) -> None:
    Path(path).write_text(json.dumps(to_document(problem), indent=2) + "\n", encoding="utf-8")


def load(path: str | Path) -> WorkMethodTimeProject:
    return from_document(json.loads(Path(path).read_text(encoding="utf-8")))


def input_hash(problem: WorkMethodTimeProject) -> str:
    """Hash the complete input document, not a trusted-workspace or approval hash."""
    return digest(to_document(problem))


def structural_view(problem: WorkMethodTimeProject) -> Project:
    """Validation-only view using the existing native structural contract.

    No elapsed-time scheduler is called with this view. The sole execution-work
    source remains each native mode's processing_ticks in the productive input.
    Resource/calendar validation uses the existing productive project validator.
    """
    source = problem.project
    return Project(
        source["id"], source["name"],
        tuple(Activity(a["id"], a["name"],
                       tuple(ExecutionMode(m["id"], m["processing_ticks"]) for m in a["modes"]),
                       predecessors=tuple(a.get("predecessors", [])),
                       not_before=a.get("not_before", 0)) for a in source["activities"]),
        objective_activity_id=source["objective_activity_id"],
        time_unit="30-minute tick", work_packages=problem.work_packages,
    )


def method_selections(problem: WorkMethodTimeProject) -> Iterator[dict[str, str]]:
    """Finite structural projections for admission/control, never candidate solves."""
    for methods in product(*(package.methods for package in problem.work_packages)):
        yield {package.id: method.id for package, method in zip(problem.work_packages, methods)}


def membership(problem: WorkMethodTimeProject) -> dict[str, tuple[str, str]]:
    return {aid: (package.id, method.id) for package in problem.work_packages
            for method in package.methods for aid in method.activity_ids}


def materialise(problem: WorkMethodTimeProject, selected: dict[str, str]) -> dict:
    """Make an ordinary productive workspace for one explicitly selected structure.

    Package arcs become FS arcs from the selected predecessor completion to every
    root of the selected successor method. Definitions in `problem` never change.
    This projection is also used for independent whole-plan physical validation.
    """
    if not isinstance(selected, dict) or set(selected) != {p.id for p in problem.work_packages}:
        raise ValueError("select exactly one method for every work package")
    chosen = {}
    for package in problem.work_packages:
        if selected[package.id] not in package.method_by_id:
            raise ValueError(f"{package.id}: unauthorised method")
        chosen[package.id] = package.method_by_id[selected[package.id]]
    members = membership(problem)
    active = {a["id"] for a in problem.project["activities"] if a["id"] not in members}
    active.update(aid for method in chosen.values() for aid in method.activity_ids)
    project = deepcopy(problem.project)
    project["activities"] = [a for a in project["activities"] if a["id"] in active]
    by_id = {a["id"]: a for a in project["activities"]}
    for package in problem.work_packages:
        method = chosen[package.id]
        ids = set(method.activity_ids)
        for aid in method.activity_ids:
            activity = by_id[aid]
            predecessors = list(activity.get("predecessors", []))
            if not set(predecessors) & ids:
                predecessors.extend(chosen[p].completion_activity_id for p in package.predecessors)
            activity["predecessors"] = list(dict.fromkeys(predecessors))
    return {"schema": GROUP_SCHEMA if "resource_groups" in project else SCHEMA,
            "project": project, "reports": deepcopy(list(problem.reports)),
            "proposal": None, "approved_plan": None, "plan_history": []}
