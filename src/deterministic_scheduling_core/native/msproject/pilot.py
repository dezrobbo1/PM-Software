"""Deterministic preparation and verification for the Microsoft Project pilot.

This module deliberately stops at preparation.  It never starts Microsoft
Project, never emits MSPDI XML, and never classifies a native case as passing.
The generated kit keeps operator instructions, independent review controls,
and sealed reference expectations in distinct files.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Mapping

from deterministic_scheduling_core.provenance.canonical_json import canonical_bytes

from .freeze import (
    INDEPENDENT_VERIFICATION_EVIDENCE_ROLES,
    OBSERVED_PRODUCT_SETTING_IDS,
    PRE_EXECUTION_ACTION_IDS,
)
from .stopped import (
    STOP_CONDITION_IDS,
    STOP_OUTCOME_BY_CONDITION_AND_NATIVE_CALCULATION,
    STOP_OUTCOME_CLASSIFICATIONS,
    STOP_RECORD_REQUIRED_FIELDS,
)


PILOT_ID = "microsoft-project-relationship-v0.1"
PILOT_STATUS = "prepared_not_executed"
PREREGISTRATION_ID = "microsoft-project-semantic-microcases-v0.1"
COMPARISON_PROFILE_ID = "microsoft-project-semantic-comparison-profile-v0.1"

CASE_IDS = tuple(f"SEM-REL-{number:03d}" for number in range(1, 13))
TRACK_IDS = (
    "manual_native_semantic_parity",
    "saved_file_reopen_recalculate_stability",
    "adapter_interchange_round_trip",
)
FULL_PROFILE_CLAIM_ELIGIBLE_CASE_COUNT = 45
PILOT_INPUT_IDENTITY_DOMAIN = (
    "microsoft-project-relationship-pilot-input-identity-v0.2"
)

OWNER_MARKER = ".pilot-kit-owner.json"
PILOT_INDEX = "pilot-index.json"
MAPPING_SOURCE_REGISTER = "mapping-source-register.json"
OPERATOR_ENVIRONMENT_TEMPLATE = "operator-environment-template.json"
POST_EXECUTION_ATTESTATION_TEMPLATE = "post-execution-attestation-template.json"
NATIVE_ATTEMPT_STOP_TEMPLATE = "native-attempt-stop-record-template.json"
TRACK_A_POST_EXECUTION_ACTION_LOG_TEMPLATE = (
    "tracks/manual_native_semantic_parity/post-execution-action-log-template.json"
)
TRACK_B_POST_EXECUTION_ACTION_LOG_TEMPLATE = (
    "tracks/saved_file_reopen_recalculate_stability/"
    "post-execution-action-log-template.json"
)
OPERATOR_RUNBOOK = "operator-runbook.md"
MANIFEST = "pilot-kit-manifest.json"
MANIFEST_CHECKSUM = "pilot-kit-manifest.sha256"
SOURCE_ONLY_PROJECTION_DIRECTORY = "source-only-case-projections"
SEALED_CONTROL_DIRECTORY = "sealed-expected-normalized"
SEALED_CONTROL_INDEX = f"{SEALED_CONTROL_DIRECTORY}/sealed-control-index.json"
BLINDING_CLASSIFICATION = "procedural_non_access_controlled"

PREREGISTRATION_PATH = (
    "native-validation/preregistrations/"
    "microsoft-project-semantic-microcases-v0.1.json"
)
PROFILE_PATH = (
    "native-validation/profiles/"
    "microsoft-project-semantic-comparison-profile-v0.1.json"
)
PREREGISTRATION_RAW_SHA256 = (
    "69594ba766cea5f204bc41f99f49af28a65b6f543919dad2bee702a9f6e0b647"
)
PROFILE_RAW_SHA256 = (
    "8ab9c47395897e13f5b6cf36773757f4bd5a273e997b81de78585d76e872a469"
)

POST_EXECUTION_ACTION_IDS_BY_TRACK: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "manual_native_semantic_parity": (
            "calculate_project",
            "save_calculated_native_file",
            "export_post_calculation_mspdi",
            "finalize_stage_and_independent_evidence",
        ),
        "saved_file_reopen_recalculate_stability": (
            "capture_pre_close_file_and_output",
            "save_and_close_project",
            "reopen_saved_project",
            "capture_reopened_file_before_recalculation",
            "recalculate_project",
            "capture_recalculated_file_and_post_output",
            "finalize_stage_and_independent_evidence",
        ),
        "adapter_interchange_round_trip": (
            "open_frozen_mspdi_input",
            "calculate_project",
            "save_native_pre_export_file",
            "export_mspdi_xml",
            "canonical_reimport",
            "controlled_reexport",
            "reopen_and_recalculate_native_file",
            "finalize_stage_and_independent_evidence",
        ),
    }
)

FIXTURE_RAW_SHA256_BY_CASE_ID: Mapping[str, str] = MappingProxyType(
    {
        "SEM-REL-001": "36d65aa5a19ba602439b08248efa3f8a9965fee1cf98bbb19744e4153aef179e",
        "SEM-REL-002": "15b1a60e5759673a95b5ac1dfb347281d6ee9fe03cf2e5db4a247a56ee4df666",
        "SEM-REL-003": "589c43c7f16080321a6a4f872e5ad49bb4b2e0fb3442e1e986b014bafffb42dc",
        "SEM-REL-004": "a96c684f71581e415a5b299edc94a49cfbde2d4e56cb628d71da7cb61a4c5f31",
        "SEM-REL-005": "6a26bd0e826b7c61c73def94f2148f8907c3831040874a7a0b81c8a4c738e6bc",
        "SEM-REL-006": "97280f6a3d1765a8c0356a79e09e5fb42dcfa8b589fe5111e25cc7258f21db42",
        "SEM-REL-007": "bb5d9ebd5b1e95ada392ab012b8cbc485e517532b9f7b85408a2577def6070f0",
        "SEM-REL-008": "962b2afab50e152be7133374455ae99d807d1923f216e0381abc10ce21d72c3f",
        "SEM-REL-009": "7da1850a63a44d540b24f429a000c5fb2a0fb7b308706e937bd5152955d3128d",
        "SEM-REL-010": "d6d22f0b14374448496b8bda34d2b0d6ed649b810b479cab45892ccc08172a25",
        "SEM-REL-011": "db1368a251eddd1a112c261f7576f69956c01b9f0c001037aef9822312af61fe",
        "SEM-REL-012": "0fab03e3f1b9da332021654c78aa191df5f4f3bcae9abb3cb196157650fbfff3",
    }
)

APPLICATION_CALCULATION_OFFICIAL_URL = (
    "https://learn.microsoft.com/en-us/office/vba/api/project.application.calculation"
)
PROJECT_SUMMARY_UID_OFFICIAL_URL = (
    "https://learn.microsoft.com/en-us/office-project/xml-data-interchange/"
    "elemtype-element?view=project-client-2016"
)
TASK_ELEMENT_OFFICIAL_URL = (
    "https://learn.microsoft.com/en-us/office-project/xml-data-interchange/"
    "task-element?view=project-client-2016"
)
SUMMARY_ELEMENT_OFFICIAL_URL = (
    "https://learn.microsoft.com/en-us/previous-versions/office/developer/"
    "office-2007/bb968468(v=office.12)"
)
PROJECT_SUMMARY_VISIBILITY_OFFICIAL_URL = (
    "https://learn.microsoft.com/en-us/office/vba/api/"
    "project.project.displayprojectsummarytask"
)

OFFICIAL_SOURCE_URLS = (
    "https://www.microsoft.com/en-sa/download/details.aspx?id=15511",
    (
        "https://download.microsoft.com/download/a/3/b/"
        "a3bbd4c5-a4c8-489b-bbe1-c167aad808e2/Project2010SDK.exe"
    ),
    "https://support.microsoft.com/en-US/project/create-a-new-base-calendar",
    (
        "https://support.microsoft.com/en-us/project/"
        "how-project-schedules-tasks-behind-the-scenes"
    ),
    (
        "https://learn.microsoft.com/en-us/office-project/xml-data-interchange/"
        "calendar-element?view=project-client-2016"
    ),
    (
        "https://learn.microsoft.com/en-us/office-project/xml-data-interchange/"
        "weekday-element?view=project-client-2016"
    ),
    (
        "https://learn.microsoft.com/en-us/previous-versions/office/developer/"
        "office-2007/bb968434(v=office.12)"
    ),
    (
        "https://learn.microsoft.com/en-us/previous-versions/office/developer/"
        "office-2007/bb968558(v=office.12)"
    ),
    (
        "https://learn.microsoft.com/en-us/previous-versions/office/developer/"
        "office-2007/bb968698(v=office.12)"
    ),
    (
        "https://learn.microsoft.com/en-us/previous-versions/office/developer/"
        "office-2007/bb968703(v=office.12)"
    ),
    "https://learn.microsoft.com/en-us/office/vba/api/project.application.levelingoptions",
    "https://learn.microsoft.com/en-us/office/vba/api/project.task.manual",
    "https://support.microsoft.com/en-US/project/task-mode-task-field",
    APPLICATION_CALCULATION_OFFICIAL_URL,
    PROJECT_SUMMARY_UID_OFFICIAL_URL,
    TASK_ELEMENT_OFFICIAL_URL,
    SUMMARY_ELEMENT_OFFICIAL_URL,
    PROJECT_SUMMARY_VISIBILITY_OFFICIAL_URL,
)

SDK_DOWNLOAD_SHA256 = (
    "5460f0846382d10101acde623cbaab8e06c43a05d3ad24ba21a3879cf7535810"
)
EMBEDDED_XSD_SHA256 = (
    "cc1ea815fcf6a083eb9940402926e7878484f474861aacbc6c168fd0bd0849d7"
)


class PilotError(RuntimeError):
    """Base class for pilot preparation failures."""


class PilotBindingError(PilotError):
    """A preregistered source no longer has its frozen raw identity."""


class PilotSafetyError(PilotError):
    """The requested output directory cannot be safely owned or updated."""


class PilotVerificationError(PilotError):
    """A prepared kit differs from a clean deterministic regeneration."""


@dataclass(frozen=True)
class _BoundSources:
    preregistration: Mapping[str, Any]
    profile: Mapping[str, Any]
    fixtures: Mapping[str, Mapping[str, Any]]


def _fixture_path(case_id: str) -> str:
    return f"benchmarks/semantic/cases/{case_id.lower()}.json"


def _source_only_projection_path(case_id: str) -> str:
    return f"{SOURCE_ONLY_PROJECTION_DIRECTORY}/{case_id}.json"


def _source_only_projection_repository_path(case_id: str) -> str:
    return (
        f"native-validation/pilot-kits/{PILOT_ID}/"
        f"{_source_only_projection_path(case_id)}"
    )


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value: Any) -> bytes:
    return canonical_bytes(value) + b"\n"


def _default_repository_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _absolute_without_following_symlinks(path: Path | str) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _read_frozen_json(
    repository_root: Path,
    *,
    relative_path: str,
    expected_sha256: str,
) -> Mapping[str, Any]:
    path = repository_root / relative_path
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise PilotBindingError(f"frozen source is missing: {relative_path}") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise PilotBindingError(f"frozen source is not a regular file: {relative_path}")
    raw = path.read_bytes()
    actual_sha256 = _sha256(raw)
    if actual_sha256 != expected_sha256:
        raise PilotBindingError(
            f"raw SHA-256 mismatch for {relative_path}: "
            f"expected {expected_sha256}, observed {actual_sha256}"
        )
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PilotBindingError(f"frozen source is not valid UTF-8 JSON: {relative_path}") from error
    if not isinstance(value, dict):
        raise PilotBindingError(f"frozen source must contain a JSON object: {relative_path}")
    return value


def _load_and_verify_bound_sources(repository_root: Path) -> _BoundSources:
    preregistration = _read_frozen_json(
        repository_root,
        relative_path=PREREGISTRATION_PATH,
        expected_sha256=PREREGISTRATION_RAW_SHA256,
    )
    profile = _read_frozen_json(
        repository_root,
        relative_path=PROFILE_PATH,
        expected_sha256=PROFILE_RAW_SHA256,
    )
    fixtures: dict[str, Mapping[str, Any]] = {}
    for case_id in CASE_IDS:
        fixtures[case_id] = _read_frozen_json(
            repository_root,
            relative_path=_fixture_path(case_id),
            expected_sha256=FIXTURE_RAW_SHA256_BY_CASE_ID[case_id],
        )

    if preregistration.get("preregistration_id") != PREREGISTRATION_ID:
        raise PilotBindingError("frozen preregistration ID is inconsistent with the pilot")
    profile_binding = preregistration.get("profile_binding")
    if not isinstance(profile_binding, dict) or (
        profile_binding.get("profile_id") != COMPARISON_PROFILE_ID
        or profile_binding.get("path") != PROFILE_PATH
        or profile_binding.get("raw_file_sha256") != PROFILE_RAW_SHA256
    ):
        raise PilotBindingError("preregistration profile binding is inconsistent with the pilot")
    if profile.get("profile_id") != COMPARISON_PROFILE_ID:
        raise PilotBindingError("frozen comparison profile ID is inconsistent with the pilot")
    execution_ids = profile.get("scope", {}).get("execution_case_ids")
    claim_ids = profile.get("scope", {}).get("claim_eligible_case_ids")
    if not isinstance(execution_ids, list) or list(CASE_IDS) != execution_ids[: len(CASE_IDS)]:
        raise PilotBindingError("pilot cases are not the frozen leading profile cases")
    if not isinstance(claim_ids, list) or any(case_id not in claim_ids for case_id in CASE_IDS):
        raise PilotBindingError("a pilot case is not claim-eligible in the frozen profile")
    if len(claim_ids) != FULL_PROFILE_CLAIM_ELIGIBLE_CASE_COUNT:
        raise PilotBindingError("frozen profile no longer has exactly 45 claim-eligible cases")
    for case_id, fixture in fixtures.items():
        if fixture.get("case_id") != case_id:
            raise PilotBindingError(f"fixture identity mismatch for {case_id}")
        schedule = fixture.get("schedule")
        if not isinstance(schedule, dict) or schedule.get("schedule_id") != case_id:
            raise PilotBindingError(f"fixture schedule identity mismatch for {case_id}")
        calendars = schedule.get("calendars")
        if not isinstance(calendars, list) or not any(
            calendar.get("id") == "CAL-24X7"
            and calendar.get("working_intervals") == [[0, 400]]
            for calendar in calendars
            if isinstance(calendar, dict)
        ):
            raise PilotBindingError(f"fixture {case_id} lacks the bound CAL-24X7 interval")
        if not isinstance(fixture.get("expected"), dict):
            raise PilotBindingError(f"fixture {case_id} lacks its sealed expected object")
    return _BoundSources(
        preregistration=preregistration,
        profile=profile,
        fixtures=MappingProxyType(fixtures),
    )


def _protocol_source_bindings() -> dict[str, Any]:
    return {
        "preregistration": {
            "id": PREREGISTRATION_ID,
            "preregistration_id": PREREGISTRATION_ID,
            "path": PREREGISTRATION_PATH,
            "relative_path": PREREGISTRATION_PATH,
            "raw_sha256": PREREGISTRATION_RAW_SHA256,
        },
        "comparison_profile": {
            "id": COMPARISON_PROFILE_ID,
            "profile_id": COMPARISON_PROFILE_ID,
            "path": PROFILE_PATH,
            "relative_path": PROFILE_PATH,
            "raw_sha256": PROFILE_RAW_SHA256,
        },
    }


def _source_only_binding_for(
    case_id: str, *, raw_sha256: str, byte_size: int
) -> dict[str, Any]:
    return {
        "binding_role": "source_only_case_projection",
        "case_id": case_id,
        "path": _source_only_projection_repository_path(case_id),
        "relative_path": _source_only_projection_repository_path(case_id),
        "raw_sha256": raw_sha256,
        "byte_size": byte_size,
        "media_type": "application/json",
        "oracle_content_included": False,
    }


def _operator_source_bindings(
    source_only_binding: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        **_protocol_source_bindings(),
        "source_only_case_projection": dict(source_only_binding),
    }


def _sealed_source_bindings_for(case_id: str) -> dict[str, Any]:
    """Bind the oracle-bearing full fixture only inside the sealed artifact."""

    return {
        **_protocol_source_bindings(),
        "fixture": {
            "case_id": case_id,
            "path": _fixture_path(case_id),
            "relative_path": _fixture_path(case_id),
            "raw_sha256": FIXTURE_RAW_SHA256_BY_CASE_ID[case_id],
        },
    }


def pilot_input_identity_projection(
    *,
    mapping_source_register_raw_sha256: str,
    source_only_projection_raw_sha256_by_case_id: Mapping[str, str],
) -> dict[str, Any]:
    """Return the domain-separated canonical identity of pilot preparation inputs.

    The mapping register and source-only case projections are generated solely
    from reviewed mapping authorities and construction inputs. Their raw digests
    bind the operator-visible preparation inputs without exposing a path or digest
    for an oracle-bearing fixture and without creating a hash cycle.
    """

    if (
        not isinstance(mapping_source_register_raw_sha256, str)
        or len(mapping_source_register_raw_sha256) != 64
        or any(character not in "0123456789abcdef" for character in mapping_source_register_raw_sha256)
    ):
        raise PilotBindingError("mapping-source-register raw SHA-256 is invalid")
    if set(source_only_projection_raw_sha256_by_case_id) != set(CASE_IDS):
        raise PilotBindingError(
            "source-only projection hash map must cover the exact pilot cases"
        )
    for case_id in CASE_IDS:
        digest = source_only_projection_raw_sha256_by_case_id[case_id]
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise PilotBindingError(
                f"source-only projection raw SHA-256 is invalid for {case_id}"
            )
    return {
        "hash_domain": PILOT_INPUT_IDENTITY_DOMAIN,
        "pilot_id": PILOT_ID,
        "ordered_case_ids": list(CASE_IDS),
        "preregistration": {
            "relative_path": PREREGISTRATION_PATH,
            "raw_sha256": PREREGISTRATION_RAW_SHA256,
        },
        "comparison_profile": {
            "relative_path": PROFILE_PATH,
            "raw_sha256": PROFILE_RAW_SHA256,
        },
        "source_only_case_projections": [
            {
                "case_id": case_id,
                "relative_path": _source_only_projection_repository_path(case_id),
                "raw_sha256": source_only_projection_raw_sha256_by_case_id[
                    case_id
                ],
            }
            for case_id in CASE_IDS
        ],
        "mapping_source_register": {
            "relative_path": MAPPING_SOURCE_REGISTER,
            "raw_sha256": mapping_source_register_raw_sha256,
        },
    }


def pilot_input_identity_sha256(projection: Mapping[str, Any]) -> str:
    """Hash a pilot input-identity projection with dsc-canonical-json-v1."""

    return _sha256(canonical_bytes(projection))


def _claim_boundary() -> dict[str, Any]:
    return {
        "pilot_is_partial_profile_preparation": True,
        "pilot_case_count": len(CASE_IDS),
        "full_profile_claim_eligible_case_count": FULL_PROFILE_CLAIM_ELIGIBLE_CASE_COUNT,
        "full_45_case_gate_satisfied": False,
        "native_execution_performed": False,
        "native_semantic_claim": False,
        "reopen_stability_claim": False,
        "adapter_execution_performed": False,
        "adapter_interchange_claim": False,
        "full_microsoft_project_compatibility_claim": False,
        "mpp_binary_compatibility_claim": False,
        "safe_production_round_trip_claim": False,
        "optimizer_benchmark_performed": False,
        "optimizer_superiority_claim": False,
        "boundary_statement": (
            "Preparation of 12 relationship cases is partial and supplies no native, "
            "adapter, compatibility, production-round-trip, or optimizer result."
        ),
    }


def _owner_document() -> dict[str, Any]:
    return {
        "document_type": "deterministic_pilot_output_owner",
        "schema_version": "microsoft-project-pilot-owner-v0.1",
        "pilot_id": PILOT_ID,
        "generator": "deterministic_scheduling_core.native.msproject.pilot",
        "ownership_scope": "only_the_exact_paths_declared_by_this_generator",
        "unrelated_content_deletion_allowed": False,
    }


def _mapping_source_register() -> dict[str, Any]:
    source_records = [
        {
            "source_id": "project-2010-sdk-download-page",
            "publisher": "Microsoft",
            "url": OFFICIAL_SOURCE_URLS[0],
            "role": "official_sdk_distribution_page",
        },
        {
            "source_id": "project-2010-sdk-installer",
            "publisher": "Microsoft",
            "url": OFFICIAL_SOURCE_URLS[1],
            "role": "official_sdk_binary",
            "raw_sha256": SDK_DOWNLOAD_SHA256,
        },
        {
            "source_id": "project-2010-sdk-embedded-xsd",
            "publisher": "Microsoft",
            "container_source_id": "project-2010-sdk-installer",
            "role": "embedded_schema_evidence",
            "raw_sha256": EMBEDDED_XSD_SHA256,
        },
    ]
    source_records.extend(
        {
            "source_id": f"official-web-source-{number:02d}",
            "publisher": "Microsoft",
            "url": url,
            "role": "official_product_or_schema_documentation",
        }
        for number, url in enumerate(OFFICIAL_SOURCE_URLS[2:], start=1)
    )
    return {
        "document_type": "microsoft_project_mapping_source_register",
        "schema_version": "microsoft-project-mapping-source-register-v0.1",
        "pilot_id": PILOT_ID,
        "status": PILOT_STATUS,
        "scope_case_ids": list(CASE_IDS),
        "authority_boundaries": {
            "claim_governance": (
                "The frozen repository preregistration, comparison profile, and fixtures "
                "govern the allowed claims and comparisons."
            ),
            "mapping_reference": (
                "Official Microsoft documentation and SDK material are the primary "
                "references for intended field mappings; they do not prove runtime semantics."
            ),
            "observed_native_behavior": (
                "Only controlled execution on the captured Microsoft Project edition, "
                "version, build, and configuration can establish observed native behavior."
            ),
        },
        "sources": source_records,
        "schema_backed_intent_if_adapter_preparation_is_unblocked": {
            "mspdi_namespace": "http://schemas.microsoft.com/project/2010",
            "save_version": 14,
            "new_tasks_are_manual": 0,
            "task_pinned": 0,
            "authority": "official SDK installer and its embedded XSD",
            "authorization_to_emit_xml": False,
        },
        "mapping_findings": [
            {
                "mapping_id": "manual-native-relationship-source-entry",
                "status": "prepared_for_controlled_manual_entry",
                "rule": (
                    "Retain each fixture's relationship type and signed lag in hours; "
                    "the operator and reviewer record the displayed native fields."
                ),
            },
            {
                "mapping_id": "manual-native-built-in-24-hours-calendar",
                "status": "prepared_for_operator_verification",
                "canonical_calendar_id": "CAL-24X7",
                "native_calendar_name": "24 Hours",
                "documented_native_definition": "12:00 AM to 12:00 AM every day",
                "rule": (
                    "Select the built-in 24 Hours calendar for manual realization and "
                    "verify all seven days and absence of nonworking time in the native UI."
                ),
                "official_url": OFFICIAL_SOURCE_URLS[2],
                "does_not_authorize_mspdi_serialization": True,
            },
            {
                "mapping_id": "manual-native-application-calculation-mode",
                "status": "prepared_for_operator_verification",
                "required_value": "manual",
                "rule": (
                    "Set the Microsoft Project application Calculation option to Manual "
                    "while constructing and freezing the source realization; this is distinct "
                    "from automatically scheduled task mode and from the protocol's "
                    "constructed_not_calculated state."
                ),
                "official_url": APPLICATION_CALCULATION_OFFICIAL_URL,
                "runtime_behavior_requires_controlled_observation": True,
            },
            {
                "mapping_id": "schema-backed-task-relationship-and-constraint-fields",
                "status": "schema_backed_intent_for_frozen_native_realization",
                "values": {
                    "fixed_duration_task_type": 1,
                    "effort_driven_false": 0,
                    "start_no_earlier_than_constraint_type": 4,
                    "predecessor_type_by_canonical_type": {
                        "FF": 0,
                        "FS": 1,
                        "SF": 2,
                        "SS": 3,
                    },
                    "link_lag_units": "signed_tenths_of_a_minute",
                    "link_lag_tenths_minutes_per_hour": 600,
                    "lag_format_hours": 5,
                },
            },
            {
                "mapping_id": "optional-structural-project-summary-task",
                "status": "documented_optional_unclaimed_structural_evidence",
                "accepted_identity_if_present": {
                    "native_task_uid": 0,
                    "native_task_id": 0,
                    "summary": True,
                    "predecessor_links_allowed": False,
                },
                "rule": (
                    "A single exported Project summary task may be retained only as "
                    "unclaimed structural evidence when it has UID 0, ID 0, Summary=true, "
                    "and no predecessor links. It is not a canonical activity, cannot "
                    "satisfy activity coverage, and contributes no claimed coordinate."
                ),
                "official_urls": [
                    PROJECT_SUMMARY_UID_OFFICIAL_URL,
                    TASK_ELEMENT_OFFICIAL_URL,
                    SUMMARY_ELEMENT_OFFICIAL_URL,
                    PROJECT_SUMMARY_VISIBILITY_OFFICIAL_URL,
                ],
                "runtime_behavior_requires_controlled_observation": True,
            },
            {
                "mapping_id": "adapter-cal-24x7-working-time",
                "status": "unresolved_normative_mapping",
                "canonical_calendar_id": "CAL-24X7",
                "canonical_working_intervals": [[0, 400]],
                "mspdi_elements_requiring_an_exact_rule": ["FromTime", "ToTime"],
                "from_time_value": None,
                "to_time_value": None,
                "finding": (
                    "The official material establishes the WorkingTime element shape and "
                    "illustrative working periods, but does not normatively establish the "
                    "exact equal-endpoint or midnight-boundary serialization needed for "
                    "continuous CAL-24X7 semantics."
                ),
                "decision": "block_adapter_preparation_for_every_pilot_case",
                "xml_generation_allowed": False,
                "required_resolution": (
                    "Freeze an authoritative exact FromTime/ToTime mapping in a new "
                    "versioned mapping decision before generating any MSPDI payload."
                ),
                "official_urls": [OFFICIAL_SOURCE_URLS[4], OFFICIAL_SOURCE_URLS[5]],
            },
        ],
        "claim_boundary": _claim_boundary(),
    }


_PRE_EXECUTION_ACTION_DETAILS: Mapping[str, tuple[str, tuple[str, ...]]] = MappingProxyType(
    {
        "capture_product_environment": (
            "Capture the identified desktop product, Windows host, locale, time zone, "
            "project start, calculation mode, schedule direction, and progress-rescheduling settings.",
            ("project_information",),
        ),
        "configure_calculation_and_schedule_direction": (
            "Set Microsoft Project calculation mode to Manual, set scheduling from the "
            "project start date, and do not invoke calculation before both required freezes.",
            ("project_information", "resource_leveling_status"),
        ),
        "verify_continuous_calendar": (
            "Select the built-in 24 Hours calendar and verify all seven days and the "
            "absence of nonworking time in the native UI.",
            ("calendar_working_time",),
        ),
        "construct_and_verify_tasks": (
            "Construct only the mapped tasks, enter explicit durations, then record and "
            "verify displayed ID, Unique ID, name, mode, type, effort-driven state, and calendar.",
            ("task_table", "task_mode_type_effort"),
        ),
        "construct_and_verify_relationships_and_constraints": (
            "Enter and independently verify only the mapped SNET constraints, relationship "
            "type, predecessor/successor identities, and signed lag.",
            ("predecessor_details",),
        ),
        "independent_pre_execution_review": (
            "The independent reviewer verifies every planned identity, source field, product "
            "setting, evidence role, and the no-result-observed boundary before freeze.",
            tuple(INDEPENDENT_VERIFICATION_EVIDENCE_ROLES),
        ),
    }
)

_EVIDENCE_ROLE_DESCRIPTIONS: Mapping[str, str] = MappingProxyType(
    {
        "task_table": "Task table showing the complete task count, ID, Unique ID, name, duration, start, and finish columns.",
        "project_information": "Project Information and calculation options showing project start, schedule direction, application calculation mode, locale-sensitive settings, and status date.",
        "calendar_working_time": "Built-in 24 Hours calendar working-time view showing all seven days and no nonworking interval.",
        "predecessor_details": "Predecessor details showing predecessor/successor task identities, relationship type, and signed lag.",
        "task_mode_type_effort": "Task fields showing automatic scheduling, fixed-duration type, and effort-driven false for every task.",
        "resource_leveling_status": "Resource-leveling controls showing leveling disabled and not run.",
    }
)


def _pre_execution_action_template() -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for sequence, action_id in enumerate(PRE_EXECUTION_ACTION_IDS, start=1):
        instruction, evidence_roles = _PRE_EXECUTION_ACTION_DETAILS[action_id]
        result.append(
            {
                "sequence": sequence,
                "action_id": action_id,
                "stage": "pre_execution",
                "action": instruction,
                "performed_by": None,
                "performed_at": None,
                "evidence_roles": list(evidence_roles),
            }
        )
    return result


def _independent_verification_plan_template() -> list[dict[str, Any]]:
    return [
        {
            "role": role,
            "planned_evidence_type": "screenshot",
            "description": _EVIDENCE_ROLE_DESCRIPTIONS[role],
        }
        for role in INDEPENDENT_VERIFICATION_EVIDENCE_ROLES
    ]


def _observed_product_settings_template(
    required_values: Mapping[str, Any]
) -> dict[str, Any]:
    if set(required_values) != set(OBSERVED_PRODUCT_SETTING_IDS):
        raise PilotBindingError("operator-observation template contract is incomplete")
    return {
        setting_id: {
            "required_value": required_values[setting_id],
            "observed_value": None,
            "observed_at": None,
            "observed_by": None,
            "independently_verified_at": None,
            "independently_verified_by": None,
        }
        for setting_id in OBSERVED_PRODUCT_SETTING_IDS
    }


def _relationship_capture(mapping: Mapping[str, Any]) -> dict[str, Any]:
    return {
        item["relationship_id"]: {
            "predecessor_activity_id": item["predecessor_activity_id"],
            "successor_activity_id": item["successor_activity_id"],
            "canonical_type": item["canonical_type"],
            "signed_lag_hours": item["canonical_signed_lag_hours"],
            "native_type": item["native_type"],
            "native_link_lag_tenths_minutes": item[
                "native_link_lag_tenths_minutes"
            ],
            "native_lag_format": item["native_lag_format"],
        }
        for item in mapping["relationships"]
    }


def _constraint_capture(mapping: Mapping[str, Any]) -> dict[str, Any]:
    return {
        item["constraint_id"]: {
            "activity_id": item["activity_id"],
            "canonical_type": item["canonical_type"],
            "canonical_coordinate": item["canonical_coordinate"],
            "canonical_timestamp": item["canonical_timestamp"],
            "native_constraint_type": item["native_constraint_type"],
        }
        for item in mapping["constraints"]
    }


def _case_environment_capture_template(
    case_id: str, fixture: Mapping[str, Any]
) -> dict[str, Any]:
    mapping = _native_mapping(fixture)
    activity_ids = [item["activity_id"] for item in mapping["activities"]]
    task_calendars = {activity_id: "24 Hours" for activity_id in activity_ids}
    task_modes = {activity_id: "automatically_scheduled" for activity_id in activity_ids}
    task_types = {activity_id: "fixed_duration" for activity_id in activity_ids}
    effort = {activity_id: False for activity_id in activity_ids}
    combined_task_fields = {
        activity_id: {
            "task_scheduling_mode": task_modes[activity_id],
            "task_type": task_types[activity_id],
            "effort_driven": effort[activity_id],
        }
        for activity_id in activity_ids
    }
    required_project_calendar = {
        "canonical_calendar_id": "CAL-24X7",
        "native_calendar_name": "24 Hours",
        "continuous_working_time_verified": True,
    }
    project_calendar = {
        **required_project_calendar,
        "continuous_working_time_verified": None,
    }
    relationships = _relationship_capture(mapping)
    constraints = _constraint_capture(mapping)
    progress_options = {
        "source_case_has_progress": False,
        "capture_complete_attestation": None,
        "native_displayed_settings": [],
    }
    actions = _pre_execution_action_template()
    observed_product_settings = _observed_product_settings_template(
        {
            "project_calendar_settings": required_project_calendar,
            "task_duration_hours_per_task": {
                item["activity_id"]: item["canonical_duration_hours"]
                for item in mapping["activities"]
            },
            "task_calendar_per_task": task_calendars,
            "task_scheduling_mode_per_task": task_modes,
            "task_type_per_task": task_types,
            "effort_driven_per_task": effort,
            "relationship_and_lag_settings": relationships,
            "constraint_settings": constraints,
            "project_start": "2026-01-05T08:00:00+08:00",
            "status_date": None,
            "schedule_from_start": True,
            "calculation_mode": "manual",
            "resource_leveling_status": "disabled_and_not_run",
        }
    )
    capture = {
        "product_name": "Microsoft Project",
        "edition": None,
        "version": None,
        "build": None,
        "operating_system": None,
        "machine_architecture": None,
        "machine_time_zone": "Australia/Perth",
        "locale": None,
        "execution_operator_id": None,
        "independent_reviewer_id": None,
        "native_file_format": "mpp",
        "native_file_hashes_by_stage": {"native_source_file_sha256": None},
        "native_source_file_format": "mpp",
        "native_source_file_sha256": None,
        "observed_native_activity_mapping": [
            {
                "activity_id": item["activity_id"],
                "native_task_id": None,
                "native_task_uid": None,
                "native_task_name": None,
            }
            for item in mapping["activities"]
        ],
        "observed_product_settings": observed_product_settings,
        "project_calendar_settings": project_calendar,
        "task_calendar_per_task": task_calendars,
        "resource_calendar_and_capacity_per_assignment": {},
        "task_scheduling_mode_per_task": task_modes,
        "task_type_per_task": task_types,
        "effort_driven_per_task": effort,
        "relationship_and_lag_settings": relationships,
        "constraint_settings": constraints,
        "project_start": "2026-01-05T08:00:00+08:00",
        "status_date": None,
        "schedule_from_start": True,
        "calculation_mode": "manual",
        "precalculation_protocol_state": "constructed_not_calculated",
        "progress_rescheduling_options": progress_options,
        "resource_leveling_status": "disabled_and_not_run",
        "manual_actions_by_stage": actions,
        "manual_construction_actions": actions,
        "manual_action_log_complete_attestation": None,
        "independent_verification_artifact_plan": (
            _independent_verification_plan_template()
        ),
        "Microsoft_Project_project_calendar_and_scheduling_options": {
            "project_calendar_settings": project_calendar,
            "calculation_mode": "manual",
            "schedule_from_start": True,
        },
        "Microsoft_Project_task_calendars": task_calendars,
        "Microsoft_Project_resource_calendars_and_capacities": {},
        "Microsoft_Project_task_scheduling_mode_type_and_effort_driven_fields": (
            combined_task_fields
        ),
        "Microsoft_Project_relationship_and_lag_settings": relationships,
        "Microsoft_Project_constraint_settings": constraints,
        "Microsoft_Project_project_start_and_status_date": {
            "project_start": "2026-01-05T08:00:00+08:00",
            "status_date": None,
        },
        "Microsoft_Project_calculation_and_progress_rescheduling_options": {
            "calculation_mode": "manual",
            "precalculation_protocol_state": "constructed_not_calculated",
            "progress_rescheduling_options": progress_options,
        },
        "Microsoft_Project_leveling_disabled_attestation": None,
    }
    return {
        "document_type": "microsoft_project_case_environment_capture_template",
        "schema_version": "microsoft-project-case-environment-template-v0.1",
        "pilot_id": PILOT_ID,
        "case_id": case_id,
        "status": PILOT_STATUS,
        "instructions": (
            "Copy only the capture object to a new canonical JSON file in the ignored "
            "execution workspace. Replace every required placeholder null except status_date, "
            "which must remain null for these no-status cases; complete the native displayed-"
            "settings array, record observed Project ID/Unique ID/name values, and complete "
            "every observed_product_settings value and its operator/reviewer provenance, "
            "the calendar and leveling attestations, and both action copies identically "
            "before either Track A or Track B freeze. Prefilled required values are plans, "
            "not observations."
        ),
        "capture": capture,
        "claim_boundary": _claim_boundary(),
    }


def _operator_environment_template(sources: _BoundSources) -> dict[str, Any]:
    prereg_fields = sources.preregistration.get("required_environment_capture", [])
    profile_fields = sources.profile.get("native_configuration", {}).get(
        "required_capture_fields", []
    )
    ordered_fields: list[str] = []
    for field in [*prereg_fields, *profile_fields]:
        if isinstance(field, str) and field not in ordered_fields:
            ordered_fields.append(field)
    for field in (
        "observed_native_activity_mapping",
        "observed_product_settings",
        "schedule_from_start",
        "precalculation_protocol_state",
        "manual_action_log_complete_attestation",
        "independent_verification_artifact_plan",
    ):
        if field not in ordered_fields:
            ordered_fields.append(field)
    document = {
        "document_type": "microsoft_project_operator_environment_template",
        "schema_version": "microsoft-project-operator-environment-v0.1",
        "pilot_id": PILOT_ID,
        "status": PILOT_STATUS,
        "instructions": (
            "This global field inventory is not a freeze input. Copy the selected per-case "
            "environment-capture template's capture object into a new canonical JSON file, "
            "then complete every required placeholder null except status_date, which must "
            "remain null, and complete every required displayed-setting entry before freeze. "
            "Do not record customer content in this preparation kit."
        ),
        "case_capture_template_pattern": (
            "tracks/manual_native_semantic_parity/environment-capture-templates/"
            "SEM-REL-NNN.json"
        ),
        "required_pre_execution_action_ids": list(PRE_EXECUTION_ACTION_IDS),
        "required_independent_verification_evidence_roles": list(
            INDEPENDENT_VERIFICATION_EVIDENCE_ROLES
        ),
        "track_attestations": {
            "manual_native_semantic_parity": {
                "operator_id": None,
                "independent_reviewer_id": None,
                "environment_capture_sha256": None,
                "native_execution_status": "not_executed",
            },
            "saved_file_reopen_recalculate_stability": {
                "operator_id": None,
                "independent_reviewer_id": None,
                "environment_capture_sha256": None,
                "native_execution_status": "not_executed",
            },
            "adapter_interchange_round_trip": {
                "operator_id": None,
                "independent_reviewer_id": None,
                "adapter_preparation_status": "preparation_blocked",
                "native_execution_status": "not_executed",
            },
        },
        "claim_boundary": _claim_boundary(),
    }
    document.update({field: None for field in ordered_fields})
    return document


def _post_execution_attestation_template() -> dict[str, Any]:
    return {
        "schema_version": "microsoft-project-post-execution-attestation-v0.1",
        "pilot_id": PILOT_ID,
        "native_system": "microsoft_project",
        "case_id": None,
        "execution_track_id": None,
        "actual_native_execution": None,
        "microsoft_project_desktop_opened": None,
        "case_opened_or_constructed": None,
        "native_recalculation_completed": None,
        "native_output_exported": None,
        "resource_leveling_disabled_and_not_run": None,
        "product_name": None,
        "edition": None,
        "version": None,
        "build": None,
        "executed_at": None,
        "attested_at": None,
        "attested_by": None,
        "environment_capture_sha256": None,
        "case_realization_manifest_sha256": None,
        "native_output_sha256": None,
        "stage_artifact_sha256_by_role": {},
        "post_execution_action_log_sha256": None,
        "independent_evidence_artifact_sha256_by_role": {},
    }


def _native_attempt_stop_template() -> dict[str, Any]:
    return {
        "schema_version": "microsoft-project-native-attempt-stop-template-v0.1",
        "document_type": "microsoft_project_native_attempt_stop_instruction_template",
        "pilot_id": PILOT_ID,
        "status": "template_only_non_claimable",
        "template_only": True,
        "is_attempt_stop_record": False,
        "claim_evidence_eligible": False,
        "allowed_case_ids": list(CASE_IDS),
        "allowed_execution_track_ids": list(TRACK_IDS),
        "allowed_stop_condition_ids": list(STOP_CONDITION_IDS),
        "allowed_outcome_classifications": list(STOP_OUTCOME_CLASSIFICATIONS),
        "outcome_by_stop_condition_and_calculation_observation": [
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
        ],
        "actual_record_contract": {
            "schema_version": "microsoft-project-native-attempt-stop-record-v0.2",
            "record_type": "native_attempt_stop_non_claimable",
            "required_top_level_fields": list(STOP_RECORD_REQUIRED_FIELDS),
            "output_filename": "native-attempt-stop-record.json",
            "created_only_by_command": "record-msproject-native-attempt-stop",
            "raw_observed_artifacts_embedded": False,
            "safe_no_overwrite_output_required": True,
        },
        "required_cli_options": [
            "--pilot",
            "--case",
            "--track",
            "--stopped-at",
            "--recorded-by",
            "--stop-condition",
            "--reason",
            "--outcome-classification",
            "--output-dir",
        ],
        "conditional_cli_options": {
            "--native-calculation-observed": (
                "required for executed_inconclusive or executed_fail and forbidden for "
                "not_executed"
            ),
            "--case-realisation-manifest": (
                "optional; if supplied, --environment-capture is required and both are "
                "revalidated against the live repository"
            ),
            "--environment-capture": (
                "optional without a manifest; required with a manifest"
            ),
            "--observed-artifact ROLE=PATH": (
                "repeat only for actual available artifacts; missing roles must not be "
                "fabricated"
            ),
        },
        "claim_boundary": {
            "native_run_evidence_record_created": False,
            "executed_pass_permitted": False,
            "claim_evidence_eligible": False,
            "repository_evidence_index_ingestion_permitted": False,
            "formal_claim_ingestion_requires_change_control": True,
            "full_45_case_gate_satisfied": False,
            "compatibility_claim_exists": False,
        },
    }


_POST_EXECUTION_ACTION_TEXT: Mapping[str, str] = MappingProxyType(
    {
        "calculate_project": "Run the controlled Microsoft Project calculation.",
        "save_calculated_native_file": (
            "Save and freeze the calculated native file without further editing."
        ),
        "export_post_calculation_mspdi": (
            "Export the frozen post-calculation observation as Project 2010 MSPDI XML."
        ),
        "finalize_stage_and_independent_evidence": (
            "Freeze every track-stage and independently verified evidence artifact."
        ),
        "capture_pre_close_file_and_output": (
            "Freeze the native pre-close file and pre-close MSPDI observation."
        ),
        "save_and_close_project": "Save and fully close Microsoft Project without editing.",
        "reopen_saved_project": "Reopen the exact saved native project.",
        "capture_reopened_file_before_recalculation": (
            "Freeze the reopened native file before recalculation."
        ),
        "recalculate_project": "Run the controlled reopen-track recalculation.",
        "capture_recalculated_file_and_post_output": (
            "Freeze the recalculated native file and post-recalculation MSPDI observation."
        ),
    }
)


def _post_execution_action_log_template(track_id: str) -> dict[str, Any]:
    if track_id not in {
        "manual_native_semantic_parity",
        "saved_file_reopen_recalculate_stability",
    }:
        raise PilotBindingError(
            "post-execution action-log templates exist only for prepared execution tracks"
        )
    stage_roles_by_action: dict[str, list[str]] = {
        "save_calculated_native_file": ["native_calculated_file_sha256"],
        "capture_pre_close_file_and_output": [
            "native_pre_close_file_sha256",
            "native_pre_close_output_sha256",
        ],
        "capture_reopened_file_before_recalculation": [
            "native_reopened_file_sha256"
        ],
        "capture_recalculated_file_and_post_output": [
            "native_recalculated_file_sha256",
            "native_post_recalculate_output_sha256",
        ],
    }
    action_ids = POST_EXECUTION_ACTION_IDS_BY_TRACK[track_id]
    return {
        "schema_version": "microsoft-project-post-execution-action-log-v0.1",
        "pilot_id": PILOT_ID,
        "native_system": "microsoft_project",
        "case_id": None,
        "execution_track_id": track_id,
        "executed_at": None,
        "operator_id": None,
        "environment_capture_sha256": None,
        "case_realization_manifest_sha256": None,
        "complete_manual_action_log_attestation": None,
        "actions": [
            {
                "sequence": sequence,
                "action_id": action_id,
                "action": _POST_EXECUTION_ACTION_TEXT[action_id],
                "performed_at": None,
                "stage_artifact_roles": stage_roles_by_action.get(action_id, []),
                "independent_evidence_roles": (
                    list(INDEPENDENT_VERIFICATION_EVIDENCE_ROLES)
                    if action_id == "finalize_stage_and_independent_evidence"
                    else []
                ),
            }
            for sequence, action_id in enumerate(action_ids, start=1)
        ],
    }


def _operator_runbook(sources: _BoundSources) -> str:
    prereg_fields = sources.preregistration.get("required_environment_capture", [])
    profile_fields = sources.profile.get("native_configuration", {}).get(
        "required_capture_fields", []
    )
    capture_fields: list[str] = []
    for field in [*prereg_fields, *profile_fields]:
        if isinstance(field, str) and field not in capture_fields:
            capture_fields.append(field)
    for field in (
        "observed_native_activity_mapping",
        "observed_product_settings",
        "schedule_from_start",
        "precalculation_protocol_state",
        "manual_action_log_complete_attestation",
        "independent_verification_artifact_plan",
    ):
        if field not in capture_fields:
            capture_fields.append(field)
    capture_checklist = "\n".join(f"- [ ] `{field}`" for field in capture_fields)
    return f"""# Microsoft Project relationship pilot operator runbook

Pilot: `{PILOT_ID}`

Status: `{PILOT_STATUS}`

Cases: `SEM-REL-001` through `SEM-REL-012`

This kit prepares a partial 12-case pilot. It contains no native calculation,
adapter execution, compatibility result, production round-trip result, or
optimizer result. The 45-case gate is false.

The frozen repository contract governs claims. Official Microsoft documentation
and SDK material are the primary mapping references, but do not prove runtime
semantics. Only controlled execution on the captured, identified Project build
can establish observed native behavior.

## Before any track

Use only the files inventoried by `pilot-kit-manifest.json`; do not use an
unrestricted repository checkout as the operator packet. Verify the raw
preregistration, comparison-profile, and source-only case projection hashes in
`pilot-index.json`. The operator packet contains no expected-result path or
digest. Copy the selected file under
`tracks/manual_native_semantic_parity/environment-capture-templates/`,
`post-execution-attestation-template.json`, and the selected case sheets into
the ignored controlled execution workspace. Copy the matching Track A or Track
B `post-execution-action-log-template.json`; no adapter template exists while
Track C remains blocked. Keep `native-attempt-stop-record-template.json`
available as non-record instructions if a mandatory stop condition occurs.
Extract only the per-case
template's `capture` object into `environment.json`; the freeze and analyser
accept canonical JSON containing those capture fields, not the surrounding
template metadata. Complete every required placeholder except `status_date`,
which must remain null; complete the displayed progress-setting list, the exact
six-action log, observed ID/Unique ID/name fields, calendar and leveling
attestations, and every `observed_product_settings` observation before freeze.
Values under `required_value` and other prefilled mapping fields are plans, not
observations: fill `observed_value`, operator/reviewer IDs, and both RFC 3339
times from the native UI and independent evidence.
Complete the attestation copy only after real desktop execution.
Never edit the tracked deterministic kit. This is a procedural blind, not an
access-controlled blind: the public repository necessarily contains frozen
oracle-bearing fixtures and comparison controls. The operator packet excludes
those materials, and the operator and pre-execution reviewer must attest that
they did not inspect them before the native observation was frozen. A separate
comparison role releases the control only after the native artifacts and
normalized observation have been durably frozen and hashed.

Required capture fields (placeholder null is incomplete except for the required
null `status_date`):

{capture_checklist}

`manual_actions_by_stage` and `manual_construction_actions` must be identical
ordered arrays using the six action IDs in the per-case template. Fill each
`performed_by` and RFC 3339 `performed_at`; attest completeness. The evidence
plan must retain exactly these roles: `task_table`, `project_information`,
`calendar_working_time`, `predecessor_details`, `task_mode_type_effort`, and
`resource_leveling_status`. Record every native progress-rescheduling option
displayed by the tested build as a `setting_name`/`displayed_value` entry and
attest the list is complete. Do not substitute `{{}}` for a capture.

## Post-execution action log and evidence hashes

The canonical JSON file supplied with `--post-execution-action-log` must have
exactly these top-level fields: `schema_version` (value
`microsoft-project-post-execution-action-log-v0.1`), `pilot_id`,
`native_system` (value `microsoft_project`), `case_id`, `execution_track_id`,
`executed_at`, `operator_id`, `environment_capture_sha256`,
`case_realization_manifest_sha256`,
`complete_manual_action_log_attestation`, and `actions`. Bind its identities,
hashes, operator, and execution time to the exact analysis invocation and set
the completeness attestation to true only after the log is complete.

Every `actions` entry must contain exactly `sequence`, `action_id`, `action`,
`performed_at`, `stage_artifact_roles`, and `independent_evidence_roles`. Keep
the exact ordered action IDs from the selected generated template, use
contiguous one-based sequence numbers, and use RFC 3339 action times. Across
all entries, the
stage-role union must equal the exact track-stage roles supplied on the command
line and the evidence-role union must equal all six roles frozen in the
environment. Empty per-entry role arrays are permitted; missing, duplicate,
unknown, or incomplete role coverage is not.

After the action log, stage files, and independent-evidence files are final,
hash their raw bytes. Complete the attestation copy with those exact values in
`post_execution_action_log_sha256`, `stage_artifact_sha256_by_role`, and
`independent_evidence_artifact_sha256_by_role`. The analyser recomputes all
three domains and rejects a mismatch; the same file may not satisfy two roles.

## Track A — manual native semantic parity

1. Use only the matching manual build sheet and its raw-bound source facts.
2. Select Microsoft Project's built-in **24 Hours** calendar for `CAL-24X7`.
   Verify all seven days and no nonworking time in the native UI.
3. Disable resource leveling and do not run it. Set Microsoft Project's
   application calculation mode to **Manual**, schedule from the project start
   date, and do not invoke Calculate Project. Keep tasks automatically
   scheduled, fixed duration, not effort driven, with Manual=0 and Pinned=0.
4. In Project Information, set Start Date exactly to
   `2026-01-05T08:00:00+08:00` (local `Australia/Perth` wall time), then enter
   the tasks in mapped A-then-B order and explicit `4h`/`3h` durations. Display
   ID and Unique ID columns and verify the resulting values; Project UIDs are
   observed identifiers, not operator-assigned inputs.
5. Enter the source SNET constraints, relationship type, and signed lag.
   Independently verify the displayed fields.
6. Capture the task table, Project Information, calendar working-time view,
   predecessor details, task mode/type/effort fields, and leveling status as
   screenshots or native reports for independent verification. Complete every
   `observed_product_settings` record from those artifacts; do not copy its
   prefilled `required_value` into `observed_value` without observing it.
7. Freeze the case-realization record, environment capture, action log, and
   native source-file hash before the controlled native calculation.
8. Only after every manifest for the tracks being executed is frozen, run Project's controlled
   calculation, save the calculated native file, and hash it without editing.
9. Export the observed schedule as Project 2010 MSPDI XML (`SaveVersion=14`),
   hash it, and stop as inconclusive if that exact dialect is unavailable.
10. Complete the post-execution action log, freeze all six independent-evidence
    artifacts and the required track-stage artifacts, then hash-bind them in the
    post-execution attestation and run the analyser. The analyser releases its
    procedurally withheld comparison material only after the normalized native
    observation is durably written and hash-verified. On Windows it uses an
    exclusive write-through handle plus FlushFileBuffers; on POSIX it fsyncs the
    file and containing directory.
11. Preserve the analyser bundle and submit it, the screenshots/reports, and
    raw controlled artifacts for independent post-execution review.

This track may not use reopen evidence or adapter evidence as a substitute.

Example Track A freeze (replace every angle-bracketed value):

```text
python -m deterministic_scheduling_core freeze-msproject-native-input \\
  --pilot microsoft-project-relationship-v0.1 \\
  --case SEM-REL-001 \\
  --track manual_native_semantic_parity \\
  --native-file <controlled-workspace>/SEM-REL-001-source.mpp \\
  --environment-capture <controlled-workspace>/SEM-REL-001-environment.json \\
  --output-dir <controlled-workspace>/SEM-REL-001-track-a-freeze \\
  --prepared-at <RFC3339-time> \\
  --prepared-by <operator-id> \\
  --independent-pre-execution-reviewed-by <reviewer-id> \\
  --attest-no-native-result-observed-before-freeze
```

Example Track A analysis after actual native calculation and evidence freeze:

```text
python -m deterministic_scheduling_core analyse-msproject-native-output \\
  --pilot microsoft-project-relationship-v0.1 \\
  --case SEM-REL-001 \\
  --track manual_native_semantic_parity \\
  --native-output <controlled-workspace>/SEM-REL-001-observed-project-2010.xml \\
  --case-realisation-manifest <controlled-workspace>/SEM-REL-001-track-a-freeze/case-realisation-manifest.json \\
  --environment-capture <controlled-workspace>/SEM-REL-001-environment.json \\
  --post-execution-attestation <controlled-workspace>/SEM-REL-001-track-a-attestation.json \\
  --post-execution-action-log <controlled-workspace>/SEM-REL-001-track-a-action-log.json \\
  --evidence-artifact task_table=<controlled-workspace>/track-a-task-table.png \\
  --evidence-artifact project_information=<controlled-workspace>/track-a-project-information.png \\
  --evidence-artifact calendar_working_time=<controlled-workspace>/track-a-calendar-working-time.png \\
  --evidence-artifact predecessor_details=<controlled-workspace>/track-a-predecessor-details.png \\
  --evidence-artifact task_mode_type_effort=<controlled-workspace>/track-a-task-mode-type-effort.png \\
  --evidence-artifact resource_leveling_status=<controlled-workspace>/track-a-resource-leveling-status.png \\
  --stage-artifact native_calculated_file_sha256=<controlled-workspace>/SEM-REL-001-calculated.mpp \\
  --output-dir <controlled-workspace>/SEM-REL-001-track-a-analysis \\
  --run-id <stable-run-id> \\
  --executed-at <RFC3339-time>
```

The value after each `--stage-artifact ROLE=` and
`--evidence-artifact ROLE=` is a file path; the analyser computes and
records its SHA-256. It is not a caller-supplied digest. Track A's action-log
stage-role union is exactly `native_calculated_file_sha256`; its evidence-role
union is exactly the six roles shown above.

## Track B — saved-file reopen/recalculate stability

1. Before the first calculation, freeze a separate Track B manifest bound to
   the same source file and the already frozen Track A manifest.
2. Start only from that exact dual-frozen realization.
3. Hash the native pre-close file and normalized pre-close observation.
4. Save, close, and reopen without editing; hash the reopened file.
5. Recalculate without leveling or manual intervention, then hash the
   recalculated file and normalized post-recalculation observation.
6. Submit the separate reopen evidence for independent review.

This track can test stability only. It cannot satisfy the native-semantic or
adapter-interchange track. Track B compares only its independently normalized
pre-close and post-recalculation observations and has no comparison-control
access.

Example Track B freeze, using the same native source and exact environment file:

```text
python -m deterministic_scheduling_core freeze-msproject-native-input \\
  --pilot microsoft-project-relationship-v0.1 \\
  --case SEM-REL-001 \\
  --track saved_file_reopen_recalculate_stability \\
  --native-file <controlled-workspace>/SEM-REL-001-source.mpp \\
  --environment-capture <controlled-workspace>/SEM-REL-001-environment.json \\
  --prerequisite-manual-case-realization-manifest <controlled-workspace>/SEM-REL-001-track-a-freeze/case-realisation-manifest.json \\
  --output-dir <controlled-workspace>/SEM-REL-001-track-b-freeze \\
  --prepared-at <RFC3339-time> \\
  --prepared-by <operator-id> \\
  --independent-pre-execution-reviewed-by <reviewer-id> \\
  --attest-no-native-result-observed-before-freeze
```

Example Track B analysis requires exactly these five separate stage files:

```text
python -m deterministic_scheduling_core analyse-msproject-native-output \\
  --pilot microsoft-project-relationship-v0.1 \\
  --case SEM-REL-001 \\
  --track saved_file_reopen_recalculate_stability \\
  --native-output <controlled-workspace>/SEM-REL-001-post-recalculate.xml \\
  --case-realisation-manifest <controlled-workspace>/SEM-REL-001-track-b-freeze/case-realisation-manifest.json \\
  --prerequisite-manual-case-realization-manifest <controlled-workspace>/SEM-REL-001-track-a-freeze/case-realisation-manifest.json \\
  --environment-capture <controlled-workspace>/SEM-REL-001-environment.json \\
  --post-execution-attestation <controlled-workspace>/SEM-REL-001-track-b-attestation.json \\
  --post-execution-action-log <controlled-workspace>/SEM-REL-001-track-b-action-log.json \\
  --evidence-artifact task_table=<controlled-workspace>/track-b-task-table.png \\
  --evidence-artifact project_information=<controlled-workspace>/track-b-project-information.png \\
  --evidence-artifact calendar_working_time=<controlled-workspace>/track-b-calendar-working-time.png \\
  --evidence-artifact predecessor_details=<controlled-workspace>/track-b-predecessor-details.png \\
  --evidence-artifact task_mode_type_effort=<controlled-workspace>/track-b-task-mode-type-effort.png \\
  --evidence-artifact resource_leveling_status=<controlled-workspace>/track-b-resource-leveling-status.png \\
  --stage-artifact native_pre_close_file_sha256=<controlled-workspace>/SEM-REL-001-pre-close.mpp \\
  --stage-artifact native_pre_close_output_sha256=<controlled-workspace>/SEM-REL-001-pre-close.xml \\
  --stage-artifact native_reopened_file_sha256=<controlled-workspace>/SEM-REL-001-reopened.mpp \\
  --stage-artifact native_recalculated_file_sha256=<controlled-workspace>/SEM-REL-001-recalculated.mpp \\
  --stage-artifact native_post_recalculate_output_sha256=<controlled-workspace>/SEM-REL-001-post-recalculate.xml \\
  --output-dir <controlled-workspace>/SEM-REL-001-track-b-analysis \\
  --run-id <stable-run-id> \\
  --executed-at <RFC3339-time>
```

Track B's action-log stage-role union is exactly the five stage roles in this
example; its evidence-role union is a separate Track B realization of the same
six planned roles. Track A evidence files cannot be supplied as Track B
evidence merely to satisfy the role names. The analyser revalidates the full
prerequisite Track A manifest supplied above; this flag is required for Track B
and forbidden for Tracks A and C.

## Track C — MSPDI adapter interchange

`adapter_preparation_status` is `preparation_blocked` for every case. The
official reviewed sources do not normatively establish the exact `FromTime`
and `ToTime` serialization needed to preserve continuous `CAL-24X7` semantics.
Do not invent, generate, import, or manually transcribe an MSPDI input. Resume
only under an approved, versioned mapping decision.

This blocker is a preparation gap, not a native failure. It supplies no
adapter-interchange or compatibility claim.

## Mandatory stop conditions and outcomes

- Any silent raw-source or binding change: stop before execution, preserve the
  evidence, and require a new versioned decision. Do not classify a result.
- Any missing, late, changed, or discarded pre-execution realization record,
  or any calculation/recalculation observed before its freeze: record
  `executed_inconclusive`; never reconstruct or overwrite the evidence.
- Wrong or unverified task mode, task type, effort-driven setting, calendar,
  locale, time zone, or leveling disabled state: record
  `executed_inconclusive`. If leveling ran, stop and preserve the failed
  attempt's evidence; never reuse it as a conforming run.
- An export outside the reviewed Project 2010 MSPDI namespace or with
  `SaveVersion` other than 14: record `executed_inconclusive` and require a
  separately reviewed dialect mapping; do not assume a newer dialect is equal.
- A post-freeze native task-mode, relationship-type, relationship-lag, or
  claim-field transformation; an off-grid timestamp; an unapproved
  transformation; or an unregistered edit after calculation: record
  `executed_fail` under the frozen profile.
- Any inaccessible or incomplete required evidence leaves its gate open.

For every stopped attempt, use the dedicated recorder rather than inventing
missing stage hashes or forcing the normal analyser to accept an incomplete
bundle. The recorder rebinds the pilot, case, track, source-only projection,
registry-backed full-fixture digest, preregistration, and comparison profile;
hashes only artifacts that
actually exist; refuses to overwrite its output; and can never emit a native
run record, `executed_pass`, or claim-eligible evidence. Supply a valid frozen
manifest and its environment capture when they exist. Omit the manifest when a
late freeze means none exists, and list each actual remaining artifact with a
repeatable `--observed-artifact ROLE=PATH`. The generated
`native-attempt-stop-record-template.json` is an instruction document only,
not a stopped-attempt record.

Example for a native calculation observed before the pre-execution freeze:

```text
python -m deterministic_scheduling_core record-msproject-native-attempt-stop \
  --pilot microsoft-project-relationship-v0.1 \
  --case SEM-REL-001 \
  --track manual_native_semantic_parity \
  --stopped-at <RFC3339-time> \
  --recorded-by <operator-id> \
  --stop-condition native_calculation_occurred_before_preexecution_freeze \
  --reason <concise-stop-reason> \
  --outcome-classification executed_inconclusive \
  --native-calculation-observed \
  --environment-capture <controlled-workspace>/SEM-REL-001-environment.json \
  --observed-artifact native_file=<controlled-workspace>/SEM-REL-001-observed.mpp \
  --output-dir <controlled-workspace>/SEM-REL-001-stopped-attempt
```

The command applies the frozen stop-condition/outcome table. A condition found
before native calculation records `not_executed`; after calculation it records
only the condition's frozen `executed_inconclusive` or `executed_fail`
classification. Formal native claim ingestion remains unavailable for this
record and any retry requires a new frozen realization.

No status or artifact may cross-satisfy another track. Even completed work on
these 12 cases cannot satisfy the full 45-case gate or support full Microsoft
Project compatibility, MPP binary compatibility, safe production round-trip,
or optimizer superiority.
"""


def _source_facts(fixture: Mapping[str, Any]) -> dict[str, Any]:
    schedule = fixture["schedule"]
    return {
        "title": fixture["title"],
        "purpose": fixture["purpose"],
        "time_axis": schedule["time_axis"],
        "project_inputs": schedule["project"],
        "calendar_inputs": schedule["calendars"],
        "resource_inputs": schedule["resources"],
        "activity_inputs": schedule["activities"],
        "relationship_inputs": schedule["relationships"],
        "operational_constraint_inputs": schedule["operational_constraints"],
    }


def _source_only_case_projection(
    case_id: str, fixture: Mapping[str, Any]
) -> dict[str, Any]:
    """Project only construction inputs into an operator-safe bound artifact."""

    return {
        "document_type": "microsoft_project_source_only_case_projection",
        "schema_version": "microsoft-project-source-only-case-projection-v0.1",
        "pilot_id": PILOT_ID,
        "case_id": case_id,
        "status": PILOT_STATUS,
        "projection_contract": {
            "construction_inputs_only": True,
            "oracle_content_included": False,
            "full_fixture_binding_included": False,
            "sealed_comparison_artifact_required_for_oracle_release": True,
        },
        "source_facts": _source_facts(fixture),
        "claim_boundary": _claim_boundary(),
    }


def _frozen_native_settings(sources: _BoundSources) -> dict[str, Any]:
    rules = sources.profile.get("native_configuration", {}).get("frozen_rules", [])
    settings: dict[str, Any] = {}
    for rule in rules:
        if isinstance(rule, dict) and rule.get("applies_to_case_ids") == ["*"]:
            settings[str(rule["setting"])] = rule["required_value"]
    settings.update(
        {
            "native_task_manual_flag": 0,
            "native_task_pinned_flag": 0,
            "schedule_from_start": True,
            "native_calculation_mode": "manual",
            "precalculation_protocol_state": "constructed_not_calculated",
            "coordinate_origin": "2026-01-05T08:00:00+08:00",
            "coordinate_unit": "hour",
            "schedule_time_zone": "Australia/Perth",
            "timestamp_tolerance_seconds": 0,
            "rounding": "forbidden",
        }
    )
    return settings


def _operator_build_sheet(
    case_id: str,
    fixture: Mapping[str, Any],
    sources: _BoundSources,
    environment_capture_template_ref: Mapping[str, Any],
    source_only_binding: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "document_type": "microsoft_project_manual_operator_build_sheet",
        "schema_version": "microsoft-project-operator-build-sheet-v0.1",
        "pilot_id": PILOT_ID,
        "case_id": case_id,
        "status": PILOT_STATUS,
        "execution_track_id": "manual_native_semantic_parity",
        "source_bindings": _operator_source_bindings(source_only_binding),
        "source_facts": _source_facts(fixture),
        "frozen_settings": _frozen_native_settings(sources),
        "native_mapping": _native_mapping(fixture),
        "environment_capture_template": environment_capture_template_ref,
        "environment_capture_requirements": [
            "Record Windows version in operating_system and use machine_time_zone Australia/Perth.",
            "Record the verified built-in 24 Hours calendar and exact per-task calendar assignments.",
            "Record exact per-task scheduling mode, task type and effort-driven values.",
            "Record the native relationship Type, signed LinkLag and LagFormat values from native_mapping.",
            "Record exact constraint and project-start mappings and keep status_date null.",
            "Record schedule_from_start=true, native calculation_mode=manual, and the separate constructed_not_calculated protocol state.",
            "Record observed Project ID, Unique ID, and name for every canonical activity and require exact agreement with the reviewed mapping.",
            "Complete the exact six-action pre-execution log and progress-rescheduling setting capture.",
            "List the screenshots or native reports planned for independent verification.",
            "Before freeze, native_file_hashes_by_stage may contain only native_source_file_sha256.",
        ],
        "operator_actions": [
            {
                "sequence": 1,
                "action": (
                    "Complete and hash the operator environment capture; verify product "
                    "edition, version, build, locale, and Australia/Perth machine time zone."
                ),
            },
            {
                "sequence": 2,
                "action": (
                    "Before entering tasks, disable resource leveling, set the application "
                    "calculation mode to Manual, schedule from the project start date, and "
                    "retain protocol state constructed_not_calculated; record the displayed settings."
                ),
            },
            {
                "sequence": 3,
                "action": (
                    "Select Microsoft Project's built-in 24 Hours calendar as the manual "
                    "realization of CAL-24X7. Capture and verify all seven days and the "
                    "absence of nonworking time; stop as inconclusive if exact continuous "
                    "coverage cannot be proven in the native UI."
                ),
            },
            {
                "sequence": 4,
                "action": (
                    "Set Project Information > Start Date to the mapped origin, then create "
                    "only the listed source activities in mapping order. Display ID and "
                    "Unique ID columns, verify the resulting values, retain names, enter each explicit "
                    "native_duration_entry, "
                    "calendar assignments, constraints, automatic scheduling, fixed-duration "
                    "task type, no effort-driven recalculation, Manual=0, and Pinned=0."
                ),
            },
            {
                "sequence": 5,
                "action": (
                    "Enter only the listed relationship type and signed lag in hours. Record "
                    "the exact native predecessor field as displayed; do not add links."
                ),
            },
            {
                "sequence": 6,
                "action": (
                    "Record the construction action log and source-field screenshots. A "
                    "second person verifies every source fact against the hash-bound "
                    "source-only case projection."
                ),
            },
            {
                "sequence": 7,
                "action": (
                    "Freeze and hash the case-realization record and native source file before "
                    "the controlled calculation. If a calculated result was observed first, "
                    "record the case as inconclusive rather than repairing it."
                ),
            },
            {
                "sequence": 8,
                "action": (
                    "Only after all required track manifests are frozen, run the controlled "
                    "native calculation, save and hash the calculated MPP, and export and hash "
                    "Project 2010 MSPDI XML with SaveVersion 14."
                ),
            },
            {
                "sequence": 9,
                "action": (
                    "Complete the post-execution attestation and exact track-stage artifact "
                    "set, run the strict analyser, preserve every failure, and submit the "
                    "evidence plus screenshots/reports for independent review."
                ),
            },
        ],
        "operator_completion": {
            "prepared_by": None,
            "prepared_at": None,
            "native_source_file_sha256": None,
            "case_realization_manifest_sha256": None,
            "construction_action_log_sha256": None,
            "attestation_no_native_result_observed_before_freeze": None,
            "native_execution_status": "not_executed",
        },
        "prohibited_actions": [
            "Do not consult the sealed normalized expectation during construction.",
            "Do not perform an unrecorded edit after calculation.",
            "Do not describe preparation as a native result or compatibility result.",
        ],
        "claim_boundary": _claim_boundary(),
    }


def _independent_review_sheet(
    case_id: str,
    fixture: Mapping[str, Any],
    sources: _BoundSources,
    operator_ref: Mapping[str, Any],
    source_only_binding: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "document_type": "microsoft_project_independent_pre_execution_review_sheet",
        "schema_version": "microsoft-project-independent-review-v0.1",
        "pilot_id": PILOT_ID,
        "case_id": case_id,
        "status": PILOT_STATUS,
        "review_scope": "source_realization_and_execution_track_separation_only",
        "source_bindings": _operator_source_bindings(source_only_binding),
        "source_facts": _source_facts(fixture),
        "frozen_settings": _frozen_native_settings(sources),
        "native_mapping": _native_mapping(fixture),
        "operator_build_sheet": operator_ref,
        "track_review_sections": {
            "manual_native_semantic_parity": {
                "native_execution_status": "not_executed",
                "review_actions": [
                    "Recompute the preregistration, comparison-profile, and source-only projection hashes independently.",
                    "Verify the exact task count and compare each displayed ID, Unique ID, name, duration, calendar, and constraint with the source facts and reviewed mapping.",
                    "Verify the predecessor/successor identities, relationship type, and signed lag exactly.",
                    "Confirm automatic task scheduling, fixed duration, effort-driven false, native calculation mode Manual, ScheduleFromStart=true, and leveling disabled and not run.",
                    "Verify the complete six-action log, progress-rescheduling capture, and exact independent-evidence role plan.",
                    "Confirm the case-realization record was frozen before any native result was observed.",
                ],
                "review_disposition": None,
            },
            "saved_file_reopen_recalculate_stability": {
                "native_execution_status": "not_executed",
                "review_actions": [
                    "Keep reopen evidence and hashes separate from the initial native semantic track.",
                    "Reject any unrecorded edit between pre-close and post-recalculation stages.",
                ],
                "review_disposition": None,
            },
            "adapter_interchange_round_trip": {
                "adapter_preparation_status": "preparation_blocked",
                "native_execution_status": "not_executed",
                "review_actions": [
                    "Confirm the CAL-24X7 FromTime/ToTime mapping remains unresolved.",
                    "Confirm no adapter input payload was generated or substituted manually.",
                ],
                "review_disposition": None,
            },
        },
        "reviewer_completion": {
            "independent_reviewer_id": None,
            "reviewed_at": None,
            "review_record_sha256": None,
        },
        "claim_boundary": _claim_boundary(),
    }


def _reopen_case_protocol(
    case_id: str, source_only_binding: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "document_type": "microsoft_project_reopen_recalculate_case_protocol",
        "schema_version": "microsoft-project-reopen-protocol-v0.1",
        "pilot_id": PILOT_ID,
        "case_id": case_id,
        "status": PILOT_STATUS,
        "execution_track_id": "saved_file_reopen_recalculate_stability",
        "source_bindings": _operator_source_bindings(source_only_binding),
        "prerequisite_track": "manual_native_semantic_parity",
        "pre_execution_freeze_requirement": {
            "separate_track_b_manifest_required": True,
            "must_bind_same_native_source_file_as_track_a": True,
            "required_manifest_field": (
                "prerequisite_manual_case_realization_manifest_sha256"
            ),
            "must_be_frozen_before_first_native_calculation": True,
        },
        "actions": [
            "Hash the native pre-close file and normalized pre-close extract.",
            "Save and fully close Microsoft Project without editing the source realization.",
            "Reopen the saved native file and record its raw hash before recalculation.",
            "Run the controlled native recalculation without leveling or manual edits.",
            "Hash the recalculated native file and normalized post-recalculation extract.",
            "Send the separate reopen evidence to the independent reviewer.",
        ],
        "required_stage_hashes": {
            "native_pre_close_file_sha256": None,
            "native_pre_close_output_sha256": None,
            "native_reopened_file_sha256": None,
            "native_recalculated_file_sha256": None,
            "native_post_recalculate_output_sha256": None,
        },
        "native_execution_status": "not_executed",
        "claim_boundary": _claim_boundary(),
    }


_NATIVE_RELATIONSHIP_TYPE = {"FF": 0, "FS": 1, "SF": 2, "SS": 3}


def _native_mapping(fixture: Mapping[str, Any]) -> dict[str, Any]:
    schedule = fixture["schedule"]
    uid_by_activity = {
        activity["id"]: number
        for number, activity in enumerate(schedule["activities"], start=1)
    }
    activities = [
        {
            "activity_id": activity["id"],
            "native_task_uid": uid_by_activity[activity["id"]],
            "native_task_id": uid_by_activity[activity["id"]],
            "native_task_name": activity["name"],
            "canonical_duration_hours": activity["duration"],
            "native_duration_entry": f"{activity['duration']}h",
            "canonical_calendar_id": activity["calendar_id"],
        }
        for activity in schedule["activities"]
    ]
    relationships = []
    for relationship in schedule["relationships"]:
        relationship_type = relationship["type"]
        lag_hours = relationship["lag"]
        relationships.append(
            {
                "relationship_id": relationship["id"],
                "predecessor_activity_id": relationship["predecessor_id"],
                "successor_activity_id": relationship["successor_id"],
                "native_predecessor_uid": uid_by_activity[relationship["predecessor_id"]],
                "native_successor_uid": uid_by_activity[relationship["successor_id"]],
                "canonical_type": relationship_type,
                "canonical_signed_lag_hours": lag_hours,
                "native_type": _NATIVE_RELATIONSHIP_TYPE[relationship_type],
                "native_link_lag_tenths_minutes": lag_hours * 600,
                "native_lag_format": 5,
            }
        )
    origin = datetime.fromisoformat(schedule["time_axis"]["origin"])
    constraints: list[dict[str, Any]] = []
    for activity in schedule["activities"]:
        for constraint in activity["constraints"]:
            if constraint["type"] != "start_no_earlier_than":
                raise PilotBindingError(
                    f"unsupported pilot constraint mapping: {constraint['type']}"
                )
            coordinate = constraint["value"]
            constraints.append(
                {
                    "constraint_id": constraint["id"],
                    "activity_id": activity["id"],
                    "native_task_uid": uid_by_activity[activity["id"]],
                    "canonical_type": "start_no_earlier_than",
                    "canonical_coordinate": coordinate,
                    "canonical_timestamp": (origin + timedelta(hours=coordinate)).isoformat(),
                    "native_constraint_type": 4,
                }
            )
    calendar = next(item for item in schedule["calendars"] if item["id"] == "CAL-24X7")
    return {
        "activities": activities,
        "calendars": [
            {
                "canonical_calendar_id": "CAL-24X7",
                "canonical_working_intervals": calendar["working_intervals"],
                "manual_native_calendar_name": "24 Hours",
                "documented_manual_native_definition": "12:00 AM to 12:00 AM every day",
                "manual_mapping_status": "prepared_for_operator_verification",
                "adapter_preparation_status": "preparation_blocked",
                "adapter_from_time": None,
                "adapter_to_time": None,
            }
        ],
        "relationships": relationships,
        "constraints": constraints,
        "progress": [],
        "project_settings": {
            "schedule_from_start": True,
            "mspdi_schedule_from_start": 1,
            "new_tasks_are_manual": False,
            "mspdi_new_tasks_are_manual": 0,
            "task_scheduling_mode": "automatically_scheduled",
            "task_pinned": 0,
            "task_type": "fixed_duration",
            "mspdi_task_type": 1,
            "effort_driven": False,
            "mspdi_effort_driven": 0,
            "resource_leveling": "disabled_and_not_run",
            "native_calculation_mode": "manual",
            "precalculation_protocol_state": "constructed_not_calculated",
            "native_project_start_timestamp": schedule["time_axis"]["origin"],
            "native_project_start_ui_path": "Project Information > Start Date",
            "manual_calendar_mapping": "CAL-24X7 -> built-in 24 Hours",
            "adapter_calendar_mapping": "preparation_blocked",
        },
    }


def _adapter_blocker(
    case_id: str,
    fixture: Mapping[str, Any],
    source_only_binding: Mapping[str, Any],
) -> dict[str, Any]:
    schedule = fixture["schedule"]
    calendar = next(item for item in schedule["calendars"] if item["id"] == "CAL-24X7")
    return {
        "document_type": "microsoft_project_adapter_preparation_blocker",
        "schema_version": "microsoft-project-adapter-blocker-v0.1",
        "pilot_id": PILOT_ID,
        "case_id": case_id,
        "status": PILOT_STATUS,
        "execution_track_id": "adapter_interchange_round_trip",
        "adapter_preparation_status": "preparation_blocked",
        "native_execution_status": "not_executed",
        "source_bindings": _operator_source_bindings(source_only_binding),
        "blocked_source_fact": {
            "canonical_calendar_id": calendar["id"],
            "canonical_working_intervals": calendar["working_intervals"],
            "canonical_horizon_hours": schedule["time_axis"]["horizon"],
        },
        "unresolved_mapping": {
            "target_format": "mspdi_xml",
            "target_namespace_if_unblocked": "http://schemas.microsoft.com/project/2010",
            "target_save_version_if_unblocked": 14,
            "mspdi_elements": ["FromTime", "ToTime"],
            "from_time_value": None,
            "to_time_value": None,
            "normative_gap": (
                "No reviewed official source establishes the exact FromTime/ToTime "
                "serialization whose import semantics are continuous CAL-24X7 working "
                "time, including the equal-endpoint or midnight-boundary case."
            ),
            "required_resolution": (
                "Obtain and freeze authoritative exact serialization/import semantics; "
                "a plausible value, sample extrapolation, or trial-and-error value is forbidden."
            ),
        },
        "official_sources": [
            OFFICIAL_SOURCE_URLS[0],
            OFFICIAL_SOURCE_URLS[1],
            OFFICIAL_SOURCE_URLS[4],
            OFFICIAL_SOURCE_URLS[5],
        ],
        "sdk_download_raw_sha256": SDK_DOWNLOAD_SHA256,
        "embedded_xsd_raw_sha256": EMBEDDED_XSD_SHA256,
        "adapter_payload_generated": False,
        "manual_transcription_allowed": False,
        "blocking_decision": "do_not_generate_or_execute_adapter_payload",
        "claim_boundary": _claim_boundary(),
    }


def _sealed_expected(case_id: str, fixture: Mapping[str, Any]) -> dict[str, Any]:
    expected = fixture["expected"]
    normalized: dict[str, Any] = {
        "reference_status": expected["reference_status"],
        "activity_times": expected["activity_times"],
        "project_finish": expected["project_finish"],
    }
    for optional_field in ("total_float", "free_float"):
        if optional_field in expected:
            normalized[optional_field] = expected[optional_field]
    return {
        "document_type": "microsoft_project_sealed_expected_normalized",
        "schema_version": "microsoft-project-sealed-expected-v0.1",
        "pilot_id": PILOT_ID,
        "case_id": case_id,
        "status": PILOT_STATUS,
        "source_bindings": _sealed_source_bindings_for(case_id),
        "seal_control": {
            "separate_from_operator_and_pre_execution_reviewer_material": True,
            "full_oracle_fixture_binding_is_sealed": True,
            "operator_access_before_native_evidence_freeze": "prohibited",
            "release_condition": (
                "Release only to the controlled comparator after native artifacts, "
                "normalization, and their hashes are frozen."
            ),
        },
        "coordinate_contract": {
            "origin": "2026-01-05T08:00:00+08:00",
            "unit": "hour",
            "timestamp_tolerance_seconds": 0,
            "rounding": "forbidden",
        },
        "expected_normalized": normalized,
        "native_execution_status": "not_executed",
        "claim_boundary": _claim_boundary(),
    }


def _operator_path(case_id: str) -> str:
    return (
        "tracks/manual_native_semantic_parity/operator-build-sheets/"
        f"{case_id}.json"
    )


def _environment_capture_path(case_id: str) -> str:
    return (
        "tracks/manual_native_semantic_parity/environment-capture-templates/"
        f"{case_id}.json"
    )


def _review_path(case_id: str) -> str:
    return (
        "tracks/manual_native_semantic_parity/independent-review-sheets/"
        f"{case_id}.json"
    )


def _reopen_path(case_id: str) -> str:
    return (
        "tracks/saved_file_reopen_recalculate_stability/case-protocols/"
        f"{case_id}.json"
    )


def _adapter_path(case_id: str) -> str:
    return (
        "tracks/adapter_interchange_round_trip/adapter-blockers/"
        f"{case_id}.json"
    )


def _sealed_path(case_id: str) -> str:
    return f"{SEALED_CONTROL_DIRECTORY}/{case_id}.json"


def _expected_relative_files() -> tuple[str, ...]:
    files = [
        OWNER_MARKER,
        MAPPING_SOURCE_REGISTER,
        OPERATOR_ENVIRONMENT_TEMPLATE,
        POST_EXECUTION_ATTESTATION_TEMPLATE,
        NATIVE_ATTEMPT_STOP_TEMPLATE,
        TRACK_A_POST_EXECUTION_ACTION_LOG_TEMPLATE,
        TRACK_B_POST_EXECUTION_ACTION_LOG_TEMPLATE,
        OPERATOR_RUNBOOK,
    ]
    for case_id in CASE_IDS:
        files.extend(
            [
                _source_only_projection_path(case_id),
                _operator_path(case_id),
                _environment_capture_path(case_id),
                _review_path(case_id),
                _reopen_path(case_id),
                _adapter_path(case_id),
                _sealed_path(case_id),
            ]
        )
    files.extend([PILOT_INDEX, SEALED_CONTROL_INDEX, MANIFEST, MANIFEST_CHECKSUM])
    return tuple(files)


def _expected_relative_directories() -> frozenset[str]:
    directories: set[str] = set()
    for filename in _expected_relative_files():
        parent = PurePosixPath(filename).parent
        while str(parent) != ".":
            directories.add(parent.as_posix())
            parent = parent.parent
    return frozenset(directories)


def _reject_symlink_components(path: Path) -> None:
    candidates = [path, *path.parents]
    for candidate in candidates:
        try:
            metadata = candidate.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(metadata.st_mode):
            raise PilotSafetyError(f"output path contains a symlink: {candidate}")


def _walk_existing_tree(output_dir: Path) -> tuple[set[str], set[str]]:
    files: set[str] = set()
    directories: set[str] = set()
    for path in output_dir.rglob("*"):
        relative = path.relative_to(output_dir).as_posix()
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise PilotSafetyError(f"pilot output contains a symlink: {relative}")
        if stat.S_ISDIR(metadata.st_mode):
            directories.add(relative)
        elif stat.S_ISREG(metadata.st_mode):
            files.add(relative)
        else:
            raise PilotSafetyError(f"pilot output contains a special path: {relative}")
    return files, directories


def _validate_output_ownership(output_dir: Path, *, require_complete: bool) -> None:
    _reject_symlink_components(output_dir)
    if not output_dir.exists():
        if require_complete:
            raise PilotVerificationError(f"pilot output does not exist: {output_dir}")
        return
    if not output_dir.is_dir():
        raise PilotSafetyError(f"pilot output is not a directory: {output_dir}")
    files, directories = _walk_existing_tree(output_dir)
    if not files and not directories:
        if require_complete:
            raise PilotVerificationError("pilot output directory is empty")
        return
    allowed_files = set(_expected_relative_files())
    allowed_directories = set(_expected_relative_directories())
    unexpected = sorted((files - allowed_files) | (directories - allowed_directories))
    if unexpected:
        raise PilotSafetyError(
            "pilot output contains paths not owned by this generator: "
            + ", ".join(unexpected)
        )
    if OWNER_MARKER not in files:
        raise PilotSafetyError("nonempty pilot output lacks the owner marker")
    if (output_dir / OWNER_MARKER).read_bytes() != _json_bytes(_owner_document()):
        raise PilotSafetyError("pilot output owner marker is invalid")
    if require_complete:
        missing_files = sorted(allowed_files - files)
        missing_directories = sorted(allowed_directories - directories)
        if missing_files or missing_directories:
            missing = [*missing_files, *missing_directories]
            raise PilotVerificationError(
                "pilot output is incomplete; missing paths: " + ", ".join(missing)
            )


def _write_owned_file(output_dir: Path, relative_path: str, data: bytes) -> None:
    if relative_path not in _expected_relative_files():
        raise PilotSafetyError(f"generator attempted an undeclared output path: {relative_path}")
    path = output_dir / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not path.is_file():
        raise PilotSafetyError(f"owned file path is not a regular file: {relative_path}")
    if path.is_symlink():
        raise PilotSafetyError(f"owned file path is a symlink: {relative_path}")
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.pilot-tmp-",
            delete=False,
        ) as temporary:
            temporary.write(data)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_name = temporary.name
        os.replace(temporary_name, path)
        temporary_name = None
    finally:
        if temporary_name is not None:
            try:
                Path(temporary_name).unlink()
            except FileNotFoundError:
                pass


def _write_json(output_dir: Path, relative_path: str, value: Any) -> None:
    _write_owned_file(output_dir, relative_path, _json_bytes(value))


def _artifact_ref(output_dir: Path, relative_path: str) -> dict[str, Any]:
    data = (output_dir / relative_path).read_bytes()
    return {
        "relative_path": relative_path,
        "sha256": _sha256(data),
        "byte_size": len(data),
        "media_type": _media_type(relative_path),
    }


def _media_type(relative_path: str) -> str:
    if relative_path.endswith(".json"):
        return "application/json"
    if relative_path.endswith(".md"):
        return "text/markdown; charset=utf-8"
    if relative_path.endswith(".sha256"):
        return "text/plain; charset=us-ascii"
    return "application/octet-stream"


def _pilot_index(output_dir: Path, sources: _BoundSources) -> dict[str, Any]:
    mapping_source_register = _artifact_ref(output_dir, MAPPING_SOURCE_REGISTER)
    source_only_artifacts = {
        case_id: _artifact_ref(output_dir, _source_only_projection_path(case_id))
        for case_id in CASE_IDS
    }
    source_only_bindings = {
        case_id: _source_only_binding_for(
            case_id,
            raw_sha256=source_only_artifacts[case_id]["sha256"],
            byte_size=source_only_artifacts[case_id]["byte_size"],
        )
        for case_id in CASE_IDS
    }
    input_identity_projection = pilot_input_identity_projection(
        mapping_source_register_raw_sha256=mapping_source_register["sha256"],
        source_only_projection_raw_sha256_by_case_id={
            case_id: binding["raw_sha256"]
            for case_id, binding in source_only_bindings.items()
        },
    )
    cases: list[dict[str, Any]] = []
    for case_id in CASE_IDS:
        environment_capture = _artifact_ref(
            output_dir, _environment_capture_path(case_id)
        )
        operator = _artifact_ref(output_dir, _operator_path(case_id))
        review = _artifact_ref(output_dir, _review_path(case_id))
        reopen = _artifact_ref(output_dir, _reopen_path(case_id))
        adapter = _artifact_ref(output_dir, _adapter_path(case_id))
        cases.append(
            {
                "case_id": case_id,
                "status": PILOT_STATUS,
                "adapter_preparation_status": "preparation_blocked",
                "adapter_preparation_blocked_reason": (
                    "CAL-24X7 exact MSPDI FromTime/ToTime serialization is unresolved"
                ),
                "source_only_case_projection": source_only_bindings[case_id],
                "native_mapping": _native_mapping(sources.fixtures[case_id]),
                "environment_capture_template": environment_capture,
                "operator_build_sheet": operator,
                "independent_review_sheet": review,
                "tracks": {
                    "manual_native_semantic_parity": {
                        "preparation_status": "prepared",
                        "native_execution_status": "not_executed",
                        "artifacts": [environment_capture, operator, review],
                    },
                    "saved_file_reopen_recalculate_stability": {
                        "preparation_status": "prepared",
                        "native_execution_status": "not_executed",
                        "artifacts": [reopen],
                    },
                    "adapter_interchange_round_trip": {
                        "adapter_preparation_status": "preparation_blocked",
                        "native_execution_status": "not_executed",
                        "artifacts": [adapter],
                    },
                },
            }
        )
    return {
        "document_type": "microsoft_project_relationship_pilot_index",
        "schema_version": "msproject-relationship-pilot-index-v0.1",
        "pilot_id": PILOT_ID,
        "status": PILOT_STATUS,
        "case_ids": list(CASE_IDS),
        "case_count": len(CASE_IDS),
        "execution_track_ids": list(TRACK_IDS),
        "coordinate_contract": {
            "canonical_origin": "2026-01-05T08:00:00+08:00",
            "canonical_unit": "hour",
            "schedule_time_zone": "Australia/Perth",
            "utc_offset": "+08:00",
            "timestamp_tolerance_seconds": 0,
            "duration_tolerance_seconds": 0,
            "float_tolerance_seconds": 0,
            "rounding_policy": "forbidden",
        },
        "source_bindings": {
            **_protocol_source_bindings(),
        },
        "bindings": {
            **_protocol_source_bindings(),
        },
        "pilot_input_identity": {
            "hash_algorithm": "sha256",
            "canonical_serialization": "dsc-canonical-json-v1",
            "projection": input_identity_projection,
            "sha256": pilot_input_identity_sha256(input_identity_projection),
        },
        "global_artifacts": {
            "mapping_source_register": mapping_source_register,
            "operator_environment_template": _artifact_ref(
                output_dir, OPERATOR_ENVIRONMENT_TEMPLATE
            ),
            "post_execution_attestation_template": _artifact_ref(
                output_dir, POST_EXECUTION_ATTESTATION_TEMPLATE
            ),
            "native_attempt_stop_instruction_template": _artifact_ref(
                output_dir, NATIVE_ATTEMPT_STOP_TEMPLATE
            ),
            "post_execution_action_log_templates_by_track": {
                "manual_native_semantic_parity": _artifact_ref(
                    output_dir, TRACK_A_POST_EXECUTION_ACTION_LOG_TEMPLATE
                ),
                "saved_file_reopen_recalculate_stability": _artifact_ref(
                    output_dir, TRACK_B_POST_EXECUTION_ACTION_LOG_TEMPLATE
                ),
                "adapter_interchange_round_trip": None,
            },
            "operator_runbook": _artifact_ref(output_dir, OPERATOR_RUNBOOK),
        },
        "execution_tracks": [
            {
                "track_id": "manual_native_semantic_parity",
                "preparation_status": "prepared",
                "native_execution_status": "not_executed",
                "artifact_role": "manual_operator_and_independent_review",
                "post_execution_action_log_template": _artifact_ref(
                    output_dir, TRACK_A_POST_EXECUTION_ACTION_LOG_TEMPLATE
                ),
            },
            {
                "track_id": "saved_file_reopen_recalculate_stability",
                "preparation_status": "prepared",
                "native_execution_status": "not_executed",
                "artifact_role": "reopen_recalculate_protocol",
                "post_execution_action_log_template": _artifact_ref(
                    output_dir, TRACK_B_POST_EXECUTION_ACTION_LOG_TEMPLATE
                ),
            },
            {
                "track_id": "adapter_interchange_round_trip",
                "adapter_preparation_status": "preparation_blocked",
                "native_execution_status": "not_executed",
                "artifact_role": "deterministic_adapter_blocker_only",
                "post_execution_action_log_template": None,
            },
        ],
        "cases": cases,
        "claim_boundary": _claim_boundary(),
    }


def _sealed_control_index(
    output_dir: Path,
    pilot_index: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the post-observation-only comparison-control index.

    The operator index deliberately has no reverse reference to this document.
    Case artifact paths are derived from the frozen case IDs by the comparator,
    so this control contains no caller-selectable path.
    """

    cases: list[dict[str, Any]] = []
    indexed_cases = {
        item["case_id"]: item
        for item in pilot_index["cases"]
    }
    for case_id in CASE_IDS:
        sealed = _artifact_ref(output_dir, _sealed_path(case_id))
        projection = indexed_cases[case_id]["source_only_case_projection"]
        cases.append(
            {
                "case_id": case_id,
                "sealed_expected_raw_sha256": sealed["sha256"],
                "sealed_expected_byte_size": sealed["byte_size"],
                "source_only_projection_raw_sha256": projection["raw_sha256"],
                "frozen_fixture_raw_sha256": FIXTURE_RAW_SHA256_BY_CASE_ID[case_id],
            }
        )
    pilot_index_bytes = (output_dir / PILOT_INDEX).read_bytes()
    return {
        "document_type": "microsoft_project_sealed_comparison_control_index",
        "schema_version": "microsoft-project-sealed-control-index-v0.1",
        "pilot_id": PILOT_ID,
        "status": "sealed_until_post_observation_release",
        "ordered_case_ids": list(CASE_IDS),
        "operator_pilot_index_binding": {
            "raw_sha256": _sha256(pilot_index_bytes),
            "canonical_sha256": _sha256(canonical_bytes(pilot_index)),
            "pilot_input_identity_sha256": pilot_index["pilot_input_identity"][
                "sha256"
            ],
        },
        "protocol_bindings": _protocol_source_bindings(),
        "cases": cases,
        "release_policy": {
            "allowed_execution_track_id": "manual_native_semantic_parity",
            "normalized_observation_must_be_durably_written_and_hash_verified": True,
            "operator_and_pre_execution_reviewer_access": "prohibited",
            "caller_selected_control_or_seal_path": "forbidden",
        },
    }


def _build_manifest(output_dir: Path) -> dict[str, Any]:
    excluded = {MANIFEST, MANIFEST_CHECKSUM}
    inventory: list[dict[str, Any]] = []
    for relative_path in sorted(set(_expected_relative_files()) - excluded):
        if relative_path.startswith(f"{SEALED_CONTROL_DIRECTORY}/"):
            continue
        data = (output_dir / relative_path).read_bytes()
        inventory.append(
            {
                "relative_path": relative_path,
                "sha256": _sha256(data),
                "byte_size": len(data),
                "media_type": _media_type(relative_path),
            }
        )
    return {
        "document_type": "microsoft_project_pilot_kit_manifest",
        "schema_version": "microsoft-project-operator-packet-manifest-v0.2",
        "pilot_id": PILOT_ID,
        "status": PILOT_STATUS,
        "hash_algorithm": "sha256",
        "path_policy": "relative_posix_paths_only",
        "artifact_scope": "operator_visible_pre_observation_packet_only",
        "comparison_control_artifacts_included": False,
        "scope_exclusions": [
            "post_observation_comparison_control_domain",
            "manifest_self_and_checksum",
        ],
        "self_excluded_artifacts": [MANIFEST, MANIFEST_CHECKSUM],
        "artifact_count": len(inventory),
        "artifacts": inventory,
        "claim_boundary": _claim_boundary(),
    }


def _tree_snapshot(output_dir: Path) -> tuple[tuple[str, ...], dict[str, bytes]]:
    files, directories = _walk_existing_tree(output_dir)
    return (
        tuple(sorted(directories)),
        {relative: (output_dir / relative).read_bytes() for relative in sorted(files)},
    )


def _result_summary(output_dir: Path, *, verified: bool) -> dict[str, Any]:
    manifest_data = (output_dir / MANIFEST).read_bytes()
    index_data = (output_dir / PILOT_INDEX).read_bytes()
    files, _ = _walk_existing_tree(output_dir)
    index = json.loads(index_data.decode("utf-8"))
    return {
        "pilot_id": PILOT_ID,
        "status": PILOT_STATUS,
        "verified": verified,
        "output_dir": str(output_dir),
        "case_ids": list(CASE_IDS),
        "case_count": len(CASE_IDS),
        "track_ids": list(TRACK_IDS),
        "artifact_file_count": len(files),
        "pilot_index_sha256": _sha256(index_data),
        "pilot_input_identity_sha256": index["pilot_input_identity"]["sha256"],
        "pilot_kit_manifest_sha256": _sha256(manifest_data),
        "adapter_preparation_status": "preparation_blocked",
        "full_45_case_gate_satisfied": False,
        "blinding_classification": BLINDING_CLASSIFICATION,
        "operator_access_control_guaranteed": False,
        "claim_boundary": _claim_boundary(),
    }


def prepare_pilot(
    output_dir: Path | str,
    repository_root: Path | str | None = None,
) -> dict[str, Any]:
    """Prepare a deterministic, non-executed 12-case pilot kit.

    Frozen inputs are checked before the output path is created or modified.
    A fresh directory may be absent or empty.  A nonempty directory must carry
    this generator's exact owner marker and contain only declared paths.
    """

    root = _absolute_without_following_symlinks(
        repository_root if repository_root is not None else _default_repository_root()
    )
    sources = _load_and_verify_bound_sources(root)

    target = _absolute_without_following_symlinks(output_dir)
    _validate_output_ownership(target, require_complete=False)
    target.mkdir(parents=True, exist_ok=True)
    _reject_symlink_components(target)

    _write_json(target, OWNER_MARKER, _owner_document())
    _write_json(target, MAPPING_SOURCE_REGISTER, _mapping_source_register())
    _write_json(
        target,
        OPERATOR_ENVIRONMENT_TEMPLATE,
        _operator_environment_template(sources),
    )
    _write_json(
        target,
        POST_EXECUTION_ATTESTATION_TEMPLATE,
        _post_execution_attestation_template(),
    )
    _write_json(
        target,
        NATIVE_ATTEMPT_STOP_TEMPLATE,
        _native_attempt_stop_template(),
    )
    _write_json(
        target,
        TRACK_A_POST_EXECUTION_ACTION_LOG_TEMPLATE,
        _post_execution_action_log_template("manual_native_semantic_parity"),
    )
    _write_json(
        target,
        TRACK_B_POST_EXECUTION_ACTION_LOG_TEMPLATE,
        _post_execution_action_log_template(
            "saved_file_reopen_recalculate_stability"
        ),
    )
    _write_owned_file(
        target,
        OPERATOR_RUNBOOK,
        _operator_runbook(sources).encode("utf-8"),
    )

    for case_id in CASE_IDS:
        fixture = sources.fixtures[case_id]
        source_only_path = _source_only_projection_path(case_id)
        _write_json(
            target,
            source_only_path,
            _source_only_case_projection(case_id, fixture),
        )
        source_only_ref = _artifact_ref(target, source_only_path)
        source_only_binding = _source_only_binding_for(
            case_id,
            raw_sha256=source_only_ref["sha256"],
            byte_size=source_only_ref["byte_size"],
        )
        environment_path = _environment_capture_path(case_id)
        _write_json(
            target,
            environment_path,
            _case_environment_capture_template(case_id, fixture),
        )
        environment_ref = _artifact_ref(target, environment_path)
        operator_path = _operator_path(case_id)
        _write_json(
            target,
            operator_path,
            _operator_build_sheet(
                case_id,
                fixture,
                sources,
                environment_ref,
                source_only_binding,
            ),
        )
        operator_ref = _artifact_ref(target, operator_path)
        _write_json(
            target,
            _review_path(case_id),
            _independent_review_sheet(
                case_id,
                fixture,
                sources,
                operator_ref,
                source_only_binding,
            ),
        )
        _write_json(
            target,
            _reopen_path(case_id),
            _reopen_case_protocol(case_id, source_only_binding),
        )
        _write_json(
            target,
            _adapter_path(case_id),
            _adapter_blocker(case_id, fixture, source_only_binding),
        )
        _write_json(target, _sealed_path(case_id), _sealed_expected(case_id, fixture))

    pilot_index = _pilot_index(target, sources)
    _write_json(target, PILOT_INDEX, pilot_index)
    _write_json(
        target,
        SEALED_CONTROL_INDEX,
        _sealed_control_index(target, pilot_index),
    )
    manifest = _build_manifest(target)
    _write_json(target, MANIFEST, manifest)
    manifest_sha256 = _sha256((target / MANIFEST).read_bytes())
    _write_owned_file(
        target,
        MANIFEST_CHECKSUM,
        f"{manifest_sha256}  {MANIFEST}\n".encode("ascii"),
    )
    _validate_output_ownership(target, require_complete=True)
    return _result_summary(target, verified=False)


def verify_pilot(
    output_dir: Path | str,
    repository_root: Path | str | None = None,
) -> dict[str, Any]:
    """Verify exact path and byte identity against a clean regeneration."""

    root = _absolute_without_following_symlinks(
        repository_root if repository_root is not None else _default_repository_root()
    )
    _load_and_verify_bound_sources(root)
    target = _absolute_without_following_symlinks(output_dir)
    _validate_output_ownership(target, require_complete=True)
    actual = _tree_snapshot(target)
    with tempfile.TemporaryDirectory(prefix="dsc-msproject-pilot-verify-") as temporary:
        regenerated = Path(temporary) / "pilot-kit"
        prepare_pilot(regenerated, repository_root=root)
        expected = _tree_snapshot(regenerated)
    if actual[0] != expected[0]:
        raise PilotVerificationError("pilot directory identity differs from regeneration")
    actual_files = actual[1]
    expected_files = expected[1]
    if actual_files.keys() != expected_files.keys():
        raise PilotVerificationError("pilot file identity differs from regeneration")
    changed = [
        relative_path
        for relative_path in actual_files
        if actual_files[relative_path] != expected_files[relative_path]
    ]
    if changed:
        raise PilotVerificationError(
            "pilot bytes differ from deterministic regeneration: " + ", ".join(changed)
        )
    return _result_summary(target, verified=True)


# Explicit aliases make the API readable to callers that use "kit" terminology.
prepare_pilot_kit = prepare_pilot
verify_pilot_kit = verify_pilot


__all__ = [
    "CASE_IDS",
    "COMPARISON_PROFILE_ID",
    "FIXTURE_RAW_SHA256_BY_CASE_ID",
    "FULL_PROFILE_CLAIM_ELIGIBLE_CASE_COUNT",
    "NATIVE_ATTEMPT_STOP_TEMPLATE",
    "PILOT_INPUT_IDENTITY_DOMAIN",
    "PILOT_ID",
    "PILOT_STATUS",
    "POST_EXECUTION_ATTESTATION_TEMPLATE",
    "POST_EXECUTION_ACTION_IDS_BY_TRACK",
    "PREREGISTRATION_ID",
    "SEALED_CONTROL_DIRECTORY",
    "SEALED_CONTROL_INDEX",
    "TRACK_IDS",
    "TRACK_A_POST_EXECUTION_ACTION_LOG_TEMPLATE",
    "TRACK_B_POST_EXECUTION_ACTION_LOG_TEMPLATE",
    "PilotBindingError",
    "PilotError",
    "PilotSafetyError",
    "PilotVerificationError",
    "prepare_pilot",
    "prepare_pilot_kit",
    "pilot_input_identity_projection",
    "pilot_input_identity_sha256",
    "verify_pilot",
    "verify_pilot_kit",
]
