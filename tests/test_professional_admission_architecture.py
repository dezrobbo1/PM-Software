"""Exact no-solve domain and pruning controls for professional 160/120."""
import subprocess
import unittest
from unittest.mock import patch
from pathlib import Path

from deterministic_scheduling_core.professional_admission_architecture import (
    BASE_HASHES, _identity_digest, domains, inspect, run_evidence,
    tiny_oracle, tiny_problem,
)
from deterministic_scheduling_core.professional_scale_challenge import (
    build_professional_projection, CURRENT_ACTIVITY_LIMIT, CURRENT_PLACEMENT_LIMIT,
)
from deterministic_scheduling_core.scheduling.work_method_time import (
    MAX_WORKFACE_INTERVALS, validate_problem,
)


class ProfessionalArchitectureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.problem = build_professional_projection()
        cls.sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        cls.evidence = run_evidence(cls.sha)

    def test_production_identity_and_admission(self):
        e = self.evidence
        self.assertEqual(e["production_hashes"], BASE_HASHES)
        self.assertEqual(e["professional_shape"]["declared_activities"], 160)
        self.assertEqual(e["professional_shape"]["selected_active_activities"], 120)
        self.assertEqual(e["professional_shape"]["authorised_structures"], 16)
        self.assertEqual(len(self.problem.work_packages), 12)
        self.assertEqual(sum(len(p.methods) > 1 for p in self.problem.work_packages), 4)
        project = self.problem.project
        self.assertEqual({r["id"] for r in project["resources"]}, {"C04"})
        self.assertEqual({g["id"] for g in project["resource_groups"]},
                         {"MECH_POOL", "ELEC_POOL", "QA_POOL"})
        self.assertTrue(any(a.get("exclusion_groups") for a in project["activities"]))
        self.assertTrue(any("latest_finish" in a for a in project["activities"]))
        self.assertEqual(e["professional_classifier"]["class"], "ADMISSION_BOUND")
        self.assertEqual((CURRENT_ACTIVITY_LIMIT, CURRENT_PLACEMENT_LIMIT, MAX_WORKFACE_INTERVALS),
                         (64, 20000, 20000))
        with self.assertRaisesRegex(ValueError, "1..64 declared activities"):
            validate_problem(self.problem)
        self.assertTrue(e["no_professional_solve"])

    def test_union_and_per_mode_reconcile(self):
        p = self.evidence["primary"]
        self.assertEqual((p["u0"]["raw_placements"], p["u0"]["flattened"]), (64068, 64032))
        self.assertEqual(sum(row["raw"] for row in p["mode_anatomy"]), 64068)
        self.assertEqual(sum(row["eligible"] for row in p["mode_anatomy"]), 64032)
        self.assertEqual(sum(row["anonymous_witness_expansion"] for row in p["mode_anatomy"]),
                         p["u0"]["anonymous_witness_expansion"])
        self.assertEqual(p["u0"]["flattened"] - p["u0"]["temporal_named_patterns"],
                         p["u0"]["anonymous_witness_expansion"])
        self.assertEqual(p["u1"]["flattened"] - p["u1"]["temporal_named_patterns"],
                         p["u1"]["anonymous_witness_expansion"])
        self.assertTrue(all(row["temporal"] <= row["temporal_named"] <= row["eligible"]
                            for row in p["mode_anatomy"]))

    def test_structure_ownership_and_selected_domains(self):
        p = self.evidence["primary"]
        self.assertEqual(len(p["structures"]), 16)
        self.assertEqual(len({tuple(sorted(s["methods"].items())) for s in p["structures"]}), 16)
        self.assertEqual([s["s0"]["flattened"] for s in p["structures"]], p["s0_counts"])
        self.assertEqual([s["s1"]["flattened"] for s in p["structures"]], p["s1_counts"])
        self.assertTrue(all(s["active_activities"] == 120 for s in p["structures"]))
        ownership = p["ownership_totals"]
        self.assertEqual(ownership["always_potentially_active"] + ownership["optional_structural"],
                         p["u0"]["flattened"])
        self.assertEqual(sum(ownership[key] for key in (
            "fixed_single_method_package", "alternative_method_package", "outside_package")),
            p["u0"]["flattened"])
        self.assertTrue(all(row["structures"] in (8, 16) for row in p["ownership"].values()))
        self.assertEqual(p["s0_distribution"]["min"], min(p["s0_counts"]))
        self.assertEqual(p["s1_distribution"]["max"], max(p["s1_counts"]))
        self.assertTrue(all(s["removed"] == s["s0"]["flattened"] - s["s1"]["flattened"]
                            for s in p["structures"]))

    def test_original_ranks_union_exactness(self):
        p = self.evidence["primary"]
        indexed, _ = domains(self.problem)
        all_u1 = p["u1"]["retained_original_ranks"]
        exact_union = {aid: set() for aid in indexed}
        for structure in p["structures"]:
            for aid, ranks in structure["s1"]["retained_original_ranks"].items():
                self.assertEqual(ranks, sorted(set(ranks)))
                self.assertTrue(all(1 <= rank <= len(indexed[aid]) for rank in ranks))
                exact_union[aid].update(ranks)
        self.assertEqual(all_u1, {aid: sorted(ranks) for aid, ranks in exact_union.items()})
        self.assertEqual(p["u1"]["original_row_identity_digest"],
                         _identity_digest(indexed, {aid: set(ranks) for aid, ranks in all_u1.items()}))
        self.assertEqual(sum(len(ranks) for ranks in all_u1.values()), p["u1"]["flattened"])

    def test_interval_and_canonical_pressure(self):
        for domain in [self.evidence["primary"]["u0"], self.evidence["primary"]["u1"]]:
            pressure = domain["model_pressure"]
            resources = sum(domain["named_resource_intervals"].values()) + sum(
                domain["group_resource_intervals"].values())
            faces = sum(domain["workface_intervals_by_group"].values())
            self.assertEqual((resources, faces),
                             (pressure["resource_optional_intervals_exact"],
                              pressure["workface_optional_intervals_exact"]))
            self.assertEqual(pressure["interval_constraints_exact"], resources + faces)
            self.assertEqual(pressure["placement_boolvars"], domain["flattened"])
            self.assertEqual(pressure["canonical_digit_count"], 332)
            self.assertEqual(pressure["measurement_kind"], "mechanically_derived_no_proto")
        self.assertEqual(self.evidence["primary"]["u0"]["model_pressure"]["canonical_block_count"],
                         self.evidence["primary"]["u1"]["model_pressure"]["canonical_block_count"])

    def test_independent_tiny_oracle_and_existing_controls(self):
        tiny = tiny_problem()
        indexed, _ = domains(tiny)
        oracle = tiny_oracle(tiny, indexed)
        self.assertEqual(len(oracle), 2)
        self.assertEqual([x["complete_precedence_schedules"] for x in oracle], [7, 4])
        for label in ("small_named", "professional", "64_48", "anonymous_group"):
            self.assertTrue(self.evidence["controls"][label]["selected_ranks_survive"])
            self.assertGreaterEqual(self.evidence["controls"][label]["u0"],
                                    self.evidence["controls"][label]["u1"])
        self.assertTrue(self.evidence["independent_64_48"]["full_policy_equal"])
        self.assertEqual(self.evidence["independent_64_48"]["fixed_networks"], 64)

    def test_no_professional_solve_or_production_import(self):
        # The 160/120 path executes domain/pruning only, even if solver API is disabled.
        with patch("deterministic_scheduling_core.professional_admission_architecture.schedule_work_method_time",
                   side_effect=AssertionError("professional scheduling called")):
            domain = inspect(self.problem)
        self.assertEqual(domain["u0"]["flattened"], 64032)
        directory = Path(__file__).resolve().parents[1] / "src/deterministic_scheduling_core/scheduling"
        self.assertFalse(any("professional_admission_architecture" in f.read_text()
                             for f in directory.glob("*.py")))

    def test_exact_result_classification_and_source(self):
        e = self.evidence
        self.assertEqual(e["source_sha"], self.sha)
        self.assertTrue(e["primary"]["source_unchanged"])
        self.assertEqual(e["classification"], "A_UNION_PRUNING")
        self.assertEqual(e["first_exact_160_120_solve"], "READY")
        self.assertLessEqual(e["primary"]["u1"]["flattened"], CURRENT_PLACEMENT_LIMIT)


if __name__ == "__main__":
    unittest.main()
