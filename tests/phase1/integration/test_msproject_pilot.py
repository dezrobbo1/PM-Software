from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from deterministic_scheduling_core.native.msproject.freeze import (
    INDEPENDENT_VERIFICATION_EVIDENCE_ROLES,
    OBSERVED_PRODUCT_SETTING_IDS,
    PRE_EXECUTION_ACTION_IDS,
)
from deterministic_scheduling_core.native.msproject.pilot import (
    APPLICATION_CALCULATION_OFFICIAL_URL,
    CASE_IDS,
    COMPARISON_PROFILE_ID,
    FIXTURE_RAW_SHA256_BY_CASE_ID,
    MAPPING_SOURCE_REGISTER,
    MANIFEST,
    NATIVE_ATTEMPT_STOP_TEMPLATE,
    OPERATOR_ENVIRONMENT_TEMPLATE,
    OPERATOR_RUNBOOK,
    POST_EXECUTION_ATTESTATION_TEMPLATE,
    POST_EXECUTION_ACTION_IDS_BY_TRACK,
    PILOT_ID,
    PILOT_INDEX,
    PILOT_STATUS,
    PREREGISTRATION_ID,
    PREREGISTRATION_PATH,
    PREREGISTRATION_RAW_SHA256,
    PROFILE_PATH,
    PROFILE_RAW_SHA256,
    PROJECT_SUMMARY_UID_OFFICIAL_URL,
    PROJECT_SUMMARY_VISIBILITY_OFFICIAL_URL,
    SUMMARY_ELEMENT_OFFICIAL_URL,
    TASK_ELEMENT_OFFICIAL_URL,
    TRACK_A_POST_EXECUTION_ACTION_LOG_TEMPLATE,
    TRACK_B_POST_EXECUTION_ACTION_LOG_TEMPLATE,
    TRACK_IDS,
    PilotBindingError,
    PilotSafetyError,
    PilotVerificationError,
    prepare_pilot,
    pilot_input_identity_projection,
    pilot_input_identity_sha256,
    verify_pilot,
)
from deterministic_scheduling_core.native.msproject.normalizer import (
    POST_EXECUTION_ACTION_IDS_BY_TRACK as NORMALIZER_POST_EXECUTION_ACTION_IDS_BY_TRACK,
)
from deterministic_scheduling_core.native.msproject.stopped import (
    STOP_CONDITION_IDS,
    STOP_OUTCOME_BY_CONDITION_AND_NATIVE_CALCULATION,
    STOP_OUTCOME_CLASSIFICATIONS,
    STOP_RECORD_REQUIRED_FIELDS,
)
from deterministic_scheduling_core.provenance.canonical_json import canonical_text


ROOT = Path(__file__).resolve().parents[3]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _all_object_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {
            child_key
            for child in value.values()
            for child_key in _all_object_keys(child)
        }
    if isinstance(value, list):
        return {child_key for child in value for child_key in _all_object_keys(child)}
    return set()


class MicrosoftProjectPilotTests(unittest.TestCase):
    def test_exact_case_order_counts_status_and_bindings(self) -> None:
        self.assertEqual(
            tuple(f"SEM-REL-{number:03d}" for number in range(1, 13)), CASE_IDS
        )
        self.assertEqual(12, len(CASE_IDS))
        self.assertEqual(
            (
                "manual_native_semantic_parity",
                "saved_file_reopen_recalculate_stability",
                "adapter_interchange_round_trip",
            ),
            TRACK_IDS,
        )
        self.assertEqual(PREREGISTRATION_RAW_SHA256, _sha256(ROOT / PREREGISTRATION_PATH))
        self.assertEqual(PROFILE_RAW_SHA256, _sha256(ROOT / PROFILE_PATH))
        for case_id in CASE_IDS:
            with self.subTest(case_id=case_id):
                fixture = ROOT / "benchmarks" / "semantic" / "cases" / f"{case_id.lower()}.json"
                self.assertEqual(FIXTURE_RAW_SHA256_BY_CASE_ID[case_id], _sha256(fixture))

        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "pilot"
            summary = prepare_pilot(output, repository_root=ROOT)
            index = _json(output / PILOT_INDEX)
            mapping_register_sha256 = _sha256(output / MAPPING_SOURCE_REGISTER)
            source_only_hashes = {
                case_id: _sha256(
                    output / "source-only-case-projections" / f"{case_id}.json"
                )
                for case_id in CASE_IDS
            }
        self.assertEqual(PILOT_ID, summary["pilot_id"])
        self.assertEqual(PILOT_STATUS, summary["status"])
        self.assertEqual(list(CASE_IDS), index["case_ids"])
        self.assertEqual(12, index["case_count"])
        self.assertEqual(12, len(index["cases"]))
        self.assertEqual(PREREGISTRATION_ID, index["source_bindings"]["preregistration"]["id"])
        self.assertEqual(
            COMPARISON_PROFILE_ID,
            index["source_bindings"]["comparison_profile"]["id"],
        )
        projection = pilot_input_identity_projection(
            mapping_source_register_raw_sha256=mapping_register_sha256,
            source_only_projection_raw_sha256_by_case_id=source_only_hashes,
        )
        self.assertEqual(projection, index["pilot_input_identity"]["projection"])
        self.assertEqual(
            pilot_input_identity_sha256(projection),
            index["pilot_input_identity"]["sha256"],
        )

    def test_operator_and_review_material_does_not_leak_sealed_expectations(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "pilot"
            prepare_pilot(output, repository_root=ROOT)
            for case_id in CASE_IDS:
                fixture = _json(
                    ROOT
                    / "benchmarks"
                    / "semantic"
                    / "cases"
                    / f"{case_id.lower()}.json"
                )
                operator_path = (
                    output
                    / "tracks"
                    / "manual_native_semantic_parity"
                    / "operator-build-sheets"
                    / f"{case_id}.json"
                )
                review_path = (
                    output
                    / "tracks"
                    / "manual_native_semantic_parity"
                    / "independent-review-sheets"
                    / f"{case_id}.json"
                )
                for controlled_path in (operator_path, review_path):
                    with self.subTest(case_id=case_id, artifact=controlled_path.name):
                        document = _json(controlled_path)
                        self.assertNotIn("expected", document)
                        self.assertNotIn("expected_normalized", document)
                        self.assertNotIn(
                            json.dumps(fixture["expected"], sort_keys=True),
                            json.dumps(document, sort_keys=True),
                        )
                        self.assertTrue(
                            {
                                "expected",
                                "expected_normalized",
                                "activity_times",
                                "project_finish",
                                "total_float",
                                "free_float",
                                "driving_relationships",
                                "resource_order",
                                "assertions",
                            }.isdisjoint(_all_object_keys(document))
                        )
                        self.assertIn("source_facts", document)
                sealed = _json(output / "sealed-expected-normalized" / f"{case_id}.json")
                self.assertEqual(fixture["expected"]["activity_times"], sealed["expected_normalized"]["activity_times"])
                self.assertEqual(fixture["expected"]["project_finish"], sealed["expected_normalized"]["project_finish"])

    def test_every_operator_visible_artifact_excludes_oracle_keys_and_coordinates(self) -> None:
        forbidden_keys = {
            "expected",
            "expected_normalized",
            "activity_times",
            "project_finish",
            "total_float",
            "free_float",
            "driving_relationships",
            "resource_order",
            "assertions",
        }
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "pilot"
            prepare_pilot(output, repository_root=ROOT)
            visible_files = {
                relative_path: data
                for relative_path, data in _snapshot(output).items()
                if not relative_path.startswith("sealed-expected-normalized/")
                and relative_path not in {MANIFEST, "pilot-kit-manifest.sha256"}
            }
            for relative_path, data in visible_files.items():
                if relative_path.endswith(".json"):
                    document = json.loads(data.decode("utf-8"))
                    self.assertTrue(
                        forbidden_keys.isdisjoint(_all_object_keys(document)),
                        relative_path,
                    )
            visible_text = b"\n".join(visible_files.values()).decode("utf-8")
            for case_id in CASE_IDS:
                fixture = _json(
                    ROOT
                    / "benchmarks"
                    / "semantic"
                    / "cases"
                    / f"{case_id.lower()}.json"
                )
                expected = fixture["expected"]
                forbidden_fragments = (
                    canonical_text(expected["activity_times"]),
                    canonical_text(
                        {"project_finish": expected["project_finish"]}
                    ),
                    canonical_text(
                        {
                            "activity_times": expected["activity_times"],
                            "project_finish": expected["project_finish"],
                        }
                    ),
                )
                for fragment in forbidden_fragments:
                    self.assertNotIn(fragment, visible_text, case_id)

    def test_operator_bindings_target_source_only_projections_and_full_fixture_is_sealed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "pilot"
            prepare_pilot(output, repository_root=ROOT)
            snapshot = _snapshot(output)
            visible_bytes = b"\n".join(
                data
                for relative_path, data in snapshot.items()
                if not relative_path.startswith("sealed-expected-normalized/")
            )
            index = _json(output / PILOT_INDEX)
            indexed_cases = {item["case_id"]: item for item in index["cases"]}
            for case_id in CASE_IDS:
                with self.subTest(case_id=case_id):
                    fixture_path = (
                        ROOT
                        / "benchmarks"
                        / "semantic"
                        / "cases"
                        / f"{case_id.lower()}.json"
                    )
                    fixture_relative = fixture_path.relative_to(ROOT).as_posix()
                    fixture_sha256 = _sha256(fixture_path)
                    self.assertNotIn(fixture_relative.encode("utf-8"), visible_bytes)
                    self.assertNotIn(fixture_sha256.encode("ascii"), visible_bytes)

                    projection_path = (
                        output / "source-only-case-projections" / f"{case_id}.json"
                    )
                    projection = _json(projection_path)
                    self.assertFalse(
                        projection["projection_contract"]["oracle_content_included"]
                    )
                    self.assertFalse(
                        projection["projection_contract"][
                            "full_fixture_binding_included"
                        ]
                    )
                    self.assertNotIn("expected", projection)
                    binding = indexed_cases[case_id]["source_only_case_projection"]
                    self.assertEqual(
                        "source_only_case_projection", binding["binding_role"]
                    )
                    self.assertEqual(_sha256(projection_path), binding["raw_sha256"])
                    self.assertEqual(
                        "native-validation/pilot-kits/"
                        f"{PILOT_ID}/source-only-case-projections/{case_id}.json",
                        binding["relative_path"],
                    )

                    for artifact_path in (
                        output
                        / "tracks"
                        / "manual_native_semantic_parity"
                        / "operator-build-sheets"
                        / f"{case_id}.json",
                        output
                        / "tracks"
                        / "manual_native_semantic_parity"
                        / "independent-review-sheets"
                        / f"{case_id}.json",
                        output
                        / "tracks"
                        / "saved_file_reopen_recalculate_stability"
                        / "case-protocols"
                        / f"{case_id}.json",
                        output
                        / "tracks"
                        / "adapter_interchange_round_trip"
                        / "adapter-blockers"
                        / f"{case_id}.json",
                    ):
                        bound = _json(artifact_path)["source_bindings"]
                        self.assertNotIn("fixture", bound)
                        self.assertEqual(
                            binding, bound["source_only_case_projection"]
                        )

                    sealed = _json(
                        output / "sealed-expected-normalized" / f"{case_id}.json"
                    )
                    full_binding = sealed["source_bindings"]["fixture"]
                    self.assertEqual(fixture_relative, full_binding["relative_path"])
                    self.assertEqual(fixture_sha256, full_binding["raw_sha256"])
                    self.assertTrue(
                        sealed["seal_control"][
                            "full_oracle_fixture_binding_is_sealed"
                        ]
                    )

    def test_tracks_are_separate_and_adapter_is_honestly_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "pilot"
            prepare_pilot(output, repository_root=ROOT)
            index = _json(output / PILOT_INDEX)
            self.assertEqual(list(TRACK_IDS), [item["track_id"] for item in index["execution_tracks"]])
            artifact_sets: list[set[str]] = []
            for track_id in TRACK_IDS:
                artifact_sets.append(
                    {
                        artifact["relative_path"]
                        for case in index["cases"]
                        for artifact in case["tracks"][track_id]["artifacts"]
                    }
                )
            for first_index, first in enumerate(artifact_sets):
                for second in artifact_sets[first_index + 1 :]:
                    self.assertTrue(first.isdisjoint(second))

            for case in index["cases"]:
                adapter = case["tracks"]["adapter_interchange_round_trip"]
                self.assertEqual("preparation_blocked", adapter["adapter_preparation_status"])
                self.assertEqual("not_executed", adapter["native_execution_status"])
                blocker = _json(output / adapter["artifacts"][0]["relative_path"])
                self.assertEqual("CAL-24X7", blocker["blocked_source_fact"]["canonical_calendar_id"])
                self.assertEqual(["FromTime", "ToTime"], blocker["unresolved_mapping"]["mspdi_elements"])
                self.assertIsNone(blocker["unresolved_mapping"]["from_time_value"])
                self.assertIsNone(blocker["unresolved_mapping"]["to_time_value"])
                self.assertFalse(blocker["adapter_payload_generated"])
                self.assertTrue(all(url.startswith("https://") for url in blocker["official_sources"]))

            mapping = _json(output / MAPPING_SOURCE_REGISTER)
            intent = mapping["schema_backed_intent_if_adapter_preparation_is_unblocked"]
            self.assertEqual("http://schemas.microsoft.com/project/2010", intent["mspdi_namespace"])
            self.assertEqual(14, intent["save_version"])
            self.assertEqual(0, intent["new_tasks_are_manual"])
            self.assertEqual(0, intent["task_pinned"])
            self.assertFalse(intent["authorization_to_emit_xml"])
            self.assertEqual([], list(output.rglob("*.xml")))
            self.assertEqual([], list(output.rglob("*.mpp")))

    def test_index_native_mappings_and_operator_runbook_are_execution_ready(self) -> None:
        native_type = {"FF": 0, "FS": 1, "SF": 2, "SS": 3}
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "pilot"
            prepare_pilot(output, repository_root=ROOT)
            index = _json(output / PILOT_INDEX)
            observed_type_lag_pairs: list[tuple[str, int]] = []
            for case in index["cases"]:
                mapping = case["native_mapping"]
                self.assertEqual(
                    [("A", 1, 1), ("B", 2, 2)],
                    [
                        (
                            item["activity_id"],
                            item["native_task_uid"],
                            item["native_task_id"],
                        )
                        for item in mapping["activities"]
                    ],
                )
                self.assertEqual(
                    [("A", 4, "4h"), ("B", 3, "3h")],
                    [
                        (
                            item["activity_id"],
                            item["canonical_duration_hours"],
                            item["native_duration_entry"],
                        )
                        for item in mapping["activities"]
                    ],
                )
                calendar = mapping["calendars"][0]
                self.assertEqual("CAL-24X7", calendar["canonical_calendar_id"])
                self.assertEqual("24 Hours", calendar["manual_native_calendar_name"])
                self.assertEqual("preparation_blocked", calendar["adapter_preparation_status"])
                relationship = mapping["relationships"][0]
                self.assertEqual(native_type[relationship["canonical_type"]], relationship["native_type"])
                self.assertEqual(
                    relationship["canonical_signed_lag_hours"] * 600,
                    relationship["native_link_lag_tenths_minutes"],
                )
                self.assertEqual(5, relationship["native_lag_format"])
                observed_type_lag_pairs.append(
                    (
                        relationship["canonical_type"],
                        relationship["canonical_signed_lag_hours"],
                    )
                )
                self.assertEqual(
                    "2026-01-05T08:00:00+08:00",
                    mapping["project_settings"]["native_project_start_timestamp"],
                )
                self.assertTrue(mapping["project_settings"]["schedule_from_start"])
                self.assertEqual(
                    "manual", mapping["project_settings"]["native_calculation_mode"]
                )
                self.assertEqual(
                    "constructed_not_calculated",
                    mapping["project_settings"]["precalculation_protocol_state"],
                )
                capture_template_path = output / case[
                    "environment_capture_template"
                ]["relative_path"]
                self.assertEqual(
                    case["environment_capture_template"]["sha256"],
                    _sha256(capture_template_path),
                )
                capture_template = _json(capture_template_path)
                self.assertEqual(case["case_id"], capture_template["case_id"])
                capture = capture_template["capture"]
                self.assertEqual(
                    list(PRE_EXECUTION_ACTION_IDS),
                    [item["action_id"] for item in capture["manual_actions_by_stage"]],
                )
                self.assertEqual(
                    list(INDEPENDENT_VERIFICATION_EVIDENCE_ROLES),
                    [
                        item["role"]
                        for item in capture["independent_verification_artifact_plan"]
                    ],
                )
                self.assertTrue(capture["schedule_from_start"])
                self.assertEqual("manual", capture["calculation_mode"])
                self.assertEqual(
                    "constructed_not_calculated",
                    capture["precalculation_protocol_state"],
                )
                self.assertIsNone(capture["status_date"])
                self.assertIsNone(
                    capture["project_calendar_settings"][
                        "continuous_working_time_verified"
                    ]
                )
                self.assertIsNone(
                    capture["Microsoft_Project_leveling_disabled_attestation"]
                )
                self.assertEqual(
                    set(OBSERVED_PRODUCT_SETTING_IDS),
                    set(capture["observed_product_settings"]),
                )
                for observation in capture["observed_product_settings"].values():
                    self.assertIsNone(observation["observed_value"])
                    self.assertIsNone(observation["observed_at"])
                    self.assertIsNone(observation["observed_by"])
                    self.assertIsNone(observation["independently_verified_at"])
                    self.assertIsNone(observation["independently_verified_by"])
                self.assertIn("status_date", capture_template["instructions"])
                self.assertIn("must remain null", capture_template["instructions"])
                self.assertTrue(
                    all(
                        item["native_task_id"] is None
                        and item["native_task_uid"] is None
                        and item["native_task_name"] is None
                        for item in capture["observed_native_activity_mapping"]
                    )
                )
                fixture = _json(
                    ROOT
                    / "benchmarks"
                    / "semantic"
                    / "cases"
                    / f"{case['case_id'].lower()}.json"
                )
                expected_constraints = [
                    (constraint["id"], activity["id"], constraint["value"], 4)
                    for activity in fixture["schedule"]["activities"]
                    for constraint in activity["constraints"]
                ]
                self.assertEqual(
                    expected_constraints,
                    [
                        (
                            item["constraint_id"],
                            item["activity_id"],
                            item["canonical_coordinate"],
                            item["native_constraint_type"],
                        )
                        for item in mapping["constraints"]
                    ],
                )
            self.assertEqual(
                [
                    (relationship_type, lag)
                    for lag in (0, 2, -2)
                    for relationship_type in ("FS", "SS", "FF", "SF")
                ],
                observed_type_lag_pairs,
            )
            self.assertEqual("+08:00", index["coordinate_contract"]["utc_offset"])
            self.assertEqual("forbidden", index["coordinate_contract"]["rounding_policy"])

            runbook = (output / OPERATOR_RUNBOOK).read_text(encoding="utf-8")
            for heading in (
                "Track A — manual native semantic parity",
                "Track B — saved-file reopen/recalculate stability",
                "Track C — MSPDI adapter interchange",
                "Mandatory stop conditions and outcomes",
            ):
                self.assertIn(heading, runbook)
            self.assertIn("built-in **24 Hours**", runbook)
            self.assertIn("`preparation_blocked`", runbook)
            self.assertIn("Never edit the tracked deterministic kit", runbook)
            self.assertIn("Project 2010 MSPDI XML (`SaveVersion=14`)", runbook)
            self.assertIn("post-execution attestation", runbook)
            self.assertIn("`status_date`,\nwhich must remain null", runbook)
            self.assertIn("--prerequisite-manual-case-realization-manifest", runbook)
            self.assertIn("--stage-artifact native_calculated_file_sha256=", runbook)
            self.assertIn("--post-execution-action-log", runbook)
            self.assertIn("--evidence-artifact task_table=", runbook)
            self.assertNotIn("--independent-evidence", runbook)
            for role in (
                "native_pre_close_file_sha256",
                "native_pre_close_output_sha256",
                "native_reopened_file_sha256",
                "native_recalculated_file_sha256",
                "native_post_recalculate_output_sha256",
            ):
                self.assertIn(f"--stage-artifact {role}=", runbook)
            self.assertIn("file path; the analyser", runbook)
            environment = _json(output / OPERATOR_ENVIRONMENT_TEMPLATE)
            self.assertIn("product_name", environment)
            self.assertIn("Microsoft_Project_leveling_disabled_attestation", environment)
            self.assertIn("independent_verification_artifact_plan", environment)
            attestation = _json(output / POST_EXECUTION_ATTESTATION_TEMPLATE)
            self.assertIsNone(attestation["actual_native_execution"])
            self.assertIsNone(attestation["microsoft_project_desktop_opened"])
            self.assertEqual({}, attestation["stage_artifact_sha256_by_role"])
            self.assertIsNone(attestation["post_execution_action_log_sha256"])
            self.assertEqual(
                {}, attestation["independent_evidence_artifact_sha256_by_role"]
            )
            stop_template = _json(output / NATIVE_ATTEMPT_STOP_TEMPLATE)
            self.assertTrue(stop_template["template_only"])
            self.assertFalse(stop_template["is_attempt_stop_record"])
            self.assertFalse(stop_template["claim_evidence_eligible"])
            self.assertNotEqual(
                "microsoft-project-native-attempt-stop-record-v0.2",
                stop_template["schema_version"],
            )
            self.assertEqual(
                list(STOP_CONDITION_IDS),
                stop_template["allowed_stop_condition_ids"],
            )
            self.assertEqual(
                list(STOP_OUTCOME_CLASSIFICATIONS),
                stop_template["allowed_outcome_classifications"],
            )
            self.assertEqual(
                list(STOP_RECORD_REQUIRED_FIELDS),
                stop_template["actual_record_contract"][
                    "required_top_level_fields"
                ],
            )
            self.assertEqual(
                "microsoft-project-native-attempt-stop-record-v0.2",
                stop_template["actual_record_contract"]["schema_version"],
            )
            expected_outcome_rows = [
                {
                    "stop_condition_id": stop_condition_id,
                    "when_native_calculation_not_observed": outcomes.get(False),
                    "when_native_calculation_observed": outcomes.get(True),
                }
                for stop_condition_id, outcomes in (
                    (
                        stop_condition_id,
                        STOP_OUTCOME_BY_CONDITION_AND_NATIVE_CALCULATION[
                            stop_condition_id
                        ],
                    )
                    for stop_condition_id in STOP_CONDITION_IDS
                )
            ]
            self.assertEqual(
                expected_outcome_rows,
                stop_template[
                    "outcome_by_stop_condition_and_calculation_observation"
                ],
            )
            self.assertEqual(
                stop_template,
                _json(
                    output
                    / index["global_artifacts"][
                        "native_attempt_stop_instruction_template"
                    ]["relative_path"]
                ),
            )
            self.assertIn("record-msproject-native-attempt-stop", runbook)
            self.assertIn(
                "native_calculation_occurred_before_preexecution_freeze", runbook
            )
            self.assertIn("--observed-artifact native_file=", runbook)
            self.assertEqual(
                POST_EXECUTION_ACTION_IDS_BY_TRACK,
                NORMALIZER_POST_EXECUTION_ACTION_IDS_BY_TRACK,
            )
            for track_id, relative_path in (
                (
                    "manual_native_semantic_parity",
                    TRACK_A_POST_EXECUTION_ACTION_LOG_TEMPLATE,
                ),
                (
                    "saved_file_reopen_recalculate_stability",
                    TRACK_B_POST_EXECUTION_ACTION_LOG_TEMPLATE,
                ),
            ):
                action_template = _json(output / relative_path)
                self.assertEqual(track_id, action_template["execution_track_id"])
                self.assertEqual(
                    list(POST_EXECUTION_ACTION_IDS_BY_TRACK[track_id]),
                    [item["action_id"] for item in action_template["actions"]],
                )
                self.assertTrue(
                    all(
                        set(item)
                        == {
                            "sequence",
                            "action_id",
                            "action",
                            "performed_at",
                            "stage_artifact_roles",
                            "independent_evidence_roles",
                        }
                        for item in action_template["actions"]
                    )
                )
            mapping_register = _json(output / MAPPING_SOURCE_REGISTER)
            findings = {
                item["mapping_id"]: item
                for item in mapping_register["mapping_findings"]
            }
            self.assertEqual(
                APPLICATION_CALCULATION_OFFICIAL_URL,
                findings["manual-native-application-calculation-mode"][
                    "official_url"
                ],
            )
            self.assertEqual(
                [
                    PROJECT_SUMMARY_UID_OFFICIAL_URL,
                    TASK_ELEMENT_OFFICIAL_URL,
                    SUMMARY_ELEMENT_OFFICIAL_URL,
                    PROJECT_SUMMARY_VISIBILITY_OFFICIAL_URL,
                ],
                findings["optional-structural-project-summary-task"][
                    "official_urls"
                ],
            )
            self.assertIn(
                "unclaimed",
                findings["optional-structural-project-summary-task"]["status"],
            )
            manifest = _json(output / MANIFEST)
            runbook_entry = next(
                item for item in manifest["artifacts"] if item["relative_path"] == OPERATOR_RUNBOOK
            )
            self.assertEqual("text/markdown; charset=utf-8", runbook_entry["media_type"])

    def test_no_result_or_gate_claim_can_be_inferred_from_preparation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "pilot"
            summary = prepare_pilot(output, repository_root=ROOT)
            index = _json(output / PILOT_INDEX)
            complete_text = "\n".join(
                data.decode("utf-8") for data in _snapshot(output).values()
            )
        boundary = index["claim_boundary"]
        self.assertTrue(boundary["pilot_is_partial_profile_preparation"])
        self.assertEqual(12, boundary["pilot_case_count"])
        self.assertEqual(45, boundary["full_profile_claim_eligible_case_count"])
        for key in (
            "full_45_case_gate_satisfied",
            "native_execution_performed",
            "native_semantic_claim",
            "adapter_execution_performed",
            "adapter_interchange_claim",
            "full_microsoft_project_compatibility_claim",
            "optimizer_benchmark_performed",
            "optimizer_superiority_claim",
        ):
            self.assertFalse(boundary[key])
        self.assertFalse(summary["full_45_case_gate_satisfied"])
        self.assertNotIn('"executed_pass"', complete_text)

    def test_verify_requires_exact_path_and_byte_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "pilot"
            prepared = prepare_pilot(output, repository_root=ROOT)
            verified = verify_pilot(output, repository_root=ROOT)
            self.assertFalse(prepared["verified"])
            self.assertTrue(verified["verified"])
            self.assertEqual(
                prepared["pilot_kit_manifest_sha256"],
                verified["pilot_kit_manifest_sha256"],
            )
            path = (
                output
                / "tracks"
                / "saved_file_reopen_recalculate_stability"
                / "case-protocols"
                / "SEM-REL-001.json"
            )
            path.write_bytes(path.read_bytes() + b" ")
            with self.assertRaises(PilotVerificationError):
                verify_pilot(output, repository_root=ROOT)

    def test_output_ownership_rejects_unowned_unexpected_and_symlink_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            unowned = base / "unowned"
            unowned.mkdir()
            (unowned / "keep.txt").write_text("unrelated", encoding="utf-8")
            with self.assertRaises(PilotSafetyError):
                prepare_pilot(unowned, repository_root=ROOT)
            self.assertEqual("unrelated", (unowned / "keep.txt").read_text(encoding="utf-8"))

            owned = base / "owned"
            prepare_pilot(owned, repository_root=ROOT)
            (owned / "unrelated.txt").write_text("keep", encoding="utf-8")
            with self.assertRaises(PilotSafetyError):
                prepare_pilot(owned, repository_root=ROOT)
            self.assertEqual("keep", (owned / "unrelated.txt").read_text(encoding="utf-8"))

            if hasattr(os, "symlink"):
                target = base / "target"
                target.mkdir()
                link = base / "link"
                link.symlink_to(target, target_is_directory=True)
                with self.assertRaises(PilotSafetyError):
                    prepare_pilot(link, repository_root=ROOT)

    def test_bindings_are_checked_before_output_is_created(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            copied_root = base / "repository"
            for relative_path in (PREREGISTRATION_PATH, PROFILE_PATH):
                destination = copied_root / relative_path
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / relative_path, destination)
            for case_id in CASE_IDS:
                relative_path = Path("benchmarks/semantic/cases") / f"{case_id.lower()}.json"
                destination = copied_root / relative_path
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / relative_path, destination)
            fixture = copied_root / "benchmarks/semantic/cases/sem-rel-006.json"
            fixture.write_bytes(fixture.read_bytes() + b"\n")
            output = base / "must-not-be-created"
            with self.assertRaises(PilotBindingError):
                prepare_pilot(output, repository_root=copied_root)
            self.assertFalse(output.exists())

    def test_three_fresh_processes_produce_byte_identical_kits(self) -> None:
        program = (
            "from pathlib import Path; import sys; "
            "from deterministic_scheduling_core.native.msproject.pilot import prepare_pilot; "
            "prepare_pilot(Path(sys.argv[1]), repository_root=Path(sys.argv[2]))"
        )
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            outputs: list[Path] = []
            environment = dict(os.environ)
            existing_pythonpath = environment.get("PYTHONPATH")
            environment["PYTHONPATH"] = str(ROOT / "src") + (
                os.pathsep + existing_pythonpath if existing_pythonpath else ""
            )
            for number in range(3):
                output = base / f"run-{number}"
                subprocess.run(
                    [sys.executable, "-c", program, str(output), str(ROOT)],
                    cwd=ROOT,
                    env=environment,
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                outputs.append(output)
            first = _snapshot(outputs[0])
            self.assertEqual(first, _snapshot(outputs[1]))
            self.assertEqual(first, _snapshot(outputs[2]))


if __name__ == "__main__":
    unittest.main()
