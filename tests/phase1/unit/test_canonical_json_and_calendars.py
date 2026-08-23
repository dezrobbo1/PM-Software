from __future__ import annotations

import unittest

from deterministic_scheduling_core.calendars.arithmetic import (
    consume_duration,
    earliest_span,
    intersect_intervals,
    shift_working_time,
)
from deterministic_scheduling_core.provenance.canonical_json import (
    canonical_text,
    sha256_digest,
)


class CanonicalJsonTests(unittest.TestCase):
    def test_keys_and_whitespace_are_canonical(self) -> None:
        self.assertEqual('{"a":1,"b":2}', canonical_text({"b": 2, "a": 1}))

    def test_unicode_is_nfc_normalised(self) -> None:
        self.assertEqual(sha256_digest({"name": "e\u0301"}), sha256_digest({"name": "é"}))

    def test_array_order_remains_semantic(self) -> None:
        self.assertNotEqual(sha256_digest(["A", "B"]), sha256_digest(["B", "A"]))

    def test_float_is_rejected(self) -> None:
        with self.assertRaises(TypeError):
            canonical_text({"time": 1.5})

    def test_nfc_equivalent_object_keys_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            canonical_text({"e\u0301": 1, "é": 2})


class CalendarArithmeticTests(unittest.TestCase):
    intervals = ((0, 4), (5, 9), (24, 28))

    def test_duration_crosses_nonworking_gap(self) -> None:
        self.assertEqual(7, consume_duration(0, 6, self.intervals))

    def test_explicit_nonworking_start_does_not_snap(self) -> None:
        self.assertIsNone(consume_duration(4, 1, self.intervals))

    def test_signed_lag_uses_productive_units(self) -> None:
        self.assertEqual(7, shift_working_time(4, 2, self.intervals))
        self.assertEqual(2, shift_working_time(5, -2, self.intervals))

    def test_earliest_span_honours_finish_bound(self) -> None:
        self.assertEqual((3, 7), earliest_span(0, 7, 3, self.intervals, 28))

    def test_interval_intersection_is_half_open(self) -> None:
        self.assertEqual(((2, 4), (5, 6)), intersect_intervals(((0, 4), (5, 9)), ((2, 6),)))
