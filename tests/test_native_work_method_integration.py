from __future__ import annotations

from dataclasses import replace
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
    Resource,
    ResourceRequirement,
    WorkPackage,
    load_project,
    save_project,
)
from deterministic_scheduling_core.project.io import LEGACY_FORMAT
from deterministic_scheduling_core.scheduling import schedule_project
from deterministic_scheduling_core.scheduling.engine import validate_project
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

    def test_many_binary_packages_do_not_require_exponential_objective_weights(self):
        activities = []
        packages = []
        for index in range(30):
            left_id = f"P{index:02d}-A"
            right_id = f"P{index:02d}-B"
            activities.extend(
                (
                    Activity(left_id, left_id, (ExecutionMode("FIXED", 1),)),
                    Activity(right_id, right_id, (ExecutionMode("FIXED", 1),)),
                )
            )
            packages.append(
                WorkPackage(
                    f"WP-{index:02d}",
                    f"Outcome {index:02d}",
                    (
                        ExecutionMethod("A", "A", (left_id,), left_id),
                        ExecutionMethod("B", "B", (right_id,), right_id),
                    ),
                )
            )

        project = Project(
            id="many-binary-methods",
            name="Many binary structural choices",
            activities=tuple(activities),
            work_packages=tuple(packages),
        )

        result = schedule_project(project)

        self.assertEqual(result.objective_finish, 1)
        self.assertEqual(
            result.selected_methods,
            tuple((f"WP-{index:02d}", "A") for index in range(30)),
        )
        self.assertEqual(len(result.entries), 30)
        self.assertTrue(all(entry.activity_id.endswith("-A") for entry in result.entries))

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


class NativeWorkMethodWindowTests(unittest.TestCase):
    def setUp(self):
        crew = (ResourceRequirement("R"),)
        self.project = Project(
            id="method-window",
            name="Closed method window",
            activities=(
                Activity("RELEASE", "Release", (ExecutionMode("FIXED", 1, crew),)),
                Activity("A1", "Prepare A", (ExecutionMode("FIXED", 1, crew),),
                         predecessors=("RELEASE",)),
                Activity("A2", "Complete A", (ExecutionMode("FIXED", 1, crew),),
                         predecessors=("A1",), latest_finish=4),
                Activity("B", "Alternative B", (ExecutionMode("FIXED", 3, crew),),
                         predecessors=("RELEASE",)),
                Activity("DONE", "Handoff", (ExecutionMode("MILESTONE", 0),),
                         kind="milestone"),
            ),
            resources=(Resource("R", "Crew", 1),),
            work_packages=(
                WorkPackage("WP", "Required work", (
                    ExecutionMethod("A", "A", ("A1", "A2"), "A2"),
                    ExecutionMethod("B", "B", ("B",), "B"),
                )),
                WorkPackage("END", "Handoff", (
                    ExecutionMethod("END", "End", ("DONE",), "DONE"),
                ), predecessors=("WP",)),
            ),
            objective_activity_id="DONE",
        )
        self.closed = self._edit_activity(self.project, "A2", not_before=5)

    @staticmethod
    def _edit_activity(project, activity_id, **changes):
        return replace(project, activities=tuple(
            replace(activity, **changes) if activity.id == activity_id else activity
            for activity in project.activities
        ))

    def test_closed_window_reselects_only_the_feasible_method(self):
        baseline = schedule_project(self.project)
        self.assertEqual(baseline.methods_by_package["WP"], "A")
        self.assertEqual(baseline.objective_finish, 3)

        result = schedule_project(self.closed)

        self.assertEqual(result.methods_by_package, {"WP": "B", "END": "END"})
        self.assertEqual(result.objective_finish, 4)
        self.assertEqual(result.solver_status, "OPTIMAL")
        self.assertEqual(
            {entry.activity_id: (entry.start, entry.finish) for entry in result.entries},
            {"RELEASE": (0, 1), "B": (1, 4), "DONE": (4, 4)},
        )
        # A1 was individually feasible but belongs to the same inactive method.
        self.assertFalse({"A1", "A2"} & set(result.by_id))
        self.assertEqual(result.entries, schedule_project(self.closed).entries)
        self.assertEqual(self.closed.activity_by_id["A2"].not_before, 5)
        self.assertEqual(self.closed.activity_by_id["A2"].latest_finish, 4)
        self.assertEqual(len(self.closed.activities), 5)

    def test_closed_alternative_round_trips_without_removing_its_constraints(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "closed-alternative.json"
            save_project(self.closed, path)
            saved_bytes = path.read_bytes()
            reopened = load_project(path)
            result = schedule_project(reopened)
            self.assertEqual(path.read_bytes(), saved_bytes)

        self.assertEqual(reopened, self.closed)
        self.assertEqual(result.methods_by_package["WP"], "B")
        self.assertEqual(result.objective_finish, 4)
        self.assertEqual(reopened.activity_by_id["A2"].latest_finish, 4)

    def test_all_closed_methods_are_infeasible_not_dropped(self):
        both_closed = self._edit_activity(self.closed, "B", not_before=5, latest_finish=4)
        only_closed = replace(
            self.closed,
            activities=tuple(a for a in self.closed.activities if a.id != "B"),
            work_packages=(
                replace(self.closed.work_packages[0], methods=self.closed.work_packages[0].methods[:1]),
                self.closed.work_packages[1],
            ),
        )
        for project in (both_closed, only_closed):
            with self.subTest(method_count=len(project.work_packages[0].methods)):
                validate_project(project)
                with self.assertRaisesRegex(SchedulingError, r"no feasible schedule: INFEASIBLE$"):
                    schedule_project(project)

    def test_frozen_decision_cannot_escape_a_closed_method(self):
        for changes in ({"frozen_start": 1}, {"frozen_mode_id": "FIXED"}):
            with self.subTest(changes=changes):
                project = self._edit_activity(self.closed, "A1", **changes)
                validate_project(project)
                with self.assertRaisesRegex(SchedulingError, r"no feasible schedule: INFEASIBLE$"):
                    schedule_project(project)

    def test_fixed_activity_window_validation_is_unchanged(self):
        mixed = self._edit_activity(self.closed, "RELEASE", not_before=5, latest_finish=4)
        fixed = replace(mixed, activities=(mixed.activity_by_id["RELEASE"],),
                        work_packages=(), objective_activity_id="RELEASE")
        for project in (fixed, mixed):
            with self.subTest(structural=bool(project.work_packages)):
                with self.assertRaisesRegex(SchedulingError, "RELEASE: latest_finish precedes not_before"):
                    validate_project(project)

    def test_closed_alternative_still_receives_general_validation(self):
        cases = (
            ({"modes": (ExecutionMode("FIXED", -1),)}, "duration must be non-negative"),
            ({"predecessors": ("A1", "UNKNOWN")}, "unknown predecessors"),
            ({"predecessors": ("A1", "B")}, "crosses execution-method/package boundaries"),
        )
        for changes, message in cases:
            with self.subTest(message=message):
                project = self._edit_activity(self.closed, "A2", **changes)
                with self.assertRaisesRegex(SchedulingError, message):
                    validate_project(project)


if __name__ == "__main__":
    unittest.main()
