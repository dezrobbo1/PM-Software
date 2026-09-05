from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from deterministic_scheduling_core.adapters.msproject_xml import (
    UNIT_SCALE,
    ImportedDecisionArea,
    import_mspdi_decision_area,
)
from deterministic_scheduling_core.errors import SchedulingError
from deterministic_scheduling_core.scheduling import (
    CapacityConflict,
    ScheduleResult,
    schedule_project,
    source_capacity_conflicts as native_source_capacity_conflicts,
)

DEFAULT_SCOPE = "Remove Calciner Isolation Blanks"
DEFAULT_HANDOFF = "Stage 2 Detag Complete"


@dataclass(frozen=True, slots=True)
class WorkspaceResult:
    source: ImportedDecisionArea
    conflicts: tuple[CapacityConflict, ...]
    schedule: ScheduleResult

    @property
    def revised_handoff(self) -> int:
        return self.schedule.objective_finish

    @property
    def solver_status(self) -> str:
        return self.schedule.solver_status

    @property
    def movements(self):
        project = self.source.project
        return tuple(
            entry
            for entry in self.schedule.entries
            if project.activity_by_id[entry.activity_id].planned_start is not None
            and entry.start != project.activity_by_id[entry.activity_id].planned_start
        )


def load_workspace(
    source_path: str | Path,
    *,
    scope_name: str = DEFAULT_SCOPE,
    handoff_name: str = DEFAULT_HANDOFF,
) -> ImportedDecisionArea:
    """Import a bounded MSPDI area into PM-Software's native project model."""

    return import_mspdi_decision_area(
        source_path,
        scope_name=scope_name,
        handoff_name=handoff_name,
    )


def source_capacity_conflicts(workspace: ImportedDecisionArea) -> tuple[CapacityConflict, ...]:
    return native_source_capacity_conflicts(workspace.project)


def run_workspace(
    source_path: str | Path,
    *,
    scope_name: str = DEFAULT_SCOPE,
    handoff_name: str = DEFAULT_HANDOFF,
) -> WorkspaceResult:
    imported = load_workspace(
        source_path,
        scope_name=scope_name,
        handoff_name=handoff_name,
    )
    return WorkspaceResult(
        source=imported,
        conflicts=native_source_capacity_conflicts(imported.project),
        schedule=schedule_project(imported.project),
    )


def _clock(workspace: ImportedDecisionArea, minute: int) -> str:
    return (workspace.origin + timedelta(minutes=minute)).strftime("%Y-%m-%d %H:%M")


def _units(value: int) -> str:
    return f"{value / UNIT_SCALE:g}"


def render_workspace(result: WorkspaceResult) -> str:
    imported = result.source
    project = imported.project
    objective = project.activity_by_id[project.objective_activity_id]
    handoff_source = objective.planned_start
    if handoff_source is None:
        raise SchedulingError("imported controlling handoff has no planned start")

    lines = [
        "PROTOTYPE 1 — REAL SCHEDULE DECISION WORKSPACE",
        "Architecture: MSPDI adapter -> PM-Software native project -> native scheduler",
        f"Project: {project.name}",
        f"Source: {imported.source_path}",
        f"Decision area: {imported.scope_name}",
        f"Activities: {len(project.activities) - 1}",
        "",
        "RESOURCE CONFLICTS IN SOURCE PLAN",
    ]
    if not result.conflicts:
        lines.append("- none detected in the selected decision area")
    else:
        for conflict in result.conflicts:
            names = [project.activity_by_id[activity_id].name for activity_id in conflict.activity_ids]
            lines.extend(
                (
                    conflict.resource_name,
                    f"  Window: {_clock(imported, conflict.start)} -> {_clock(imported, conflict.finish)}",
                    f"  Required: {_units(conflict.demand)}",
                    f"  Available: {_units(conflict.capacity)}",
                    "  Active work: " + "; ".join(names),
                )
            )

    lines.extend(("", "PROPOSED REVISION"))
    if not result.movements:
        lines.append("- no activity movement required")
    else:
        for entry in result.movements:
            activity = project.activity_by_id[entry.activity_id]
            planned = activity.planned_start
            if planned is None:
                continue
            lines.extend(
                (
                    activity.name,
                    f"  {_clock(imported, planned)} -> {_clock(imported, entry.start)} (+{entry.start - planned} min)",
                )
            )

    handoff_delay = result.revised_handoff - handoff_source
    lines.extend(
        (
            "",
            imported.handoff_name,
            f"  Source: {_clock(imported, handoff_source)}",
            f"  Revised: {_clock(imported, result.revised_handoff)} "
            + ("UNCHANGED" if handoff_delay == 0 else f"(+{handoff_delay} min)"),
            "",
            "PROJECT COMPLETION IMPACT",
        )
    )
    if handoff_delay == 0:
        lines.append(
            "UNCHANGED — controlling handoff is preserved; work outside the bounded decision area is not rescheduled. "
            f"Source project finish remains {imported.source_project_finish:%Y-%m-%d %H:%M} for this accepted case."
        )
    else:
        lines.append(
            f"AT RISK — controlling handoff moves by +{handoff_delay} min; source project finish is "
            f"{imported.source_project_finish:%Y-%m-%d %H:%M}."
        )

    lines.extend(
        (
            "",
            f"Activities moved: {len(result.movements)}",
            f"Solver: {result.solver_status}",
            "Microsoft Project fields are confined to the adapter; the scheduler consumes only the native PM-Software project model.",
        )
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Import one MSPDI decision area, then schedule the PM-Software native model."
    )
    parser.add_argument("xml", help="Path to Microsoft Project XML/MSPDI file")
    parser.add_argument("--scope", default=DEFAULT_SCOPE, help="Exact summary-task name")
    parser.add_argument("--handoff", default=DEFAULT_HANDOFF, help="Exact controlling handoff name")
    args = parser.parse_args(argv)
    try:
        result = run_workspace(args.xml, scope_name=args.scope, handoff_name=args.handoff)
    except SchedulingError as exc:
        parser.error(str(exc))
    print(render_workspace(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
