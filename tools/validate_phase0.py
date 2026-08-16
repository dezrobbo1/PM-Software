from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

try:
    from .build_consolidated_protocol import render as render_consolidated_protocol
    from .repository_files import repository_paths
except ImportError:  # Direct execution: python tools/validate_phase0.py
    from build_consolidated_protocol import render as render_consolidated_protocol
    from repository_files import repository_paths

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "schemas"
CASES = ROOT / "benchmarks" / "semantic" / "cases"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_EXPECTED_REGISTERS = {
    "comparator-run-register.csv",
    "evidence-register.csv",
    "experiment-register.csv",
    "input-economics-log.csv",
    "native-roundtrip-diff.csv",
    "semantic-compatibility-matrix.csv",
    "source-quality-contradiction-register.csv",
}
_EXPECTED_OBJECTIVE_LEVELS = [
    {"level": 1, "metric": "hard_violation_count", "direction": "minimize"},
    {
        "level": 2,
        "metric": "mandatory_milestone_lateness_lexicographic_vector",
        "direction": "minimize",
    },
    {"level": 3, "metric": "project_finish", "direction": "minimize"},
    {"level": 4, "metric": "approved_forecast_movement", "direction": "minimize"},
    {
        "level": 5,
        "metric": "overtime_mobilisation_peak_penalty",
        "direction": "minimize",
    },
    {
        "level": 6,
        "metric": "continuity_interruption_penalty",
        "direction": "minimize",
    },
    {
        "level": 7,
        "metric": "canonical_activity_mode_resource_id_rank",
        "direction": "minimize",
    },
]
_EXPECTED_MILESTONE_AGGREGATION = {
    "priority_order": "descending_integer_priority",
    "mandatory_definition": "milestone_priority_greater_than_zero_and_due_time_not_null",
    "lateness_definition": "max(0, milestone_finish_minus_due_time)",
    "group_primary": "sum_lateness",
    "group_secondary": "maximum_lateness",
    "group_tertiary": "individual_lateness_vector_in_ascending_stable_milestone_id_order",
    "advance_rule": "advance_to_the_next_lower_priority_only_when_the_entire_current_priority_tuple_is_equal",
}
_EXPECTED_OBJECTIVE_VECTOR_ENCODING = [
    "hard_violation_count",
    "for_each_priority_descending:sum_lateness",
    "for_each_priority_descending:maximum_lateness",
    "for_each_priority_descending:individual_lateness_by_stable_milestone_id",
    "project_finish",
    "approved_forecast_movement",
    "overtime_mobilisation_peak_penalty",
    "continuity_interruption_penalty",
    "canonical_tie_rank",
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _duplicate_values(values: Iterable[Any]) -> list[Any]:
    seen: set[Any] = set()
    duplicates: set[Any] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates, key=lambda value: str(value))


def _entity_ids(items: list[dict[str, Any]], entity: str, case_name: str, errors: list[str]) -> list[str]:
    ids = [item.get("id") for item in items]
    for duplicate in _duplicate_values(ids):
        errors.append(f"{case_name}: duplicate {entity} ID {duplicate!r}")
    return [value for value in ids if isinstance(value, str)]


def _validate_calendar_intervals(
    schedule: dict[str, Any], case_name: str, errors: list[str]
) -> None:
    horizon = schedule.get("time_axis", {}).get("horizon")
    if not isinstance(horizon, int) or isinstance(horizon, bool):
        return

    for calendar in schedule.get("calendars", []):
        calendar_id = calendar.get("id", "<missing>")
        previous_finish: int | None = None
        for index, interval in enumerate(calendar.get("working_intervals", [])):
            if (
                not isinstance(interval, list)
                or len(interval) != 2
                or any(not isinstance(value, int) or isinstance(value, bool) for value in interval)
            ):
                continue  # JSON Schema reports the structural error.
            start, finish = interval
            if start < 0 or finish > horizon:
                errors.append(
                    f"{case_name}: calendar {calendar_id} interval {index} [{start}, {finish}) "
                    f"is outside horizon [0, {horizon})"
                )
            if start >= finish:
                errors.append(
                    f"{case_name}: calendar {calendar_id} interval {index} must satisfy start < finish"
                )
            if previous_finish is not None and start < previous_finish:
                errors.append(
                    f"{case_name}: calendar {calendar_id} intervals overlap or are not in canonical order "
                    f"at index {index}"
                )
            previous_finish = finish


def _validate_state_activity_references(
    state: Any,
    state_name: str,
    activity_ids: set[str],
    mode_ids_by_activity: dict[str, set[str]],
    resource_ids: set[str],
    horizon: int | None,
    case_name: str,
    errors: list[str],
) -> None:
    if not isinstance(state, dict):
        return
    seen: list[str] = []
    for activity_state in state.get("activity_states", []):
        activity_id = activity_state.get("activity_id")
        if isinstance(activity_id, str):
            seen.append(activity_id)
            if activity_id not in activity_ids:
                errors.append(f"{case_name}: {state_name} references unknown activity {activity_id}")
            mode_id = activity_state.get("mode_id")
            if mode_id is not None and mode_id not in mode_ids_by_activity.get(activity_id, set()):
                errors.append(
                    f"{case_name}: {state_name} activity {activity_id} references unknown mode {mode_id}"
                )

        start = activity_state.get("start")
        finish = activity_state.get("finish")
        if (
            isinstance(start, int)
            and not isinstance(start, bool)
            and isinstance(finish, int)
            and not isinstance(finish, bool)
        ):
            if start > finish:
                errors.append(
                    f"{case_name}: {state_name} activity {activity_id} start exceeds finish"
                )
            if horizon is not None and (start < 0 or finish > horizon):
                errors.append(
                    f"{case_name}: {state_name} activity {activity_id} lies outside horizon [0, {horizon}]"
                )

        assignment_resource_ids: list[str] = []
        for assignment in activity_state.get("assignments", []):
            resource_id = assignment.get("resource_id")
            if isinstance(resource_id, str):
                assignment_resource_ids.append(resource_id)
            if resource_id not in resource_ids:
                errors.append(
                    f"{case_name}: {state_name} activity {activity_id} references unknown resource {resource_id}"
                )
        for duplicate in _duplicate_values(assignment_resource_ids):
            errors.append(
                f"{case_name}: {state_name} activity {activity_id} has duplicate assignment for {duplicate}"
            )

    for duplicate in _duplicate_values(seen):
        errors.append(f"{case_name}: {state_name} has duplicate activity state {duplicate}")


def validate_case_document(data: dict[str, Any], case_name: str) -> list[str]:
    """Run semantic cross-reference checks not expressible cleanly in JSON Schema."""

    errors: list[str] = []
    schedule = data.get("schedule", {})
    activities = schedule.get("activities", [])
    relationships = schedule.get("relationships", [])
    calendars = schedule.get("calendars", [])
    resources = schedule.get("resources", [])
    wbs_nodes = schedule.get("wbs", [])
    operational_constraints = schedule.get("operational_constraints", [])

    activity_ids = set(_entity_ids(activities, "activity", case_name, errors))
    relationship_ids = set(_entity_ids(relationships, "relationship", case_name, errors))
    calendar_ids = set(_entity_ids(calendars, "calendar", case_name, errors))
    resource_ids = set(_entity_ids(resources, "resource", case_name, errors))
    wbs_ids = set(_entity_ids(wbs_nodes, "WBS", case_name, errors))
    _entity_ids(operational_constraints, "operational constraint", case_name, errors)

    _validate_calendar_intervals(schedule, case_name, errors)

    for node in wbs_nodes:
        parent_id = node.get("parent_id")
        if parent_id is not None and parent_id not in wbs_ids:
            errors.append(f"{case_name}: WBS node {node.get('id')} references unknown parent {parent_id}")
        if parent_id == node.get("id"):
            errors.append(f"{case_name}: WBS node {node.get('id')} cannot be its own parent")

    mode_ids_by_activity: dict[str, set[str]] = {}
    for activity in activities:
        activity_id = activity.get("id", "<missing>")
        if activity.get("calendar_id") not in calendar_ids:
            errors.append(f"{case_name}: unknown activity calendar {activity.get('calendar_id')}")
        wbs_id = activity.get("wbs_id")
        if wbs_id is not None and wbs_id not in wbs_ids:
            errors.append(f"{case_name}: activity {activity_id} references unknown WBS {wbs_id}")

        frozen_state = activity.get("frozen_state")
        if isinstance(frozen_state, dict) and frozen_state.get("is_frozen") is True:
            frozen_start = frozen_state.get("frozen_start")
            frozen_finish = frozen_state.get("frozen_finish")
            if (
                isinstance(frozen_start, int)
                and not isinstance(frozen_start, bool)
                and isinstance(frozen_finish, int)
                and not isinstance(frozen_finish, bool)
            ):
                if frozen_start > frozen_finish:
                    errors.append(
                        f"{case_name}: activity {activity_id} frozen start exceeds frozen finish"
                    )
                horizon = schedule.get("time_axis", {}).get("horizon")
                if isinstance(horizon, int) and not isinstance(horizon, bool):
                    if frozen_start < 0 or frozen_finish > horizon:
                        errors.append(
                            f"{case_name}: activity {activity_id} frozen coordinates lie outside horizon [0, {horizon}]"
                        )

        assignment_resource_ids: list[str] = []
        for assignment in activity.get("assignments", []):
            resource_id = assignment.get("resource_id")
            if isinstance(resource_id, str):
                assignment_resource_ids.append(resource_id)
            if resource_id not in resource_ids:
                errors.append(f"{case_name}: unknown resource {resource_id}")
        for duplicate in _duplicate_values(assignment_resource_ids):
            errors.append(f"{case_name}: activity {activity_id} has duplicate assignment for {duplicate}")

        modes = activity.get("eligible_modes", [])
        mode_ids = _entity_ids(modes, f"mode on activity {activity_id}", case_name, errors)
        mode_ids_by_activity[str(activity_id)] = set(mode_ids)
        for mode in modes:
            mode_id = mode.get("id", "<missing>")
            mode_calendar = mode.get("calendar_id")
            if mode_calendar is not None and mode_calendar not in calendar_ids:
                errors.append(
                    f"{case_name}: mode {mode_id} on activity {activity_id} references unknown calendar {mode_calendar}"
                )
            mode_assignment_ids: list[str] = []
            for assignment in mode.get("assignments", []):
                resource_id = assignment.get("resource_id")
                if isinstance(resource_id, str):
                    mode_assignment_ids.append(resource_id)
                if resource_id not in resource_ids:
                    errors.append(
                        f"{case_name}: mode {mode_id} on activity {activity_id} references unknown resource {resource_id}"
                    )
            for duplicate in _duplicate_values(mode_assignment_ids):
                errors.append(
                    f"{case_name}: mode {mode_id} on activity {activity_id} has duplicate assignment for {duplicate}"
                )

    for resource in resources:
        if resource.get("calendar_id") not in calendar_ids:
            errors.append(f"{case_name}: unknown resource calendar {resource.get('calendar_id')}")

    for relationship in relationships:
        predecessor_id = relationship.get("predecessor_id")
        successor_id = relationship.get("successor_id")
        if predecessor_id not in activity_ids or successor_id not in activity_ids:
            errors.append(f"{case_name}: relationship references unknown activity")
        if predecessor_id == successor_id:
            errors.append(f"{case_name}: relationship {relationship.get('id')} is self-referential")
        lag_calendar = relationship.get("lag_calendar")
        if lag_calendar is not None and lag_calendar not in calendar_ids:
            errors.append(
                f"{case_name}: relationship {relationship.get('id')} references unknown lag calendar {lag_calendar}"
            )

    for constraint in operational_constraints:
        constraint_id = constraint.get("id", "<missing>")
        for activity_id in constraint.get("activity_ids", []):
            if activity_id not in activity_ids:
                errors.append(
                    f"{case_name}: operational constraint {constraint_id} references unknown activity {activity_id}"
                )
        for resource_id in constraint.get("resource_ids", []):
            if resource_id not in resource_ids:
                errors.append(
                    f"{case_name}: operational constraint {constraint_id} references unknown resource {resource_id}"
                )

    expected_state_types = {
        "baseline": "baseline",
        "approved_forecast": "approved_forecast",
    }
    for state_name in ("baseline", "approved_forecast", "proposed_scenario"):
        state = schedule.get(state_name)
        expected_state_type = expected_state_types.get(state_name)
        if (
            isinstance(state, dict)
            and expected_state_type is not None
            and state.get("state_type") != expected_state_type
        ):
            errors.append(
                f"{case_name}: {state_name} state_type must be {expected_state_type}"
            )
        horizon = schedule.get("time_axis", {}).get("horizon")
        _validate_state_activity_references(
            state,
            state_name,
            activity_ids,
            mode_ids_by_activity,
            resource_ids,
            horizon if isinstance(horizon, int) and not isinstance(horizon, bool) else None,
            case_name,
            errors,
        )

    expected = data.get("expected", {})
    expected_times = expected.get("activity_times", {})
    expected_ids = set(expected_times) if isinstance(expected_times, dict) else set()
    unknown_expected = expected_ids - activity_ids
    if unknown_expected:
        errors.append(
            f"{case_name}: expected activity_times contains unknown IDs {sorted(unknown_expected)}"
        )

    if expected.get("reference_status") == "declared":
        missing_expected = activity_ids - expected_ids
        if missing_expected:
            errors.append(
                f"{case_name}: declared expected activity_times omits {sorted(missing_expected)}"
            )
        for activity_id in sorted(activity_ids & expected_ids):
            record = expected_times.get(activity_id, {})
            start = record.get("start")
            finish = record.get("finish")
            if not isinstance(start, int) or isinstance(start, bool):
                errors.append(f"{case_name}: declared expected start missing/non-integer for {activity_id}")
            if not isinstance(finish, int) or isinstance(finish, bool):
                errors.append(f"{case_name}: declared expected finish missing/non-integer for {activity_id}")
            if isinstance(start, int) and isinstance(finish, int) and start > finish:
                errors.append(f"{case_name}: expected start exceeds finish for {activity_id}")
        project_finish = expected.get("project_finish")
        if not isinstance(project_finish, int) or isinstance(project_finish, bool):
            errors.append(f"{case_name}: declared expected project_finish must be an integer")
        elif expected_times and all(
            isinstance(record.get("finish"), int) and not isinstance(record.get("finish"), bool)
            for record in expected_times.values()
        ):
            calculated_finish = max(record["finish"] for record in expected_times.values())
            if calculated_finish != project_finish:
                errors.append(
                    f"{case_name}: declared project_finish {project_finish} does not equal max activity finish {calculated_finish}"
                )

    driving_relationships = expected.get("driving_relationships", [])
    for relationship_id in driving_relationships:
        if relationship_id not in relationship_ids:
            errors.append(f"{case_name}: expected driving relationship is unknown: {relationship_id}")
    for duplicate in _duplicate_values(driving_relationships):
        errors.append(f"{case_name}: duplicate expected driving relationship {duplicate}")

    resource_order = expected.get("resource_order", [])
    for activity_id in resource_order:
        if activity_id not in activity_ids:
            errors.append(f"{case_name}: expected resource order references unknown activity {activity_id}")
    for duplicate in _duplicate_values(resource_order):
        errors.append(f"{case_name}: duplicate activity in expected resource order {duplicate}")

    return errors


def _schema_validators(root: Path) -> tuple[Draft202012Validator, list[str]]:
    errors: list[str] = []
    schemas_dir = root / "schemas"
    schemas: dict[str, dict[str, Any]] = {}
    for path in sorted(schemas_dir.glob("*.json")):
        try:
            schema = load_json(path)
            Draft202012Validator.check_schema(schema)
            schemas[path.name] = schema
        except Exception as exc:  # json/schema diagnostics are surfaced with the file name.
            errors.append(f"{path.name}: invalid JSON Schema: {exc}")

    canonical = schemas.get("canonical-schedule.schema.json")
    case_schema = schemas.get("semantic-test-case.schema.json")
    if canonical is None or case_schema is None:
        # Return a harmless validator; the missing-schema errors will fail the run.
        return Draft202012Validator({}, format_checker=FormatChecker()), errors

    registry = Registry().with_resource(
        "https://example.invalid/dsc/canonical-schedule.schema.json",
        Resource.from_contents(canonical),
    )
    return Draft202012Validator(
        case_schema, registry=registry, format_checker=FormatChecker()
    ), errors


def validate_cases(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    validator, schema_errors = _schema_validators(root)
    errors.extend(schema_errors)
    cases_dir = root / "benchmarks" / "semantic" / "cases"
    case_files = sorted(cases_dir.glob("*.json"))
    if len(case_files) != 50:
        errors.append(f"Expected 50 case files, found {len(case_files)}")

    seen: set[str] = set()
    for path in case_files:
        try:
            data = load_json(path)
        except Exception as exc:
            errors.append(f"{path.name}: invalid JSON: {exc}")
            continue
        case_id = data.get("case_id", "<missing>")
        if case_id in seen:
            errors.append(f"Duplicate case_id: {case_id}")
        seen.add(case_id)
        for error in sorted(validator.iter_errors(data), key=lambda item: list(item.path)):
            location = ".".join(str(part) for part in error.path)
            errors.append(f"{path.name}:{location}: {error.message}")
        errors.extend(validate_case_document(data, path.name))

    catalogue = root / "benchmarks" / "semantic" / "catalogue.csv"
    try:
        with catalogue.open("r", encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
    except Exception as exc:
        errors.append(f"catalogue.csv: {exc}")
        return errors
    if len(rows) != 50:
        errors.append(f"Expected 50 catalogue rows, found {len(rows)}")
    catalogue_ids = [row.get("case_id") for row in rows]
    for duplicate in _duplicate_values(catalogue_ids):
        errors.append(f"Duplicate catalogue case_id: {duplicate}")
    if set(catalogue_ids) != seen:
        errors.append("Catalogue case IDs do not match fixture case IDs")
    return errors


def validate_registers(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    register_dir = root / "registers"
    discovered = {path.name for path in register_dir.glob("*.csv")}
    for missing in sorted(_EXPECTED_REGISTERS - discovered):
        errors.append(f"Required register is missing: {missing}")
    for unexpected in sorted(discovered - _EXPECTED_REGISTERS):
        errors.append(f"Unexpected register file: {unexpected}")

    for name in sorted(discovered & _EXPECTED_REGISTERS):
        path = register_dir / name
        with path.open("r", encoding="utf-8", newline="") as f:
            rows = list(csv.reader(f))
        if len(rows) != 1 or not rows[0] or any(not header for header in rows[0]):
            errors.append(f"{path.name}: expected exactly one non-empty header row")
        for duplicate in _duplicate_values(rows[0] if rows else []):
            errors.append(f"{path.name}: duplicate header {duplicate}")
    return errors


def validate_configuration(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    objective_path = root / "config" / "objective-policy-v0.2.json"
    deterministic_path = root / "config" / "deterministic-execution-profile-v0.1.json"
    try:
        objective = load_json(objective_path)
        expected_scalars = {
            "policy_id": "objective-v0.2",
            "type": "lexicographic",
            "status": "benchmark_policy_not_practitioner_validated",
            "final_tie_break": "stable_ascending_activity_id_then_mode_id_then_resource_id",
        }
        for key, expected in expected_scalars.items():
            if objective.get(key) != expected:
                errors.append(
                    f"objective-policy-v0.2.json: {key} must equal {expected!r}"
                )
        if objective.get("levels") != _EXPECTED_OBJECTIVE_LEVELS:
            errors.append(
                "objective-policy-v0.2.json: levels must match the frozen ordered level definitions"
            )
        if objective.get("milestone_priority_aggregation") != _EXPECTED_MILESTONE_AGGREGATION:
            errors.append(
                "objective-policy-v0.2.json: milestone priority aggregation values must match the frozen policy"
            )
        if objective.get("objective_vector_encoding") != _EXPECTED_OBJECTIVE_VECTOR_ENCODING:
            errors.append(
                "objective-policy-v0.2.json: objective vector encoding must match the frozen ordering"
            )
    except Exception as exc:
        errors.append(f"objective-policy-v0.2.json: {exc}")

    try:
        deterministic = load_json(deterministic_path)
        if deterministic.get("tie_break_policy") != "objective-v0.2-level-7":
            errors.append(
                "deterministic-execution-profile-v0.1.json: tie_break_policy must reference objective-v0.2"
            )
    except Exception as exc:
        errors.append(f"deterministic-execution-profile-v0.1.json: {exc}")
    return errors


def validate_consolidated_protocol(root: Path = ROOT) -> list[str]:
    path = root / "PHASE-0-PROTOCOL-CONSOLIDATED.md"
    if not path.exists():
        return ["PHASE-0-PROTOCOL-CONSOLIDATED.md is missing"]
    expected = render_consolidated_protocol() if root.resolve() == ROOT.resolve() else _render_for_root(root)
    actual = path.read_text(encoding="utf-8")
    if actual != expected:
        return [
            "PHASE-0-PROTOCOL-CONSOLIDATED.md does not match the numbered authoritative documents"
        ]
    return []


def _render_for_root(root: Path) -> str:
    header = (
        "# Deterministic Scheduling Core — Phase 0 Protocol\n\n"
        "This consolidated review document mirrors the authoritative files in this bundle. "
        "The individual files remain the change-controlled source.\n\n\n---\n\n"
    )
    sources = sorted((root / "docs").glob("[0-9][0-9]-*.md"))
    return header + "\n\n---\n\n".join(path.read_text(encoding="utf-8").strip() for path in sources) + "\n"


def _safe_manifest_path(raw: str) -> PurePosixPath:
    rel = PurePosixPath(raw)
    if rel.is_absolute() or not rel.parts or any(part in {"", ".", ".."} for part in rel.parts):
        raise ValueError(f"unsafe path {raw!r}")
    return rel


def validate_manifest(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    manifest = root / "manifest.sha256"
    if not manifest.exists():
        return ["manifest.sha256 is missing"]

    entries: dict[PurePosixPath, str] = {}
    for line_number, line in enumerate(manifest.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            digest, raw_path = line.split("  ", 1)
        except ValueError:
            errors.append(f"Manifest line {line_number} is malformed")
            continue
        if not _SHA256_RE.fullmatch(digest):
            errors.append(f"Manifest line {line_number} has an invalid SHA-256 digest")
        try:
            rel = _safe_manifest_path(raw_path)
        except ValueError as exc:
            errors.append(f"Manifest line {line_number}: {exc}")
            continue
        if rel in entries:
            errors.append(f"Manifest contains duplicate path: {rel.as_posix()}")
            continue
        entries[rel] = digest

    try:
        expected_paths = set(repository_paths(root))
    except Exception as exc:
        errors.append(f"Unable to determine repository file set: {exc}")
        return errors
    manifest_paths = set(entries)

    for rel in sorted(expected_paths - manifest_paths, key=lambda item: item.as_posix()):
        errors.append(f"Tracked repository file missing from manifest: {rel.as_posix()}")
    for rel in sorted(manifest_paths - expected_paths, key=lambda item: item.as_posix()):
        errors.append(f"Manifest path is not an intended tracked file: {rel.as_posix()}")

    for rel in sorted(manifest_paths & expected_paths, key=lambda item: item.as_posix()):
        path = root / rel
        if path.is_symlink():
            errors.append(f"Manifest path must not be a symlink: {rel.as_posix()}")
        elif not path.is_file():
            errors.append(f"Manifest path missing: {rel.as_posix()}")
        elif sha256(path) != entries[rel]:
            errors.append(f"Manifest hash mismatch: {rel.as_posix()}")
    return errors


def collect_errors(root: Path = ROOT) -> list[str]:
    return (
        validate_cases(root)
        + validate_registers(root)
        + validate_configuration(root)
        + validate_consolidated_protocol(root)
        + validate_manifest(root)
    )


def main() -> int:
    errors = collect_errors(ROOT)
    if errors:
        print("PHASE 0 VALIDATION: FAIL")
        for error in errors:
            print(f"- {error}")
        return 1
    print("PHASE 0 VALIDATION: PASS")
    print("- 50 unique semantic fixtures validated")
    print("- JSON Schemas resolved and meta-validated")
    print("- IDs, references, calendars, and expected results validated")
    print("- Register headers validated")
    print("- Objective and deterministic-profile contracts aligned")
    print("- Consolidated protocol matches authoritative documents")
    print("- SHA-256 manifest completeness and hashes verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
