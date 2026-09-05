from __future__ import annotations

import argparse
from pathlib import Path

from deterministic_scheduling_core.project import (
    Activity,
    ExecutionMode,
    Project,
    Resource,
    ResourceRequirement,
    load_project,
    replace_mode_duration,
    save_project,
)
from deterministic_scheduling_core.scheduling import ScheduleResult, schedule_project


def _fixed(mode_id: str, duration: int, *resources: str) -> tuple[ExecutionMode, ...]:
    return (
        ExecutionMode(
            mode_id,
            duration,
            tuple(ResourceRequirement(resource) for resource in resources),
        ),
    )


def build_native_demo_project() -> Project:
    """Create a project entirely in PM-Software's native model."""

    normal = ExecutionMode(
        "NORMAL",
        8,
        (ResourceRequirement("MECH"),),
        "Normal repair",
    )
    accelerated = ExecutionMode(
        "ACCELERATED",
        5,
        (ResourceRequirement("MECH"), ResourceRequirement("SPEC")),
        "Specialist-assisted repair",
    )
    return Project(
        id="native-demo",
        name="Native decision project",
        resources=(Resource("MECH", "Mechanical crew"), Resource("SPEC", "Specialist")),
        activities=(
            Activity("N01", "Release workfront", _fixed("FIXED", 1)),
            Activity("N02", "Repair exchanger", (normal, accelerated), ("N01",)),
            Activity("N03", "Post-repair cure", _fixed("FIXED", 8), ("N02",)),
            Activity("N04", "Inspect protection system", _fixed("FIXED", 6, "SPEC"), ("N01",)),
            Activity("N05", "Protection-system corrective work", _fixed("FIXED", 10), ("N04",)),
            Activity("N06", "Reinstate plant", _fixed("FIXED", 1, "MECH"), ("N03", "N05")),
            Activity("N07", "Return to service", _fixed("FIXED", 1), ("N06",)),
            Activity(
                "N08",
                "Project complete",
                _fixed("MILESTONE", 0),
                ("N07",),
                kind="milestone",
            ),
        ),
        objective_activity_id="N08",
        time_unit="hour",
    )


def _mode(result: ScheduleResult, activity_id: str) -> str:
    return result.by_id[activity_id].mode_id


def run_native_demo(path: str | Path) -> tuple[ScheduleResult, ScheduleResult, Path, Path]:
    """Save, reopen, schedule, edit and reschedule a native project."""

    native_path = Path(path)
    project = build_native_demo_project()
    save_project(project, native_path)
    reopened = load_project(native_path)
    first = schedule_project(reopened)

    changed = replace_mode_duration(reopened, "N05", "FIXED", 2)
    modified_path = native_path.with_name(f"{native_path.stem}.modified{native_path.suffix}")
    save_project(changed, modified_path)
    second = schedule_project(load_project(modified_path))
    return first, second, native_path, modified_path


def render_demo(
    first: ScheduleResult,
    second: ScheduleResult,
    native_path: Path,
    modified_path: Path,
) -> str:
    return "\n".join(
        (
            "PROTOTYPE 2 — NATIVE PROJECT CORE",
            "External scheduling format required: none",
            f"Native project saved: {native_path}",
            f"Native project reopened: {first.project.name}",
            "",
            "INITIAL PROJECT",
            f"Repair mode: {_mode(first, 'N02')}",
            f"Project finish: H{first.objective_finish}",
            "",
            "EDIT",
            "Protection-system corrective work duration: 10h -> 2h",
            f"Modified native project saved: {modified_path}",
            "",
            "RECALCULATED PROJECT",
            f"Repair mode: {_mode(second, 'N02')}",
            f"Project finish: H{second.objective_finish}",
            "",
            "Learning: PM-Software can create, persist, reopen, modify and optimise its own project without Microsoft Project or P6 in the workflow.",
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run Prototype 2 using only PM-Software's native project model."
    )
    parser.add_argument("path", help="Path for the native JSON project created by the demo")
    args = parser.parse_args(argv)
    first, second, native_path, modified_path = run_native_demo(args.path)
    print(render_demo(first, second, native_path, modified_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
