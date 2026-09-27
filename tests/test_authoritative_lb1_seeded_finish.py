"""Source-frozen S0 history and exact LB1-seeded finish adoption controls."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ortools.sat.python import cp_model

from deterministic_scheduling_core.accepted_work_method_time_experiment import (
    build_problem as accepted_problem, build_status_workspace,
)
from deterministic_scheduling_core.canonical_cost_experiment import semantic_plan
from deterministic_scheduling_core.converged_scale_experiment import build_problem as scale_problem
from deterministic_scheduling_core.errors import SchedulingError
from deterministic_scheduling_core.factored_finish_search_experiment import build_group_stress
from deterministic_scheduling_core.native_work_method_time import build_problem as small_problem
from deterministic_scheduling_core.professional_workface_experiment import build_problem as professional_problem
from deterministic_scheduling_core.project.planning_workspace import state_hash
from deterministic_scheduling_core.project.rolling_structural_status import (
    from_document as cycle_from_document, to_document as cycle_to_document, save as save_cycle, load as load_cycle,
)
from deterministic_scheduling_core.project.work_method_time import from_document, input_hash
from deterministic_scheduling_core.rolling_structural_status_experiment import _t2_assertions
from deterministic_scheduling_core.scheduling.accepted_work_method_time import (
    _compile_future_problem, schedule_accepted_work_method_time, validate_input as validate_accepted_input,
    validate_plan as validate_accepted_plan,
)
from deterministic_scheduling_core.scheduling.finish_lower_bound import authorised_precedence_lower_bound
from deterministic_scheduling_core.scheduling.finish_search import exact_bound_search, maximum_queries, prove_finish
from deterministic_scheduling_core.scheduling.rolling_structural_status import (
    advance_structural_status_cycle, calculate_structural_recovery,
    promote_structural_recovery_to_status_cycle, validate_cycle,
)
from deterministic_scheduling_core.scheduling.work_method_time import (
    _compile_work_method_time, _new_solver, _schedule_work_method_time_batched,
    _schedule_work_method_time_sequential_oracle, schedule_work_method_time, validate_plan,
)

FROZEN = Path(__file__).parent / "fixtures" / "lb1-seeded-legacy"
SEQUENTIAL = Path(__file__).parent / "fixtures" / "canonical-batching-legacy"
HASHES = {"small": "458a5927a645fb2eed8a8ac432c0262d2bfcf23d3ae222a4e9f32d4682569ab5",
          "professional": "61add1ea57ede769cb676aa11f93b31eb5696f8f691b22b22a38b9f146172a7d",
          "scale_64_48": "88f125d76b5cdbe4f18e14834767e964e5b29f2db21a2c839481e1399e21f63f"}


def frozen(name, directory=FROZEN):
    return json.loads((directory / name).read_text(encoding="utf-8"))


class AuthoritativeLB1FinishTests(unittest.TestCase):
    def test_historical_generations_validate_without_solver_or_mutation(self):
        cases = (("small", small_problem()),
                 ("professional", professional_problem(workface=True, deadline=True)),
                 ("scale_64_48", scale_problem()))
        for name, problem in cases:
            with self.subTest(name=name):
                old = frozen(f"{name}-batched-plan.json")
                before = deepcopy(old)
                self.assertEqual(old["plan_hash"], HASHES[name])
                self.assertEqual(old["solver"]["compiler"], "native-work-method-time-batched/0")
                with patch.object(cp_model.CpSolver, "solve", side_effect=AssertionError("no solve")):
                    self.assertEqual(validate_plan(problem, old), "PROVEN_FEASIBLE")
                self.assertEqual(old, before)
        for name, problem in (("small", small_problem()),
                              ("professional", professional_problem(workface=True, deadline=True))):
            old = frozen(f"{name}-sequential-plan.json", SEQUENTIAL)
            before = deepcopy(old)
            with patch.object(cp_model.CpSolver, "solve", side_effect=AssertionError("no solve")):
                self.assertEqual(validate_plan(problem, old), "PROVEN_FEASIBLE")
            self.assertEqual(old, before)

    def test_complete_semantics_history_and_truthful_proof(self):
        for name, problem in (("small", small_problem()),
                              ("professional", professional_problem(workface=True, deadline=True)),
                              ("scale_64_48", scale_problem()),
                              ("group", build_group_stress()),
                              ("suspended", professional_problem(workface=True, deadline=False)),
                              ("fixed_network", accepted_problem())):
            with self.subTest(name=name):
                before = input_hash(problem)
                old = _schedule_work_method_time_batched(problem)
                if name in HASHES:
                    self.assertEqual(old.plan["plan_hash"], HASHES[name])
                with patch("deterministic_scheduling_core.scheduling.work_method_time._schedule_work_method_time_batched",
                           side_effect=AssertionError("no oracle in production")), patch(
                           "deterministic_scheduling_core.scheduling.work_method_time._schedule_work_method_time_sequential_oracle",
                           side_effect=AssertionError("no sequential in production")):
                    current = schedule_work_method_time(problem)
                repeat = schedule_work_method_time(problem)
                self.assertEqual(semantic_plan(current.plan), semantic_plan(old.plan))
                self.assertEqual(current.plan, repeat.plan)
                self.assertEqual(current.metrics["canonical_vector"], old.metrics["canonical_vector"])
                self.assertEqual(current.plan["physical_status"], "PROVEN_FEASIBLE")
                self.assertEqual(current.plan["solver"]["compiler"], "native-work-method-time-lb1-seeded/0")
                self.assertNotEqual(current.plan["plan_hash"], old.plan["plan_hash"])
                self.assertEqual(input_hash(problem), before)
                self.assertEqual(len(current.plan["solver"]["stages"]), current.metrics["policy_stage_count"])
                self.assertEqual(len(current.metrics["stage_metrics"]), current.metrics["policy_stage_count"])
                self.assertEqual(current.metrics["solver_calls"], current.metrics["finish_query_count"] +
                                 current.metrics["policy_stage_count"] - 1)
                proof = current.plan["solver"]["stages"][0]
                self.assertEqual(proof["status"], "PROVEN_EXACT")
                self.assertEqual(proof["proof_kind"], "lb1-seeded-sat-search/0")
                self.assertEqual(proof["lower_bound"]["value"], current.metrics["finish_lower_bound"])
                self.assertEqual(proof["queries"], [{"bound": row["bound"], "result": row["result"]}
                                                    for row in current.metrics["finish_query_metrics"]])
                self.assertTrue(all(row["status"] == "OPTIMAL" for row in current.plan["solver"]["stages"][1:]))
                self.assertGreaterEqual(current.metrics["finish_remaining_deterministic_budget"], 0)
                self.assertEqual(validate_plan(problem, current.plan), "PROVEN_FEASIBLE")
                if name == "scale_64_48":
                    self.assertEqual((current.plan["objective"][0], current.metrics["finish_lower_bound"],
                                      current.metrics["finish_query_count"], current.metrics["solver_calls"]),
                                     (19, 19, 1, 11))
                if name == "small":
                    self.assertEqual((current.metrics["finish_lower_bound"], current.plan["objective"][0]), (27, 30))
                    self.assertEqual([(r["bound"], r["result"]) for r in current.metrics["finish_query_metrics"]],
                                     [(27, "INFEASIBLE"), (28, "INFEASIBLE"), (29, "INFEASIBLE"),
                                      (31, "SAT"), (30, "SAT")])

    def test_exhaustive_pure_query_order_and_maximum(self):
        observed = 0
        for lower in range(481):
            for finish in range(lower, 481):
                queried = []
                def ask(bound):
                    queried.append(bound)
                    return bound >= finish
                self.assertEqual(exact_bound_search(lower, 480, ask), finish)
                self.assertEqual(len(queried), len(set(queried)))
                self.assertLessEqual(len(queried), maximum_queries(480))
                observed = max(observed, len(queried))
        self.assertEqual((observed, maximum_queries(480)), (19, 19))
        with self.assertRaisesRegex(SchedulingError, "INFEASIBLE"):
            exact_bound_search(481, 480, lambda b: False)
        with self.assertRaisesRegex(SchedulingError, "INFEASIBLE"):
            exact_bound_search(480, 480, lambda b: False)
        with self.assertRaisesRegex(SchedulingError, "INFEASIBLE"):
            exact_bound_search(0, 480, lambda b: False)
        with patch("deterministic_scheduling_core.scheduling.finish_search.maximum_queries", return_value=0):
            with self.assertRaisesRegex(AssertionError, "query-count"):
                exact_bound_search(0, 480, lambda b: True)

    def test_budget_and_status_fail_closed(self):
        compiled = _compile_work_method_time(small_problem())
        lower, _ = authorised_precedence_lower_bound(compiled.problem)
        class MockSolver:
            def __init__(self, status, used, bad_finish=False):
                self.status, self.parameters = status, SimpleNamespace(max_deterministic_time=None)
                self.response_proto = SimpleNamespace(deterministic_time=used, wall_time=0)
                self.bad_finish = bad_finish
            def solve(self, model):
                return self.status
            def value(self, var):
                return lower - 1 if self.bad_finish else lower
            def status_name(self, status):
                return {cp_model.UNKNOWN: "UNKNOWN", cp_model.MODEL_INVALID: "MODEL_INVALID",
                        cp_model.OPTIMAL: "OPTIMAL", cp_model.INFEASIBLE: "INFEASIBLE"}[status]
        for status in (cp_model.UNKNOWN, cp_model.MODEL_INVALID):
            with self.assertRaisesRegex(SchedulingError, "not proven"):
                prove_finish(compiled, lower, new_solver=lambda s=status: MockSolver(s, 0), budget=60)
        with self.assertRaisesRegex(AssertionError, "LB1 contradicted"):
            prove_finish(compiled, lower, new_solver=lambda: MockSolver(cp_model.OPTIMAL, 0, True), budget=60)
        created = []
        def solver_factory():
            obj = MockSolver(cp_model.INFEASIBLE, 31)
            created.append(obj)
            return obj
        with self.assertRaisesRegex(SchedulingError, "budget exceeded"):
            prove_finish(compiled, lower, new_solver=solver_factory, budget=60)
        self.assertEqual(len(created), 2)
        self.assertEqual([x.parameters.max_deterministic_time for x in created], [60, 29])
        statuses = iter((cp_model.INFEASIBLE, cp_model.UNKNOWN))
        with self.assertRaisesRegex(SchedulingError, "not proven"):
            prove_finish(compiled, lower, new_solver=lambda: MockSolver(next(statuses), 0), budget=60)
        statuses = iter((cp_model.INFEASIBLE, cp_model.INFEASIBLE))
        with self.assertRaisesRegex(SchedulingError, "budget exhausted"):
            prove_finish(compiled, lower, new_solver=lambda: MockSolver(next(statuses), 30), budget=60)

    def test_infeasibility_is_not_unknown_and_no_proof_leaks(self):
        base = small_problem()
        too_short = deepcopy(base.project)
        too_short["horizon_ticks"] = 29  # source-valid; even the fastest full execution needs 30.
        with self.assertRaisesRegex(SchedulingError, "INFEASIBLE: no executable"):
            schedule_work_method_time(replace(base, project=too_short))
        below_relaxed_finish = deepcopy(base.project)
        below_relaxed_finish["horizon_ticks"] = 26  # LB1 > admitted horizon.
        with self.assertRaisesRegex(SchedulingError, "INFEASIBLE: no executable"):
            schedule_work_method_time(replace(base, project=below_relaxed_finish))

    def test_accepted_nonexact_lb1_future_not_derived_from_actual_periods(self):
        bundle = frozen("accepted-batched-reference.json")
        problem = from_document(bundle["source"])
        status = build_status_workspace(problem, bundle["reference_plan"], remaining_ticks=4)
        before = deepcopy(status)
        future, _, _ = _compile_future_problem(problem, problem, bundle["reference_plan"], status)
        s2 = schedule_work_method_time(future)
        s0 = _schedule_work_method_time_batched(future)
        self.assertEqual((s2.metrics["finish_lower_bound"], s2.plan["objective"][0]), (8, 10))
        self.assertGreater(s2.metrics["finish_query_count"], 1)
        self.assertEqual(semantic_plan(s2.plan), semantic_plan(s0.plan))
        accepted = schedule_accepted_work_method_time(problem, problem, bundle["reference_plan"], status)
        self.assertEqual(semantic_plan(accepted.plan["future_plan"]), semantic_plan(s0.plan))
        self.assertEqual(accepted.plan["fixed_methods"]["REMOVE"], "LIFT")
        self.assertEqual(status, before)

    def test_new_s2_accepted_reference_keeps_history_and_oracle_future(self):
        problem = accepted_problem()
        reference = schedule_work_method_time(problem).plan
        status = build_status_workspace(problem, reference, remaining_ticks=4)
        before = deepcopy(status)
        with patch.object(cp_model.CpSolver, "solve", side_effect=AssertionError("no solve")):
            validate_accepted_input(problem, problem, reference, status)
        future, _, _ = _compile_future_problem(problem, problem, reference, status)
        recovery = schedule_accepted_work_method_time(problem, problem, reference, status).plan
        self.assertEqual(recovery["reference_plan_hash"], reference["plan_hash"])
        self.assertEqual(recovery["status_state_hash"], state_hash(status))
        self.assertEqual(recovery["future_plan"]["solver"]["compiler"], "native-work-method-time-lb1-seeded/0")
        self.assertEqual(semantic_plan(recovery["future_plan"]),
                         semantic_plan(_schedule_work_method_time_batched(future).plan))
        self.assertEqual(status, before)

    def test_frozen_accepted_and_rolling_history(self):
        bundle = frozen("accepted-batched-reference.json")
        before = deepcopy(bundle)
        problem = from_document(bundle["source"])
        reference, status = bundle["reference_plan"], bundle["status_workspace"]
        self.assertEqual(reference["plan_hash"], "74713c6e4f9afd8876764b2a3c3c9a0c1079312b8559c5b34e4d2a66a6bb40ca")
        history_hash = state_hash(status)
        with patch.object(cp_model.CpSolver, "solve", side_effect=AssertionError("no solve")):
            validate_accepted_input(problem, problem, reference, status)
        recovery = schedule_accepted_work_method_time(problem, problem, reference, status).plan
        future_problem, _, _ = _compile_future_problem(problem, problem, reference, status)
        oracle = _schedule_work_method_time_batched(future_problem)
        self.assertEqual(semantic_plan(recovery["future_plan"]), semantic_plan(oracle.plan))
        self.assertEqual(recovery["future_plan"]["solver"]["compiler"], "native-work-method-time-lb1-seeded/0")
        self.assertEqual(recovery["reference_plan_hash"], reference["plan_hash"])
        with patch("deterministic_scheduling_core.scheduling.accepted_work_method_time.schedule_work_method_time",
                   side_effect=_schedule_work_method_time_batched):
            historical_recovery = schedule_accepted_work_method_time(problem, problem, reference, status).plan
        with patch.object(cp_model.CpSolver, "solve", side_effect=AssertionError("no solve")):
            self.assertEqual(validate_accepted_plan(problem, problem, reference, status, historical_recovery),
                             "PROVEN_FEASIBLE")
            self.assertEqual(validate_accepted_plan(problem, problem, reference, status, recovery),
                             "PROVEN_FEASIBLE")
        self.assertEqual(state_hash(status), history_hash)
        self.assertEqual(bundle, before)
        cycle_doc = frozen("rolling-batched-cycle.json")
        cycle = cycle_from_document(cycle_doc)
        old_lineage = deepcopy(cycle.lineage)
        self.assertEqual(cycle.reference_plan["plan_hash"], "bca8421d3077b9cc1b8a6d05a548491d851ea7ce79eb0ef57d57207c54196824")
        with patch.object(cp_model.CpSolver, "solve", side_effect=AssertionError("no solve")):
            validate_cycle(cycle)
        self.assertEqual(cycle_to_document(cycle), cycle_doc)
        recovered = calculate_structural_recovery(cycle).plan
        self.assertEqual(recovered["future_plan"]["solver"]["compiler"], "native-work-method-time-lb1-seeded/0")
        promoted = promote_structural_recovery_to_status_cycle(
            cycle.current_problem, cycle.reference_problem, cycle.reference_plan, cycle.status_workspace,
            recovered, asserted_by="planner", accepted_by="acceptor", prior_lineage=cycle.lineage,
        )
        self.assertEqual(promoted.lineage[:-1], old_lineage)
        self.assertEqual(promoted.lineage[-1]["prior_reference_plan_hash"], cycle.reference_plan["plan_hash"])
        self.assertEqual(promoted.lineage[-1]["recovery_plan_hash"], recovered["plan_hash"])
        self.assertEqual(promoted.lineage[-1]["promoted_reference_plan_hash"], promoted.reference_plan["plan_hash"])
        advanced = advance_structural_status_cycle(
            promoted, 6, _t2_assertions(), asserted_by="planner", accepted_by="acceptor")
        self.assertEqual(advanced.lineage[:len(old_lineage)], old_lineage)
        self.assertEqual(calculate_structural_recovery(advanced).plan["future_plan"]["solver"]["compiler"],
                         "native-work-method-time-lb1-seeded/0")
        round_trip = cycle_from_document(cycle_to_document(advanced))
        with patch.object(cp_model.CpSolver, "solve", side_effect=AssertionError("no solve")):
            validate_cycle(round_trip)
        self.assertEqual(cycle_to_document(round_trip), cycle_to_document(advanced))
        with TemporaryDirectory() as folder:
            path = Path(folder) / "s2-cycle.json"
            save_cycle(advanced, path)
            with patch.object(cp_model.CpSolver, "solve", side_effect=AssertionError("no solve")):
                reopened = load_cycle(path)
                validate_cycle(reopened)
            self.assertEqual(cycle_to_document(reopened), cycle_to_document(advanced))


if __name__ == "__main__":
    unittest.main()
