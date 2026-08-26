from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Any

from rfc3339_validator import validate_rfc3339

from deterministic_scheduling_core.canonical.frozen_suite import (
    EXPECTED_FILENAME_BY_ID,
    EXPECTED_FIXTURE_SHA256_BY_FILENAME,
)
from deterministic_scheduling_core.provenance.canonical_json import (
    canonical_text,
    sha256_digest,
    write_canonical_json,
)


PILOT_ID = "microsoft-project-relationship-v0.1"
NATIVE_SYSTEM = "microsoft_project"
PILOT_INDEX_RELATIVE_PATH = (
    "native-validation/pilot-kits/microsoft-project-relationship-v0.1/pilot-index.json"
)
OWNER_MARKER = ".dsc-msproject-native-evidence-owner.json"
CASE_REALISATION_FILENAME = "case-realisation-manifest.json"
EXECUTION_TRACK_IDS = frozenset(
    {
        "manual_native_semantic_parity",
        "saved_file_reopen_recalculate_stability",
        "adapter_interchange_round_trip",
    }
)
RELATIONSHIP_TYPE_TO_MSPDI = {"FF": 0, "FS": 1, "SF": 2, "SS": 3}

# This is the frozen Microsoft Project preregistration's environment contract.
REQUIRED_ENVIRONMENT_FIELDS = (
    "product_name",
    "edition",
    "version",
    "build",
    "operating_system",
    "machine_architecture",
    "machine_time_zone",
    "locale",
    "execution_operator_id",
    "independent_reviewer_id",
    "native_file_format",
    "native_file_hashes_by_stage",
    "Microsoft_Project_project_calendar_and_scheduling_options",
    "Microsoft_Project_task_calendars",
    "Microsoft_Project_resource_calendars_and_capacities",
    "Microsoft_Project_task_scheduling_mode_type_and_effort_driven_fields",
    "Microsoft_Project_relationship_and_lag_settings",
    "Microsoft_Project_constraint_settings",
    "Microsoft_Project_project_start_and_status_date",
    "Microsoft_Project_calculation_and_progress_rescheduling_options",
    "Microsoft_Project_leveling_disabled_attestation",
    "manual_actions_by_stage",
)
PROFILE_REQUIRED_ENVIRONMENT_FIELDS = (
    "product_name",
    "edition",
    "version",
    "build",
    "operating_system",
    "machine_time_zone",
    "locale",
    "native_source_file_format",
    "native_source_file_sha256",
    "project_calendar_settings",
    "task_calendar_per_task",
    "resource_calendar_and_capacity_per_assignment",
    "task_scheduling_mode_per_task",
    "task_type_per_task",
    "effort_driven_per_task",
    "relationship_and_lag_settings",
    "constraint_settings",
    "project_start",
    "status_date",
    "calculation_mode",
    "progress_rescheduling_options",
    "resource_leveling_status",
    "manual_construction_actions",
)
ALL_REQUIRED_ENVIRONMENT_FIELDS = tuple(
    dict.fromkeys((*REQUIRED_ENVIRONMENT_FIELDS, *PROFILE_REQUIRED_ENVIRONMENT_FIELDS))
)
# These pilot-only fields close the gap between a planned manual mapping and
# the values actually displayed by Microsoft Project before calculation.
PILOT_REQUIRED_ENVIRONMENT_FIELDS = (
    "observed_native_activity_mapping",
    "observed_product_settings",
    "schedule_from_start",
    "precalculation_protocol_state",
    "manual_action_log_complete_attestation",
    "independent_verification_artifact_plan",
)

OBSERVED_PRODUCT_SETTING_IDS = (
    "project_calendar_settings",
    "task_duration_hours_per_task",
    "task_calendar_per_task",
    "task_scheduling_mode_per_task",
    "task_type_per_task",
    "effort_driven_per_task",
    "relationship_and_lag_settings",
    "constraint_settings",
    "project_start",
    "status_date",
    "schedule_from_start",
    "calculation_mode",
    "resource_leveling_status",
)

PRE_EXECUTION_ACTION_IDS = (
    "capture_product_environment",
    "configure_calculation_and_schedule_direction",
    "verify_continuous_calendar",
    "construct_and_verify_tasks",
    "construct_and_verify_relationships_and_constraints",
    "independent_pre_execution_review",
)

INDEPENDENT_VERIFICATION_EVIDENCE_ROLES = (
    "task_table",
    "project_information",
    "calendar_working_time",
    "predecessor_details",
    "task_mode_type_effort",
    "resource_leveling_status",
)

CASE_REALISATION_REQUIRED_KEYS = frozenset(
    {
        "schema_version",
        "pilot_id",
        "pilot_index_canonical_sha256",
        "pilot_index_raw_sha256",
        "pilot_index_path",
        "native_system",
        "state",
        "case_id",
        "execution_track_id",
        "prerequisite_manual_case_realization_manifest_sha256",
        "fixture_raw_sha256",
        "source_only_projection_path",
        "source_only_projection_raw_sha256",
        "preregistration_id",
        "preregistration_path",
        "preregistration_raw_sha256",
        "comparison_profile_id",
        "comparison_profile_path",
        "comparison_profile_raw_sha256",
        "native_source_file_sha256",
        "native_source_file_byte_size",
        "native_source_file_format",
        "raw_native_file_embedded",
        "environment_capture_sha256",
        "coordinate_contract",
        "native_activity_and_field_mapping",
        "native_calendar_realization",
        "native_relationship_and_lag_realization",
        "native_constraint_realization",
        "native_progress_realization",
        "all_product_settings",
        "captured_product_environment",
        "construction_action_log",
        "prepared_at",
        "prepared_by",
        "independent_pre_execution_reviewed_by",
        "attestation_no_native_result_observed_before_freeze",
        "claim_boundary",
    }
)


class NativeEvidenceError(ValueError):
    """A native-evidence input is incomplete, ambiguous, or unsafe."""


@dataclass(frozen=True, slots=True)
class FrozenNativeInput:
    manifest: dict[str, Any]
    manifest_path: Path
    manifest_sha256: str


@dataclass(frozen=True, slots=True)
class RegularFileSnapshot:
    """Immutable bytes and metadata read from one stable, no-follow file handle."""

    data: bytes
    sha256: str
    byte_size: int
    device: int
    inode: int
    resolved_path: Path

    @property
    def file_identity(self) -> tuple[int, int]:
        """Stable operating-system identity used to reject hard-link aliases."""

        return (self.device, self.inode)


def read_regular_file_snapshot(
    path: Path,
    *,
    label: str,
    max_bytes: int | None = None,
) -> RegularFileSnapshot:
    """Read a regular file once and reject replacement or mutation during the read.

    Hashes, byte sizes, JSON/XML parsing and later evidence bindings can all be
    derived from this one byte snapshot.  ``O_NOFOLLOW`` protects the final path
    component where the host provides it; the existing component checks and the
    post-read inode comparison cover the portable fallback.
    """

    _require_regular_file(path, label=label)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise NativeEvidenceError(f"{label} could not be opened safely: {exc}") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise NativeEvidenceError(f"{label} must be a regular file")
        if max_bytes is not None and before.st_size > max_bytes:
            raise NativeEvidenceError(
                f"{label} exceeds the {max_bytes}-byte evidence limit"
            )
        chunks: list[bytes] = []
        observed_size = 0
        while True:
            block = os.read(descriptor, 1024 * 1024)
            if not block:
                break
            observed_size += len(block)
            if max_bytes is not None and observed_size > max_bytes:
                raise NativeEvidenceError(
                    f"{label} exceeds the {max_bytes}-byte evidence limit"
                )
            chunks.append(block)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)

    try:
        current = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise NativeEvidenceError(f"{label} changed while it was read: {exc}") from exc
    _require_regular_file(path, label=label)
    stable_fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns")
    if any(getattr(before, field) != getattr(after, field) for field in stable_fields):
        raise NativeEvidenceError(f"{label} changed while it was read")
    if any(getattr(after, field) != getattr(current, field) for field in stable_fields):
        raise NativeEvidenceError(f"{label} was replaced while it was read")
    data = b"".join(chunks)
    if len(data) != after.st_size:
        raise NativeEvidenceError(f"{label} byte count changed while it was read")
    return RegularFileSnapshot(
        data=data,
        sha256=hashlib.sha256(data).hexdigest(),
        byte_size=len(data),
        device=after.st_dev,
        inode=after.st_ino,
        # Keep the lexical source path.  Calling ``resolve`` after the final
        # lstat would reopen a narrow race in which a replacement symlink could
        # affect the recorded path even though it cannot affect these bytes.
        resolved_path=path.absolute(),
    )


def raw_file_sha256(path: Path) -> str:
    return read_regular_file_snapshot(path, label="file to hash").sha256


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise NativeEvidenceError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def parse_canonical_json_snapshot(
    snapshot: RegularFileSnapshot, *, label: str
) -> dict[str, Any]:
    try:
        text = snapshot.data.decode("utf-8")
        document = json.loads(text, object_pairs_hook=_strict_object)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise NativeEvidenceError(f"{label} is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise NativeEvidenceError(f"{label} must be a JSON object")
    try:
        expected_text = canonical_text(document) + "\n"
    except (TypeError, ValueError) as exc:
        raise NativeEvidenceError(f"{label} is outside canonical JSON: {exc}") from exc
    if text != expected_text:
        raise NativeEvidenceError(
            f"{label} must use canonical JSON (dsc-canonical-json-v1) with one trailing LF"
        )
    return document


def load_canonical_json_snapshot(
    path: Path, *, label: str
) -> tuple[dict[str, Any], RegularFileSnapshot]:
    snapshot = read_regular_file_snapshot(path, label=label)
    return parse_canonical_json_snapshot(snapshot, label=label), snapshot


def load_canonical_json(path: Path, *, label: str) -> dict[str, Any]:
    document, _ = load_canonical_json_snapshot(path, label=label)
    return document


def _require_regular_file(path: Path, *, label: str) -> None:
    absolute = path.absolute()
    if any(candidate.is_symlink() for candidate in (absolute, *absolute.parents)):
        raise NativeEvidenceError(f"{label} path must not contain symbolic links")
    if not path.is_file():
        raise NativeEvidenceError(f"{label} must be a regular, non-symbolic-link file")


def _require_nonblank(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise NativeEvidenceError(f"{field} must be a nonblank string")
    return value


def _require_sha256(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise NativeEvidenceError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _binding_path(binding: Mapping[str, Any], *, label: str) -> str:
    value = binding.get("path", binding.get("relative_path"))
    return _require_nonblank(value, field=f"{label}.path")


def _safe_repository_file(repository_root: Path, relative_path: Any, *, label: str) -> Path:
    relative = _require_nonblank(relative_path, field=f"{label}.path")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts or "\\" in relative:
        raise NativeEvidenceError(f"{label}.path must be a safe repository-relative POSIX path")
    path = repository_root.joinpath(*pure.parts)
    _require_regular_file(path, label=label)
    resolved_root = repository_root.resolve()
    resolved_path = path.resolve()
    if resolved_path != resolved_root and resolved_root not in resolved_path.parents:
        raise NativeEvidenceError(f"{label}.path resolves outside the repository")
    return path


def _binding_container(pilot_index: Mapping[str, Any]) -> Mapping[str, Any]:
    for key in ("bindings", "source_bindings", "frozen_source_bindings"):
        value = pilot_index.get(key)
        if isinstance(value, Mapping):
            return value
    return pilot_index


def _named_binding(pilot_index: Mapping[str, Any], role: str) -> Mapping[str, Any]:
    container = _binding_container(pilot_index)
    aliases = {
        "preregistration": (
            "preregistration",
            "preregistration_binding",
            "microsoft_project_preregistration",
        ),
        "comparison_profile": (
            "comparison_profile",
            "comparison_profile_binding",
            "microsoft_project_comparison_profile",
        ),
    }[role]
    for key in aliases:
        value = container.get(key)
        if isinstance(value, Mapping):
            return value
        value = pilot_index.get(key)
        if isinstance(value, Mapping):
            return value
    values = container.get("documents")
    if isinstance(values, Sequence) and not isinstance(values, (str, bytes, bytearray)):
        matches = [item for item in values if isinstance(item, Mapping) and item.get("role") == role]
        if len(matches) == 1:
            return matches[0]
    raise NativeEvidenceError(f"pilot index has no unambiguous {role} binding")


def _binding_id(binding: Mapping[str, Any], role: str) -> str:
    keys = (
        ("preregistration_id", "id")
        if role == "preregistration"
        else ("profile_id", "comparison_profile_id", "id")
    )
    for key in keys:
        if key in binding:
            return _require_nonblank(binding[key], field=f"{role}.{key}")
    raise NativeEvidenceError(f"{role} binding has no identifier")


def _case_entries(pilot_index: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    source = pilot_index.get("cases", pilot_index.get("case_bindings"))
    if isinstance(source, Mapping):
        result: list[Mapping[str, Any]] = []
        for case_id, value in source.items():
            if not isinstance(value, Mapping):
                raise NativeEvidenceError("pilot case bindings must be objects")
            item = dict(value)
            item.setdefault("case_id", case_id)
            result.append(item)
        return result
    if isinstance(source, Sequence) and not isinstance(source, (str, bytes, bytearray)):
        if not all(isinstance(item, Mapping) for item in source):
            raise NativeEvidenceError("pilot cases must be objects")
        return list(source)
    raise NativeEvidenceError("pilot index must contain case bindings")


def _case_entry(pilot_index: Mapping[str, Any], case_id: str) -> Mapping[str, Any]:
    entries = _case_entries(pilot_index)
    identifiers = [_require_nonblank(item.get("case_id"), field="cases[].case_id") for item in entries]
    if len(identifiers) != len(set(identifiers)):
        raise NativeEvidenceError("pilot index contains duplicate case IDs")
    declared_ids = pilot_index.get("case_ids")
    if declared_ids is not None:
        if not isinstance(declared_ids, list) or not all(isinstance(item, str) for item in declared_ids):
            raise NativeEvidenceError("pilot index case_ids must be an ordered string array")
        if declared_ids != identifiers:
            raise NativeEvidenceError("pilot index case_ids must exactly match case binding order")
    matches = [item for item in entries if item["case_id"] == case_id]
    if not matches:
        raise NativeEvidenceError(f"case {case_id} does not belong to the pilot")
    return matches[0]


def _source_only_projection_binding(case_entry: Mapping[str, Any]) -> Mapping[str, Any]:
    value = case_entry.get("source_only_case_projection")
    if not isinstance(value, Mapping):
        raise NativeEvidenceError("pilot case has no source-only case projection binding")
    return value


def _frozen_fixture_raw_sha256(case_id: str) -> str:
    """Return the preregistered full-fixture identity without opening oracle bytes."""

    filename = EXPECTED_FILENAME_BY_ID.get(case_id)
    if filename is None:
        raise NativeEvidenceError(f"case {case_id} is outside the frozen semantic suite")
    digest = EXPECTED_FIXTURE_SHA256_BY_FILENAME.get(filename)
    if digest is None:
        raise NativeEvidenceError(f"case {case_id} has no frozen fixture identity")
    return _require_sha256(digest, field=f"frozen_fixture_registry.{filename}")


def _mapping_container(case_entry: Mapping[str, Any]) -> Mapping[str, Any]:
    for key in ("native_mapping", "native_realization", "mapping"):
        value = case_entry.get(key)
        if isinstance(value, Mapping):
            return value
    return case_entry


def _normalise_activity_mapping(case_entry: Mapping[str, Any]) -> list[dict[str, Any]]:
    container = _mapping_container(case_entry)
    source = container.get(
        "activities",
        container.get("activity_uid_mapping", container.get("native_activity_and_field_mapping")),
    )
    records: list[dict[str, Any]] = []
    if isinstance(source, Mapping):
        for activity_id, value in source.items():
            if isinstance(value, Mapping):
                uid = value.get("native_task_uid", value.get("task_uid"))
                native_task_id = value.get("native_task_id", value.get("task_id", uid))
                native_task_name = value.get("native_task_name", activity_id)
                duration_hours = value.get("canonical_duration_hours")
                calendar_id = value.get("canonical_calendar_id")
            else:
                uid = value
                native_task_id = value
                native_task_name = activity_id
                duration_hours = None
                calendar_id = None
            records.append(
                {
                    "activity_id": activity_id,
                    "native_task_uid": uid,
                    "native_task_id": native_task_id,
                    "native_task_name": native_task_name,
                    "canonical_duration_hours": duration_hours,
                    "canonical_calendar_id": calendar_id,
                }
            )
    elif isinstance(source, Sequence) and not isinstance(source, (str, bytes, bytearray)):
        for value in source:
            if not isinstance(value, Mapping):
                raise NativeEvidenceError("activity mapping entries must be objects")
            records.append(
                {
                    "activity_id": value.get("activity_id", value.get("canonical_activity_id")),
                    "native_task_uid": value.get("native_task_uid", value.get("task_uid")),
                    "native_task_id": value.get(
                        "native_task_id", value.get("task_id", value.get("native_task_uid", value.get("task_uid")))
                    ),
                    "native_task_name": value.get(
                        "native_task_name", value.get("task_name", value.get("activity_id"))
                    ),
                    "canonical_duration_hours": value.get("canonical_duration_hours"),
                    "canonical_calendar_id": value.get("canonical_calendar_id"),
                }
            )
    else:
        raise NativeEvidenceError("pilot case has no native activity/UID mapping")
    if not records:
        raise NativeEvidenceError("native activity/UID mapping must not be empty")
    activity_ids: set[str] = set()
    uids: set[int] = set()
    task_ids: set[int] = set()
    for record in records:
        activity_id = _require_nonblank(record["activity_id"], field="activity_id")
        uid = record["native_task_uid"]
        task_id = record["native_task_id"]
        _require_nonblank(record["native_task_name"], field=f"{activity_id}.native_task_name")
        duration_hours = record["canonical_duration_hours"]
        if isinstance(duration_hours, bool) or not isinstance(duration_hours, int) or duration_hours < 0:
            raise NativeEvidenceError(
                f"canonical duration for {activity_id} must be a nonnegative integer hour value"
            )
        _require_nonblank(
            record["canonical_calendar_id"], field=f"{activity_id}.canonical_calendar_id"
        )
        if isinstance(uid, bool) or not isinstance(uid, int) or uid < 0:
            raise NativeEvidenceError(f"native task UID for {activity_id} must be a nonnegative integer")
        if isinstance(task_id, bool) or not isinstance(task_id, int) or task_id < 0:
            raise NativeEvidenceError(f"native task ID for {activity_id} must be a nonnegative integer")
        if activity_id in activity_ids or uid in uids or task_id in task_ids:
            raise NativeEvidenceError("native activity mapping IDs and UIDs must be unique")
        activity_ids.add(activity_id)
        uids.add(uid)
        task_ids.add(task_id)
    return sorted(records, key=lambda item: item["activity_id"])


def _mapping_value(case_entry: Mapping[str, Any], *keys: str, allow_empty: bool = False) -> Any:
    container = _mapping_container(case_entry)
    for key in keys:
        if key in container:
            value = container[key]
            if not allow_empty and value in (None, [], {}):
                raise NativeEvidenceError(f"{key} realization must not be empty")
            return value
    raise NativeEvidenceError(f"pilot case is missing {keys[0]} realization")


def _normalise_relationship_mapping(
    case_entry: Mapping[str, Any], activity_mapping: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    source = _mapping_value(
        case_entry,
        "relationships",
        "relationship_mapping",
        "native_relationship_and_lag_realization",
    )
    if not isinstance(source, Sequence) or isinstance(source, (str, bytes, bytearray)):
        raise NativeEvidenceError("relationship realization must be an array")
    uid_by_activity = {item["activity_id"]: item["native_task_uid"] for item in activity_mapping}
    records: list[dict[str, Any]] = []
    relation_ids: set[str] = set()
    pairs: set[tuple[str, str]] = set()
    for value in source:
        if not isinstance(value, Mapping):
            raise NativeEvidenceError("relationship realization entries must be objects")
        relationship_id = _require_nonblank(
            value.get("relationship_id", value.get("id")), field="relationship_id"
        )
        predecessor = _require_nonblank(
            value.get("predecessor_activity_id", value.get("predecessor_id")),
            field=f"{relationship_id}.predecessor_activity_id",
        )
        successor = _require_nonblank(
            value.get("successor_activity_id", value.get("successor_id")),
            field=f"{relationship_id}.successor_activity_id",
        )
        canonical_type = _require_nonblank(
            value.get("canonical_type", value.get("relationship_type", value.get("type"))),
            field=f"{relationship_id}.canonical_type",
        )
        if canonical_type not in RELATIONSHIP_TYPE_TO_MSPDI:
            raise NativeEvidenceError(f"unsupported relationship type {canonical_type!r}")
        lag_hours = value.get("canonical_signed_lag_hours", value.get("signed_lag_hours", value.get("lag")))
        if isinstance(lag_hours, bool) or not isinstance(lag_hours, int):
            raise NativeEvidenceError(f"{relationship_id}.signed_lag_hours must be an integer")
        if predecessor not in uid_by_activity or successor not in uid_by_activity:
            raise NativeEvidenceError(f"{relationship_id} contains an unresolved activity reference")
        native_type = value.get("native_type", value.get("mspdi_type", RELATIONSHIP_TYPE_TO_MSPDI[canonical_type]))
        expected_native_type = RELATIONSHIP_TYPE_TO_MSPDI[canonical_type]
        if native_type != expected_native_type:
            raise NativeEvidenceError(
                f"{relationship_id} native Type {native_type!r} does not encode {canonical_type}"
            )
        native_lag = value.get(
            "native_link_lag_tenths_minutes",
            value.get("mspdi_link_lag", lag_hours * 600),
        )
        if native_lag != lag_hours * 600:
            raise NativeEvidenceError(
                f"{relationship_id} native LinkLag {native_lag!r} changes signed lag {lag_hours}h"
            )
        native_lag_format = value.get("native_lag_format", value.get("mspdi_lag_format"))
        if native_lag_format != 5:
            raise NativeEvidenceError(
                f"{relationship_id} native LagFormat must be the reviewed hours value 5"
            )
        if relationship_id in relation_ids or (predecessor, successor) in pairs:
            raise NativeEvidenceError("relationship realization identities must be unique")
        relation_ids.add(relationship_id)
        pairs.add((predecessor, successor))
        records.append(
            {
                "relationship_id": relationship_id,
                "predecessor_activity_id": predecessor,
                "successor_activity_id": successor,
                "native_predecessor_uid": uid_by_activity[predecessor],
                "native_successor_uid": uid_by_activity[successor],
                "canonical_type": canonical_type,
                "native_type": native_type,
                "canonical_signed_lag_hours": lag_hours,
                "native_link_lag_tenths_minutes": native_lag,
                "native_lag_format": native_lag_format,
            }
        )
    return sorted(records, key=lambda item: item["relationship_id"])


def _validate_observed_activity_mapping(
    value: Any,
    *,
    planned_mapping: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise NativeEvidenceError("observed_native_activity_mapping must be an ordered array")
    if len(value) != len(planned_mapping):
        raise NativeEvidenceError(
            "observed_native_activity_mapping must cover every planned activity exactly once"
        )
    expected_keys = {
        "activity_id",
        "native_task_id",
        "native_task_uid",
        "native_task_name",
    }
    observed: list[dict[str, Any]] = []
    task_ids: set[int] = set()
    task_uids: set[int] = set()
    for position, (item, planned) in enumerate(zip(value, planned_mapping, strict=True), start=1):
        if not isinstance(item, Mapping) or set(item) != expected_keys:
            raise NativeEvidenceError(
                "each observed activity mapping must contain exactly activity_id, "
                "native_task_id, native_task_uid, and native_task_name"
            )
        activity_id = _require_nonblank(
            item["activity_id"], field=f"observed_native_activity_mapping[{position}].activity_id"
        )
        task_name = _require_nonblank(
            item["native_task_name"],
            field=f"observed_native_activity_mapping[{position}].native_task_name",
        )
        task_id = item["native_task_id"]
        task_uid = item["native_task_uid"]
        if isinstance(task_id, bool) or not isinstance(task_id, int) or task_id < 0:
            raise NativeEvidenceError(f"observed native task ID for {activity_id} is invalid")
        if isinstance(task_uid, bool) or not isinstance(task_uid, int) or task_uid < 0:
            raise NativeEvidenceError(f"observed native task UID for {activity_id} is invalid")
        if task_id in task_ids or task_uid in task_uids:
            raise NativeEvidenceError("observed native task IDs and UIDs must be unique")
        required_identity = {
            "activity_id": planned["activity_id"],
            "native_task_id": planned["native_task_id"],
            "native_task_uid": planned["native_task_uid"],
            "native_task_name": planned["native_task_name"],
        }
        if dict(item) != required_identity:
            raise NativeEvidenceError(
                f"observed native identity for {activity_id} does not match the reviewed pilot mapping"
            )
        task_ids.add(task_id)
        task_uids.add(task_uid)
        observed.append(
            {
                **dict(planned),
                "native_task_id": task_id,
                "native_task_uid": task_uid,
                "native_task_name": task_name,
                "native_identity_source": "observed_and_independently_verified_before_freeze",
            }
        )
    return observed


def _validate_manual_actions(
    value: Any,
    *,
    prepared_by: str,
    reviewed_by: str,
    prepared_at: str,
) -> list[Mapping[str, Any]]:
    if not isinstance(value, list) or len(value) != len(PRE_EXECUTION_ACTION_IDS):
        raise NativeEvidenceError(
            "manual_actions_by_stage must contain the exact ordered pre-execution action set"
        )
    expected_keys = {
        "sequence",
        "action_id",
        "stage",
        "action",
        "performed_by",
        "performed_at",
        "evidence_roles",
    }
    covered_evidence_roles: set[str] = set()
    prepared_instant = datetime.fromisoformat(prepared_at.replace("Z", "+00:00"))
    previous_instant: datetime | None = None
    for sequence, (item, expected_action_id) in enumerate(
        zip(value, PRE_EXECUTION_ACTION_IDS, strict=True), start=1
    ):
        if not isinstance(item, Mapping) or set(item) != expected_keys:
            raise NativeEvidenceError(
                "each manual action must contain exactly sequence, action_id, stage, action, "
                "performed_by, performed_at, and evidence_roles"
            )
        if item["sequence"] != sequence or item["action_id"] != expected_action_id:
            raise NativeEvidenceError("manual actions must retain the reviewed ID and order")
        if item["stage"] != "pre_execution":
            raise NativeEvidenceError("manual action stage must remain pre_execution")
        _require_nonblank(item["action"], field=f"manual action {expected_action_id}.action")
        expected_actor = (
            reviewed_by
            if expected_action_id == "independent_pre_execution_review"
            else prepared_by
        )
        if item["performed_by"] != expected_actor:
            raise NativeEvidenceError(
                f"manual action {expected_action_id} must be performed by {expected_actor!r}"
            )
        performed_at = item["performed_at"]
        if not isinstance(performed_at, str) or not validate_rfc3339(performed_at):
            raise NativeEvidenceError(
                f"manual action {expected_action_id}.performed_at must be RFC 3339"
            )
        performed_instant = datetime.fromisoformat(
            performed_at.replace("Z", "+00:00")
        )
        if performed_instant > prepared_instant:
            raise NativeEvidenceError(
                f"manual action {expected_action_id}.performed_at must not be after prepared_at"
            )
        if previous_instant is not None and performed_instant <= previous_instant:
            raise NativeEvidenceError(
                "manual action performed_at values must be strictly chronological"
            )
        previous_instant = performed_instant
        roles = item["evidence_roles"]
        if not isinstance(roles, list) or not roles or not all(
            isinstance(role, str) and role in INDEPENDENT_VERIFICATION_EVIDENCE_ROLES
            for role in roles
        ):
            raise NativeEvidenceError(
                f"manual action {expected_action_id}.evidence_roles are incomplete or unknown"
            )
        if len(roles) != len(set(roles)):
            raise NativeEvidenceError(
                f"manual action {expected_action_id}.evidence_roles contain duplicates"
            )
        covered_evidence_roles.update(roles)
    if covered_evidence_roles != set(INDEPENDENT_VERIFICATION_EVIDENCE_ROLES):
        raise NativeEvidenceError(
            "manual action log must cover every required independent-verification evidence role"
        )
    return value


def _validate_progress_rescheduling_options(value: Any) -> Mapping[str, Any]:
    expected_keys = {
        "source_case_has_progress",
        "capture_complete_attestation",
        "native_displayed_settings",
    }
    if not isinstance(value, Mapping) or set(value) != expected_keys:
        raise NativeEvidenceError(
            "progress_rescheduling_options must contain the exact reviewed capture fields"
        )
    if value["source_case_has_progress"] is not False:
        raise NativeEvidenceError("relationship pilot source cases must record no progress data")
    if value["capture_complete_attestation"] is not True:
        raise NativeEvidenceError(
            "progress rescheduling options require a complete-capture attestation"
        )
    settings = value["native_displayed_settings"]
    if not isinstance(settings, list) or not settings:
        raise NativeEvidenceError(
            "progress rescheduling options must list the native displayed settings"
        )
    names: set[str] = set()
    for item in settings:
        if not isinstance(item, Mapping) or set(item) != {"setting_name", "displayed_value"}:
            raise NativeEvidenceError(
                "each progress rescheduling setting must contain setting_name and displayed_value"
            )
        name = _require_nonblank(item["setting_name"], field="progress setting_name")
        _require_nonblank(item["displayed_value"], field=f"progress setting {name}.displayed_value")
        if name in names:
            raise NativeEvidenceError("progress rescheduling setting names must be unique")
        names.add(name)
    return value


def _validate_verification_plan(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list) or len(value) != len(
        INDEPENDENT_VERIFICATION_EVIDENCE_ROLES
    ):
        raise NativeEvidenceError(
            "independent_verification_artifact_plan must contain every exact evidence role"
        )
    expected_keys = {"role", "planned_evidence_type", "description"}
    for item, expected_role in zip(
        value, INDEPENDENT_VERIFICATION_EVIDENCE_ROLES, strict=True
    ):
        if not isinstance(item, Mapping) or set(item) != expected_keys:
            raise NativeEvidenceError(
                "each independent-verification artifact plan entry must contain exactly "
                "role, planned_evidence_type, and description"
            )
        if item["role"] != expected_role:
            raise NativeEvidenceError(
                "independent-verification artifact roles must retain the reviewed order"
            )
        if item["planned_evidence_type"] not in {"screenshot", "native_report"}:
            raise NativeEvidenceError(
                f"independent-verification role {expected_role} must plan a screenshot or native report"
            )
        _require_nonblank(
            item["description"], field=f"independent verification {expected_role}.description"
        )
    return value


def _validate_observed_product_settings(
    value: Any,
    *,
    required_values: Mapping[str, Any],
    prepared_by: str,
    reviewed_by: str,
    prepared_at: str,
) -> Mapping[str, Any]:
    """Require operator-observed settings with independent review provenance."""

    if not isinstance(value, Mapping) or set(value) != set(
        OBSERVED_PRODUCT_SETTING_IDS
    ):
        raise NativeEvidenceError(
            "observed_product_settings must contain every exact reviewed setting"
        )
    if set(required_values) != set(OBSERVED_PRODUCT_SETTING_IDS):
        raise NativeEvidenceError("internal observed-product-setting contract is incomplete")
    exact_record_keys = {
        "required_value",
        "observed_value",
        "observed_at",
        "observed_by",
        "independently_verified_at",
        "independently_verified_by",
    }
    for setting_id in OBSERVED_PRODUCT_SETTING_IDS:
        record = value[setting_id]
        if not isinstance(record, Mapping) or set(record) != exact_record_keys:
            raise NativeEvidenceError(
                f"observed product setting {setting_id} has an inexact observation shape"
            )
        required = required_values[setting_id]
        if record["required_value"] != required:
            raise NativeEvidenceError(
                f"observed product setting {setting_id}.required_value changed"
            )
        if record["observed_value"] != required:
            raise NativeEvidenceError(
                f"observed product setting {setting_id}.observed_value is incomplete or mismatched"
            )
        if record["observed_by"] != prepared_by:
            raise NativeEvidenceError(
                f"observed product setting {setting_id}.observed_by must equal prepared_by"
            )
        if record["independently_verified_by"] != reviewed_by:
            raise NativeEvidenceError(
                f"observed product setting {setting_id}.independently_verified_by must equal the reviewer"
            )
        parsed_times: dict[str, datetime] = {}
        for timestamp_field in ("observed_at", "independently_verified_at"):
            timestamp = record[timestamp_field]
            if not isinstance(timestamp, str) or not validate_rfc3339(timestamp):
                raise NativeEvidenceError(
                    f"observed product setting {setting_id}.{timestamp_field} must be RFC 3339"
                )
            parsed_times[timestamp_field] = datetime.fromisoformat(
                timestamp.replace("Z", "+00:00")
            )
        prepared_instant = datetime.fromisoformat(prepared_at.replace("Z", "+00:00"))
        if not (
            parsed_times["observed_at"]
            <= parsed_times["independently_verified_at"]
            <= prepared_instant
        ):
            raise NativeEvidenceError(
                f"observed product setting {setting_id} must be observed, independently "
                "verified, and frozen in chronological order"
            )
    return value


def _validate_environment(
    document: Mapping[str, Any],
    *,
    prepared_by: str,
    reviewed_by: str,
    prepared_at: str,
    track_id: str,
    native_sha256: str,
    activity_mapping: Sequence[Mapping[str, Any]],
    relationship_mapping: Sequence[Mapping[str, Any]],
    constraint_realization: Sequence[Mapping[str, Any]],
    coordinate_contract: Mapping[str, Any],
) -> list[dict[str, Any]]:
    required_fields = (*ALL_REQUIRED_ENVIRONMENT_FIELDS, *PILOT_REQUIRED_ENVIRONMENT_FIELDS)
    missing = [field for field in required_fields if field not in document]
    if missing:
        raise NativeEvidenceError(f"environment capture is missing required fields: {missing}")
    for field in (
        "product_name",
        "edition",
        "version",
        "build",
        "operating_system",
        "machine_architecture",
        "machine_time_zone",
        "locale",
        "execution_operator_id",
        "independent_reviewer_id",
        "native_file_format",
    ):
        _require_nonblank(document[field], field=f"environment_capture.{field}")
    if document["product_name"] != "Microsoft Project":
        raise NativeEvidenceError("environment capture product_name must be 'Microsoft Project'")
    if "windows" not in document["operating_system"].casefold():
        raise NativeEvidenceError("environment operating_system must record the Windows version")
    if document["machine_time_zone"] != coordinate_contract.get("schedule_time_zone"):
        raise NativeEvidenceError(
            "environment machine_time_zone must equal the frozen schedule time zone"
        )
    if document["execution_operator_id"] != prepared_by:
        raise NativeEvidenceError("environment execution_operator_id must equal prepared_by")
    if document["independent_reviewer_id"] != reviewed_by:
        raise NativeEvidenceError(
            "environment independent_reviewer_id must equal independent_pre_execution_reviewed_by"
        )
    if track_id == "adapter_interchange_round_trip" and document["native_file_format"] != "mspdi_xml":
        raise NativeEvidenceError("adapter_interchange_round_trip requires native_file_format=mspdi_xml")
    if track_id != "adapter_interchange_round_trip" and document["native_file_format"] != "mpp":
        raise NativeEvidenceError("manual and reopen tracks require native_file_format=mpp")
    if document["native_source_file_format"] != document["native_file_format"]:
        raise NativeEvidenceError("native source file-format captures must agree")
    if document["native_source_file_sha256"] != native_sha256:
        raise NativeEvidenceError("environment native_source_file_sha256 does not match the input")
    if document["Microsoft_Project_leveling_disabled_attestation"] is not True:
        raise NativeEvidenceError("environment capture must attest that resource leveling is disabled")
    if not isinstance(document["native_file_hashes_by_stage"], Mapping):
        raise NativeEvidenceError("environment native_file_hashes_by_stage must be an object")
    stage_hashes = document["native_file_hashes_by_stage"]
    if dict(stage_hashes) != {"native_source_file_sha256": native_sha256}:
        raise NativeEvidenceError(
            "pre-execution native_file_hashes_by_stage must contain only "
            "native_source_file_sha256"
        )
    actions = _validate_manual_actions(
        document["manual_actions_by_stage"],
        prepared_by=prepared_by,
        reviewed_by=reviewed_by,
        prepared_at=prepared_at,
    )
    if document["manual_construction_actions"] != actions:
        raise NativeEvidenceError("the two required manual-action captures must agree")
    if document["manual_action_log_complete_attestation"] is not True:
        raise NativeEvidenceError("manual action log requires an affirmative completeness attestation")
    if document["resource_leveling_status"] != "disabled_and_not_run":
        raise NativeEvidenceError("resource_leveling_status must be disabled_and_not_run")

    observed_activity_mapping = _validate_observed_activity_mapping(
        document["observed_native_activity_mapping"], planned_mapping=activity_mapping
    )

    activity_ids = [item["activity_id"] for item in activity_mapping]
    expected_keys = set(activity_ids)

    def exact_activity_map(field: str) -> Mapping[str, Any]:
        value = document[field]
        if not isinstance(value, Mapping) or set(value) != expected_keys:
            raise NativeEvidenceError(
                f"environment {field} must cover exactly the mapped activity IDs"
            )
        return value

    project_calendar = document["project_calendar_settings"]
    if not isinstance(project_calendar, Mapping) or dict(project_calendar) != {
        "canonical_calendar_id": "CAL-24X7",
        "native_calendar_name": "24 Hours",
        "continuous_working_time_verified": True,
    }:
        raise NativeEvidenceError(
            "project_calendar_settings must record the verified built-in 24 Hours realization"
        )
    task_calendars = exact_activity_map("task_calendar_per_task")
    if any(value != "24 Hours" for value in task_calendars.values()):
        raise NativeEvidenceError("every task calendar must be the verified built-in 24 Hours calendar")
    modes = exact_activity_map("task_scheduling_mode_per_task")
    if any(value != "automatically_scheduled" for value in modes.values()):
        raise NativeEvidenceError("every task must be recorded as automatically_scheduled")
    task_types = exact_activity_map("task_type_per_task")
    if any(value != "fixed_duration" for value in task_types.values()):
        raise NativeEvidenceError("every task must be recorded as fixed_duration")
    effort = exact_activity_map("effort_driven_per_task")
    if any(value is not False for value in effort.values()):
        raise NativeEvidenceError("every task must record effort_driven=false")
    resources = document["resource_calendar_and_capacity_per_assignment"]
    if not isinstance(resources, Mapping) or resources:
        raise NativeEvidenceError("relationship pilot resource mapping must remain an empty object")

    expected_relationships = {
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
        for item in relationship_mapping
    }
    if document["relationship_and_lag_settings"] != expected_relationships:
        raise NativeEvidenceError(
            "relationship_and_lag_settings do not exactly match the frozen native mapping"
        )
    expected_constraints = {
        item["constraint_id"]: {
            "activity_id": item["activity_id"],
            "canonical_type": item["canonical_type"],
            "canonical_coordinate": item["canonical_coordinate"],
            "canonical_timestamp": item["canonical_timestamp"],
            "native_constraint_type": item["native_constraint_type"],
        }
        for item in constraint_realization
    }
    if document["constraint_settings"] != expected_constraints:
        raise NativeEvidenceError(
            "constraint_settings do not exactly match the frozen native mapping"
        )
    if document["project_start"] != coordinate_contract.get("canonical_origin"):
        raise NativeEvidenceError("project_start must equal the frozen canonical origin")
    if document["status_date"] is not None:
        raise NativeEvidenceError("relationship pilot status_date must remain null")
    if document["schedule_from_start"] is not True:
        raise NativeEvidenceError("schedule_from_start must be true")
    if document["calculation_mode"] != "manual":
        raise NativeEvidenceError("calculation_mode must record Microsoft Project manual mode")
    if document["precalculation_protocol_state"] != "constructed_not_calculated":
        raise NativeEvidenceError(
            "precalculation_protocol_state must remain constructed_not_calculated until freeze"
        )
    progress_options = _validate_progress_rescheduling_options(
        document["progress_rescheduling_options"]
    )
    _validate_verification_plan(document["independent_verification_artifact_plan"])
    _validate_observed_product_settings(
        document["observed_product_settings"],
        required_values={
            "project_calendar_settings": {
                "canonical_calendar_id": "CAL-24X7",
                "native_calendar_name": "24 Hours",
                "continuous_working_time_verified": True,
            },
            "task_duration_hours_per_task": {
                item["activity_id"]: item["canonical_duration_hours"]
                for item in activity_mapping
            },
            "task_calendar_per_task": dict(task_calendars),
            "task_scheduling_mode_per_task": dict(modes),
            "task_type_per_task": dict(task_types),
            "effort_driven_per_task": dict(effort),
            "relationship_and_lag_settings": expected_relationships,
            "constraint_settings": expected_constraints,
            "project_start": coordinate_contract.get("canonical_origin"),
            "status_date": None,
            "schedule_from_start": True,
            "calculation_mode": "manual",
            "resource_leveling_status": "disabled_and_not_run",
        },
        prepared_by=prepared_by,
        reviewed_by=reviewed_by,
        prepared_at=prepared_at,
    )

    if document["Microsoft_Project_task_calendars"] != task_calendars:
        raise NativeEvidenceError("Microsoft Project task-calendar captures disagree")
    if document["Microsoft_Project_resource_calendars_and_capacities"] != resources:
        raise NativeEvidenceError("Microsoft Project resource-calendar captures disagree")
    combined_task_fields = {
        activity_id: {
            "task_scheduling_mode": modes[activity_id],
            "task_type": task_types[activity_id],
            "effort_driven": effort[activity_id],
        }
        for activity_id in activity_ids
    }
    if (
        document["Microsoft_Project_task_scheduling_mode_type_and_effort_driven_fields"]
        != combined_task_fields
    ):
        raise NativeEvidenceError("Microsoft Project task-setting captures disagree")
    if document["Microsoft_Project_relationship_and_lag_settings"] != expected_relationships:
        raise NativeEvidenceError("Microsoft Project relationship captures disagree")
    if document["Microsoft_Project_constraint_settings"] != expected_constraints:
        raise NativeEvidenceError("Microsoft Project constraint captures disagree")
    if document["Microsoft_Project_project_start_and_status_date"] != {
        "project_start": document["project_start"],
        "status_date": document["status_date"],
    }:
        raise NativeEvidenceError("Microsoft Project project-start/status-date captures disagree")
    if document["Microsoft_Project_calculation_and_progress_rescheduling_options"] != {
        "calculation_mode": document["calculation_mode"],
        "precalculation_protocol_state": document["precalculation_protocol_state"],
        "progress_rescheduling_options": progress_options,
    }:
        raise NativeEvidenceError("Microsoft Project calculation/progress captures disagree")
    if document["Microsoft_Project_project_calendar_and_scheduling_options"] != {
        "project_calendar_settings": project_calendar,
        "calculation_mode": document["calculation_mode"],
        "schedule_from_start": document["schedule_from_start"],
    }:
        raise NativeEvidenceError("Microsoft Project project-calendar captures disagree")
    return observed_activity_mapping


def _environment_capture(document: Mapping[str, Any]) -> Mapping[str, Any]:
    capture = document.get("capture")
    if capture is None:
        return document
    if not isinstance(capture, Mapping):
        raise NativeEvidenceError("environment capture field must be an object")
    return capture


def _reject_blocked_adapter_preparation(
    *,
    pilot_index: Mapping[str, Any],
    case: Mapping[str, Any],
    track_id: str,
) -> None:
    """Fail closed when any tracked scope blocks the adapter execution track.

    The freeze path is not the only consumer of a case-realisation manifest.
    In particular, the output analyser can be given retained or hand-authored
    manifest bytes.  Rechecking every pilot- and case-level adapter status
    against the tracked index prevents those bytes from bypassing a blocker
    that was already in force when the repository was read.
    """

    if track_id != "adapter_interchange_round_trip":
        return

    blocked_sources: list[str] = []
    if pilot_index.get("adapter_preparation_status") == "preparation_blocked":
        blocked_sources.append("pilot adapter_preparation_status")

    execution_tracks = pilot_index.get("execution_tracks", [])
    if isinstance(execution_tracks, Sequence) and not isinstance(
        execution_tracks, (str, bytes, bytearray)
    ):
        for track in execution_tracks:
            if (
                isinstance(track, Mapping)
                and track.get("track_id") == track_id
                and track.get("adapter_preparation_status") == "preparation_blocked"
            ):
                blocked_sources.append("pilot execution-track adapter_preparation_status")

    if case.get("adapter_preparation_status") == "preparation_blocked":
        blocked_sources.append("case adapter_preparation_status")
    case_tracks = case.get("tracks", {})
    if isinstance(case_tracks, Mapping):
        case_track = case_tracks.get(track_id, {})
        if (
            isinstance(case_track, Mapping)
            and case_track.get("adapter_preparation_status") == "preparation_blocked"
        ):
            blocked_sources.append("case execution-track adapter_preparation_status")

    if not blocked_sources:
        return
    case_id = _require_nonblank(case.get("case_id"), field="case.case_id")
    reason = case.get(
        "adapter_preparation_blocked_reason",
        "CAL-24X7 adapter serialization remains unresolved",
    )
    if not isinstance(reason, str) or not reason.strip():
        reason = "CAL-24X7 adapter serialization remains unresolved"
    raise NativeEvidenceError(
        f"adapter preparation for {case_id} is blocked by "
        f"{', '.join(blocked_sources)}: {reason}"
    )


def validate_case_realisation_manifest(document: Mapping[str, Any]) -> None:
    """Validate the complete frozen pre-execution manifest contract.

    This validator is deliberately stricter than the output normalizer's
    minimum parser contract.  In particular, it prevents a hand-written
    partial JSON document from being used as a Track B prerequisite.
    """

    if set(document) != CASE_REALISATION_REQUIRED_KEYS:
        missing = sorted(CASE_REALISATION_REQUIRED_KEYS - set(document))
        extra = sorted(set(document) - CASE_REALISATION_REQUIRED_KEYS)
        raise NativeEvidenceError(
            f"case-realisation manifest has an inexact key set; missing={missing}, extra={extra}"
        )
    expected_scalars = {
        "schema_version": "msproject-case-realisation-manifest-v0.2",
        "pilot_id": PILOT_ID,
        "pilot_index_path": PILOT_INDEX_RELATIVE_PATH,
        "native_system": NATIVE_SYSTEM,
        "state": "frozen_before_native_calculation",
    }
    for field, expected in expected_scalars.items():
        if document[field] != expected:
            raise NativeEvidenceError(
                f"case-realisation manifest {field} must be {expected!r}"
            )
    case_id = _require_nonblank(document["case_id"], field="manifest.case_id")
    track_id = _require_nonblank(
        document["execution_track_id"], field="manifest.execution_track_id"
    )
    if track_id not in EXECUTION_TRACK_IDS:
        raise NativeEvidenceError("case-realisation manifest has an unknown execution track")
    prerequisite = document["prerequisite_manual_case_realization_manifest_sha256"]
    if track_id == "saved_file_reopen_recalculate_stability":
        _require_sha256(prerequisite, field="manifest.prerequisite_manual_manifest_sha256")
    elif prerequisite is not None:
        raise NativeEvidenceError(
            "only a reopen/recalculate manifest may bind a prerequisite manual manifest"
        )
    for field in (
        "pilot_index_canonical_sha256",
        "pilot_index_raw_sha256",
        "fixture_raw_sha256",
        "source_only_projection_raw_sha256",
        "preregistration_raw_sha256",
        "comparison_profile_raw_sha256",
        "native_source_file_sha256",
        "environment_capture_sha256",
    ):
        _require_sha256(document[field], field=f"manifest.{field}")
    for field in (
        "source_only_projection_path",
        "preregistration_id",
        "preregistration_path",
        "comparison_profile_id",
        "comparison_profile_path",
        "native_source_file_format",
    ):
        _require_nonblank(document[field], field=f"manifest.{field}")
    native_size = document["native_source_file_byte_size"]
    if isinstance(native_size, bool) or not isinstance(native_size, int) or native_size <= 0:
        raise NativeEvidenceError("manifest native_source_file_byte_size must be positive")
    if document["raw_native_file_embedded"] is not False:
        raise NativeEvidenceError("raw native files must not be embedded in repository evidence")
    if document["native_source_file_format"] != (
        "mspdi_xml" if track_id == "adapter_interchange_round_trip" else "mpp"
    ):
        raise NativeEvidenceError("manifest native source format does not match its track")

    coordinate_contract = document["coordinate_contract"]
    expected_coordinate_keys = {
        "canonical_origin",
        "canonical_unit",
        "schedule_time_zone",
        "utc_offset",
        "timestamp_tolerance_seconds",
        "rounding_policy",
    }
    if not isinstance(coordinate_contract, Mapping) or set(coordinate_contract) != expected_coordinate_keys:
        raise NativeEvidenceError("manifest coordinate contract has an inexact shape")
    if coordinate_contract != {
        "canonical_origin": "2026-01-05T08:00:00+08:00",
        "canonical_unit": "hour",
        "schedule_time_zone": "Australia/Perth",
        "utc_offset": "+08:00",
        "timestamp_tolerance_seconds": 0,
        "rounding_policy": "forbidden",
    }:
        raise NativeEvidenceError("manifest coordinate contract differs from the pilot freeze")

    activity_mapping = document["native_activity_and_field_mapping"]
    if not isinstance(activity_mapping, list):
        raise NativeEvidenceError("manifest activity mapping must be an array")
    normalized_activity_mapping = _normalise_activity_mapping(
        {"native_mapping": {"activities": activity_mapping}}
    )
    relationships = document["native_relationship_and_lag_realization"]
    if not isinstance(relationships, list):
        raise NativeEvidenceError("manifest relationship realization must be an array")
    _normalise_relationship_mapping(
        {"native_mapping": {"relationships": relationships}},
        normalized_activity_mapping,
    )
    for field in (
        "native_calendar_realization",
        "native_constraint_realization",
        "native_progress_realization",
    ):
        value = document[field]
        if not isinstance(value, list) or (field == "native_calendar_realization" and not value):
            raise NativeEvidenceError(f"manifest {field} must be an appropriate array")
        if not all(isinstance(item, Mapping) for item in value):
            raise NativeEvidenceError(f"manifest {field} entries must be objects")
    settings = document["all_product_settings"]
    if not isinstance(settings, Mapping):
        raise NativeEvidenceError("manifest all_product_settings must be an object")
    for field, expected in {
        "schedule_from_start": True,
        "new_tasks_are_manual": False,
        "task_pinned": 0,
        "task_type": "fixed_duration",
        "effort_driven": False,
        "resource_leveling": "disabled_and_not_run",
    }.items():
        if settings.get(field) != expected:
            raise NativeEvidenceError(
                f"manifest product setting {field} must remain {expected!r}"
            )

    prepared_by = _require_nonblank(document["prepared_by"], field="manifest.prepared_by")
    reviewed_by = _require_nonblank(
        document["independent_pre_execution_reviewed_by"],
        field="manifest.independent_pre_execution_reviewed_by",
    )
    if prepared_by == reviewed_by:
        raise NativeEvidenceError("manifest preparer and reviewer must differ")
    prepared_at = document["prepared_at"]
    if not isinstance(prepared_at, str) or not validate_rfc3339(prepared_at):
        raise NativeEvidenceError("manifest prepared_at must be RFC 3339")
    if document["attestation_no_native_result_observed_before_freeze"] is not True:
        raise NativeEvidenceError("manifest lacks the no-result-observed attestation")

    environment = document["captured_product_environment"]
    if not isinstance(environment, Mapping):
        raise NativeEvidenceError("manifest captured_product_environment must be an object")
    realized = _validate_environment(
        environment,
        prepared_by=prepared_by,
        reviewed_by=reviewed_by,
        prepared_at=prepared_at,
        track_id=track_id,
        native_sha256=document["native_source_file_sha256"],
        activity_mapping=normalized_activity_mapping,
        relationship_mapping=relationships,
        constraint_realization=document["native_constraint_realization"],
        coordinate_contract=coordinate_contract,
    )
    if realized != activity_mapping:
        raise NativeEvidenceError(
            "manifest activity mapping is not the observed environment realization"
        )
    if document["construction_action_log"] != environment["manual_actions_by_stage"]:
        raise NativeEvidenceError("manifest construction action log differs from its environment")
    if document["claim_boundary"] != {
        "native_result_exists": False,
        "compatibility_claim_exists": False,
        "full_45_case_gate_satisfied": False,
    }:
        raise NativeEvidenceError("manifest claim boundary is not the frozen pre-execution boundary")
    if not case_id.startswith("SEM-REL-"):
        raise NativeEvidenceError("manifest case is outside the relationship pilot")


def validate_case_realisation_manifest_against_repository(
    *,
    repository_root: Path,
    document: Mapping[str, Any],
    environment_capture_path: Path,
) -> None:
    """Revalidate a frozen manifest without opening fixture-oracle bytes.

    The full fixture digest comes from the immutable semantic-suite identity
    registry.  Only the source-only operator projection is opened here.  A
    Track-A analyser releases the separately tracked sealed comparison control
    after it has durably persisted the normalized native observation.
    """

    validate_case_realisation_manifest(document)
    repository_root = repository_root.resolve()
    if not repository_root.is_dir():
        raise NativeEvidenceError("repository_root must be a directory")
    tracked_index_path = _safe_repository_file(
        repository_root,
        PILOT_INDEX_RELATIVE_PATH,
        label="tracked pilot index",
    )
    pilot_index, pilot_index_snapshot = load_canonical_json_snapshot(
        tracked_index_path, label="tracked pilot index"
    )
    if pilot_index.get("pilot_id") != PILOT_ID or pilot_index.get("status") != "prepared_not_executed":
        raise NativeEvidenceError("tracked pilot index is not the frozen prepared pilot")
    expected_index_values = {
        "pilot_index_raw_sha256": pilot_index_snapshot.sha256,
        "pilot_index_canonical_sha256": sha256_digest(pilot_index),
        "pilot_index_path": PILOT_INDEX_RELATIVE_PATH,
    }
    for field, expected in expected_index_values.items():
        if document[field] != expected:
            raise NativeEvidenceError(f"manifest {field} does not match the tracked pilot index")

    case_id = document["case_id"]
    case = _case_entry(pilot_index, case_id)
    _reject_blocked_adapter_preparation(
        pilot_index=pilot_index,
        case=case,
        track_id=document["execution_track_id"],
    )
    activity_mapping = _normalise_activity_mapping(case)
    expected_observed_mapping = [
        {
            **item,
            "native_identity_source": "observed_and_independently_verified_before_freeze",
        }
        for item in activity_mapping
    ]
    relationship_mapping = _normalise_relationship_mapping(case, activity_mapping)
    calendar_realization = _mapping_value(
        case, "calendars", "calendar_mapping", "native_calendar_realization"
    )
    constraint_realization = _mapping_value(
        case,
        "constraints",
        "constraint_mapping",
        "native_constraint_realization",
        allow_empty=True,
    )
    progress_realization = _mapping_value(
        case,
        "progress",
        "progress_mapping",
        "native_progress_realization",
        allow_empty=True,
    )
    project_settings = _mapping_value(case, "project_settings", "all_product_settings")
    expected_realizations = {
        "native_activity_and_field_mapping": expected_observed_mapping,
        "native_calendar_realization": calendar_realization,
        "native_relationship_and_lag_realization": relationship_mapping,
        "native_constraint_realization": constraint_realization,
        "native_progress_realization": progress_realization,
        "all_product_settings": project_settings,
    }
    for field, expected in expected_realizations.items():
        if document[field] != expected:
            raise NativeEvidenceError(
                f"manifest {field} does not match the tracked case realization"
            )

    for role, prefix in (
        ("preregistration", "preregistration"),
        ("comparison_profile", "comparison_profile"),
    ):
        binding = _named_binding(pilot_index, role)
        relative_path = _binding_path(binding, label=role)
        bound_path = _safe_repository_file(repository_root, relative_path, label=role)
        declared_hash = _require_sha256(
            binding.get("raw_sha256"), field=f"{role}.raw_sha256"
        )
        if read_regular_file_snapshot(
            bound_path, label=f"tracked {role}"
        ).sha256 != declared_hash:
            raise NativeEvidenceError(f"tracked {role} bytes do not match the pilot binding")
        expected_binding_values = {
            f"{prefix}_id": _binding_id(binding, role),
            f"{prefix}_path": relative_path,
            f"{prefix}_raw_sha256": declared_hash,
        }
        for field, expected in expected_binding_values.items():
            if document[field] != expected:
                raise NativeEvidenceError(f"manifest {field} differs from the tracked binding")

    source_projection = _source_only_projection_binding(case)
    source_projection_relative_path = _binding_path(
        source_projection, label="source-only projection"
    )
    source_projection_path = _safe_repository_file(
        repository_root,
        source_projection_relative_path,
        label="source-only projection",
    )
    source_projection_sha256 = _require_sha256(
        source_projection.get("raw_sha256"),
        field=f"{case_id}.source_only_case_projection.raw_sha256",
    )
    if read_regular_file_snapshot(
        source_projection_path, label="tracked source-only projection"
    ).sha256 != source_projection_sha256:
        raise NativeEvidenceError(
            "tracked source-only projection bytes do not match the pilot binding"
        )
    if (
        document["source_only_projection_path"] != source_projection_relative_path
        or document["source_only_projection_raw_sha256"]
        != source_projection_sha256
    ):
        raise NativeEvidenceError(
            "manifest source-only projection binding differs from the tracked case"
        )
    if document["fixture_raw_sha256"] != _frozen_fixture_raw_sha256(case_id):
        raise NativeEvidenceError(
            "manifest full-fixture digest differs from the frozen suite registry"
        )

    environment_document, environment_snapshot = load_canonical_json_snapshot(
        environment_capture_path, label="environment capture"
    )
    environment = _environment_capture(environment_document)
    if environment_snapshot.sha256 != document["environment_capture_sha256"]:
        raise NativeEvidenceError("environment capture hash differs from the frozen manifest")
    if environment != document["captured_product_environment"]:
        raise NativeEvidenceError(
            "environment capture realization differs from the frozen manifest"
        )


def _declared_track_ids(pilot_index: Mapping[str, Any]) -> set[str]:
    source = pilot_index.get("execution_track_ids", pilot_index.get("execution_tracks"))
    if source is None:
        return set(EXECUTION_TRACK_IDS)
    if not isinstance(source, Sequence) or isinstance(source, (str, bytes, bytearray)):
        raise NativeEvidenceError("pilot execution tracks must be an array")
    result: set[str] = set()
    for item in source:
        track_id = item.get("track_id") if isinstance(item, Mapping) else item
        result.add(_require_nonblank(track_id, field="execution_track_id"))
    return result


def _prepare_new_output_directory(output_dir: Path, *, purpose: str) -> Path:
    absolute = output_dir.absolute()
    for candidate in (absolute, *absolute.parents):
        if candidate.is_symlink():
            raise NativeEvidenceError("output directory path must not contain symbolic links")
    if output_dir.exists() and (output_dir.is_symlink() or not output_dir.is_dir()):
        raise NativeEvidenceError("output directory must be a real directory")
    output_dir.mkdir(parents=True, exist_ok=True)
    if any(output_dir.iterdir()):
        raise NativeEvidenceError(
            "output directory must be empty; frozen evidence is never overwritten or deleted"
        )
    marker = {
        "schema_version": "msproject-native-evidence-owned-directory-v0.1",
        "owner": "deterministic-scheduling-core",
        "purpose": purpose,
        "mutation_policy": "append_or_overwrite_forbidden",
    }
    write_canonical_json(output_dir / OWNER_MARKER, marker)
    return output_dir


def freeze_msproject_native_input(
    *,
    repository_root: Path,
    pilot_index: Mapping[str, Any],
    pilot_id: str,
    case_id: str,
    track_id: str,
    native_file: Path,
    environment_capture_path: Path,
    output_dir: Path,
    prerequisite_manual_case_realization_manifest_path: Path | None = None,
    prepared_at: str,
    prepared_by: str,
    independent_pre_execution_reviewed_by: str,
    attestation_no_native_result_observed_before_freeze: bool,
) -> FrozenNativeInput:
    """Freeze one native input before result observation.

    The raw native file is hashed in place and is never copied into the output
    directory.  The caller supplies the already verified pilot index; this
    function requires it to equal the tracked canonical index and rechecks
    every bound repository file before writing evidence.
    """

    repository_root = repository_root.resolve()
    if not repository_root.is_dir():
        raise NativeEvidenceError("repository_root must be a directory")
    tracked_index_path = _safe_repository_file(
        repository_root,
        PILOT_INDEX_RELATIVE_PATH,
        label="tracked pilot index",
    )
    tracked_index, tracked_index_snapshot = load_canonical_json_snapshot(
        tracked_index_path, label="tracked pilot index"
    )
    if pilot_index != tracked_index:
        raise NativeEvidenceError("supplied pilot index does not equal the tracked frozen kit index")
    pilot_index_raw_sha256 = tracked_index_snapshot.sha256

    if pilot_id != PILOT_ID or pilot_index.get("pilot_id") != pilot_id:
        raise NativeEvidenceError(f"unsupported or mismatched pilot {pilot_id!r}")
    if pilot_index.get("status") != "prepared_not_executed":
        raise NativeEvidenceError("pilot index must remain prepared_not_executed")
    if track_id not in EXECUTION_TRACK_IDS or track_id not in _declared_track_ids(pilot_index):
        raise NativeEvidenceError(f"track {track_id!r} does not belong to the pilot")
    case = _case_entry(pilot_index, case_id)
    _reject_blocked_adapter_preparation(
        pilot_index=pilot_index,
        case=case,
        track_id=track_id,
    )

    activity_mapping = _normalise_activity_mapping(case)
    relationship_mapping = _normalise_relationship_mapping(case, activity_mapping)
    calendar_realization = _mapping_value(
        case, "calendars", "calendar_mapping", "native_calendar_realization"
    )
    constraint_realization = _mapping_value(
        case,
        "constraints",
        "constraint_mapping",
        "native_constraint_realization",
        allow_empty=True,
    )
    progress_realization = _mapping_value(
        case,
        "progress",
        "progress_mapping",
        "native_progress_realization",
        allow_empty=True,
    )
    project_settings = _mapping_value(case, "project_settings", "all_product_settings")
    if not isinstance(constraint_realization, Sequence) or isinstance(
        constraint_realization, (str, bytes, bytearray)
    ):
        raise NativeEvidenceError("constraint realization must be an array")
    if not all(isinstance(item, Mapping) for item in constraint_realization):
        raise NativeEvidenceError("constraint realization entries must be objects")
    coordinate_contract = pilot_index.get("coordinate_contract")
    if not isinstance(coordinate_contract, Mapping):
        raise NativeEvidenceError("pilot index must contain the frozen coordinate contract")
    origin = _require_nonblank(
        coordinate_contract.get("canonical_origin"), field="coordinate_contract.canonical_origin"
    )
    if coordinate_contract.get("utc_offset") != "+08:00":
        raise NativeEvidenceError("pilot coordinate contract must retain utc_offset +08:00")

    prepared_by = _require_nonblank(prepared_by, field="prepared_by")
    reviewed_by = _require_nonblank(
        independent_pre_execution_reviewed_by,
        field="independent_pre_execution_reviewed_by",
    )
    if prepared_by == reviewed_by:
        raise NativeEvidenceError("preparer and independent reviewer identities must differ")
    if attestation_no_native_result_observed_before_freeze is not True:
        raise NativeEvidenceError("the no-native-result-observed attestation must be true")
    if not isinstance(prepared_at, str) or not validate_rfc3339(prepared_at):
        raise NativeEvidenceError("prepared_at must be a timezone-qualified RFC 3339 timestamp")

    native_snapshot = read_regular_file_snapshot(native_file, label="native input")
    native_sha256 = native_snapshot.sha256
    native_size = native_snapshot.byte_size
    if track_id != "adapter_interchange_round_trip":
        if native_file.suffix.lower() != ".mpp" or not native_snapshot.data.startswith(
            b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
        ):
            raise NativeEvidenceError(
                "manual and reopen native inputs must be Microsoft Compound File Binary .mpp files"
            )

    environment_document, environment_snapshot = load_canonical_json_snapshot(
        environment_capture_path, label="environment capture"
    )
    if environment_snapshot.file_identity == native_snapshot.file_identity:
        raise NativeEvidenceError("native input and environment capture must be distinct files")
    environment = _environment_capture(environment_document)
    observed_activity_mapping = _validate_environment(
        environment,
        prepared_by=prepared_by,
        reviewed_by=reviewed_by,
        prepared_at=prepared_at,
        track_id=track_id,
        native_sha256=native_sha256,
        activity_mapping=activity_mapping,
        relationship_mapping=relationship_mapping,
        constraint_realization=constraint_realization,
        coordinate_contract=coordinate_contract,
    )
    environment_sha256 = environment_snapshot.sha256

    prerequisite_manual_manifest_sha256: str | None = None
    prerequisite: Mapping[str, Any] | None = None
    if track_id == "saved_file_reopen_recalculate_stability":
        if prerequisite_manual_case_realization_manifest_path is None:
            raise NativeEvidenceError(
                "reopen/recalculate freeze requires the prerequisite manual case-realization manifest"
            )
        prerequisite, prerequisite_snapshot = load_canonical_json_snapshot(
            prerequisite_manual_case_realization_manifest_path,
            label="prerequisite manual case-realization manifest",
        )
        if prerequisite_snapshot.file_identity in {
            native_snapshot.file_identity,
            environment_snapshot.file_identity,
        }:
            raise NativeEvidenceError(
                "prerequisite manifest must be distinct from native and environment inputs"
            )
        validate_case_realisation_manifest_against_repository(
            repository_root=repository_root,
            document=prerequisite,
            environment_capture_path=environment_capture_path,
        )
        required_prerequisite_values = {
            "schema_version": "msproject-case-realisation-manifest-v0.2",
            "pilot_id": pilot_id,
            "native_system": NATIVE_SYSTEM,
            "state": "frozen_before_native_calculation",
            "case_id": case_id,
            "execution_track_id": "manual_native_semantic_parity",
            "native_source_file_sha256": native_sha256,
            "pilot_index_raw_sha256": pilot_index_raw_sha256,
        }
        for field, expected in required_prerequisite_values.items():
            if prerequisite.get(field) != expected:
                raise NativeEvidenceError(
                    f"prerequisite manual manifest {field} does not match this Track B freeze"
                )
        if prerequisite.get("attestation_no_native_result_observed_before_freeze") is not True:
            raise NativeEvidenceError(
                "prerequisite manual manifest lacks its pre-observation attestation"
            )
        prerequisite_manual_manifest_sha256 = prerequisite_snapshot.sha256
    elif prerequisite_manual_case_realization_manifest_path is not None:
        raise NativeEvidenceError(
            "a prerequisite manual manifest is accepted only for the reopen/recalculate track"
        )

    bound_documents: dict[str, dict[str, Any]] = {}
    for role in ("preregistration", "comparison_profile"):
        binding = _named_binding(pilot_index, role)
        relative_path = _binding_path(binding, label=role)
        bound_path = _safe_repository_file(repository_root, relative_path, label=role)
        declared_hash = _require_sha256(binding.get("raw_sha256"), field=f"{role}.raw_sha256")
        bound_snapshot = read_regular_file_snapshot(bound_path, label=role)
        observed_hash = bound_snapshot.sha256
        if observed_hash != declared_hash:
            raise NativeEvidenceError(
                f"{role} raw hash mismatch: declared {declared_hash}, observed {observed_hash}"
            )
        bound_documents[role] = {
            "id": _binding_id(binding, role),
            "path": relative_path,
            "raw_sha256": declared_hash,
            "resolved_path": bound_snapshot.resolved_path,
            "file_identity": bound_snapshot.file_identity,
        }

    source_projection = _source_only_projection_binding(case)
    source_projection_relative_path = _binding_path(
        source_projection, label="source-only projection"
    )
    source_projection_path = _safe_repository_file(
        repository_root,
        source_projection_relative_path,
        label="source-only projection",
    )
    source_projection_sha256 = _require_sha256(
        source_projection.get("raw_sha256"),
        field=f"{case_id}.source_only_case_projection.raw_sha256",
    )
    source_projection_snapshot = read_regular_file_snapshot(
        source_projection_path, label="source-only projection"
    )
    if source_projection_snapshot.sha256 != source_projection_sha256:
        raise NativeEvidenceError(
            "source-only projection raw hash does not match the pilot index"
        )
    fixture_sha256 = _frozen_fixture_raw_sha256(case_id)
    protected_role_identities = {
        tracked_index_snapshot.file_identity,
        environment_snapshot.file_identity,
        source_projection_snapshot.file_identity,
        *(document["file_identity"] for document in bound_documents.values()),
    }
    if native_snapshot.file_identity in protected_role_identities:
        raise NativeEvidenceError(
            "native input must be file-distinct from protocol, source projection, and environment files"
        )

    product_fields = dict(environment)
    if prerequisite is not None:
        expected_prerequisite_values = {
            "pilot_index_canonical_sha256": sha256_digest(pilot_index),
            "pilot_index_raw_sha256": pilot_index_raw_sha256,
            "pilot_index_path": PILOT_INDEX_RELATIVE_PATH,
            "prerequisite_manual_case_realization_manifest_sha256": None,
            "fixture_raw_sha256": fixture_sha256,
            "source_only_projection_path": source_projection_relative_path,
            "source_only_projection_raw_sha256": source_projection_sha256,
            "preregistration_id": bound_documents["preregistration"]["id"],
            "preregistration_path": bound_documents["preregistration"]["path"],
            "preregistration_raw_sha256": bound_documents["preregistration"]["raw_sha256"],
            "comparison_profile_id": bound_documents["comparison_profile"]["id"],
            "comparison_profile_path": bound_documents["comparison_profile"]["path"],
            "comparison_profile_raw_sha256": bound_documents["comparison_profile"]["raw_sha256"],
            "native_source_file_sha256": native_sha256,
            "native_source_file_byte_size": native_size,
            "native_source_file_format": environment["native_file_format"],
            "environment_capture_sha256": environment_sha256,
            "native_activity_and_field_mapping": observed_activity_mapping,
            "native_calendar_realization": calendar_realization,
            "native_relationship_and_lag_realization": relationship_mapping,
            "native_constraint_realization": constraint_realization,
            "native_progress_realization": progress_realization,
            "all_product_settings": project_settings,
            "captured_product_environment": product_fields,
            "construction_action_log": environment["manual_actions_by_stage"],
            "prepared_by": prepared_by,
            "independent_pre_execution_reviewed_by": reviewed_by,
        }
        for field, expected in expected_prerequisite_values.items():
            if prerequisite[field] != expected:
                raise NativeEvidenceError(
                    f"prerequisite manual manifest {field} does not match the Track B realization"
                )
    manifest = {
        "schema_version": "msproject-case-realisation-manifest-v0.2",
        "pilot_id": pilot_id,
        "pilot_index_canonical_sha256": sha256_digest(pilot_index),
        "pilot_index_raw_sha256": pilot_index_raw_sha256,
        "pilot_index_path": PILOT_INDEX_RELATIVE_PATH,
        "native_system": NATIVE_SYSTEM,
        "state": "frozen_before_native_calculation",
        "case_id": case_id,
        "execution_track_id": track_id,
        "prerequisite_manual_case_realization_manifest_sha256": (
            prerequisite_manual_manifest_sha256
        ),
        "fixture_raw_sha256": fixture_sha256,
        "source_only_projection_path": source_projection_relative_path,
        "source_only_projection_raw_sha256": source_projection_sha256,
        "preregistration_id": bound_documents["preregistration"]["id"],
        "preregistration_path": bound_documents["preregistration"]["path"],
        "preregistration_raw_sha256": bound_documents["preregistration"]["raw_sha256"],
        "comparison_profile_id": bound_documents["comparison_profile"]["id"],
        "comparison_profile_path": bound_documents["comparison_profile"]["path"],
        "comparison_profile_raw_sha256": bound_documents["comparison_profile"]["raw_sha256"],
        "native_source_file_sha256": native_sha256,
        "native_source_file_byte_size": native_size,
        "native_source_file_format": environment["native_file_format"],
        "raw_native_file_embedded": False,
        "environment_capture_sha256": environment_sha256,
        "coordinate_contract": {
            "canonical_origin": origin,
            "canonical_unit": coordinate_contract.get("canonical_unit"),
            "schedule_time_zone": coordinate_contract.get("schedule_time_zone"),
            "utc_offset": coordinate_contract.get("utc_offset"),
            "timestamp_tolerance_seconds": coordinate_contract.get("timestamp_tolerance_seconds"),
            "rounding_policy": coordinate_contract.get("rounding_policy"),
        },
        "native_activity_and_field_mapping": observed_activity_mapping,
        "native_calendar_realization": calendar_realization,
        "native_relationship_and_lag_realization": relationship_mapping,
        "native_constraint_realization": constraint_realization,
        "native_progress_realization": progress_realization,
        "all_product_settings": project_settings,
        "captured_product_environment": product_fields,
        "construction_action_log": environment["manual_actions_by_stage"],
        "prepared_at": prepared_at,
        "prepared_by": prepared_by,
        "independent_pre_execution_reviewed_by": reviewed_by,
        "attestation_no_native_result_observed_before_freeze": True,
        "claim_boundary": {
            "native_result_exists": False,
            "compatibility_claim_exists": False,
            "full_45_case_gate_satisfied": False,
        },
    }

    if output_dir.resolve() == repository_root:
        raise NativeEvidenceError("output directory must not be the repository root")
    validate_case_realisation_manifest_against_repository(
        repository_root=repository_root,
        document=manifest,
        environment_capture_path=environment_capture_path,
    )
    output_dir = _prepare_new_output_directory(
        output_dir, purpose="microsoft-project-pre-execution-freeze"
    )
    manifest_path = output_dir / CASE_REALISATION_FILENAME
    write_canonical_json(manifest_path, manifest)
    return FrozenNativeInput(
        manifest=manifest,
        manifest_path=manifest_path,
        manifest_sha256=raw_file_sha256(manifest_path),
    )


__all__ = [
    "ALL_REQUIRED_ENVIRONMENT_FIELDS",
    "CASE_REALISATION_FILENAME",
    "CASE_REALISATION_REQUIRED_KEYS",
    "EXECUTION_TRACK_IDS",
    "FrozenNativeInput",
    "NativeEvidenceError",
    "RegularFileSnapshot",
    "OBSERVED_PRODUCT_SETTING_IDS",
    "OWNER_MARKER",
    "PILOT_ID",
    "PILOT_INDEX_RELATIVE_PATH",
    "PILOT_REQUIRED_ENVIRONMENT_FIELDS",
    "PRE_EXECUTION_ACTION_IDS",
    "INDEPENDENT_VERIFICATION_EVIDENCE_ROLES",
    "RELATIONSHIP_TYPE_TO_MSPDI",
    "PROFILE_REQUIRED_ENVIRONMENT_FIELDS",
    "REQUIRED_ENVIRONMENT_FIELDS",
    "freeze_msproject_native_input",
    "load_canonical_json",
    "load_canonical_json_snapshot",
    "parse_canonical_json_snapshot",
    "raw_file_sha256",
    "read_regular_file_snapshot",
    "validate_case_realisation_manifest",
    "validate_case_realisation_manifest_against_repository",
]
