"""Tests for professional-shaped 160/120 converged-path barrier classification."""
from __future__ import annotations

import unittest

from deterministic_scheduling_core.professional_scale_challenge import (
    ACTIVE_ACTIVITIES,
    AUTHORISED_STRUCTURES,
    DECLARED_ACTIVITIES,
    FLEXIBLE_PACKAGES,
    WORK_PACKAGES,
    run_challenge,
)


class ProfessionalScaleChallengeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = run_challenge()

    def test_fixture_preserves_professional_shape(self):
        shape = self.result["shape"]
        self.assertEqual(shape["declared_activities"], DECLARED_ACTIVITIES)
        self.assertEqual(shape["selected_active_activities"], ACTIVE_ACTIVITIES)
        self.assertEqual(shape["work_packages"], WORK_PACKAGES)
        self.assertEqual(shape["flexible_packages"], FLEXIBLE_PACKAGES)
        self.assertEqual(shape["authorised_structures"], AUTHORISED_STRUCTURES)
        self.assertEqual(shape["unsupported_activity_fields"], [])

    def test_current_authoritative_path_fails_first_at_admission(self):
        failure = self.result["authoritative_first_failure"]
        self.assertIsNotNone(failure)
        self.assertEqual(failure["class"], "ADMISSION_BOUND")
        self.assertIn("1..64 declared activities", failure["message"])

    def test_faithful_selected_projection_accepts_both_semantics(self):
        failure = self.result["selected_projection_failure"]
        self.assertIsNone(failure)
        self.assertTrue(self.result["faithful_projection_valid"])

    def test_diagnostic_faithful_projection_reaches_next_scale_checks(self):
        diagnostic = self.result["diagnostic_faithful_projection"]
        self.assertTrue(diagnostic["projection_valid"])
        self.assertIsNone(diagnostic["projection_error"])
        self.assertIsInstance(diagnostic["placement_alternatives"], int)
        self.assertEqual(diagnostic["raw_generated_placements"], 64068)
        self.assertEqual(diagnostic["placement_alternatives"], 64032)
        self.assertGreater(
            diagnostic["placement_alternatives"],
            diagnostic["placement_limit"],
        )
        self.assertTrue(diagnostic["placement_limit_would_be_exceeded"])
        self.assertEqual(diagnostic["lexicographic_stage_count_if_admitted"], 334)

    def test_challenge_is_classification_only_and_immutable(self):
        self.assertTrue(self.result["portable_round_trip"])
        self.assertTrue(self.result["source_unchanged"])
        self.assertTrue(self.result["evidence_valid"])
        self.assertEqual(
            self.result["classification"]["first_authoritative_barrier"],
            "ADMISSION_BOUND",
        )
        self.assertEqual(
            self.result["classification"]["semantic_projection_barrier"],
            None,
        )


if __name__ == "__main__":
    unittest.main()
