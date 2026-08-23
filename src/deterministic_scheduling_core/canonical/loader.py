from __future__ import annotations

import copy
import csv
import json
import unicodedata
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from deterministic_scheduling_core import SEMANTIC_PROFILE
from deterministic_scheduling_core.errors import CanonicalValidationError
from deterministic_scheduling_core.provenance.canonical_json import sha256_digest

from .frozen_suite import EXPECTED_CASE_IDS, EXPECTED_FILENAME_BY_ID, EXPECTED_ID_BY_FILENAME
from .model import LoadedCase


def _duplicates(values: Iterable[Any]) -> list[Any]:
    seen: set[Any] = set()
    duplicates: set[Any] = set()
    for value in values:
        identity = unicodedata.normalize("NFC", value) if isinstance(value, str) else value
        if identity in seen:
            duplicates.add(identity)
        seen.add(identity)
    return sorted(duplicates, key=str)


def _sort_entities(items: list[dict[str, Any]], key: str = "id") -> None:
    items.sort(
        key=lambda item: unicodedata.normalize("NFC", str(item.get(key, "")))
    )


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    normalised_keys: set[str] = set()
    for key, value in pairs:
        normalised_key = unicodedata.normalize("NFC", key)
        if key in result or normalised_key in normalised_keys:
            raise ValueError(f"duplicate JSON object key after NFC normalisation: {key!r}")
        result[key] = value
        normalised_keys.add(normalised_key)
    return result


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_strict_object)


def _canonicalise_schedule(schedule: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(schedule)
    for key in ("wbs", "calendars", "resources", "activities", "relationships", "operational_constraints"):
        values = result.get(key)
        if isinstance(values, list):
            _sort_entities(values)
    for activity in result.get("activities", []):
        for key, stable_key in (
            ("constraints", "id"),
            ("assignments", "resource_id"),
            ("eligible_modes", "id"),
        ):
            values = activity.get(key)
            if isinstance(values, list):
                _sort_entities(values, stable_key)
        for mode in activity.get("eligible_modes", []):
            if isinstance(mode.get("assignments"), list):
                _sort_entities(mode["assignments"], "resource_id")
            if isinstance(mode.get("required_skills"), list):
                mode["required_skills"].sort()
        if isinstance(activity.get("assignments"), list):
            _sort_entities(activity["assignments"], "resource_id")
    for resource in result.get("resources", []):
        for key in ("skills", "certifications"):
            if isinstance(resource.get(key), list):
                resource[key].sort(key=lambda value: unicodedata.normalize("NFC", value))
    for constraint in result.get("operational_constraints", []):
        for key in ("activity_ids", "resource_ids"):
            if isinstance(constraint.get(key), list):
                constraint[key].sort(key=lambda value: unicodedata.normalize("NFC", value))
    governance = result.get("governance")
    if isinstance(governance, dict):
        if isinstance(governance.get("evidence"), list):
            _sort_entities(governance["evidence"])
        if isinstance(governance.get("rejected_alternative_ids"), list):
            governance["rejected_alternative_ids"].sort(
                key=lambda value: unicodedata.normalize("NFC", value)
            )
    for key in ("baseline", "approved_forecast", "proposed_scenario"):
        state = result.get(key)
        if isinstance(state, dict) and isinstance(state.get("activity_states"), list):
            _sort_entities(state["activity_states"], "activity_id")
            for activity_state in state["activity_states"]:
                if isinstance(activity_state.get("assignments"), list):
                    _sort_entities(activity_state["assignments"], "resource_id")
            if isinstance(state.get("alternative_scenario_ids"), list):
                state["alternative_scenario_ids"].sort(
                    key=lambda value: unicodedata.normalize("NFC", value)
                )
            state_governance = state.get("governance")
            if isinstance(state_governance, dict):
                if isinstance(state_governance.get("evidence"), list):
                    _sort_entities(state_governance["evidence"])
                if isinstance(state_governance.get("rejected_alternative_ids"), list):
                    state_governance["rejected_alternative_ids"].sort(
                        key=lambda value: unicodedata.normalize("NFC", value)
                    )
    return result


def _canonicalise_case(document: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(document)
    result["schedule"] = _canonicalise_schedule(result["schedule"])
    return result


def _working_units(intervals: list[list[int]]) -> set[int]:
    return {unit for start, finish in intervals for unit in range(start, finish)}


def _intersect_units(left: set[int], right: set[int]) -> set[int]:
    return left & right


def _finish_from_units(start: int, duration: int, units: set[int], horizon: int) -> int | None:
    if duration == 0:
        return start if start in units else None
    if start not in units:
        return None
    remaining = duration
    for unit in range(start, horizon):
        if unit in units:
            remaining -= 1
            if remaining == 0:
                return unit + 1
    return None


class CanonicalLoader:
    """Schema and reference-resolving loader for canonical Phase 1 inputs."""

    def __init__(self, repository_root: Path):
        self.root = repository_root.resolve()
        schema_dir = self.root / "schemas"
        self.canonical_schema = json.loads(
            (schema_dir / "canonical-schedule.schema.json").read_text(encoding="utf-8")
        )
        self.case_schema = json.loads(
            (schema_dir / "semantic-test-case.schema.json").read_text(encoding="utf-8")
        )
        registry = Registry().with_resource(
            self.canonical_schema["$id"], Resource.from_contents(self.canonical_schema)
        )
        self.schedule_validator = Draft202012Validator(
            self.canonical_schema, format_checker=FormatChecker()
        )
        self.case_validator = Draft202012Validator(
            self.case_schema, registry=registry, format_checker=FormatChecker()
        )

    @staticmethod
    def _schema_errors(validator: Draft202012Validator, value: Any) -> list[str]:
        errors: list[str] = []
        for error in sorted(
            validator.iter_errors(value),
            key=lambda item: tuple(str(part) for part in item.absolute_path),
        ):
            location = "/".join(str(part) for part in error.absolute_path) or "<root>"
            errors.append(f"schema {location}: {error.message}")
        return errors

    def load_schedule(self, path: Path) -> dict[str, Any]:
        try:
            document = _load_json(path)
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
            raise CanonicalValidationError([f"{path.name}: {exc}"]) from exc
        errors = self._schema_errors(self.schedule_validator, document)
        errors.extend(self._cross_validate_schedule(document, path.name))
        if errors:
            raise CanonicalValidationError(errors)
        return _canonicalise_schedule(document)

    def load_case(self, path: Path) -> LoadedCase:
        try:
            document = _load_json(path)
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
            raise CanonicalValidationError([f"{path.name}: {exc}"]) from exc
        errors = self._schema_errors(self.case_validator, document)
        if isinstance(document, dict) and isinstance(document.get("schedule"), dict):
            errors.extend(self._cross_validate_schedule(document["schedule"], path.name))
            case_id = document.get("case_id")
            if document["schedule"].get("schedule_id") != case_id:
                errors.append(f"{path.name}: schedule_id must equal case_id")
            expected_times = document.get("expected", {}).get("activity_times", {})
            activity_ids = {
                activity.get("id") for activity in document["schedule"].get("activities", [])
            }
            if isinstance(expected_times, dict) and set(expected_times) != activity_ids:
                errors.append(
                    f"{path.name}: expected activity_times must exactly cover schedule activities"
                )
        if errors:
            raise CanonicalValidationError(errors)
        normalised = _canonicalise_case(document)
        schedule = normalised["schedule"]
        return LoadedCase(
            case_id=normalised["case_id"],
            path=path.resolve(),
            document=normalised,
            schedule=schedule,
            expected=normalised["expected"],
            input_hash=sha256_digest(schedule),
            fixture_hash=sha256_digest(normalised),
        )

    def discover_frozen_suite(
        self,
        cases_dir: Path | None = None,
        catalogue_path: Path | None = None,
    ) -> list[LoadedCase]:
        cases_dir = (cases_dir or self.root / "benchmarks" / "semantic" / "cases").resolve()
        catalogue_path = (
            catalogue_path or self.root / "benchmarks" / "semantic" / "catalogue.csv"
        ).resolve()
        discovered = {path.name: path for path in cases_dir.glob("*.json")}
        expected_names = set(EXPECTED_ID_BY_FILENAME)
        errors: list[str] = []
        missing = sorted(expected_names - set(discovered))
        additional = sorted(set(discovered) - expected_names)
        if missing:
            errors.append(f"frozen suite is missing filenames {missing}")
        if additional:
            errors.append(f"frozen suite contains additional filenames {additional}")
        if errors:
            raise CanonicalValidationError(errors)

        cases: list[LoadedCase] = []
        for case_id in EXPECTED_CASE_IDS:
            filename = EXPECTED_FILENAME_BY_ID[case_id]
            loaded = self.load_case(discovered[filename])
            if loaded.case_id != case_id:
                errors.append(
                    f"{filename}: expected frozen case_id {case_id}, found {loaded.case_id}"
                )
            cases.append(loaded)
        for duplicate in _duplicates(case.case_id for case in cases):
            errors.append(f"frozen suite contains duplicate case_id {duplicate}")

        try:
            with catalogue_path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
        except OSError as exc:
            errors.append(f"catalogue cannot be read: {exc}")
            rows = []
        catalogue_ids = [row.get("case_id") for row in rows]
        if catalogue_ids != list(EXPECTED_CASE_IDS):
            errors.append("catalogue case order does not match the frozen identity sequence")
        by_id = {case.case_id: case for case in cases}
        for row in rows:
            case = by_id.get(str(row.get("case_id")))
            if case is None:
                continue
            expected = case.expected
            expected_finish = expected.get("project_finish")
            fields = {
                "category": case.document["category"],
                "title": case.document["title"],
                "reference_status": expected.get("reference_status"),
                "project_finish": "" if expected_finish is None else str(expected_finish),
                "p6_validation": case.document["native_validation"].get("p6"),
                "microsoft_project_validation": case.document["native_validation"].get(
                    "microsoft_project"
                ),
            }
            for field, expected_value in fields.items():
                if row.get(field) != expected_value:
                    errors.append(
                        f"catalogue {case.case_id} field {field} does not match its fixture"
                    )
        if errors:
            raise CanonicalValidationError(errors)
        return cases

    def _cross_validate_schedule(self, schedule: dict[str, Any], context: str) -> list[str]:
        errors: list[str] = []
        if schedule.get("schema_version") != "0.1.3":
            errors.append(f"{context}: unsupported canonical schema version")
        if schedule.get("semantic_profile") != SEMANTIC_PROFILE:
            errors.append(f"{context}: semantic profile must be {SEMANTIC_PROFILE}")
        horizon = schedule.get("time_axis", {}).get("horizon")
        if not isinstance(horizon, int) or isinstance(horizon, bool):
            return errors

        entity_groups = {
            "WBS": schedule.get("wbs", []),
            "calendar": schedule.get("calendars", []),
            "resource": schedule.get("resources", []),
            "activity": schedule.get("activities", []),
            "relationship": schedule.get("relationships", []),
            "operational constraint": schedule.get("operational_constraints", []),
        }
        for label, entities in entity_groups.items():
            for duplicate in _duplicates(item.get("id") for item in entities):
                errors.append(f"{context}: duplicate {label} ID {duplicate!r}")

        calendars = {
            calendar.get("id"): calendar for calendar in schedule.get("calendars", [])
        }
        resources = {
            resource.get("id"): resource for resource in schedule.get("resources", [])
        }
        activities = {
            activity.get("id"): activity for activity in schedule.get("activities", [])
        }
        wbs = {node.get("id"): node for node in schedule.get("wbs", [])}

        for calendar_id, calendar in calendars.items():
            previous_finish: int | None = None
            for index, interval in enumerate(calendar.get("working_intervals", [])):
                if not (
                    isinstance(interval, list)
                    and len(interval) == 2
                    and all(isinstance(value, int) and not isinstance(value, bool) for value in interval)
                ):
                    continue
                start, finish = interval
                if start < 0 or finish > horizon or start >= finish:
                    errors.append(
                        f"{context}: calendar {calendar_id} interval {index} is outside the valid horizon"
                    )
                if previous_finish is not None and start < previous_finish:
                    errors.append(
                        f"{context}: calendar {calendar_id} intervals overlap or are unordered"
                    )
                previous_finish = finish

        parent_by_id = {node_id: node.get("parent_id") for node_id, node in wbs.items()}
        for node_id, parent_id in parent_by_id.items():
            if parent_id is not None and parent_id not in wbs:
                errors.append(f"{context}: WBS {node_id} references unknown parent {parent_id}")
        for start in sorted(str(node_id) for node_id in parent_by_id):
            seen: set[str] = set()
            current: str | None = start
            while current is not None and current in parent_by_id:
                if current in seen:
                    errors.append(f"{context}: WBS hierarchy contains a cycle through {current}")
                    break
                seen.add(current)
                parent = parent_by_id[current]
                current = parent if isinstance(parent, str) else None

        constraint_ids: list[str] = []
        for activity_id, activity in activities.items():
            if activity.get("calendar_id") not in calendars:
                errors.append(
                    f"{context}: activity {activity_id} references unknown calendar {activity.get('calendar_id')}"
                )
            if activity.get("wbs_id") is not None and activity.get("wbs_id") not in wbs:
                errors.append(
                    f"{context}: activity {activity_id} references unknown WBS {activity.get('wbs_id')}"
                )
            for constraint in activity.get("constraints", []):
                if isinstance(constraint.get("id"), str):
                    constraint_ids.append(constraint["id"])
            self._validate_assignments(
                activity.get("assignments", []), activity_id, resources, errors, context
            )
            mode_ids = [mode.get("id") for mode in activity.get("eligible_modes", [])]
            for duplicate in _duplicates(mode_ids):
                errors.append(f"{context}: activity {activity_id} has duplicate mode {duplicate}")
            for mode in activity.get("eligible_modes", []):
                calendar_id = mode.get("calendar_id")
                if calendar_id is not None and calendar_id not in calendars:
                    errors.append(
                        f"{context}: activity {activity_id} mode {mode.get('id')} references unknown calendar {calendar_id}"
                    )
                self._validate_assignments(
                    mode.get("assignments", []), activity_id, resources, errors, context
                )
            actual_start = activity.get("actual_start")
            actual_finish = activity.get("actual_finish")
            if isinstance(actual_start, int) and not isinstance(actual_start, bool):
                status_time = schedule.get("project", {}).get("status_time")
                if actual_finish is None and not isinstance(status_time, int):
                    errors.append(
                        f"{context}: in-progress activity {activity_id} requires integer status_time"
                    )
                if isinstance(status_time, int) and actual_start > status_time:
                    errors.append(
                        f"{context}: activity {activity_id} actual_start exceeds status_time"
                    )
            if isinstance(actual_finish, int) and isinstance(actual_start, int):
                if actual_finish < actual_start:
                    errors.append(
                        f"{context}: activity {activity_id} actual_finish precedes actual_start"
                    )
        for duplicate in _duplicates(constraint_ids):
            errors.append(f"{context}: duplicate constraint ID {duplicate}")

        for resource_id, resource in resources.items():
            if resource.get("calendar_id") not in calendars:
                errors.append(
                    f"{context}: resource {resource_id} references unknown calendar {resource.get('calendar_id')}"
                )

        for relationship_id, relationship in {
            item.get("id"): item for item in schedule.get("relationships", [])
        }.items():
            for field in ("predecessor_id", "successor_id"):
                if relationship.get(field) not in activities:
                    errors.append(
                        f"{context}: relationship {relationship_id} {field} is unresolved"
                    )
            lag_calendar = relationship.get("lag_calendar")
            if lag_calendar is not None and lag_calendar not in calendars:
                errors.append(
                    f"{context}: relationship {relationship_id} references unknown lag calendar {lag_calendar}"
                )

        for constraint in schedule.get("operational_constraints", []):
            constraint_id = constraint.get("id")
            for activity_id in constraint.get("activity_ids", []):
                if activity_id not in activities:
                    errors.append(
                        f"{context}: operational constraint {constraint_id} references unknown activity {activity_id}"
                    )
            for resource_id in constraint.get("resource_ids", []):
                if resource_id not in resources:
                    errors.append(
                        f"{context}: operational constraint {constraint_id} references unknown resource {resource_id}"
                    )

        for state_name in ("baseline", "approved_forecast", "proposed_scenario"):
            state = schedule.get(state_name)
            if not isinstance(state, dict):
                continue
            states = state.get("activity_states", [])
            state_ids = [item.get("activity_id") for item in states]
            for duplicate in _duplicates(state_ids):
                errors.append(f"{context}: {state_name} duplicates activity {duplicate}")
            if state_name in {"approved_forecast", "proposed_scenario"} and set(state_ids) != set(activities):
                errors.append(
                    f"{context}: supplied {state_name} must exactly cover all activities"
                )
            for activity_state in states:
                self._validate_activity_state(
                    activity_state,
                    state_name,
                    activities,
                    resources,
                    calendars,
                    horizon,
                    errors,
                    context,
                )
        return errors

    @staticmethod
    def _validate_assignments(
        assignments: list[dict[str, Any]],
        activity_id: Any,
        resources: dict[Any, dict[str, Any]],
        errors: list[str],
        context: str,
    ) -> None:
        resource_ids = [assignment.get("resource_id") for assignment in assignments]
        for duplicate in _duplicates(resource_ids):
            errors.append(
                f"{context}: activity {activity_id} has duplicate assignment for {duplicate}"
            )
        for resource_id in resource_ids:
            if resource_id not in resources:
                errors.append(
                    f"{context}: activity {activity_id} references unknown resource {resource_id}"
                )

    @staticmethod
    def _validate_activity_state(
        state: dict[str, Any],
        state_name: str,
        activities: dict[Any, dict[str, Any]],
        resources: dict[Any, dict[str, Any]],
        calendars: dict[Any, dict[str, Any]],
        horizon: int,
        errors: list[str],
        context: str,
    ) -> None:
        activity_id = state.get("activity_id")
        activity = activities.get(activity_id)
        if activity is None:
            errors.append(f"{context}: {state_name} references unknown activity {activity_id}")
            return
        start = state.get("start")
        finish = state.get("finish")
        if isinstance(start, int) and isinstance(finish, int):
            if start > finish or start < 0 or finish > horizon:
                errors.append(
                    f"{context}: {state_name} activity {activity_id} has invalid span [{start}, {finish}]"
                )
        modes = {mode.get("id"): mode for mode in activity.get("eligible_modes", [])}
        mode_id = state.get("mode_id")
        if mode_id is not None and mode_id not in modes:
            errors.append(
                f"{context}: {state_name} activity {activity_id} references unknown mode {mode_id}"
            )
        mode = modes.get(mode_id)
        assignments = (
            state.get("assignments", [])
            if "assignments" in state
            else mode.get("assignments", [])
            if mode is not None
            else activity.get("assignments", [])
        )
        CanonicalLoader._validate_assignments(
            assignments, activity_id, resources, errors, context
        )
        if activity.get("actual_start") is not None or activity.get("actual_finish") is not None:
            return
        duration = mode.get("duration") if mode is not None else activity.get("duration")
        calendar_id = (
            mode.get("calendar_id")
            if mode is not None and mode.get("calendar_id") is not None
            else activity.get("calendar_id")
        )
        calendar = calendars.get(calendar_id)
        if calendar is None or not isinstance(start, int) or not isinstance(finish, int):
            return
        units = _working_units(calendar.get("working_intervals", []))
        for assignment in assignments:
            resource = resources.get(assignment.get("resource_id"))
            resource_calendar = calendars.get(resource.get("calendar_id")) if resource else None
            if resource_calendar is not None:
                units = _intersect_units(
                    units, _working_units(resource_calendar.get("working_intervals", []))
                )
        derived_finish = _finish_from_units(start, duration, units, horizon)
        if derived_finish != finish:
            errors.append(
                f"{context}: {state_name} activity {activity_id} span does not consume its selected duration"
            )
        frozen = activity.get("frozen_state")
        if state_name == "proposed_scenario" and isinstance(frozen, dict) and frozen.get("is_frozen"):
            if start != frozen.get("frozen_start") or finish != frozen.get("frozen_finish"):
                errors.append(
                    f"{context}: proposed_scenario activity {activity_id} changes frozen coordinates"
                )
