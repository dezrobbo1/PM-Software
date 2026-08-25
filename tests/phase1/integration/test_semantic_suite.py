from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from deterministic_scheduling_core.canonical import CanonicalLoader
from deterministic_scheduling_core.cli import main as cli_main
from deterministic_scheduling_core.execution import SemanticSuiteHarness
from deterministic_scheduling_core.errors import SchedulingError, ValidationFailure
from deterministic_scheduling_core.provenance.canonical_json import sha256_digest
from deterministic_scheduling_core.provenance.runtime import verified_source_manifest_hash
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
            "native-requirements.json",
            "portable-semantic-result.json",
            "evidence-bundle.json",
            "execution-record.json",
            "environment-evidence.json",
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
            self.assertEqual(
                item["native_requirements_hash"],
                sha256_digest(self.read(case_id, "native-requirements.json")),
            )
            if item["status"] == "executed_pass":
                self.assertEqual(item["output_hash"], sha256_digest(self.read(case_id, "calculated-output.json")))
                self.assertEqual(item["explanation_hash"], sha256_digest(self.read(case_id, "explanation.json")))
                self.assertEqual(
                    item["portable_semantic_result_hash"],
                    sha256_digest(self.read(case_id, "portable-semantic-result.json")),
                )
                self.assertEqual(
                    item["environment_evidence_hash"],
                    sha256_digest(self.read(case_id, "environment-evidence.json")),
                )
            elif item["status"] == "executed_fail":
                self.assertEqual(
                    item["portable_failure_result_hash"],
                    sha256_digest(self.read(case_id, "portable-failure-result.json")),
                )
                self.assertEqual(
                    item["environment_evidence_hash"],
                    sha256_digest(self.read(case_id, "environment-evidence.json")),
                )

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
        native_requirements = self.read("SEM-STA-045", "native-requirements.json")
        self.assertEqual(
            ["p6", "microsoft_project"],
            [item["native_system"] for item in native_requirements["requirements"]],
        )
        self.assertTrue(
            all(item["status"] == "required_not_run" for item in native_requirements["requirements"])
        )

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
        native_requirements = self.read(case_id, "native-requirements.json")
        portable_result = self.read(case_id, "portable-semantic-result.json")
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
            native_requirements=native_requirements,
            portable_result=portable_result,
            bundle=bundle,
            record=record,
        )
        self.assertTrue(any("output_hash" in error for error in errors))

        output = self.read(case_id, "calculated-output.json")
        explanation = self.read(case_id, "explanation.json")
        identity = self.read(case_id, "execution-identity.json")
        bundle = self.read(case_id, "evidence-bundle.json")
        record = self.read(case_id, "execution-record.json")
        identity["dependency_environment"]["pip_version"] = "0.0-tampered"
        identity_hash = sha256_digest(identity)
        explanation["recomputation"]["execution_identity"] = identity_hash
        explanation_hash = sha256_digest(explanation)
        bundle["execution_identity"] = identity_hash
        bundle["explanation_hash"] = explanation_hash
        record["execution_identity"] = identity_hash
        record["explanation_hash"] = explanation_hash
        record["evidence_bundle_hash"] = sha256_digest(bundle)
        errors = self.harness.evidence_validator.validate_executed_artifacts(
            case=case,
            output=output,
            selected_state=selected,
            validation=validation,
            explanation=explanation,
            identity=identity,
            native_requirements=native_requirements,
            portable_result=portable_result,
            bundle=bundle,
            record=record,
        )
        self.assertTrue(any("pinned evidence environment" in error for error in errors))

        identity = self.read(case_id, "execution-identity.json")
        explanation = self.read(case_id, "explanation.json")
        native_requirements = self.read(case_id, "native-requirements.json")
        portable_result = self.read(case_id, "portable-semantic-result.json")
        bundle = self.read(case_id, "evidence-bundle.json")
        record = self.read(case_id, "execution-record.json")
        native_requirements["requirements"][0]["preregistration_id"] = "tampered-plan"
        native_requirements_hash = sha256_digest(native_requirements)
        portable_result["native_requirements_hash"] = native_requirements_hash
        portable_result_hash = sha256_digest(portable_result)
        bundle["native_requirements_hash"] = native_requirements_hash
        bundle["portable_semantic_result_hash"] = portable_result_hash
        record["evidence_bundle_hash"] = sha256_digest(bundle)
        errors = self.harness.evidence_validator.validate_executed_artifacts(
            case=case,
            output=output,
            selected_state=selected,
            validation=validation,
            explanation=explanation,
            identity=identity,
            native_requirements=native_requirements,
            portable_result=portable_result,
            bundle=bundle,
            record=record,
        )
        self.assertTrue(any("complete preregistered projection" in error for error in errors))

        errors = self.harness.evidence_validator.validate_executed_artifacts(
            case=case,
            output=output,
            selected_state=selected,
            validation=validation,
            explanation=explanation,
            identity=identity,
            native_requirements=["not", "an", "object"],
            portable_result=portable_result,
            bundle=bundle,
            record=record,
        )
        self.assertIn("native requirements must be a JSON object", errors)

        native_requirements = self.read(case_id, "native-requirements.json")
        portable_result = self.read(case_id, "portable-semantic-result.json")
        bundle = self.read(case_id, "evidence-bundle.json")
        record = self.read(case_id, "execution-record.json")
        bundle["evidence_paths"] = 7
        errors = self.harness.evidence_validator.validate_executed_artifacts(
            case=case,
            output=output,
            selected_state=selected,
            validation=validation,
            explanation=explanation,
            identity=identity,
            native_requirements=native_requirements,
            portable_result=portable_result,
            bundle=bundle,
            record=record,
        )
        self.assertIn("evidence bundle evidence_paths must be an array", errors)

    def test_remaining_start_and_trace_cause_tampering_are_detected(self) -> None:
        cases = {case.case_id: case for case in CanonicalLoader(ROOT).discover_frozen_suite()}

        case = cases["SEM-STA-040"]
        output = self.read(case.case_id, "calculated-output.json")
        selected = self.read(case.case_id, "selected-state.json")
        validation = self.read(case.case_id, "validation.json")
        explanation = self.read(case.case_id, "explanation.json")
        identity = self.read(case.case_id, "execution-identity.json")
        native_requirements = self.read(case.case_id, "native-requirements.json")
        portable_result = self.read(case.case_id, "portable-semantic-result.json")
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
            native_requirements=native_requirements,
            portable_result=portable_result,
            bundle=bundle,
            record=record,
        )
        self.assertTrue(any("remaining_start differs" in error for error in errors))

        selected = self.read(case.case_id, "selected-state.json")
        selected["activity_states"].append(copy.deepcopy(selected["activity_states"][0]))
        selected_hash = sha256_digest(selected)
        portable_result = self.read(case.case_id, "portable-semantic-result.json")
        portable_result["selected_state_hash"] = selected_hash
        portable_result_hash = sha256_digest(portable_result)
        bundle = self.read(case.case_id, "evidence-bundle.json")
        bundle["selected_scenario_hash"] = selected_hash
        bundle["portable_semantic_result_hash"] = portable_result_hash
        record = self.read(case.case_id, "execution-record.json")
        record["selected_scenario_hash"] = selected_hash
        record["evidence_bundle_hash"] = sha256_digest(bundle)
        errors = self.harness.evidence_validator.validate_executed_artifacts(
            case=case,
            output=output,
            selected_state=selected,
            validation=validation,
            explanation=explanation,
            identity=identity,
            native_requirements=native_requirements,
            portable_result=portable_result,
            bundle=bundle,
            record=record,
        )
        self.assertTrue(any("duplicate activity_id" in error for error in errors))

        case = cases["SEM-CON-035"]
        output = self.read(case.case_id, "calculated-output.json")
        selected = self.read(case.case_id, "selected-state.json")
        validation = self.read(case.case_id, "validation.json")
        explanation = self.read(case.case_id, "explanation.json")
        identity = self.read(case.case_id, "execution-identity.json")
        native_requirements = self.read(case.case_id, "native-requirements.json")
        portable_result = self.read(case.case_id, "portable-semantic-result.json")
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
            native_requirements=native_requirements,
            portable_result=portable_result,
            bundle=bundle,
            record=record,
        )
        self.assertTrue(any("constraint_value is inconsistent" in error for error in errors))

    def test_deterministic_profile_v03_is_pinned(self) -> None:
        self.assertEqual("deterministic-v0.3", self.harness.profile["profile_id"])
        self.assertEqual("dsc-canonical-json-v1", self.harness.profile["canonical_json"])
        self.assertEqual(
            "canonical-record-with-executed_at-omitted",
            self.harness.profile["execution_record_hash_projection"],
        )
        self.assertEqual(
            "phase1-portable-semantic-result-v0.1",
            self.harness.profile["portable_semantic_result_projection"],
        )
        self.assertEqual(
            "phase1-portable-failure-result-v0.1",
            self.harness.profile["portable_failure_result_projection"],
        )
        self.assertEqual(
            "phase1-environment-evidence-v0.1",
            self.harness.profile["environment_evidence_projection"],
        )
        self.assertEqual(9, len(self.harness.profile["dependency_distributions"]))
        self.assertEqual(
            "CPython 3.11.x or 3.12.x on Linux x86_64",
            self.harness.profile["python_runtime"],
        )
        identity = self.read("SEM-REL-001", "execution-identity.json")
        dependency_environment = identity["dependency_environment"]
        self.assertEqual(
            "locked_runtime_and_build_dependency_closure",
            dependency_environment["scope"],
        )
        self.assertNotIn("installed_distributions", dependency_environment)
        self.assertNotIn("suite_hash", self.suite_run.summary)

        def write_manifest(root: Path, relative_paths: list[str]) -> None:
            lines = []
            for relative in sorted(relative_paths):
                digest = hashlib.sha256((root / relative).read_bytes()).hexdigest()
                lines.append(f"{digest}  {relative}")
            (root / "manifest.sha256").write_text(
                "\n".join(lines) + "\n", encoding="utf-8"
            )

        with tempfile.TemporaryDirectory() as temporary:
            archive_root = Path(temporary)
            (archive_root / "one.txt").write_text("one", encoding="utf-8")
            write_manifest(archive_root, ["one.txt"])
            self.assertEqual(
                hashlib.sha256((archive_root / "manifest.sha256").read_bytes()).hexdigest(),
                verified_source_manifest_hash(archive_root),
            )

            (archive_root / "omitted.txt").write_text("omitted", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "omitted: omitted.txt"):
                verified_source_manifest_hash(archive_root)

            write_manifest(archive_root, ["one.txt", "omitted.txt"])
            duplicate_line = (archive_root / "manifest.sha256").read_text(encoding="utf-8").splitlines()[0]
            with (archive_root / "manifest.sha256").open("a", encoding="utf-8") as stream:
                stream.write(duplicate_line + "\n")
            with self.assertRaisesRegex(RuntimeError, "duplicate path"):
                verified_source_manifest_hash(archive_root)

            write_manifest(archive_root, ["one.txt", "omitted.txt"])
            (archive_root / "linked.txt").symlink_to("one.txt")
            with self.assertRaisesRegex(RuntimeError, "symbolic link"):
                verified_source_manifest_hash(archive_root)

    def test_invalid_execution_timestamp_is_rejected_before_any_case_runs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, "RFC 3339"):
                self.harness.run(
                    output_dir=Path(temporary) / "invalid-time",
                    executed_at="not-a-timestamp",
                )

    def test_unexplained_case_failure_is_retained_and_suite_fails(self) -> None:
        def run_with_failure(message: str, output_dir: Path):
            harness = SemanticSuiteHarness(ROOT)
            original = harness.kernel.calculate

            def fail_one(schedule, *, case_id, category):
                if case_id == "SEM-REL-001":
                    raise SchedulingError(message)
                return original(schedule, case_id=case_id, category=category)

            with patch.object(harness.kernel, "calculate", side_effect=fail_one):
                return harness, harness.run(output_dir=output_dir)

        with tempfile.TemporaryDirectory() as temporary:
            first_dir = Path(temporary) / "retained-failure-a"
            second_dir = Path(temporary) / "retained-failure-b"
            harness, first_run = run_with_failure("focused retained failure A", first_dir)
            _, second_run = run_with_failure("focused retained failure B", second_dir)
            failure_path = first_dir / "cases" / "SEM-REL-001" / "failure.json"
            portable_failure_path = (
                first_dir / "cases" / "SEM-REL-001" / "portable-failure-result.json"
            )
            self.assertFalse(first_run.passed)
            self.assertEqual(1, first_run.summary["counts"]["executed_fail"])
            self.assertTrue(failure_path.is_file())
            self.assertTrue(portable_failure_path.is_file())
            self.assertNotEqual(
                first_run.summary["portable_suite_result_hash"],
                second_run.summary["portable_suite_result_hash"],
            )
            first_case = next(
                item
                for item in first_run.summary["cases"]
                if item["case_id"] == "SEM-REL-001"
            )
            second_case = next(
                item
                for item in second_run.summary["cases"]
                if item["case_id"] == "SEM-REL-001"
            )
            self.assertNotEqual(
                first_case["portable_failure_result_hash"],
                second_case["portable_failure_result_hash"],
            )

            def read_failure_artifact(filename: str):
                return json.loads(
                    (first_dir / "cases" / "SEM-REL-001" / filename).read_text()
                )

            case = next(
                case
                for case in CanonicalLoader(ROOT).discover_frozen_suite()
                if case.case_id == "SEM-REL-001"
            )
            artifacts = {
                "failure": read_failure_artifact("failure.json"),
                "identity": read_failure_artifact("execution-identity.json"),
                "native_requirements": read_failure_artifact("native-requirements.json"),
                "portable_failure_result": read_failure_artifact(
                    "portable-failure-result.json"
                ),
                "bundle": read_failure_artifact("evidence-bundle.json"),
                "record": read_failure_artifact("execution-record.json"),
            }
            self.assertEqual(
                [],
                harness.evidence_validator.validate_failure_artifacts(
                    case=case, **artifacts
                ),
            )
            artifacts["bundle"]["evidence_paths"] = 7
            errors = harness.evidence_validator.validate_failure_artifacts(
                case=case, **artifacts
            )
            self.assertIn(
                "failure evidence bundle evidence_paths must be an array", errors
            )
            artifacts["bundle"] = read_failure_artifact("evidence-bundle.json")
            artifacts["native_requirements"]["requirements"][0][
                "preregistration_id"
            ] = "tampered-plan"
            errors = harness.evidence_validator.validate_failure_artifacts(
                case=case, **artifacts
            )
            self.assertTrue(
                any("native requirements" in error for error in errors), errors
            )

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
            marker = output_dir / harness.profile["output_directory_owner_marker"]
            marker_before = marker.read_bytes()
            self.assertTrue(
                (output_dir / "cases" / "SEM-REL-001" / "failure.json").is_file()
            )

            self.assertTrue(harness.run(output_dir=output_dir).passed)
            passing_files = {
                path.name for path in (output_dir / "cases" / "SEM-REL-001").iterdir()
            }
            self.assertNotIn("failure.json", passing_files)
            self.assertIn("calculated-output.json", passing_files)
            self.assertEqual(marker_before, marker.read_bytes())

            with patch.object(harness.kernel, "calculate", side_effect=fail_one):
                self.assertFalse(harness.run(output_dir=output_dir).passed)
            failure_files = {
                path.name for path in (output_dir / "cases" / "SEM-REL-001").iterdir()
            }
            self.assertEqual(
                {
                    "failure.json",
                    "execution-identity.json",
                    "native-requirements.json",
                    "portable-failure-result.json",
                    "evidence-bundle.json",
                    "execution-record.json",
                    "environment-evidence.json",
                },
                failure_files,
            )

    def test_reused_output_directory_preserves_unrelated_entries(self) -> None:
        harness = SemanticSuiteHarness(ROOT)
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary) / "not-managed"
            unrelated = output_dir / "cases" / "keep-me.txt"
            unrelated.parent.mkdir(parents=True)
            unrelated.write_text("user-owned", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "not owned"):
                harness.run(output_dir=output_dir)
            self.assertEqual("user-owned", unrelated.read_text(encoding="utf-8"))

            owned_dir = Path(temporary) / "tampered-marker"
            self.assertTrue(harness.run(output_dir=owned_dir).passed)
            marker = owned_dir / harness.profile["output_directory_owner_marker"]
            marker.write_text("{}\n", encoding="utf-8")
            retained = owned_dir / "cases" / "SEM-REL-001" / "calculated-output.json"
            retained_before = retained.read_bytes()
            with self.assertRaisesRegex(ValueError, "marker does not match"):
                harness.run(output_dir=owned_dir)
            self.assertEqual(retained_before, retained.read_bytes())

            cli_target = Path(temporary) / "cli-symlink-target"
            cli_target.mkdir()
            cli_link = Path(temporary) / "cli-symlink"
            cli_link.symlink_to(cli_target, target_is_directory=True)
            with patch("builtins.print"):
                exit_code = cli_main(
                    [
                        "run-semantic-suite",
                        "--repository-root",
                        str(ROOT),
                        "--output-dir",
                        str(cli_link),
                    ]
                )
            self.assertEqual(1, exit_code)
            self.assertEqual([], list(cli_target.iterdir()))

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
