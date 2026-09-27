"""Exact, bounded proof-boundary diagnostics outside the production scheduler."""
import subprocess
import unittest
from pathlib import Path

from deterministic_scheduling_core.block000_boundary_experiment import run_evidence
from deterministic_scheduling_core.post_finish_proof_experiment import BASE_HASHES


class BlockBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        cls.evidence = run_evidence(sha)

    def test_exact_policy_and_production_identity(self):
        p = self.evidence["primary"]
        self.assertEqual(p["production_hash"], BASE_HASHES["64_48"])
        self.assertEqual((p["F"], p["G"]), (19, 14674))
        self.assertEqual(p["placements"], 5626)
        self.assertEqual(p["target_name"], "canonical_block:000")
        self.assertEqual(p["target_index"], 0)
        self.assertEqual((p["method_numerics"]["digit_count"], p["mode_numerics"]["digit_count"]), (8, 54))
        original = [(v["name"], v["value"]) for v in p["production"]["canonical_vector"]]
        for name, calls in (("p1", 2), ("p2", 62)):
            row = p[name]
            self.assertTrue(row["semantic_equal"])
            self.assertTrue(row["canonical_equal"])
            self.assertEqual(row["physical_status"], "PROVEN_FEASIBLE")
            self.assertEqual(row["target_calls"], calls)
            self.assertEqual([(v["name"], v["value"]) for v in row["canonical_vector"]], original)
            self.assertEqual(row["model_builds"], 1)
            self.assertEqual(row["solver_calls"], row["finish_query_calls"] + row["global_timing_calls"] + row["target_calls"] + row["other_canonical_calls"])

    def test_three_exact_anatomies_and_numerical_safety(self):
        p = self.evidence["primary"]
        for label, value in (("p0_anatomy", p["target_value"]),
                             ("method_anatomy", p["p1"]["target_stage_metrics"][0]["value"]),
                             ("mode_anatomy", p["p1"]["target_stage_metrics"][1]["value"])):
            row = p[label]
            self.assertTrue(row["context"]["objective_absent"])
            self.assertEqual(row["optimization"]["value"], value)
            self.assertEqual(row["at_value"]["status"], "SAT")
            self.assertEqual(row["one_better"]["status"], "INFEASIBLE")
            self.assertEqual(row["at_value"]["bound"], value)
            self.assertEqual(row["one_better"]["bound"], value - 1)
            self.assertEqual(row["optimization"]["variables"], row["context"]["variables"])
            self.assertEqual(row["one_better"]["constraints"], row["context"]["constraints"] + 1)
        self.assertEqual(p["p0_anatomy"]["context"], p["method_anatomy"]["context"])
        self.assertEqual(p["mode_anatomy"]["context"]["constraints"], p["method_anatomy"]["context"]["constraints"] + 1)
        self.assertEqual([d["name"] for d in p["target_numerics"]["digits"]],
                         [d["name"] for d in p["method_numerics"]["digits"] + p["mode_numerics"]["digits"]])
        for name in ("target", "method", "mode"):
            n = p[name + "_numerics"]
            self.assertLessEqual(n["maximum"], n["safety_bound"])
            self.assertEqual(n["coefficient_ratio"], n["largest_coefficient"] // n["smallest_nonzero_coefficient"])

    def test_repeated_solver_call_floor(self):
        p = self.evidence["primary"]
        self.assertEqual(set(p["floor"]), {"context_sat", "target_value_fixed", "target_digits_fixed"})
        for floor in p["floor"].values():
            self.assertEqual(len(floor["repetitions"]), 3)
            self.assertTrue(all(r["status"] == "SAT" for r in floor["repetitions"]))
            self.assertLessEqual(floor["wall_min_ms"], floor["wall_median_ms"])
            self.assertLessEqual(floor["wall_median_ms"], floor["wall_max_ms"])

    def test_controls_and_admission(self):
        e = self.evidence
        self.assertEqual(e["controls"]["small_named"]["plan_hash"], BASE_HASHES["small_named"])
        self.assertEqual(e["controls"]["professional"]["plan_hash"], BASE_HASHES["professional"])
        self.assertFalse(e["controls"]["small_named"]["split_applicable"])
        self.assertFalse(e["controls"]["anonymous_group"]["split_applicable"])
        self.assertEqual([x["activities"] for x in e["activity_ladder"]], [8, 16, 32, 48, 64])
        self.assertEqual([x["placements"] for x in e["density_ladder"]], [129, 513, 1537, 3841])
        classifier = e["professional_classifier"]
        self.assertEqual(classifier["authoritative_first_failure"]["class"], "ADMISSION_BOUND")
        self.assertEqual(classifier["diagnostic_faithful_projection"]["raw_generated_placements"], 64068)
        self.assertEqual(classifier["diagnostic_faithful_projection"]["placement_alternatives"], 64032)

    def test_no_production_dependency(self):
        directory = Path(__file__).resolve().parents[1] / "src/deterministic_scheduling_core/scheduling"
        self.assertFalse(any("block000_boundary_experiment" in p.read_text() for p in directory.glob("*.py")))


if __name__ == "__main__":
    unittest.main()
