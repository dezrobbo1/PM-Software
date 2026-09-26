"""Source-frozen historical compatibility and exact authoritative adoption."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import json
import unittest
from unittest.mock import patch

from ortools.sat.python import cp_model

from deterministic_scheduling_core.accepted_work_method_time_experiment import build_problem as accepted_problem
from deterministic_scheduling_core.canonical_cost_experiment import semantic_plan
from deterministic_scheduling_core.converged_scale_experiment import build_problem as scale_problem
from deterministic_scheduling_core.native_work_method_time import build_problem as small_problem
from deterministic_scheduling_core.professional_workface_experiment import build_problem as professional_problem
from deterministic_scheduling_core.professional_scale_challenge import run_challenge
from deterministic_scheduling_core.project.planning_workspace import state_hash
from deterministic_scheduling_core.project.rolling_structural_status import (
    from_document as cycle_from_document, to_document as cycle_to_document,
)
from deterministic_scheduling_core.project.work_method_time import from_document as problem_from_document, input_hash
from deterministic_scheduling_core.rolling_structural_status_experiment import _t2_assertions
from deterministic_scheduling_core.scheduling.accepted_work_method_time import (
    _compile_future_problem, schedule_accepted_work_method_time,
    validate_input as validate_accepted_input, validate_plan as validate_accepted_plan,
)
from deterministic_scheduling_core.scheduling.rolling_structural_status import (
    advance_structural_status_cycle, calculate_structural_recovery,
    promote_structural_recovery_to_status_cycle, validate_cycle,
)
from deterministic_scheduling_core.scheduling.work_method_time import (
    _schedule_work_method_time_sequential_oracle, schedule_work_method_time, validate_plan,
)

FROZEN = Path(__file__).parent / "fixtures" / "canonical-batching-legacy"
SMALL_HASH = "3d8409958ca0b0248d78aad631ce4e0ded7f6c6a5af15ee5c6a108121fcdc7d0"
PRO_HASH = "dea09dd2458b901faa1410c343827cc7bfd0f140ad059b1b87a47381575518bd"
ACCEPTED_HASH = "3c7238a0c8c73a141254a08d491188cbc460cf12146e632192a375a6958da54c"
ROLLING_HASH = "64ebee72814da097951bebf95914e748266c1f788ad7225bae68434ce26f4673"
STATUS_HASH = "f7b3539c05377c7e7e43ba58cbee9f0d91d66a75962c9e84f93b4be92042f880"


def frozen(name):
    return json.loads((FROZEN / name).read_text(encoding="utf-8"))


class AuthoritativeCanonicalBatchingTests(unittest.TestCase):
    def test_160_120_stays_outside_authoritative_admission(self):
        result = run_challenge()
        self.assertTrue(result["faithful_projection_valid"])
        self.assertEqual(result["authoritative_first_failure"]["class"], "ADMISSION_BOUND")
        diagnostic = result["diagnostic_faithful_projection"]
        self.assertEqual((diagnostic["raw_generated_placements"], diagnostic["placement_alternatives"]), (64068, 64032))
        self.assertEqual(diagnostic["placement_limit"], 20000)

    def test_frozen_sequential_plans_validate_without_solving_or_migration(self):
        for name, problem, expected in (
            ("small", small_problem(), SMALL_HASH),
            ("professional", professional_problem(workface=True, deadline=True), PRO_HASH),
        ):
            with self.subTest(name=name):
                old = frozen(f"{name}-sequential-plan.json")
                untouched = deepcopy(old)
                self.assertEqual(old["plan_hash"], expected)
                self.assertEqual(old["solver"]["compiler"], "native-work-method-time/0")
                with patch.object(cp_model.CpSolver, "solve", side_effect=AssertionError("no scheduling")):
                    self.assertEqual(validate_plan(problem, old), "PROVEN_FEASIBLE")
                self.assertEqual(old, untouched)
                authoritative = schedule_work_method_time(problem)
                self.assertEqual(semantic_plan(old), semantic_plan(authoritative.plan))
                self.assertNotEqual(old["plan_hash"], authoritative.plan["plan_hash"])
                self.assertEqual(validate_plan(problem, authoritative.plan), "PROVEN_FEASIBLE")

    def test_batched_proofs_and_complete_canonical_vector_match_oracle(self):
        for name, problem in (
            ("small", small_problem()),
            ("professional", professional_problem(workface=True, deadline=True)),
            ("64_48", scale_problem()),
            ("accepted_resource", accepted_problem()),
        ):
            with self.subTest(name=name):
                source_hash = input_hash(problem)
                oracle = _schedule_work_method_time_sequential_oracle(problem)
                with patch(
                    "deterministic_scheduling_core.scheduling.work_method_time._solve_sequential",
                    side_effect=AssertionError("production must not run sequential oracle"),
                ):
                    batch = schedule_work_method_time(problem)
                self.assertEqual(semantic_plan(batch.plan), semantic_plan(oracle.plan))
                self.assertEqual(batch.plan, schedule_work_method_time(problem).plan)
                self.assertEqual(input_hash(problem), source_hash)
                self.assertEqual(
                    [(row["name"], row["value"]) for row in batch.metrics["canonical_vector"]],
                    [(row["stage"], row["value"]) for row in oracle.metrics["stage_metrics"][2:]],
                )
                blocks = batch.plan["solver"]["canonical_blocks"]
                stages = batch.plan["solver"]["stages"]
                digit_values = {row["name"]: row["value"] for row in batch.metrics["canonical_vector"]}
                self.assertEqual(len(stages), 2 + len(blocks))
                self.assertEqual(len(stages), batch.metrics["solver_calls"])
                self.assertEqual([row["stage"] for row in stages[2:]], [row["name"] for row in blocks])
                for block, stage in zip(blocks, stages[2:]):
                    self.assertEqual(stage["status"], "OPTIMAL")
                    self.assertEqual(block["solved_value"], stage["value"])
                    self.assertLessEqual(block["maximum_possible_value"], block["integer_safety_bound"])
                    self.assertEqual(
                        block["solved_value"],
                        sum(digit_values[digit["name"]] * digit["coefficient"]
                            for digit in block["digits"]),
                    )
                if name == "professional":
                    digits = {row["name"]: row["value"] for row in batch.metrics["canonical_vector"]}
                    self.assertEqual((digits["mode:C_ALT"], digits["placement:C_ALT"]), (0, 0))
                if name == "64_48":
                    self.assertEqual((batch.metrics["placement_alternatives"], oracle.metrics["solver_calls"], batch.metrics["solver_calls"]), (5626, 138, 11))

    def test_frozen_accepted_reference_and_future_recovery(self):
        bundle = frozen("accepted-sequential-reference.json")
        before = deepcopy(bundle)
        problem = problem_from_document(bundle["source"])
        reference = bundle["reference_plan"]
        status = bundle["status_workspace"]
        self.assertEqual(reference["plan_hash"], ACCEPTED_HASH)
        historic_status = state_hash(status)
        self.assertEqual(historic_status, STATUS_HASH)
        with patch.object(cp_model.CpSolver, "solve", side_effect=AssertionError("no scheduling")):
            validate_accepted_input(problem, problem, reference, status)
        recovery = schedule_accepted_work_method_time(problem, problem, reference, status)
        self.assertEqual(recovery.plan["reference_plan_hash"], ACCEPTED_HASH)
        self.assertEqual(recovery.plan["status_state_hash"], historic_status)
        self.assertEqual(recovery.plan["fixed_methods"]["REMOVE"], "LIFT")
        self.assertEqual(recovery.plan["selected_methods"]["RESTORE"], "MANUAL")
        self.assertEqual(recovery.plan["future_plan"]["solver"]["compiler"], "native-work-method-time-batched/0")
        future_problem, _, _ = _compile_future_problem(problem, problem, reference, status)
        oracle = _schedule_work_method_time_sequential_oracle(future_problem)
        self.assertEqual(semantic_plan(recovery.plan["future_plan"]), semantic_plan(oracle.plan))
        # Reconstruct the base-tree accepted-plan shape through the frozen
        # sequential oracle, then independently validate this stored artifact.
        with patch(
            "deterministic_scheduling_core.scheduling.accepted_work_method_time.schedule_work_method_time",
            side_effect=_schedule_work_method_time_sequential_oracle,
        ):
            legacy_recovery = schedule_accepted_work_method_time(problem, problem, reference, status).plan
        self.assertEqual(legacy_recovery["future_plan"]["plan_hash"], oracle.plan["plan_hash"])
        with patch.object(cp_model.CpSolver, "solve", side_effect=AssertionError("no scheduling")):
            self.assertEqual(validate_accepted_plan(problem, problem, reference, status, recovery.plan), "PROVEN_FEASIBLE")
            self.assertEqual(validate_accepted_plan(problem, problem, reference, status, legacy_recovery), "PROVEN_FEASIBLE")
        self.assertEqual(bundle, before)
        self.assertEqual(state_hash(status), historic_status)

    def test_frozen_rolling_cycle_lineage_survives_promotion_and_advance(self):
        historical = frozen("rolling-sequential-cycle.json")
        cycle = cycle_from_document(historical)
        self.assertEqual(cycle_to_document(cycle), historical)
        self.assertEqual(cycle.reference_plan["plan_hash"], ROLLING_HASH)
        old_lineage = deepcopy(cycle.lineage)
        self.assertEqual(old_lineage[0]["prior_reference_plan_hash"], ACCEPTED_HASH)
        self.assertEqual(old_lineage[0]["prior_status_state_hash"], STATUS_HASH)
        self.assertEqual(old_lineage[0]["promoted_reference_plan_hash"], ROLLING_HASH)
        with patch.object(cp_model.CpSolver, "solve", side_effect=AssertionError("no scheduling")):
            validate_cycle(cycle)
        recovery = calculate_structural_recovery(cycle).plan
        self.assertEqual(recovery["reference_plan_hash"], ROLLING_HASH)
        self.assertEqual(recovery["future_plan"]["solver"]["compiler"], "native-work-method-time-batched/0")
        promoted = promote_structural_recovery_to_status_cycle(
            cycle.current_problem, cycle.reference_problem, cycle.reference_plan,
            cycle.status_workspace, recovery, asserted_by="planner", accepted_by="acceptor",
            prior_lineage=cycle.lineage,
        )
        self.assertEqual(promoted.lineage[:-1], old_lineage)
        link = promoted.lineage[-1]
        self.assertEqual(link["prior_reference_plan_hash"], ROLLING_HASH)
        self.assertEqual(link["recovery_plan_hash"], recovery["plan_hash"])
        self.assertEqual(link["promoted_reference_plan_hash"], promoted.reference_plan["plan_hash"])
        self.assertEqual(promoted.reference_plan["solver"]["compiler"], "native-work-method-time-batched/0")
        advanced = advance_structural_status_cycle(
            promoted, 6, _t2_assertions(),
            asserted_by="planner", accepted_by="acceptor",
        )
        self.assertEqual(advanced.lineage, promoted.lineage)
        self.assertEqual(cycle_to_document(cycle), historical)


if __name__ == "__main__":
    unittest.main()
