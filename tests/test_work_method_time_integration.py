"""Focused composition tests, including a solver-independent tiny exact oracle."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from unittest.mock import patch

from ortools.sat.python import cp_model

from deterministic_scheduling_core.errors import SchedulingError
from deterministic_scheduling_core.native_work_method_time import (
    build_problem, crane_outage, run_comparison, solve_fixed_controls,
)
from deterministic_scheduling_core.project.model import ExecutionMethod, WorkPackage
from deterministic_scheduling_core.project.planning_workspace import digest
from deterministic_scheduling_core.project.work_method_time import (
    WorkMethodTimeProject, from_document, input_hash, load, materialise, save, to_document,
)
from deterministic_scheduling_core.scheduling.work_method_time import (
    policy_key, schedule_work_method_time, validate_plan, validate_problem,
)


def tiny_problem(outage=False):
    def mode(work, named=False, grouped=False, calendar="DAY"):
        return {"id": "FIXED", "processing_ticks": work, "calendar_id": calendar,
                "continuity": "SUSPENDABLE_AT_AVAILABILITY_GAPS",
                "requirements": [{"id": "MECH", "pool_ids": ["MECH"], "eligible_resource_ids": ["M"]}] if named else [],
                "group_requirements": [{"group_id": "G", "demand": 1}] if grouped else []}
    project = {"id": "tiny", "name": "Independent enumeration microcase", "horizon_ticks": 8,
               "calendars": [{"id": "DAY", "daily_windows": [[0, 2], [3, 8]]},
                             {"id": "ALWAYS", "daily_windows": [[0, 48]]}],
               "resources": [{"id": "M", "capabilities": ["MECH"], "calendar_id": "ALWAYS"}],
               "resource_groups": [{"id": "G", "name": "Independent crew", "capacity": 1,
                                    "calendar_id": "DAY", "disjoint": True, "interchangeable": True}],
               "activities": [
                   {"id": "A", "name": "Named-resource method", "modes": [mode(3, named=True)]},
                   {"id": "B", "name": "Pooled-crew method", "modes": [mode(4, grouped=True)]},
                   {"id": "J", "name": "Other named work", "not_before": 2, "modes": [mode(1, named=True, calendar="ALWAYS")]},
                   {"id": "DONE", "name": "Handoff", "predecessors": ["J"], "modes": [mode(0, calendar="ALWAYS")]},
               ], "objective_activity_id": "DONE", "pool_riggers": False}
    packages = (
        WorkPackage("WORK", "Required work", (ExecutionMethod("A", "A", ("A",), "A"), ExecutionMethod("B", "B", ("B",), "B"))),
        WorkPackage("HANDOFF", "Handoff", (ExecutionMethod("FIXED", "Handoff", ("DONE",), "DONE"),), ("WORK",)),
    )
    reports = ({"id": "E", "resource_id": "M", "start": 0, "finish": 3,
                "reason": "Synthetic outage", "reported_by": "operations", "status": "ACCEPTED", "accepted_by": "planner"},) if outage else ()
    return WorkMethodTimeProject(project, packages, reports)


def exact_tiny_oracle(outage):
    """Enumerate every start/finish and named occupancy directly from tiny facts.

    No candidate compiler, calendar helper, checker, CP-SAT or fixed-control solve
    is used. The frozen microcase has one alternate crew and one named resource.
    """
    day = {0, 1, 3, 4, 5, 6, 7}
    available_m = set(range(8)) - ({0, 1, 2} if outage else set())
    feasible = []
    for index, aid in enumerate(("A", "B")):
        work = 3 if aid == "A" else 4
        allowed = day & available_m if aid == "A" else day
        for start in range(8):
            if start not in allowed:
                continue
            occupied = sorted(t for t in allowed if t >= start)[:work]
            if len(occupied) != work:
                continue
            for jstart in range(2, 8):
                if jstart not in available_m or (aid == "A" and jstart in occupied):
                    continue
                for finish in range(max(occupied[-1] + 1, jstart + 1), 9):
                    timing = (index + 1) * start + 3 * jstart + 4 * finish
                    feasible.append(((finish, timing), (index, 0),
                                     (int(aid == "A"), int(aid == "B"), 1, 1)))
    return min(feasible)


def rehash(plan):
    plan["plan_hash"] = digest({k: v for k, v in plan.items() if k != "plan_hash"})


class WorkMethodTimeIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = run_comparison()

    def test_joint_candidate_matches_all_fixed_method_mode_controls(self):
        self.assertTrue(self.evidence["evidence_valid"])
        for case in self.evidence["cases"].values():
            self.assertTrue(case["matches_full_policy"])
            self.assertTrue(case["source_unchanged"])
            self.assertTrue(case["repeat_plan_matches"])
            self.assertEqual(len(case["control"]["branches"]), 3)
            self.assertEqual(case["candidate"]["metrics"]["model_builds"], 1)

    def test_accepted_availability_changes_authorised_structure_not_scope(self):
        normal = self.evidence["cases"]["normal"]["candidate"]["plan"]
        changed = self.evidence["cases"]["accepted_outage"]["candidate"]["plan"]
        self.assertEqual(normal["selected_methods"]["REMOVE"], "LIFT")
        self.assertEqual(normal["selected_modes"]["L1"], "NORMAL")
        self.assertEqual(changed["selected_methods"]["REMOVE"], "SEGMENTED")
        self.assertFalse({"S1", "S2"} & set(normal["selected_modes"]))
        self.assertFalse({"L1", "L2"} & set(changed["selected_modes"]))
        self.assertEqual(self.evidence["cases"]["normal"]["input"]["project"],
                         self.evidence["cases"]["accepted_outage"]["input"]["project"])

    def test_reported_only_availability_does_not_change_execution(self):
        normal = self.evidence["cases"]["normal"]["candidate"]["plan"]
        reported = self.evidence["cases"]["reported_outage"]["candidate"]["plan"]
        for field in ("objective", "entries", "selected_modes", "selected_methods", "allocation_witness"):
            self.assertEqual(normal[field], reported[field])

    def test_productive_suspension_releases_crane_and_selects_executable_workers(self):
        plan = self.evidence["cases"]["normal"]["candidate"]["plan"]
        entries = {e["activity_id"]: e for e in plan["entries"]}
        self.assertEqual(entries["L1"]["periods"], [[20, 24], [25, 27]])
        self.assertEqual(entries["C_SERVICE"]["periods"], [[24, 25]])
        self.assertEqual(dict(entries["L1"]["assignments"])["MECH"], "M1")
        self.assertEqual(dict(entries["P1"]["assignments"])["SPECIALIST"], "M2")
        self.assertEqual(len(entries["QA"]["periods"]), 1)
        self.assertEqual(entries["QA"]["finish"] - entries["QA"]["start"], 2)

    def test_group_requirements_stay_quantities_without_fictitious_workers(self):
        plan = self.evidence["cases"]["normal"]["candidate"]["plan"]
        by_id = {e["activity_id"]: e for e in plan["entries"]}
        self.assertEqual(by_id["R1"]["group_demands"], [["RIGGING", 1]])
        self.assertEqual(by_id["R2"]["group_demands"], [["RIGGING", 1]])
        self.assertEqual(by_id["R1"]["start"], by_id["R2"]["start"])
        self.assertNotIn("@group/", json.dumps(plan))

    def test_native_input_and_plan_reopen_without_any_schedule_solve(self):
        problem = build_problem()
        plan = self.evidence["cases"]["normal"]["candidate"]["plan"]
        before = to_document(problem)
        with TemporaryDirectory() as directory:
            source_path, plan_path = Path(directory) / "source.json", Path(directory) / "plan.json"
            save(problem, source_path)
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            with patch.object(cp_model.CpSolver, "solve", side_effect=AssertionError("reopen must not schedule")):
                reopened = load(source_path)
                reopened_plan = json.loads(plan_path.read_text(encoding="utf-8"))
                self.assertEqual(validate_plan(reopened, reopened_plan), "PROVEN_FEASIBLE")
        self.assertEqual(to_document(reopened), before)
        self.assertEqual(reopened_plan, plan)

    def test_candidate_never_calls_the_fixed_network_oracle(self):
        with patch("deterministic_scheduling_core.native_work_method_time.solve_fixed_controls",
                   side_effect=AssertionError("oracle leaked into candidate")):
            result = schedule_work_method_time(tiny_problem())
        self.assertEqual(result.plan["selected_methods"]["WORK"], "A")

    def test_tiny_exhaustive_oracle_includes_resource_conflict_calendar_and_structure(self):
        for outage in (False, True):
            with self.subTest(outage=outage):
                problem = tiny_problem(outage)
                plan = schedule_work_method_time(problem).plan
                observed = policy_key(problem, plan["selected_methods"], plan["selected_modes"], plan["objective"])
                self.assertEqual(observed, exact_tiny_oracle(outage))
                self.assertEqual(plan["selected_methods"]["WORK"], "B" if outage else "A")

    def test_continuous_work_cannot_use_the_suspendable_pattern(self):
        problem = tiny_problem()
        problem.project["activities"][0]["modes"][0]["continuity"] = "CONTINUOUS"
        result = schedule_work_method_time(problem)
        self.assertEqual(result.plan["selected_methods"]["WORK"], "B")
        self.assertEqual(result.plan["objective"], solve_fixed_controls(problem)["best"]["objective"])

    def test_unavailable_optional_method_does_not_invalidate_other_structure(self):
        problem = tiny_problem(True)
        problem.reports[0]["finish"] = 8
        problem.project["activities"][2]["modes"][0]["requirements"] = []
        result = schedule_work_method_time(problem)
        self.assertEqual(result.plan["selected_methods"]["WORK"], "B")
        self.assertNotIn("A", result.plan["selected_modes"])
        problem.project["calendars"].append({"id": "EMPTY", "daily_windows": []})
        problem.project["resource_groups"][0]["calendar_id"] = "EMPTY"
        with self.assertRaisesRegex(SchedulingError, "INFEASIBLE"):
            schedule_work_method_time(problem)

    def test_invalid_inactive_mode_and_cross_method_links_are_still_rejected(self):
        problem = tiny_problem(True)
        problem.project["activities"][0]["modes"][0]["unexpected"] = True
        with self.assertRaisesRegex(ValueError, "unsupported mode"):
            schedule_work_method_time(problem)
        problem = tiny_problem()
        problem.project["activities"][0]["predecessors"] = ["B"]
        with self.assertRaisesRegex(SchedulingError, "crosses"):
            validate_problem(problem)

    def test_old_status_or_approval_documents_are_not_silently_migrated(self):
        with self.assertRaises(ValueError):
            from_document({"schema": "pm-native-planning-workspace/2", "execution": {"status_point": 2}})
        document = to_document(tiny_problem())
        document["approved_plan"] = {}
        with self.assertRaises(ValueError):
            from_document(document)

    def test_full_fixed_network_remains_a_special_case(self):
        tiny = tiny_problem()
        fixed = materialise(tiny, {"WORK": "A", "HANDOFF": "FIXED"})
        problem = WorkMethodTimeProject(fixed["project"])
        result = schedule_work_method_time(problem)
        control = solve_fixed_controls(problem)
        self.assertEqual(result.plan["selected_methods"], {})
        self.assertEqual(result.plan["objective"], control["best"]["objective"])

    def test_rehashed_inactive_entries_and_wrong_objectives_are_rejected(self):
        problem = tiny_problem()
        original = schedule_work_method_time(problem).plan
        plan = deepcopy(original)
        plan["entries"].append({**plan["entries"][0], "activity_id": "B"})
        rehash(plan)
        with self.assertRaisesRegex(ValueError, "exactly"):
            validate_plan(problem, plan)
        plan = deepcopy(original)
        plan["objective"][1] += 1
        rehash(plan)
        with self.assertRaisesRegex(ValueError, "objective"):
            validate_plan(problem, plan)

    def test_rehashed_voluntary_gap_is_not_accepted_as_productive_execution(self):
        problem = tiny_problem()
        plan = schedule_work_method_time(problem).plan
        by_id = {e["activity_id"]: e for e in plan["entries"]}
        by_id["A"].update(periods=[[0, 1], [3, 5]], finish=5)
        by_id["DONE"].update(start=5, finish=5)
        plan["objective"] = [5, 3 * by_id["J"]["start"] + 4 * 5]
        rehash(plan)
        with self.assertRaisesRegex(ValueError, "physical validation"):
            validate_plan(problem, plan)

    def test_rehashed_group_quantity_and_named_witness_corruption_are_rejected(self):
        problem = tiny_problem(True)
        plan = schedule_work_method_time(problem).plan
        original = deepcopy(plan)
        next(e for e in plan["entries"] if e["activity_id"] == "B")["group_demands"] = [["G", 2]]
        rehash(plan)
        with self.assertRaisesRegex(ValueError, "quantities"):
            validate_plan(problem, plan)
        plan = original
        plan["allocation_witness"][0][2] = "not-a-resource"
        rehash(plan)
        with self.assertRaises(ValueError):
            validate_plan(problem, plan)

    def test_verified_rigger_pool_falls_back_when_interchangeability_is_lost(self):
        problem = tiny_problem(True)
        project = problem.project
        project["pool_riggers"] = True
        project["resources"].extend({"id": rid, "capabilities": ["RIGGER"], "calendar_id": "DAY"} for rid in ("R1", "R2"))
        mode = project["activities"][1]["modes"][0]
        mode["group_requirements"] = []
        mode["requirements"] = [{"id": "RIGGER", "pool_ids": ["RIGGER"], "eligible_resource_ids": ["R1", "R2"]}]
        pooled = schedule_work_method_time(problem).plan
        self.assertTrue(pooled["pooled_riggers"])
        self.assertEqual(next(e for e in pooled["entries"] if e["activity_id"] == "B")["assignments"], [["RIGGER", None]])
        problem = replace(problem, reports=problem.reports + ({"id": "R_OUT", "resource_id": "R2", "start": 0, "finish": 1,
            "reason": "Loss of interchangeability", "reported_by": "operations", "status": "ACCEPTED", "accepted_by": "planner"},))
        explicit = schedule_work_method_time(problem).plan
        self.assertFalse(explicit["pooled_riggers"])
        self.assertIsNotNone(next(e for e in explicit["entries"] if e["activity_id"] == "B")["assignments"][0][1])

    def test_unknown_and_model_invalid_are_not_reported_as_project_infeasible(self):
        problem = tiny_problem()
        before = input_hash(problem)
        for status, label in ((cp_model.UNKNOWN, "UNKNOWN"), (cp_model.MODEL_INVALID, "MODEL_INVALID")):
            with self.subTest(status=label), patch.object(cp_model.CpSolver, "solve", return_value=status):
                with self.assertRaisesRegex(SchedulingError, label):
                    schedule_work_method_time(problem)
        self.assertEqual(input_hash(problem), before)


if __name__ == "__main__":
    unittest.main()
