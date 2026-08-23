from __future__ import annotations

import copy
import unittest
from pathlib import Path

from deterministic_scheduling_core.canonical import CanonicalLoader
from deterministic_scheduling_core.cpm import ReferenceCPMKernel
from deterministic_scheduling_core.validation import IndependentResultValidator


ROOT = Path(__file__).resolve().parents[3]


class IndependentValidatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cases = CanonicalLoader(ROOT).discover_frozen_suite()
        cls.by_id = {case.case_id: case for case in cases}
        cls.kernel = ReferenceCPMKernel()
        cls.validator = IndependentResultValidator()

    def output(self, case_id: str):
        case = self.by_id[case_id]
        return self.kernel.calculate(
            case.schedule, case_id=case_id, category=case.document["category"]
        )

    def assert_corruption_fails(self, case_id: str, mutate) -> tuple[str, ...]:
        result = copy.deepcopy(self.output(case_id))
        mutate(result)
        report = self.validator.validate(self.by_id[case_id], result)
        self.assertEqual("fail", report.status)
        return report.errors

    def test_valid_calculation_passes_without_calling_kernel(self) -> None:
        result = self.output("SEM-CAL-024")
        self.assertEqual("pass", self.validator.validate(self.by_id["SEM-CAL-024"], result).status)

    def test_corrupted_relationship_formula_fails(self) -> None:
        errors = self.assert_corruption_fails(
            "SEM-REL-005", lambda result: result["activity_times"]["B"].update(start=5, finish=8)
        )
        self.assertTrue(any("signed-lag lower bound" in error for error in errors))

    def test_corrupted_duration_span_fails(self) -> None:
        errors = self.assert_corruption_fails(
            "SEM-CAL-021", lambda result: result["activity_times"]["A"].update(finish=6)
        )
        self.assertTrue(any("productive-duration span" in error for error in errors))

    def test_missing_activity_fails_complete_coverage(self) -> None:
        errors = self.assert_corruption_fails(
            "SEM-NET-013", lambda result: result["activity_times"].pop("C")
        )
        self.assertTrue(any("coverage differs" in error for error in errors))

    def test_changed_actual_coordinate_fails(self) -> None:
        errors = self.assert_corruption_fails(
            "SEM-STA-039", lambda result: result["activity_times"]["A"].update(start=2)
        )
        self.assertTrue(any("actual coordinates changed" in error for error in errors))

    def test_resource_overlap_fails(self) -> None:
        def overlap(result):
            result["activity_times"]["B"].update(start=0, finish=4)

        errors = self.assert_corruption_fails("SEM-DET-049", overlap)
        self.assertTrue(any("over capacity" in error for error in errors))

    def test_float_corruption_fails(self) -> None:
        errors = self.assert_corruption_fails(
            "SEM-FLT-047", lambda result: result["activity_times"]["C"].update(total_float=4)
        )
        self.assertTrue(any("total_float is incorrect" in error for error in errors))

    def test_objective_vector_corruption_fails(self) -> None:
        errors = self.assert_corruption_fails(
            "SEM-DET-050", lambda result: result["selection_objective_vector"].append(99)
        )
        self.assertTrue(any("objective vector" in error for error in errors))
