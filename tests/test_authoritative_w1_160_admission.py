"""Pre-adoption frozen parity and bounded W1 public admission contracts."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from ortools.sat.python import cp_model

from deterministic_scheduling_core.converged_scale_experiment import build_problem as scale
from deterministic_scheduling_core.factored_finish_search_experiment import build_group_stress
from deterministic_scheduling_core.native_work_method_time import build_problem as small
from deterministic_scheduling_core.professional_workface_experiment import build_problem as professional
from deterministic_scheduling_core.professional_scale_challenge import build_professional_projection
from deterministic_scheduling_core.project.work_method_time import WorkMethodTimeProject, from_document, input_hash
from deterministic_scheduling_core.project.rolling_structural_status import from_document as cycle_from_document
from deterministic_scheduling_core.scheduling.accepted_work_method_time import validate_input as validate_accepted
from deterministic_scheduling_core.scheduling.rolling_structural_status import validate_cycle
from deterministic_scheduling_core.scheduling.placement_window import (
    RankedPlacement, check_preprocessing_count, union_supported_ranks,
)
from deterministic_scheduling_core.scheduling.work_method_time import (
    _compile_work_method_time, _mode_cases, schedule_work_method_time, validate_plan, validate_problem,
)
from deterministic_scheduling_core.scheduling.planning_workspace import _group_placements
from deterministic_scheduling_core.w1_model_integration_experiment import low_density_case, w1_domain

BASELINE = json.loads((Path(__file__).parent / "fixtures/w1-adoption/pre-adoption.json").read_text())
PR53 = json.loads((Path(__file__).parent / "fixtures/w1-adoption/pr53-exact-result.json").read_text())


class AuthoritativeW1AdmissionTests(unittest.TestCase):
    def test_pre_adoption_semantic_and_original_rank_parity(self):
        self.assertEqual(BASELINE["source_sha"], "fcce684febefc36be800b0c70a7d943089f10b7f")
        cases = {"small": small(), "professional": professional(workface=True, deadline=True),
                 "group_suspended": build_group_stress(), "64_48": scale()}
        for name, problem in cases.items():
            with self.subTest(name=name):
                frozen = BASELINE["controls"][name]
                source = input_hash(problem)
                self.assertEqual(source, frozen["input_hash"])
                current = schedule_work_method_time(problem)
                self.assertEqual({k: v for k, v in current.plan.items() if k not in ("solver", "plan_hash")},
                                 frozen["semantic_plan"])
                self.assertEqual(current.metrics["canonical_vector"], frozen["canonical_vector"])
                self.assertEqual(current.plan["solver"]["canonical_blocks"], frozen["canonical_blocks"])
                self.assertEqual(current.plan["solver"]["compiler"], "native-work-method-time-w1-lb1-seeded/0")
                indexed, allowed, _, structures = w1_domain(problem)
                current_rows = {aid: tuple(RankedPlacement(row.mode, row.rank, row)
                                           for row in rows) for aid, rows in indexed.items()}
                self.assertEqual(union_supported_ranks(problem, current_rows), allowed)
                self.assertEqual(current.metrics["placement_alternatives"], sum(map(len, allowed.values())))
                self.assertEqual(current.metrics["u0_eligible_placements"], sum(map(len, indexed.values())))
                self.assertLessEqual(structures, 16)
                self.assertEqual(input_hash(problem), source)
                self.assertEqual(validate_plan(problem, current.plan), "PROVEN_FEASIBLE")
        self.assertEqual(BASELINE["controls"]["64_48"]["plan_hash"],
                         "0698e2c95e7aed5ee35d7d343349e77b88e39121bfbad41fa865c6818d923410")

    def test_historical_artifacts_validate_without_solving(self):
        fixture = Path(__file__).parent / "fixtures"
        cases = (("canonical-batching-legacy/small-sequential-plan.json", small()),
                 ("canonical-batching-legacy/professional-sequential-plan.json", professional(workface=True, deadline=True)),
                 ("lb1-seeded-legacy/small-batched-plan.json", small()),
                 ("lb1-seeded-legacy/professional-batched-plan.json", professional(workface=True, deadline=True)),
                 ("lb1-seeded-legacy/scale_64_48-batched-plan.json", scale()))
        with patch.object(cp_model.CpSolver, "solve", side_effect=AssertionError("historical validation solved")):
            for path, problem in cases:
                with self.subTest(path=path):
                    plan = json.loads((fixture / path).read_text())
                    prior = deepcopy(plan)
                    self.assertEqual(validate_plan(problem, plan), "PROVEN_FEASIBLE")
                    self.assertEqual(plan, prior)
            for label in ("canonical-batching-legacy/accepted-sequential-reference.json",
                          "lb1-seeded-legacy/accepted-batched-reference.json"):
                accepted = json.loads((fixture / label).read_text())
                source = from_document(accepted["source"])
                validate_accepted(source, source, accepted["reference_plan"], accepted["status_workspace"])
            for label in ("canonical-batching-legacy/rolling-sequential-cycle.json",
                          "lb1-seeded-legacy/rolling-batched-cycle.json"):
                rolling = json.loads((fixture / label).read_text())
                validate_cycle(cycle_from_document(rolling))

    def test_ordinary_admission_and_previous_status_boundary(self):
        for count in (65, 96, 128, 160):
            with self.subTest(count=count):
                problem = low_density_case(count)
                prior = input_hash(problem)
                validate_problem(problem)
                result = schedule_work_method_time(problem)
                self.assertEqual(result.plan["objective"],
                                 [count, sum((i + 1) * i for i in range(count))])
                self.assertEqual(input_hash(problem), prior)
                self.assertTrue(all(x["value"] == 1 for x in result.metrics["canonical_vector"]
                                    if x["name"].startswith("placement:")))
                with self.assertRaisesRegex(ValueError, "accepted-history recovery supports at most 64"):
                    validate_accepted(problem, problem, {}, {})
        original = low_density_case(160)
        source = deepcopy(original.project)
        source["horizon_ticks"] = 161
        final = deepcopy(source["activities"][-1])
        final["id"] = "A160"
        final["name"] = "Activity 160"
        final["predecessors"] = ["A159"]
        final["not_before"] = 160
        final["latest_finish"] = 161
        source["activities"].append(final)
        source["objective_activity_id"] = "A160"
        with self.assertRaisesRegex(ValueError, "1..160 declared activities"):
            validate_problem(WorkMethodTimeProject(source))

    def test_retained_and_workface_caps_fail_before_solver(self):
        base = low_density_case(65)
        source = deepcopy(base.project)
        source["horizon_ticks"] = 480
        for activity in source["activities"]:
            activity.pop("predecessors", None)
            activity["not_before"] = 0
            activity["latest_finish"] = 480
        source["activities"][-1]["predecessors"] = [activity["id"] for activity in source["activities"][:-1]]
        with patch.object(cp_model.CpSolver, "solve", side_effect=AssertionError("solver invoked")):
            with self.assertRaisesRegex(ValueError, "20000 placement alternatives"):
                schedule_work_method_time(WorkMethodTimeProject(source))
        source["activities"] = source["activities"][:45]
        source["objective_activity_id"] = source["activities"][-1]["id"]
        for activity in source["activities"]:
            activity["latest_finish"] = 400
            activity["exclusion_groups"] = ["FRONT", "REAR"]
        source["activities"][-1]["predecessors"] = [activity["id"] for activity in source["activities"][:-1]]
        with patch.object(cp_model.CpSolver, "solve", side_effect=AssertionError("solver invoked")):
            with self.assertRaisesRegex(ValueError, "20000 workface intervals"):
                schedule_work_method_time(WorkMethodTimeProject(source))
        check_preprocessing_count(100_000)
        with self.assertRaisesRegex(ValueError, "100000 raw placements"):
            check_preprocessing_count(100_001)

    def test_raw_guard_stops_inside_mode_generation(self):
        case = small()
        environment, specs = _mode_cases(case)
        first = case.project["activities"][0]
        spec = specs[first["id"], first["modes"][0]["id"]]
        all_rows = _group_placements(environment, spec, "B")
        self.assertGreater(len(all_rows), 1)
        self.assertEqual(_group_placements(environment, spec, "B", max_count=len(all_rows)), all_rows)
        with self.assertRaisesRegex(ValueError, "raw placements"):
            _group_placements(environment, spec, "B", max_count=len(all_rows) - 1)
        with self.assertRaisesRegex(ValueError, "raw placements"):
            _group_placements(environment, spec, "B", max_count=0)

    def test_professional_public_exact_and_repeat(self):
        problem = build_professional_projection()
        prior = input_hash(problem)
        first = schedule_work_method_time(problem)
        second = schedule_work_method_time(problem)
        self.assertEqual(first.plan, second.plan)
        self.assertEqual(first.metrics["canonical_vector"], second.metrics["canonical_vector"])
        self.assertEqual(first.plan["objective"], [60, 363133])
        self.assertEqual(PR53["source_sha"], "b3186ac915bfb2d4bdfe3eaee530c7e28f26be61")
        self.assertEqual(first.plan["selected_methods"], PR53["result"]["selected_methods"])
        self.assertEqual(first.plan["selected_modes"], PR53["result"]["selected_modes"])
        self.assertEqual([{"name": d["name"], "value": d["value"], "maximum": d["maximum"]}
                          for d in first.metrics["canonical_vector"]], PR53["result"]["canonical_vector"])
        self.assertEqual({d["name"].removeprefix("placement:"): d["value"]
                          for d in first.metrics["canonical_vector"] if d["name"].startswith("placement:")},
                         PR53["result"]["selected_original_placement_ranks"])
        self.assertEqual((first.metrics["u0_raw_placements"], first.metrics["u0_eligible_placements"],
                          first.metrics["placement_alternatives"], first.metrics["workface_intervals"]),
                         (64068, 64032, 7812, 409))
        self.assertEqual(first.metrics["canonical_block_count"], 26)
        self.assertEqual(first.metrics["solver_calls"], 28)
        self.assertEqual(first.plan["physical_status"], "PROVEN_FEASIBLE")
        self.assertEqual(input_hash(problem), prior)
        self.assertEqual(validate_plan(problem, first.plan), "PROVEN_FEASIBLE")


if __name__ == "__main__":
    unittest.main()
