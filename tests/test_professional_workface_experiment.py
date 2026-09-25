"""Focused future-only workface and protected latest-finish falsification."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from unittest.mock import patch

from ortools.sat.python import cp_model

from deterministic_scheduling_core.project.planning_workspace import digest, validate as validate_workspace
from deterministic_scheduling_core.project.work_method_time import (
    from_document, input_hash, load, materialise, save, to_document,
)
from deterministic_scheduling_core.professional_workface_experiment import (
    build_problem, independent_control, run_experiment,
)
from deterministic_scheduling_core.scheduling.work_method_time import (
    schedule_work_method_time, validate_plan, validate_problem,
)


def rebind(plan, problem):
    plan = deepcopy(plan)
    plan["input_hash"] = input_hash(problem)
    plan["plan_hash"] = digest({k: v for k, v in plan.items() if k != "plan_hash"})
    return plan


class ProfessionalWorkfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = run_experiment()

    def test_control_agrees_with_all_retained_cases(self):
        self.assertTrue(all(case["control_matches"] and case["source_unchanged"]
                            for case in self.cases.values()))
        self.assertTrue(all(case["placement_alternatives"] < 20000 for case in self.cases.values()))

    def test_without_fields_preserves_fast_default_and_existing_workspace_validation(self):
        p = build_problem()
        self.assertEqual(self.cases["baseline"]["methods"]["BUILD"], "FAST")
        self.assertEqual(self.cases["baseline"]["objective"], [6, 96])
        validate_workspace(materialise(p, {"BUILD": "FAST", "ACCESS": "FIXED", "CREW": "FAST",
                                           "CHECK": "FIXED", "HANDOFF": "FIXED"}))

    def test_workface_counterfactual_and_suspendable_envelope(self):
        no_face = self.cases["baseline"]
        face = self.cases["workface"]
        self.assertEqual(no_face["objective"][0], 6)
        self.assertEqual(face["objective"][0], 7)
        self.assertEqual(no_face["starts"]["B"], 2)
        self.assertEqual(face["starts"]["B"], 6)
        plan = schedule_work_method_time(build_problem(workface=True)).plan
        a = next(e for e in plan["entries"] if e["activity_id"] == "A_FAST")
        b = next(e for e in plan["entries"] if e["activity_id"] == "B")
        self.assertEqual(a["periods"], [[0, 2], [4, 6]])
        self.assertEqual((a["start"], a["finish"], b["start"]), (0, 6, 6))

    def test_removing_only_workface_from_protected_case_restores_fast_method(self):
        protected = self.cases["protected"]
        no_face = self.cases["no_workface"]
        self.assertEqual(protected["methods"]["BUILD"], "ALT")
        self.assertEqual(no_face["methods"]["BUILD"], "FAST")
        self.assertEqual(protected["objective"][0], 7)
        self.assertEqual(no_face["objective"][0], 6)
        self.assertEqual(protected["starts"]["B"], no_face["starts"]["B"])

    def test_protected_finish_changes_structure_and_inactive_fields_do_not_bind(self):
        protected = self.cases["protected"]
        self.assertEqual(self.cases["no_deadline"]["methods"]["BUILD"], "FAST")
        self.assertEqual(protected["methods"]["BUILD"], "ALT")
        self.assertEqual(protected["methods"]["CREW"], "FAST")
        self.assertEqual(protected["starts"]["B"], 2)
        self.assertNotIn("C_ALT", protected["starts"])
        self.assertNotIn("A_FAST", protected["starts"])
        # C_ALT has an impossible latest_finish and shares WF-A, but is inactive.
        p = build_problem(workface=True, deadline=True)
        self.assertEqual(next(a for a in p.project["activities"] if a["id"] == "C_ALT")["latest_finish"], 0)
        self.assertEqual(validate_plan(p, schedule_work_method_time(p).plan), "PROVEN_FEASIBLE")

    def test_round_trip_and_no_solve_validation(self):
        p = build_problem(workface=True, deadline=True)
        before = to_document(p)
        plan = schedule_work_method_time(p).plan
        with TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.json"
            save(p, path)
            reopened = load(path)
            with patch.object(cp_model.CpSolver, "solve", side_effect=AssertionError("validation solved")):
                self.assertEqual(validate_plan(reopened, json.loads(json.dumps(plan))), "PROVEN_FEASIBLE")
        self.assertEqual(to_document(reopened), before)
        self.assertEqual(to_document(p), before)
        self.assertEqual(to_document(from_document(before)), before)

    def test_malformed_exclusion_and_latest_finish(self):
        for invalid in ("WF-A", ["WF-A", "WF-A"], [""], [4], None, {}):
            with self.subTest(invalid=invalid):
                p = build_problem()
                p.project["activities"][0]["exclusion_groups"] = invalid
                with self.assertRaisesRegex(ValueError, "exclusion_groups"):
                    validate_problem(p)
        for invalid in (True, 2.5, -1, None, 9, "3"):
            with self.subTest(invalid=invalid):
                p = build_problem()
                p.project["activities"][2]["latest_finish"] = invalid
                with self.assertRaisesRegex(ValueError, "latest_finish"):
                    validate_problem(p)
        p = build_problem()
        p.project["activities"][2]["latest_finish"] = 2
        with self.assertRaisesRegex(ValueError, "fixed activity.*latest_finish"):
            validate_problem(p)

    def test_rehashed_overlap_rejected_without_solver(self):
        unrestricted = schedule_work_method_time(build_problem()).plan
        p = build_problem(workface=True)
        with patch.object(cp_model.CpSolver, "solve", side_effect=AssertionError("validation solved")):
            with self.assertRaisesRegex(ValueError, "workface execution envelopes overlap"):
                validate_plan(p, rebind(unrestricted, p))

    def test_rehashed_late_finish_rejected_without_solver(self):
        unrestricted = schedule_work_method_time(build_problem(workface=True)).plan
        p = build_problem(workface=True, deadline=True)
        with patch.object(cp_model.CpSolver, "solve", side_effect=AssertionError("validation solved")):
            with self.assertRaisesRegex(ValueError, "active finish exceeds latest_finish"):
                validate_plan(p, rebind(unrestricted, p))

    def test_zero_length_milestone_does_not_reserve_a_workface(self):
        p = build_problem(workface=True)
        next(a for a in p.project["activities"] if a["id"] == "D")["exclusion_groups"] = ["WF-A"]
        plan = schedule_work_method_time(p).plan
        self.assertEqual(next(e for e in plan["entries"] if e["activity_id"] == "D")["start"], 1)
        self.assertEqual(validate_plan(p, plan), "PROVEN_FEASIBLE")

    def test_workface_interval_expansion_is_bounded_before_creation(self):
        p = build_problem(workface=True)
        next(a for a in p.project["activities"] if a["id"] == "B")["exclusion_groups"] = [
            f"WF-{i}" for i in range(4000)
        ]
        with self.assertRaisesRegex(ValueError, "20000 workface intervals"):
            schedule_work_method_time(p)

    def test_repeated_plan_and_independent_raw_control(self):
        p = build_problem(workface=True, deadline=True)
        before = input_hash(p)
        a = schedule_work_method_time(p).plan
        b = schedule_work_method_time(p).plan
        self.assertEqual(a, b)
        self.assertEqual(input_hash(p), before)
        control = independent_control(p)
        self.assertEqual(control["objective"], a["objective"])
        self.assertEqual(control["selected_methods"], a["selected_methods"])
        self.assertEqual(control["starts"], {e["activity_id"]: e["start"] for e in a["entries"]})


if __name__ == "__main__":
    unittest.main()
