"""Bounded model identity and fail-closed exact-proof contracts."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import subprocess
import unittest
from unittest.mock import patch

from ortools.sat.python import cp_model

from deterministic_scheduling_core.errors import SchedulingError
from deterministic_scheduling_core.professional_workface_experiment import build_problem as professional_small
from deterministic_scheduling_core.project.work_method_time import input_hash
from deterministic_scheduling_core.scheduling import work_method_time as production
from deterministic_scheduling_core.professional_160_exact_solve_experiment import (
    EXPECTED_INPUT_HASH, _experimental_validate, _head, _run_policy, _stable_result, main, prepare, run,
)
from deterministic_scheduling_core.w1_model_integration_experiment import (
    _blocks, compile_compact, validate_experimental, w1_domain,
)


class ProfessionalFirstSolveControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.problem, cls.indexed, cls.allowed, cls.compiled, cls.ranked, cls.blocks, cls.evidence = prepare()

    def test_source_domain_and_rank_holes(self):
        e = self.evidence
        self.assertEqual(e["professional_input_hash"], EXPECTED_INPUT_HASH)
        self.assertEqual((e["domain"]["u0_raw"], e["domain"]["u0_eligible"],
                          e["domain"]["w1_retained"]), (64068, 64032, 7812))
        self.assertEqual((e["domain"]["resource_optional_intervals"],
                          e["domain"]["workface_optional_intervals"]), (6705, 409))
        self.assertEqual((e["domain"]["canonical_digits"], e["domain"]["canonical_blocks"]), (332, 26))
        self.assertEqual((e["model"]["pre_canonical"]["variables"],
                          e["model"]["pre_canonical"]["constraints"]), (8308, 7952))
        self.assertEqual((e["model"]["post_witness"]["variables"],
                          e["model"]["post_witness"]["constraints"]), (8640, 8284))
        self.assertEqual(sum(len(x) for x in self.allowed.values()), self.compiled.placement_count)
        holes = [(aid, ranks) for aid, ranks in self.allowed.items()
                 if ranks and len(ranks) < max(ranks)]
        self.assertTrue(holes)
        for aid, ranks in holes:
            stage = next(s for s in self.compiled.stages if s.name == f"placement:{aid}")
            self.assertEqual(stage.maximum, len(self.indexed[aid]))
            self.assertEqual({rank for rank, *_ in self.ranked[aid]}, ranks)
        self.assertEqual(input_hash(self.problem), EXPECTED_INPUT_HASH)

    def test_public_rejects_160_diagnostic_validator_only(self):
        with self.assertRaisesRegex(ValueError, "1..64 declared activities"):
            production.validate_problem(self.problem)
        validate_experimental(self.problem)
        with self.assertRaises(AssertionError):
            validate_experimental(self.problem, limit=161)
        with self.assertRaisesRegex(ValueError, "recorded pre-install SHA"):
            _head("wrong")
        _head(subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip())

    def test_repeatability_ignores_only_noisy_wall_observation(self):
        first = {"objective": [60, 363133], "plan_signature": "fixed",
                 "extraction_validation_wall_ms": {"independent_allocation_ms": 12.0}}
        second = deepcopy(first)
        second["extraction_validation_wall_ms"]["independent_allocation_ms"] = 35.0
        self.assertEqual(_stable_result(first), _stable_result(second))
        second["plan_signature"] = "changed"
        self.assertNotEqual(_stable_result(first), _stable_result(second))

    def test_unknown_finish_captures_query_and_does_not_fallback(self):
        class UnknownSolver:
            def __init__(self):
                self.parameters = SimpleNamespace(max_deterministic_time=60.0)
                self.response_proto = SimpleNamespace(deterministic_time=1.5, wall_time=0.002)

            def solve(self, _):
                return cp_model.UNKNOWN

            def status_name(self, status):
                return cp_model.CpSolver().status_name(status)

        record = {"model": self.evidence["model"]}
        with patch("deterministic_scheduling_core.professional_160_exact_solve_experiment.production._new_solver",
                   return_value=UnknownSolver()), patch.object(production, "_solve_compiled_stages",
                   side_effect=AssertionError("no fallback")):
            self.assertIsNone(_run_policy(self.problem, self.indexed, self.allowed,
                self.compiled, self.ranked, self.blocks, record, lambda: None))
        self.assertEqual(record["classification"], "EXACT_FINISH_NOT_PROVEN_WITHIN_DECLARED_BUDGET")
        self.assertEqual(record["finish_proof"]["queries"][0]["result"], "UNKNOWN")
        self.assertEqual(record["finish_proof"]["queries"][0]["budget_before"], 60.0)
        self.assertEqual(record["finish_proof"]["queries"][0]["deterministic_time"], 1.5)

    def test_later_unknown_and_feasible_are_not_optimal(self):
        for returned in (cp_model.FEASIBLE, cp_model.UNKNOWN):
            with self.subTest(status=returned):
                class StageSolver:
                    def __init__(self):
                        self.response_proto = SimpleNamespace(deterministic_time=0.25, wall_time=0.001)

                    def solve(self, _):
                        return returned

                    def status_name(self, value):
                        return cp_model.CpSolver().status_name(value)

                problem, indexed, allowed, compiled, ranked, blocks, evidence = prepare()
                record = {"model": evidence["model"]}
                with patch("deterministic_scheduling_core.professional_160_exact_solve_experiment.prove_finish",
                           return_value=(48, [], 60.0, "digest")), patch(
                    "deterministic_scheduling_core.professional_160_exact_solve_experiment.production._new_solver",
                    return_value=StageSolver()):
                    self.assertIsNone(_run_policy(problem, indexed, allowed, compiled,
                        ranked, blocks, record, lambda: None))
                self.assertEqual(record["classification"], "EXACT_FINISH_PROVEN_LOWER_POLICY_INCOMPLETE")
                self.assertEqual(record["stopped_stage"], "global_start_timing")
                self.assertEqual(record["lower_policy"]["completed_blocks"], 0)

    def test_budget_infeasibility_and_model_invalid_remain_distinct(self):
        for error, expected in (("UNKNOWN: shared finish proof budget exhausted",
                                 "EXACT_FINISH_NOT_PROVEN_WITHIN_DECLARED_BUDGET"),
                                ("INFEASIBLE: no executable authorised structure",
                                 "MODEL_INFEASIBLE"),
                                ("MODEL_INVALID: finish not proven", "MODEL_OR_VALIDATION_DEFECT")):
            with self.subTest(error=error), patch(
                "deterministic_scheduling_core.professional_160_exact_solve_experiment.prove_finish",
                side_effect=SchedulingError(error)):
                record = {"model": self.evidence["model"]}
                self.assertIsNone(_run_policy(self.problem, self.indexed, self.allowed,
                    self.compiled, self.ranked, self.blocks, record, lambda: None))
                self.assertEqual(record["classification"], expected)

    def test_source_bound_partial_defect_writes_checkpoint(self):
        sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        with TemporaryDirectory() as directory, patch(
            "deterministic_scheduling_core.professional_160_exact_solve_experiment.prepare",
            side_effect=AssertionError("injected model discrepancy")):
            output = Path(directory) / "partial.json"
            result = run(sha, output, repeat_on_success=False, controls=False)
            self.assertEqual(result["classification"], "MODEL_OR_VALIDATION_DEFECT")
            self.assertEqual(result["source_sha"], sha)
            import json
            stored = json.loads(output.read_text())
            self.assertEqual(stored["classification"], result["classification"])
            self.assertIn("injected model discrepancy", stored["error"])

    def test_cli_reports_success_only_for_complete_exact_proof(self):
        classifications = ("COMPLETE_EXACT_POLICY_PROVEN",
                           "EXACT_FINISH_PROVEN_LOWER_POLICY_INCOMPLETE",
                           "EXACT_FINISH_NOT_PROVEN_WITHIN_DECLARED_BUDGET",
                           "MODEL_INFEASIBLE", "MODEL_OR_VALIDATION_DEFECT")
        for classification in classifications:
            with self.subTest(classification=classification), patch(
                "sys.argv", ["experiment", "--source-sha", "head", "--output", "/tmp/result.json"]
            ), patch("deterministic_scheduling_core.professional_160_exact_solve_experiment.run",
                     return_value={"source_sha": "head", "classification": classification,
                                   "finish_proof": {}, "lower_policy": {}, "solver_calls": 0}), patch(
                "builtins.print"):
                if classification == "COMPLETE_EXACT_POLICY_PROVEN":
                    self.assertIsNone(main())
                else:
                    with self.assertRaises(SystemExit) as stopped:
                        main()
                    self.assertEqual(stopped.exception.code, 1)

    def test_independent_physical_validator_retains_hard_deadline(self):
        small = professional_small(workface=True, deadline=True)
        plan = production.schedule_work_method_time(small).plan
        self.assertEqual(_experimental_validate(small, plan), production.ra.EXACT_FEASIBLE)
        modified = deepcopy(plan)
        protected = next(row for row in modified["entries"] if row["activity_id"] == "B")
        protected["finish"] += 1
        modified["plan_hash"] = production._hash_plan(modified)
        with self.assertRaises(ValueError):
            _experimental_validate(small, modified)


if __name__ == "__main__":
    unittest.main()
