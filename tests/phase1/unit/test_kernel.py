from __future__ import annotations

import copy
import unittest
from pathlib import Path

from deterministic_scheduling_core.canonical import CanonicalLoader
from deterministic_scheduling_core.cpm import ReferenceCPMKernel
from deterministic_scheduling_core.errors import UnsupportedSemanticError


ROOT = Path(__file__).resolve().parents[3]


class ReferenceKernelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = CanonicalLoader(ROOT).discover_frozen_suite()
        cls.by_id = {case.case_id: case for case in cls.cases}
        cls.kernel = ReferenceCPMKernel()

    def calculate(self, case_id: str, schedule=None):
        case = self.by_id[case_id]
        return self.kernel.calculate(
            schedule or case.schedule,
            case_id=case_id,
            category=case.document["category"],
        )

    def test_all_49_declared_oracles_calculate_exactly(self) -> None:
        for case in self.cases:
            if case.expected["reference_status"] != "declared":
                continue
            with self.subTest(case=case.case_id):
                result = self.calculate(case.case_id)
                self.assertEqual(case.expected["activity_times"], result["activity_times"])
                self.assertEqual(case.expected["project_finish"], result["project_finish"])
                self.assertEqual(case.expected["resource_order"], result["resource_order"])

    def test_expected_values_are_not_kernel_inputs(self) -> None:
        case = self.by_id["SEM-REL-001"]
        before = self.calculate(case.case_id)
        mutated_document = copy.deepcopy(case.document)
        mutated_document["expected"]["activity_times"]["B"]["finish"] = 399
        after = self.kernel.calculate(
            mutated_document["schedule"], case_id=case.case_id, category=case.document["category"]
        )
        self.assertEqual(before, after)

    def test_all_relationship_types_and_signed_lag_execute(self) -> None:
        for number in range(1, 13):
            case_id = f"SEM-REL-{number:03d}"
            with self.subTest(case=case_id):
                self.assertEqual(self.by_id[case_id].expected["activity_times"], self.calculate(case_id)["activity_times"])

    def test_resource_order_uses_canonical_id_tie_break(self) -> None:
        self.assertEqual(["A", "B"], self.calculate("SEM-DET-049")["resource_order"])

    def test_milestone_priority_precedes_id_tie_break(self) -> None:
        self.assertEqual(["B", "A"], self.calculate("SEM-DET-050")["resource_order"])

    def test_explicit_lag_calendar_fails_closed(self) -> None:
        schedule = copy.deepcopy(self.by_id["SEM-REL-001"].schedule)
        schedule["relationships"][0]["lag_calendar"] = "CAL-24X7"
        with self.assertRaises(UnsupportedSemanticError) as caught:
            self.calculate("SEM-REL-001", schedule)
        self.assertEqual("explicit-lag-calendar", caught.exception.code)

    def test_cumulative_capacity_fails_closed(self) -> None:
        schedule = copy.deepcopy(self.by_id["SEM-DET-049"].schedule)
        schedule["resources"][0].update({"type": "cumulative", "capacity": 2})
        with self.assertRaises(UnsupportedSemanticError) as caught:
            self.calculate("SEM-DET-049", schedule)
        self.assertEqual("cumulative-capacity", caught.exception.code)

    def test_fixed_dates_fail_closed(self) -> None:
        schedule = copy.deepcopy(self.by_id["SEM-REL-001"].schedule)
        schedule["activities"][0]["constraints"].append(
            {"id": "FIXED", "type": "fixed_start", "value": 0}
        )
        with self.assertRaises(UnsupportedSemanticError) as caught:
            self.calculate("SEM-REL-001", schedule)
        self.assertEqual("fixed-date-constraint", caught.exception.code)

    def test_actual_dates_is_native_validation_only(self) -> None:
        with self.assertRaises(UnsupportedSemanticError) as caught:
            self.calculate("SEM-STA-045")
        self.assertEqual("actual-dates-native-only", caught.exception.code)

    def test_execution_modes_fail_closed(self) -> None:
        schedule = copy.deepcopy(self.by_id["SEM-REL-001"].schedule)
        schedule["activities"][0]["eligible_modes"] = [
            {"id": "M1", "duration": 4, "calendar_id": None, "assignments": []}
        ]
        with self.assertRaises(UnsupportedSemanticError) as caught:
            self.calculate("SEM-REL-001", schedule)
        self.assertEqual("execution-modes", caught.exception.code)
