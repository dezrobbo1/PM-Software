"""Focused falsification tests; small manual enumeration is independent of CP-SAT."""
from dataclasses import asdict, replace
from itertools import product
import unittest
from unittest.mock import patch

from deterministic_scheduling_core import resource_assignment_experiment as ra
from deterministic_scheduling_core.resource_allocation_repair_experiment import (
    FEASIBLE, INFEASIBLE, INCONCLUSIVE, OPTIMAL, build_calendar_case,
    build_continuity_case, check_allocation, pattern, project_placements,
    run_experiment, solve_repair,
)
from deterministic_scheduling_core.working_time_experiment import WorkCalendar


def manual_continuity_schedules(horizon=6):
    """Enumerate starts, milestone time and X's identity using only interval math."""
    feasible = []
    for x, y, z in product(range(horizon - 3), range(horizon - 1), range(2, horizon - 1)):
        for resource in ("M1", "M2"):
            blocker_start = y if resource == "M1" else z
            if max(x, blocker_start) < min(x + 4, blocker_start + 2):
                continue
            for finish in range(max(x + 4, y + 2, z + 2), horizon + 1):
                starts = {"X": x, "Y": y, "Z": z, "DONE": finish}
                durations = {"X": 4, "Y": 2, "Z": 2, "DONE": 0}
                patterns = {a: (s, s + durations[a], ((s, s + durations[a]),) if durations[a] else ())
                            for a, s in starts.items()}
                objective = finish, x + 2 * y + 3 * z + 4 * finish
                feasible.append((objective, patterns))
    return feasible


class ResourceAllocationRepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = run_experiment()

    def test_three_cases_match_complete_reference_objectives(self):
        self.assertEqual(self.result["conclusion"], "NOT_FALSIFIED_FOR_TESTED_PROFILE")
        self.assertEqual(set(self.result["cases"]), {"overlap", "continuity", "calendar"})
        for name, record in self.result["cases"].items():
            with self.subTest(case=name):
                self.assertTrue(record["matches_reference"])
                self.assertEqual(record["candidate"]["status"], OPTIMAL)
                self.assertEqual(record["candidate"]["objective"], record["reference"]["objective"])
                self.assertTrue(record["candidate"]["allocation"])
                self.assertTrue(record["source_unchanged"])
        overlap = self.result["cases"]["overlap"]
        self.assertEqual(overlap["candidate"]["objective"], (75, 4349))
        self.assertEqual(overlap["selective_control"]["objective"], (75, 4349))
        self.assertTrue(overlap["selective_control"]["physically_assignable"])

    def test_feedback_is_automatic_not_the_hard_coded_shared_capacity_diagnostic(self):
        record = self.result["cases"]["overlap"]["candidate"]
        self.assertGreater(len(record["cuts"]), 0)
        self.assertEqual(record["trace"][0]["checker_status"], INFEASIBLE)
        self.assertEqual(record["trace"][-1]["checker_status"], FEASIBLE)
        with patch.object(ra, "_add_shared_multiskill_constraint", side_effect=AssertionError("hard-coded repair")):
            result = solve_repair(build_continuity_case())
        self.assertEqual(result.status, OPTIMAL)
        self.assertTrue(result.cuts)

    def test_no_handover_repair_can_increase_the_finish(self):
        result = self.result["cases"]["continuity"]["candidate"]
        self.assertEqual(result["trace"][0]["objective"][0], 4)
        self.assertEqual(result["objective"][0], 6)
        initial = tuple(ra.ScheduledEntry(**e) for e in result["trace"][0]["candidate"])
        case = build_continuity_case()
        self.assertTrue(ra.each_time_slice_is_assignable(case, initial))
        self.assertEqual(check_allocation(case, initial).status, INFEASIBLE)
        self.assertEqual(min(o for o, _ in manual_continuity_schedules()), result["objective"])

    def test_every_feedback_cut_preserves_all_manually_enumerated_feasible_schedules(self):
        case = build_continuity_case()
        result = solve_repair(case)
        enumerated = manual_continuity_schedules()
        self.assertTrue(enumerated)
        self.assertTrue(result.cuts)
        for cut in result.cuts:
            self.assertEqual(check_allocation(case, cut, complete=False).status, INFEASIBLE)
            for _, feasible in enumerated:
                self.assertFalse(all(feasible[e.activity_id] == pattern(e) for e in cut))

    def test_all_candidate_placement_spaces_include_the_reference_space(self):
        for case in (ra.build_case(), build_continuity_case(), build_calendar_case()):
            catalog, variants, _ = project_placements(case)
            self.assertGreaterEqual(variants, sum(map(len, catalog.values())))
            for activity in case.activities:
                projected = {pattern(e) for e in catalog[activity.id]}
                explicit = {pattern(p) for p in ra._candidate_placements(case, activity, "B")}
                self.assertEqual(projected, explicit)
                self.assertTrue(all(rid is None for e in catalog[activity.id] for _, rid in e.assignments))

    def test_heterogeneous_calendars_preserve_patterns_missing_from_old_pool(self):
        case = build_calendar_case()
        catalog, _, missing = project_placements(case)
        key = (0, 6, ((0, 2), (4, 6)))
        self.assertIn(key, {pattern(e) for e in catalog["FLEX"]})
        self.assertNotIn(key, {pattern(p) for p in ra._candidate_placements(case, case.activity_by_id["FLEX"], "A")})
        self.assertGreater(missing, 0)
        result = self.result["cases"]["calendar"]["candidate"]
        flex = next(e for e in result["entries"] if e["activity_id"] == "FLEX")
        self.assertEqual(flex["periods"], ((0, 2), (4, 6)))
        self.assertIn(("FLEX", "MECH", "E"), result["allocation"])
        self.assertEqual(result["objective"][0], 6)

    def test_checker_does_not_allow_an_unexplained_gap_under_another_witness(self):
        calendar = WorkCalendar("TEST", ((0, 4),))
        resources = (ra.PhysicalResource("ALWAYS", ("MECH",), "TEST"),
                     ra.PhysicalResource("GAP", ("MECH",), "TEST"))
        req = ra.RequirementSlot
        activities = (
            ra.ActivitySpec("X", "Suspended work", 2, "TEST", (req("MECH", ("MECH",), ("ALWAYS", "GAP")),)),
            ra.ActivitySpec("Y", "GAP occupied early", 1, "TEST", (req("MECH", ("MECH",), ("GAP",)),)),
        )
        case = ra.ExperimentCase((calendar,), resources, (ra.AvailabilityException("GAP", 1, 2, "gap"),), activities, "X", 4)
        entries = (ra.ScheduledEntry("X", 0, 3, ((0, 1), (2, 3)), (("MECH", None),)),
                   ra.ScheduledEntry("Y", 0, 1, ((0, 1),), (("MECH", None),)))
        # The existing checker's proof is narrower: availability/occupancy only.
        self.assertEqual(ra.check_fixed_schedule(case, entries).exact_status, FEASIBLE)
        self.assertEqual(check_allocation(case, entries).status, INFEASIBLE)
        valid = check_allocation(case, entries[:1], complete=False)
        self.assertEqual(valid.status, FEASIBLE)
        self.assertEqual(valid.witness, (("X", "MECH", "GAP"),))

    def test_failed_greedy_dispatch_does_not_generate_a_cut(self):
        calendar = WorkCalendar("TEST", ((0, 2),))
        resources = (ra.PhysicalResource("M1", ("MECH",), "TEST"),
                     ra.PhysicalResource("M2", ("MECH", "SPECIALIST"), "TEST"))
        req = ra.RequirementSlot
        activities = (
            ra.ActivitySpec("ORDINARY", "Ordinary", 2, "TEST", (req("MECH", ("MECH",), ("M1", "M2")),)),
            ra.ActivitySpec("SPECIAL", "Special", 2, "TEST", (req("SPECIALIST", ("SPECIALIST",), ("M2",)),)),
            ra.ActivitySpec("DONE", "Handoff", 0, "TEST", predecessors=("ORDINARY", "SPECIAL")),
        )
        case = ra.ExperimentCase((calendar,), resources, (), activities, "DONE", 2)
        result = solve_repair(case)
        self.assertEqual(result.status, OPTIMAL)
        self.assertFalse(result.cuts)
        greedy, _, _ = ra._greedy_assignment(case, result.entries, preferred_resources=("M2", "M1"))
        self.assertEqual(greedy, "FAILED")
        self.assertIn(("ORDINARY", "MECH", "M1"), result.allocation)
        self.assertIn(("SPECIAL", "SPECIALIST", "M2"), result.allocation)

    def test_search_limit_is_inconclusive_and_produces_no_cut(self):
        result = solve_repair(build_continuity_case(), max_search_nodes=0)
        self.assertEqual(result.status, INCONCLUSIVE)
        self.assertFalse(result.cuts)
        self.assertFalse(result.entries)
        self.assertFalse(result.allocation)
        self.assertIsNone(result.objective)

    def test_iteration_limit_does_not_claim_project_infeasibility(self):
        result = solve_repair(build_continuity_case(), max_iterations=1)
        self.assertEqual(result.status, INCONCLUSIVE)
        self.assertEqual(len(result.trace), 1)
        self.assertEqual(len(result.cuts), 1)
        self.assertFalse(result.entries)
        self.assertIsNone(result.objective)

    def test_exhausted_finite_horizon_is_proven_infeasible(self):
        case = build_continuity_case(horizon=4)
        self.assertFalse(manual_continuity_schedules(horizon=4))
        result = solve_repair(case)
        self.assertEqual(result.status, INFEASIBLE)
        self.assertTrue(result.cuts)
        self.assertEqual(result.trace[-1]["master_status"], INFEASIBLE)
        self.assertFalse(result.entries)

    def test_inconclusive_master_is_not_converted_to_infeasibility(self):
        measured = {"solver_calls": 1, "build_ms": 0.0, "solve_ms": 0.0, "variables": 1, "constraints": 1}
        with patch("deterministic_scheduling_core.resource_allocation_repair_experiment._master",
                   return_value=(INCONCLUSIVE, (), None, measured)):
            result = solve_repair(build_continuity_case())
        self.assertEqual(result.status, INCONCLUSIVE)
        self.assertFalse(result.cuts)
        self.assertEqual(result.metrics["checker_calls"], 0)

    def test_repeats_include_trace_and_witness_without_runtime_in_signature(self):
        for record in self.result["cases"].values():
            self.assertTrue(record["repeat_signature_matches"])
            self.assertTrue(record["repeat_trace_matches"])
            self.assertTrue(record["repeat_objective_matches"])

    def test_costs_and_identity_preprocessing_are_not_hidden(self):
        for record in self.result["cases"].values():
            metrics = record["candidate"]["metrics"]
            self.assertEqual(metrics["assignment_variables"], 0)
            self.assertGreater(metrics["local_assignment_placements"], 0)
            self.assertGreater(metrics["projected_patterns"], 0)
            self.assertEqual(metrics["solver_calls"], 2 * metrics["iterations"])
            self.assertGreaterEqual(metrics["checker_calls"], metrics["iterations"])
            self.assertGreater(metrics["elapsed_ms"], 0)
            self.assertGreater(record["reference"]["end_to_end_ms"], 0)
            self.assertEqual(record["planner_facts"]["physical resources"], len(record["case"]["resources"]))
            for entry in record["candidate"]["entries"]:
                self.assertTrue(all(rid is None for _, rid in entry["assignments"]))

    def test_checker_coverage_and_profile_boundary_are_explicit(self):
        case = build_continuity_case()
        self.assertEqual(check_allocation(case, ()).status, INFEASIBLE)
        before = asdict(case)
        bad = replace(case, resources=(replace(case.resources[0], capacity=2), case.resources[1]))
        with self.assertRaisesRegex(ValueError, "capacity-one"):
            solve_repair(bad)
        self.assertEqual(asdict(case), before)
        with self.assertRaises(ValueError):
            solve_repair(case, max_iterations=0)


if __name__ == "__main__":
    unittest.main()
