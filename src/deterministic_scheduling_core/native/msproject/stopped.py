from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re
from typing import Any

from rfc3339_validator import validate_rfc3339

from deterministic_scheduling_core.provenance.canonical_json import write_canonical_json

from .freeze import (
    EXECUTION_TRACK_IDS,
    NATIVE_SYSTEM,
    PILOT_ID,
    PILOT_INDEX_RELATIVE_PATH,
    NativeEvidenceError,
    RegularFileSnapshot,
    _binding_id,
    _binding_path,
    _case_entry,
    _declared_track_ids,
    _environment_capture,
    _fixture_binding,
    _named_binding,
    _prepare_new_output_directory,
    _require_nonblank,
    _require_sha256,
    _safe_repository_file,
    load_canonical_json_snapshot,
    read_regular_file_snapshot,
    validate_case_realisation_manifest_against_repository,
)


STOP_RECORD_FILENAME = "native-attempt-stop-record.json"
STOP_CONDITION_IDS = (
    "project_silently_changed_source_field",
    "unsupported_mspdi_data_discarded",
    "task_mode_changed",
    "relationship_or_lag_transformed",
    "timezone_or_locale_created_off_grid_time",
    "resource_leveling_ran",
    "unapproved_transformation_required",
    "native_calculation_occurred_before_preexecution_freeze",
    "native_input_or_evidence_changed_during_capture",
    "required_environment_or_evidence_unavailable",
)
STOP_OUTCOME_CLASSIFICATIONS = (
    "not_executed",
    "executed_inconclusive",
    "executed_fail",
)
STOP_OUTCOME_BY_CONDITION_AND_NATIVE_CALCULATION = {
    "project_silently_changed_source_field": {
        False: "not_executed",
        True: "executed_fail",
    },
    "unsupported_mspdi_data_discarded": {
        False: "not_executed",
        True: "executed_inconclusive",
    },
    "task_mode_changed": {
        False: "not_executed",
        True: "executed_inconclusive",
    },
    "relationship_or_lag_transformed": {
        False: "not_executed",
        True: "executed_fail",
    },
    "timezone_or_locale_created_off_grid_time": {
        False: "not_executed",
        True: "executed_fail",
    },
    "resource_leveling_ran": {
        False: "not_executed",
        True: "executed_inconclusive",
    },
    "unapproved_transformation_required": {
        False: "not_executed",
        True: "executed_fail",
    },
    "native_calculation_occurred_before_preexecution_freeze": {
        True: "executed_inconclusive"
    },
    "native_input_or_evidence_changed_during_capture": {
        False: "not_executed",
        True: "executed_inconclusive",
    },
    "required_environment_or_evidence_unavailable": {
        False: "not_executed",
        True: "executed_inconclusive",
    },
}
STOP_RECORD_REQUIRED_FIELDS = (
    "schema_version",
    "record_type",
    "pilot_id",
    "pilot_index_raw_sha256",
    "native_system",
    "case_id",
    "execution_track_id",
    "preregistration_id",
    "preregistration_path",
    "preregistration_raw_sha256",
    "comparison_profile_id",
    "comparison_profile_path",
    "comparison_profile_raw_sha256",
    "fixture_path",
    "fixture_raw_sha256",
    "stopped_at",
    "recorded_by",
    "stop_condition_id",
    "reason",
    "frozen_outcome_classification",
    "native_calculation_observed",
    "case_realisation_manifest_available",
    "case_realisation_manifest_sha256",
    "environment_capture_available",
    "environment_capture_sha256",
    "observed_artifacts",
    "missing_required_evidence",
    "claim_boundary",
)


class NativeAttemptStopError(NativeEvidenceError):
    """A stopped-attempt record is ambiguous, unsafe, or claim-like."""


@dataclass(frozen=True, slots=True)
class StoppedNativeAttempt:
    record: dict[str, Any]
    record_path: Path
    record_sha256: str


def _media_type(path: Path, snapshot: RegularFileSnapshot) -> str:
    media_types = {
        ".mpp": "application/vnd.ms-project",
        ".xml": "application/xml",
        ".json": "application/json",
        ".png": "image/png",
        ".pdf": "application/pdf",
        ".csv": "text/csv",
        ".txt": "text/plain",
    }
    media_type = media_types.get(path.suffix.lower())
    if media_type is None:
        raise NativeAttemptStopError(
            f"stopped-attempt artifact {path.name!r} has an unsupported media type"
        )
    if path.suffix.lower() == ".png" and not snapshot.data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise NativeAttemptStopError("stopped-attempt PNG artifact has an invalid signature")
    if path.suffix.lower() == ".pdf" and not snapshot.data.startswith(b"%PDF-"):
        raise NativeAttemptStopError("stopped-attempt PDF artifact has an invalid signature")
    if path.suffix.lower() == ".mpp" and not snapshot.data.startswith(
        b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    ):
        raise NativeAttemptStopError("stopped-attempt MPP artifact has an invalid CFB signature")
    return media_type


def record_msproject_native_attempt_stop(
    *,
    repository_root: Path,
    pilot_id: str,
    case_id: str,
    track_id: str,
    stopped_at: str,
    recorded_by: str,
    stop_condition_id: str,
    reason: str,
    outcome_classification: str,
    native_calculation_observed: bool,
    output_dir: Path,
    case_realisation_manifest_path: Path | None = None,
    environment_capture_path: Path | None = None,
    observed_artifact_paths: Mapping[str, Path] | None = None,
) -> StoppedNativeAttempt:
    """Record an aborted native attempt without creating native run evidence.

    This record exists specifically for stop conditions, including a calculation
    that happened before the pre-execution freeze.  It cannot be promoted to an
    executed pass or ingested as a frozen ``nativeRunEvidenceRecord``.
    """

    repository_root = repository_root.resolve()
    if not repository_root.is_dir():
        raise NativeAttemptStopError("repository_root must be a directory")
    if pilot_id != PILOT_ID:
        raise NativeAttemptStopError(f"unsupported pilot {pilot_id!r}")
    if track_id not in EXECUTION_TRACK_IDS:
        raise NativeAttemptStopError(f"unknown execution track {track_id!r}")
    if stop_condition_id not in STOP_CONDITION_IDS:
        raise NativeAttemptStopError(f"unknown stop condition {stop_condition_id!r}")
    if outcome_classification not in STOP_OUTCOME_CLASSIFICATIONS:
        raise NativeAttemptStopError("stopped-attempt outcome classification is invalid")
    if not isinstance(native_calculation_observed, bool):
        raise NativeAttemptStopError("native_calculation_observed must be Boolean")
    allowed_by_observation = STOP_OUTCOME_BY_CONDITION_AND_NATIVE_CALCULATION[
        stop_condition_id
    ]
    expected_outcome = allowed_by_observation.get(native_calculation_observed)
    if expected_outcome is None:
        raise NativeAttemptStopError(
            f"stop condition {stop_condition_id} is incompatible with the native-calculation observation"
        )
    if outcome_classification != expected_outcome:
        raise NativeAttemptStopError(
            f"stop condition {stop_condition_id} with native_calculation_observed="
            f"{native_calculation_observed} requires {expected_outcome}"
        )
    if not isinstance(stopped_at, str) or not validate_rfc3339(stopped_at):
        raise NativeAttemptStopError("stopped_at must be timezone-qualified RFC 3339")
    recorded_by = _require_nonblank(recorded_by, field="recorded_by")
    reason = _require_nonblank(reason, field="reason")

    index_path = _safe_repository_file(
        repository_root, PILOT_INDEX_RELATIVE_PATH, label="tracked pilot index"
    )
    index, index_snapshot = load_canonical_json_snapshot(
        index_path, label="tracked pilot index"
    )
    if index.get("pilot_id") != PILOT_ID or index.get("status") != "prepared_not_executed":
        raise NativeAttemptStopError("tracked pilot index is not the prepared frozen pilot")
    if track_id not in _declared_track_ids(index):
        raise NativeAttemptStopError("execution track is not declared by the pilot")
    case = _case_entry(index, case_id)

    bindings: dict[str, dict[str, Any]] = {}
    protected_files: dict[tuple[int, int], str] = {
        index_snapshot.file_identity: "pilot_index"
    }
    for role in ("preregistration", "comparison_profile"):
        binding = _named_binding(index, role)
        relative_path = _binding_path(binding, label=role)
        path = _safe_repository_file(repository_root, relative_path, label=role)
        snapshot = read_regular_file_snapshot(path, label=role)
        declared = _require_sha256(binding.get("raw_sha256"), field=f"{role}.raw_sha256")
        if snapshot.sha256 != declared:
            raise NativeAttemptStopError(f"tracked {role} bytes changed")
        if snapshot.file_identity in protected_files:
            raise NativeAttemptStopError(
                f"tracked {role} aliases {protected_files[snapshot.file_identity]}"
            )
        protected_files[snapshot.file_identity] = role
        bindings[role] = {
            "id": _binding_id(binding, role),
            "path": relative_path,
            "raw_sha256": declared,
        }
    fixture = _fixture_binding(case)
    fixture_path_text = _binding_path(fixture, label="fixture")
    fixture_path = _safe_repository_file(
        repository_root, fixture_path_text, label="fixture"
    )
    fixture_snapshot = read_regular_file_snapshot(fixture_path, label="fixture")
    fixture_hash = _require_sha256(
        fixture.get("raw_sha256"), field=f"{case_id}.fixture.raw_sha256"
    )
    if fixture_snapshot.sha256 != fixture_hash:
        raise NativeAttemptStopError("tracked fixture bytes changed")
    if fixture_snapshot.file_identity in protected_files:
        raise NativeAttemptStopError(
            f"tracked fixture aliases {protected_files[fixture_snapshot.file_identity]}"
        )
    protected_files[fixture_snapshot.file_identity] = "fixture"

    manifest_document: Mapping[str, Any] | None = None
    manifest_snapshot: RegularFileSnapshot | None = None
    environment_snapshot: RegularFileSnapshot | None = None
    if case_realisation_manifest_path is not None:
        if environment_capture_path is None:
            raise NativeAttemptStopError(
                "a supplied case-realisation manifest requires its environment capture"
            )
        manifest_document, manifest_snapshot = load_canonical_json_snapshot(
            case_realisation_manifest_path, label="case-realisation manifest"
        )
        validate_case_realisation_manifest_against_repository(
            repository_root=repository_root,
            document=manifest_document,
            environment_capture_path=environment_capture_path,
        )
        if manifest_document.get("case_id") != case_id or manifest_document.get(
            "execution_track_id"
        ) != track_id:
            raise NativeAttemptStopError(
                "case-realisation manifest identity does not match the stopped attempt"
            )
        if manifest_snapshot.file_identity in protected_files:
            raise NativeAttemptStopError(
                "case-realisation manifest aliases frozen repository evidence"
            )
        protected_files[manifest_snapshot.file_identity] = "case_realisation_manifest"
        prepared_at = manifest_document.get("prepared_at")
        if not isinstance(prepared_at, str) or not validate_rfc3339(prepared_at):
            raise NativeAttemptStopError("case-realisation manifest prepared_at is invalid")
        if datetime.fromisoformat(stopped_at.replace("Z", "+00:00")) <= datetime.fromisoformat(
            prepared_at.replace("Z", "+00:00")
        ):
            raise NativeAttemptStopError("stopped_at must be after the pre-execution freeze")
    if environment_capture_path is not None:
        environment_document, environment_snapshot = load_canonical_json_snapshot(
            environment_capture_path, label="environment capture"
        )
        environment = _environment_capture(environment_document)
        if environment.get("execution_operator_id") != recorded_by:
            raise NativeAttemptStopError(
                "recorded_by must equal the captured execution_operator_id"
            )
        if manifest_document is not None and environment_snapshot.sha256 != manifest_document.get(
            "environment_capture_sha256"
        ):
            raise NativeAttemptStopError(
                "environment capture does not match the supplied case-realisation manifest"
            )
        if environment_snapshot.file_identity in protected_files:
            raise NativeAttemptStopError("environment capture aliases another evidence role")
        protected_files[environment_snapshot.file_identity] = "environment_capture"

    artifact_records: list[dict[str, Any]] = []
    digest_roles: dict[str, str] = {}
    for role, path in sorted((observed_artifact_paths or {}).items()):
        if re.fullmatch(r"[a-z][a-z0-9_]{0,63}", role) is None:
            raise NativeAttemptStopError(f"unsafe stopped-attempt artifact role {role!r}")
        snapshot = read_regular_file_snapshot(
            path, label=f"stopped-attempt artifact {role}", max_bytes=128 * 1024 * 1024
        )
        if snapshot.file_identity in protected_files:
            raise NativeAttemptStopError(
                f"stopped-attempt artifact {role} aliases "
                f"{protected_files[snapshot.file_identity]}"
            )
        if snapshot.sha256 in digest_roles:
            raise NativeAttemptStopError(
                f"stopped-attempt artifacts {digest_roles[snapshot.sha256]} and {role} "
                "reuse identical bytes"
            )
        protected_files[snapshot.file_identity] = role
        digest_roles[snapshot.sha256] = role
        artifact_records.append(
            {
                "artifact_role": role,
                "sha256": snapshot.sha256,
                "byte_size": snapshot.byte_size,
                "media_type": _media_type(path, snapshot),
                "raw_artifact_embedded": False,
                "claim_use_permitted": False,
            }
        )

    missing = [
        "post_execution_attestation",
        "complete_track_stage_artifacts",
        "normalized_native_output",
        "field_difference_manifest",
        "complete_independent_review_evidence",
        "accepted_independent_review_disposition",
        "schema_conforming_committed_redacted_evidence_manifest",
        "complete_45_case_track_evidence",
    ]
    if manifest_snapshot is None:
        missing.insert(0, "valid_preexecution_case_realisation_manifest")
    if environment_snapshot is None:
        missing.insert(1 if manifest_snapshot is None else 0, "complete_environment_capture")
    record = {
        "schema_version": "microsoft-project-native-attempt-stop-record-v0.1",
        "record_type": "native_attempt_stop_non_claimable",
        "pilot_id": PILOT_ID,
        "pilot_index_raw_sha256": index_snapshot.sha256,
        "native_system": NATIVE_SYSTEM,
        "case_id": case_id,
        "execution_track_id": track_id,
        "preregistration_id": bindings["preregistration"]["id"],
        "preregistration_path": bindings["preregistration"]["path"],
        "preregistration_raw_sha256": bindings["preregistration"]["raw_sha256"],
        "comparison_profile_id": bindings["comparison_profile"]["id"],
        "comparison_profile_path": bindings["comparison_profile"]["path"],
        "comparison_profile_raw_sha256": bindings["comparison_profile"]["raw_sha256"],
        "fixture_path": fixture_path_text,
        "fixture_raw_sha256": fixture_hash,
        "stopped_at": stopped_at,
        "recorded_by": recorded_by,
        "stop_condition_id": stop_condition_id,
        "reason": reason,
        "frozen_outcome_classification": outcome_classification,
        "native_calculation_observed": native_calculation_observed,
        "case_realisation_manifest_available": manifest_snapshot is not None,
        "case_realisation_manifest_sha256": (
            manifest_snapshot.sha256 if manifest_snapshot is not None else None
        ),
        "environment_capture_available": environment_snapshot is not None,
        "environment_capture_sha256": (
            environment_snapshot.sha256 if environment_snapshot is not None else None
        ),
        "observed_artifacts": artifact_records,
        "missing_required_evidence": missing,
        "claim_boundary": {
            "native_run_evidence_record_exists": False,
            "executed_pass_permitted": False,
            "claim_evidence_eligible": False,
            "repository_evidence_index_ingestion_permitted": False,
            "full_45_case_gate_satisfied": False,
            "compatibility_claim_exists": False,
            "requires_new_frozen_realization_before_retry": True,
        },
    }
    if set(record) != set(STOP_RECORD_REQUIRED_FIELDS):
        raise AssertionError("stopped-attempt record field contract drifted")
    output_dir = _prepare_new_output_directory(
        output_dir, purpose="microsoft-project-native-attempt-stop"
    )
    record_path = output_dir / STOP_RECORD_FILENAME
    write_canonical_json(record_path, record)
    record_snapshot = read_regular_file_snapshot(record_path, label="stopped-attempt record")
    return StoppedNativeAttempt(
        record=record,
        record_path=record_path,
        record_sha256=record_snapshot.sha256,
    )


__all__ = [
    "NativeAttemptStopError",
    "STOP_CONDITION_IDS",
    "STOP_OUTCOME_CLASSIFICATIONS",
    "STOP_OUTCOME_BY_CONDITION_AND_NATIVE_CALCULATION",
    "STOP_RECORD_FILENAME",
    "STOP_RECORD_REQUIRED_FIELDS",
    "StoppedNativeAttempt",
    "record_msproject_native_attempt_stop",
]
