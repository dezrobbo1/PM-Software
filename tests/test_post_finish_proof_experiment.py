"""Exact, production-independent post-finish proof controls."""
import subprocess
import unittest
from pathlib import Path

from deterministic_scheduling_core.post_finish_proof_experiment import BASE_HASHES, run_evidence
from deterministic_scheduling_core.converged_scale_experiment import build_problem as scale_problem
from deterministic_scheduling_core.scheduling.work_method_time import schedule_work_method_time


class PostFinishProofTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        cls.evidence = run_evidence(sha)

    def test_production_identity_and_independent_control(self):
        e = self.evidence
        self.assertEqual(e["baseline_hashes_verified"], BASE_HASHES)
        self.assertEqual(e["primary"]["plan_hash"], BASE_HASHES["64_48"])
        self.assertEqual(e["primary"]["objective"][0], 19)
        self.assertEqual(e["primary"]["shape"]["placement_alternatives"], 5626)
        self.assertEqual(e["independent_fixed_network"]["objective"][0], e["controls"][0]["objective"][0])

    def test_all_stage_optima_and_better_infeasibility(self):
        for row in [self.evidence["primary"], *self.evidence["controls"]]:
            stages = [(row["global_anatomy"], row["objective"][1])]
            stages.extend((a, b["value"]) for a, b in zip(row["block_anatomy"], row["blocks"]))
            for anatomy, optimum in stages:
                self.assertTrue(anatomy["context"]["objective_absent"])
                self.assertEqual(anatomy["optimization"]["value"], optimum)
                self.assertEqual(anatomy["at_value"]["status"], "SAT")
                self.assertEqual(anatomy["one_better"]["status"], "INFEASIBLE")
                self.assertEqual(anatomy["at_value"]["bound"], optimum)
                self.assertEqual(anatomy["one_better"]["bound"], optimum - 1)
                self.assertEqual(anatomy["optimization"]["variables"], anatomy["at_value"]["variables"])
                self.assertEqual(anatomy["optimization"]["constraints"], anatomy["context"]["constraints"])
                self.assertEqual(anatomy["at_value"]["constraints"], anatomy["context"]["constraints"] + 1)
                self.assertEqual(anatomy["one_better"]["constraints"], anatomy["context"]["constraints"] + 1)
            self.assertTrue(row["fresh_vs_sequence"]["global_value_equal"])
            self.assertTrue(row["fresh_vs_sequence"]["block_values_equal"])

    def test_block_inventory_covers_exact_canonical_vector(self):
        for row in [self.evidence["primary"], *self.evidence["controls"],
                    *self.evidence["activity_ladder"], *self.evidence["density_ladder"]]:
            self.assertEqual([d["name"] for b in row["blocks"] for d in b["digits"]],
                             [d["name"] for d in row["canonical_vector"]])
            self.assertEqual(sum(b["production_cost"]["deterministic_time"] for b in row["blocks"]),
                             row["post_finish_deterministic"]["canonical"])
            self.assertEqual(row["physical_status"], "PROVEN_FEASIBLE")
            self.assertEqual(row["shape"]["placement_alternatives"] > 0, True)
            self.assertGreaterEqual(row["pipeline_wall"]["residual_ms"], -0.01)
            self.assertAlmostEqual(sum(row["pipeline_wall"]["non_overlapping_ms"].values())
                                   + row["pipeline_wall"]["residual_ms"],
                                   row["pipeline_wall"]["end_to_end_ms"])

    def test_fixture_ladders_and_professional_admission(self):
        e = self.evidence
        self.assertEqual([r["name"] for r in e["activity_ladder"]],
                         [f"activity_{n}" for n in (8, 16, 32, 48, 64)])
        self.assertEqual([r["shape"]["placement_alternatives"] for r in e["density_ladder"]],
                         [129, 513, 1537, 3841])
        classifier = e["professional_classifier"]
        self.assertEqual(classifier["authoritative_first_failure"]["class"], "ADMISSION_BOUND")
        self.assertEqual(classifier["diagnostic_faithful_projection"]["raw_generated_placements"], 64068)
        self.assertEqual(classifier["diagnostic_faithful_projection"]["placement_alternatives"], 64032)

    def test_authority_repeatable_and_experiment_not_imported(self):
        first = schedule_work_method_time(scale_problem()).plan
        second = schedule_work_method_time(scale_problem()).plan
        self.assertEqual(first, second)
        self.assertEqual(first["plan_hash"], BASE_HASHES["64_48"])
        directory = Path(__file__).resolve().parents[1] / "src/deterministic_scheduling_core/scheduling"
        self.assertFalse(any("post_finish_proof_experiment" in source.read_text()
                             for source in directory.glob("*.py")))


if __name__ == "__main__":
    unittest.main()
