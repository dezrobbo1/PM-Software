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

from .headless import (
    CASE_IDS,
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


SEALED_DIRECTORY = PurePosixPath(
    "native-validation/pilot-kits/microsoft-project-relationship-v0.1/"
    "sealed-expected-normalized"
)


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
    path = repository_root.joinpath(*SEALED_DIRECTORY.parts, f"{case_id}.json")
    _regular_file(path, label="sealed normalized expectation")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ObservationFreezeError(
            "sealed normalized expectation is not valid UTF-8 JSON"
        ) from error
    if not isinstance(value, dict):
        raise ObservationFreezeError(
            "sealed normalized expectation must be an object"
        )
    return value


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
    cases: list[dict[str, Any]] = []
    for case_id in CASE_IDS:
        native = normalized_by_case[case_id]
        expected_activities, expected_finish = _expected_projection(
            expected_reader(run.repository_root, case_id)
        )
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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--log", type=Path)
    return parser


def main(arguments: list[str] | None = None) -> int:
    args = _parser().parse_args(arguments)
    journal = _Journal(args.state, args.log)
    journal.emit("start", {"run_id": args.run_id})
    try:
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
