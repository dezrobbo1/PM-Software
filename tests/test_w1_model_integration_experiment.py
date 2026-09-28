"""Original-rank W1 model falsification and isolated >64 diagnostic admission."""
from __future__ import annotations

import subprocess
import unittest
from unittest.mock import patch

from ortools.sat.python import cp_model

from deterministic_scheduling_core.professional_admission_architecture import BASE_HASHES
from deterministic_scheduling_core.w1_model_integration_experiment import (
    activity_ladder, professional_assembly, run_evidence,
)


class W1ModelIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        cls.result = run_evidence(sha)
        cls.facts = cls.result["exact_semantic_facts"]

    def test_anchor_shadow_compact_and_original_ranks(self):
        anchor = self.facts["anchor"]
        self.assertEqual(anchor["production_hash"], BASE_HASHES["64_48"])
        self.assertEqual((anchor["u0"], anchor["u1"], anchor["disabled"]), (5626, 4284, 1342))
        self.assertEqual(anchor["p0"]["objective"], [19, 14674])
        self.assertEqual(anchor["p0"]["objective"], anchor["e0"]["objective"])
        self.assertEqual(anchor["p0"]["objective"], anchor["e1"]["objective"])
        self.assertEqual(anchor["p0"]["canonical_vector"], anchor["e0"]["canonical_vector"])
        self.assertEqual(anchor["p0"]["canonical_vector"], anchor["e1"]["canonical_vector"])
        self.assertEqual(anchor["p0"]["canonical_blocks"], anchor["e1"]["canonical_blocks"])
        self.assertEqual(anchor["original_rank_mapping"]["selected_p0"],
                         anchor["original_rank_mapping"]["selected_e1"])
        self.assertTrue(anchor["original_rank_mapping"]["all_u0_rows_match"])
        self.assertTrue(anchor["original_rank_mapping"]["all_u1_rows_match"])
        self.assertTrue(anchor["semantic_equal"] and anchor["physical_equal"])
        self.assertEqual(anchor["e0"]["base"]["variables"], anchor["p0"]["base"]["variables"])
        self.assertEqual(anchor["e0"]["base"]["constraints"],
                         anchor["p0"]["base"]["constraints"] + anchor["disabled"])
        for field in ("variables", "constraints", "serialized_bytes"):
            self.assertLess(anchor["e1"]["base"][field], anchor["p0"]["base"][field])
        self.assertTrue(anchor["e1"]["pr51_estimate_reconciliation"]["exact_reconciliation"])

    def test_admitted_controls_and_fixed_oracle_scope(self):
        for label, case in self.facts["controls"].items():
            with self.subTest(label=label):
                self.assertTrue(case["semantic_equal"] and case["canonical_equal"])
                self.assertEqual(case["p0"]["canonical_vector"], case["e1"]["canonical_vector"])
                self.assertTrue(case["source_unchanged"])
        self.assertEqual(self.facts["controls"]["small"]["production_hash"], BASE_HASHES["small_named"])
        self.assertEqual(self.facts["controls"]["professional"]["production_hash"], BASE_HASHES["professional"])
        fixed = self.facts["fixed_network_prefix"]
        self.assertEqual(fixed["fixed_networks"], 64)
        self.assertEqual(fixed["objective"], [19, 14674])
        self.assertFalse(fixed["placement_canonical_checked"])
        self.assertTrue(all(fixed[k] for k in ("selected_methods_equal", "selected_modes_equal",
                                             "finish_equal", "global_timing_equal")))

    def test_experimental_activity_ladder_and_public_rejection(self):
        rows = self.facts["activity_admission_ladder"]
        self.assertEqual([r["declared"] for r in rows], [65, 96, 128, 160])
        for row in rows:
            self.assertIsNone(row["production_rejection"])
            self.assertEqual(row["actual_objective"][0], row["declared"])
            self.assertEqual(row["actual_objective"][1],
                             sum((i + 1) * i for i in range(row["declared"])))
            self.assertTrue(row["all_original_placement_ranks_one"])

    def test_professional_160_120_assembly_never_calls_solver(self):
        # Assembly and canonical witness construction are safe with no solver API.
        with patch.object(cp_model.CpSolver, "solve", side_effect=AssertionError("160/120 must not solve")):
            result = professional_assembly()
        self.assertFalse(result["solve_invoked"])
        self.assertEqual((result["declared"], result["active_per_structure"],
                          result["authorised_structures"]), (160, 120, 16))
        self.assertEqual((result["u0_raw"], result["u0_eligible"],
                          result["retained_placements"]), (64068, 64032, 7812))
        self.assertEqual((result["resource_optional_intervals"], result["workface_optional_intervals"]),
                         (6705, 409))
        self.assertEqual((result["canonical_digits"], result["canonical_blocks"]), (332, 26))
        self.assertEqual((result["pre_canonical"]["variables"], result["pre_canonical"]["constraints"]),
                         (8308, 7952))
        self.assertEqual((result["post_witness"]["variables"], result["post_witness"]["constraints"]),
                         (8640, 8284))
        self.assertEqual(result["pr51_reconciliation"]["actual_package_root_arcs"], 15)
        self.assertTrue(result["pr51_reconciliation"]["exact_reconciliation"])
        self.assertIsNone(result["production_rejection"])

    def test_result_and_experiment_are_isolated(self):
        self.assertEqual(self.result["source_sha"], subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True).strip())
        self.assertEqual(self.facts["classification"], "A_W1_MODEL_INTEGRATION_PROVEN")
        self.assertEqual(self.facts["first_exact_professional_160_120_solve_experiment"], "READY")
        self.assertTrue(self.result["no_professional_solve"])
        import deterministic_scheduling_core.scheduling.work_method_time as production
        self.assertNotIn("w1_model_integration_experiment", production.__dict__)


if __name__ == "__main__":
    unittest.main()
