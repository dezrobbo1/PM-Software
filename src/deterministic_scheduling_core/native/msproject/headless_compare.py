"""Oracle-capable comparison process for frozen Microsoft Project evidence.

This module is intentionally absent from the native construction worker's
import graph. It can read sealed normalized references only after the complete
twelve-case durable freeze gate has verified.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import sys
from typing import Any, Callable, Mapping

from deterministic_scheduling_core.provenance.canonical_json import canonical_bytes

from .freeze import (
    NativeEvidenceError,
    read_regular_file_snapshot,
)
from .headless import (
    CASE_IDS,
    PILOT_ID,
    TRACK_ID,
    ObservationFreezeError,
    RunWorkspace,
    _regular_file,
    create_run_workspace,
    durable_write_canonical_json,
    effective_stop_conditions,
    normalize_observation,
    verify_run_freeze_gate,
)
from .pilot import (
    COMPARISON_PROFILE_ID,
    FIXTURE_RAW_SHA256_BY_CASE_ID,
    FULL_PROFILE_CLAIM_ELIGIBLE_CASE_COUNT,
    PILOT_STATUS,
    PREREGISTRATION_ID,
    PREREGISTRATION_PATH,
    PREREGISTRATION_RAW_SHA256,
    PROFILE_PATH,
    PROFILE_RAW_SHA256,
)


SEALED_DIRECTORY = PurePosixPath(
    "native-validation/pilot-kits/microsoft-project-relationship-v0.1/"
    "sealed-expected-normalized"
)
COMPARATOR_MODULE = (
    "deterministic_scheduling_core.native.msproject.headless_compare"
)
COMPARATOR_SOURCE = PurePosixPath(
    "src/deterministic_scheduling_core/native/msproject/headless_compare.py"
)
MAX_ORACLE_JSON_BYTES = 1024 * 1024
MAX_COMPARATOR_SOURCE_BYTES = 1024 * 1024
ORACLE_PROVENANCE_SCHEMA = "headless-msproject-oracle-provenance-v0.1"
SEALED_EXPECTED_KEYS = frozenset(
    {
        "document_type",
        "schema_version",
        "pilot_id",
        "case_id",
        "status",
        "source_bindings",
        "seal_control",
        "coordinate_contract",
        "expected_normalized",
        "native_execution_status",
        "claim_boundary",
    }
)
SEALED_NORMALIZED_REQUIRED_KEYS = frozenset(
    {"reference_status", "activity_times", "project_finish"}
)
SEALED_NORMALIZED_OPTIONAL_KEYS = frozenset({"total_float", "free_float"})
_SEALED_RELEASE_CONTROL = {
    "separate_from_operator_and_pre_execution_reviewer_material": True,
    "full_oracle_fixture_binding_is_sealed": True,
    "operator_access_before_native_evidence_freeze": "prohibited",
    "release_condition": (
        "Release only to the controlled comparator after native artifacts, "
        "normalization, and their hashes are frozen."
    ),
}
_SEALED_COORDINATE_CONTRACT = {
    "origin": "2026-01-05T08:00:00+08:00",
    "unit": "hour",
    "timestamp_tolerance_seconds": 0,
    "rounding": "forbidden",
}
_SEALED_CLAIM_BOUNDARY = {
    "pilot_is_partial_profile_preparation": True,
    "pilot_case_count": len(CASE_IDS),
    "full_profile_claim_eligible_case_count": (
        FULL_PROFILE_CLAIM_ELIGIBLE_CASE_COUNT
    ),
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

try:
    _IMPORTED_COMPARATOR_SOURCE_PATH = Path(__file__).resolve(strict=True)
    _imported_comparator_source_snapshot = read_regular_file_snapshot(
        _IMPORTED_COMPARATOR_SOURCE_PATH,
        label="imported comparison source",
        max_bytes=MAX_COMPARATOR_SOURCE_BYTES,
    )
except (OSError, NativeEvidenceError) as error:
    raise ImportError("comparison source identity cannot be captured at import") from error
_IMPORTED_COMPARATOR_SOURCE_BYTES = _imported_comparator_source_snapshot.data
_IMPORTED_COMPARATOR_SOURCE_SHA256 = _imported_comparator_source_snapshot.sha256


def _exact_json_value(value: Any, expected: Any) -> bool:
    """Compare JSON values without Python's bool/integer equality aliases."""

    if type(value) is not type(expected):
        return False
    if isinstance(expected, dict):
        return set(value) == set(expected) and all(
            _exact_json_value(value[key], expected[key]) for key in expected
        )
    if isinstance(expected, list):
        return len(value) == len(expected) and all(
            _exact_json_value(item, expected_item)
            for item, expected_item in zip(value, expected)
        )
    return value == expected


class _DuplicateJsonKeyError(ValueError):
    pass


def _strict_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise _DuplicateJsonKeyError(f"duplicate JSON key {key!r}")
        value[key] = item
    return value


def _parse_fixture_json(data: bytes, *, case_id: str) -> dict[str, Any]:
    """Parse authenticated fixture bytes into the canonical JSON value domain."""

    try:
        value = json.loads(
            data.decode("utf-8"), object_pairs_hook=_strict_json_object
        )
        if not isinstance(value, dict):
            raise TypeError("fixture root is not an object")
        # The raw digest authenticates the reviewed on-disk serialization. This
        # additional conversion rejects values (for example floats) outside the
        # canonical JSON domain without imposing a new whitespace serialization.
        canonical_bytes(value)
    except (
        UnicodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
    ) as error:
        raise ObservationFreezeError(
            f"bound full fixture {case_id} is not strict canonical-domain JSON"
        ) from error
    return value


def _sealed_source_bindings(case_id: str) -> dict[str, Any]:
    fixture_path = f"benchmarks/semantic/cases/{case_id.lower()}.json"
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
        "fixture": {
            "case_id": case_id,
            "path": fixture_path,
            "relative_path": fixture_path,
            "raw_sha256": FIXTURE_RAW_SHA256_BY_CASE_ID[case_id],
        },
    }


def _valid_expected_normalized(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if (
        not SEALED_NORMALIZED_REQUIRED_KEYS.issubset(value)
        or not set(value).issubset(
            SEALED_NORMALIZED_REQUIRED_KEYS | SEALED_NORMALIZED_OPTIONAL_KEYS
        )
        or not isinstance(value["reference_status"], str)
        or not value["reference_status"]
    ):
        return False

    activity_times = value["activity_times"]
    if not isinstance(activity_times, dict) or set(activity_times) != {"A", "B"}:
        return False
    allowed_time_fields = {"start", "remaining_start", "finish"}
    for coordinates in activity_times.values():
        if (
            not isinstance(coordinates, dict)
            or not {"start", "finish"}.issubset(coordinates)
            or not set(coordinates).issubset(allowed_time_fields)
            or any(
                not isinstance(coordinate, int) or isinstance(coordinate, bool)
                for coordinate in coordinates.values()
            )
        ):
            return False
    project_finish = value["project_finish"]
    if not isinstance(project_finish, int) or isinstance(project_finish, bool):
        return False
    for field in SEALED_NORMALIZED_OPTIONAL_KEYS & set(value):
        floats = value[field]
        if (
            not isinstance(floats, dict)
            or set(floats) != {"A", "B"}
            or any(
                not isinstance(coordinate, int) or isinstance(coordinate, bool)
                for coordinate in floats.values()
            )
        ):
            return False
    return True


def _valid_sealed_envelope(value: Mapping[str, Any], case_id: str) -> bool:
    if case_id not in FIXTURE_RAW_SHA256_BY_CASE_ID:
        return False
    return (
        set(value) == SEALED_EXPECTED_KEYS
        and value.get("document_type")
        == "microsoft_project_sealed_expected_normalized"
        and value.get("schema_version")
        == "microsoft-project-sealed-expected-v0.1"
        and value.get("pilot_id") == PILOT_ID
        and value.get("case_id") == case_id
        and value.get("status") == PILOT_STATUS
        and value.get("native_execution_status") == "not_executed"
        and _exact_json_value(
            value.get("source_bindings"), _sealed_source_bindings(case_id)
        )
        and _exact_json_value(value.get("seal_control"), _SEALED_RELEASE_CONTROL)
        and _exact_json_value(
            value.get("coordinate_contract"), _SEALED_COORDINATE_CONTRACT
        )
        and _valid_expected_normalized(value.get("expected_normalized"))
        and _exact_json_value(value.get("claim_boundary"), _SEALED_CLAIM_BOUNDARY)
    )


def _bound_fixture_identity(
    repository_root: Path,
    sealed_expected: Mapping[str, Any],
    case_id: str,
) -> dict[str, Any]:
    """Verify the sealed projection against one stable full-fixture snapshot."""

    fixture_binding = sealed_expected["source_bindings"]["fixture"]
    relative_path = fixture_binding["relative_path"]
    fixture_path = repository_root.joinpath(*PurePosixPath(relative_path).parts)
    try:
        snapshot = read_regular_file_snapshot(
            fixture_path,
            label=f"bound full fixture {case_id}",
            max_bytes=MAX_ORACLE_JSON_BYTES,
        )
        if snapshot.sha256 != FIXTURE_RAW_SHA256_BY_CASE_ID[case_id]:
            raise ObservationFreezeError(
                "bound full fixture digest does not match the known case identity"
            )
        fixture = _parse_fixture_json(snapshot.data, case_id=case_id)
    except NativeEvidenceError as error:
        raise ObservationFreezeError(
            "bound full fixture is not a stable bounded regular-file snapshot"
        ) from error

    fixture_expected = fixture.get("expected")
    if fixture.get("case_id") != case_id or not isinstance(
        fixture_expected, Mapping
    ):
        raise ObservationFreezeError(
            "bound full fixture identity or expected mapping is invalid"
        )
    required_fields = ("reference_status", "activity_times", "project_finish")
    if any(field not in fixture_expected for field in required_fields):
        raise ObservationFreezeError(
            "bound full fixture expected projection is incomplete"
        )
    fixture_projection = {
        field: fixture_expected[field] for field in required_fields
    }
    for field in ("total_float", "free_float"):
        if field in fixture_expected:
            fixture_projection[field] = fixture_expected[field]
    if not _exact_json_value(
        sealed_expected["expected_normalized"], fixture_projection
    ):
        raise ObservationFreezeError(
            "sealed normalized expectation differs from its bound full fixture"
        )
    return {
        "case_id": case_id,
        "relative_path": relative_path,
        "sha256": snapshot.sha256,
        "byte_size": snapshot.byte_size,
        "source_kind": "bound_fixture_byte_snapshot",
    }


def _expected_projection(
    value: Mapping[str, Any],
) -> tuple[dict[str, dict[str, int]], int]:
    candidate: Mapping[str, Any] = value
    for key in ("expected_normalized", "expected", "normalized"):
        nested = candidate.get(key)
        if isinstance(nested, Mapping):
            candidate = nested
            break
    raw_activities = candidate.get("activities", candidate.get("activity_times"))
    project_finish = candidate.get("project_finish")
    activities: dict[str, dict[str, int]] = {}
    if isinstance(raw_activities, Mapping):
        for activity_id, coordinates in raw_activities.items():
            if not isinstance(activity_id, str) or not isinstance(coordinates, Mapping):
                raise ObservationFreezeError(
                    "sealed normalized activity entry is malformed"
                )
            start = coordinates.get("start")
            finish = coordinates.get("finish")
            if (
                not isinstance(start, int)
                or isinstance(start, bool)
                or not isinstance(finish, int)
                or isinstance(finish, bool)
            ):
                raise ObservationFreezeError(
                    "sealed normalized activity coordinates must be integers"
                )
            activities[activity_id] = {"start": start, "finish": finish}
    elif isinstance(raw_activities, list):
        for item in raw_activities:
            if not isinstance(item, Mapping):
                raise ObservationFreezeError(
                    "sealed normalized activity entry is malformed"
                )
            activity_id = item.get("activity_id", item.get("id"))
            start = item.get("start")
            finish = item.get("finish")
            if (
                not isinstance(activity_id, str)
                or not isinstance(start, int)
                or isinstance(start, bool)
                or not isinstance(finish, int)
                or isinstance(finish, bool)
                or activity_id in activities
            ):
                raise ObservationFreezeError(
                    "sealed normalized activity entry is malformed or duplicated"
                )
            activities[activity_id] = {"start": start, "finish": finish}
    if (
        set(activities) != {"A", "B"}
        or not isinstance(project_finish, int)
        or isinstance(project_finish, bool)
    ):
        raise ObservationFreezeError(
            "sealed normalized expectation must contain exactly A, B and integer project_finish"
        )
    return activities, project_finish


def _default_expected_reader(
    repository_root: Path, case_id: str
) -> Mapping[str, Any]:
    value, _identity = _default_expected_snapshot(repository_root, case_id)
    return value


def _default_expected_snapshot(
    repository_root: Path, case_id: str
) -> tuple[Mapping[str, Any], dict[str, Any]]:
    """Read, hash and parse one exact sealed-reference byte snapshot."""

    relative_path = SEALED_DIRECTORY / f"{case_id}.json"
    path = repository_root.joinpath(*relative_path.parts)
    _regular_file(path, label="sealed normalized expectation")
    try:
        expected_bytes = path.read_bytes()
        if len(expected_bytes) > 1024 * 1024:
            raise ObservationFreezeError(
                "sealed normalized expectation exceeds the bounded 1 MiB limit"
            )
        value = json.loads(expected_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ObservationFreezeError(
            "sealed normalized expectation is not valid UTF-8 JSON"
        ) from error
    if not isinstance(value, dict):
        raise ObservationFreezeError(
            "sealed normalized expectation must be an object"
        )
    if not _valid_sealed_envelope(value, case_id):
        raise ObservationFreezeError(
            "sealed normalized expectation schema or identity does not match the requested case"
        )
    fixture_identity = _bound_fixture_identity(repository_root, value, case_id)
    return value, {
        "case_id": case_id,
        "relative_path": relative_path.as_posix(),
        "sha256": hashlib.sha256(expected_bytes).hexdigest(),
        "source_kind": "sealed_reference_byte_snapshot",
        "bound_fixture": fixture_identity,
    }


def _comparator_source_identity(
    repository_root: Path, *, require_repository_source: bool
) -> dict[str, str]:
    """Bind provenance to import-time bytes and reject later source mutation."""

    repository_path = repository_root.joinpath(*COMPARATOR_SOURCE.parts)
    if require_repository_source:
        try:
            if (
                repository_path.resolve(strict=True)
                != _IMPORTED_COMPARATOR_SOURCE_PATH
            ):
                raise ObservationFreezeError(
                    "executed comparator is not the checked-out repository source"
                )
        except OSError as error:
            raise ObservationFreezeError(
                "checked-out comparison source cannot be resolved"
            ) from error
        path = repository_path
    else:
        # Injected readers are a parser/test seam, never a production cache.
        path = _IMPORTED_COMPARATOR_SOURCE_PATH
    try:
        current = read_regular_file_snapshot(
            path,
            label="current comparison source",
            max_bytes=MAX_COMPARATOR_SOURCE_BYTES,
        )
    except NativeEvidenceError as error:
        raise ObservationFreezeError(
            "comparison source cannot be read as a stable bounded snapshot"
        ) from error
    if (
        current.sha256 != _IMPORTED_COMPARATOR_SOURCE_SHA256
        or current.data != _IMPORTED_COMPARATOR_SOURCE_BYTES
    ):
        raise ObservationFreezeError(
            "comparison source changed after its import-time identity was captured"
        )
    return {
        "module": COMPARATOR_MODULE,
        "relative_path": COMPARATOR_SOURCE.as_posix(),
        "sha256": _IMPORTED_COMPARATOR_SOURCE_SHA256,
    }


def compare_frozen_observations(
    run: RunWorkspace,
    *,
    expected_reader: Callable[[Path, str], Mapping[str, Any]] = _default_expected_reader,
) -> dict[str, Any]:
    """Compare only after the complete durable twelve-case gate verifies."""

    freeze_index = verify_run_freeze_gate(run, write_index=False)
    freezes = freeze_index.get("case_freezes")
    if not isinstance(freezes, list) or [
        item.get("case_id") if isinstance(item, Mapping) else None
        for item in freezes
    ] != list(CASE_IDS):
        raise ObservationFreezeError(
            "oracle gate remains closed: freeze index has invalid case identity"
        )
    frozen_digests = {
        str(item["case_id"]): item.get("native_observation_sha256")
        for item in freezes
    }
    observations: dict[str, Mapping[str, Any]] = {}
    # Defense in depth: scan every frozen observation for retained stop
    # evidence before the first sealed-reference read. A per-case scan inside
    # the comparison loop would reveal earlier references before a later stop.
    for case_id in CASE_IDS:
        observation_path = run.path / "cases" / case_id / "native-observation.json"
        try:
            _regular_file(observation_path, label=f"frozen observation {case_id}")
            # Hash and parse the same bounded byte snapshot.  Reopening the
            # path after the freeze gate would create a gate-to-oracle TOCTOU
            # window in which unfrozen bytes could be normalized before the
            # first sealed-reference read.
            observation_bytes = observation_path.read_bytes()
            digest = hashlib.sha256(observation_bytes).hexdigest()
            expected_digest = frozen_digests.get(case_id)
            if not isinstance(expected_digest, str) or digest != expected_digest:
                raise ObservationFreezeError(
                    f"oracle gate remains closed: {case_id} changed after freeze verification"
                )
            observation = json.loads(observation_bytes.decode("utf-8"))
        except ObservationFreezeError:
            raise
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ObservationFreezeError(
                f"oracle gate remains closed: malformed observation {case_id}"
            ) from error
        if (
            not isinstance(observation, Mapping)
            or observation.get("case_id") != case_id
            or observation.get("characterisation_label") != TRACK_ID
        ):
            raise ObservationFreezeError(
                f"oracle gate remains closed: {case_id} observation is malformed"
            )
        try:
            conditions = effective_stop_conditions(observation)
        except ObservationFreezeError as error:
            raise ObservationFreezeError(
                f"oracle gate remains closed: {case_id} stop evidence is malformed"
            ) from error
        if conditions:
            raise ObservationFreezeError(
                f"oracle gate remains closed: {case_id} contains stop conditions: {conditions}"
            )
        observations[case_id] = observation
    normalized_by_case: dict[str, dict[str, Any]] = {}
    for case_id in CASE_IDS:
        # Complete every fallible native normalization before the first oracle
        # read, so a malformed later case cannot reveal any earlier reference.
        normalized_by_case[case_id] = normalize_observation(observations[case_id])
    # The source identity and sealed snapshots are intentionally acquired only
    # after every frozen native observation has passed stop validation and
    # normalization.  Native construction never imports this module.
    comparator_identity = _comparator_source_identity(
        run.repository_root,
        require_repository_source=expected_reader is _default_expected_reader,
    )
    cases: list[dict[str, Any]] = []
    reference_identities: list[dict[str, Any]] = []
    for case_id in CASE_IDS:
        native = normalized_by_case[case_id]
        if expected_reader is _default_expected_reader:
            expected_value, reference_identity = _default_expected_snapshot(
                run.repository_root, case_id
            )
        else:
            expected_value = expected_reader(run.repository_root, case_id)
            reference_identity = {
                "case_id": case_id,
                "relative_path": (SEALED_DIRECTORY / f"{case_id}.json").as_posix(),
                "sha256": hashlib.sha256(canonical_bytes(expected_value)).hexdigest(),
                "source_kind": "injected_mapping_canonical_json",
                "bound_fixture": None,
            }
        reference_identities.append(reference_identity)
        projection_source = (
            expected_value["expected_normalized"]
            if expected_reader is _default_expected_reader
            else expected_value
        )
        expected_activities, expected_finish = _expected_projection(projection_source)
        fields: list[dict[str, Any]] = []
        for activity_id in sorted(set(expected_activities) | set(native["activities"])):
            for coordinate in ("start", "finish"):
                expected_value = expected_activities.get(activity_id, {}).get(coordinate)
                native_value = native["activities"].get(activity_id, {}).get(coordinate)
                if expected_value is None:
                    classification = "extra_unclaimed_field"
                elif native_value is None:
                    classification = "missing_claim_field"
                elif native_value == expected_value:
                    classification = "exact_match"
                else:
                    classification = "claim_field_mismatch"
                fields.append(
                    {
                        "field": f"activities.{activity_id}.{coordinate}",
                        "native": native_value,
                        "reference": expected_value,
                        "classification": classification,
                    }
                )
        fields.append(
            {
                "field": "project_finish",
                "native": native["project_finish"],
                "reference": expected_finish,
                "classification": (
                    "exact_match"
                    if native["project_finish"] == expected_finish
                    else "claim_field_mismatch"
                ),
            }
        )
        status = (
            "characterisation_exact"
            if all(item["classification"] == "exact_match" for item in fields)
            else "characterisation_mismatch"
        )
        cases.append(
            {
                "case_id": case_id,
                "status": status,
                "fields": fields,
                "normalized_native": native,
            }
        )
    return {
        "schema_version": "headless-msproject-comparison-v0.1",
        "characterisation_label": TRACK_ID,
        "run_id": run.run_id,
        "manual_native_semantic_parity_status_emitted": False,
        "oracle_provenance": {
            "schema_version": ORACLE_PROVENANCE_SCHEMA,
            "comparator": comparator_identity,
            "sealed_references": reference_identities,
        },
        "cases": cases,
    }


class _Journal:
    def __init__(self, state_path: Path | None, log_path: Path | None):
        self.state_path = state_path
        self.log_path = log_path
        self.sequence = 0

    def emit(self, phase: str, details: Mapping[str, Any]) -> None:
        self.sequence += 1
        event = {
            "sequence": self.sequence,
            "worker_pid": os.getpid(),
            "stage": "comparison",
            "phase": phase,
            "details": dict(details),
        }
        data = canonical_bytes(event) + b"\n"
        if self.log_path is not None:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("ab") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        if self.state_path is not None:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.state_path.with_name(
                f"{self.state_path.name}.{os.getpid()}.tmp"
            )
            with temporary.open("xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.state_path)


def _require_parent_comparator_identity(expected_sha256: str) -> None:
    if expected_sha256 != _IMPORTED_COMPARATOR_SOURCE_SHA256:
        raise ObservationFreezeError(
            "imported comparator source differs from the parent prelaunch snapshot"
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--expected-comparator-sha256", required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--log", type=Path)
    return parser


def main(arguments: list[str] | None = None) -> int:
    args = _parser().parse_args(arguments)
    journal = _Journal(args.state, args.log)
    journal.emit("start", {"run_id": args.run_id})
    try:
        _require_parent_comparator_identity(args.expected_comparator_sha256)
        run = create_run_workspace(
            args.repository_root.resolve(), args.run_id, resume=True
        )
        result = compare_frozen_observations(run)
        digest = durable_write_canonical_json(args.result, result)
    except BaseException as error:
        journal.emit(
            "error",
            {"error_type": type(error).__name__, "error": str(error)},
        )
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 1
    journal.emit("complete", {"result_sha256": digest})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
