from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from deterministic_scheduling_core.canonical.frozen_suite import (
    EXPECTED_FIXTURE_SHA256_BY_FILENAME,
)
from deterministic_scheduling_core.native.msproject.freeze import (
    INDEPENDENT_VERIFICATION_EVIDENCE_ROLES,
    NativeEvidenceError,
    PILOT_ID,
    PRE_EXECUTION_ACTION_IDS,
    REQUIRED_ENVIRONMENT_FIELDS,
    freeze_msproject_native_input,
    read_regular_file_snapshot,
    validate_case_realisation_manifest_against_repository,
    validate_case_realisation_manifest,
)
from deterministic_scheduling_core.native.msproject.normalizer import (
    MSPDI_NAMESPACE,
    NativeOutputError,
    POST_EXECUTION_ACTION_IDS_BY_TRACK,
    _release_tracked_sealed_expected,
    _validate_post_execution_action_log,
    _hash_independent_evidence_artifacts,
    _hash_stage_artifacts,
    _snapshot_stage_artifacts,
    analyse_msproject_native_output,
    compare_normalized_output,
    normalize_mspdi_output,
    validate_native_run_record,
)
from deterministic_scheduling_core.native.msproject.stopped import (
    STOP_RECORD_REQUIRED_FIELDS,
    NativeAttemptStopError,
    record_msproject_native_attempt_stop,
)
from deterministic_scheduling_core.provenance.canonical_json import (
    canonical_text,
    write_canonical_json,
)


def _raw_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class MicrosoftProjectFreezeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "native-validation/preregistrations").mkdir(parents=True)
        (self.root / "native-validation/profiles").mkdir(parents=True)
        (self.root / "benchmarks/semantic/cases").mkdir(parents=True)
        self.preregistration = (
            self.root
            / "native-validation/preregistrations/microsoft-project-semantic-microcases-v0.1.json"
        )
        self.profile = (
            self.root
            / "native-validation/profiles/microsoft-project-semantic-comparison-profile-v0.1.json"
        )
        self.fixture = self.root / "benchmarks/semantic/cases/sem-rel-001.json"
        self.preregistration.write_bytes(b'{"frozen":"preregistration"}\n')
        self.profile.write_bytes(b'{"frozen":"profile"}\n')
        self.fixture.write_bytes(b'{"case_id":"SEM-REL-001"}\n')
        self.source_projection = (
            self.root
            / "native-validation/pilot-kits/microsoft-project-relationship-v0.1/"
            "source-only-case-projections/SEM-REL-001.json"
        )
        self.source_projection.parent.mkdir(parents=True)
        write_canonical_json(
            self.source_projection,
            {"case_id": "SEM-REL-001", "source_only": True},
        )
        self.native_input = self.root / "native-input.mpp"
        self.native_input.write_bytes(
            b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1synthetic opaque pre-calculation test bytes"
        )
        self.sealed_expected = (
            self.root
            / "native-validation/pilot-kits/microsoft-project-relationship-v0.1/"
            "sealed-expected-normalized/SEM-REL-001.json"
        )
        self.sealed_expected.parent.mkdir(parents=True)
        write_canonical_json(
            self.sealed_expected,
            {
                "pilot_id": PILOT_ID,
                "case_id": "SEM-REL-001",
                "fixture_raw_sha256": EXPECTED_FIXTURE_SHA256_BY_FILENAME[
                    "sem-rel-001.json"
                ],
                "fixture_path": "benchmarks/semantic/cases/sem-rel-001.json",
                "source_bindings": {
                    "preregistration": {
                        "preregistration_id": "microsoft-project-semantic-microcases-v0.1",
                        "relative_path": str(self.preregistration.relative_to(self.root)),
                        "raw_sha256": _raw_sha(self.preregistration),
                    },
                    "comparison_profile": {
                        "profile_id": "microsoft-project-semantic-comparison-profile-v0.1",
                        "relative_path": str(self.profile.relative_to(self.root)),
                        "raw_sha256": _raw_sha(self.profile),
                    },
                    "fixture": {
                        "case_id": "SEM-REL-001",
                        "path": "benchmarks/semantic/cases/sem-rel-001.json",
                        "relative_path": "benchmarks/semantic/cases/sem-rel-001.json",
                        "raw_sha256": EXPECTED_FIXTURE_SHA256_BY_FILENAME[
                            "sem-rel-001.json"
                        ],
                    },
                },
                "expected_normalized": {
                    "activity_times": {
                        "A": {"start": 0, "finish": 4},
                        "B": {"start": 4, "finish": 7},
                    },
                    "project_finish": 7,
                },
            },
        )
        self.environment_path = self.root / "environment.json"
        self.environment = self._environment()
        write_canonical_json(self.environment_path, self.environment)
        self.pilot_index = self._pilot_index()
        self.pilot_index_path = (
            self.root
            / "native-validation/pilot-kits/microsoft-project-relationship-v0.1/"
            "pilot-index.json"
        )
        write_canonical_json(self.pilot_index_path, self.pilot_index)
        self.sealed_control_path = self.sealed_expected.parent / "sealed-control-index.json"
        self._write_sealed_control()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _environment(self) -> dict[str, object]:
        evidence_by_action = {
            "capture_product_environment": ["project_information"],
            "configure_calculation_and_schedule_direction": [
                "project_information",
                "resource_leveling_status",
            ],
            "verify_continuous_calendar": ["calendar_working_time"],
            "construct_and_verify_tasks": [
                "task_table",
                "task_mode_type_effort",
            ],
            "construct_and_verify_relationships_and_constraints": [
                "predecessor_details"
            ],
            "independent_pre_execution_review": list(
                INDEPENDENT_VERIFICATION_EVIDENCE_ROLES
            ),
        }
        actions = [
            {
                "sequence": sequence,
                "action_id": action_id,
                "stage": "pre_execution",
                "action": f"test-only completion of {action_id}",
                "performed_by": (
                    "reviewer-002"
                    if action_id == "independent_pre_execution_review"
                    else "operator-001"
                ),
                "performed_at": f"2026-08-26T09:0{sequence}:00+08:00",
                "evidence_roles": evidence_by_action[action_id],
            }
            for sequence, action_id in enumerate(PRE_EXECUTION_ACTION_IDS, start=1)
        ]
        progress_options = {
            "source_case_has_progress": False,
            "capture_complete_attestation": True,
            "native_displayed_settings": [
                {
                    "setting_name": "synthetic parser-test progress option",
                    "displayed_value": "disabled",
                }
            ],
        }
        relationship_settings = {
            "R1": {
                "predecessor_activity_id": "A",
                "successor_activity_id": "B",
                "canonical_type": "FS",
                "signed_lag_hours": 0,
                "native_type": 1,
                "native_link_lag_tenths_minutes": 0,
                "native_lag_format": 5,
            }
        }
        observed_required_values = {
            "project_calendar_settings": {
                "canonical_calendar_id": "CAL-24X7",
                "native_calendar_name": "24 Hours",
                "continuous_working_time_verified": True,
            },
            "task_duration_hours_per_task": {"A": 4, "B": 3},
            "task_calendar_per_task": {"A": "24 Hours", "B": "24 Hours"},
            "task_scheduling_mode_per_task": {
                "A": "automatically_scheduled",
                "B": "automatically_scheduled",
            },
            "task_type_per_task": {"A": "fixed_duration", "B": "fixed_duration"},
            "effort_driven_per_task": {"A": False, "B": False},
            "relationship_and_lag_settings": relationship_settings,
            "constraint_settings": {},
            "project_start": "2026-01-05T08:00:00+08:00",
            "status_date": None,
            "schedule_from_start": True,
            "calculation_mode": "manual",
            "resource_leveling_status": "disabled_and_not_run",
        }
        observed_product_settings = {
            setting_id: {
                "required_value": required_value,
                "observed_value": required_value,
                "observed_at": "2026-08-26T09:07:00+08:00",
                "observed_by": "operator-001",
                "independently_verified_at": "2026-08-26T09:08:00+08:00",
                "independently_verified_by": "reviewer-002",
            }
            for setting_id, required_value in observed_required_values.items()
        }
        document: dict[str, object] = {
            "product_name": "Microsoft Project",
            "edition": "Desktop test edition",
            "version": "test-version",
            "build": "test-build",
            "operating_system": "Windows test fixture",
            "machine_architecture": "x86_64",
            "machine_time_zone": "Australia/Perth",
            "locale": "en-AU",
            "execution_operator_id": "operator-001",
            "independent_reviewer_id": "reviewer-002",
            "native_file_format": "mpp",
            "native_file_hashes_by_stage": {
                "native_source_file_sha256": _raw_sha(self.native_input)
            },
            "native_source_file_format": "mpp",
            "native_source_file_sha256": _raw_sha(self.native_input),
            "observed_native_activity_mapping": [
                {
                    "activity_id": "A",
                    "native_task_id": 1,
                    "native_task_uid": 1,
                    "native_task_name": "A",
                },
                {
                    "activity_id": "B",
                    "native_task_id": 2,
                    "native_task_uid": 2,
                    "native_task_name": "B",
                },
            ],
            "observed_product_settings": observed_product_settings,
            "Microsoft_Project_project_calendar_and_scheduling_options": {
                "project_calendar_settings": {
                    "canonical_calendar_id": "CAL-24X7",
                    "native_calendar_name": "24 Hours",
                    "continuous_working_time_verified": True,
                },
                "calculation_mode": "manual",
                "schedule_from_start": True,
            },
            "Microsoft_Project_task_calendars": {"A": "24 Hours", "B": "24 Hours"},
            "Microsoft_Project_resource_calendars_and_capacities": {},
            "Microsoft_Project_task_scheduling_mode_type_and_effort_driven_fields": {
                "A": {
                    "task_scheduling_mode": "automatically_scheduled",
                    "task_type": "fixed_duration",
                    "effort_driven": False,
                },
                "B": {
                    "task_scheduling_mode": "automatically_scheduled",
                    "task_type": "fixed_duration",
                    "effort_driven": False,
                },
            },
            "Microsoft_Project_relationship_and_lag_settings": relationship_settings,
            "Microsoft_Project_constraint_settings": {},
            "Microsoft_Project_project_start_and_status_date": {
                "project_start": "2026-01-05T08:00:00+08:00",
                "status_date": None,
            },
            "Microsoft_Project_calculation_and_progress_rescheduling_options": {
                "calculation_mode": "manual",
                "precalculation_protocol_state": "constructed_not_calculated",
                "progress_rescheduling_options": progress_options,
            },
            "Microsoft_Project_leveling_disabled_attestation": True,
            "manual_actions_by_stage": actions,
            "project_calendar_settings": {
                "canonical_calendar_id": "CAL-24X7",
                "native_calendar_name": "24 Hours",
                "continuous_working_time_verified": True,
            },
            "task_calendar_per_task": {"A": "24 Hours", "B": "24 Hours"},
            "resource_calendar_and_capacity_per_assignment": {},
            "task_scheduling_mode_per_task": {
                "A": "automatically_scheduled",
                "B": "automatically_scheduled",
            },
            "task_type_per_task": {"A": "fixed_duration", "B": "fixed_duration"},
            "effort_driven_per_task": {"A": False, "B": False},
            "relationship_and_lag_settings": relationship_settings,
            "constraint_settings": {},
            "project_start": "2026-01-05T08:00:00+08:00",
            "status_date": None,
            "schedule_from_start": True,
            "calculation_mode": "manual",
            "precalculation_protocol_state": "constructed_not_calculated",
            "progress_rescheduling_options": progress_options,
            "resource_leveling_status": "disabled_and_not_run",
            "manual_construction_actions": actions,
            "manual_action_log_complete_attestation": True,
            "independent_verification_artifact_plan": [
                {
                    "role": role,
                    "planned_evidence_type": "screenshot",
                    "description": f"synthetic test-only plan for {role}",
                }
                for role in INDEPENDENT_VERIFICATION_EVIDENCE_ROLES
            ],
        }
        self.assertTrue(set(REQUIRED_ENVIRONMENT_FIELDS).issubset(document))
        return document

    def _pilot_index(self) -> dict[str, object]:
        return {
            "schema_version": "msproject-relationship-pilot-index-v0.1",
            "pilot_id": PILOT_ID,
            "status": "prepared_not_executed",
            "pilot_input_identity": {"sha256": "1" * 64},
            "case_ids": ["SEM-REL-001"],
            "execution_track_ids": [
                "manual_native_semantic_parity",
                "saved_file_reopen_recalculate_stability",
                "adapter_interchange_round_trip",
            ],
            "bindings": {
                "preregistration": {
                    "preregistration_id": "microsoft-project-semantic-microcases-v0.1",
                    "relative_path": str(self.preregistration.relative_to(self.root)),
                    "raw_sha256": _raw_sha(self.preregistration),
                },
                "comparison_profile": {
                    "profile_id": "microsoft-project-semantic-comparison-profile-v0.1",
                    "relative_path": str(self.profile.relative_to(self.root)),
                    "raw_sha256": _raw_sha(self.profile),
                },
            },
            "coordinate_contract": {
                "canonical_origin": "2026-01-05T08:00:00+08:00",
                "canonical_unit": "hour",
                "schedule_time_zone": "Australia/Perth",
                "utc_offset": "+08:00",
                "timestamp_tolerance_seconds": 0,
                "rounding_policy": "forbidden",
            },
            "cases": [
                {
                    "case_id": "SEM-REL-001",
                    "adapter_preparation_status": "prepared_not_executed",
                    "source_only_case_projection": {
                        "relative_path": str(
                            self.source_projection.relative_to(self.root)
                        ),
                        "raw_sha256": _raw_sha(self.source_projection),
                    },
                    "native_mapping": {
                        "activities": [
                            {
                                "activity_id": "A",
                                "native_task_uid": 1,
                                "native_task_id": 1,
                                "native_task_name": "A",
                                "canonical_duration_hours": 4,
                                "canonical_calendar_id": "CAL-24X7",
                            },
                            {
                                "activity_id": "B",
                                "native_task_uid": 2,
                                "native_task_id": 2,
                                "native_task_name": "B",
                                "canonical_duration_hours": 3,
                                "canonical_calendar_id": "CAL-24X7",
                            },
                        ],
                        "calendars": [{"canonical_calendar_id": "CAL-24X7", "native_uid": 1}],
                        "relationships": [
                            {
                                "relationship_id": "R1",
                                "predecessor_activity_id": "A",
                                "successor_activity_id": "B",
                                "canonical_type": "FS",
                                "canonical_signed_lag_hours": 0,
                                "native_type": 1,
                                "native_link_lag_tenths_minutes": 0,
                                "native_lag_format": 5,
                            }
                        ],
                        "constraints": [],
                        "progress": [],
                        "project_settings": {
                            "schedule_from_start": True,
                            "new_tasks_are_manual": False,
                            "task_pinned": 0,
                            "task_type": "fixed_duration",
                            "effort_driven": False,
                            "resource_leveling": "disabled_and_not_run",
                        },
                    },
                }
            ],
        }

    def _write_sealed_control(self) -> None:
        write_canonical_json(
            self.sealed_control_path,
            {
                "document_type": "microsoft_project_sealed_comparison_control_index",
                "schema_version": "microsoft-project-sealed-control-index-v0.1",
                "pilot_id": PILOT_ID,
                "status": "sealed_until_post_observation_release",
                "ordered_case_ids": ["SEM-REL-001"],
                "operator_pilot_index_binding": {
                    "raw_sha256": _raw_sha(self.pilot_index_path),
                    "canonical_sha256": hashlib.sha256(
                        canonical_text(self.pilot_index).encode("utf-8")
                    ).hexdigest(),
                    "pilot_input_identity_sha256": "1" * 64,
                },
                "protocol_bindings": self.pilot_index["bindings"],
                "cases": [
                    {
                        "case_id": "SEM-REL-001",
                        "sealed_expected_raw_sha256": _raw_sha(self.sealed_expected),
                        "sealed_expected_byte_size": self.sealed_expected.stat().st_size,
                        "source_only_projection_raw_sha256": _raw_sha(
                            self.source_projection
                        ),
                        "frozen_fixture_raw_sha256": (
                            EXPECTED_FIXTURE_SHA256_BY_FILENAME["sem-rel-001.json"]
                        ),
                    }
                ],
                "release_policy": {
                    "allowed_execution_track_id": "manual_native_semantic_parity",
                    "normalized_observation_must_be_durably_written_and_hash_verified": True,
                    "operator_and_pre_execution_reviewer_access": "prohibited",
                    "caller_selected_control_or_seal_path": "forbidden",
                },
            },
        )

    def _freeze(self, output_name: str = "frozen"):
        return freeze_msproject_native_input(
            repository_root=self.root,
            pilot_index=self.pilot_index,
            pilot_id=PILOT_ID,
            case_id="SEM-REL-001",
            track_id="manual_native_semantic_parity",
            native_file=self.native_input,
            environment_capture_path=self.environment_path,
            output_dir=self.root / output_name,
            prepared_at="2026-08-26T10:00:00+08:00",
            prepared_by="operator-001",
            independent_pre_execution_reviewed_by="reviewer-002",
            attestation_no_native_result_observed_before_freeze=True,
        )

    def _retained_adapter_manifest(self, output_name: str) -> dict[str, object]:
        """Model retained Track-C bytes without going through adapter freeze."""

        manifest = json.loads(json.dumps(self._freeze(output_name).manifest))
        environment = json.loads(json.dumps(self.environment))
        environment["native_file_format"] = "mspdi_xml"
        environment["native_source_file_format"] = "mspdi_xml"
        write_canonical_json(self.environment_path, environment)
        manifest["execution_track_id"] = "adapter_interchange_round_trip"
        manifest["native_source_file_format"] = "mspdi_xml"
        manifest["captured_product_environment"] = environment
        manifest["environment_capture_sha256"] = _raw_sha(self.environment_path)
        validate_case_realisation_manifest_against_repository(
            repository_root=self.root,
            document=manifest,
            environment_capture_path=self.environment_path,
        )
        return manifest

    def _bind_manifest_to_current_pilot_index(
        self, manifest: dict[str, object]
    ) -> None:
        write_canonical_json(self.pilot_index_path, self.pilot_index)
        manifest["pilot_index_raw_sha256"] = _raw_sha(self.pilot_index_path)
        manifest["pilot_index_canonical_sha256"] = hashlib.sha256(
            canonical_text(self.pilot_index).encode("utf-8")
        ).hexdigest()

    def test_freeze_hashes_input_and_writes_only_metadata(self) -> None:
        result = self._freeze()
        self.assertEqual(result.manifest["native_source_file_sha256"], _raw_sha(self.native_input))
        self.assertEqual(
            result.manifest["fixture_raw_sha256"],
            EXPECTED_FIXTURE_SHA256_BY_FILENAME["sem-rel-001.json"],
        )
        self.assertEqual(
            result.manifest["source_only_projection_raw_sha256"],
            _raw_sha(self.source_projection),
        )
        manifest_text = result.manifest_path.read_text(encoding="utf-8")
        self.assertNotIn("sealed-expected-normalized", manifest_text)
        self.assertNotIn("benchmarks/semantic/cases", manifest_text)
        self.assertEqual(result.manifest_sha256, _raw_sha(result.manifest_path))
        self.assertFalse(result.manifest["raw_native_file_embedded"])
        self.assertEqual(
            {path.name for path in result.manifest_path.parent.iterdir()},
            {".dsc-msproject-native-evidence-owner.json", "case-realisation-manifest.json"},
        )
        self.assertNotIn(str(self.native_input), result.manifest_path.read_text(encoding="utf-8"))

    def test_freeze_refuses_overwrite_and_non_owned_directory(self) -> None:
        self._freeze()
        with self.assertRaisesRegex(NativeEvidenceError, "never overwritten"):
            self._freeze()
        nonempty = self.root / "nonempty"
        nonempty.mkdir()
        (nonempty / "unrelated.txt").write_text("keep", encoding="utf-8")
        with self.assertRaisesRegex(NativeEvidenceError, "must be empty"):
            self._freeze("nonempty")
        self.assertEqual((nonempty / "unrelated.txt").read_text(encoding="utf-8"), "keep")

    def test_freeze_refuses_symlink_output(self) -> None:
        target = self.root / "target"
        target.mkdir()
        link = self.root / "linked-output"
        try:
            link.symlink_to(target, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"symlinks unavailable: {exc}")
        with self.assertRaisesRegex(NativeEvidenceError, "symbolic"):
            self._freeze("linked-output")

    def test_freeze_requires_distinct_identities_and_attestation(self) -> None:
        with self.assertRaisesRegex(NativeEvidenceError, "identities must differ"):
            freeze_msproject_native_input(
                repository_root=self.root,
                pilot_index=self.pilot_index,
                pilot_id=PILOT_ID,
                case_id="SEM-REL-001",
                track_id="manual_native_semantic_parity",
                native_file=self.native_input,
                environment_capture_path=self.environment_path,
                output_dir=self.root / "same-identities",
                prepared_at="2026-08-26T10:00:00+08:00",
                prepared_by="operator-001",
                independent_pre_execution_reviewed_by="operator-001",
                attestation_no_native_result_observed_before_freeze=True,
            )
        with self.assertRaisesRegex(NativeEvidenceError, "attestation must be true"):
            freeze_msproject_native_input(
                repository_root=self.root,
                pilot_index=self.pilot_index,
                pilot_id=PILOT_ID,
                case_id="SEM-REL-001",
                track_id="manual_native_semantic_parity",
                native_file=self.native_input,
                environment_capture_path=self.environment_path,
                output_dir=self.root / "false-attestation",
                prepared_at="2026-08-26T10:00:00+08:00",
                prepared_by="operator-001",
                independent_pre_execution_reviewed_by="reviewer-002",
                attestation_no_native_result_observed_before_freeze=False,
            )

    def test_freeze_rejects_binding_mutation(self) -> None:
        self.source_projection.write_bytes(b'{"case_id":"SEM-REL-MUTATED"}\n')
        with self.assertRaisesRegex(NativeEvidenceError, "source-only projection raw hash"):
            self._freeze("mutated-fixture")

    def test_freeze_rejects_an_index_other_than_the_tracked_kit_index(self) -> None:
        supplied = json.loads(json.dumps(self.pilot_index))
        supplied["cases"][0]["native_mapping"]["relationships"][0][
            "native_link_lag_tenths_minutes"
        ] = 600
        with self.assertRaisesRegex(NativeEvidenceError, "does not equal the tracked"):
            freeze_msproject_native_input(
                repository_root=self.root,
                pilot_index=supplied,
                pilot_id=PILOT_ID,
                case_id="SEM-REL-001",
                track_id="manual_native_semantic_parity",
                native_file=self.native_input,
                environment_capture_path=self.environment_path,
                output_dir=self.root / "altered-index",
                prepared_at="2026-08-26T10:00:00+08:00",
                prepared_by="operator-001",
                independent_pre_execution_reviewed_by="reviewer-002",
                attestation_no_native_result_observed_before_freeze=True,
            )

    def test_freeze_rejects_noncanonical_or_incomplete_environment(self) -> None:
        self.environment_path.write_text(json.dumps(self.environment, indent=2), encoding="utf-8")
        with self.assertRaisesRegex(NativeEvidenceError, "canonical JSON"):
            self._freeze("pretty-environment")
        incomplete = dict(self.environment)
        incomplete.pop("build")
        write_canonical_json(self.environment_path, incomplete)
        with self.assertRaisesRegex(NativeEvidenceError, "missing required fields"):
            self._freeze("incomplete-environment")

    def test_freeze_rejects_leveling_or_native_hash_mismatch(self) -> None:
        self.environment["resource_leveling_status"] = "enabled"
        write_canonical_json(self.environment_path, self.environment)
        with self.assertRaisesRegex(NativeEvidenceError, "resource_leveling_status"):
            self._freeze("leveling-enabled")
        self.environment["resource_leveling_status"] = "disabled_and_not_run"
        self.environment["native_source_file_sha256"] = "0" * 64
        write_canonical_json(self.environment_path, self.environment)
        with self.assertRaisesRegex(NativeEvidenceError, "does not match the input"):
            self._freeze("native-hash-mismatch")

    def test_freeze_rejects_placeholders_wrong_zone_and_post_result_stage_hashes(self) -> None:
        self.environment["project_calendar_settings"] = None
        write_canonical_json(self.environment_path, self.environment)
        with self.assertRaisesRegex(NativeEvidenceError, "project_calendar_settings"):
            self._freeze("null-calendar")

        self.environment = self._environment()
        self.environment["machine_time_zone"] = "UTC"
        write_canonical_json(self.environment_path, self.environment)
        with self.assertRaisesRegex(NativeEvidenceError, "frozen schedule time zone"):
            self._freeze("wrong-time-zone")

        self.environment = self._environment()
        self.environment["native_file_hashes_by_stage"][
            "native_calculated_file_sha256"
        ] = "0" * 64
        write_canonical_json(self.environment_path, self.environment)
        with self.assertRaisesRegex(NativeEvidenceError, "must contain only"):
            self._freeze("post-result-stage-hash")

    def test_adapter_freeze_refuses_preparation_blocked_case(self) -> None:
        self.pilot_index["cases"][0]["adapter_preparation_status"] = "preparation_blocked"
        self.pilot_index["cases"][0]["adapter_preparation_blocked_reason"] = (
            "CAL-24X7 MSPDI representation is unresolved"
        )
        write_canonical_json(self.pilot_index_path, self.pilot_index)
        self.environment["native_file_format"] = "mspdi_xml"
        self.environment["native_source_file_format"] = "mspdi_xml"
        write_canonical_json(self.environment_path, self.environment)
        with self.assertRaisesRegex(NativeEvidenceError, "CAL-24X7"):
            freeze_msproject_native_input(
                repository_root=self.root,
                pilot_index=self.pilot_index,
                pilot_id=PILOT_ID,
                case_id="SEM-REL-001",
                track_id="adapter_interchange_round_trip",
                native_file=self.native_input,
                environment_capture_path=self.environment_path,
                output_dir=self.root / "blocked-adapter",
                prepared_at="2026-08-26T10:00:00+08:00",
                prepared_by="operator-001",
                independent_pre_execution_reviewed_by="reviewer-002",
                attestation_no_native_result_observed_before_freeze=True,
            )

    def test_adapter_freeze_also_enforces_top_level_blocker(self) -> None:
        self.pilot_index["execution_track_ids"] = [
            "manual_native_semantic_parity",
            "saved_file_reopen_recalculate_stability",
            "adapter_interchange_round_trip",
        ]
        self.pilot_index["execution_tracks"] = [
            {"track_id": "manual_native_semantic_parity", "preparation_status": "prepared"},
            {
                "track_id": "saved_file_reopen_recalculate_stability",
                "preparation_status": "prepared",
            },
            {
                "track_id": "adapter_interchange_round_trip",
                "adapter_preparation_status": "preparation_blocked",
            },
        ]
        self.pilot_index["cases"][0]["adapter_preparation_status"] = "prepared"
        write_canonical_json(self.pilot_index_path, self.pilot_index)
        self.environment["native_file_format"] = "mspdi_xml"
        self.environment["native_source_file_format"] = "mspdi_xml"
        write_canonical_json(self.environment_path, self.environment)
        with self.assertRaisesRegex(NativeEvidenceError, "adapter preparation.*blocked"):
            freeze_msproject_native_input(
                repository_root=self.root,
                pilot_index=self.pilot_index,
                pilot_id=PILOT_ID,
                case_id="SEM-REL-001",
                track_id="adapter_interchange_round_trip",
                native_file=self.native_input,
                environment_capture_path=self.environment_path,
                output_dir=self.root / "top-level-blocked-adapter",
                prepared_at="2026-08-26T10:00:00+08:00",
                prepared_by="operator-001",
                independent_pre_execution_reviewed_by="reviewer-002",
                attestation_no_native_result_observed_before_freeze=True,
            )

    def test_reopen_track_requires_and_binds_the_same_manual_realization(self) -> None:
        manual = self._freeze("manual-prerequisite")
        with self.assertRaisesRegex(NativeEvidenceError, "requires the prerequisite"):
            freeze_msproject_native_input(
                repository_root=self.root,
                pilot_index=self.pilot_index,
                pilot_id=PILOT_ID,
                case_id="SEM-REL-001",
                track_id="saved_file_reopen_recalculate_stability",
                native_file=self.native_input,
                environment_capture_path=self.environment_path,
                output_dir=self.root / "reopen-without-prerequisite",
                prepared_at="2026-08-26T10:01:00+08:00",
                prepared_by="operator-001",
                independent_pre_execution_reviewed_by="reviewer-002",
                attestation_no_native_result_observed_before_freeze=True,
            )
        reopened = freeze_msproject_native_input(
            repository_root=self.root,
            pilot_index=self.pilot_index,
            pilot_id=PILOT_ID,
            case_id="SEM-REL-001",
            track_id="saved_file_reopen_recalculate_stability",
            native_file=self.native_input,
            environment_capture_path=self.environment_path,
            output_dir=self.root / "reopen-with-prerequisite",
            prerequisite_manual_case_realization_manifest_path=manual.manifest_path,
            prepared_at="2026-08-26T10:01:00+08:00",
            prepared_by="operator-001",
            independent_pre_execution_reviewed_by="reviewer-002",
            attestation_no_native_result_observed_before_freeze=True,
        )
        self.assertEqual(
            _raw_sha(manual.manifest_path),
            reopened.manifest[
                "prerequisite_manual_case_realization_manifest_sha256"
            ],
        )

    def test_freeze_requires_exact_observed_native_activity_mapping(self) -> None:
        self.environment["observed_native_activity_mapping"][1]["native_task_uid"] = 9
        write_canonical_json(self.environment_path, self.environment)
        with self.assertRaisesRegex(NativeEvidenceError, "observed native identity"):
            self._freeze("changed-observed-uid")

        self.environment = self._environment()
        self.environment["observed_native_activity_mapping"][1]["native_task_name"] = "renamed"
        write_canonical_json(self.environment_path, self.environment)
        with self.assertRaisesRegex(NativeEvidenceError, "observed native identity"):
            self._freeze("changed-observed-name")

        self.environment = self._environment()
        self.environment["observed_native_activity_mapping"].pop()
        write_canonical_json(self.environment_path, self.environment)
        with self.assertRaisesRegex(NativeEvidenceError, "cover every planned activity"):
            self._freeze("missing-observed-activity")

    def test_freeze_requires_operator_observed_settings_not_prefilled_plans(self) -> None:
        for record in self.environment["observed_product_settings"].values():
            record["observed_value"] = None
            record["observed_at"] = None
            record["observed_by"] = None
            record["independently_verified_at"] = None
            record["independently_verified_by"] = None
        write_canonical_json(self.environment_path, self.environment)
        with self.assertRaisesRegex(
            NativeEvidenceError, "observed_value is incomplete or mismatched"
        ):
            self._freeze("prefilled-plan-is-not-observation")

    def test_freeze_requires_chronological_pre_execution_actions_before_freeze(self) -> None:
        actions = self.environment["manual_actions_by_stage"]
        actions[0]["performed_at"], actions[1]["performed_at"] = (
            actions[1]["performed_at"],
            actions[0]["performed_at"],
        )
        write_canonical_json(self.environment_path, self.environment)
        with self.assertRaisesRegex(NativeEvidenceError, "strictly chronological"):
            self._freeze("out-of-order-actions")

        self.environment = self._environment()
        self.environment["manual_actions_by_stage"][-1]["performed_at"] = (
            "2026-08-26T10:01:00+08:00"
        )
        write_canonical_json(self.environment_path, self.environment)
        with self.assertRaisesRegex(NativeEvidenceError, "must not be after prepared_at"):
            self._freeze("post-freeze-action")

    def test_freeze_requires_structured_complete_actions_progress_and_evidence(self) -> None:
        self.environment["manual_actions_by_stage"][0] = None
        self.environment["manual_construction_actions"] = self.environment[
            "manual_actions_by_stage"
        ]
        write_canonical_json(self.environment_path, self.environment)
        with self.assertRaisesRegex(NativeEvidenceError, "each manual action"):
            self._freeze("malformed-actions")

        self.environment = self._environment()
        self.environment["independent_verification_artifact_plan"].pop()
        write_canonical_json(self.environment_path, self.environment)
        with self.assertRaisesRegex(NativeEvidenceError, "every exact evidence role"):
            self._freeze("missing-evidence-role")

        self.environment = self._environment()
        self.environment["progress_rescheduling_options"] = {}
        self.environment[
            "Microsoft_Project_calculation_and_progress_rescheduling_options"
        ]["progress_rescheduling_options"] = {}
        write_canonical_json(self.environment_path, self.environment)
        with self.assertRaisesRegex(NativeEvidenceError, "exact reviewed capture fields"):
            self._freeze("empty-progress-options")

    def test_freeze_separates_schedule_calculation_mode_and_protocol_state(self) -> None:
        self.environment["schedule_from_start"] = False
        self.environment["Microsoft_Project_project_calendar_and_scheduling_options"][
            "schedule_from_start"
        ] = False
        write_canonical_json(self.environment_path, self.environment)
        with self.assertRaisesRegex(NativeEvidenceError, "schedule_from_start must be true"):
            self._freeze("schedule-from-finish")

        self.environment = self._environment()
        self.environment["calculation_mode"] = "automatic"
        self.environment["Microsoft_Project_project_calendar_and_scheduling_options"][
            "calculation_mode"
        ] = "automatic"
        self.environment[
            "Microsoft_Project_calculation_and_progress_rescheduling_options"
        ]["calculation_mode"] = "automatic"
        write_canonical_json(self.environment_path, self.environment)
        with self.assertRaisesRegex(NativeEvidenceError, "manual mode"):
            self._freeze("automatic-calculation")

        self.environment = self._environment()
        self.environment["precalculation_protocol_state"] = "already_calculated"
        self.environment[
            "Microsoft_Project_calculation_and_progress_rescheduling_options"
        ]["precalculation_protocol_state"] = "already_calculated"
        write_canonical_json(self.environment_path, self.environment)
        with self.assertRaisesRegex(NativeEvidenceError, "constructed_not_calculated"):
            self._freeze("already-calculated")

    def test_reopen_prerequisite_rejects_partial_forgery_and_changed_environment(self) -> None:
        manual = self._freeze("strict-manual-prerequisite")
        forged_path = self.root / "forged-prerequisite.json"
        write_canonical_json(
            forged_path,
            {
                "schema_version": "msproject-case-realisation-manifest-v0.2",
                "pilot_id": PILOT_ID,
                "native_system": "microsoft_project",
                "state": "frozen_before_native_calculation",
                "case_id": "SEM-REL-001",
                "execution_track_id": "manual_native_semantic_parity",
                "native_source_file_sha256": _raw_sha(self.native_input),
                "pilot_index_raw_sha256": _raw_sha(self.pilot_index_path),
                "attestation_no_native_result_observed_before_freeze": True,
            },
        )
        with self.assertRaisesRegex(NativeEvidenceError, "inexact key set"):
            freeze_msproject_native_input(
                repository_root=self.root,
                pilot_index=self.pilot_index,
                pilot_id=PILOT_ID,
                case_id="SEM-REL-001",
                track_id="saved_file_reopen_recalculate_stability",
                native_file=self.native_input,
                environment_capture_path=self.environment_path,
                output_dir=self.root / "forged-track-b",
                prerequisite_manual_case_realization_manifest_path=forged_path,
                prepared_at="2026-08-26T10:01:00+08:00",
                prepared_by="operator-001",
                independent_pre_execution_reviewed_by="reviewer-002",
                attestation_no_native_result_observed_before_freeze=True,
            )

        self.environment["build"] = "another-build"
        write_canonical_json(self.environment_path, self.environment)
        with self.assertRaisesRegex(NativeEvidenceError, "environment capture hash"):
            freeze_msproject_native_input(
                repository_root=self.root,
                pilot_index=self.pilot_index,
                pilot_id=PILOT_ID,
                case_id="SEM-REL-001",
                track_id="saved_file_reopen_recalculate_stability",
                native_file=self.native_input,
                environment_capture_path=self.environment_path,
                output_dir=self.root / "changed-environment-track-b",
                prerequisite_manual_case_realization_manifest_path=manual.manifest_path,
                prepared_at="2026-08-26T10:01:00+08:00",
                prepared_by="operator-001",
                independent_pre_execution_reviewed_by="reviewer-002",
                attestation_no_native_result_observed_before_freeze=True,
            )

    def test_strict_case_realisation_validator_rejects_extra_keys(self) -> None:
        manifest = dict(self._freeze("strict-manifest").manifest)
        manifest["unregistered_field"] = "forbidden"
        with self.assertRaisesRegex(NativeEvidenceError, "inexact key set"):
            validate_case_realisation_manifest(manifest)

    def test_repository_validator_rechecks_live_tracked_bindings(self) -> None:
        manifest = self._freeze("repository-bound-manifest").manifest
        self.source_projection.write_bytes(self.source_projection.read_bytes() + b" ")
        with self.assertRaisesRegex(NativeEvidenceError, "source-only projection bytes"):
            validate_case_realisation_manifest_against_repository(
                repository_root=self.root,
                document=manifest,
                environment_capture_path=self.environment_path,
            )

    def test_preexecution_rebinding_never_reads_fixture_or_sealed_oracle(self) -> None:
        self.sealed_control_path.unlink()
        self.sealed_expected.unlink()
        self.fixture.unlink()
        manifest = self._freeze("oracle-blind-preexecution").manifest
        validate_case_realisation_manifest_against_repository(
            repository_root=self.root,
            document=manifest,
            environment_capture_path=self.environment_path,
        )
        tampered = dict(manifest)
        tampered["fixture_raw_sha256"] = "0" * 64
        with self.assertRaisesRegex(NativeEvidenceError, "frozen suite registry"):
            validate_case_realisation_manifest_against_repository(
                repository_root=self.root,
                document=tampered,
                environment_capture_path=self.environment_path,
            )

    def test_post_observation_seal_release_rejects_control_digest_substitution(self) -> None:
        manifest = dict(self._freeze("unsafe-seal-release").manifest)
        control = json.loads(self.sealed_control_path.read_text(encoding="utf-8"))
        control["cases"][0]["sealed_expected_raw_sha256"] = "0" * 64
        write_canonical_json(self.sealed_control_path, control)
        with self.assertRaisesRegex(
            NativeOutputError, "do not match the comparison control"
        ):
            _release_tracked_sealed_expected(
                repository_root=self.root,
                manifest=manifest,
            )

    def test_post_observation_seal_release_rejects_rebound_oracle_values(self) -> None:
        manifest = dict(self._freeze("rebound-seal-release").manifest)
        tracked_root = Path(__file__).resolve().parents[3]
        self.fixture.write_bytes(
            (
                tracked_root
                / "benchmarks/semantic/cases/sem-rel-001.json"
            ).read_bytes()
        )
        sealed = json.loads(
            (
                tracked_root
                / "native-validation/pilot-kits/"
                "microsoft-project-relationship-v0.1/"
                "sealed-expected-normalized/SEM-REL-001.json"
            ).read_text(encoding="utf-8")
        )
        sealed["source_bindings"]["preregistration"] = self.pilot_index[
            "bindings"
        ]["preregistration"]
        sealed["source_bindings"]["comparison_profile"] = self.pilot_index[
            "bindings"
        ]["comparison_profile"]
        sealed["expected_normalized"]["activity_times"]["B"]["start"] = 123
        write_canonical_json(self.sealed_expected, sealed)
        self._write_sealed_control()

        with self.assertRaisesRegex(
            NativeOutputError,
            "does not match the frozen fixture projection",
        ):
            _release_tracked_sealed_expected(
                repository_root=self.root,
                manifest=manifest,
            )

    def test_post_observation_seal_release_rejects_inexact_control_identity(self) -> None:
        manifest = dict(self._freeze("inexact-seal-control").manifest)
        baseline = json.loads(self.sealed_control_path.read_text(encoding="utf-8"))
        mutations = {
            "missing case": lambda document: document["cases"].clear(),
            "duplicate case": lambda document: document["cases"].append(
                dict(document["cases"][0])
            ),
            "wrong operator index": lambda document: document[
                "operator_pilot_index_binding"
            ].update({"raw_sha256": "0" * 64}),
            "extra key": lambda document: document.update({"unexpected": True}),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                changed = json.loads(json.dumps(baseline))
                mutate(changed)
                write_canonical_json(self.sealed_control_path, changed)
                with self.assertRaises(NativeOutputError):
                    _release_tracked_sealed_expected(
                        repository_root=self.root,
                        manifest=manifest,
                    )
        write_canonical_json(self.sealed_control_path, baseline)

    def test_post_observation_seal_release_revalidates_exact_fixture_binding(self) -> None:
        manifest = dict(self._freeze("exact-seal-fixture-binding").manifest)
        sealed = json.loads(self.sealed_expected.read_text(encoding="utf-8"))
        sealed["source_bindings"]["fixture"]["path"] = (
            "benchmarks/semantic/cases/sem-rel-002.json"
        )
        write_canonical_json(self.sealed_expected, sealed)
        self._write_sealed_control()
        with self.assertRaisesRegex(NativeOutputError, "full-fixture binding is not exact"):
            _release_tracked_sealed_expected(
                repository_root=self.root,
                manifest=manifest,
            )

    def test_post_observation_seal_release_is_track_a_only(self) -> None:
        manifest = dict(self._freeze("track-a-only-seal-release").manifest)
        manifest["execution_track_id"] = "saved_file_reopen_recalculate_stability"
        with self.assertRaisesRegex(NativeOutputError, "only to Track A"):
            _release_tracked_sealed_expected(
                repository_root=self.root,
                manifest=manifest,
            )

    def test_post_observation_seal_release_rejects_postfreeze_index_substitution(
        self,
    ) -> None:
        manifest = self._freeze("index-bound-seal-release").manifest
        self.pilot_index["cases"][0]["status"] = "substituted-after-freeze"
        write_canonical_json(self.pilot_index_path, self.pilot_index)
        with self.assertRaisesRegex(NativeOutputError, "changed after the pre-execution"):
            _release_tracked_sealed_expected(
                repository_root=self.root,
                manifest=manifest,
            )

    def test_repository_rebinder_rejects_tampered_manifest_binding(self) -> None:
        frozen = self._freeze("repository-bound-manifest")
        validate_case_realisation_manifest_against_repository(
            repository_root=self.root,
            document=frozen.manifest,
            environment_capture_path=self.environment_path,
        )
        tampered = dict(frozen.manifest)
        tampered["fixture_raw_sha256"] = "0" * 64
        with self.assertRaisesRegex(NativeEvidenceError, "fixture"):
            validate_case_realisation_manifest_against_repository(
                repository_root=self.root,
                document=tampered,
                environment_capture_path=self.environment_path,
            )

    def test_repository_rebinder_rejects_case_blocked_retained_adapter_manifest(
        self,
    ) -> None:
        manifest = self._retained_adapter_manifest("retained-adapter-case-blocker")
        self.pilot_index["cases"][0][
            "adapter_preparation_status"
        ] = "preparation_blocked"
        self.pilot_index["cases"][0]["adapter_preparation_blocked_reason"] = (
            "case-specific CAL-24X7 MSPDI mapping remains unresolved"
        )
        self._bind_manifest_to_current_pilot_index(manifest)

        with self.assertRaisesRegex(
            NativeEvidenceError, "case adapter_preparation_status.*CAL-24X7"
        ):
            validate_case_realisation_manifest_against_repository(
                repository_root=self.root,
                document=manifest,
                environment_capture_path=self.environment_path,
            )

    def test_analyser_rejects_top_level_blocked_retained_adapter_manifest(
        self,
    ) -> None:
        manifest = self._retained_adapter_manifest("retained-adapter-top-blocker")
        self.pilot_index["execution_tracks"] = [
            {
                "track_id": "adapter_interchange_round_trip",
                "adapter_preparation_status": "preparation_blocked",
            }
        ]
        self._bind_manifest_to_current_pilot_index(manifest)
        manifest_path = self.root / "retained-adapter-manifest.json"
        write_canonical_json(manifest_path, manifest)

        with self.assertRaisesRegex(
            NativeEvidenceError,
            "blocked by pilot execution-track adapter_preparation_status",
        ):
            analyse_msproject_native_output(
                repository_root=self.root,
                native_output_path=self.root / "unread-native-output.xml",
                case_realisation_manifest_path=manifest_path,
                environment_capture_path=self.environment_path,
                post_execution_attestation_path=self.root / "unread-attestation.json",
                post_execution_action_log_path=self.root / "unread-actions.json",
                stage_artifact_paths={},
                independent_evidence_artifact_paths={},
                output_dir=self.root / "unwritten-analysis",
                run_id="must-not-be-created",
                executed_at="2026-08-26T11:00:00+08:00",
            )

    def test_freeze_rejects_future_product_observation(self) -> None:
        setting = self.environment["observed_product_settings"]["calculation_mode"]
        setting["observed_at"] = "2026-08-26T10:01:00+08:00"
        setting["independently_verified_at"] = "2026-08-26T10:02:00+08:00"
        write_canonical_json(self.environment_path, self.environment)
        with self.assertRaisesRegex(NativeEvidenceError, "chronological order"):
            self._freeze("future-product-observation")

    def test_immutable_snapshot_rejects_path_replacement_during_read(self) -> None:
        target = self.root / "snapshot-race.bin"
        target.write_bytes(b"A" * (2 * 1024 * 1024))
        replacement = self.root / "snapshot-race-replacement.bin"
        replacement.write_bytes(b"B" * (2 * 1024 * 1024))
        real_read = os.read
        replaced = False

        def racing_read(descriptor: int, size: int) -> bytes:
            nonlocal replaced
            data = real_read(descriptor, size)
            if data and not replaced:
                replacement.replace(target)
                replaced = True
            return data

        with patch(
            "deterministic_scheduling_core.native.msproject.freeze.os.read",
            side_effect=racing_read,
        ), self.assertRaisesRegex(NativeEvidenceError, "replaced while it was read"):
            read_regular_file_snapshot(target, label="synthetic racing input")

    def test_stopped_attempt_without_freeze_is_nonclaimable_and_immutable(self) -> None:
        output_dir = self.root / "late-freeze-stop"
        stopped = record_msproject_native_attempt_stop(
            repository_root=self.root,
            pilot_id=PILOT_ID,
            case_id="SEM-REL-001",
            track_id="manual_native_semantic_parity",
            stopped_at="2026-08-26T10:01:00+08:00",
            recorded_by="operator-001",
            stop_condition_id=(
                "native_calculation_occurred_before_preexecution_freeze"
            ),
            reason="Synthetic test-only late-freeze stop; no native result exists.",
            outcome_classification="executed_inconclusive",
            native_calculation_observed=True,
            output_dir=output_dir,
        )
        self.assertEqual(set(stopped.record), set(STOP_RECORD_REQUIRED_FIELDS))
        self.assertEqual(
            stopped.record["record_type"], "native_attempt_stop_non_claimable"
        )
        self.assertEqual(
            stopped.record["fixture_raw_sha256"],
            EXPECTED_FIXTURE_SHA256_BY_FILENAME["sem-rel-001.json"],
        )
        self.assertEqual(
            stopped.record["source_only_projection_raw_sha256"],
            _raw_sha(self.source_projection),
        )
        stopped_text = stopped.record_path.read_text(encoding="utf-8")
        self.assertNotIn("benchmarks/semantic/cases", stopped_text)
        self.assertNotIn("sealed-expected-normalized", stopped_text)
        self.assertFalse(stopped.record["case_realisation_manifest_available"])
        self.assertFalse(stopped.record["environment_capture_available"])
        self.assertIsNone(stopped.record["case_realisation_manifest_sha256"])
        self.assertIsNone(stopped.record["environment_capture_sha256"])
        self.assertFalse(
            stopped.record["claim_boundary"]["native_run_evidence_record_exists"]
        )
        self.assertNotIn('"status"', stopped_text)
        self.assertNotIn('"status":"executed_pass"', stopped_text)
        with self.assertRaisesRegex(NativeEvidenceError, "never overwritten"):
            record_msproject_native_attempt_stop(
                repository_root=self.root,
                pilot_id=PILOT_ID,
                case_id="SEM-REL-001",
                track_id="manual_native_semantic_parity",
                stopped_at="2026-08-26T10:02:00+08:00",
                recorded_by="operator-001",
                stop_condition_id=(
                    "native_calculation_occurred_before_preexecution_freeze"
                ),
                reason="Synthetic retry must not overwrite the first stop record.",
                outcome_classification="executed_inconclusive",
                native_calculation_observed=True,
                output_dir=output_dir,
            )

    def test_stopped_attempt_enforces_outcome_environment_and_chronology(self) -> None:
        frozen = self._freeze("stop-prerequisite")
        common = {
            "repository_root": self.root,
            "pilot_id": PILOT_ID,
            "case_id": "SEM-REL-001",
            "track_id": "manual_native_semantic_parity",
            "stop_condition_id": "task_mode_changed",
            "reason": "Synthetic test-only task-mode stop.",
            "native_calculation_observed": True,
            "case_realisation_manifest_path": frozen.manifest_path,
            "environment_capture_path": self.environment_path,
        }
        with self.assertRaisesRegex(
            NativeAttemptStopError, "requires executed_inconclusive"
        ):
            record_msproject_native_attempt_stop(
                **common,
                stopped_at="2026-08-26T10:01:00+08:00",
                recorded_by="operator-001",
                outcome_classification="executed_fail",
                output_dir=self.root / "wrong-stop-outcome",
            )
        with self.assertRaisesRegex(
            NativeAttemptStopError, "captured execution_operator_id"
        ):
            record_msproject_native_attempt_stop(
                **common,
                stopped_at="2026-08-26T10:01:00+08:00",
                recorded_by="reviewer-002",
                outcome_classification="executed_inconclusive",
                output_dir=self.root / "wrong-stop-operator",
            )
        with self.assertRaisesRegex(NativeAttemptStopError, "after the pre-execution"):
            record_msproject_native_attempt_stop(
                **common,
                stopped_at="2026-08-26T09:59:00+08:00",
                recorded_by="operator-001",
                outcome_classification="executed_inconclusive",
                output_dir=self.root / "pre-freeze-stop-time",
            )
        stopped = record_msproject_native_attempt_stop(
            **common,
            stopped_at="2026-08-26T10:01:00+08:00",
            recorded_by="operator-001",
            outcome_classification="executed_inconclusive",
            output_dir=self.root / "valid-stopped-attempt",
        )
        self.assertTrue(stopped.record["case_realisation_manifest_available"])
        self.assertTrue(stopped.record["environment_capture_available"])

    def test_stopped_attempt_rejects_non_mpp_bytes_for_mpp_artifact(self) -> None:
        malformed_mpp = self.root / "synthetic-malformed-observed.mpp"
        malformed_mpp.write_bytes(b"not a compound file")
        with self.assertRaisesRegex(NativeAttemptStopError, "invalid CFB signature"):
            record_msproject_native_attempt_stop(
                repository_root=self.root,
                pilot_id=PILOT_ID,
                case_id="SEM-REL-001",
                track_id="manual_native_semantic_parity",
                stopped_at="2026-08-26T10:01:00+08:00",
                recorded_by="operator-001",
                stop_condition_id="relationship_or_lag_transformed",
                reason="Synthetic malformed artifact evidence.",
                outcome_classification="executed_fail",
                native_calculation_observed=True,
                observed_artifact_paths={"native_file": malformed_mpp},
                output_dir=self.root / "malformed-mpp-stop",
            )


class MicrosoftProjectNormalizerTests(unittest.TestCase):
    """Synthetic XML parser tests only; none of these documents are native results."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repository_root = Path(__file__).resolve().parents[3]
        self.manifest = self._manifest()
        self.rebinder_patcher = patch(
            "deterministic_scheduling_core.native.msproject.normalizer."
            "validate_case_realisation_manifest_against_repository"
        )
        self.mock_rebinder = self.rebinder_patcher.start()
        self.seal_release_patcher = patch(
            "deterministic_scheduling_core.native.msproject.normalizer."
            "_release_tracked_sealed_expected",
            side_effect=self._release_synthetic_sealed_expected,
        )
        self.mock_seal_release = self.seal_release_patcher.start()

    def tearDown(self) -> None:
        self.seal_release_patcher.stop()
        self.rebinder_patcher.stop()
        self.temporary.cleanup()

    def _release_synthetic_sealed_expected(
        self,
        *,
        repository_root: Path,
        manifest: dict[str, object],
    ):
        del repository_root, manifest
        snapshot = read_regular_file_snapshot(
            self.latest_sealed_path, label="sealed expected artifact"
        )
        return json.loads(snapshot.data.decode("utf-8")), snapshot

    @staticmethod
    def _manifest() -> dict[str, object]:
        return {
            "schema_version": "msproject-case-realisation-manifest-v0.2",
            "pilot_id": PILOT_ID,
            "native_system": "microsoft_project",
            "state": "frozen_before_native_calculation",
            "prepared_at": "2026-08-26T10:00:00+08:00",
            "case_id": "SEM-REL-001",
            "execution_track_id": "manual_native_semantic_parity",
            "prerequisite_manual_case_realization_manifest_sha256": None,
            "fixture_raw_sha256": EXPECTED_FIXTURE_SHA256_BY_FILENAME[
                "sem-rel-001.json"
            ],
            "source_only_projection_path": (
                "native-validation/pilot-kits/microsoft-project-relationship-v0.1/"
                "source-only-case-projections/SEM-REL-001.json"
            ),
            "source_only_projection_raw_sha256": "2" * 64,
            "preregistration_id": "microsoft-project-semantic-microcases-v0.1",
            "preregistration_raw_sha256": "69594ba766cea5f204bc41f99f49af28a65b6f543919dad2bee702a9f6e0b647",
            "comparison_profile_id": "microsoft-project-semantic-comparison-profile-v0.1",
            "comparison_profile_raw_sha256": "8ab9c47395897e13f5b6cf36773757f4bd5a273e997b81de78585d76e872a469",
            "native_source_file_sha256": "4" * 64,
            "environment_capture_sha256": "5" * 64,
            "coordinate_contract": {
                "canonical_origin": "2026-01-05T08:00:00+08:00",
                "utc_offset": "+08:00",
                "timestamp_tolerance_seconds": 0,
                "rounding_policy": "forbidden",
            },
            "native_activity_and_field_mapping": [
                {
                    "activity_id": "A",
                    "native_task_uid": 1,
                    "native_task_id": 1,
                    "native_task_name": "A",
                    "canonical_duration_hours": 4,
                    "canonical_calendar_id": "CAL-24X7",
                },
                {
                    "activity_id": "B",
                    "native_task_uid": 2,
                    "native_task_id": 2,
                    "native_task_name": "B",
                    "canonical_duration_hours": 3,
                    "canonical_calendar_id": "CAL-24X7",
                },
            ],
            "native_relationship_and_lag_realization": [
                {
                    "relationship_id": "R1",
                    "predecessor_activity_id": "A",
                    "successor_activity_id": "B",
                    "native_predecessor_uid": 1,
                    "native_successor_uid": 2,
                    "canonical_type": "FS",
                    "native_type": 1,
                    "canonical_signed_lag_hours": -2,
                    "native_link_lag_tenths_minutes": -1200,
                    "native_lag_format": 5,
                }
            ],
            "native_calendar_realization": [
                {
                    "canonical_calendar_id": "CAL-24X7",
                    "manual_native_calendar_name": "24 Hours",
                }
            ],
            "native_constraint_realization": [],
            "all_product_settings": {
                "new_tasks_are_manual": False,
                "task_pinned": 0,
                "mspdi_task_type": 1,
                "mspdi_effort_driven": 0,
                "resource_leveling": "disabled_and_not_run",
            },
            "captured_product_environment": {
                "product_name": "Microsoft Project",
                "edition": "Synthetic parser fixture",
                "version": "not-a-native-result",
                "build": "not-a-native-result",
                "execution_operator_id": "operator-001",
                "independent_reviewer_id": "reviewer-002",
                "project_start": "2026-01-05T08:00:00+08:00",
                "status_date": None,
                "schedule_from_start": True,
                "calculation_mode": "manual",
                "precalculation_protocol_state": "constructed_not_calculated",
                "resource_leveling_status": "disabled_and_not_run",
                "project_calendar_settings": {
                    "canonical_calendar_id": "CAL-24X7",
                    "native_calendar_name": "24 Hours",
                    "continuous_working_time_verified": True,
                },
                "task_calendar_per_task": {"A": "24 Hours", "B": "24 Hours"},
                "task_scheduling_mode_per_task": {
                    "A": "automatically_scheduled",
                    "B": "automatically_scheduled",
                },
                "task_type_per_task": {"A": "fixed_duration", "B": "fixed_duration"},
                "effort_driven_per_task": {"A": False, "B": False},
                "relationship_and_lag_settings": {
                    "R1": {
                        "predecessor_activity_id": "A",
                        "successor_activity_id": "B",
                        "canonical_type": "FS",
                        "signed_lag_hours": -2,
                        "native_type": 1,
                        "native_link_lag_tenths_minutes": -1200,
                        "native_lag_format": 5,
                    }
                },
                "constraint_settings": {},
                "independent_verification_artifact_plan": [
                    {"role": role, "planned_evidence_type": "screenshot"}
                    for role in (
                        "task_table",
                        "project_information",
                        "calendar_working_time",
                        "predecessor_details",
                        "task_mode_type_effort",
                        "resource_leveling_status",
                    )
                ],
            },
            "construction_action_log": [{"sequence": 1, "action": "synthetic"}],
            "prepared_by": "operator-001",
            "independent_pre_execution_reviewed_by": "reviewer-002",
            "attestation_no_native_result_observed_before_freeze": True,
        }

    @staticmethod
    def _synthetic_xml(
        *,
        namespace: str = MSPDI_NAMESPACE,
        start_b: str = "2026-01-05T14:00:00",
        link_type: int = 1,
        link_lag: int = -1200,
        predecessor_uid: int = 1,
        include_b: bool = True,
        duplicate_uid: bool = False,
        include_link: bool = True,
        lag_format: int = 5,
        cross_project: int = 0,
        summary_task_xml: str = "",
    ) -> str:
        link = ""
        if include_link:
            link = f"""
        <PredecessorLink>
          <PredecessorUID>{predecessor_uid}</PredecessorUID>
          <Type>{link_type}</Type>
          <LinkLag>{link_lag}</LinkLag>
          <LagFormat>{lag_format}</LagFormat>
          <CrossProject>{cross_project}</CrossProject>
        </PredecessorLink>"""
        task_b = ""
        if include_b:
            uid = 1 if duplicate_uid else 2
            task_b = f"""
      <Task>
        <UID>{uid}</UID><ID>2</ID><Name>B</Name>
        <Type>1</Type><EffortDriven>0</EffortDriven><Manual>0</Manual><Pinned>0</Pinned>
        <CalendarUID>1</CalendarUID>
        <Duration>PT3H0M0S</Duration>
        <Start>{start_b}</Start><Finish>2026-01-05T17:00:00</Finish>
        <Resume xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:nil="true"/>
        {link}
      </Task>"""
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<Project xmlns="{namespace}">
  <SaveVersion>14</SaveVersion>
  <NewTasksAreManual>0</NewTasksAreManual>
  <ScheduleFromStart>1</ScheduleFromStart>
  <CalendarUID>1</CalendarUID>
  <StartDate>2026-01-05T08:00:00</StartDate>
  <FinishDate>2026-01-05T17:00:00</FinishDate>
  <Calendars><Calendar><UID>1</UID><Name>24 Hours</Name></Calendar></Calendars>
  <Tasks>
    {summary_task_xml}
    <Task>
      <UID>1</UID><ID>1</ID><Name>A</Name>
      <Type>1</Type><EffortDriven>0</EffortDriven><Manual>0</Manual><Pinned>0</Pinned>
      <CalendarUID>1</CalendarUID>
      <Duration>PT4H0M0S</Duration>
      <Start>2026-01-05T08:00:00</Start><Finish>2026-01-05T12:00:00</Finish>
    </Task>{task_b}
  </Tasks>
</Project>
"""

    def _write_xml(self, text: str, name: str = "synthetic-parser-output.xml") -> Path:
        path = self.root / name
        path.write_text(text, encoding="utf-8", newline="\n")
        return path

    def _normalize(self, **changes):
        return normalize_mspdi_output(
            native_output_path=self._write_xml(self._synthetic_xml(**changes)),
            case_realisation_manifest=self.manifest,
        )

    def test_normalizer_accepts_only_project_2010_namespace_and_save_version(self) -> None:
        normalized = self._normalize()
        self.assertEqual(normalized["mspdi_namespace"], MSPDI_NAMESPACE)
        for namespace in (
            "http://schemas.microsoft.com/project",
            "http://schemas.microsoft.com/project/2007",
        ):
            with self.assertRaisesRegex(NativeOutputError, "only the reviewed MSPDI 2010"):
                self._normalize(namespace=namespace)
        missing_schedule_direction = self._synthetic_xml().replace(
            "  <ScheduleFromStart>1</ScheduleFromStart>\n", "", 1
        )
        with self.assertRaisesRegex(NativeOutputError, "ScheduleFromStart must be present"):
            normalize_mspdi_output(
                native_output_path=self._write_xml(
                    missing_schedule_direction,
                    "synthetic-missing-schedule-direction.xml",
                ),
                case_realisation_manifest=self.manifest,
            )

    def test_normalizer_preserves_missing_null_and_zero(self) -> None:
        normalized = self._normalize()
        self.assertEqual(
            normalized["activity_times"]["A"]["start"],
            {
                "presence": "present",
                "raw": "2026-01-05T08:00:00",
                "value": 0,
                "transformation_id": "microsoft-project-coordinate-normalisation-v0.1",
            },
        )
        self.assertNotIn("remaining_start", normalized["activity_times"]["A"])
        self.assertEqual(
            normalized["activity_times"]["B"]["remaining_start"],
            {"presence": "present", "value": None},
        )

    def test_normalizer_rejects_missing_duplicate_and_unknown_tasks(self) -> None:
        with self.assertRaisesRegex(NativeOutputError, "missing mapped task"):
            self._normalize(include_b=False)
        with self.assertRaisesRegex(NativeOutputError, "duplicate native task UID"):
            self._normalize(duplicate_uid=True)
        unknown = self._synthetic_xml().replace("<UID>2</UID><ID>2</ID>", "<UID>3</UID><ID>2</ID>")
        with self.assertRaisesRegex(NativeOutputError, "unknown native task UID"):
            normalize_mspdi_output(
                native_output_path=self._write_xml(unknown, "synthetic-unknown-task.xml"),
                case_realisation_manifest=self.manifest,
            )

    def test_normalizer_retains_only_the_official_project_summary_task(self) -> None:
        summary = (
            "<Task><UID>0</UID><ID>0</ID><Name>Project Summary</Name>"
            "<Summary>1</Summary><Start>2026-01-05T08:00:00</Start>"
            "<Finish>2026-01-05T17:00:00</Finish></Task>"
        )
        normalized = self._normalize(summary_task_xml=summary)
        retained = normalized["additional_native_fields"]["project"][
            "ProjectSummaryTask"
        ]
        self.assertEqual(retained["presence"], "present")
        self.assertEqual(retained["interpretation_status"], "retained_unclaimed")
        self.assertIn("Project Summary", canonical_text(retained))

        malformed = (
            summary.replace("<ID>0</ID>", "<ID>9</ID>"),
            summary.replace("<Summary>1</Summary>", "<Summary>0</Summary>"),
            summary.replace(
                "</Task>",
                "<PredecessorLink><PredecessorUID>1</PredecessorUID></PredecessorLink></Task>",
            ),
            summary + summary,
        )
        messages = ("both UID 0 and ID 0", "Summary true", "must not contain", "duplicate")
        for number, (row, message) in enumerate(zip(malformed, messages), start=1):
            with self.subTest(mutation=number):
                with self.assertRaisesRegex(NativeOutputError, message):
                    self._normalize(summary_task_xml=row)

    def test_normalizer_rejects_missing_unknown_or_transformed_relationship(self) -> None:
        with self.assertRaisesRegex(NativeOutputError, "missing mapped relationships"):
            self._normalize(include_link=False)
        with self.assertRaisesRegex(NativeOutputError, "unknown relationship"):
            self._normalize(predecessor_uid=2)
        with self.assertRaisesRegex(NativeOutputError, "Type changed"):
            self._normalize(link_type=3)
        with self.assertRaisesRegex(NativeOutputError, "unknown relationship Type"):
            self._normalize(link_type=9)

    def test_normalizer_rejects_transformed_or_sign_inverted_lag(self) -> None:
        with self.assertRaisesRegex(NativeOutputError, "LinkLag changed"):
            self._normalize(link_lag=-600)
        with self.assertRaisesRegex(NativeOutputError, "LinkLag changed"):
            self._normalize(link_lag=1200)
        with self.assertRaisesRegex(NativeOutputError, "LagFormat changed"):
            self._normalize(lag_format=7)
        with self.assertRaisesRegex(NativeOutputError, "cross-project"):
            self._normalize(cross_project=1)

    def test_normalizer_rejects_off_grid_timestamp_without_rounding(self) -> None:
        with self.assertRaisesRegex(NativeOutputError, "off the exact integer-hour grid"):
            self._normalize(start_b="2026-01-05T14:30:00")

    def test_normalizer_rejects_changed_task_configuration(self) -> None:
        mutations = (
            ("<NewTasksAreManual>0</NewTasksAreManual>", "<NewTasksAreManual>1</NewTasksAreManual>", "automatic-task"),
            ("<ScheduleFromStart>1</ScheduleFromStart>", "<ScheduleFromStart>0</ScheduleFromStart>", "schedule from finish"),
            ("<Type>1</Type>", "<Type>0</Type>", "fixed-duration"),
            ("<EffortDriven>0</EffortDriven>", "<EffortDriven>1</EffortDriven>", "effort-driven"),
            ("<Manual>0</Manual>", "<Manual>1</Manual>", "manually scheduled"),
            ("<Pinned>0</Pinned>", "<Pinned>1</Pinned>", "automatically scheduled"),
        )
        for number, (old, new, message) in enumerate(mutations, start=1):
            with self.subTest(field=old):
                changed = self._synthetic_xml().replace(old, new, 1)
                with self.assertRaisesRegex(NativeOutputError, message):
                    normalize_mspdi_output(
                        native_output_path=self._write_xml(
                            changed, f"synthetic-changed-config-{number}.xml"
                        ),
                        case_realisation_manifest=self.manifest,
                    )

    def test_normalizer_bounds_xml_depth(self) -> None:
        nesting = "<Extra>" * 65 + "bounded" + "</Extra>" * 65
        xml = self._synthetic_xml().replace("  <Tasks>", f"  {nesting}\n  <Tasks>")
        with self.assertRaisesRegex(NativeOutputError, "depth limit") as error:
            normalize_mspdi_output(
                native_output_path=self._write_xml(xml, "synthetic-too-deep.xml"),
                case_realisation_manifest=self.manifest,
            )
        self.assertEqual(error.exception.outcome, "executed_inconclusive")

    def test_normalizer_bounds_xml_input_bytes(self) -> None:
        with patch(
            "deterministic_scheduling_core.native.msproject.normalizer.MAX_MSPDI_BYTES",
            64,
        ), self.assertRaisesRegex(NativeOutputError, "evidence limit") as error:
            normalize_mspdi_output(
                native_output_path=self._write_xml(
                    self._synthetic_xml(), "synthetic-too-large.xml"
                ),
                case_realisation_manifest=self.manifest,
            )
        self.assertEqual(error.exception.outcome, "executed_inconclusive")

    def test_normalizer_bounds_xml_elements_and_text(self) -> None:
        for constant, limit, message in (
            ("MAX_MSPDI_ELEMENTS", 10, "element limit"),
            ("MAX_MSPDI_TEXT_BYTES", 8, "text limit"),
        ):
            with self.subTest(constant=constant), patch(
                f"deterministic_scheduling_core.native.msproject.normalizer.{constant}",
                limit,
            ), self.assertRaisesRegex(NativeOutputError, message) as error:
                normalize_mspdi_output(
                    native_output_path=self._write_xml(
                        self._synthetic_xml(),
                        f"synthetic-{constant.lower()}-overflow.xml",
                    ),
                    case_realisation_manifest=self.manifest,
                )
            self.assertEqual(error.exception.outcome, "executed_inconclusive")

    def test_missing_configuration_is_inconclusive_but_missing_claim_is_failure(self) -> None:
        configuration_elements = (
            "<SaveVersion>14</SaveVersion>",
            "<NewTasksAreManual>0</NewTasksAreManual>",
            "<ScheduleFromStart>1</ScheduleFromStart>",
            "<Type>1</Type>",
            "<EffortDriven>0</EffortDriven>",
            "<Manual>0</Manual>",
            "<Pinned>0</Pinned>",
            "<CalendarUID>1</CalendarUID>",
        )
        for number, element in enumerate(configuration_elements, start=1):
            with self.subTest(element=element):
                changed = self._synthetic_xml().replace(element, "", 1)
                with self.assertRaises(NativeOutputError) as captured:
                    normalize_mspdi_output(
                        native_output_path=self._write_xml(
                            changed, f"synthetic-missing-config-{number}.xml"
                        ),
                        case_realisation_manifest=self.manifest,
                    )
                self.assertEqual(captured.exception.outcome, "executed_inconclusive")

        missing_claim = self._synthetic_xml().replace(
            "<Start>2026-01-05T08:00:00</Start>", "", 1
        )
        normalized = normalize_mspdi_output(
            native_output_path=self._write_xml(
                missing_claim, "synthetic-missing-claim-start.xml"
            ),
            case_realisation_manifest=self.manifest,
        )
        comparison = compare_normalized_output(
            normalized_output=normalized,
            sealed_expected={
                "case_id": "SEM-REL-001",
                "expected_normalized_output": {
                    "activity_times": {
                        "A": {"start": 0, "finish": 4},
                        "B": {"start": 6, "finish": 9},
                    },
                    "project_finish": 9,
                },
            },
        )
        self.assertTrue(comparison["claim_field_failure"])

    def test_normalizer_rejects_changed_frozen_model_facts(self) -> None:
        mutations = (
            ("<Name>A</Name>", "<Name>changed</Name>", "native name"),
            ("<Duration>PT4H0M0S</Duration>", "<Duration>PT5H0M0S</Duration>", "duration"),
            ("<CalendarUID>1</CalendarUID>", "<CalendarUID>9</CalendarUID>", "CalendarUID"),
            ("<StartDate>2026-01-05T08:00:00</StartDate>", "<StartDate>2026-01-05T09:00:00</StartDate>", "project StartDate"),
            ("<Name>24 Hours</Name>", "<Name>Standard</Name>", "24 Hours"),
        )
        for number, (old, new, message) in enumerate(mutations, start=1):
            with self.subTest(field=old):
                changed = self._synthetic_xml().replace(old, new, 1)
                with self.assertRaisesRegex(NativeOutputError, message):
                    normalize_mspdi_output(
                        native_output_path=self._write_xml(
                            changed, f"synthetic-changed-fact-{number}.xml"
                        ),
                        case_realisation_manifest=self.manifest,
                    )

    def test_calendar_working_time_structure_is_retained_but_not_interpreted(self) -> None:
        xml = self._synthetic_xml().replace(
            "<UID>1</UID><Name>24 Hours</Name>",
            "<UID>1</UID><Name>24 Hours</Name><WeekDays><WeekDay>"
            "<DayType>1</DayType><DayWorking>1</DayWorking><WorkingTimes>"
            "<WorkingTime><FromTime>00:00:00</FromTime><ToTime>00:00:00</ToTime>"
            "</WorkingTime></WorkingTimes></WeekDay></WeekDays>",
            1,
        )
        normalized = normalize_mspdi_output(
            native_output_path=self._write_xml(
                xml, "synthetic-calendar-structure-parser-only.xml"
            ),
            case_realisation_manifest=self.manifest,
        )
        structure = normalized["additional_native_fields"]["project"][
            "CAL-24X7-native-calendar-structure"
        ]
        self.assertEqual(structure["interpretation_status"], "retained_unclaimed")
        self.assertFalse(structure["working_time_serialization_interpreted"])
        self.assertIn("WeekDays", canonical_text(structure))

    def test_normalizer_validates_frozen_snet_constraint(self) -> None:
        constraint = {
            "constraint_id": "C1",
            "activity_id": "A",
            "native_task_uid": 1,
            "canonical_type": "start_no_earlier_than",
            "canonical_coordinate": 0,
            "canonical_timestamp": "2026-01-05T08:00:00+08:00",
            "native_constraint_type": 4,
        }
        self.manifest["native_constraint_realization"] = [constraint]
        self.manifest["captured_product_environment"]["constraint_settings"] = {
            "C1": {
                key: constraint[key]
                for key in (
                    "activity_id",
                    "canonical_type",
                    "canonical_coordinate",
                    "canonical_timestamp",
                    "native_constraint_type",
                )
            }
        }
        source = self._synthetic_xml().replace(
            "<Duration>PT4H0M0S</Duration>",
            "<Duration>PT4H0M0S</Duration><ConstraintType>4</ConstraintType>"
            "<ConstraintDate>2026-01-05T08:00:00</ConstraintDate>",
            1,
        )
        normalized = normalize_mspdi_output(
            native_output_path=self._write_xml(source, "synthetic-snet.xml"),
            case_realisation_manifest=self.manifest,
        )
        self.assertEqual(normalized["activity_times"]["A"]["start"]["value"], 0)
        for number, (old, new, message) in enumerate(
            (
                ("<ConstraintType>4</ConstraintType>", "<ConstraintType>2</ConstraintType>", "constraint type"),
                ("<ConstraintDate>2026-01-05T08:00:00</ConstraintDate>", "<ConstraintDate>2026-01-05T09:00:00</ConstraintDate>", "constraint date"),
            ),
            start=1,
        ):
            with self.subTest(mutation=old):
                with self.assertRaisesRegex(NativeOutputError, message):
                    normalize_mspdi_output(
                        native_output_path=self._write_xml(
                            source.replace(old, new, 1),
                            f"synthetic-snet-mutation-{number}.xml",
                        ),
                        case_realisation_manifest=self.manifest,
                    )

    def test_comparison_is_separate_and_limits_status_claim(self) -> None:
        normalized = self._normalize()
        normalized_bytes_before = (canonical_text(normalized) + "\n").encode("utf-8")
        sealed = {
            "case_id": "SEM-REL-001",
            "expected_normalized_output": {
                "activity_times": {
                    "A": {"start": 0, "finish": 4},
                    "B": {"start": 6, "finish": 9},
                },
                "project_finish": 9,
            },
        }
        comparison = compare_normalized_output(
            normalized_output=normalized, sealed_expected=sealed
        )
        self.assertFalse(comparison["claim_field_failure"])
        self.assertFalse(comparison["full_45_case_gate_satisfied"])
        claim_classes = {
            record["classification"]
            for record in comparison["records"]
            if not record["field_path"].startswith("additional_native_fields")
        }
        self.assertEqual(claim_classes, {"approved_transformation_match"})
        changed_oracle = json.loads(json.dumps(sealed))
        changed_oracle["expected_normalized_output"]["project_finish"] = 99
        compare_normalized_output(
            normalized_output=normalized, sealed_expected=changed_oracle
        )
        self.assertEqual(
            (canonical_text(normalized) + "\n").encode("utf-8"),
            normalized_bytes_before,
        )

    def test_independent_evidence_roles_and_paths_are_exact_and_unique(self) -> None:
        roles = ["task_table", "project_information"]
        environment = {
            "independent_verification_artifact_plan": [
                {"role": role, "planned_evidence_type": "screenshot"} for role in roles
            ]
        }
        first = self.root / "synthetic-test-only-evidence-first.png"
        second = self.root / "synthetic-test-only-evidence-second.png"
        first.write_bytes(b"\x89PNG\r\n\x1a\nfirst")
        second.write_bytes(b"\x89PNG\r\n\x1a\nsecond")
        with self.assertRaisesRegex(NativeOutputError, "exactly planned roles"):
            _hash_independent_evidence_artifacts(
                environment=environment,
                independent_evidence_artifact_paths={"task_table": first},
                forbidden_paths=(),
            )
        with self.assertRaisesRegex(NativeOutputError, "duplicate roles"):
            _hash_independent_evidence_artifacts(
                environment={"independent_verification_artifact_plan": [
                    {"role": "task_table", "planned_evidence_type": "screenshot"},
                    {"role": "task_table", "planned_evidence_type": "screenshot"},
                ]},
                independent_evidence_artifact_paths={"task_table": first},
                forbidden_paths=(),
            )
        hardlink = self.root / "synthetic-test-only-evidence-hardlink.png"
        os.link(first, hardlink)
        with self.assertRaisesRegex(NativeOutputError, "distinct file"):
            _hash_independent_evidence_artifacts(
                environment=environment,
                independent_evidence_artifact_paths={
                    "task_table": first, "project_information": hardlink,
                },
                forbidden_paths=(),
            )
        empty = self.root / "synthetic-test-only-empty.png"
        empty.write_bytes(b"")
        invalid = self.root / "synthetic-test-only-invalid.png"
        invalid.write_bytes(b"not a PNG")
        for path, message in ((empty, "must not be empty"), (invalid, "invalid PNG")):
            with self.subTest(path=path.name), self.assertRaisesRegex(NativeOutputError, message):
                _hash_independent_evidence_artifacts(
                    environment={"independent_verification_artifact_plan": [{
                        "role": "task_table", "planned_evidence_type": "screenshot"
                    }]},
                    independent_evidence_artifact_paths={"task_table": path},
                    forbidden_paths=(),
                )
        with self.assertRaisesRegex(NativeOutputError, "stage artifact .* must not be empty"):
            _hash_stage_artifacts(
                track_id="manual_native_semantic_parity",
                stage_artifact_paths={"native_calculated_file_sha256": empty},
            )
        wrong_media = self.root / "synthetic-test-only-evidence.txt"
        wrong_media.write_text("not a screenshot", encoding="utf-8")
        with self.assertRaisesRegex(NativeOutputError, "planned screenshot"):
            _hash_independent_evidence_artifacts(
                environment={"independent_verification_artifact_plan": [{
                    "role": "task_table", "planned_evidence_type": "screenshot"
                }]},
                independent_evidence_artifact_paths={"task_table": wrong_media},
                forbidden_paths=(),
            )
        duplicate = self.root / "synthetic-test-only-evidence-duplicate.png"
        duplicate.write_bytes(first.read_bytes())
        with self.assertRaisesRegex(NativeOutputError, "identical evidence bytes"):
            _hash_independent_evidence_artifacts(
                environment=environment,
                independent_evidence_artifact_paths={
                    "task_table": first,
                    "project_information": duplicate,
                },
                forbidden_paths=(),
            )

    def test_stage_artifact_cannot_alias_control_evidence(self) -> None:
        control = self.root / "synthetic-control-manifest.mpp"
        control.write_bytes(
            b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1synthetic stage"
        )
        stage = self.root / "synthetic-hardlink-stage.mpp"
        os.link(control, stage)
        with self.assertRaisesRegex(
            NativeOutputError, "control manifest and native_calculated"
        ):
            _snapshot_stage_artifacts(
                track_id="manual_native_semantic_parity",
                stage_artifact_paths={"native_calculated_file_sha256": stage},
                forbidden_files={
                    read_regular_file_snapshot(
                        control, label="synthetic control manifest"
                    ).file_identity: "control manifest"
                },
            )

    def test_post_execution_actions_require_exact_ids_order_and_chronology(self) -> None:
        manifest = self.manifest
        environment = manifest["captured_product_environment"]
        actions = self._post_execution_actions(
            track_id="manual_native_semantic_parity",
            stage_roles={"native_calculated_file_sha256"},
            evidence_roles={"task_table"},
        )
        base = {
            "schema_version": "microsoft-project-post-execution-action-log-v0.1",
            "pilot_id": PILOT_ID,
            "native_system": "microsoft_project",
            "case_id": "SEM-REL-001",
            "execution_track_id": "manual_native_semantic_parity",
            "executed_at": "2026-08-26T11:00:00+08:00",
            "operator_id": environment["execution_operator_id"],
            "environment_capture_sha256": "e" * 64,
            "case_realization_manifest_sha256": "m" * 64,
            "complete_manual_action_log_attestation": True,
            "actions": actions,
        }
        for mutation in ("missing", "reordered", "early"):
            changed = json.loads(json.dumps(base))
            if mutation == "missing":
                changed["actions"].pop(1)
                for sequence, item in enumerate(changed["actions"], start=1):
                    item["sequence"] = sequence
            elif mutation == "reordered":
                changed["actions"][0]["action_id"], changed["actions"][1]["action_id"] = (
                    changed["actions"][1]["action_id"], changed["actions"][0]["action_id"]
                )
            else:
                changed["actions"][0]["performed_at"] = "2026-08-26T10:59:59+08:00"
            with self.subTest(mutation=mutation), self.assertRaises(NativeOutputError):
                _validate_post_execution_action_log(
                    document=changed, manifest=manifest, environment=environment,
                    executed_at="2026-08-26T11:00:00+08:00",
                    manifest_sha256="m" * 64, environment_sha256="e" * 64,
                    stage_roles={"native_calculated_file_sha256"},
                    evidence_roles={"task_table"},
                )
    def _analysis_inputs(self, *, xml_text: str | None = None):
        xml_path = self._write_xml(xml_text or self._synthetic_xml())
        manifest_path = self.root / "case-realisation-manifest.json"
        environment_path = self.root / "environment-capture.json"
        sealed_path = self.root / "sealed-expected.json"
        environment = dict(self.manifest["captured_product_environment"])
        write_canonical_json(environment_path, environment)
        write_canonical_json(
            sealed_path,
            {
                "case_id": "SEM-REL-001",
                "source_bindings": {
                    "fixture": {
                        "path": "benchmarks/semantic/cases/sem-rel-001.json",
                        "raw_sha256": _raw_sha(
                            self.repository_root
                            / "benchmarks/semantic/cases/sem-rel-001.json"
                        ),
                    }
                },
                "expected_normalized_output": {
                    "activity_times": {
                        "A": {"start": 0, "finish": 4},
                        "B": {"start": 6, "finish": 9},
                    },
                    "project_finish": 9,
                },
            },
        )
        self.latest_sealed_path = sealed_path
        self.manifest["environment_capture_sha256"] = _raw_sha(environment_path)
        write_canonical_json(manifest_path, self.manifest)
        stage_path = self.root / "synthetic-test-only-native-calculated.mpp"
        stage_path.write_bytes(
            b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
            b"SYNTHETIC TEST-ONLY STAGE ARTIFACT; NOT NATIVE EVIDENCE"
        )
        stage_paths = {"native_calculated_file_sha256": stage_path}
        self.latest_evidence_paths = {}
        for item in environment["independent_verification_artifact_plan"]:
            role = item["role"]
            path = self.root / f"synthetic-test-only-evidence-{role}.png"
            path.write_bytes(
                b"\x89PNG\r\n\x1a\n" + f"SYNTHETIC TEST ONLY EVIDENCE {role}".encode("ascii")
            )
            self.latest_evidence_paths[role] = path
        self.latest_action_log_path = self.root / "synthetic-test-only-post-action-log.json"
        write_canonical_json(
            self.latest_action_log_path,
            {
                "schema_version": "microsoft-project-post-execution-action-log-v0.1",
                "pilot_id": PILOT_ID,
                "native_system": "microsoft_project",
                "case_id": "SEM-REL-001",
                "execution_track_id": self.manifest["execution_track_id"],
                "executed_at": "2026-08-26T11:00:00+08:00",
                "operator_id": environment["execution_operator_id"],
                "environment_capture_sha256": _raw_sha(environment_path),
                "case_realization_manifest_sha256": _raw_sha(manifest_path),
                "complete_manual_action_log_attestation": True,
                "actions": self._post_execution_actions(
                    track_id=self.manifest["execution_track_id"],
                    stage_roles=set(stage_paths),
                    evidence_roles=set(self.latest_evidence_paths),
                ),
            },
        )
        return xml_path, manifest_path, environment_path, sealed_path, stage_paths

    @staticmethod
    def _post_execution_actions(
        *, track_id: str, stage_roles: set[str], evidence_roles: set[str]
    ) -> list[dict[str, object]]:
        action_ids = POST_EXECUTION_ACTION_IDS_BY_TRACK[track_id]
        return [
            {
                "sequence": sequence,
                "action_id": action_id,
                "action": f"SYNTHETIC TEST ONLY completion of {action_id}",
                "performed_at": "2026-08-26T11:00:00+08:00",
                "stage_artifact_roles": sorted(stage_roles) if sequence == len(action_ids) else [],
                "independent_evidence_roles": sorted(evidence_roles) if sequence == len(action_ids) else [],
            }
            for sequence, action_id in enumerate(action_ids, start=1)
        ]

    def _write_simulated_attestation(
        self,
        *,
        xml_path: Path,
        manifest_path: Path,
        environment_path: Path,
        stage_paths: dict[str, Path],
        actual_native_execution: bool = True,
    ) -> Path:
        attestation_path = self.root / "synthetic-test-only-post-execution-attestation.json"
        environment = self.manifest["captured_product_environment"]
        write_canonical_json(
            attestation_path,
            {
                "schema_version": "microsoft-project-post-execution-attestation-v0.1",
                "pilot_id": PILOT_ID,
                "native_system": "microsoft_project",
                "case_id": "SEM-REL-001",
                "execution_track_id": self.manifest["execution_track_id"],
                "actual_native_execution": actual_native_execution,
                "microsoft_project_desktop_opened": True,
                "case_opened_or_constructed": True,
                "native_recalculation_completed": True,
                "native_output_exported": True,
                "resource_leveling_disabled_and_not_run": True,
                "product_name": environment["product_name"],
                "edition": environment["edition"],
                "version": environment["version"],
                "build": environment["build"],
                "executed_at": "2026-08-26T11:00:00+08:00",
                "attested_at": "2026-08-26T11:01:00+08:00",
                "attested_by": environment["execution_operator_id"],
                "environment_capture_sha256": _raw_sha(environment_path),
                "case_realization_manifest_sha256": _raw_sha(manifest_path),
                "native_output_sha256": _raw_sha(xml_path),
                "stage_artifact_sha256_by_role": {
                    role: _raw_sha(path) for role, path in stage_paths.items()
                },
                "post_execution_action_log_sha256": _raw_sha(
                    self.latest_action_log_path
                ),
                "independent_evidence_artifact_sha256_by_role": {
                    role: _raw_sha(path)
                    for role, path in self.latest_evidence_paths.items()
                },
            },
        )
        return attestation_path

    def _track_b_inputs(self, *, pre_close_xml: str, post_recalculate_xml: str):
        xml_path, manifest_path, environment_path, sealed_path, _ = (
            self._analysis_inputs(xml_text=post_recalculate_xml)
        )
        prerequisite = json.loads(json.dumps(self.manifest))
        prerequisite["execution_track_id"] = "manual_native_semantic_parity"
        prerequisite["prerequisite_manual_case_realization_manifest_sha256"] = None
        self.latest_prerequisite_path = (
            self.root / "synthetic-test-only-prerequisite-track-a-manifest.json"
        )
        write_canonical_json(self.latest_prerequisite_path, prerequisite)
        self.manifest["execution_track_id"] = "saved_file_reopen_recalculate_stability"
        self.manifest[
            "prerequisite_manual_case_realization_manifest_sha256"
        ] = _raw_sha(self.latest_prerequisite_path)
        write_canonical_json(manifest_path, self.manifest)

        pre_close_output = self.root / "synthetic-test-only-pre-close-output.xml"
        pre_close_output.write_text(pre_close_xml, encoding="utf-8", newline="\n")
        stage_paths: dict[str, Path] = {
            "native_pre_close_file_sha256": self.root
            / "synthetic-test-only-pre-close.mpp",
            "native_pre_close_output_sha256": pre_close_output,
            "native_reopened_file_sha256": self.root
            / "synthetic-test-only-reopened.mpp",
            "native_recalculated_file_sha256": self.root
            / "synthetic-test-only-recalculated.mpp",
            "native_post_recalculate_output_sha256": xml_path,
        }
        for role, path in stage_paths.items():
            if not path.exists():
                path.write_bytes(
                    b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
                    + f"SYNTHETIC TEST ONLY {role}".encode("ascii")
                )
        write_canonical_json(
            self.latest_action_log_path,
            {
                "schema_version": "microsoft-project-post-execution-action-log-v0.1",
                "pilot_id": PILOT_ID,
                "native_system": "microsoft_project",
                "case_id": "SEM-REL-001",
                "execution_track_id": "saved_file_reopen_recalculate_stability",
                "executed_at": "2026-08-26T11:00:00+08:00",
                "operator_id": self.manifest["captured_product_environment"][
                    "execution_operator_id"
                ],
                "environment_capture_sha256": _raw_sha(environment_path),
                "case_realization_manifest_sha256": _raw_sha(manifest_path),
                "complete_manual_action_log_attestation": True,
                "actions": self._post_execution_actions(
                    track_id="saved_file_reopen_recalculate_stability",
                    stage_roles=set(stage_paths),
                    evidence_roles=set(self.latest_evidence_paths),
                ),
            },
        )
        attestation_path = self._write_simulated_attestation(
            xml_path=xml_path,
            manifest_path=manifest_path,
            environment_path=environment_path,
            stage_paths=stage_paths,
        )
        return (
            xml_path,
            manifest_path,
            environment_path,
            sealed_path,
            stage_paths,
            attestation_path,
        )

    def test_analysis_requires_actual_post_execution_attestation_before_status(self) -> None:
        xml_path, manifest_path, environment_path, sealed_path, stage_paths = (
            self._analysis_inputs()
        )
        output_dir = self.root / "analysis-without-attestation"
        with self.assertRaises(NativeEvidenceError):
            analyse_msproject_native_output(
                repository_root=self.repository_root,
                native_output_path=xml_path,
                case_realisation_manifest_path=manifest_path,
                environment_capture_path=environment_path,
                post_execution_attestation_path=self.root / "missing-attestation.json",
                post_execution_action_log_path=self.latest_action_log_path,
                stage_artifact_paths=stage_paths,
                independent_evidence_artifact_paths=self.latest_evidence_paths,
                output_dir=output_dir,
                run_id="synthetic-parser-run-no-attestation",
                executed_at="2026-08-26T11:00:00+08:00",
            )
        self.assertFalse(output_dir.exists())

        attestation_path = self._write_simulated_attestation(
            xml_path=xml_path,
            manifest_path=manifest_path,
            environment_path=environment_path,
            stage_paths=stage_paths,
            actual_native_execution=False,
        )
        with self.assertRaisesRegex(NativeOutputError, "actual_native_execution must be true"):
            analyse_msproject_native_output(
                repository_root=self.repository_root,
                native_output_path=xml_path,
                case_realisation_manifest_path=manifest_path,
                environment_capture_path=environment_path,
                post_execution_attestation_path=attestation_path,
                post_execution_action_log_path=self.latest_action_log_path,
                stage_artifact_paths=stage_paths,
                independent_evidence_artifact_paths=self.latest_evidence_paths,
                output_dir=output_dir,
                run_id="synthetic-parser-run-false-attestation",
                executed_at="2026-08-26T11:00:00+08:00",
            )
        self.assertFalse(output_dir.exists())

        valid_attestation_path = self._write_simulated_attestation(
            xml_path=xml_path,
            manifest_path=manifest_path,
            environment_path=environment_path,
            stage_paths=stage_paths,
        )
        missing_action_output = self.root / "analysis-without-post-action-log"
        with self.assertRaises(NativeEvidenceError):
            analyse_msproject_native_output(
                repository_root=self.repository_root,
                native_output_path=xml_path,
                case_realisation_manifest_path=manifest_path,
                environment_capture_path=environment_path,
                post_execution_attestation_path=valid_attestation_path,
                post_execution_action_log_path=self.root / "missing-action-log.json",
                stage_artifact_paths=stage_paths,
                independent_evidence_artifact_paths=self.latest_evidence_paths,
                output_dir=missing_action_output,
                run_id="synthetic-parser-run-no-action-log",
                executed_at="2026-08-26T11:00:00+08:00",
            )
        self.assertFalse(missing_action_output.exists())

    def test_analysis_requires_exact_track_stage_artifacts(self) -> None:
        xml_path, manifest_path, environment_path, sealed_path, stage_paths = (
            self._analysis_inputs()
        )
        attestation_path = self._write_simulated_attestation(
            xml_path=xml_path,
            manifest_path=manifest_path,
            environment_path=environment_path,
            stage_paths=stage_paths,
        )
        with self.assertRaisesRegex(NativeOutputError, "must contain exactly"):
            analyse_msproject_native_output(
                repository_root=self.repository_root,
                native_output_path=xml_path,
                case_realisation_manifest_path=manifest_path,
                environment_capture_path=environment_path,
                post_execution_attestation_path=attestation_path,
                post_execution_action_log_path=self.latest_action_log_path,
                stage_artifact_paths={},
                independent_evidence_artifact_paths=self.latest_evidence_paths,
                output_dir=self.root / "analysis-missing-stage",
                run_id="synthetic-parser-run-missing-stage",
                executed_at="2026-08-26T11:00:00+08:00",
            )

    def test_simulated_attested_parser_failure_is_retained_without_pass(self) -> None:
        """Test-only attestation exercises failure retention; it is not native evidence."""

        xml_path, manifest_path, environment_path, sealed_path, stage_paths = (
            self._analysis_inputs(
                xml_text=self._synthetic_xml(start_b="2026-01-05T14:30:00")
            )
        )
        attestation_path = self._write_simulated_attestation(
            xml_path=xml_path,
            manifest_path=manifest_path,
            environment_path=environment_path,
            stage_paths=stage_paths,
        )
        analysis = analyse_msproject_native_output(
            repository_root=self.repository_root,
            native_output_path=xml_path,
            case_realisation_manifest_path=manifest_path,
            environment_capture_path=environment_path,
            post_execution_attestation_path=attestation_path,
            post_execution_action_log_path=self.latest_action_log_path,
            stage_artifact_paths=stage_paths,
            independent_evidence_artifact_paths=self.latest_evidence_paths,
            output_dir=self.root / "analysis",
            run_id="synthetic-parser-run-001",
            executed_at="2026-08-26T11:00:00+08:00",
        )
        self.assertEqual(analysis.native_run_record["status"], "executed_fail")
        self.assertEqual(analysis.normalized_output["normalization_status"], "failed")
        validate_native_run_record(
            repository_root=self.repository_root,
            record=analysis.native_run_record,
        )
        invalid_record = dict(analysis.native_run_record)
        invalid_record["unexpected"] = True
        with self.assertRaisesRegex(NativeOutputError, "nativeRunEvidenceRecord"):
            validate_native_run_record(
                repository_root=self.repository_root,
                record=invalid_record,
            )
        self.assertFalse(analysis.redacted_evidence_manifest_draft["commit_as_claim_evidence"])
        self.assertEqual(
            analysis.redacted_evidence_manifest_draft["document_classification"],
            "non_claimable_incomplete_draft",
        )
        self.assertFalse(
            analysis.redacted_evidence_manifest_draft["claim_evidence_eligible"]
        )
        self.assertFalse(
            analysis.redacted_evidence_manifest_draft[
                "repository_evidence_index_ingestion_permitted"
            ]
        )
        self.assertTrue(
            analysis.redacted_evidence_manifest_draft[
                "must_not_be_committed_or_indexed_as_claim_evidence"
            ]
        )
        self.assertTrue(
            analysis.redacted_evidence_manifest_draft[
                "native_run_record_created"
            ]
        )
        self.assertFalse(
            analysis.redacted_evidence_manifest_draft[
                "native_run_record_accepted_as_claim_evidence"
            ]
        )
        self.assertEqual(
            analysis.redacted_evidence_manifest_draft[
                "required_frozen_redacted_manifest_fields_missing"
            ],
            [
                "preregistration_id",
                "preregistration_raw_sha256",
                "comparison_profile_id",
                "comparison_profile_raw_sha256",
                "case_outcomes",
                "artifact_index",
                "environment_capture_sha256",
                "difference_manifest_sha256",
                "created_at",
            ],
        )
        self.assertEqual(
            analysis.redacted_evidence_manifest_draft[
                "required_frozen_redacted_manifest_fields_nonfinal"
            ],
            ["schema_version", "review_disposition"],
        )
        self.assertEqual(
            analysis.redacted_evidence_manifest_draft[
                "required_frozen_artifact_roles_missing"
            ],
            [
                "preregistration",
                "comparison_profile",
                "case_realization_manifest",
                "environment_capture",
                "native_input",
                "native_stage_output",
                "normalized_output",
                "field_difference_manifest",
                "manual_action_log",
                "independent_review",
            ],
        )
        emitted = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted(analysis.output_dir.glob("*.json"))
        )
        self.assertNotIn('"status":"executed_pass"', emitted)
        self.assertNotIn('"full_45_case_gate_satisfied":true', emitted)

    def test_normalized_observation_is_durable_before_missing_oracle_is_opened(self) -> None:
        """A missing comparison control must not erase the native observation."""

        xml_path, manifest_path, environment_path, sealed_path, stage_paths = (
            self._analysis_inputs()
        )
        attestation_path = self._write_simulated_attestation(
            xml_path=xml_path,
            manifest_path=manifest_path,
            environment_path=environment_path,
            stage_paths=stage_paths,
        )
        sealed_path.unlink()
        self.mock_seal_release.reset_mock()
        output_dir = self.root / "analysis-missing-sealed-oracle"
        original_snapshot_reader = read_regular_file_snapshot

        def observed_snapshot_read(path: Path, *, label: str, max_bytes=None):
            if label == "sealed expected artifact":
                retained = output_dir / "normalized-native-output.json"
                self.assertTrue(retained.is_file())
                retained_document = json.loads(retained.read_text(encoding="utf-8"))
                self.assertEqual(
                    _raw_sha(retained),
                    hashlib.sha256(
                        (canonical_text(retained_document) + "\n").encode("utf-8")
                    ).hexdigest(),
                )
            return original_snapshot_reader(path, label=label, max_bytes=max_bytes)

        with patch(
            "deterministic_scheduling_core.native.msproject.normalizer."
            "read_regular_file_snapshot",
            side_effect=observed_snapshot_read,
        ):
            analysis = analyse_msproject_native_output(
                repository_root=self.repository_root,
                native_output_path=xml_path,
                case_realisation_manifest_path=manifest_path,
                environment_capture_path=environment_path,
                post_execution_attestation_path=attestation_path,
                post_execution_action_log_path=self.latest_action_log_path,
                stage_artifact_paths=stage_paths,
                independent_evidence_artifact_paths=self.latest_evidence_paths,
                output_dir=output_dir,
                run_id="synthetic-parser-run-missing-oracle",
                executed_at="2026-08-26T11:00:00+08:00",
            )

        retained = output_dir / "normalized-native-output.json"
        self.assertEqual(analysis.native_run_record["status"], "executed_inconclusive")
        self.assertEqual(
            analysis.native_run_record["normalized_output_sha256"], _raw_sha(retained)
        )
        self.assertEqual(
            analysis.difference_manifest["comparison_status"], "not_completed"
        )
        self.assertFalse(analysis.difference_manifest["claim_field_failure"])
        self.assertIn(
            "sealed expected comparison did not complete",
            analysis.native_run_record["failure_or_inconclusive_reason"],
        )

    def test_normalized_observation_is_synced_before_oracle_release(self) -> None:
        """The observation file and directory are synced before oracle access."""

        xml_path, manifest_path, environment_path, sealed_path, stage_paths = (
            self._analysis_inputs()
        )
        attestation_path = self._write_simulated_attestation(
            xml_path=xml_path,
            manifest_path=manifest_path,
            environment_path=environment_path,
            stage_paths=stage_paths,
        )
        output_dir = self.root / "analysis-durable-before-oracle"
        events: list[str] = []
        original_fsync = os.fsync

        def observed_fsync(file_descriptor: int) -> None:
            metadata = os.fstat(file_descriptor)
            if stat.S_ISREG(metadata.st_mode):
                self.assertGreater(
                    metadata.st_size,
                    0,
                    "the buffered observation must be flushed before file fsync",
                )
                events.append("file_fsync")
            elif stat.S_ISDIR(metadata.st_mode):
                events.append("directory_fsync")
            else:
                self.fail("durability fsync used an unexpected file type")
            original_fsync(file_descriptor)

        def observed_release(**kwargs):
            retained = output_dir / "normalized-native-output.json"
            self.assertTrue(retained.is_file())
            self.assertEqual(events, ["file_fsync", "directory_fsync"])
            events.append("sealed_oracle_release")
            return self._release_synthetic_sealed_expected(**kwargs)

        self.mock_seal_release.side_effect = observed_release
        with patch(
            "deterministic_scheduling_core.native.msproject.normalizer.os.fsync",
            side_effect=observed_fsync,
        ):
            analyse_msproject_native_output(
                repository_root=self.repository_root,
                native_output_path=xml_path,
                case_realisation_manifest_path=manifest_path,
                environment_capture_path=environment_path,
                post_execution_attestation_path=attestation_path,
                post_execution_action_log_path=self.latest_action_log_path,
                stage_artifact_paths=stage_paths,
                independent_evidence_artifact_paths=self.latest_evidence_paths,
                output_dir=output_dir,
                run_id="synthetic-parser-run-durable-before-oracle",
                executed_at="2026-08-26T11:00:00+08:00",
            )

        self.assertEqual(
            events,
            ["file_fsync", "directory_fsync", "sealed_oracle_release"],
        )

    def test_observation_fsync_failures_block_oracle_release(self) -> None:
        """File or directory sync failure leaves the sealed oracle unopened."""

        original_fsync = os.fsync
        for failed_kind in ("file", "directory"):
            with self.subTest(failed_kind=failed_kind):
                (
                    xml_path,
                    manifest_path,
                    environment_path,
                    sealed_path,
                    stage_paths,
                ) = self._analysis_inputs()
                attestation_path = self._write_simulated_attestation(
                    xml_path=xml_path,
                    manifest_path=manifest_path,
                    environment_path=environment_path,
                    stage_paths=stage_paths,
                )
                output_dir = self.root / f"analysis-{failed_kind}-fsync-failure"

                def failing_fsync(file_descriptor: int) -> None:
                    metadata = os.fstat(file_descriptor)
                    descriptor_kind = (
                        "file" if stat.S_ISREG(metadata.st_mode) else "directory"
                    )
                    if descriptor_kind == failed_kind:
                        raise OSError(f"synthetic {failed_kind} fsync failure")
                    original_fsync(file_descriptor)

                self.mock_seal_release.reset_mock()
                with patch(
                    "deterministic_scheduling_core.native.msproject.normalizer.os.fsync",
                    side_effect=failing_fsync,
                ):
                    with self.assertRaisesRegex(
                        NativeOutputError,
                        "could not durably persist normalized native observation",
                    ) as raised:
                        analyse_msproject_native_output(
                            repository_root=self.repository_root,
                            native_output_path=xml_path,
                            case_realisation_manifest_path=manifest_path,
                            environment_capture_path=environment_path,
                            post_execution_attestation_path=attestation_path,
                            post_execution_action_log_path=self.latest_action_log_path,
                            stage_artifact_paths=stage_paths,
                            independent_evidence_artifact_paths=self.latest_evidence_paths,
                            output_dir=output_dir,
                            run_id=f"synthetic-parser-run-{failed_kind}-fsync-failure",
                            executed_at="2026-08-26T11:00:00+08:00",
                        )

                self.assertEqual(raised.exception.outcome, "executed_inconclusive")
                self.mock_seal_release.assert_not_called()

    def test_track_b_ignores_oracle_and_uses_only_exact_pre_post_stability(self) -> None:
        """Synthetic stable observations may differ from the Track-A oracle."""

        observed = self._synthetic_xml(start_b="2026-01-05T15:00:00")
        observed = observed.replace(
            "<FinishDate>2026-01-05T17:00:00</FinishDate>",
            "<FinishDate>2026-01-05T18:00:00</FinishDate>",
            1,
        ).replace(
            "<Finish>2026-01-05T17:00:00</Finish>",
            "<Finish>2026-01-05T18:00:00</Finish>",
            1,
        )
        (
            xml_path,
            manifest_path,
            environment_path,
            sealed_path,
            stage_paths,
            attestation_path,
        ) = self._track_b_inputs(
            pre_close_xml=observed,
            post_recalculate_xml=observed,
        )
        sealed_path.unlink()
        self.mock_seal_release.reset_mock()
        with patch(
            "deterministic_scheduling_core.native.msproject.normalizer."
            "compare_normalized_output",
            side_effect=AssertionError("Track B must not consult the Track-A oracle"),
        ):
            analysis = analyse_msproject_native_output(
                repository_root=self.repository_root,
                native_output_path=xml_path,
                case_realisation_manifest_path=manifest_path,
                environment_capture_path=environment_path,
                post_execution_attestation_path=attestation_path,
                post_execution_action_log_path=self.latest_action_log_path,
                prerequisite_manual_case_realization_manifest_path=(
                    self.latest_prerequisite_path
                ),
                stage_artifact_paths=stage_paths,
                independent_evidence_artifact_paths=self.latest_evidence_paths,
                output_dir=self.root / "synthetic-track-b-oracle-independent",
                run_id="synthetic-track-b-oracle-independent",
                executed_at="2026-08-26T11:00:00+08:00",
            )

        stability = analysis.evidence_bundle["reopen_stability_evidence"]
        self.assertTrue(stability["exact_normalized_stability"])
        self.assertFalse(stability["expected_oracle_used_for_stability_comparison"])
        self.assertEqual(analysis.native_run_record["status"], "executed_inconclusive")
        self.assertEqual(
            analysis.difference_manifest["comparison_status"],
            "not_applicable_for_reopen_stability_track",
        )
        self.assertFalse(analysis.difference_manifest["expected_oracle_used"])
        self.assertFalse(analysis.difference_manifest["claim_field_failure"])
        self.assertNotIn("sealed_expected", analysis.evidence_bundle["artifact_hashes"])
        self.mock_seal_release.assert_not_called()
        self.assertEqual(
            analysis.native_run_record["fixture_raw_sha256"],
            EXPECTED_FIXTURE_SHA256_BY_FILENAME["sem-rel-001.json"],
        )

    def test_analyser_api_has_no_caller_selected_sealed_expected_path(self) -> None:
        self.assertNotIn(
            "sealed_expected_path", analyse_msproject_native_output.__annotations__
        )

    def test_track_a_still_fails_a_sealed_claim_field_mismatch(self) -> None:
        """The Track B separation must not weaken Track A comparison."""

        observed = self._synthetic_xml(start_b="2026-01-05T15:00:00")
        observed = observed.replace(
            "<FinishDate>2026-01-05T17:00:00</FinishDate>",
            "<FinishDate>2026-01-05T18:00:00</FinishDate>",
            1,
        ).replace(
            "<Finish>2026-01-05T17:00:00</Finish>",
            "<Finish>2026-01-05T18:00:00</Finish>",
            1,
        )
        xml_path, manifest_path, environment_path, sealed_path, stage_paths = (
            self._analysis_inputs(xml_text=observed)
        )
        attestation_path = self._write_simulated_attestation(
            xml_path=xml_path,
            manifest_path=manifest_path,
            environment_path=environment_path,
            stage_paths=stage_paths,
        )
        analysis = analyse_msproject_native_output(
            repository_root=self.repository_root,
            native_output_path=xml_path,
            case_realisation_manifest_path=manifest_path,
            environment_capture_path=environment_path,
            post_execution_attestation_path=attestation_path,
            post_execution_action_log_path=self.latest_action_log_path,
            stage_artifact_paths=stage_paths,
            independent_evidence_artifact_paths=self.latest_evidence_paths,
            output_dir=self.root / "synthetic-track-a-claim-mismatch",
            run_id="synthetic-track-a-claim-mismatch",
            executed_at="2026-08-26T11:00:00+08:00",
        )
        self.assertEqual(analysis.native_run_record["status"], "executed_fail")
        self.assertTrue(analysis.difference_manifest["claim_field_failure"])
        self.assertIn(
            "one or more claim fields differ",
            analysis.native_run_record["failure_or_inconclusive_reason"],
        )

    def test_analysis_revalidates_the_sealed_full_fixture_binding(self) -> None:
        """Synthetic control tampering must block oracle release, not create a result."""

        xml_path, manifest_path, environment_path, sealed_path, stage_paths = (
            self._analysis_inputs()
        )
        sealed = json.loads(sealed_path.read_text(encoding="utf-8"))
        sealed["source_bindings"]["fixture"]["raw_sha256"] = "0" * 64
        write_canonical_json(sealed_path, sealed)
        write_canonical_json(manifest_path, self.manifest)
        action_log = json.loads(
            self.latest_action_log_path.read_text(encoding="utf-8")
        )
        action_log["case_realization_manifest_sha256"] = _raw_sha(manifest_path)
        write_canonical_json(self.latest_action_log_path, action_log)
        attestation_path = self._write_simulated_attestation(
            xml_path=xml_path,
            manifest_path=manifest_path,
            environment_path=environment_path,
            stage_paths=stage_paths,
        )
        analysis = analyse_msproject_native_output(
            repository_root=self.repository_root,
            native_output_path=xml_path,
            case_realisation_manifest_path=manifest_path,
            environment_capture_path=environment_path,
            post_execution_attestation_path=attestation_path,
            post_execution_action_log_path=self.latest_action_log_path,
            stage_artifact_paths=stage_paths,
            independent_evidence_artifact_paths=self.latest_evidence_paths,
            output_dir=self.root / "synthetic-sealed-binding-mismatch",
            run_id="synthetic-sealed-binding-mismatch",
            executed_at="2026-08-26T11:00:00+08:00",
        )
        self.assertEqual("executed_inconclusive", analysis.native_run_record["status"])
        self.assertFalse(analysis.difference_manifest["expected_oracle_used"])
        self.assertIn(
            "full-fixture digest does not match the frozen manifest",
            analysis.native_run_record["failure_or_inconclusive_reason"],
        )

    def test_track_b_compares_pre_and_post_with_missing_null_distinct(self) -> None:
        """Synthetic Track B files are parser data, never Microsoft Project evidence."""

        post_xml = self._synthetic_xml()
        pre_xml = post_xml.replace(
            '        <Resume xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:nil="true"/>\n',
            "",
            1,
        )
        (
            xml_path,
            manifest_path,
            environment_path,
            sealed_path,
            stage_paths,
            attestation_path,
        ) = self._track_b_inputs(
            pre_close_xml=pre_xml,
            post_recalculate_xml=post_xml,
        )
        analysis = analyse_msproject_native_output(
            repository_root=self.repository_root,
            native_output_path=xml_path,
            case_realisation_manifest_path=manifest_path,
            environment_capture_path=environment_path,
            post_execution_attestation_path=attestation_path,
            post_execution_action_log_path=self.latest_action_log_path,
            prerequisite_manual_case_realization_manifest_path=(
                self.latest_prerequisite_path
            ),
            stage_artifact_paths=stage_paths,
            independent_evidence_artifact_paths=self.latest_evidence_paths,
            output_dir=self.root / "synthetic-track-b-mismatch-analysis",
            run_id="synthetic-track-b-missing-null-mismatch",
            executed_at="2026-08-26T11:00:00+08:00",
        )
        self.assertEqual(analysis.native_run_record["status"], "executed_fail")
        stability = json.loads(
            (analysis.output_dir / "reopen-stability-difference.json").read_text(
                encoding="utf-8"
            )
        )
        remaining = next(
            record
            for record in stability["records"]
            if record["field_path"] == "activity_times.B.remaining_start"
        )
        self.assertEqual(remaining["pre_close_state"], {"presence": "missing"})
        self.assertEqual(
            remaining["post_recalculate_state"],
            {"presence": "present", "value": None},
        )
        self.assertFalse(stability["exact_normalized_stability"])
        self.assertFalse(stability["expected_oracle_used"])
        self.assertIn(
            "stability_difference_sha256",
            analysis.evidence_bundle["reopen_stability_evidence"],
        )

    def test_track_b_analysis_rejects_missing_or_wrong_prerequisite_bytes(self) -> None:
        (
            xml_path,
            manifest_path,
            environment_path,
            sealed_path,
            stage_paths,
            attestation_path,
        ) = self._track_b_inputs(
            pre_close_xml=self._synthetic_xml(),
            post_recalculate_xml=self._synthetic_xml(),
        )
        common = {
            "repository_root": self.repository_root,
            "native_output_path": xml_path,
            "case_realisation_manifest_path": manifest_path,
            "environment_capture_path": environment_path,
            "post_execution_attestation_path": attestation_path,
            "post_execution_action_log_path": self.latest_action_log_path,
            "stage_artifact_paths": stage_paths,
            "independent_evidence_artifact_paths": self.latest_evidence_paths,
            "run_id": "synthetic-track-b-prerequisite-rejection",
            "executed_at": "2026-08-26T11:00:00+08:00",
        }
        with self.assertRaisesRegex(NativeOutputError, "requires the bound prerequisite"):
            analyse_msproject_native_output(
                **common,
                output_dir=self.root / "missing-track-a-prerequisite",
            )
        wrong = self.root / "synthetic-wrong-track-a-prerequisite.json"
        wrong_document = json.loads(
            self.latest_prerequisite_path.read_text(encoding="utf-8")
        )
        wrong_document["unexpected"] = True
        write_canonical_json(wrong, wrong_document)
        with self.assertRaisesRegex(NativeOutputError, "prerequisite bytes"):
            analyse_msproject_native_output(
                **common,
                prerequisite_manual_case_realization_manifest_path=wrong,
                output_dir=self.root / "wrong-track-a-prerequisite",
            )

    def test_track_b_retains_pre_close_parser_failure(self) -> None:
        """Synthetic malformed XML verifies retention, not native behavior."""

        (
            xml_path,
            manifest_path,
            environment_path,
            sealed_path,
            stage_paths,
            attestation_path,
        ) = self._track_b_inputs(
            pre_close_xml="<synthetic-test-only-malformed",
            post_recalculate_xml=self._synthetic_xml(),
        )
        analysis = analyse_msproject_native_output(
            repository_root=self.repository_root,
            native_output_path=xml_path,
            case_realisation_manifest_path=manifest_path,
            environment_capture_path=environment_path,
            post_execution_attestation_path=attestation_path,
            post_execution_action_log_path=self.latest_action_log_path,
            stage_artifact_paths=stage_paths,
            independent_evidence_artifact_paths=self.latest_evidence_paths,
            output_dir=self.root / "synthetic-track-b-parser-failure-analysis",
            run_id="synthetic-track-b-parser-failure",
            executed_at="2026-08-26T11:00:00+08:00",
            prerequisite_manual_case_realization_manifest_path=(
                self.latest_prerequisite_path
            ),
        )
        self.assertEqual(
            analysis.native_run_record["status"], "executed_inconclusive"
        )
        retained_pre = json.loads(
            (analysis.output_dir / "normalized-native-output-pre-close.json").read_text(
                encoding="utf-8"
            )
        )
        stability = json.loads(
            (analysis.output_dir / "reopen-stability-difference.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(retained_pre["normalization_status"], "failed")
        self.assertEqual(stability["comparison_status"], "not_completed")
        self.assertIn("pre_close", stability["errors_by_observation"])


if __name__ == "__main__":
    unittest.main()
