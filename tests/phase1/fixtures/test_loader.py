from __future__ import annotations

import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from deterministic_scheduling_core.canonical import CanonicalLoader
from deterministic_scheduling_core.errors import CanonicalValidationError


ROOT = Path(__file__).resolve().parents[3]
CASE_PATH = ROOT / "benchmarks" / "semantic" / "cases" / "sem-rel-001.json"


class CanonicalLoaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.loader = CanonicalLoader(ROOT)
        cls.base = json.loads(CASE_PATH.read_text(encoding="utf-8"))

    def load_mutation(self, document: dict) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / CASE_PATH.name
            path.write_text(json.dumps(document), encoding="utf-8")
            self.loader.load_case(path)

    def test_exact_frozen_suite_loads_in_preregistered_order(self) -> None:
        cases = self.loader.discover_frozen_suite()
        self.assertEqual(50, len(cases))
        self.assertEqual("SEM-REL-001", cases[0].case_id)
        self.assertEqual("SEM-DET-050", cases[-1].case_id)

    def test_same_count_replacement_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cases_dir = Path(temporary) / "cases"
            shutil.copytree(ROOT / "benchmarks" / "semantic" / "cases", cases_dir)
            replacement = json.loads((cases_dir / "sem-rel-002.json").read_text())
            (cases_dir / "sem-rel-001.json").write_text(json.dumps(replacement), encoding="utf-8")
            with self.assertRaisesRegex(CanonicalValidationError, "expected frozen case_id"):
                self.loader.discover_frozen_suite(
                    cases_dir, ROOT / "benchmarks" / "semantic" / "catalogue.csv"
                )

    def test_duplicate_ids_are_rejected(self) -> None:
        data = copy.deepcopy(self.base)
        data["schedule"]["activities"].append(copy.deepcopy(data["schedule"]["activities"][0]))
        with self.assertRaisesRegex(CanonicalValidationError, "duplicate activity"):
            self.load_mutation(data)

    def test_unresolved_activity_calendar_is_rejected(self) -> None:
        data = copy.deepcopy(self.base)
        data["schedule"]["activities"][0]["calendar_id"] = "CAL-MISSING"
        with self.assertRaisesRegex(CanonicalValidationError, "unknown calendar"):
            self.load_mutation(data)

    def test_wbs_cycle_is_rejected(self) -> None:
        data = copy.deepcopy(self.base)
        data["schedule"]["wbs"] = [
            {"id": "W1", "name": "W1", "parent_id": "W2"},
            {"id": "W2", "name": "W2", "parent_id": "W1"},
        ]
        with self.assertRaisesRegex(CanonicalValidationError, "WBS hierarchy contains a cycle"):
            self.load_mutation(data)

    def test_supplied_approved_forecast_must_be_complete(self) -> None:
        data = copy.deepcopy(self.base)
        data["schedule"]["approved_forecast"] = {
            "state_id": "F1",
            "state_type": "approved_forecast",
            "activity_states": [{"activity_id": "A", "start": 0, "finish": 4}],
        }
        with self.assertRaisesRegex(CanonicalValidationError, "exactly cover all activities"):
            self.load_mutation(data)

    def test_invalid_saved_span_is_rejected(self) -> None:
        data = copy.deepcopy(self.base)
        data["schedule"]["approved_forecast"] = {
            "state_id": "F1",
            "state_type": "approved_forecast",
            "activity_states": [
                {"activity_id": "A", "start": 0, "finish": 3},
                {"activity_id": "B", "start": 4, "finish": 7},
            ],
        }
        with self.assertRaisesRegex(CanonicalValidationError, "selected duration"):
            self.load_mutation(data)

    def test_source_specific_fields_are_preserved(self) -> None:
        data = copy.deepcopy(self.base)
        data["schedule"]["activities"][0]["source_fields"] = {"vendor_code": "α"}
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / CASE_PATH.name
            path.write_text(json.dumps(data), encoding="utf-8")
            loaded = self.loader.load_case(path)
        activity = next(item for item in loaded.schedule["activities"] if item["id"] == "A")
        self.assertEqual({"vendor_code": "α"}, activity["source_fields"])

    def test_in_memory_entities_use_stable_id_order(self) -> None:
        data = copy.deepcopy(self.base)
        data["schedule"]["activities"].reverse()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / CASE_PATH.name
            path.write_text(json.dumps(data), encoding="utf-8")
            loaded = self.loader.load_case(path)
        self.assertEqual(["A", "B"], [item["id"] for item in loaded.schedule["activities"]])

    def test_known_alternate_lag_calendar_is_preserved_by_loader(self) -> None:
        data = copy.deepcopy(self.base)
        data["schedule"]["relationships"][0]["lag_calendar"] = "CAL-24X7"
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / CASE_PATH.name
            path.write_text(json.dumps(data), encoding="utf-8")
            loaded = self.loader.load_case(path)
        self.assertEqual("CAL-24X7", loaded.schedule["relationships"][0]["lag_calendar"])

    def test_duplicate_json_object_keys_are_rejected_before_schema_loading(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / CASE_PATH.name
            path.write_text('{"case_id":"A","case_id":"B"}', encoding="utf-8")
            with self.assertRaisesRegex(CanonicalValidationError, "duplicate JSON object key"):
                self.loader.load_case(path)
