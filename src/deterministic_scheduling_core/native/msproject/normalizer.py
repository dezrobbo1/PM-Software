from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

from jsonschema import Draft202012Validator, FormatChecker
from rfc3339_validator import validate_rfc3339

from deterministic_scheduling_core.provenance.canonical_json import (
    canonical_text,
    write_canonical_json,
)

from .freeze import (
    NATIVE_SYSTEM,
    NativeEvidenceError,
    RegularFileSnapshot,
    _prepare_new_output_directory,
    _require_regular_file,
    load_canonical_json,
    load_canonical_json_snapshot,
    parse_canonical_json_snapshot,
    raw_file_sha256,
    read_regular_file_snapshot,
    validate_case_realisation_manifest_against_repository,
)


# The pilot's reviewed serialization target is the Project 2010 MSPDI schema
# (SaveVersion 14).  Unversioned and Project 2007 documents are deliberately
# rejected instead of being treated as equivalent dialects.
MSPDI_NAMESPACE = "http://schemas.microsoft.com/project/2010"
MSPDI_SAVE_VERSION = 14
XSI_NAMESPACE = "http://www.w3.org/2001/XMLSchema-instance"
COORDINATE_TRANSFORMATION_ID = "microsoft-project-coordinate-normalisation-v0.1"
ENUM_TRANSFORMATION_ID = "microsoft-project-enumeration-normalisation-v0.1"
MAX_MSPDI_BYTES = 8 * 1024 * 1024
MAX_MSPDI_ELEMENTS = 20_000
MAX_MSPDI_DEPTH = 64
MAX_MSPDI_TEXT_BYTES = 4 * 1024 * 1024
COMPOUND_FILE_BINARY_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
SUPPLIED_STAGE_ARTIFACT_KEYS_BY_TRACK = {
    "manual_native_semantic_parity": frozenset({"native_calculated_file_sha256"}),
    "saved_file_reopen_recalculate_stability": frozenset(
        {
            "native_pre_close_file_sha256",
            "native_pre_close_output_sha256",
            "native_reopened_file_sha256",
            "native_recalculated_file_sha256",
            "native_post_recalculate_output_sha256",
        }
    ),
    "adapter_interchange_round_trip": frozenset(
        {
            "native_pre_export_file_sha256",
            "mspdi_xml_export_sha256",
            "canonical_reimport_sha256",
            "controlled_reexport_sha256",
            "native_reopened_recalculated_file_sha256",
        }
    ),
}
REQUIRED_STAGE_HASH_KEYS_BY_TRACK = {
    "manual_native_semantic_parity": frozenset(
        {
            "case_realization_manifest_sha256",
            "native_source_file_sha256",
            "native_calculated_file_sha256",
            "normalized_native_output_sha256",
        }
    ),
    "saved_file_reopen_recalculate_stability": frozenset(
        {
            "native_pre_close_file_sha256",
            "native_pre_close_output_sha256",
            "native_reopened_file_sha256",
            "native_recalculated_file_sha256",
            "native_post_recalculate_output_sha256",
        }
    ),
    "adapter_interchange_round_trip": frozenset(
        {
            "native_pre_export_file_sha256",
            "mspdi_xml_export_sha256",
            "canonical_reimport_sha256",
            "controlled_reexport_sha256",
            "native_reopened_recalculated_file_sha256",
            "final_normalized_native_output_sha256",
        }
    ),
}
POST_EXECUTION_ACTION_IDS_BY_TRACK = {
    "manual_native_semantic_parity": (
        "calculate_project", "save_calculated_native_file",
        "export_post_calculation_mspdi", "finalize_stage_and_independent_evidence",
    ),
    "saved_file_reopen_recalculate_stability": (
        "capture_pre_close_file_and_output", "save_and_close_project",
        "reopen_saved_project", "capture_reopened_file_before_recalculation",
        "recalculate_project", "capture_recalculated_file_and_post_output",
        "finalize_stage_and_independent_evidence",
    ),
    "adapter_interchange_round_trip": (
        "open_frozen_mspdi_input", "calculate_project",
        "save_native_pre_export_file", "export_mspdi_xml", "canonical_reimport",
        "controlled_reexport", "reopen_and_recalculate_native_file",
        "finalize_stage_and_independent_evidence",
    ),
}


class NativeOutputError(NativeEvidenceError):
    """A native XML output cannot be normalized under the frozen mapping."""

    def __init__(self, message: str, *, outcome: str = "executed_fail"):
        if outcome not in {"executed_fail", "executed_inconclusive"}:
            raise ValueError(f"invalid native-output failure outcome {outcome!r}")
        self.outcome = outcome
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class NativeAnalysis:
    normalized_output: dict[str, Any]
    difference_manifest: dict[str, Any]
    native_run_record: dict[str, Any]
    evidence_bundle: dict[str, Any]
    redacted_evidence_manifest_draft: dict[str, Any]
    output_dir: Path


def _q(local_name: str) -> str:
    return f"{{{MSPDI_NAMESPACE}}}{local_name}"


def _parse_bounded_mspdi(snapshot: RegularFileSnapshot) -> ET.Element:
    """Parse one immutable MSPDI snapshot within the pilot's resource envelope."""

    if snapshot.byte_size > MAX_MSPDI_BYTES:
        raise NativeOutputError(
            f"native output exceeds the {MAX_MSPDI_BYTES}-byte MSPDI limit",
            outcome="executed_inconclusive",
        )
    try:
        text = snapshot.data.decode("utf-8")
    except UnicodeError as exc:
        raise NativeOutputError(f"native output is not readable UTF-8 XML: {exc}") from exc
    if re.search(r"<!DOCTYPE|<!ENTITY", text, flags=re.IGNORECASE):
        raise NativeOutputError("DTD and entity declarations are forbidden in native XML evidence")
    parser = ET.XMLPullParser(events=("start", "end"))
    depth = 0
    element_count = 0
    text_bytes = 0
    root: ET.Element | None = None
    try:
        for offset in range(0, len(snapshot.data), 64 * 1024):
            parser.feed(snapshot.data[offset : offset + 64 * 1024])
            for event, element in parser.read_events():
                if event == "start":
                    depth += 1
                    element_count += 1
                    if root is None:
                        root = element
                    if depth > MAX_MSPDI_DEPTH:
                        raise NativeOutputError(
                            f"native XML exceeds the {MAX_MSPDI_DEPTH}-level depth limit",
                            outcome="executed_inconclusive",
                        )
                    if element_count > MAX_MSPDI_ELEMENTS:
                        raise NativeOutputError(
                            f"native XML exceeds the {MAX_MSPDI_ELEMENTS}-element limit",
                            outcome="executed_inconclusive",
                        )
                else:
                    for value in (element.text, element.tail):
                        if value:
                            text_bytes += len(value.encode("utf-8"))
                    if text_bytes > MAX_MSPDI_TEXT_BYTES:
                        raise NativeOutputError(
                            f"native XML exceeds the {MAX_MSPDI_TEXT_BYTES}-byte text limit",
                            outcome="executed_inconclusive",
                        )
                    depth -= 1
        parser.close()
    except ET.ParseError as exc:
        raise NativeOutputError(
            f"native output is not well-formed XML: {exc}",
            outcome="executed_inconclusive",
        ) from exc
    if root is None or depth != 0:
        raise NativeOutputError(
            "native output has no complete XML document",
            outcome="executed_inconclusive",
        )
    return root


def _canonical_json_file_sha256(document: Mapping[str, Any]) -> str:
    return hashlib.sha256((canonical_text(document) + "\n").encode("utf-8")).hexdigest()


def _element_state(parent: ET.Element, local_name: str) -> dict[str, Any]:
    children = parent.findall(_q(local_name))
    if len(children) > 1:
        raise NativeOutputError(f"duplicate {local_name} element")
    if not children:
        return {"presence": "missing"}
    child = children[0]
    nil = child.get(f"{{{XSI_NAMESPACE}}}nil")
    if nil in {"true", "1"}:
        if child.text not in (None, ""):
            raise NativeOutputError(f"nil {local_name} element must not contain text")
        return {"presence": "present", "value": None}
    if nil not in (None, "false", "0"):
        raise NativeOutputError(f"invalid xsi:nil value on {local_name}")
    raw = child.text if child.text is not None else ""
    if raw == "":
        return {"presence": "present", "value_kind": "blank", "raw": ""}
    return {"presence": "present", "raw": raw}


def _required_text(parent: ET.Element, local_name: str) -> str:
    state = _element_state(parent, local_name)
    if state.get("presence") != "present" or "raw" not in state or state["raw"].strip() == "":
        raise NativeOutputError(f"{local_name} must be present and nonblank")
    return state["raw"]


def _required_integer(parent: ET.Element, local_name: str) -> tuple[int, dict[str, Any]]:
    raw = _required_text(parent, local_name)
    if re.fullmatch(r"-?(0|[1-9][0-9]*)", raw) is None:
        raise NativeOutputError(f"{local_name} must be an exact base-10 integer")
    value = int(raw)
    return value, {"presence": "present", "raw": raw, "value": value}


def _required_boolean(parent: ET.Element, local_name: str) -> tuple[bool, dict[str, Any]]:
    raw = _required_text(parent, local_name)
    if raw not in {"0", "1", "false", "true"}:
        raise NativeOutputError(f"{local_name} must be an XML boolean")
    value = raw in {"1", "true"}
    return value, {"presence": "present", "raw": raw, "value": value}


def _required_configuration_integer(
    parent: ET.Element, local_name: str
) -> tuple[int, dict[str, Any]]:
    try:
        return _required_integer(parent, local_name)
    except NativeOutputError as exc:
        raise NativeOutputError(str(exc), outcome="executed_inconclusive") from exc


def _required_configuration_boolean(
    parent: ET.Element, local_name: str
) -> tuple[bool, dict[str, Any]]:
    try:
        return _required_boolean(parent, local_name)
    except NativeOutputError as exc:
        raise NativeOutputError(str(exc), outcome="executed_inconclusive") from exc


def _required_configuration_text(parent: ET.Element, local_name: str) -> str:
    try:
        return _required_text(parent, local_name)
    except NativeOutputError as exc:
        raise NativeOutputError(str(exc), outcome="executed_inconclusive") from exc


def _parse_origin(manifest: Mapping[str, Any]) -> datetime:
    contract = manifest.get("coordinate_contract")
    if not isinstance(contract, Mapping):
        raise NativeOutputError("case-realisation manifest has no coordinate contract")
    raw = contract.get("canonical_origin")
    if not isinstance(raw, str):
        raise NativeOutputError("canonical origin must be a string")
    try:
        origin = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise NativeOutputError("canonical origin is not an ISO date-time") from exc
    if origin.tzinfo is None or origin.utcoffset() != timedelta(hours=8):
        raise NativeOutputError("canonical origin must carry the frozen +08:00 offset")
    if contract.get("utc_offset") != "+08:00":
        raise NativeOutputError("case-realisation manifest does not retain utc_offset +08:00")
    if contract.get("timestamp_tolerance_seconds") != 0:
        raise NativeOutputError("timestamp tolerance must remain zero")
    if contract.get("rounding_policy") != "forbidden":
        raise NativeOutputError("rounding must remain forbidden")
    return origin


def _timestamp_coordinate(raw: str, origin: datetime, *, field: str) -> int:
    if "T" not in raw:
        raise NativeOutputError(f"{field} must be an ISO local date-time")
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise NativeOutputError(f"{field} is not an ISO date-time") from exc
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone(timedelta(hours=8)))
    elif value.utcoffset() != timedelta(hours=8):
        raise NativeOutputError(f"{field} must be local +08:00 evidence")
    delta = value - origin
    if delta.microseconds != 0:
        raise NativeOutputError(f"{field} is off the exact integer-hour grid")
    seconds = delta.days * 86400 + delta.seconds
    if seconds % 3600 != 0:
        raise NativeOutputError(f"{field} is off the exact integer-hour grid")
    return seconds // 3600


def _coordinate_state(parent: ET.Element, local_name: str, origin: datetime) -> dict[str, Any]:
    state = _element_state(parent, local_name)
    if state.get("presence") == "missing" or (
        "value" in state and state["value"] is None
    ):
        return state
    if state.get("value_kind") == "blank":
        return state
    coordinate = _timestamp_coordinate(state["raw"], origin, field=local_name)
    return {
        "presence": "present",
        "raw": state["raw"],
        "value": coordinate,
        "transformation_id": COORDINATE_TRANSFORMATION_ID,
    }


def _manifest_activity_mapping(
    manifest: Mapping[str, Any],
) -> tuple[dict[int, str], dict[int, int], dict[int, Mapping[str, Any]]]:
    source = manifest.get("native_activity_and_field_mapping")
    if not isinstance(source, list) or not source:
        raise NativeOutputError("case-realisation manifest has no activity mapping")
    activity_by_uid: dict[int, str] = {}
    id_by_uid: dict[int, int] = {}
    record_by_uid: dict[int, Mapping[str, Any]] = {}
    activity_ids: set[str] = set()
    task_ids: set[int] = set()
    for item in source:
        if not isinstance(item, Mapping):
            raise NativeOutputError("case-realisation activity mapping entries must be objects")
        activity_id = item.get("activity_id")
        uid = item.get("native_task_uid")
        task_id = item.get("native_task_id")
        task_name = item.get("native_task_name")
        duration_hours = item.get("canonical_duration_hours")
        calendar_id = item.get("canonical_calendar_id")
        if not isinstance(activity_id, str) or not activity_id:
            raise NativeOutputError("mapped activity ID must be nonblank")
        if isinstance(uid, bool) or not isinstance(uid, int) or uid < 0:
            raise NativeOutputError(f"mapped UID for {activity_id} is invalid")
        if isinstance(task_id, bool) or not isinstance(task_id, int) or task_id < 0:
            raise NativeOutputError(f"mapped task ID for {activity_id} is invalid")
        if not isinstance(task_name, str) or not task_name:
            raise NativeOutputError(f"mapped task name for {activity_id} is invalid")
        if (
            isinstance(duration_hours, bool)
            or not isinstance(duration_hours, int)
            or duration_hours < 0
        ):
            raise NativeOutputError(f"mapped duration for {activity_id} is invalid")
        if not isinstance(calendar_id, str) or not calendar_id:
            raise NativeOutputError(f"mapped calendar for {activity_id} is invalid")
        if uid == 0 or task_id == 0:
            raise NativeOutputError(
                "mapped activity UID and ID 0 are reserved for the Project summary task"
            )
        if uid in activity_by_uid or activity_id in activity_ids or task_id in task_ids:
            raise NativeOutputError("case-realisation activity mappings must be unique")
        activity_by_uid[uid] = activity_id
        id_by_uid[uid] = task_id
        record_by_uid[uid] = item
        activity_ids.add(activity_id)
        task_ids.add(task_id)
    return activity_by_uid, id_by_uid, record_by_uid


def _duration_hours(parent: ET.Element) -> tuple[int, dict[str, Any]]:
    raw = _required_text(parent, "Duration")
    match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", raw)
    if match is None or all(part is None for part in match.groups()):
        raise NativeOutputError("Duration must be an exact nonnegative MSPDI duration")
    hours, minutes, seconds = (int(part or "0") for part in match.groups())
    total_seconds = hours * 3600 + minutes * 60 + seconds
    if total_seconds % 3600 != 0:
        raise NativeOutputError("Duration is off the exact integer-hour grid")
    value = total_seconds // 3600
    return value, {"presence": "present", "raw": raw, "value": value}


def _manifest_constraints(
    manifest: Mapping[str, Any], activity_by_uid: Mapping[int, str]
) -> dict[int, Mapping[str, Any]]:
    source = manifest.get("native_constraint_realization")
    if not isinstance(source, list):
        raise NativeOutputError("case-realisation manifest has no constraint realization")
    result: dict[int, Mapping[str, Any]] = {}
    for item in source:
        if not isinstance(item, Mapping):
            raise NativeOutputError("constraint realization entries must be objects")
        uid = item.get("native_task_uid")
        if uid not in activity_by_uid:
            raise NativeOutputError("constraint realization contains an unresolved task UID")
        if uid in result:
            raise NativeOutputError("multiple native constraints for one pilot task are unsupported")
        if item.get("native_constraint_type") != 4:
            raise NativeOutputError("pilot constraint realization must retain SNET Type 4")
        coordinate = item.get("canonical_coordinate")
        if isinstance(coordinate, bool) or not isinstance(coordinate, int):
            raise NativeOutputError("constraint canonical coordinate must be an integer hour")
        result[uid] = item
    return result


def _manifest_calendar_uids(
    root: ET.Element,
    manifest: Mapping[str, Any],
    activity_records: Mapping[int, Mapping[str, Any]],
) -> tuple[dict[str, int], dict[str, Any]]:
    source = manifest.get("native_calendar_realization")
    if not isinstance(source, list) or not source:
        raise NativeOutputError("case-realisation manifest has no calendar realization")
    expected_names: dict[str, str] = {}
    for item in source:
        if not isinstance(item, Mapping):
            raise NativeOutputError("calendar realization entries must be objects")
        calendar_id = item.get("canonical_calendar_id")
        native_name = item.get("manual_native_calendar_name")
        if not isinstance(calendar_id, str) or not calendar_id:
            raise NativeOutputError("calendar realization has an invalid canonical ID")
        if not isinstance(native_name, str) or not native_name:
            raise NativeOutputError("calendar realization has no reviewed native calendar name")
        if calendar_id in expected_names:
            raise NativeOutputError("calendar realization contains duplicate canonical IDs")
        expected_names[calendar_id] = native_name
    used_ids = {record["canonical_calendar_id"] for record in activity_records.values()}
    if not used_ids.issubset(expected_names):
        raise NativeOutputError("activity mapping contains an unresolved calendar ID")
    calendars_parent = root.find(_q("Calendars"))
    if calendars_parent is None:
        raise NativeOutputError("native output is missing Calendars")
    uids_by_name: dict[str, list[int]] = {}
    calendar_elements_by_uid: dict[int, ET.Element] = {}
    for calendar in calendars_parent.findall(_q("Calendar")):
        uid, _ = _required_configuration_integer(calendar, "UID")
        name = _required_configuration_text(calendar, "Name")
        if uid in calendar_elements_by_uid:
            raise NativeOutputError("native output contains duplicate calendar UIDs")
        calendar_elements_by_uid[uid] = calendar
        uids_by_name.setdefault(name, []).append(uid)
    resolved: dict[str, int] = {}
    for calendar_id, native_name in expected_names.items():
        matches = uids_by_name.get(native_name, [])
        if len(matches) != 1:
            raise NativeOutputError(
                f"native calendar {native_name!r} must resolve to exactly one UID"
            )
        resolved[calendar_id] = matches[0]
    project_calendar_uid, _ = _required_configuration_integer(root, "CalendarUID")
    expected_project_uid = resolved.get("CAL-24X7")
    if expected_project_uid is None or project_calendar_uid != expected_project_uid:
        raise NativeOutputError("project CalendarUID does not resolve to frozen CAL-24X7")
    calendar_element = calendar_elements_by_uid[expected_project_uid]
    return resolved, {
        "presence": "present",
        "value": _xml_structural_evidence(calendar_element),
        "interpretation_status": "retained_unclaimed",
        "working_time_serialization_interpreted": False,
        "working_time_serialization_note": (
            "The official MSPDI XSD defines WeekDays/WorkingTimes structure but does not "
            "establish that equal midnight endpoints encode a continuous 24-hour day. "
            "The raw structure is retained for independent review and is not used to claim "
            "CAL-24X7 equivalence."
        ),
    }


def _xml_structural_evidence(element: ET.Element) -> dict[str, Any]:
    """Return deterministic unclaimed evidence for one MSPDI subtree."""

    local_name = element.tag.rsplit("}", 1)[-1]
    attributes = {
        key.rsplit("}", 1)[-1]: value for key, value in sorted(element.attrib.items())
    }
    text = element.text.strip() if element.text and element.text.strip() else None
    return {
        "element": local_name,
        "attributes": attributes,
        "text": text,
        "children": [_xml_structural_evidence(child) for child in list(element)],
    }


def _manifest_relationship_mapping(
    manifest: Mapping[str, Any], activity_by_uid: Mapping[int, str]
) -> dict[tuple[int, int], Mapping[str, Any]]:
    source = manifest.get("native_relationship_and_lag_realization")
    if not isinstance(source, list):
        raise NativeOutputError("case-realisation manifest has no relationship mapping")
    expected: dict[tuple[int, int], Mapping[str, Any]] = {}
    for item in source:
        if not isinstance(item, Mapping):
            raise NativeOutputError("relationship mapping entries must be objects")
        predecessor_uid = item.get("native_predecessor_uid")
        successor_uid = item.get("native_successor_uid")
        native_type = item.get("native_type")
        native_lag = item.get("native_link_lag_tenths_minutes")
        native_lag_format = item.get("native_lag_format")
        if predecessor_uid not in activity_by_uid or successor_uid not in activity_by_uid:
            raise NativeOutputError("relationship mapping contains an unresolved task UID")
        if isinstance(native_type, bool) or native_type not in {0, 1, 2, 3}:
            raise NativeOutputError("relationship mapping has an unknown native Type")
        if isinstance(native_lag, bool) or not isinstance(native_lag, int):
            raise NativeOutputError("relationship mapping native LinkLag must be an integer")
        if native_lag_format != 5:
            raise NativeOutputError("relationship mapping native LagFormat must be 5 (hours)")
        key = (predecessor_uid, successor_uid)
        if key in expected:
            raise NativeOutputError("relationship mapping contains duplicate task pairs")
        expected[key] = item
    return expected


def _validate_manifest_for_normalization(manifest: Mapping[str, Any]) -> None:
    if manifest.get("schema_version") != "msproject-case-realisation-manifest-v0.1":
        raise NativeOutputError("unsupported case-realisation manifest version")
    if manifest.get("native_system") != NATIVE_SYSTEM:
        raise NativeOutputError("case-realisation manifest is not for Microsoft Project")
    if manifest.get("state") != "frozen_before_native_calculation":
        raise NativeOutputError("case-realisation manifest was not frozen before calculation")
    if manifest.get("attestation_no_native_result_observed_before_freeze") is not True:
        raise NativeOutputError("case-realisation manifest lacks the pre-observation attestation")


def _validate_frozen_settings(
    manifest: Mapping[str, Any],
    activity_records: Mapping[int, Mapping[str, Any]],
    relationships: Mapping[tuple[int, int], Mapping[str, Any]],
    constraints: Mapping[int, Mapping[str, Any]],
) -> Mapping[str, Any]:
    settings = manifest.get("all_product_settings")
    if not isinstance(settings, Mapping):
        raise NativeOutputError("case-realisation manifest has no product settings")
    required_settings = {
        "new_tasks_are_manual": False,
        "task_pinned": 0,
        "mspdi_task_type": 1,
        "mspdi_effort_driven": 0,
        "resource_leveling": "disabled_and_not_run",
    }
    for field, expected in required_settings.items():
        if settings.get(field) != expected:
            raise NativeOutputError(
                f"frozen product setting {field} is not {expected!r}",
                outcome="executed_inconclusive",
            )

    environment = manifest.get("captured_product_environment")
    if not isinstance(environment, Mapping):
        raise NativeOutputError("case-realisation manifest has no captured product environment")
    for field in (
        "product_name",
        "edition",
        "version",
        "build",
        "execution_operator_id",
        "independent_reviewer_id",
    ):
        value = environment.get(field)
        if not isinstance(value, str) or not value.strip():
            raise NativeOutputError(
                f"captured product environment {field} must be nonblank",
                outcome="executed_inconclusive",
            )
    if environment["product_name"] != "Microsoft Project":
        raise NativeOutputError(
            "captured product is not Microsoft Project",
            outcome="executed_inconclusive",
        )
    if environment.get("project_start") != manifest["coordinate_contract"]["canonical_origin"]:
        raise NativeOutputError(
            "captured project_start differs from the frozen origin",
            outcome="executed_inconclusive",
        )
    if environment.get("status_date") is not None:
        raise NativeOutputError(
            "relationship pilot status_date must remain null",
            outcome="executed_inconclusive",
        )
    if environment.get("schedule_from_start") is not True:
        raise NativeOutputError(
            "captured schedule_from_start must be true",
            outcome="executed_inconclusive",
        )
    if environment.get("calculation_mode") != "manual":
        raise NativeOutputError(
            "captured calculation_mode is not Microsoft Project manual mode",
            outcome="executed_inconclusive",
        )
    if environment.get("precalculation_protocol_state") != "constructed_not_calculated":
        raise NativeOutputError(
            "captured precalculation protocol state is not constructed_not_calculated",
            outcome="executed_inconclusive",
        )
    if environment.get("resource_leveling_status") != "disabled_and_not_run":
        raise NativeOutputError(
            "captured resource leveling was not disabled and not run",
            outcome="executed_inconclusive",
        )
    project_calendar = environment.get("project_calendar_settings")
    if project_calendar != {
        "canonical_calendar_id": "CAL-24X7",
        "native_calendar_name": "24 Hours",
        "continuous_working_time_verified": True,
    }:
        raise NativeOutputError(
            "captured project calendar settings do not verify CAL-24X7 as 24 Hours",
            outcome="executed_inconclusive",
        )

    activity_ids = {record["activity_id"] for record in activity_records.values()}
    expected_task_maps = {
        "task_calendar_per_task": {activity_id: "24 Hours" for activity_id in activity_ids},
        "task_scheduling_mode_per_task": {
            activity_id: "automatically_scheduled" for activity_id in activity_ids
        },
        "task_type_per_task": {activity_id: "fixed_duration" for activity_id in activity_ids},
        "effort_driven_per_task": {activity_id: False for activity_id in activity_ids},
    }
    for field, expected in expected_task_maps.items():
        if environment.get(field) != expected:
            raise NativeOutputError(
                f"captured {field} does not exactly cover the mapped activities",
                outcome="executed_inconclusive",
            )

    expected_relationship_settings = {
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
        for item in relationships.values()
    }
    if environment.get("relationship_and_lag_settings") != expected_relationship_settings:
        raise NativeOutputError(
            "captured relationship and lag settings differ from the frozen realization",
            outcome="executed_inconclusive",
        )
    expected_constraint_settings = {
        item["constraint_id"]: {
            "activity_id": item["activity_id"],
            "canonical_type": item["canonical_type"],
            "canonical_coordinate": item["canonical_coordinate"],
            "canonical_timestamp": item["canonical_timestamp"],
            "native_constraint_type": item["native_constraint_type"],
        }
        for item in constraints.values()
    }
    if environment.get("constraint_settings") != expected_constraint_settings:
        raise NativeOutputError(
            "captured constraint settings differ from the frozen realization",
            outcome="executed_inconclusive",
        )
    return environment


def _additional_field_states(task: ET.Element) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for field in (
        "Name",
        "Duration",
        "Type",
        "EffortDriven",
        "Manual",
        "Pinned",
        "CalendarUID",
        "ConstraintType",
        "ConstraintDate",
        "Resume",
    ):
        result[field] = _element_state(task, field)
    return result


def normalize_mspdi_output(
    *,
    native_output_path: Path,
    case_realisation_manifest: Mapping[str, Any],
    native_output_snapshot: RegularFileSnapshot | None = None,
) -> dict[str, Any]:
    """Normalize native MSPDI evidence without accepting an expected oracle.

    Expected dates are intentionally absent from this API.  Source-semantic
    mappings come only from the manifest frozen before native calculation.
    """

    _validate_manifest_for_normalization(case_realisation_manifest)
    if native_output_snapshot is None:
        try:
            snapshot = read_regular_file_snapshot(
                native_output_path,
                label="native output",
                max_bytes=MAX_MSPDI_BYTES,
            )
        except NativeEvidenceError as exc:
            raise NativeOutputError(
                str(exc), outcome="executed_inconclusive"
            ) from exc
    else:
        snapshot = native_output_snapshot
    if snapshot.resolved_path != native_output_path.absolute():
        raise NativeOutputError("native output snapshot does not belong to the supplied path")
    root = _parse_bounded_mspdi(snapshot)
    if root.tag != _q("Project"):
        raise NativeOutputError(
            f"native output must use only the reviewed MSPDI 2010 namespace {MSPDI_NAMESPACE}",
            outcome="executed_inconclusive",
        )
    save_version, save_version_state = _required_configuration_integer(root, "SaveVersion")
    if save_version != MSPDI_SAVE_VERSION:
        raise NativeOutputError(
            "native output SaveVersion must be 14 for the MSPDI 2010 pilot",
            outcome="executed_inconclusive",
        )
    new_tasks_manual, new_tasks_manual_state = _required_configuration_boolean(
        root, "NewTasksAreManual"
    )
    if new_tasks_manual:
        raise NativeOutputError(
            "native output changed project automatic-task mode",
            outcome="executed_inconclusive",
        )
    schedule_from_start, schedule_from_start_state = _required_configuration_boolean(
        root, "ScheduleFromStart"
    )
    if not schedule_from_start:
        raise NativeOutputError(
            "native output changed the project to schedule from finish",
            outcome="executed_inconclusive",
        )

    origin = _parse_origin(case_realisation_manifest)
    activity_by_uid, task_id_by_uid, activity_records = _manifest_activity_mapping(
        case_realisation_manifest
    )
    expected_relationships = _manifest_relationship_mapping(
        case_realisation_manifest, activity_by_uid
    )
    expected_constraints = _manifest_constraints(
        case_realisation_manifest, activity_by_uid
    )
    _validate_frozen_settings(
        case_realisation_manifest,
        activity_records,
        expected_relationships,
        expected_constraints,
    )
    calendar_uid_by_id, calendar_structure = _manifest_calendar_uids(
        root, case_realisation_manifest, activity_records
    )
    project_start = _coordinate_state(root, "StartDate", origin)
    if project_start.get("value") != 0:
        raise NativeOutputError("native project StartDate differs from the frozen project start")
    tasks_parent = root.find(_q("Tasks"))
    if tasks_parent is None:
        raise NativeOutputError("native output is missing Tasks")
    task_elements = tasks_parent.findall(_q("Task"))
    observed_tasks: dict[int, ET.Element] = {}
    observed_task_ids: set[int] = set()
    project_summary_task: ET.Element | None = None
    for task in task_elements:
        uid, _ = _required_integer(task, "UID")
        task_id, _ = _required_integer(task, "ID")
        if uid == 0 or task_id == 0:
            if uid != 0 or task_id != 0:
                raise NativeOutputError(
                    "Project summary task must use both UID 0 and ID 0"
                )
            if project_summary_task is not None:
                raise NativeOutputError("native output contains duplicate Project summary tasks")
            is_summary, _ = _required_configuration_boolean(task, "Summary")
            if not is_summary:
                raise NativeOutputError(
                    "Project summary task UID 0/ID 0 must declare Summary true"
                )
            if task.findall(_q("PredecessorLink")):
                raise NativeOutputError("Project summary task must not contain predecessor links")
            project_summary_task = task
            continue
        if uid in observed_tasks:
            raise NativeOutputError(f"duplicate native task UID {uid}")
        if task_id in observed_task_ids:
            raise NativeOutputError(f"duplicate native task ID {task_id}")
        if uid not in activity_by_uid:
            raise NativeOutputError(f"unknown native task UID {uid}")
        if task_id != task_id_by_uid[uid]:
            raise NativeOutputError(
                f"native task UID {uid} changed mapped task ID from {task_id_by_uid[uid]} to {task_id}"
            )
        observed_tasks[uid] = task
        observed_task_ids.add(task_id)
    missing_uids = sorted(set(activity_by_uid) - set(observed_tasks))
    if missing_uids:
        raise NativeOutputError(f"native output is missing mapped task UIDs {missing_uids}")

    activity_times: dict[str, Any] = {}
    additional_task_fields: dict[str, Any] = {}
    raw_relationship_evidence: list[dict[str, Any]] = []
    observed_relationships: set[tuple[int, int]] = set()
    for uid in sorted(observed_tasks, key=lambda item: activity_by_uid[item]):
        task = observed_tasks[uid]
        activity_id = activity_by_uid[uid]
        expected_activity = activity_records[uid]
        summary_state = _element_state(task, "Summary")
        if summary_state.get("presence") == "present":
            is_summary, _ = _required_configuration_boolean(task, "Summary")
            if is_summary:
                raise NativeOutputError(
                    f"mapped task {activity_id} unexpectedly became a summary task"
                )
        if _required_text(task, "Name") != expected_activity["native_task_name"]:
            raise NativeOutputError(f"task {activity_id} changed its frozen native name")
        duration_hours, _ = _duration_hours(task)
        if duration_hours != expected_activity["canonical_duration_hours"]:
            raise NativeOutputError(f"task {activity_id} changed its frozen duration")
        task_calendar_uid, _ = _required_configuration_integer(task, "CalendarUID")
        expected_calendar_uid = calendar_uid_by_id[expected_activity["canonical_calendar_id"]]
        if task_calendar_uid != expected_calendar_uid:
            raise NativeOutputError(f"task {activity_id} changed its frozen calendar")
        task_type, _ = _required_configuration_integer(task, "Type")
        if task_type != 1:
            raise NativeOutputError(
                f"task {activity_id} is not fixed-duration (Type 1)",
                outcome="executed_inconclusive",
            )
        effort_driven, _ = _required_configuration_boolean(task, "EffortDriven")
        if effort_driven:
            raise NativeOutputError(
                f"task {activity_id} changed to effort-driven",
                outcome="executed_inconclusive",
            )
        pinned, _ = _required_configuration_boolean(task, "Pinned")
        if pinned:
            raise NativeOutputError(
                f"task {activity_id} is not automatically scheduled (Pinned 0)",
                outcome="executed_inconclusive",
            )
        manual, _ = _required_configuration_boolean(task, "Manual")
        if manual:
            raise NativeOutputError(
                f"task {activity_id} changed to manually scheduled (Manual 1)",
                outcome="executed_inconclusive",
            )
        constraint = expected_constraints.get(uid)
        constraint_type_state = _element_state(task, "ConstraintType")
        constraint_date_state = _coordinate_state(task, "ConstraintDate", origin)
        if constraint is None:
            if constraint_type_state.get("presence") == "present":
                raw_constraint_type = constraint_type_state.get("raw")
                if (
                    not isinstance(raw_constraint_type, str)
                    or re.fullmatch(r"(0|[1-9][0-9]*)", raw_constraint_type) is None
                ):
                    raise NativeOutputError(f"task {activity_id} has an invalid ConstraintType")
                if int(raw_constraint_type) != 0:
                    raise NativeOutputError(f"task {activity_id} gained an unexpected constraint")
            if "raw" in constraint_date_state:
                raise NativeOutputError(f"task {activity_id} gained an unexpected constraint date")
        else:
            observed_constraint_type, _ = _required_integer(task, "ConstraintType")
            if observed_constraint_type != constraint["native_constraint_type"]:
                raise NativeOutputError(f"task {activity_id} changed its frozen constraint type")
            if constraint_date_state.get("value") != constraint["canonical_coordinate"]:
                raise NativeOutputError(f"task {activity_id} changed its frozen constraint date")
        times = {
            "start": _coordinate_state(task, "Start", origin),
            "finish": _coordinate_state(task, "Finish", origin),
        }
        resume = _coordinate_state(task, "Resume", origin)
        if resume.get("presence") != "missing":
            times["remaining_start"] = resume
        activity_times[activity_id] = times
        additional_task_fields[activity_id] = _additional_field_states(task)

        for link in task.findall(_q("PredecessorLink")):
            predecessor_uid, predecessor_state = _required_integer(link, "PredecessorUID")
            native_type, type_state = _required_integer(link, "Type")
            native_lag, lag_state = _required_integer(link, "LinkLag")
            native_lag_format, lag_format_state = _required_configuration_integer(
                link, "LagFormat"
            )
            cross_project, cross_project_state = _required_configuration_boolean(
                link, "CrossProject"
            )
            if cross_project:
                raise NativeOutputError("cross-project predecessor links are outside the pilot")
            if predecessor_uid not in activity_by_uid:
                raise NativeOutputError(
                    f"task {activity_id} has unresolved predecessor UID {predecessor_uid}"
                )
            if native_type not in {0, 1, 2, 3}:
                raise NativeOutputError(f"task {activity_id} has unknown relationship Type {native_type}")
            key = (predecessor_uid, uid)
            if key in observed_relationships:
                raise NativeOutputError("native output contains a duplicate predecessor link")
            if key not in expected_relationships:
                raise NativeOutputError(
                    f"native output contains unknown relationship {activity_by_uid[predecessor_uid]}->{activity_id}"
                )
            expected = expected_relationships[key]
            if native_type != expected["native_type"]:
                raise NativeOutputError(
                    f"relationship {expected['relationship_id']} Type changed from "
                    f"{expected['native_type']} to {native_type}"
                )
            if native_lag != expected["native_link_lag_tenths_minutes"]:
                raise NativeOutputError(
                    f"relationship {expected['relationship_id']} LinkLag changed from "
                    f"{expected['native_link_lag_tenths_minutes']} to {native_lag}"
                )
            if native_lag_format != expected["native_lag_format"]:
                raise NativeOutputError(
                    f"relationship {expected['relationship_id']} LagFormat changed from "
                    f"{expected['native_lag_format']} to {native_lag_format}"
                )
            observed_relationships.add(key)
            raw_relationship_evidence.append(
                {
                    "relationship_id": expected["relationship_id"],
                    "predecessor_activity_id": activity_by_uid[predecessor_uid],
                    "successor_activity_id": activity_id,
                    "predecessor_uid": predecessor_state,
                    "native_type": type_state,
                    "native_link_lag": lag_state,
                    "native_lag_format": lag_format_state,
                    "cross_project": cross_project_state,
                    "normalised_type": expected["canonical_type"],
                    "normalised_signed_lag_hours": expected["canonical_signed_lag_hours"],
                    "transformation_id": ENUM_TRANSFORMATION_ID,
                }
            )
    missing_relationships = sorted(set(expected_relationships) - observed_relationships)
    if missing_relationships:
        rendered = [
            f"{activity_by_uid[pred]}->{activity_by_uid[succ]}"
            for pred, succ in missing_relationships
        ]
        raise NativeOutputError(f"native output is missing mapped relationships {rendered}")

    normalized = {
        "schema_version": "microsoft-project-normalized-native-output-v0.1",
        "native_system": NATIVE_SYSTEM,
        "mspdi_namespace": MSPDI_NAMESPACE,
        "mspdi_save_version": MSPDI_SAVE_VERSION,
        "case_id": case_realisation_manifest.get("case_id"),
        "native_output_raw_sha256": snapshot.sha256,
        "coordinate_origin": case_realisation_manifest["coordinate_contract"]["canonical_origin"],
        "activity_times": activity_times,
        "project_finish": _coordinate_state(root, "FinishDate", origin),
        "raw_relationship_evidence": sorted(
            raw_relationship_evidence, key=lambda item: item["relationship_id"]
        ),
        "additional_native_fields": {
            "project": {
                "SaveVersion": save_version_state,
                "NewTasksAreManual": new_tasks_manual_state,
                "ScheduleFromStart": schedule_from_start_state,
                "StartDate": project_start,
                "FinishDate": _element_state(root, "FinishDate"),
                "CAL-24X7-native-calendar-structure": calendar_structure,
                "ProjectSummaryTask": (
                    {
                        "presence": "present",
                        "value": _xml_structural_evidence(project_summary_task),
                        "interpretation_status": "retained_unclaimed",
                    }
                    if project_summary_task is not None
                    else {"presence": "missing"}
                ),
            },
            "tasks": additional_task_fields,
        },
        "claim_boundary": {
            "pilot_case_count": 1,
            "full_profile_required_case_count": 45,
            "full_45_case_gate_satisfied": False,
            "compatibility_claim_exists": False,
        },
    }
    return normalized


def _expected_projection(sealed_expected: Mapping[str, Any], case_id: str) -> Mapping[str, Any]:
    if sealed_expected.get("case_id") != case_id:
        raise NativeOutputError("sealed expected artifact case ID does not match the frozen manifest")
    source: Any = sealed_expected.get(
        "expected_normalized_output",
        sealed_expected.get(
            "expected_normalized", sealed_expected.get("expected", sealed_expected)
        ),
    )
    if not isinstance(source, Mapping):
        raise NativeOutputError("sealed expected artifact has no normalized expected object")
    activity_times = source.get("activity_times")
    if not isinstance(activity_times, Mapping) or "project_finish" not in source:
        raise NativeOutputError("sealed expected artifact lacks activity_times or project_finish")
    return source


def _difference_record(
    *,
    case_id: str,
    entity_id: str,
    field_path: str,
    expected: Any,
    observed_state: Mapping[str, Any],
) -> dict[str, Any]:
    if observed_state.get("presence") == "missing":
        classification = "missing_claim_field"
        observed: Any = {"presence": "missing"}
        transformation: str | None = None
    elif "value" not in observed_state:
        classification = "claim_field_mismatch"
        observed = dict(observed_state)
        transformation = None
    else:
        observed = observed_state["value"]
        if observed == expected:
            transformation = observed_state.get("transformation_id")
            classification = (
                "approved_transformation_match" if transformation is not None else "exact_match"
            )
        else:
            classification = "claim_field_mismatch"
            transformation = observed_state.get("transformation_id")
    return {
        "case_id": case_id,
        "activity_or_entity_id": entity_id,
        "field_path": field_path,
        "expected_normalized_value": expected,
        "observed_normalized_value": observed,
        "approved_transformation_id_or_null": transformation,
        "classification": classification,
        "evidence_artifact_sha256": None,
    }


def compare_normalized_output(
    *, normalized_output: Mapping[str, Any], sealed_expected: Mapping[str, Any]
) -> dict[str, Any]:
    """Compare a completed normalization against a separately supplied oracle."""

    case_id = normalized_output.get("case_id")
    if not isinstance(case_id, str) or not case_id:
        raise NativeOutputError("normalized output has no case ID")
    expected = _expected_projection(sealed_expected, case_id)
    expected_times = expected["activity_times"]
    observed_times = normalized_output.get("activity_times")
    if not isinstance(observed_times, Mapping):
        raise NativeOutputError("normalized output has no activity times")
    if set(expected_times) != set(observed_times):
        raise NativeOutputError("sealed and observed activity ID sets do not match")
    records: list[dict[str, Any]] = []
    for activity_id in sorted(expected_times):
        expected_record = expected_times[activity_id]
        observed_record = observed_times[activity_id]
        if not isinstance(expected_record, Mapping) or not isinstance(observed_record, Mapping):
            raise NativeOutputError("activity-time records must be objects")
        for field in ("start", "remaining_start", "finish"):
            if field not in expected_record:
                continue
            state = observed_record.get(field, {"presence": "missing"})
            if not isinstance(state, Mapping):
                raise NativeOutputError("normalized activity field state must be an object")
            records.append(
                _difference_record(
                    case_id=case_id,
                    entity_id=activity_id,
                    field_path=f"activity_times.{activity_id}.{field}",
                    expected=expected_record[field],
                    observed_state=state,
                )
            )
    project_state = normalized_output.get("project_finish")
    if not isinstance(project_state, Mapping):
        raise NativeOutputError("normalized project_finish state must be an object")
    records.append(
        _difference_record(
            case_id=case_id,
            entity_id="project",
            field_path="project_finish",
            expected=expected["project_finish"],
            observed_state=project_state,
        )
    )

    additional = normalized_output.get("additional_native_fields", {})
    if isinstance(additional, Mapping):
        project_fields = additional.get("project", {})
        if isinstance(project_fields, Mapping):
            for field, observed in sorted(project_fields.items()):
                if isinstance(observed, Mapping) and observed.get("presence") != "missing":
                    records.append(
                        {
                            "case_id": case_id,
                            "activity_or_entity_id": "project",
                            "field_path": f"additional_native_fields.project.{field}",
                            "expected_normalized_value": None,
                            "observed_normalized_value": dict(observed),
                            "approved_transformation_id_or_null": None,
                            "classification": "extra_unclaimed_field",
                            "evidence_artifact_sha256": None,
                        }
                    )
        task_fields = additional.get("tasks", {})
        if isinstance(task_fields, Mapping):
            for activity_id, fields in sorted(task_fields.items()):
                if not isinstance(fields, Mapping):
                    continue
                for field, observed in sorted(fields.items()):
                    if isinstance(observed, Mapping) and observed.get("presence") != "missing":
                        records.append(
                            {
                                "case_id": case_id,
                                "activity_or_entity_id": activity_id,
                                "field_path": f"additional_native_fields.tasks.{activity_id}.{field}",
                                "expected_normalized_value": None,
                                "observed_normalized_value": dict(observed),
                                "approved_transformation_id_or_null": None,
                                "classification": "extra_unclaimed_field",
                                "evidence_artifact_sha256": None,
                            }
                        )
    counts = {
        classification: sum(item["classification"] == classification for item in records)
        for classification in (
            "exact_match",
            "approved_transformation_match",
            "claim_field_mismatch",
            "missing_claim_field",
            "extra_unclaimed_field",
        )
    }
    has_claim_failure = bool(counts["claim_field_mismatch"] or counts["missing_claim_field"])
    return {
        "schema_version": "microsoft-project-field-difference-manifest-v0.1",
        "case_id": case_id,
        "difference_classifications": [
            "exact_match",
            "approved_transformation_match",
            "claim_field_mismatch",
            "missing_claim_field",
            "extra_unclaimed_field",
        ],
        "records": records,
        "counts": counts,
        "claim_field_failure": has_claim_failure,
        "partial_pilot_only": True,
        "full_45_case_gate_satisfied": False,
    }


def _safe_run_id(run_id: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", run_id) is None:
        raise NativeOutputError("run_id is outside the frozen safe identifier format")
    return run_id


def _require_sha256(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise NativeOutputError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _load_native_evidence_schema(repository_root: Path) -> dict[str, Any]:
    root = repository_root.resolve()
    if not root.is_dir():
        raise NativeOutputError("repository_root must be a directory")
    schema_path = root / "schemas/native-validation-preregistration.schema.json"
    _require_regular_file(schema_path, label="native-evidence schema")
    try:
        document = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise NativeOutputError(f"native-evidence schema is not readable JSON: {exc}") from exc
    if not isinstance(document, dict) or not isinstance(document.get("$defs"), dict):
        raise NativeOutputError("native-evidence schema has no $defs object")
    if "nativeRunEvidenceRecord" not in document["$defs"]:
        raise NativeOutputError("native-evidence schema has no nativeRunEvidenceRecord definition")
    return document


def validate_native_run_record(
    *, repository_root: Path, record: Mapping[str, Any]
) -> None:
    """Validate an emitted record against the frozen native evidence schema."""

    schema = _load_native_evidence_schema(repository_root)
    record_schema = {
        "$schema": schema.get("$schema", "https://json-schema.org/draft/2020-12/schema"),
        "$defs": schema["$defs"],
        "$ref": "#/$defs/nativeRunEvidenceRecord",
    }
    validator = Draft202012Validator(record_schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(dict(record)), key=lambda error: list(error.path))
    if errors:
        rendered = "; ".join(
            f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
            for error in errors
        )
        raise NativeOutputError(
            f"native-run record violates frozen nativeRunEvidenceRecord: {rendered}",
            outcome="executed_inconclusive",
        )


STAGE_ARTIFACT_FORMAT_BY_ROLE = {
    "native_calculated_file_sha256": "mpp",
    "native_pre_close_file_sha256": "mpp",
    "native_pre_close_output_sha256": "mspdi_xml",
    "native_reopened_file_sha256": "mpp",
    "native_recalculated_file_sha256": "mpp",
    "native_post_recalculate_output_sha256": "mspdi_xml",
    "native_pre_export_file_sha256": "mpp",
    "mspdi_xml_export_sha256": "mspdi_xml",
    "canonical_reimport_sha256": "canonical_json",
    "controlled_reexport_sha256": "mspdi_xml",
    "native_reopened_recalculated_file_sha256": "mpp",
}


def _validate_stage_artifact_format(
    *, role: str, path: Path, snapshot: RegularFileSnapshot
) -> None:
    expected_format = STAGE_ARTIFACT_FORMAT_BY_ROLE[role]
    if expected_format == "mpp":
        if path.suffix.lower() != ".mpp" or not snapshot.data.startswith(
            COMPOUND_FILE_BINARY_SIGNATURE
        ):
            raise NativeOutputError(
                f"stage artifact {role} must be a Compound File Binary .mpp file",
                outcome="executed_inconclusive",
            )
    elif expected_format == "mspdi_xml":
        if path.suffix.lower() != ".xml":
            raise NativeOutputError(
                f"stage artifact {role} must use the .xml MSPDI format",
                outcome="executed_inconclusive",
            )
        # The pre/post observation roles are parsed in the failure-retaining
        # analysis path below.  Do not turn an attested malformed observation
        # into a pre-analysis exception that loses its executed disposition.
        if role == "controlled_reexport_sha256":
            root = _parse_bounded_mspdi(snapshot)
            if root.tag != _q("Project"):
                raise NativeOutputError(
                    f"stage artifact {role} is not a reviewed Project 2010 MSPDI document",
                    outcome="executed_inconclusive",
                )
        else:
            try:
                snapshot.data.decode("utf-8")
            except UnicodeError as exc:
                raise NativeOutputError(
                    f"stage artifact {role} is not UTF-8 MSPDI XML",
                    outcome="executed_inconclusive",
                ) from exc
    elif expected_format == "canonical_json":
        if path.suffix.lower() != ".json":
            raise NativeOutputError(
                f"stage artifact {role} must use canonical JSON",
                outcome="executed_inconclusive",
            )
        try:
            parse_canonical_json_snapshot(snapshot, label=f"stage artifact {role}")
        except NativeEvidenceError as exc:
            raise NativeOutputError(str(exc), outcome="executed_inconclusive") from exc


def _snapshot_stage_artifacts(
    *,
    track_id: str,
    stage_artifact_paths: Mapping[str, Path],
    forbidden_files: Mapping[tuple[int, int], str] | None = None,
) -> dict[str, RegularFileSnapshot]:
    required = SUPPLIED_STAGE_ARTIFACT_KEYS_BY_TRACK.get(track_id)
    if required is None:
        raise NativeOutputError(f"unsupported execution track {track_id!r}")
    supplied = set(stage_artifact_paths)
    if supplied != set(required):
        raise NativeOutputError(
            f"stage_artifact_paths for {track_id} must contain exactly {sorted(required)}; "
            f"received {sorted(supplied)}",
            outcome="executed_inconclusive",
        )
    snapshots: dict[str, RegularFileSnapshot] = {}
    occupied_files: dict[tuple[int, int], str] = dict(forbidden_files or {})
    for role in sorted(required):
        path = stage_artifact_paths[role]
        if not isinstance(path, Path):
            raise NativeOutputError(
                f"stage artifact {role} must be supplied as a pathlib.Path",
                outcome="executed_inconclusive",
            )
        snapshot = read_regular_file_snapshot(
            path, label=f"stage artifact {role}", max_bytes=128 * 1024 * 1024
        )
        if snapshot.byte_size == 0:
            raise NativeOutputError(
                f"stage artifact {role} must not be empty",
                outcome="executed_inconclusive",
            )
        identity = snapshot.file_identity
        if identity in occupied_files:
            raise NativeOutputError(
                f"artifact roles {occupied_files[identity]} and {role} must use distinct files",
                outcome="executed_inconclusive",
            )
        occupied_files[identity] = role
        _validate_stage_artifact_format(role=role, path=path, snapshot=snapshot)
        snapshots[role] = snapshot
    return snapshots


def _hash_stage_artifacts(
    *, track_id: str, stage_artifact_paths: Mapping[str, Path]
) -> dict[str, str]:
    """Compatibility helper retained for focused policy tests."""

    return {
        role: snapshot.sha256
        for role, snapshot in _snapshot_stage_artifacts(
            track_id=track_id, stage_artifact_paths=stage_artifact_paths
        ).items()
    }


def _validate_post_execution_attestation(
    *,
    attestation: Mapping[str, Any],
    manifest: Mapping[str, Any],
    environment: Mapping[str, Any],
    executed_at: str,
    manifest_sha256: str,
    environment_sha256: str,
    native_output_sha256: str,
    stage_hashes: Mapping[str, str],
    post_execution_action_log_sha256: str,
    independent_evidence_hashes: Mapping[str, str],
    minimum_attested_at: datetime,
) -> None:
    required_fields = {
        "schema_version",
        "pilot_id",
        "native_system",
        "case_id",
        "execution_track_id",
        "actual_native_execution",
        "microsoft_project_desktop_opened",
        "case_opened_or_constructed",
        "native_recalculation_completed",
        "native_output_exported",
        "resource_leveling_disabled_and_not_run",
        "product_name",
        "edition",
        "version",
        "build",
        "executed_at",
        "attested_at",
        "attested_by",
        "environment_capture_sha256",
        "case_realization_manifest_sha256",
        "native_output_sha256",
        "stage_artifact_sha256_by_role",
        "post_execution_action_log_sha256",
        "independent_evidence_artifact_sha256_by_role",
    }
    if set(attestation) != required_fields:
        raise NativeOutputError(
            "post-execution attestation fields must exactly match the controlled contract",
            outcome="executed_inconclusive",
        )
    expected_identity = {
        "schema_version": "microsoft-project-post-execution-attestation-v0.1",
        "pilot_id": manifest.get("pilot_id"),
        "native_system": NATIVE_SYSTEM,
        "case_id": manifest.get("case_id"),
        "execution_track_id": manifest.get("execution_track_id"),
        "product_name": environment.get("product_name"),
        "edition": environment.get("edition"),
        "version": environment.get("version"),
        "build": environment.get("build"),
        "executed_at": executed_at,
        "attested_by": environment.get("execution_operator_id"),
        "environment_capture_sha256": environment_sha256,
        "case_realization_manifest_sha256": manifest_sha256,
        "native_output_sha256": native_output_sha256,
        "stage_artifact_sha256_by_role": dict(stage_hashes),
        "post_execution_action_log_sha256": post_execution_action_log_sha256,
        "independent_evidence_artifact_sha256_by_role": dict(
            independent_evidence_hashes
        ),
    }
    for field, expected in expected_identity.items():
        if attestation.get(field) != expected:
            raise NativeOutputError(
                f"post-execution attestation {field} does not match the frozen evidence",
                outcome="executed_inconclusive",
            )
    for field in (
        "actual_native_execution",
        "microsoft_project_desktop_opened",
        "case_opened_or_constructed",
        "native_recalculation_completed",
        "native_output_exported",
        "resource_leveling_disabled_and_not_run",
    ):
        if attestation.get(field) is not True:
            raise NativeOutputError(
                f"post-execution attestation {field} must be true before executed evidence exists",
                outcome="executed_inconclusive",
            )
    attested_at = attestation.get("attested_at")
    if not isinstance(attested_at, str) or not validate_rfc3339(attested_at):
        raise NativeOutputError(
            "post-execution attestation attested_at must be RFC 3339",
            outcome="executed_inconclusive",
        )
    if datetime.fromisoformat(attested_at.replace("Z", "+00:00")) < minimum_attested_at:
        raise NativeOutputError(
            "post-execution attestation cannot precede execution actions",
            outcome="executed_inconclusive",
        )
    for field in ("product_name", "edition", "version", "build", "attested_by"):
        if not isinstance(attestation.get(field), str) or not attestation[field].strip():
            raise NativeOutputError(
                f"post-execution attestation {field} must be nonblank",
                outcome="executed_inconclusive",
            )


def _snapshot_independent_evidence_artifacts(
    *,
    environment: Mapping[str, Any],
    independent_evidence_artifact_paths: Mapping[str, Path],
    forbidden_files: Mapping[tuple[int, int], str],
) -> dict[str, RegularFileSnapshot]:
    plan = environment.get("independent_verification_artifact_plan")
    if not isinstance(plan, list) or not plan:
        raise NativeOutputError("frozen environment has no independent evidence plan")
    roles: list[str] = []
    planned_type_by_role: dict[str, str] = {}
    for item in plan:
        if not isinstance(item, Mapping):
            raise NativeOutputError("independent evidence plan entries must be objects")
        role = item.get("role")
        if not isinstance(role, str) or not role:
            raise NativeOutputError("independent evidence plan role must be nonblank")
        roles.append(role)
        planned_type = item.get("planned_evidence_type")
        if planned_type not in {"screenshot", "native_report"}:
            raise NativeOutputError(
                f"independent evidence plan role {role} has an unknown planned media type"
            )
        planned_type_by_role[role] = planned_type
    if len(roles) != len(set(roles)):
        raise NativeOutputError("independent evidence plan contains duplicate roles")
    if set(independent_evidence_artifact_paths) != set(roles):
        raise NativeOutputError(
            f"independent evidence paths must contain exactly planned roles {sorted(roles)}",
            outcome="executed_inconclusive",
        )
    occupied_files = dict(forbidden_files)
    snapshots: dict[str, RegularFileSnapshot] = {}
    digest_roles: dict[str, str] = {}
    for role in sorted(roles):
        path = independent_evidence_artifact_paths[role]
        if not isinstance(path, Path):
            raise NativeOutputError(f"independent evidence {role} must be a pathlib.Path")
        snapshot = read_regular_file_snapshot(
            path, label=f"independent evidence {role}", max_bytes=32 * 1024 * 1024
        )
        if snapshot.byte_size == 0:
            raise NativeOutputError(
                f"independent evidence {role} must not be empty",
                outcome="executed_inconclusive",
            )
        suffix = path.suffix.lower()
        allowed_suffixes = (
            {".png"}
            if planned_type_by_role[role] == "screenshot"
            else {".pdf", ".csv"}
        )
        if suffix not in allowed_suffixes:
            raise NativeOutputError(
                f"independent evidence {role} does not match its planned "
                f"{planned_type_by_role[role]} media type",
                outcome="executed_inconclusive",
            )
        prefix = snapshot.data[:8]
        if suffix == ".png" and prefix != b"\x89PNG\r\n\x1a\n":
            raise NativeOutputError(
                f"independent evidence {role} has an invalid PNG signature",
                outcome="executed_inconclusive",
            )
        if suffix == ".pdf" and not prefix.startswith(b"%PDF-"):
            raise NativeOutputError(
                f"independent evidence {role} has an invalid PDF signature",
                outcome="executed_inconclusive",
            )
        identity = snapshot.file_identity
        if identity in occupied_files:
            raise NativeOutputError(
                f"independent evidence role {role} aliases "
                f"{occupied_files[identity]}; every evidence role must use its own distinct file",
                outcome="executed_inconclusive",
            )
        occupied_files[identity] = role
        if snapshot.sha256 in digest_roles:
            raise NativeOutputError(
                f"independent evidence roles {digest_roles[snapshot.sha256]} and {role} "
                "must not reuse identical evidence bytes",
                outcome="executed_inconclusive",
            )
        digest_roles[snapshot.sha256] = role
        snapshots[role] = snapshot
    return snapshots


def _hash_independent_evidence_artifacts(
    *,
    environment: Mapping[str, Any],
    independent_evidence_artifact_paths: Mapping[str, Path],
    forbidden_paths: Sequence[Path],
) -> dict[str, str]:
    """Compatibility helper retained for focused evidence-policy tests."""

    forbidden_files: dict[tuple[int, int], str] = {}
    for number, path in enumerate(forbidden_paths, start=1):
        snapshot = read_regular_file_snapshot(
            path, label=f"forbidden evidence role {number}"
        )
        forbidden_files[snapshot.file_identity] = f"forbidden evidence role {number}"

    return {
        role: snapshot.sha256
        for role, snapshot in _snapshot_independent_evidence_artifacts(
            environment=environment,
            independent_evidence_artifact_paths=independent_evidence_artifact_paths,
            forbidden_files=forbidden_files,
        ).items()
    }


def _validate_post_execution_action_log(
    *,
    document: Mapping[str, Any],
    manifest: Mapping[str, Any],
    environment: Mapping[str, Any],
    executed_at: str,
    manifest_sha256: str,
    environment_sha256: str,
    stage_roles: set[str],
    evidence_roles: set[str],
) -> datetime:
    required_fields = {
        "schema_version",
        "pilot_id",
        "native_system",
        "case_id",
        "execution_track_id",
        "executed_at",
        "operator_id",
        "environment_capture_sha256",
        "case_realization_manifest_sha256",
        "complete_manual_action_log_attestation",
        "actions",
    }
    if set(document) != required_fields:
        raise NativeOutputError("post-execution action log has an inexact field set")
    expected = {
        "schema_version": "microsoft-project-post-execution-action-log-v0.1",
        "pilot_id": manifest.get("pilot_id"),
        "native_system": NATIVE_SYSTEM,
        "case_id": manifest.get("case_id"),
        "execution_track_id": manifest.get("execution_track_id"),
        "executed_at": executed_at,
        "operator_id": environment.get("execution_operator_id"),
        "environment_capture_sha256": environment_sha256,
        "case_realization_manifest_sha256": manifest_sha256,
        "complete_manual_action_log_attestation": True,
    }
    for field, value in expected.items():
        if document.get(field) != value:
            raise NativeOutputError(f"post-execution action log {field} is not bound")
    actions = document.get("actions")
    if not isinstance(actions, list) or not actions:
        raise NativeOutputError("post-execution action log actions must be nonempty")
    seen_stage_roles: set[str] = set()
    seen_evidence_roles: set[str] = set()
    required_action_ids = POST_EXECUTION_ACTION_IDS_BY_TRACK.get(
        str(manifest.get("execution_track_id"))
    )
    if required_action_ids is None:
        raise NativeOutputError("post-execution action track is unsupported", outcome="executed_inconclusive")
    previous_datetime = datetime.fromisoformat(executed_at.replace("Z", "+00:00"))
    observed_action_ids: list[str] = []
    for expected_sequence, action in enumerate(actions, start=1):
        if not isinstance(action, Mapping) or set(action) != {
            "sequence",
            "action_id",
            "action",
            "performed_at",
            "stage_artifact_roles",
            "independent_evidence_roles",
        }:
            raise NativeOutputError("post-execution action entries have an inexact shape")
        if action["sequence"] != expected_sequence:
            raise NativeOutputError("post-execution action sequence must be contiguous")
        if not isinstance(action["action_id"], str):
            raise NativeOutputError("post-execution action_id must be a string")
        observed_action_ids.append(action["action_id"])
        if not isinstance(action["action"], str) or not action["action"].strip():
            raise NativeOutputError("post-execution action text must be nonblank")
        if not isinstance(action["performed_at"], str) or not validate_rfc3339(
            action["performed_at"]
        ):
            raise NativeOutputError("post-execution action performed_at must be RFC 3339")
        performed_datetime = datetime.fromisoformat(action["performed_at"].replace("Z", "+00:00"))
        if performed_datetime < previous_datetime:
            raise NativeOutputError(
                "post-execution actions must be chronological and not precede execution",
                outcome="executed_inconclusive",
            )
        previous_datetime = performed_datetime
        for field, allowed, seen in (
            ("stage_artifact_roles", stage_roles, seen_stage_roles),
            ("independent_evidence_roles", evidence_roles, seen_evidence_roles),
        ):
            values = action[field]
            if (
                not isinstance(values, list)
                or not all(isinstance(item, str) for item in values)
                or len(values) != len(set(values))
                or not set(values).issubset(allowed)
            ):
                raise NativeOutputError(f"post-execution action {field} is invalid")
            seen.update(values)
    if tuple(observed_action_ids) != required_action_ids:
        raise NativeOutputError(
            "post-execution action_ids must exactly match the frozen track order",
            outcome="executed_inconclusive",
        )
    if seen_stage_roles != stage_roles:
        raise NativeOutputError("post-execution actions do not cover every native stage role")
    if seen_evidence_roles != evidence_roles:
        raise NativeOutputError("post-execution actions do not cover every evidence role")
    return previous_datetime


def _stage_hashes_for_record(
    *,
    manifest: Mapping[str, Any],
    manifest_sha256: str,
    supplied_stage_hashes: Mapping[str, str],
    normalized_output_sha256: str,
) -> dict[str, str]:
    track_id = manifest["execution_track_id"]
    if track_id == "manual_native_semantic_parity":
        result = {
            "case_realization_manifest_sha256": manifest_sha256,
            "native_source_file_sha256": _require_sha256(
                manifest.get("native_source_file_sha256"),
                field="manifest.native_source_file_sha256",
            ),
            "native_calculated_file_sha256": supplied_stage_hashes[
                "native_calculated_file_sha256"
            ],
            "normalized_native_output_sha256": normalized_output_sha256,
        }
    elif track_id == "saved_file_reopen_recalculate_stability":
        prerequisite = _require_sha256(
            manifest.get("prerequisite_manual_case_realization_manifest_sha256"),
            field="manifest.prerequisite_manual_case_realization_manifest_sha256",
        )
        # Accessing the value is intentional: its binding is separately retained
        # in the evidence bundle while the frozen schema fixes Track B's five keys.
        if not prerequisite:
            raise AssertionError("unreachable")
        result = dict(supplied_stage_hashes)
    elif track_id == "adapter_interchange_round_trip":
        result = dict(supplied_stage_hashes)
        result["final_normalized_native_output_sha256"] = normalized_output_sha256
    else:
        raise NativeOutputError(f"unsupported execution track {track_id!r}")
    if set(result) != set(REQUIRED_STAGE_HASH_KEYS_BY_TRACK[track_id]):
        raise NativeOutputError(
            "derived stage hash keys do not match the frozen track schema",
            outcome="executed_inconclusive",
        )
    return result


def _failed_normalization_documents(
    *, case_id: str, native_output_sha256: str, error: NativeOutputError
) -> tuple[dict[str, Any], dict[str, Any]]:
    normalized = {
        "schema_version": "microsoft-project-normalized-native-output-v0.1",
        "native_system": NATIVE_SYSTEM,
        "case_id": case_id,
        "normalization_status": "failed",
        "native_output_raw_sha256": native_output_sha256,
        "error_type": type(error).__name__,
        "error_message": str(error),
        "claim_boundary": {
            "pilot_case_count": 1,
            "full_profile_required_case_count": 45,
            "full_45_case_gate_satisfied": False,
            "compatibility_claim_exists": False,
        },
    }
    classification = (
        "claim_field_mismatch"
        if error.outcome == "executed_fail"
        else "extra_unclaimed_field"
    )
    counts = {
        "exact_match": 0,
        "approved_transformation_match": 0,
        "claim_field_mismatch": int(classification == "claim_field_mismatch"),
        "missing_claim_field": 0,
        "extra_unclaimed_field": int(classification == "extra_unclaimed_field"),
    }
    difference = {
        "schema_version": "microsoft-project-field-difference-manifest-v0.1",
        "case_id": case_id,
        "difference_classifications": [
            "exact_match",
            "approved_transformation_match",
            "claim_field_mismatch",
            "missing_claim_field",
            "extra_unclaimed_field",
        ],
        "records": [
            {
                "case_id": case_id,
                "activity_or_entity_id": "native_output",
                "field_path": "normalization",
                "expected_normalized_value": None,
                "observed_normalized_value": {
                    "normalization_status": "failed",
                    "error_type": type(error).__name__,
                    "error_message": str(error),
                },
                "approved_transformation_id_or_null": None,
                "classification": classification,
                "evidence_artifact_sha256": None,
            }
        ],
        "counts": counts,
        "claim_field_failure": error.outcome == "executed_fail",
        "partial_pilot_only": True,
        "full_45_case_gate_satisfied": False,
    }
    return normalized, difference


def _stability_claim_projection(normalized: Mapping[str, Any]) -> dict[str, Any]:
    """Project only the claim fields allowed by the frozen comparison profile."""

    activity_times = normalized.get("activity_times")
    project_finish = normalized.get("project_finish")
    if not isinstance(activity_times, Mapping) or not isinstance(project_finish, Mapping):
        raise NativeOutputError("normalized stability observation lacks claim fields")
    projected_activities: dict[str, Any] = {}
    for activity_id in sorted(activity_times):
        record = activity_times[activity_id]
        if not isinstance(activity_id, str) or not isinstance(record, Mapping):
            raise NativeOutputError("normalized stability activity record is invalid")
        projected_activities[activity_id] = {}
        for field in ("start", "remaining_start", "finish"):
            state = record.get(field, {"presence": "missing"})
            if not isinstance(state, Mapping):
                raise NativeOutputError("normalized stability field state is invalid")
            presence = state.get("presence")
            if presence == "missing":
                projected_activities[activity_id][field] = {"presence": "missing"}
            elif presence == "present" and "value" in state:
                projected_activities[activity_id][field] = {
                    "presence": "present",
                    "value": state["value"],
                }
            elif presence == "present" and state.get("value_kind") == "blank":
                projected_activities[activity_id][field] = {
                    "presence": "present",
                    "value_kind": "blank",
                }
            else:
                raise NativeOutputError("normalized stability field presence is invalid")
    project_presence = project_finish.get("presence")
    if project_presence == "missing":
        projected_finish = {"presence": "missing"}
    elif project_presence == "present" and "value" in project_finish:
        projected_finish = {"presence": "present", "value": project_finish["value"]}
    elif project_presence == "present" and project_finish.get("value_kind") == "blank":
        projected_finish = {"presence": "present", "value_kind": "blank"}
    else:
        raise NativeOutputError("normalized stability project finish state is invalid")
    return {
        "activity_times": projected_activities,
        "project_finish": projected_finish,
    }


def _compare_reopen_stability(
    *,
    case_id: str,
    pre_close_normalized: Mapping[str, Any],
    post_recalculate_normalized: Mapping[str, Any],
) -> dict[str, Any]:
    """Compare two native observations without consulting the expected oracle."""

    pre = _stability_claim_projection(pre_close_normalized)
    post = _stability_claim_projection(post_recalculate_normalized)
    records: list[dict[str, Any]] = []
    activity_ids = sorted(set(pre["activity_times"]) | set(post["activity_times"]))
    for activity_id in activity_ids:
        pre_record = pre["activity_times"].get(activity_id)
        post_record = post["activity_times"].get(activity_id)
        for field in ("start", "remaining_start", "finish"):
            pre_state = (
                pre_record.get(field, {"presence": "missing"})
                if isinstance(pre_record, Mapping)
                else {"presence": "missing"}
            )
            post_state = (
                post_record.get(field, {"presence": "missing"})
                if isinstance(post_record, Mapping)
                else {"presence": "missing"}
            )
            records.append(
                {
                    "field_path": f"activity_times.{activity_id}.{field}",
                    "pre_close_state": pre_state,
                    "post_recalculate_state": post_state,
                    "exact_normalized_match": pre_state == post_state,
                }
            )
    records.append(
        {
            "field_path": "project_finish",
            "pre_close_state": pre["project_finish"],
            "post_recalculate_state": post["project_finish"],
            "exact_normalized_match": pre["project_finish"] == post["project_finish"],
        }
    )
    mismatch_count = sum(not record["exact_normalized_match"] for record in records)
    return {
        "schema_version": "microsoft-project-reopen-stability-difference-v0.1",
        "case_id": case_id,
        "comparison_status": "completed",
        "comparison_domain": "permitted_normalized_claim_fields_only",
        "expected_oracle_used": False,
        "null_missing_zero_compared_exactly": True,
        "records": records,
        "mismatch_count": mismatch_count,
        "exact_normalized_stability": mismatch_count == 0,
    }


def _failed_stability_document(
    *, case_id: str, errors_by_observation: Mapping[str, NativeOutputError]
) -> dict[str, Any]:
    return {
        "schema_version": "microsoft-project-reopen-stability-difference-v0.1",
        "case_id": case_id,
        "comparison_status": "not_completed",
        "comparison_domain": "permitted_normalized_claim_fields_only",
        "expected_oracle_used": False,
        "null_missing_zero_compared_exactly": True,
        "errors_by_observation": {
            key: {
                "error_type": type(error).__name__,
                "error_message": str(error),
                "outcome": error.outcome,
            }
            for key, error in sorted(errors_by_observation.items())
        },
        "records": [],
        "mismatch_count": None,
        "exact_normalized_stability": False,
    }


def _validate_track_b_prerequisite(
    *,
    repository_root: Path,
    track_b_manifest: Mapping[str, Any],
    prerequisite_path: Path | None,
    environment_capture_path: Path,
) -> tuple[Mapping[str, Any], RegularFileSnapshot] | None:
    track_id = track_b_manifest.get("execution_track_id")
    if track_id != "saved_file_reopen_recalculate_stability":
        if prerequisite_path is not None:
            raise NativeOutputError(
                "a prerequisite manual manifest is accepted only for Track B",
                outcome="executed_inconclusive",
            )
        return None
    if prerequisite_path is None:
        raise NativeOutputError(
            "Track B analysis requires the bound prerequisite Track-A manifest bytes",
            outcome="executed_inconclusive",
        )
    prerequisite, snapshot = load_canonical_json_snapshot(
        prerequisite_path, label="prerequisite manual case-realisation manifest"
    )
    expected_digest = _require_sha256(
        track_b_manifest.get("prerequisite_manual_case_realization_manifest_sha256"),
        field="manifest.prerequisite_manual_case_realization_manifest_sha256",
    )
    if snapshot.sha256 != expected_digest:
        raise NativeOutputError(
            "Track B prerequisite bytes do not match the frozen prerequisite digest",
            outcome="executed_inconclusive",
        )
    validate_case_realisation_manifest_against_repository(
        repository_root=repository_root,
        document=prerequisite,
        environment_capture_path=environment_capture_path,
    )
    exact_values = {
        "pilot_id": track_b_manifest.get("pilot_id"),
        "native_system": NATIVE_SYSTEM,
        "state": "frozen_before_native_calculation",
        "case_id": track_b_manifest.get("case_id"),
        "execution_track_id": "manual_native_semantic_parity",
        "prerequisite_manual_case_realization_manifest_sha256": None,
        "native_source_file_sha256": track_b_manifest.get("native_source_file_sha256"),
        "environment_capture_sha256": track_b_manifest.get("environment_capture_sha256"),
        "captured_product_environment": track_b_manifest.get(
            "captured_product_environment"
        ),
        "native_activity_and_field_mapping": track_b_manifest.get(
            "native_activity_and_field_mapping"
        ),
        "native_calendar_realization": track_b_manifest.get(
            "native_calendar_realization"
        ),
        "native_relationship_and_lag_realization": track_b_manifest.get(
            "native_relationship_and_lag_realization"
        ),
        "native_constraint_realization": track_b_manifest.get(
            "native_constraint_realization"
        ),
        "native_progress_realization": track_b_manifest.get(
            "native_progress_realization"
        ),
        "all_product_settings": track_b_manifest.get("all_product_settings"),
        "prepared_by": track_b_manifest.get("prepared_by"),
        "independent_pre_execution_reviewed_by": track_b_manifest.get(
            "independent_pre_execution_reviewed_by"
        ),
    }
    for field, expected in exact_values.items():
        if prerequisite.get(field) != expected:
            raise NativeOutputError(
                f"Track B prerequisite {field} does not match the frozen realization",
                outcome="executed_inconclusive",
            )
    return prerequisite, snapshot


def analyse_msproject_native_output(
    *,
    repository_root: Path,
    native_output_path: Path,
    case_realisation_manifest_path: Path,
    sealed_expected_path: Path,
    environment_capture_path: Path,
    post_execution_attestation_path: Path,
    post_execution_action_log_path: Path,
    prerequisite_manual_case_realization_manifest_path: Path | None = None,
    stage_artifact_paths: Mapping[str, Path],
    independent_evidence_artifact_paths: Mapping[str, Path],
    output_dir: Path,
    run_id: str,
    executed_at: str,
) -> NativeAnalysis:
    """Normalize and compare one frozen native output, retaining claim limits.

    This actual-analysis path requires explicit attestation and all stage files.
    Parser-only callers must use :func:`normalize_mspdi_output`, which creates no
    execution status.  This function can emit ``executed_fail`` or
    ``executed_inconclusive`` only; acceptance remains a separate review step.
    """

    run_id = _safe_run_id(run_id)
    if not isinstance(executed_at, str) or not validate_rfc3339(executed_at):
        raise NativeOutputError("executed_at must be a timezone-qualified RFC 3339 timestamp")
    manifest, manifest_snapshot = load_canonical_json_snapshot(
        case_realisation_manifest_path, label="case-realisation manifest"
    )
    environment, environment_snapshot = load_canonical_json_snapshot(
        environment_capture_path, label="environment capture"
    )
    validate_case_realisation_manifest_against_repository(
        repository_root=repository_root,
        document=manifest,
        environment_capture_path=environment_capture_path,
    )
    executed_datetime = datetime.fromisoformat(executed_at.replace("Z", "+00:00"))
    prepared_at = manifest.get("prepared_at")
    if not isinstance(prepared_at, str) or not validate_rfc3339(prepared_at):
        raise NativeOutputError("case-realisation manifest prepared_at must be RFC 3339", outcome="executed_inconclusive")
    if executed_datetime <= datetime.fromisoformat(prepared_at.replace("Z", "+00:00")):
        raise NativeOutputError("native execution must occur after the pre-execution freeze", outcome="executed_inconclusive")
    environment_sha256 = environment_snapshot.sha256
    if environment_sha256 != manifest.get("environment_capture_sha256"):
        raise NativeOutputError("environment capture hash does not match the frozen manifest")
    sealed_expected_snapshot = read_regular_file_snapshot(
        sealed_expected_path, label="sealed expected artifact"
    )
    if sealed_expected_snapshot.sha256 != manifest.get("sealed_expected_raw_sha256"):
        raise NativeOutputError("sealed expected artifact hash does not match the frozen manifest")

    _validate_manifest_for_normalization(manifest)
    track_id = manifest.get("execution_track_id")
    prerequisite_result = _validate_track_b_prerequisite(
        repository_root=repository_root,
        track_b_manifest=manifest,
        prerequisite_path=prerequisite_manual_case_realization_manifest_path,
        environment_capture_path=environment_capture_path,
    )
    prerequisite_snapshot = prerequisite_result[1] if prerequisite_result is not None else None
    action_log, action_log_snapshot = load_canonical_json_snapshot(
        post_execution_action_log_path, label="post-execution action log"
    )
    attestation, attestation_snapshot = load_canonical_json_snapshot(
        post_execution_attestation_path, label="post-execution attestation"
    )
    native_output_snapshot = read_regular_file_snapshot(
        native_output_path, label="native output", max_bytes=MAX_MSPDI_BYTES
    )
    control_snapshots: dict[str, RegularFileSnapshot] = {
        "case-realisation manifest": manifest_snapshot,
        "environment capture": environment_snapshot,
        "sealed expected": sealed_expected_snapshot,
        "post-execution attestation": attestation_snapshot,
        "post-execution action log": action_log_snapshot,
        "native output": native_output_snapshot,
    }
    if prerequisite_snapshot is not None:
        control_snapshots["prerequisite Track-A manifest"] = prerequisite_snapshot
    occupied_control_files: dict[tuple[int, int], str] = {}
    for role, snapshot in control_snapshots.items():
        if snapshot.file_identity in occupied_control_files:
            raise NativeOutputError(
                f"artifact roles {occupied_control_files[snapshot.file_identity]} and {role} "
                "must use distinct files",
                outcome="executed_inconclusive",
            )
        occupied_control_files[snapshot.file_identity] = role
    stage_snapshots = _snapshot_stage_artifacts(
        track_id=track_id,
        stage_artifact_paths=stage_artifact_paths,
        forbidden_files={
            identity: role
            for identity, role in occupied_control_files.items()
            if role != "native output"
        },
    )
    supplied_stage_hashes = {
        role: snapshot.sha256 for role, snapshot in stage_snapshots.items()
    }
    permitted_native_output_alias = {
        "saved_file_reopen_recalculate_stability": "native_post_recalculate_output_sha256",
        "adapter_interchange_round_trip": "mspdi_xml_export_sha256",
    }.get(str(track_id))
    for role, snapshot in stage_snapshots.items():
        if (
            snapshot.file_identity == native_output_snapshot.file_identity
            and role != permitted_native_output_alias
        ):
            raise NativeOutputError(
                f"stage artifact {role} must not alias the native output role",
                outcome="executed_inconclusive",
            )
    native_output_sha256 = native_output_snapshot.sha256
    if track_id == "saved_file_reopen_recalculate_stability" and (
        supplied_stage_hashes["native_post_recalculate_output_sha256"]
        != native_output_sha256
    ):
        raise NativeOutputError(
            "Track B native output must be the supplied post-recalculate output",
            outcome="executed_inconclusive",
        )
    if track_id == "adapter_interchange_round_trip" and (
        supplied_stage_hashes["mspdi_xml_export_sha256"] != native_output_sha256
    ):
        raise NativeOutputError(
            "adapter native output must be the supplied MSPDI XML export",
            outcome="executed_inconclusive",
        )
    manifest_sha256 = manifest_snapshot.sha256
    occupied_evidence_files = dict(occupied_control_files)
    occupied_evidence_files.update(
        {snapshot.file_identity: role for role, snapshot in stage_snapshots.items()}
    )
    evidence_snapshots = _snapshot_independent_evidence_artifacts(
        environment=environment,
        independent_evidence_artifact_paths=independent_evidence_artifact_paths,
        forbidden_files=occupied_evidence_files,
    )
    independent_evidence_hashes = {
        role: snapshot.sha256 for role, snapshot in evidence_snapshots.items()
    }
    last_action_at = _validate_post_execution_action_log(
        document=action_log,
        manifest=manifest,
        environment=environment,
        executed_at=executed_at,
        manifest_sha256=manifest_sha256,
        environment_sha256=environment_sha256,
        stage_roles=set(supplied_stage_hashes),
        evidence_roles=set(independent_evidence_hashes),
    )
    _validate_post_execution_attestation(
        attestation=attestation,
        manifest=manifest,
        environment=environment,
        executed_at=executed_at,
        manifest_sha256=manifest_sha256,
        environment_sha256=environment_sha256,
        native_output_sha256=native_output_sha256,
        stage_hashes=supplied_stage_hashes,
        post_execution_action_log_sha256=action_log_snapshot.sha256,
        independent_evidence_hashes=independent_evidence_hashes,
        minimum_attested_at=last_action_at,
    )

    errors_by_observation: dict[str, NativeOutputError] = {}
    pre_close_normalized: dict[str, Any] | None = None
    if track_id == "saved_file_reopen_recalculate_stability":
        pre_close_path = stage_artifact_paths["native_pre_close_output_sha256"]
        try:
            pre_close_normalized = normalize_mspdi_output(
                native_output_path=pre_close_path,
                case_realisation_manifest=manifest,
                native_output_snapshot=stage_snapshots[
                    "native_pre_close_output_sha256"
                ],
            )
        except NativeOutputError as exc:
            errors_by_observation["pre_close"] = exc
            pre_close_normalized, _ = _failed_normalization_documents(
                case_id=manifest["case_id"],
                native_output_sha256=supplied_stage_hashes[
                    "native_pre_close_output_sha256"
                ],
                error=exc,
            )
        except Exception as exc:
            wrapped = NativeOutputError(
                f"unexpected pre-close normalization error: {type(exc).__name__}: {exc}",
                outcome="executed_inconclusive",
            )
            errors_by_observation["pre_close"] = wrapped
            pre_close_normalized, _ = _failed_normalization_documents(
                case_id=manifest["case_id"],
                native_output_sha256=supplied_stage_hashes[
                    "native_pre_close_output_sha256"
                ],
                error=wrapped,
            )

    normalized: dict[str, Any]
    precomparison_normalized_sha256: str | None = None
    try:
        normalized = normalize_mspdi_output(
            native_output_path=native_output_path,
            case_realisation_manifest=manifest,
            native_output_snapshot=native_output_snapshot,
        )
    except NativeOutputError as exc:
        errors_by_observation["post_recalculate"] = exc
        normalized, difference = _failed_normalization_documents(
            case_id=manifest["case_id"],
            native_output_sha256=native_output_sha256,
            error=exc,
        )
    except Exception as exc:  # preserve an attested run even if parsing fails unexpectedly
        wrapped = NativeOutputError(
            f"unexpected post-recalculate normalization error: {type(exc).__name__}: {exc}",
            outcome="executed_inconclusive",
        )
        errors_by_observation["post_recalculate"] = wrapped
        normalized, difference = _failed_normalization_documents(
            case_id=manifest["case_id"],
            native_output_sha256=native_output_sha256,
            error=wrapped,
        )
    else:
        # Freeze the independently normalized observation before releasing the
        # sealed oracle to the comparison path.
        precomparison_normalized_sha256 = _canonical_json_file_sha256(normalized)
        try:
            sealed_expected = parse_canonical_json_snapshot(
                sealed_expected_snapshot, label="sealed expected artifact"
            )
            expected_fixture_hash = sealed_expected.get(
                "fixture_raw_sha256", sealed_expected.get("source_fixture_raw_sha256")
            )
            if expected_fixture_hash is None:
                source_bindings = sealed_expected.get("source_bindings", {})
                fixture_binding = (
                    source_bindings.get("fixture", {})
                    if isinstance(source_bindings, Mapping)
                    else {}
                )
                if isinstance(fixture_binding, Mapping):
                    expected_fixture_hash = fixture_binding.get("raw_sha256")
            if (
                expected_fixture_hash is not None
                and expected_fixture_hash != manifest.get("fixture_raw_sha256")
            ):
                raise NativeOutputError(
                    "sealed expected artifact is not bound to the frozen fixture"
                )
            difference = compare_normalized_output(
                normalized_output=normalized,
                sealed_expected=sealed_expected,
            )
        except NativeOutputError as exc:
            errors_by_observation["post_recalculate_expected_comparison"] = exc
            _, difference = _failed_normalization_documents(
                case_id=manifest["case_id"],
                native_output_sha256=native_output_sha256,
                error=exc,
            )
        except NativeEvidenceError as exc:
            wrapped = NativeOutputError(
                f"sealed expected artifact could not be released: {exc}",
                outcome="executed_inconclusive",
            )
            errors_by_observation["post_recalculate_expected_comparison"] = wrapped
            _, difference = _failed_normalization_documents(
                case_id=manifest["case_id"],
                native_output_sha256=native_output_sha256,
                error=wrapped,
            )
        except Exception as exc:
            wrapped = NativeOutputError(
                f"unexpected expected-comparison error: {type(exc).__name__}: {exc}",
                outcome="executed_inconclusive",
            )
            errors_by_observation["post_recalculate_expected_comparison"] = wrapped
            _, difference = _failed_normalization_documents(
                case_id=manifest["case_id"],
                native_output_sha256=native_output_sha256,
                error=wrapped,
            )

    if precomparison_normalized_sha256 is None:
        precomparison_normalized_sha256 = _canonical_json_file_sha256(normalized)

    stability_difference: dict[str, Any] | None = None
    if track_id == "saved_file_reopen_recalculate_stability":
        if errors_by_observation:
            stability_difference = _failed_stability_document(
                case_id=manifest["case_id"],
                errors_by_observation=errors_by_observation,
            )
        else:
            if pre_close_normalized is None:
                raise AssertionError("Track B pre-close normalization was not produced")
            try:
                stability_difference = _compare_reopen_stability(
                    case_id=manifest["case_id"],
                    pre_close_normalized=pre_close_normalized,
                    post_recalculate_normalized=normalized,
                )
            except NativeOutputError as exc:
                errors_by_observation["stability_comparison"] = exc
                stability_difference = _failed_stability_document(
                    case_id=manifest["case_id"],
                    errors_by_observation=errors_by_observation,
                )
            except Exception as exc:
                wrapped = NativeOutputError(
                    f"unexpected stability comparison error: {type(exc).__name__}: {exc}",
                    outcome="executed_inconclusive",
                )
                errors_by_observation["stability_comparison"] = wrapped
                stability_difference = _failed_stability_document(
                    case_id=manifest["case_id"],
                    errors_by_observation=errors_by_observation,
                )

    if errors_by_observation:
        status = (
            "executed_fail"
            if any(error.outcome == "executed_fail" for error in errors_by_observation.values())
            else "executed_inconclusive"
        )
        reason = "native observation processing did not complete: " + "; ".join(
            f"{key}: {error}" for key, error in sorted(errors_by_observation.items())
        )
    elif difference["claim_field_failure"]:
        status = "executed_fail"
        reason = "one or more claim fields differ or are missing"
    elif stability_difference is not None and not stability_difference[
        "exact_normalized_stability"
    ]:
        status = "executed_fail"
        reason = "pre-close and post-recalculate normalized claim fields differ"
    else:
        status = "executed_inconclusive"
        reason = (
            "exact normalized comparison awaits independent review; the partial pilot "
            "cannot satisfy the 45-case gate"
        )

    output_dir = _prepare_new_output_directory(
        output_dir, purpose="microsoft-project-native-output-analysis"
    )
    normalized_path = output_dir / "normalized-native-output.json"
    difference_path = output_dir / "field-difference-manifest.json"
    environment_path = output_dir / "environment-capture.json"
    attestation_path = output_dir / "post-execution-attestation.json"
    manual_log_path = output_dir / "post-execution-manual-action-log.json"
    construction_log_path = output_dir / "pre-execution-construction-action-log.json"
    pre_close_normalized_path = output_dir / "normalized-native-output-pre-close.json"
    stability_difference_path = output_dir / "reopen-stability-difference.json"
    write_canonical_json(normalized_path, normalized)
    normalized_sha = raw_file_sha256(normalized_path)
    if normalized_sha != precomparison_normalized_sha256:
        raise NativeOutputError(
            "written normalized output hash differs from its precomparison freeze",
            outcome="executed_inconclusive",
        )
    pre_close_normalized_sha: str | None = None
    stability_difference_sha: str | None = None
    if track_id == "saved_file_reopen_recalculate_stability":
        if pre_close_normalized is None or stability_difference is None:
            raise AssertionError("Track B retained observations were not produced")
        write_canonical_json(pre_close_normalized_path, pre_close_normalized)
        pre_close_normalized_sha = raw_file_sha256(pre_close_normalized_path)
        if pre_close_normalized_sha != _canonical_json_file_sha256(
            pre_close_normalized
        ):
            raise NativeOutputError(
                "written pre-close normalized hash differs from its independent freeze",
                outcome="executed_inconclusive",
            )
        stability_difference["pre_close_normalized_output_sha256"] = (
            pre_close_normalized_sha
        )
        stability_difference["post_recalculate_normalized_output_sha256"] = normalized_sha
        write_canonical_json(stability_difference_path, stability_difference)
        stability_difference_sha = raw_file_sha256(stability_difference_path)
    for record in difference["records"]:
        record["evidence_artifact_sha256"] = normalized_sha
    write_canonical_json(difference_path, difference)
    write_canonical_json(environment_path, environment)
    write_canonical_json(attestation_path, attestation)
    write_canonical_json(manual_log_path, action_log)
    construction_log = {
        "schema_version": "msproject-manual-action-log-v0.1",
        "case_id": manifest["case_id"],
        "execution_track_id": manifest["execution_track_id"],
        "actions": manifest["construction_action_log"],
    }
    write_canonical_json(construction_log_path, construction_log)

    artifact_hashes = {
        "case_realisation_manifest": manifest_sha256,
        "environment_capture": raw_file_sha256(environment_path),
        "field_difference_manifest": raw_file_sha256(difference_path),
        "manual_action_log": raw_file_sha256(manual_log_path),
        "pre_execution_construction_action_log": raw_file_sha256(
            construction_log_path
        ),
        "native_input": manifest["native_source_file_sha256"],
        "native_output": native_output_sha256,
        "normalized_output": normalized_sha,
        "post_execution_attestation": raw_file_sha256(attestation_path),
        "sealed_expected": sealed_expected_snapshot.sha256,
    }
    for role, digest in independent_evidence_hashes.items():
        artifact_hashes[f"independent_evidence.{role}"] = digest
    for role, digest in supplied_stage_hashes.items():
        artifact_hashes[f"stage.{role}"] = digest
    prerequisite_manual_sha = manifest.get(
        "prerequisite_manual_case_realization_manifest_sha256"
    )
    if track_id == "saved_file_reopen_recalculate_stability":
        artifact_hashes["prerequisite_manual_case_realization_manifest"] = _require_sha256(
            prerequisite_manual_sha,
            field="manifest.prerequisite_manual_case_realization_manifest_sha256",
        )
        artifact_hashes["pre_close_normalized_output"] = pre_close_normalized_sha
        artifact_hashes["reopen_stability_difference"] = stability_difference_sha
    artifact_index = {
        "schema_version": "msproject-native-artifact-hash-index-v0.1",
        "case_id": manifest["case_id"],
        "run_id": run_id,
        "hash_algorithm": "sha256",
        "artifacts": [
            {
                "artifact_role": role,
                "sha256": digest,
                **(
                    {
                        "byte_size": evidence_snapshots[
                            role.removeprefix("independent_evidence.")
                        ].byte_size,
                        "media_type": {
                            ".png": "image/png", ".pdf": "application/pdf",
                            ".csv": "text/csv", ".json": "application/json",
                            ".xml": "application/xml", ".txt": "text/plain",
                        }[independent_evidence_artifact_paths[
                            role.removeprefix("independent_evidence.")
                        ].suffix.lower()],
                    }
                    if role.startswith("independent_evidence.") else {}
                ),
            }
            for role, digest in sorted(artifact_hashes.items())
        ],
        "raw_native_files_embedded": False,
    }
    artifact_index_path = output_dir / "artifact-hash-index.json"
    write_canonical_json(artifact_index_path, artifact_index)

    evidence_bundle = {
        "schema_version": "msproject-native-analysis-evidence-bundle-v0.1",
        "run_id": run_id,
        "case_id": manifest["case_id"],
        "execution_track_id": manifest["execution_track_id"],
        "status": status,
        "artifact_hashes": artifact_hashes,
        "native_artifact_hashes_by_stage": _stage_hashes_for_record(
            manifest=manifest,
            manifest_sha256=manifest_sha256,
            supplied_stage_hashes=supplied_stage_hashes,
            normalized_output_sha256=normalized_sha,
        ),
        "post_execution_attestation_sha256": artifact_hashes[
            "post_execution_attestation"
        ],
        "post_execution_action_log_sha256": artifact_hashes["manual_action_log"],
        "independent_evidence_artifact_hashes_by_role": independent_evidence_hashes,
        "independent_evidence_artifact_metadata_by_role": {
            role: {
                "sha256": independent_evidence_hashes[role],
                "byte_size": evidence_snapshots[role].byte_size,
                "media_type": {
                    ".png": "image/png", ".pdf": "application/pdf",
                    ".csv": "text/csv", ".json": "application/json",
                    ".xml": "application/xml", ".txt": "text/plain",
                }[path.suffix.lower()],
            }
            for role, path in sorted(independent_evidence_artifact_paths.items())
        },
        "raw_independent_evidence_embedded": False,
        "review_disposition": "pending",
        "partial_pilot_only": True,
        "full_profile_required_case_count": 45,
        "full_45_case_gate_satisfied": False,
        "compatibility_claim_exists": False,
    }
    if track_id == "saved_file_reopen_recalculate_stability":
        evidence_bundle["reopen_stability_evidence"] = {
            "pre_close_normalized_output_sha256": pre_close_normalized_sha,
            "post_recalculate_normalized_output_sha256": normalized_sha,
            "stability_difference_sha256": stability_difference_sha,
            "exact_normalized_stability": stability_difference[
                "exact_normalized_stability"
            ],
            "expected_oracle_used_for_stability_comparison": False,
        }
    evidence_path = output_dir / "evidence-bundle.json"
    write_canonical_json(evidence_path, evidence_bundle)

    native_stage_hashes = evidence_bundle["native_artifact_hashes_by_stage"]
    native_run_record = {
        "schema_version": "native-run-evidence-v0.1",
        "run_id": run_id,
        "preregistration_id": manifest["preregistration_id"],
        "preregistration_raw_sha256": manifest["preregistration_raw_sha256"],
        "comparison_profile_id": manifest["comparison_profile_id"],
        "comparison_profile_raw_sha256": manifest["comparison_profile_raw_sha256"],
        "native_system": NATIVE_SYSTEM,
        "case_id": manifest["case_id"],
        "execution_track_id": manifest["execution_track_id"],
        "status": status,
        "executed_at": executed_at,
        "operator_id": attestation["attested_by"],
        "independent_reviewer_id": manifest["independent_pre_execution_reviewed_by"],
        "environment_capture_sha256": artifact_hashes["environment_capture"],
        "fixture_raw_sha256": manifest["fixture_raw_sha256"],
        "case_realization_manifest_sha256": artifact_hashes["case_realisation_manifest"],
        "native_artifact_hashes_by_stage": native_stage_hashes,
        "normalized_output_sha256": artifact_hashes["normalized_output"],
        "field_difference_manifest_sha256": artifact_hashes["field_difference_manifest"],
        "manual_action_log_sha256": artifact_hashes["manual_action_log"],
        "evidence_bundle_sha256": raw_file_sha256(evidence_path),
        "failure_or_inconclusive_reason": reason,
        "review_disposition": "pending",
    }
    validate_native_run_record(repository_root=repository_root, record=native_run_record)
    run_record_path = output_dir / "native-run-record.json"
    write_canonical_json(run_record_path, native_run_record)
    run_record_sha = raw_file_sha256(run_record_path)

    product = manifest["captured_product_environment"]
    redacted_draft = {
        "schema_version": "native-redacted-evidence-manifest-draft-v0.1",
        "document_classification": "non_claimable_incomplete_draft",
        "intended_frozen_schema_ref": (
            "schemas/native-validation-preregistration.schema.json"
            "#/$defs/redactedEvidenceManifest"
        ),
        "conforms_to_frozen_redactedEvidenceManifest_schema": False,
        "must_not_be_committed_or_indexed_as_claim_evidence": True,
        "native_run_record_created": True,
        "native_run_record_candidate_status_only": True,
        "native_run_record_accepted_as_claim_evidence": False,
        "run_id": run_id,
        "case_id": manifest["case_id"],
        "native_system": NATIVE_SYSTEM,
        "product_edition_version_build": {
            key: product[key] for key in ("product_name", "edition", "version", "build")
        },
        "execution_track_id": manifest["execution_track_id"],
        "candidate_status": status,
        "run_record_sha256": run_record_sha,
        "artifact_index_sha256": raw_file_sha256(artifact_index_path),
        "review_disposition": "pending",
        "commit_as_claim_evidence": False,
        "claim_evidence_eligible": False,
        "repository_evidence_index_ingestion_permitted": False,
        "executed_pass_permitted": False,
        "required_frozen_redacted_manifest_fields_missing": [
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
        "required_frozen_redacted_manifest_fields_nonfinal": [
            "schema_version",
            "review_disposition",
        ],
        "frozen_schema_additional_properties_cleanup_required": True,
        "required_frozen_artifact_roles_missing": [
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
        "missing_before_claim": [
            "replace_draft_schema_version_with_frozen_schema_version",
            "remove_all_draft_only_additional_properties",
            "populate_every_missing_frozen_required_field",
            "populate_every_required_frozen_artifact_role",
            "schema_conforming_redacted_evidence_manifest",
            "controlled_locations_byte_sizes_media_types_restriction_flags_and_retention_owners",
            "independent_post_execution_review",
            "accepted_review_disposition",
            "complete_45_case_track_evidence",
        ],
        "full_45_case_gate_satisfied": False,
        "compatibility_claim_exists": False,
    }
    write_canonical_json(
        output_dir / "redacted-evidence-manifest-draft.json", redacted_draft
    )
    return NativeAnalysis(
        normalized_output=normalized,
        difference_manifest=difference,
        native_run_record=native_run_record,
        evidence_bundle=evidence_bundle,
        redacted_evidence_manifest_draft=redacted_draft,
        output_dir=output_dir,
    )


__all__ = [
    "MSPDI_NAMESPACE",
    "MSPDI_SAVE_VERSION",
    "NativeAnalysis",
    "NativeOutputError",
    "analyse_msproject_native_output",
    "compare_normalized_output",
    "normalize_mspdi_output",
    "validate_native_run_record",
]
