from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from deterministic_scheduling_core.canonical import CanonicalLoader
from deterministic_scheduling_core.execution import SemanticSuiteHarness
from deterministic_scheduling_core.errors import SchedulingError, ValidationFailure
from deterministic_scheduling_core.provenance.canonical_json import sha256_digest
from deterministic_scheduling_core.validation import execution_record_hash


ROOT = Path(__file__).resolve().parents[3]


class SemanticSuiteIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.output_dir = Path(cls.temporary.name) / "evidence"
        cls.harness = SemanticSuiteHarness(ROOT)
        cls.suite_run = cls.harness.run(output_dir=cls.output_dir)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def read(self, case_id: str, filename: str):
        return json.loads((self.output_dir / "cases" / case_id / filename).read_text())

    def test_exact_fixture_disposition(self) -> None:
        self.assertTrue(self.suite_run.passed)
        self.assertEqual(
            {"executed_pass": 49, "executed_fail": 0, "native_validation_required": 1, "total": 50},
            self.suite_run.summary["counts"],
        )

    def test_every_declared_case_has_complete_evidence(self) -> None:
        expected_files = {
            "canonical-input.json",
            "calculated-output.json",
            "selected-state.json",
            "validation.json",
            "explanation.json",
            "execution-identity.json",
            "evidence-bundle.json",
            "execution-record.json",
        }
        for item in self.suite_run.summary["cases"]:
            if item["status"] != "executed_pass":
                continue
            with self.subTest(case=item["case_id"]):
                files = {path.name for path in (self.output_dir / "cases" / item["case_id"]).iterdir()}
                self.assertEqual(expected_files, files)

    def test_hashes_recompute_from_saved_artifacts(self) -> None:
        for item in self.suite_run.summary["cases"]:
            case_id = item["case_id"]
            record = self.read(case_id, "execution-record.json")
            self.assertEqual(item["execution_record_hash"], execution_record_hash(record))
            if item["status"] == "executed_pass":
                self.assertEqual(item["output_hash"], sha256_digest(self.read(case_id, "calculated-output.json")))
                self.assertEqual(item["explanation_hash"], sha256_digest(self.read(case_id, "explanation.json")))

    def test_all_saved_execution_and_explanation_documents_match_frozen_schemas(self) -> None:
        for item in self.suite_run.summary["cases"]:
            record = self.read(item["case_id"], "execution-record.json")
            self.assertEqual([], self.harness.evidence_validator.validate_native_record(record))
            if item["status"] == "executed_pass":
                explanation = self.read(item["case_id"], "explanation.json")
                self.assertEqual(
                    [],
                    self.harness.evidence_validator._schema_errors(
                        self.harness.evidence_validator.explanation_validator,
                        explanation,
                        "explanation",
                    ),
                )

    def test_native_only_case_has_no_fabricated_execution_hashes(self) -> None:
        record = self.read("SEM-STA-045", "execution-record.json")
        self.assertEqual("native_validation_required", record["status"])
        for field in (
            "execution_identity",
            "input_hash",
            "output_hash",
            "selected_scenario_hash",
            "explanation_hash",
            "evidence_bundle_hash",
        ):
            self.assertIsNone(record[field])
        self.assertEqual([], record["objective_vector"])

    def test_selected_state_hash_binds_in_progress_remaining_start(self) -> None:
        output = self.read("SEM-STA-040", "calculated-output.json")
        selected = self.read("SEM-STA-040", "selected-state.json")
        selected_by_id = {item["activity_id"]: item for item in selected["activity_states"]}
        in_progress_ids = [
            activity_id
            for activity_id, record in output["activity_times"].items()
            if "remaining_start" in record
        ]
        self.assertTrue(in_progress_ids)
        for activity_id in in_progress_ids:
            self.assertEqual(
                output["activity_times"][activity_id]["remaining_start"],
                selected_by_id[activity_id]["remaining_start"],
            )

    def test_calculation_traces_name_the_actual_governing_cause(self) -> None:
        constraint = self.read("SEM-CON-035", "explanation.json")
        self.assertEqual("date_constraint", constraint["reason_type"])
        self.assertEqual(
            {"type": "constraint", "id": "C-A-01", "source_field": None},
            constraint["governing_entity"],
        )
        self.assertEqual(5, constraint["calculation_trace"]["input_values"]["constraint_value"])

        resource = self.read("SEM-DET-050", "explanation.json")
        self.assertEqual("resource_conflict", resource["reason_type"])
        self.assertEqual("R1", resource["governing_entity"]["id"])
        self.assertEqual("A", resource["activity_id"])
        self.assertEqual("B", resource["conflicting_activity_id"])
        self.assertEqual(
            ["B", "A"],
            resource["calculation_trace"]["input_values"]["selected_resource_order"],
        )

        precedence = self.read("SEM-REL-001", "explanation.json")
        self.assertEqual("precedence", precedence["reason_type"])
        self.assertEqual("R1", precedence["governing_entity"]["id"])
        self.assertEqual(
            "FS", precedence["calculation_trace"]["input_values"]["relationship_type"]
        )

    def test_evidence_tampering_is_detected(self) -> None:
        case = CanonicalLoader(ROOT).discover_frozen_suite()[0]
        case_id = case.case_id
        output = self.read(case_id, "calculated-output.json")
        selected = self.read(case_id, "selected-state.json")
        validation = self.read(case_id, "validation.json")
        explanation = self.read(case_id, "explanation.json")
        identity = self.read(case_id, "execution-identity.json")
        bundle = self.read(case_id, "evidence-bundle.json")
        record = self.read(case_id, "execution-record.json")
        output["project_finish"] += 1
        errors = self.harness.evidence_validator.validate_executed_artifacts(
            case=case,
            output=output,
            selected_state=selected,
            validation=validation,
            explanation=explanation,
            identity=identity,
            bundle=bundle,
            record=record,
        )
        self.assertTrue(any("output_hash" in error for error in errors))

    def test_remaining_start_and_trace_cause_tampering_are_detected(self) -> None:
        cases = {case.case_id: case for case in CanonicalLoader(ROOT).discover_frozen_suite()}

        case = cases["SEM-STA-040"]
        output = self.read(case.case_id, "calculated-output.json")
        selected = self.read(case.case_id, "selected-state.json")
        validation = self.read(case.case_id, "validation.json")
        explanation = self.read(case.case_id, "explanation.json")
        identity = self.read(case.case_id, "execution-identity.json")
        bundle = self.read(case.case_id, "evidence-bundle.json")
        record = self.read(case.case_id, "execution-record.json")
        in_progress = next(
            item for item in selected["activity_states"] if "remaining_start" in item
        )
        in_progress["remaining_start"] += 1
        errors = self.harness.evidence_validator.validate_executed_artifacts(
            case=case,
            output=output,
            selected_state=selected,
            validation=validation,
            explanation=explanation,
            identity=identity,
            bundle=bundle,
            record=record,
        )
        self.assertTrue(any("remaining_start differs" in error for error in errors))

        case = cases["SEM-CON-035"]
        output = self.read(case.case_id, "calculated-output.json")
        selected = self.read(case.case_id, "selected-state.json")
        validation = self.read(case.case_id, "validation.json")
        explanation = self.read(case.case_id, "explanation.json")
        identity = self.read(case.case_id, "execution-identity.json")
        bundle = self.read(case.case_id, "evidence-bundle.json")
        record = self.read(case.case_id, "execution-record.json")
        explanation["calculation_trace"]["input_values"]["constraint_value"] = 0
        errors = self.harness.evidence_validator.validate_executed_artifacts(
            case=case,
            output=output,
            selected_state=selected,
            validation=validation,
            explanation=explanation,
            identity=identity,
            bundle=bundle,
            record=record,
        )
        self.assertTrue(any("constraint_value is inconsistent" in error for error in errors))

    def test_deterministic_profile_v02_is_pinned(self) -> None:
        self.assertEqual("deterministic-v0.2", self.harness.profile["profile_id"])
        self.assertEqual("dsc-canonical-json-v1", self.harness.profile["canonical_json"])
        self.assertEqual(
            "canonical-record-with-executed_at-omitted",
            self.harness.profile["execution_record_hash_projection"],
        )

    def test_invalid_execution_timestamp_is_rejected_before_any_case_runs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, "RFC 3339"):
                self.harness.run(
                    output_dir=Path(temporary) / "invalid-time",
                    executed_at="not-a-timestamp",
                )

    def test_unexplained_case_failure_is_retained_and_suite_fails(self) -> None:
        harness = SemanticSuiteHarness(ROOT)
        original = harness.kernel.calculate

        def fail_one(schedule, *, case_id, category):
            if case_id == "SEM-REL-001":
                raise SchedulingError("focused retained failure")
            return original(schedule, case_id=case_id, category=category)

        with tempfile.TemporaryDirectory() as temporary, patch.object(
            harness.kernel, "calculate", side_effect=fail_one
        ):
            run = harness.run(output_dir=Path(temporary) / "retained-failure")
            failure_path = (
                Path(temporary)
                / "retained-failure"
                / "cases"
                / "SEM-REL-001"
                / "failure.json"
            )
            self.assertFalse(run.passed)
            self.assertEqual(1, run.summary["counts"]["executed_fail"])
            self.assertTrue(failure_path.is_file())

    def test_reused_output_directory_clears_stale_case_artifacts(self) -> None:
        harness = SemanticSuiteHarness(ROOT)
        original = harness.kernel.calculate

        def fail_one(schedule, *, case_id, category):
            if case_id == "SEM-REL-001":
                raise SchedulingError("focused retained failure")
            return original(schedule, case_id=case_id, category=category)

        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary) / "reused"
            with patch.object(harness.kernel, "calculate", side_effect=fail_one):
                self.assertFalse(harness.run(output_dir=output_dir).passed)
            self.assertTrue(
                (output_dir / "cases" / "SEM-REL-001" / "failure.json").is_file()
            )

            self.assertTrue(harness.run(output_dir=output_dir).passed)
            passing_files = {
                path.name for path in (output_dir / "cases" / "SEM-REL-001").iterdir()
            }
            self.assertNotIn("failure.json", passing_files)
            self.assertIn("calculated-output.json", passing_files)

            with patch.object(harness.kernel, "calculate", side_effect=fail_one):
                self.assertFalse(harness.run(output_dir=output_dir).passed)
            failure_files = {
                path.name for path in (output_dir / "cases" / "SEM-REL-001").iterdir()
            }
            self.assertEqual(
                {
                    "failure.json",
                    "execution-identity.json",
                    "evidence-bundle.json",
                    "execution-record.json",
                },
                failure_files,
            )

    def test_reused_output_directory_preserves_unrelated_entries(self) -> None:
        harness = SemanticSuiteHarness(ROOT)
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary) / "not-managed"
            output_dir.mkdir()
            unrelated = output_dir / "keep-me.txt"
            unrelated.write_text("user-owned", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "non-suite entries"):
                harness.run(output_dir=output_dir)
            self.assertEqual("user-owned", unrelated.read_text(encoding="utf-8"))

    def test_native_only_evidence_failure_is_retained_in_suite_summary(self) -> None:
        harness = SemanticSuiteHarness(ROOT)
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            harness,
            "_write_native_disposition",
            side_effect=ValidationFailure("focused native disposition failure"),
        ):
            output_dir = Path(temporary) / "native-failure"
            run = harness.run(output_dir=output_dir)
            self.assertFalse(run.passed)
            self.assertEqual(1, run.summary["counts"]["executed_fail"])
            self.assertEqual(0, run.summary["counts"]["native_validation_required"])
            failure = json.loads(
                (output_dir / "cases" / "SEM-STA-045" / "failure.json").read_text()
            )
            self.assertEqual("ValidationFailure", failure["failure_code"])
