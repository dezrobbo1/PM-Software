import tempfile
import unittest
from pathlib import Path

from deterministic_scheduling_core.prototype1_workspace import (
    DEFAULT_HANDOFF,
    DEFAULT_SCOPE,
    load_workspace,
    render_workspace,
    run_workspace,
    source_capacity_conflicts,
)


MSPDI_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<Project xmlns="http://schemas.microsoft.com/project">
  <Name>prototype1-test.xml</Name>
  <Title>Prototype 1 Test</Title>
  <FinishDate>2026-01-02T12:00:00</FinishDate>
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
  <Resources>
    <Resource><UID>1</UID><Name>WGP-NTP</Name><MaxUnits>2.00</MaxUnits></Resource>
    <Resource><UID>2</UID><Name>WGP-MTP</Name><MaxUnits>1.00</MaxUnits></Resource>
  </Resources>
  <Assignments>
    <Assignment><UID>101</UID><TaskUID>11</TaskUID><ResourceUID>1</ResourceUID><Units>1</Units></Assignment>
    <Assignment><UID>102</UID><TaskUID>12</TaskUID><ResourceUID>1</ResourceUID><Units>1</Units></Assignment>
    <Assignment><UID>103</UID><TaskUID>13</TaskUID><ResourceUID>1</ResourceUID><Units>1</Units></Assignment>
    <Assignment><UID>104</UID><TaskUID>14</TaskUID><ResourceUID>2</ResourceUID><Units>1</Units></Assignment>
  </Assignments>
</Project>
"""


class Prototype1WorkspaceTests(unittest.TestCase):
    def setUp(self) -> None:
        handle = tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False)
        handle.write(MSPDI_FIXTURE)
        handle.close()
        self.path = Path(handle.name)

    def tearDown(self) -> None:
        self.path.unlink(missing_ok=True)

    def test_imports_into_native_project_model(self) -> None:
        workspace = load_workspace(self.path)
        self.assertEqual(workspace.scope_name, DEFAULT_SCOPE)
        self.assertEqual(workspace.handoff_name, DEFAULT_HANDOFF)
        self.assertEqual(len(workspace.project.activities) - 1, 4)
        self.assertEqual(
            {resource.name for resource in workspace.project.resources},
            {"WGP-NTP", "WGP-MTP"},
        )

    def test_detects_declared_source_overload(self) -> None:
        workspace = load_workspace(self.path)
        conflicts = source_capacity_conflicts(workspace)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0].resource_name, "WGP-NTP")
        self.assertEqual(conflicts[0].demand, 300)
        self.assertEqual(conflicts[0].capacity, 200)
        self.assertEqual((conflicts[0].start, conflicts[0].finish), (0, 60))

    def test_replan_removes_overload_without_moving_handoff(self) -> None:
        result = run_workspace(self.path)
        objective = result.source.project.activity_by_id[
            result.source.project.objective_activity_id
        ]
        self.assertEqual(result.revised_handoff, objective.planned_start)
        self.assertEqual(len(result.movements), 1)
        moved = result.movements[0]
        activity = result.source.project.activity_by_id[moved.activity_id]
        self.assertEqual(moved.start - activity.planned_start, 60)

    def test_output_exposes_native_boundary_and_project_impact(self) -> None:
        output = render_workspace(run_workspace(self.path))
        self.assertIn("REAL SCHEDULE DECISION WORKSPACE", output)
        self.assertIn("MSPDI adapter -> PM-Software native project -> native scheduler", output)
        self.assertIn("WGP-NTP", output)
        self.assertIn("Required: 3", output)
        self.assertIn("Available: 2", output)
        self.assertIn("Stage 2 Detag Complete", output)
        self.assertIn("UNCHANGED", output)
        self.assertIn("PROJECT COMPLETION IMPACT", output)


if __name__ == "__main__":
    unittest.main()
