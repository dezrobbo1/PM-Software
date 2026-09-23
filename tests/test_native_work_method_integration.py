from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from deterministic_scheduling_core.errors import SchedulingError
from deterministic_scheduling_core.native_work_method_integration import (
    build_native_structural_project,
    run_experiment,
)
from deterministic_scheduling_core.project import (
    Activity,
    ExecutionMethod,
    ExecutionMode,
    Project,
    WorkPackage,
    load_project,
    save_project,
)
from deterministic_scheduling_core.project.io import LEGACY_FORMAT
from deterministic_scheduling_core.scheduling import schedule_project
from deterministic_scheduling_core.work_method_experiment import build_case


class NativeWorkMethodIntegrationTests(unittest.TestCase):
    def test_owning_native_scheduler_matches_exhaustive_oracle_in_all_scenarios(self):
        result = run_experiment()
        self.assertFalse(result.falsified)
        by_id = {item.scenario_id: item for item in result.scenarios}

        self.assertEqual(by_id["A"].native.objective_finish, 37)
        self.assertEqual(
            by_id["A"].native.methods_by_package,
            {
                "WP-A": "ISOLATE",
                "WP-B": "SCAFFOLD",
                "WP-C": "CRANE",
                "WP-D": "NORMAL",
                "WP-E": "REINSTALL",
                "WP-F": "HANDOVER",
            },
        )
        self.assertEqual(by_id["B"].native.objective_finish, 41)
        self.assertEqual(by_id["B"].native.methods_by_package["WP-C"], "SEGMENTED")
        self.assertEqual(by_id["C"].native.objective_finish, 35)
        self.assertEqual(by_id["C"].native.methods_by_package["WP-B"], "ROPE")
        self.assertEqual(by_id["C"].native.methods_by_package["WP-D"], "SPECIALIST")

    def test_only_selected_method_activities_exist_in_schedule_result(self):
        case = build_case()
        project = build_native_structural_project(case, case.scenarios[1])
        result = schedule_project(project)

        ids = set(result.by_id)
        self.assertTrue({"C2-1", "C2-2", "C2-3", "C2-4"} <= ids)
        self.assertFalse({"C1-1", "C1-2", "C1-3", "C1-4"} & ids)
        self.assertEqual(result.methods_by_package["WP-C"], "SEGMENTED")

    def test_structural_native_project_round_trips_without_materialising_one_network(self):
        case = build_case()
        project = build_native_structural_project(case, case.scenarios[2])

        with TemporaryDirectory() as directory:
            path = Path(directory) / "structural-project.json"
            save_project(project, path)
            raw = json.loads(path.read_text(encoding="utf-8"))
            reopened = load_project(path)

        self.assertEqual(reopened, project)
        self.assertEqual(len(raw["work_packages"]), 6)
        self.assertEqual(
            [method["id"] for method in raw["work_packages"][1]["methods"]],
            ["SCAFFOLD", "ROPE"],
        )
        result = schedule_project(reopened)
        self.assertEqual(result.objective_finish, 35)
        self.assertEqual(result.methods_by_package["WP-B"], "ROPE")

    def test_legacy_v0_native_project_still_loads_as_fixed_network(self):
        document = {
            "format": LEGACY_FORMAT,
            "id": "legacy",
            "name": "Legacy fixed network",
            "time_unit": "hour",
            "objective_activity_id": "B",
            "resources": [],
            "activities": [
                {
                    "id": "A",
                    "name": "A",
                    "kind": "task",
                    "predecessors": [],
                    "not_before": 0,
                    "latest_finish": None,
                    "exclusion_groups": [],
                    "planned_start": None,
                    "planned_mode_id": None,
                    "frozen_start": None,
                    "frozen_mode_id": None,
                    "modes": [
                        {
                            "id": "FIXED",
                            "name": None,
                            "duration": 2,
                            "requirements": [],
                        }
                    ],
                },
                {
                    "id": "B",
                    "name": "Done",
                    "kind": "milestone",
                    "predecessors": ["A"],
                    "not_before": 0,
                    "latest_finish": None,
                    "exclusion_groups": [],
                    "planned_start": None,
                    "planned_mode_id": None,
                    "frozen_start": None,
                    "frozen_mode_id": None,
                    "modes": [
                        {
                            "id": "MILESTONE",
                            "name": None,
                            "duration": 0,
                            "requirements": [],
                        }
                    ],
                },
            ],
        }
        with TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            project = load_project(path)

        self.assertEqual(project.work_packages, ())
        result = schedule_project(project)
        self.assertEqual(result.selected_methods, ())
        self.assertEqual(result.objective_finish, 2)

    def test_cross_method_activity_dependency_is_rejected(self):
        project = Project(
            id="invalid",
            name="Invalid cross-method dependency",
            activities=(
                Activity("A1", "Method A", (ExecutionMode("FIXED", 1),)),
                Activity(
                    "B1",
                    "Method B",
                    (ExecutionMode("FIXED", 1),),
                    predecessors=("A1",),
                ),
                Activity(
                    "DONE",
                    "Done",
                    (ExecutionMode("MILESTONE", 0),),
                    predecessors=(),
                    kind="milestone",
                ),
            ),
            work_packages=(
                WorkPackage(
                    "WP",
                    "Outcome",
                    (
                        ExecutionMethod("A", "A", ("A1",), "A1"),
                        ExecutionMethod("B", "B", ("B1",), "B1"),
                    ),
                ),
                WorkPackage(
                    "END",
                    "End",
                    (ExecutionMethod("END", "End", ("DONE",), "DONE"),),
                    predecessors=("WP",),
                ),
            ),
            objective_activity_id="DONE",
        )

        with self.assertRaisesRegex(SchedulingError, "crosses execution-method/package boundaries"):
            schedule_project(project)

    def test_structural_planned_coordinates_require_explicit_reference_method(self):
        project = Project(
            id="planned-structural",
            name="Ambiguous structural reference",
            activities=(
                Activity(
                    "A",
                    "Alternative A",
                    (ExecutionMode("FIXED", 1),),
                    planned_start=0,
                    planned_mode_id="FIXED",
                ),
                Activity("B", "Alternative B", (ExecutionMode("FIXED", 1),)),
                Activity(
                    "DONE",
                    "Done",
                    (ExecutionMode("MILESTONE", 0),),
                    kind="milestone",
                ),
            ),
            work_packages=(
                WorkPackage(
                    "WP",
                    "Outcome",
                    (
                        ExecutionMethod("A", "A", ("A",), "A"),
                        ExecutionMethod("B", "B", ("B",), "B"),
                    ),
                ),
                WorkPackage(
                    "END",
                    "End",
                    (ExecutionMethod("END", "End", ("DONE",), "DONE"),),
                    predecessors=("WP",),
                ),
            ),
            objective_activity_id="DONE",
        )

        with self.assertRaisesRegex(SchedulingError, "explicit selected reference method"):
            schedule_project(project)

    def test_method_completion_must_cover_all_method_work(self):
        project = Project(
            id="invalid-completion",
            name="Invalid completion",
            activities=(
                Activity("A", "A", (ExecutionMode("FIXED", 1),)),
                Activity("B", "B", (ExecutionMode("FIXED", 1),)),
            ),
            work_packages=(
                WorkPackage(
                    "WP",
                    "Outcome",
                    (ExecutionMethod("M", "Method", ("A", "B"), "A"),),
                ),
            ),
            objective_activity_id="A",
        )

        with self.assertRaisesRegex(SchedulingError, "do not feed method completion"):
            schedule_project(project)


if __name__ == "__main__":
    unittest.main()
