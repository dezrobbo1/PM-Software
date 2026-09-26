"""Focused exactness and cost-evidence tests for canonical batching."""
from __future__ import annotations

from copy import deepcopy
from itertools import product
from pathlib import Path
import json
import os
import unittest
from unittest.mock import patch

from ortools.sat.python import cp_model

from deterministic_scheduling_core.canonical_cost_experiment import (
    MAX_SAFE_BLOCK_VALUE,
    CanonicalDigit,
    _classify_cost_outcome,
    build_lexicographic_blocks,
    run_cost_decomposition,
    schedule_batched_challenger,
    semantic_plan,
)
from deterministic_scheduling_core.native_work_method_time import build_problem
from deterministic_scheduling_core.professional_workface_experiment import (
    build_problem as build_professional_problem,
)
from deterministic_scheduling_core.project.planning_workspace import digest
from deterministic_scheduling_core.project.work_method_time import WorkMethodTimeProject
from deterministic_scheduling_core.scheduling.work_method_time import (
    _schedule_work_method_time_sequential_oracle,
    schedule_work_method_time,
    validate_plan,
    validate_problem,
)


class LexicographicBlockBuilderTests(unittest.TestCase):
    def test_mixed_radix_preserves_complete_lexicographic_order(self):
        digits = tuple(CanonicalDigit(name, maximum) for name, maximum in (
            ("method", 2), ("mode", 3), ("placement", 4)
        ))
        block = build_lexicographic_blocks(digits)[0]
        vectors = list(product(*(range(digit.maximum + 1) for digit in digits)))
        encoded = [sum(value * coefficient for value, coefficient in zip(vector, block.coefficients))
                   for vector in vectors]
        self.assertEqual(vectors, sorted(vectors))
        self.assertEqual(encoded, sorted(encoded))
        self.assertEqual(len(encoded), len(set(encoded)))
        self.assertEqual(max(encoded), block.maximum)

    def test_builder_splits_before_unsafe_expansion_and_rejects_unsafe_digit(self):
        digits = tuple(CanonicalDigit(f"d{i}", 9) for i in range(3))
        blocks = build_lexicographic_blocks(digits, safety_bound=99)
        self.assertEqual([len(block.digits) for block in blocks], [2, 1])
        self.assertTrue(all(block.maximum <= 99 for block in blocks))
        self.assertTrue(all(block.to_document()["integer_safety_bound"] == 99
                            for block in blocks))
        with self.assertRaisesRegex(ValueError, "digit maximum exceeds"):
            build_lexicographic_blocks((CanonicalDigit("unsafe", 100),), safety_bound=99)
        with self.assertRaisesRegex(ValueError, "safety_bound"):
            build_lexicographic_blocks((), safety_bound=MAX_SAFE_BLOCK_VALUE + 1)

    def test_zero_contribution_digits_and_construction_are_deterministic(self):
        digits = (CanonicalDigit("inactive-method", 0), CanonicalDigit("active-mode", 2))
        first = build_lexicographic_blocks(digits)
        second = build_lexicographic_blocks(digits)
        self.assertEqual(first, second)
        self.assertEqual(first[0].coefficients, (3, 1))
        self.assertEqual(first[0].maximum, 2)


class CanonicalCostExperimentTests(unittest.TestCase):
    MEASURED_CLASSIFICATIONS = {
        "A_CANONICAL_PROOF_DOMINATED",
        "B_PLACEMENT_GENERATION_DOMINATED",
        "C_MIXED_BOTTLENECK",
        "D_CHALLENGER_NOT_JUSTIFIED",
    }

    @classmethod
    def setUpClass(cls):
        cls.result = run_cost_decomposition()
        output = os.environ.get("CANONICAL_COST_EVIDENCE_OUTPUT")
        if output:
            path = Path(output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(cls.result, indent=2) + "\n", encoding="utf-8")
        cls.by_name = {case["name"]: case for case in cls.result["cases"]}

    def test_sequential_oracle_preserves_known_historical_plan_bytes(self):
        known = {
            "small": (build_problem(), "3d8409958ca0b0248d78aad631ce4e0ded7f6c6a5af15ee5c6a108121fcdc7d0"),
            "professional": (
                build_professional_problem(workface=True, deadline=True),
                "dea09dd2458b901faa1410c343827cc7bfd0f140ad059b1b87a47381575518bd",
            ),
        }
        for name, (problem, expected_hash) in known.items():
            with self.subTest(name=name):
                result = _schedule_work_method_time_sequential_oracle(problem)
                self.assertEqual(result.plan["plan_hash"], expected_hash)
                self.assertIn("validation_ms", result.metrics)
                self.assertIn("stage_metrics", result.metrics)
                self.assertEqual(len(result.metrics["stage_metrics"]), result.metrics["solver_calls"])

    def test_all_cases_match_exact_policy_semantic_plan_physics_and_repeat(self):
        self.assertTrue(self.result["evidence_valid"])
        self.assertIn(self.result["classification"], self.MEASURED_CLASSIFICATIONS)
        for case in self.result["cases"]:
            with self.subTest(case=case["name"]):
                self.assertTrue(all(case["equivalence"].values()))
                self.assertLess(case["challenger"]["total_stages"], case["sequential"]["total_stages"])
                self.assertTrue(case["challenger"]["blocks"])
                self.assertEqual(
                    len(case["sequential"]["stage_evidence"]),
                    case["sequential"]["total_stages"],
                )
                self.assertTrue(all(stage["status"] == "OPTIMAL"
                                    for stage in case["sequential"]["stage_evidence"]))

    def test_required_anchor_stage_counts_and_professional_semantics_are_retained(self):
        scale = self.by_name["converged_64_48"]
        self.assertEqual(scale["sequential"]["total_stages"], 138)
        self.assertEqual(scale["shape"]["declared_activities"], 64)
        self.assertEqual(scale["shape"]["active_activities"], 48)
        self.assertEqual(
            [stage["deterministic_time"] for stage in scale["sequential"]["stage_evidence"][:2]],
            [stage["deterministic_time"] for stage in scale["challenger"]["stage_evidence"][:2]],
        )
        professional = self.by_name["professional_semantics_small"]
        self.assertGreater(professional["shape"]["workface_intervals"], 0)
        self.assertTrue(professional["equivalence"]["exact_semantic_plan_match"])

    def test_challenger_retains_suspension_envelope_and_protected_finish_semantics(self):
        workface_problem = build_professional_problem(workface=True)
        workface = schedule_batched_challenger(workface_problem)
        by_id = {entry["activity_id"]: entry for entry in workface.plan["entries"]}
        self.assertEqual(by_id["A_FAST"]["periods"], [[0, 2], [4, 6]])
        self.assertEqual(by_id["A_FAST"]["finish"], by_id["B"]["start"])

        protected_problem = build_professional_problem(workface=True, deadline=True)
        protected = schedule_batched_challenger(protected_problem)
        protected_by_id = {entry["activity_id"]: entry for entry in protected.plan["entries"]}
        self.assertEqual(protected.plan["selected_methods"]["BUILD"], "ALT")
        self.assertLessEqual(protected_by_id["B"]["finish"], 3)
        self.assertNotIn("C_ALT", protected_by_id)
        vector = {digit["name"]: digit["value"]
                  for digit in protected.metrics["canonical_vector"]}
        self.assertEqual(vector["mode:C_ALT"], 0)
        self.assertEqual(vector["placement:C_ALT"], 0)

    def test_stage_ladder_holds_placement_density_and_grows_stage_count(self):
        cases = [self.by_name[f"stage_{count}"] for count in (8, 16, 32, 48, 64)]
        self.assertEqual([case["shape"]["placement_alternatives"] for case in cases],
                         [8, 16, 32, 48, 64])
        self.assertEqual([case["sequential"]["total_stages"] for case in cases],
                         [18, 34, 66, 98, 130])

    def test_fixed_model_prefix_ladder_isolates_sequential_proof_count(self):
        evidence = self.result["fixed_model_stage_prefix_ladder"]
        self.assertTrue(evidence["evidence_valid"])
        self.assertTrue(evidence["complete_policy_only_in_final_row"])
        rows = evidence["rows"]
        self.assertEqual([row["total_stages"] for row in rows], [18, 34, 66, 98, 130])
        self.assertEqual(len({(
            row["declared_activities"],
            row["placement_alternatives"],
            row["base_variables"],
            row["base_constraints"],
        ) for row in rows}), 1)
        self.assertEqual(rows[0]["declared_activities"], 64)
        self.assertEqual(rows[0]["placement_alternatives"], 64)

    def test_exit_classification_is_derived_from_measured_costs(self):
        classification, _, basis = _classify_cost_outcome(self.result["cases"], True)
        self.assertEqual(classification, self.result["classification"])
        self.assertIn(classification, self.MEASURED_CLASSIFICATIONS)
        self.assertTrue(all(isinstance(value, bool)
                            for value in basis["measured_predicates"].values()))

        contradicted = deepcopy(self.result["cases"])
        scale = next(case for case in contradicted if case["name"] == "converged_64_48")
        scale["challenger"]["end_to_end_ms"] = scale["sequential"]["end_to_end_ms"] * 2
        classification, _, _ = _classify_cost_outcome(contradicted, True)
        self.assertEqual(classification, "D_CHALLENGER_NOT_JUSTIFIED")
        classification, _, _ = _classify_cost_outcome(contradicted, False)
        self.assertEqual(classification, "E_NEW_CORRECTNESS_FAILURE")

        assembly_dominated = deepcopy(self.result["cases"])
        scale = next(case for case in assembly_dominated
                     if case["name"] == "converged_64_48")
        solve_ms = scale["sequential"]["solve_ms"]
        scale["sequential"]["placement_generation_ms"] = 1
        scale["sequential"]["cp_model_assembly_ms"] = solve_ms * 2
        scale["sequential"]["build_ms"] = solve_ms * 3
        classification, recommendation, basis = _classify_cost_outcome(
            assembly_dominated, True
        )
        self.assertEqual(classification, "B_PLACEMENT_GENERATION_DOMINATED")
        self.assertEqual(basis["construction_dominant_component"], "cp_model_assembly")
        self.assertIn("CP-model assembly", recommendation)

        scale["challenger"]["end_to_end_ms"] = scale["sequential"]["end_to_end_ms"]
        classification, _, _ = _classify_cost_outcome(assembly_dominated, True)
        self.assertEqual(classification, "D_CHALLENGER_NOT_JUSTIFIED")

    def test_density_ladder_holds_stage_count_and_grows_model(self):
        cases = [self.by_name[f"density_{horizon}"] for horizon in (16, 64, 192, 480)]
        self.assertEqual({case["sequential"]["total_stages"] for case in cases}, {18})
        placements = [case["shape"]["placement_alternatives"] for case in cases]
        variables = [case["shape"]["sequential_variables"] for case in cases]
        self.assertEqual(placements, sorted(placements))
        self.assertEqual(variables, sorted(variables))
        self.assertEqual(len(set(placements)), len(placements))

    def test_source_admission_and_stored_plan_validation_are_unchanged(self):
        problem = build_professional_problem(workface=True, deadline=True)
        before = deepcopy(problem.project)
        result = schedule_batched_challenger(problem)
        with patch.object(
            cp_model.CpSolver,
            "solve",
            side_effect=AssertionError("stored-plan validation must not solve"),
        ):
            self.assertEqual(validate_plan(problem, result.plan), "PROVEN_FEASIBLE")
        self.assertEqual(problem.project, before)
        illegal = deepcopy(result.plan)
        entry = next(row for row in illegal["entries"] if row["activity_id"] == "B")
        entry["finish"] = 4
        illegal["plan_hash"] = digest({key: value for key, value in illegal.items() if key != "plan_hash"})
        with self.assertRaisesRegex(ValueError, "latest_finish"):
            validate_plan(problem, illegal)
        oversized = WorkMethodTimeProject({**deepcopy(problem.project), "activities": [
            *deepcopy(problem.project["activities"]),
            *({"id": f"X{i}", "name": f"X{i}", "modes": [{
                "id": "FIXED", "processing_ticks": 0, "calendar_id": "ALWAYS",
                "continuity": "SUSPENDABLE_AT_AVAILABILITY_GAPS", "requirements": [],
            }]} for i in range(55)),
        ]})
        with self.assertRaisesRegex(ValueError, "1..64 declared activities"):
            validate_problem(oversized)

    def test_professional_160_120_remains_classification_only(self):
        result = self.result["professional_scale_follow_up"]
        self.assertEqual(result["authoritative_first_failure"]["class"], "ADMISSION_BOUND")
        self.assertTrue(result["faithful_projection_valid"])
        diagnostic = result["diagnostic_faithful_projection"]
        self.assertEqual(diagnostic["raw_generated_placements"], 64068)
        self.assertEqual(diagnostic["placement_alternatives"], 64032)

    def test_direct_challenger_projection_matches_authoritative_plan_fields(self):
        problem = build_problem()
        oracle = _schedule_work_method_time_sequential_oracle(problem)
        authoritative = schedule_work_method_time(problem)
        self.assertEqual(semantic_plan(oracle.plan), semantic_plan(authoritative.plan))
        self.assertNotEqual(oracle.plan["solver"]["compiler"], authoritative.plan["solver"]["compiler"])


if __name__ == "__main__":
    unittest.main()
