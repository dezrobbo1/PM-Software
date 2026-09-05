import tempfile
import unittest
from pathlib import Path

from deterministic_scheduling_core.adapters.msproject_xml import import_mspdi_decision_area
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
from deterministic_scheduling_core.prototype2_native import build_native_demo_project
from deterministic_scheduling_core.scheduling import schedule_project, source_capacity_conflicts


MSPDI_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<Project xmlns="http://schemas.microsoft.com/project">
  <Name>native-adapter-test.xml</Name><Title>Native Adapter Test</Title><FinishDate>2026-01-02T12:00:00</FinishDate>
  <Tasks>
    <Task><UID>10</UID><ID>1</ID><Name>Remove Calciner Isolation Blanks</Name><WBS>1</WBS><Summary>1</Summary><Start>2026-01-01T06:00:00</Start><Finish>2026-01-01T10:00:00</Finish></Task>
    <Task><UID>11</UID><ID>2</ID><Name>Work A</Name><WBS>1.1</WBS><Summary>0</Summary><Start>2026-01-01T06:00:00</Start><Finish>2026-01-01T07:00:00</Finish></Task>
    <Task><UID>12</UID><ID>3</ID><Name>Work B</Name><WBS>1.2</WBS><Summary>0</Summary><Start>2026-01-01T06:00:00</Start><Finish>2026-01-01T07:00:00</Finish></Task>
    <Task><UID>13</UID><ID>4</ID><Name>Long work</Name><WBS>1.3</WBS><Summary>0</Summary><Start>2026-01-01T06:00:00</Start><Finish>2026-01-01T08:00:00</Finish></Task>
    <Task><UID>14</UID><ID>5</ID><Name>Follow-on</Name><WBS>1.4</WBS><Summary>0</Summary><Start>2026-01-01T08:00:00</Start><Finish>2026-01-01T09:00:00</Finish><PredecessorLink><PredecessorUID>13</PredecessorUID><Type>1</Type><LinkLag>0</LinkLag></PredecessorLink></Task>
    <Task><UID>20</UID><ID>6</ID><Name>Stage 2 Detag Complete</Name><WBS>2</WBS><Summary>0</Summary><Start>2026-01-01T10:00:00</Start><Finish>2026-01-01T10:00:00</Finish>
      <PredecessorLink><PredecessorUID>11</PredecessorUID><Type>1</Type><LinkLag>0</LinkLag></PredecessorLink>
      <PredecessorLink><PredecessorUID>12</PredecessorUID><Type>1</Type><LinkLag>0</LinkLag></PredecessorLink>
      <PredecessorLink><PredecessorUID>14</PredecessorUID><Type>1</Type><LinkLag>0</LinkLag></PredecessorLink>
    </Task>
  </Tasks>
  <Resources><Resource><UID>1</UID><Name>WGP-NTP</Name><MaxUnits>2.00</MaxUnits></Resource><Resource><UID>2</UID><Name>WGP-MTP</Name><MaxUnits>1.00</MaxUnits></Resource></Resources>
  <Assignments>
    <Assignment><UID>101</UID><TaskUID>11</TaskUID><ResourceUID>1</ResourceUID><Units>1</Units></Assignment>
    <Assignment><UID>102</UID><TaskUID>12</TaskUID><ResourceUID>1</ResourceUID><Units>1</Units></Assignment>
    <Assignment><UID>103</UID><TaskUID>13</TaskUID><ResourceUID>1</ResourceUID><Units>1</Units></Assignment>
    <Assignment><UID>104</UID><TaskUID>14</TaskUID><ResourceUID>2</ResourceUID><Units>1</Units></Assignment>
  </Assignments>
</Project>
"""


def fixed(mode_id: str, duration: int, *resources: str) -> tuple[ExecutionMode, ...]:
    return (
        ExecutionMode(
            mode_id,
            duration,
            tuple(ResourceRequirement(resource) for resource in resources),
        ),
    )


class NativeProjectCoreTests(unittest.TestCase):
    def test_native_project_round_trip_and_schedule_need_no_external_format(self) -> None:
        project = build_native_demo_project()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "project.json"
            save_project(project, path)
            reopened = load_project(path)
        self.assertEqual(reopened, project)
        result = schedule_project(reopened)
        self.assertEqual(result.by_id["N02"].mode_id, "NORMAL")
        self.assertEqual(result.objective_finish, 19)

    def test_native_edit_changes_whole_project_mode_choice(self) -> None:
        project = build_native_demo_project()
        changed = replace_mode_duration(project, "N05", "FIXED", 2)
        result = schedule_project(changed)
        self.assertEqual(result.by_id["N02"].mode_id, "ACCELERATED")
        self.assertEqual(result.objective_finish, 16)

    def test_operational_window_and_workface_are_native_constraints(self) -> None:
        project = Project(
            id="ops",
            name="Operational native project",
            resources=(Resource("CRANE", "Crane"),),
            activities=(
                Activity("A", "Release", fixed("FIXED", 1)),
                Activity("B", "Strip scaffold", fixed("FIXED", 4), ("A",), exclusion_groups=("WF",)),
                Activity(
                    "C",
                    "Lift spool",
                    fixed("FIXED", 3, "CRANE"),
                    ("A",),
                    not_before=4,
                    latest_finish=9,
                    exclusion_groups=("WF",),
                ),
                Activity("D", "Done", fixed("MILESTONE", 0), ("B", "C"), kind="milestone"),
            ),
            objective_activity_id="D",
        )
        result = schedule_project(project)
        self.assertEqual((result.by_id["B"].start, result.by_id["B"].finish), (1, 5))
        self.assertEqual((result.by_id["C"].start, result.by_id["C"].finish), (5, 8))
        self.assertEqual(result.objective_finish, 8)

    def test_mspdi_is_only_an_adapter_into_native_model(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False) as handle:
            handle.write(MSPDI_FIXTURE)
            path = Path(handle.name)
        try:
            imported = import_mspdi_decision_area(
                path,
                scope_name="Remove Calciner Isolation Blanks",
                handoff_name="Stage 2 Detag Complete",
            )
        finally:
            path.unlink(missing_ok=True)
        self.assertIsInstance(imported.project, Project)
        conflicts = source_capacity_conflicts(imported.project)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0].resource_name, "WGP-NTP")
        self.assertEqual((conflicts[0].demand, conflicts[0].capacity), (300, 200))
        result = schedule_project(imported.project)
        objective = imported.project.activity_by_id[imported.project.objective_activity_id]
        self.assertEqual(result.objective_finish, objective.planned_start)
        moved = [
            entry
            for entry in result.entries
            if imported.project.activity_by_id[entry.activity_id].planned_start is not None
            and entry.start != imported.project.activity_by_id[entry.activity_id].planned_start
        ]
        self.assertEqual(len(moved), 1)


if __name__ == "__main__":
    unittest.main()
