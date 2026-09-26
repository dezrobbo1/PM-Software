"""Exact R0 objective formulation and LB-seeded finish search controls."""
import inspect
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from ortools.sat.python import cp_model

from deterministic_scheduling_core import finish_objective_search_experiment as experiment
from deterministic_scheduling_core.converged_scale_experiment import build_problem as scale_problem
from deterministic_scheduling_core.finish_proof_experiment import BASE_HASHES
from deterministic_scheduling_core.native_work_method_time import build_problem as small_problem
from deterministic_scheduling_core.project.work_method_time import input_hash
from deterministic_scheduling_core.scheduling import work_method_time


class FinishObjectiveSearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Run the costly controlled matrix once and bind optional evidence to HEAD."""
        cls.result = experiment.run_experiment(source_sha=os.getenv("SOURCE_HEAD_SHA"))
        expected = os.getenv("SOURCE_HEAD_SHA")
        if expected:
            actual = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
            if expected != actual or cls.result["source_sha"] != actual:
                raise AssertionError("evidence does not match checked-out HEAD")
        output = os.getenv("FINISH_OBJECTIVE_EVIDENCE_OUTPUT")
        if output:
            target = Path(output)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(cls.result, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def test_production_identity_independent_control_and_base(self):
        """Guard the frozen hashes, independent F and objective-free base."""
        r = self.result
        self.assertEqual(r["production_hashes"], BASE_HASHES)
        self.assertEqual((r["small_named"]["production_hash"], r["professional"]["production_hash"],
                          r["anchor"]["production_hash"]),
                         (BASE_HASHES["small"], BASE_HASHES["professional"], BASE_HASHES["scale_64_48"]))
        self.assertTrue(r["independent_control"])
        a = r["anchor"]
        self.assertEqual(a["finish"], 19)
        self.assertEqual([a["base"][n] for n in
                          ("declared_activities", "authorised_structures", "placement_alternatives",
                           "base_variables", "base_constraints", "workface_intervals")],
                         [64, 16, 5626, 5832, 3860, 0])
        self.assertEqual(a["base"]["source_input_hash"], input_hash(scale_problem()))
        self.assertEqual(a["base"]["objective_end_domain"], [0, 64])
        self.assertEqual(len(a["base"]["proto_text_sha256"]), 64)

    def test_algebraic_equality_for_every_feasible_small_assignment(self):
        """Search for an impossible end-versus-expression counterexample."""
        compiled = work_method_time._compile_work_method_time(small_problem())
        end = compiled.stages[0].expression
        expr = experiment._direct_expression(compiled)
        # Compiler establishes end == sum(finish*literal), independent of objective.
        # A counterexample on the complete base model must therefore be impossible.
        compiled.model.add(end != expr)
        self.assertEqual(work_method_time._new_solver().solve(compiled.model), cp_model.INFEASIBLE)

    def test_complete_matrix_matches_every_policy_digit_and_physical_witness(self):
        """Compare all complete policy and physical projections across cells."""
        for name in ("anchor", "small_named", "professional", "anonymous_group", "suspended_workface"):
            row = self.result[name]
            with self.subTest(name=name):
                self.assertEqual(set(row["cells"]), {
                    "C1_end/S0", "C2_direct/S0", "C1_end/S2-LB1", "C1_end/S2-LB2",
                    "C1_end/S2-LB3", "C2_direct/S2-LB1"})
                self.assertTrue(row["source_unchanged"] and row["semantic_equal"] and
                                row["canonical_equal"] and row["physical_equal"])
                reference = row["cells"]["C1_end/S0"]
                for key, cell in row["cells"].items():
                    with self.subTest(cell=key):
                        self.assertEqual(cell["base"], row["base"])
                        self.assertEqual(cell["finish"], row["finish"])
                        self.assertEqual(cell["semantic_plan"], reference["semantic_plan"])
                        self.assertEqual(cell["canonical_vector"], reference["canonical_vector"])
                        self.assertEqual(cell["physical_status"], reference["physical_status"])
                        self.assertIn("allocation_witness", cell["semantic_plan"])
                        self.assertEqual(cell["physical_status"], "PROVEN_FEASIBLE")
                        if "/S0" in key:
                            self.assertEqual(cell["finish_proof"]["status"], "OPTIMAL")
                            self.assertEqual(cell["finish_proof"]["objective_value"], row["finish"])
                            self.assertEqual(cell["added_constraints_before_finish"], 0)
                            self.assertEqual(cell["solver_calls"], 1 + len(cell["policy_proofs"]))
                        else:
                            bound = cell["bound"]["value"]
                            self.assertLessEqual(bound, row["finish"])
                            search = cell["search"]
                            self.assertEqual(search["exact_finish"], row["finish"])
                            self.assertEqual(search["trace"][0]["bound"], bound)
                            self.assertEqual(search["lower_bound_hit"], bound == row["finish"])
                            self.assertEqual(cell["solver_calls"], search["query_count"] +
                                             len(cell["policy_proofs"]))
                            self.assertTrue(all(q["satisfaction_status"] in
                                                ("OPTIMAL", "FEASIBLE", "INFEASIBLE")
                                                for q in search["trace"]))
                            self.assertTrue(all(q["bound_constraints"] == 1 for q in search["trace"]))
                        self.assertTrue(all(p["status"] == "OPTIMAL" for p in cell["policy_proofs"]))

    def test_nonexact_and_exact_bounds_query_traces(self):
        """Check both immediate bound hits and certified F-1 misses."""
        for name, expected in (("anchor", [19, 19, 19]), ("small_named", [27, 28, 28]),
                               ("professional", [4, 6, 6]), ("anonymous_group", [3, 3, 3])):
            row = self.result[name]
            self.assertEqual([row["cells"]["C1_end/S2-"+n]["bound"]["value"] for n in
                              ("LB1", "LB2", "LB3")], expected)
            for n in ("LB1", "LB2", "LB3"):
                trace = row["cells"]["C1_end/S2-"+n]["search"]["trace"]
                if expected[int(n[-1])-1] == row["finish"]:
                    self.assertEqual(len(trace), 1)
                    self.assertTrue(trace[0]["sat"])
                else:
                    self.assertFalse(trace[0]["sat"])
                    self.assertTrue(any(not q["sat"] for q in trace))
                    self.assertTrue(any(q["sat"] for q in trace))
                    self.assertTrue(any(q["bound"] == row["finish"] - 1 and not q["sat"]
                                        for q in trace))

    def test_supported_incumbent_and_bound_diagnostics_are_finish_only(self):
        """Ensure callback observations belong to the finish proof alone."""
        cell = self.result["anchor"]["cells"]["C1_end/S0"]
        self.assertEqual(cell["incumbents"][0]["objective"], 19)
        self.assertEqual(cell["finish_proof"]["best_objective_bound"], 19)
        self.assertTrue(all(e["solver_wall_ms"] <= cell["finish_proof"]["solver_wall_ms"]
                            for e in cell["incumbents"]))
        self.assertTrue(all(e["elapsed_wall_ms"] <= cell["finish_proof"]["wall_observation_ms"]
                            for e in cell["bound_events"]))
        self.assertIn("propagations:", cell["finish_proof"]["response_stats"])
        self.assertGreater(cell["finish_proof"]["binary_propagations"], 0)

    def test_controls_and_ladders(self):
        """Exercise professional constraints and retained size/density cases."""
        r = self.result
        self.assertEqual(r["small_named"]["finish"], 30)
        self.assertTrue(any(len(req["eligible_resource_ids"]) > 1
                            for activity in small_problem().project["activities"]
                            for mode in activity["modes"] for req in mode.get("requirements", [])))
        self.assertEqual((r["professional"]["finish"], r["anonymous_group"]["finish"]), (7, 5))
        self.assertNotIn("C_ALT", {e["activity_id"] for e in
                                   r["professional"]["cells"]["C1_end/S0"]["semantic_plan"]["entries"]})
        protected = {e["activity_id"]: e for e in
                     r["professional"]["cells"]["C1_end/S0"]["semantic_plan"]["entries"]}
        self.assertLessEqual(protected["B"]["finish"], 3)
        periods = {e["activity_id"]: e for e in
                   r["suspended_workface"]["cells"]["C1_end/S0"]["semantic_plan"]["entries"]}
        self.assertEqual(periods["A_FAST"]["periods"], [[0, 2], [4, 6]])
        self.assertGreaterEqual(periods["B"]["start"], periods["A_FAST"]["finish"])
        self.assertEqual([(n, r["activity_ladder"][str(n)]["finish"],
                           r["activity_ladder"][str(n)]["base"]["placement_alternatives"])
                          for n in (8, 16, 32, 48, 64)], [(n, n, n) for n in (8, 16, 32, 48, 64)])
        self.assertEqual([r["density_ladder"][str(h)]["base"]["placement_alternatives"]
                          for h in (16, 64, 192, 480)], [129, 513, 1537, 3841])
        for rows in (r["activity_ladder"], r["density_ladder"]):
            for row in rows.values():
                self.assertEqual(set(row["cells"]), {"C1_end/S0", "C1_end/S2-LB1"})
                self.assertEqual(row["cells"]["C1_end/S2-LB1"]["bound"]["value"], row["finish"])
                self.assertEqual(row["cells"]["C1_end/S2-LB1"]["search"]["query_count"], 1)
        historical = r["historical_S1_same_environment"]
        self.assertEqual(historical["exact_finish"], 19)
        self.assertTrue(historical["finish_feasible"] and historical["one_tick_better_infeasible"])

    def test_unknown_rejected_and_queries_do_not_leak(self):
        """Reject an unproved SAT answer and guard independent clone bounds."""
        problem = small_problem()
        compiled = work_method_time._compile_work_method_time(problem)
        base = experiment._base_identity(compiled)
        first = experiment._query(compiled, 27, base)
        second = experiment._query(compiled, 30, base)
        self.assertFalse(first["sat"])
        self.assertTrue(second["sat"])
        self.assertEqual(base, experiment._base_identity(compiled))
        self.assertEqual(len(compiled.model.proto.constraints), base["base_constraints"])
        class UnknownSolver:
            def solve(self, model):
                return cp_model.UNKNOWN
        with patch.object(experiment, "_new_solver", return_value=UnknownSolver()), \
             patch.object(experiment, "_response", return_value={"status": "UNKNOWN"}):
            with self.assertRaisesRegex(AssertionError, "unclosed SAT bound"):
                experiment._query(compiled, 27, base)

    def test_repeatability_on_nonexact_bound(self):
        """Repeat a nontrivial query trace without mutating source input."""
        problem = small_problem()
        before = input_hash(problem)
        base = experiment._base_identity(work_method_time._compile_work_method_time(problem))
        first = experiment._seeded(problem, "LB1", "C1_end", base)
        second = experiment._seeded(problem, "LB1", "C1_end", base)
        self.assertEqual(first["semantic_plan"], second["semantic_plan"])
        self.assertEqual(first["canonical_vector"], second["canonical_vector"])
        self.assertEqual([(q["bound"], q["sat"], q["feasible_finish"]) for q in first["search"]["trace"]],
                         [(q["bound"], q["sat"], q["feasible_finish"]) for q in second["search"]["trace"]])
        self.assertEqual(before, input_hash(problem))

    def test_classifier_production_isolation_and_input(self):
        """Keep the experiment out of production and 160/120 outside admission."""
        r = self.result
        p = r["professional_scale"]
        self.assertTrue(p["faithful_projection_valid"])
        self.assertEqual(p["authoritative_first_failure"]["class"], "ADMISSION_BOUND")
        self.assertEqual(tuple(p["diagnostic_faithful_projection"][n] for n in
                               ("raw_generated_placements", "placement_alternatives", "placement_limit")),
                         (64068, 64032, 20000))
        self.assertNotIn("finish_objective_search_experiment", inspect.getsource(work_method_time))
        measured = experiment._classify(r)
        self.assertEqual(r["classification"], measured)
        self.assertIn(measured["category"], "ABCDEF")
        self.assertIn("anchor_total_deterministic_saving", measured["basis"])
        source = scale_problem()
        before = input_hash(source)
        for bound in ("LB1", "LB2", "LB3"):
            experiment._derive(source, bound,
                               work_method_time._compile_work_method_time(source) if bound == "LB3" else None)
        self.assertEqual(input_hash(source), before)

    def test_adverse_measured_cost_cannot_claim_outcome_a(self):
        """Reject a favorable classification when measured costs turn adverse."""
        controls = deepcopy(self.result)
        cells = controls["anchor"]["cells"]
        cells["C1_end/S2-LB1"]["total_deterministic_time"] = (
            cells["C1_end/S0"]["total_deterministic_time"] + 1)
        self.assertNotEqual(experiment._classify(controls)["category"], "A")
        controls = deepcopy(self.result)
        cells = controls["anchor"]["cells"]
        cells["C1_end/S2-LB1"]["end_to_end_wall_ms"] = (
            cells["C1_end/S0"]["end_to_end_wall_ms"] + 1)
        self.assertNotEqual(experiment._classify(controls)["category"], "A")


if __name__ == "__main__":
    unittest.main()
