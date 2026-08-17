from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Sequence

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

try:
    from .build_consolidated_protocol import (
        AUTHORITATIVE_CHAPTERS,
        authoritative_sources,
        render as render_consolidated_protocol,
    )
    from .repository_files import repository_paths
except ImportError:  # Direct execution: python tools/validate_phase0.py
    from build_consolidated_protocol import (
        AUTHORITATIVE_CHAPTERS,
        authoritative_sources,
        render as render_consolidated_protocol,
    )
    from repository_files import repository_paths

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "schemas"
CASES = ROOT / "benchmarks" / "semantic" / "cases"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CANONICAL_SCHEMA_VERSION = "0.1.3"
_EXECUTION_SCHEMA_VERSION = "0.1.4"
_EXPLANATION_SCHEMA_VERSION = "0.1.3"
_ACTIVE_SEMANTIC_PROFILE_ID = "reference-v0.3"
_ACTIVE_OBJECTIVE_POLICY_ID = "objective-v0.3"

_EXPECTED_REGISTERS: dict[str, list[str]] = {
    "comparator-run-register.csv": [
        "run_id",
        "case_id",
        "comparator",
        "product_version",
        "settings_snapshot",
        "input_hash",
        "output_hash",
        "project_finish",
        "milestone_lateness",
        "hard_violations",
        "resource_overload",
        "activities_moved",
        "movement_hours",
        "runtime_seconds",
        "memory_mb",
        "planner_minutes",
        "acceptance",
        "evidence_path",
    ],
    "evidence-register.csv": [
        "evidence_id",
        "claim",
        "source",
        "source_date",
        "evidence_class",
        "direct_or_inferred",
        "supporting_evidence",
        "contradictory_evidence",
        "independent",
        "confidence",
        "unresolved_measurement",
        "research_implication",
    ],
    "experiment-register.csv": [
        "experiment_id",
        "hypothesis",
        "corpus",
        "configuration_id",
        "baseline",
        "execution_status",
        "result_summary",
        "input_hash",
        "output_hash",
        "evidence_path",
        "limitations",
        "reviewer",
        "date",
    ],
    "input-economics-log.csv": [
        "case_id",
        "activity",
        "role",
        "start_time",
        "end_time",
        "working_minutes",
        "waiting_minutes",
        "tool",
        "manual_transfer_count",
        "error_or_rework",
        "notes",
    ],
    "native-roundtrip-diff.csv": [
        "run_id",
        "case_id",
        "native_product",
        "field_or_semantic",
        "source_value",
        "exported_value",
        "reopened_value",
        "recalculated_value",
        "classification",
        "material",
        "manual_approval_required",
        "evidence_path",
    ],
    "semantic-compatibility-matrix.csv": [
        "case_id",
        "feature",
        "reference_expected",
        "reference_result",
        "p6_version",
        "p6_settings",
        "p6_result",
        "msp_version",
        "msp_settings",
        "msp_result",
        "compatibility_status",
        "discrepancy",
        "practical_consequence",
        "evidence_path",
    ],
    "source-quality-contradiction-register.csv": [
        "issue_id",
        "claim_or_source",
        "quality_issue",
        "contradiction",
        "effect_on_interpretation",
        "required_resolution",
        "status",
    ],
}
_EXPECTED_CATALOGUE_FIELDS = [
    "case_id",
    "category",
    "title",
    "reference_status",
    "project_finish",
    "p6_validation",
    "microsoft_project_validation",
]
_EXPECTED_CASE_IDS = (
    "SEM-REL-001",
    "SEM-REL-002",
    "SEM-REL-003",
    "SEM-REL-004",
    "SEM-REL-005",
    "SEM-REL-006",
    "SEM-REL-007",
    "SEM-REL-008",
    "SEM-REL-009",
    "SEM-REL-010",
    "SEM-REL-011",
    "SEM-REL-012",
    "SEM-NET-013",
    "SEM-NET-014",
    "SEM-NET-015",
    "SEM-NET-016",
    "SEM-NET-017",
    "SEM-NET-018",
    "SEM-NET-019",
    "SEM-NET-020",
    "SEM-CAL-021",
    "SEM-CAL-022",
    "SEM-CAL-023",
    "SEM-CAL-024",
    "SEM-CAL-025",
    "SEM-CAL-026",
    "SEM-CAL-027",
    "SEM-CAL-028",
    "SEM-CAL-029",
    "SEM-CAL-030",
    "SEM-MIL-031",
    "SEM-MIL-032",
    "SEM-MIL-033",
    "SEM-MIL-034",
    "SEM-CON-035",
    "SEM-CON-036",
    "SEM-CON-037",
    "SEM-CON-038",
    "SEM-STA-039",
    "SEM-STA-040",
    "SEM-STA-041",
    "SEM-STA-042",
    "SEM-STA-043",
    "SEM-STA-044",
    "SEM-STA-045",
    "SEM-STA-046",
    "SEM-FLT-047",
    "SEM-FLT-048",
    "SEM-DET-049",
    "SEM-DET-050",
)
_EXPECTED_CASE_FILE_BY_ID = {case_id: f"{case_id.lower()}.json" for case_id in _EXPECTED_CASE_IDS}
_EXPECTED_CASE_ID_BY_FILE = {name: case_id for case_id, name in _EXPECTED_CASE_FILE_BY_ID.items()}
_EXPECTED_CONFIG_FILES = {
    "deterministic-execution-profile-v0.1.json",
    "objective-policy-v0.1.json",
    "objective-policy-v0.2.json",
    "objective-policy-v0.3.json",
    "semantic-profile-reference-v0.1.json",
    "semantic-profile-reference-v0.2.json",
    "semantic-profile-reference-v0.3.json",
}
_EXPECTED_OBJECTIVE_POLICY: dict[str, Any] = {
    "policy_id": "objective-v0.3",
    "type": "lexicographic",
    "levels": [
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
            "metric": "operational_resource_penalty_lexicographic_tuple",
            "direction": "minimize",
        },
        {"level": 6, "metric": "continuity_interruption_count", "direction": "minimize"},
        {
            "level": 7,
            "metric": "canonical_scenario_decision_vector",
            "direction": "minimize",
        },
    ],
    "status": "benchmark_policy_not_practitioner_validated",
    "milestone_priority_aggregation": {
        "priority_order": "descending_integer_priority",
        "mandatory_definition": "kind_in_start_or_finish_milestone_and_milestone_priority_greater_than_zero_and_due_time_not_null",
        "lateness_definition": "max(0, milestone_finish_minus_due_time)",
        "group_primary": "sum_lateness",
        "group_secondary": "maximum_lateness",
        "group_tertiary": "individual_lateness_vector_in_ascending_stable_milestone_id_order",
        "advance_rule": "advance_to_the_next_lower_priority_only_when_the_entire_current_priority_tuple_is_equal",
    },
    "approved_forecast_movement": {
        "missing_forecast_value": 0,
        "activity_order": "stable_ascending_activity_id",
        "formula": "sum_abs_proposed_start_minus_approved_start_plus_abs_proposed_finish_minus_approved_finish",
    },
    "operational_resource_penalty": {
        "ordering": "lexicographic",
        "components": [
            "overtime_units",
            "mobilisation_block_count",
            "resource_peak_demand_sum",
        ],
        "overtime_units_definition": "constant_zero_in_canonical_schema_0.1.3_overtime_not_yet_modelled",
        "mobilisation_block_count_definition": "sum_over_resources_of_maximal_contiguous_or_overlapping_productive_assignment_blocks",
        "resource_peak_demand_sum_definition": "sum_over_resources_of_maximum_concurrent_integer_assignment_demand",
    },
    "continuity_interruption": {
        "definition": "constant_zero_in_canonical_schema_0.1.3_split_execution_not_yet_modelled"
    },
    "canonical_tie_break": {
        "activity_order": "stable_ascending_activity_id",
        "resource_order": "stable_ascending_resource_id",
        "mode_ordinal": "zero_for_no_mode_otherwise_one_plus_index_in_stable_ascending_mode_id_order",
        "per_activity_encoding": [
            "start",
            "finish",
            "mode_ordinal",
            "for_each_resource_in_stable_order:assignment_demand_or_zero",
        ],
    },
    "objective_vector_encoding": [
        "hard_violation_count",
        "for_each_priority_descending:sum_lateness",
        "for_each_priority_descending:maximum_lateness",
        "for_each_priority_descending:individual_lateness_by_stable_milestone_id",
        "project_finish",
        "approved_forecast_movement",
        "overtime_units",
        "mobilisation_block_count",
        "resource_peak_demand_sum",
        "continuity_interruption_count",
        "for_each_activity_id_ascending:start",
        "for_each_activity_id_ascending:finish",
        "for_each_activity_id_ascending:mode_ordinal",
        "for_each_activity_id_ascending_and_resource_id_ascending:assignment_demand_or_zero",
    ],
    "final_tie_break": "lexicographic_canonical_scenario_decision_vector",
}
_EXPECTED_DETERMINISTIC_PROFILE: dict[str, Any] = {
    "profile_id": "deterministic-v0.1",
    "canonical_json": "implementation_to_be_pinned_before_execution",
    "unicode_normalization": "NFC",
    "hash_algorithm": "SHA-256",
    "time_representation": "integer",
    "worker_count": 1,
    "random_seed": 0,
    "wall_clock_termination_for_semantic_tests": False,
    "solver_name": "to_be_pinned_in_phase1",
    "solver_build": "to_be_pinned_in_phase1",
    "tie_break_policy": "objective-v0.3-level-7",
    "cross_version_determinism_promised": False,
}
_EXPECTED_SEMANTIC_PROFILE_V1: dict[str, Any] = {
    "profile_id": "reference-v0.1",
    "time_domain": "integer",
    "duration_basis": "productive_working_time",
    "relationship_types": ["FS", "SS", "FF", "SF"],
    "lag_policy": "successor_calendar_unless_explicit",
    "negative_lag": "supported",
    "project_start_lower_bound": True,
    "constraints": [
        "start_no_earlier_than",
        "finish_no_earlier_than",
        "fixed_start",
        "fixed_finish",
    ],
    "progress_policies": ["none", "retained_logic", "progress_override"],
    "actual_dates_policy": "native_validation_only",
    "float_scope": "simple_24x7_acyclic_unconstrained_networks_only",
    "native_equivalence": {"p6": "not_claimed", "microsoft_project": "not_claimed"},
}
_EXPECTED_SEMANTIC_PROFILE_V2: dict[str, Any] = {
    **_EXPECTED_SEMANTIC_PROFILE_V1,
    "profile_id": "reference-v0.2",
    "constraints": ["start_no_earlier_than", "finish_no_earlier_than"],
    "supersedes": "reference-v0.1",
    "change_reason": "fixed_start_and_fixed_finish_removed_from_executable_claim_until_direct_semantic_fixtures_exist",
}
_EXPECTED_SEMANTIC_PROFILE: dict[str, Any] = {
    **_EXPECTED_SEMANTIC_PROFILE_V2,
    "profile_id": "reference-v0.3",
    "lag_policy": "successor_calendar_only",
    "explicit_lag_calendars": "preserved_in_canonical_model_but_not_executable_until_direct_fixture_exists",
    "resource_capacity_semantics": "exclusive_capacity_one_only",
    "cumulative_resources": "preserved_in_canonical_model_but_not_executable_until_direct_fixture_exists",
    "supersedes": "reference-v0.2",
    "change_reason": "explicit_alternate_lag_calendars_and_cumulative_capacity_removed_from_executable_claim_until_direct_semantic_fixtures_exist",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _duplicate_values(values: Iterable[Any]) -> list[Any]:
    seen: set[Any] = set()
    duplicates: set[Any] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates, key=lambda value: str(value))


def _entity_ids(
    items: list[dict[str, Any]], entity: str, case_name: str, errors: list[str]
) -> list[str]:
    ids = [item.get("id") for item in items]
    for duplicate in _duplicate_values(ids):
        errors.append(f"{case_name}: duplicate {entity} ID {duplicate!r}")
    return [value for value in ids if isinstance(value, str)]


def _validate_calendar_intervals(
    schedule: dict[str, Any], case_name: str, errors: list[str]
) -> None:
    horizon = schedule.get("time_axis", {}).get("horizon")
    if not _is_int(horizon):
        return

    for calendar in schedule.get("calendars", []):
        calendar_id = calendar.get("id", "<missing>")
        previous_finish: int | None = None
        for index, interval in enumerate(calendar.get("working_intervals", [])):
            if (
                not isinstance(interval, list)
                or len(interval) != 2
                or any(not _is_int(value) for value in interval)
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


def _validate_wbs_hierarchy(
    wbs_nodes: list[dict[str, Any]], case_name: str, errors: list[str]
) -> None:
    parent_by_id = {
        node["id"]: node.get("parent_id")
        for node in wbs_nodes
        if isinstance(node.get("id"), str)
    }
    reported: set[tuple[str, ...]] = set()
    for start in sorted(parent_by_id):
        path: list[str] = []
        index_by_id: dict[str, int] = {}
        current: str | None = start
        while current is not None and current in parent_by_id:
            if current in index_by_id:
                cycle = path[index_by_id[current] :]
                canonical = tuple(sorted(cycle))
                if canonical not in reported:
                    reported.add(canonical)
                    errors.append(
                        f"{case_name}: WBS hierarchy contains cycle {' -> '.join(cycle + [current])}"
                    )
                break
            index_by_id[current] = len(path)
            path.append(current)
            parent = parent_by_id[current]
            current = parent if isinstance(parent, str) else None


def _intersect_intervals(
    left: Sequence[Sequence[int]], right: Sequence[Sequence[int]]
) -> list[list[int]]:
    result: list[list[int]] = []
    i = j = 0
    while i < len(left) and j < len(right):
        start = max(left[i][0], right[j][0])
        finish = min(left[i][1], right[j][1])
        if start < finish:
            result.append([start, finish])
        if left[i][1] <= right[j][1]:
            i += 1
        else:
            j += 1
    return result


def _consume_working_duration(
    start: int, duration: int, intervals: Sequence[Sequence[int]]
) -> int | None:
    if duration == 0:
        return start
    current = start
    remaining = duration
    for interval_start, interval_finish in intervals:
        if current >= interval_finish:
            continue
        if current < interval_start:
            # A scheduled start is an explicit coordinate; it may not silently snap.
            return None
        available = interval_finish - current
        if remaining <= available:
            return current + remaining
        remaining -= available
        current = interval_finish
        # The next loop may cross a non-working gap by moving to the next interval start.
        for next_start, _ in intervals:
            if next_start >= current:
                current = next_start
                break
    return None


def _add_working_lag(
    anchor: int, lag: int, intervals: Sequence[Sequence[int]]
) -> int | None:
    """Shift an event coordinate by signed productive working time.

    Positive lag snaps forward to the next working interval before consuming work;
    negative lag snaps backward to the preceding interval finish. Zero lag preserves
    the event coordinate exactly.
    """

    if lag == 0:
        return anchor
    if lag > 0:
        remaining = lag
        cursor = anchor
        for interval_start, interval_finish in intervals:
            if cursor >= interval_finish:
                continue
            position = max(cursor, interval_start)
            available = interval_finish - position
            if remaining <= available:
                return position + remaining
            remaining -= available
            cursor = interval_finish
        return None

    remaining = -lag
    cursor = anchor
    for interval_start, interval_finish in reversed(intervals):
        if cursor <= interval_start:
            continue
        position = min(cursor, interval_finish)
        available = position - interval_start
        if remaining <= available:
            return position - remaining
        remaining -= available
        cursor = interval_start
    return None


def _selected_mode(activity: dict[str, Any], mode_id: Any) -> dict[str, Any] | None:
    if not isinstance(mode_id, str):
        return None
    return next((mode for mode in activity.get("eligible_modes", []) if mode.get("id") == mode_id), None)


def _state_assignments(
    activity_state: dict[str, Any], activity: dict[str, Any], mode: dict[str, Any] | None
) -> list[dict[str, Any]]:
    if "assignments" in activity_state:
        return activity_state.get("assignments", [])
    if mode is not None:
        return mode.get("assignments", [])
    return activity.get("assignments", [])


def _validate_unstarted_state_span(
    activity_state: dict[str, Any],
    activity: dict[str, Any],
    calendars_by_id: dict[str, dict[str, Any]],
    resources_by_id: dict[str, dict[str, Any]],
    state_name: str,
    case_name: str,
    errors: list[str],
) -> None:
    # Actual/in-progress state has product-specific treatment and is not asserted here.
    if _is_int(activity.get("actual_start")) or _is_int(activity.get("actual_finish")):
        return
    start = activity_state.get("start")
    finish = activity_state.get("finish")
    if not (_is_int(start) and _is_int(finish)):
        return

    mode = _selected_mode(activity, activity_state.get("mode_id"))
    duration = mode.get("duration") if mode is not None else activity.get("duration")
    calendar_id = (
        mode.get("calendar_id")
        if mode is not None and mode.get("calendar_id") is not None
        else activity.get("calendar_id")
    )
    if not _is_int(duration) or calendar_id not in calendars_by_id:
        return

    intervals: list[list[int]] = [
        list(interval) for interval in calendars_by_id[calendar_id].get("working_intervals", [])
    ]
    for assignment in _state_assignments(activity_state, activity, mode):
        resource = resources_by_id.get(assignment.get("resource_id"))
        if resource is None:
            continue
        resource_calendar = calendars_by_id.get(resource.get("calendar_id"))
        if resource_calendar is None:
            continue
        intervals = _intersect_intervals(
            intervals,
            resource_calendar.get("working_intervals", []),
        )

    expected_finish = _consume_working_duration(start, duration, intervals)
    if expected_finish is None:
        errors.append(
            f"{case_name}: {state_name} activity {activity.get('id')} cannot consume duration {duration} "
            f"from start {start} on its selected calendars"
        )
    elif finish != expected_finish:
        errors.append(
            f"{case_name}: {state_name} activity {activity.get('id')} finish {finish} does not equal "
            f"calendar-derived finish {expected_finish} for duration {duration}"
        )


def _validate_state_activity_references(
    state: Any,
    state_name: str,
    activities_by_id: dict[str, dict[str, Any]],
    mode_ids_by_activity: dict[str, set[str]],
    resources_by_id: dict[str, dict[str, Any]],
    calendars_by_id: dict[str, dict[str, Any]],
    horizon: int | None,
    case_name: str,
    errors: list[str],
    *,
    require_complete: bool = False,
) -> None:
    if not isinstance(state, dict):
        return
    seen: list[str] = []
    for activity_state in state.get("activity_states", []):
        activity_id = activity_state.get("activity_id")
        if isinstance(activity_id, str):
            seen.append(activity_id)
            if activity_id not in activities_by_id:
                errors.append(f"{case_name}: {state_name} references unknown activity {activity_id}")
            mode_id = activity_state.get("mode_id")
            if mode_id is not None and mode_id not in mode_ids_by_activity.get(activity_id, set()):
                errors.append(
                    f"{case_name}: {state_name} activity {activity_id} references unknown mode {mode_id}"
                )

        start = activity_state.get("start")
        finish = activity_state.get("finish")
        if _is_int(start) and _is_int(finish):
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
            if resource_id not in resources_by_id:
                errors.append(
                    f"{case_name}: {state_name} activity {activity_id} references unknown resource {resource_id}"
                )
        for duplicate in _duplicate_values(assignment_resource_ids):
            errors.append(
                f"{case_name}: {state_name} activity {activity_id} has duplicate assignment for {duplicate}"
            )

        activity = activities_by_id.get(activity_id)
        if activity is not None:
            frozen_state = activity.get("frozen_state")
            if (
                state_name == "proposed_scenario"
                and isinstance(frozen_state, dict)
                and frozen_state.get("is_frozen") is True
            ):
                frozen_start = frozen_state.get("frozen_start")
                frozen_finish = frozen_state.get("frozen_finish")
                if start != frozen_start or finish != frozen_finish:
                    errors.append(
                        f"{case_name}: proposed_scenario activity {activity_id} must preserve "
                        f"frozen coordinates [{frozen_start}, {frozen_finish}]"
                    )
            _validate_unstarted_state_span(
                activity_state,
                activity,
                calendars_by_id,
                resources_by_id,
                state_name,
                case_name,
                errors,
            )

    for duplicate in _duplicate_values(seen):
        errors.append(f"{case_name}: {state_name} has duplicate activity state {duplicate}")

    if require_complete:
        present = set(seen)
        required = set(activities_by_id)
        if present != required:
            missing = sorted(required - present)
            extra = sorted(present - required)
            details: list[str] = []
            if missing:
                details.append(f"missing {missing}")
            if extra:
                details.append(f"unknown {extra}")
            errors.append(
                f"{case_name}: {state_name} activity states must exactly cover the schedule ({'; '.join(details)})"
            )


def mandatory_milestones(schedule: dict[str, Any]) -> dict[int, list[str]]:
    groups: dict[int, list[str]] = {}
    for activity in schedule.get("activities", []):
        priority = activity.get("milestone_priority")
        due_time = activity.get("due_time")
        if (
            activity.get("kind") in {"start_milestone", "finish_milestone"}
            and _is_int(priority)
            and priority > 0
            and _is_int(due_time)
            and isinstance(activity.get("id"), str)
        ):
            groups.setdefault(priority, []).append(activity["id"])
    return {priority: sorted(ids) for priority, ids in groups.items()}


def objective_vector_layout(schedule: dict[str, Any]) -> list[str]:
    labels = ["hard_violation_count"]
    groups = mandatory_milestones(schedule)
    for priority in sorted(groups, reverse=True):
        labels.append(f"priority[{priority}].sum_lateness")
        labels.append(f"priority[{priority}].maximum_lateness")
        labels.extend(f"priority[{priority}].milestone[{mid}].lateness" for mid in groups[priority])
    labels.extend(
        [
            "project_finish",
            "approved_forecast_movement",
            "overtime_units",
            "mobilisation_block_count",
            "resource_peak_demand_sum",
            "continuity_interruption_count",
        ]
    )
    resource_ids = sorted(
        resource["id"]
        for resource in schedule.get("resources", [])
        if isinstance(resource.get("id"), str)
    )
    for activity in sorted(
        schedule.get("activities", []), key=lambda item: str(item.get("id", ""))
    ):
        activity_id = activity.get("id", "<missing>")
        labels.extend(
            [
                f"activity[{activity_id}].start",
                f"activity[{activity_id}].finish",
                f"activity[{activity_id}].mode_ordinal",
            ]
        )
        labels.extend(
            f"activity[{activity_id}].resource[{resource_id}].demand"
            for resource_id in resource_ids
        )
    return labels


def validate_objective_vector(
    vector: Any,
    schedule: dict[str, Any],
    context: str,
    *,
    allow_empty: bool = False,
) -> list[str]:
    if not isinstance(vector, list):
        return [f"{context}: objective vector must be an array"]
    if allow_empty and not vector:
        return []
    expected = objective_vector_layout(schedule)
    errors: list[str] = []
    if len(vector) != len(expected):
        errors.append(
            f"{context}: objective vector has {len(vector)} entries; expected {len(expected)} "
            f"for the canonical input"
        )
    if any(not _is_int(value) for value in vector):
        errors.append(f"{context}: objective vector must contain integers only")
    return errors


def validate_execution_record(
    record: dict[str, Any], schedule: dict[str, Any], context: str = "execution record"
) -> list[str]:
    errors: list[str] = []
    optimality = record.get("optimality_status")
    if optimality in {"optimal", "feasible_not_proven"}:
        errors.extend(validate_objective_vector(record.get("objective_vector"), schedule, context))
    elif optimality == "infeasible_proven":
        if record.get("feasibility_status") != "infeasible":
            errors.append(f"{context}: infeasible proof must be classified infeasible")
        if record.get("selected_scenario_hash") is not None:
            errors.append(
                f"{context}: infeasible proof must not publish a selected-scenario hash"
            )
        if record.get("objective_vector") != []:
            errors.append(f"{context}: infeasible proof must have an empty objective vector")
        if record.get("best_bound") is not None:
            errors.append(f"{context}: infeasible proof must not publish a best bound")
        if record.get("optimality_gap") is not None:
            errors.append(f"{context}: infeasible proof must not publish an optimality gap")
    elif optimality == "not_applicable" and record.get("objective_vector") not in ([], None):
        errors.append(f"{context}: not-applicable optimisation must have an empty objective vector")
    return errors


def validate_explanation_document(
    explanation: dict[str, Any],
    schedule: dict[str, Any] | None = None,
    context: str = "structured explanation",
) -> list[str]:
    errors: list[str] = []
    basis = explanation.get("movement_basis")
    movement = explanation.get("movement")
    coordinate_pairs = {
        "start": (explanation.get("previous_start"), explanation.get("proposed_start")),
        "finish": (explanation.get("previous_finish"), explanation.get("proposed_finish")),
    }
    derived: int | None = None
    if basis in {"start", "finish"}:
        previous, proposed = coordinate_pairs[basis]
        if _is_int(previous) and _is_int(proposed):
            derived = proposed - previous
        else:
            errors.append(f"{context}: {basis}-basis movement requires integer previous/proposed {basis}")
    elif basis == "both":
        start_previous, start_proposed = coordinate_pairs["start"]
        finish_previous, finish_proposed = coordinate_pairs["finish"]
        if all(_is_int(value) for value in (start_previous, start_proposed, finish_previous, finish_proposed)):
            start_delta = start_proposed - start_previous
            finish_delta = finish_proposed - finish_previous
            if start_delta != finish_delta:
                errors.append(
                    f"{context}: both-basis movement requires equal start and finish deltas"
                )
            else:
                derived = start_delta
        else:
            errors.append(
                f"{context}: both-basis movement requires integer previous/proposed start and finish"
            )
    if derived is not None and movement != derived:
        errors.append(
            f"{context}: movement {movement!r} does not equal coordinate-derived movement {derived}"
        )

    if explanation.get("decision_scope") == "optimisation_scenario" and schedule is not None:
        errors.extend(
            validate_objective_vector(
                explanation.get("selected_objective_vector"),
                schedule,
                context,
            )
        )

    if schedule is not None:
        activities = {
            activity.get("id"): activity
            for activity in schedule.get("activities", [])
            if isinstance(activity.get("id"), str)
        }
        entity_namespaces: dict[str, set[str]] = {
            "activity": set(activities),
            "relationship": {
                relationship["id"]
                for relationship in schedule.get("relationships", [])
                if isinstance(relationship.get("id"), str)
            },
            "calendar": {
                calendar["id"]
                for calendar in schedule.get("calendars", [])
                if isinstance(calendar.get("id"), str)
            },
            "constraint": {
                constraint["id"]
                for activity in schedule.get("activities", [])
                for constraint in activity.get("constraints", [])
                if isinstance(constraint.get("id"), str)
            },
            "resource": {
                resource["id"]
                for resource in schedule.get("resources", [])
                if isinstance(resource.get("id"), str)
            },
            "operational_constraint": {
                constraint["id"]
                for constraint in schedule.get("operational_constraints", [])
                if isinstance(constraint.get("id"), str)
            },
            "objective_policy": {_ACTIVE_OBJECTIVE_POLICY_ID},
        }

        activity_id = explanation.get("activity_id")
        if activity_id not in activities:
            errors.append(f"{context}: activity_id references unknown activity {activity_id}")

        governing = explanation.get("governing_entity")
        if isinstance(governing, dict):
            entity_type = governing.get("type")
            entity_id = governing.get("id")
            if entity_type == "actual_event":
                source_field = governing.get("source_field")
                activity = activities.get(entity_id)
                if activity is None:
                    errors.append(
                        f"{context}: governing actual_event references unknown activity {entity_id}"
                    )
                elif source_field not in {"actual_start", "actual_finish"}:
                    errors.append(
                        f"{context}: governing actual_event source_field must be actual_start or actual_finish"
                    )
                elif not _is_int(activity.get(source_field)):
                    errors.append(
                        f"{context}: governing actual_event {entity_id}.{source_field} is not present in the canonical input"
                    )
            elif entity_type in entity_namespaces and entity_id not in entity_namespaces[entity_type]:
                errors.append(
                    f"{context}: governing {entity_type} references unknown ID {entity_id}"
                )

        conflicting_activity = explanation.get("conflicting_activity_id")
        if conflicting_activity is not None and conflicting_activity not in activities:
            errors.append(
                f"{context}: conflicting_activity_id references unknown activity {conflicting_activity}"
            )

        affected_milestone = explanation.get("affected_milestone_id")
        if affected_milestone is not None:
            activity = activities.get(affected_milestone)
            if activity is None:
                errors.append(
                    f"{context}: affected_milestone_id references unknown activity {affected_milestone}"
                )
            elif activity.get("kind") not in {"start_milestone", "finish_milestone"}:
                errors.append(
                    f"{context}: affected_milestone_id {affected_milestone} is not a milestone"
                )

        proposed = schedule.get("proposed_scenario")
        if explanation.get("decision_scope") == "optimisation_scenario" and isinstance(
            proposed, dict
        ):
            if explanation.get("scenario_id") != proposed.get("scenario_id"):
                errors.append(
                    f"{context}: scenario_id does not match the canonical proposed_scenario"
                )
        if explanation.get("decision_scope") == "optimisation_scenario" and explanation.get(
            "objective_policy_version"
        ) != _ACTIVE_OBJECTIVE_POLICY_ID:
            errors.append(
                f"{context}: objective_policy_version must be {_ACTIVE_OBJECTIVE_POLICY_ID}"
            )

        for counterfactual in explanation.get("counterfactuals", []):
            if counterfactual.get("result_status") == "feasible":
                errors.extend(
                    validate_objective_vector(
                        counterfactual.get("objective_vector"),
                        schedule,
                        f"{context}: counterfactual {counterfactual.get('counterfactual_id', '<missing>')}",
                    )
                )
            for impact in counterfactual.get("milestone_impacts", []):
                milestone_id = impact.get("milestone_id")
                milestone = activities.get(milestone_id)
                if milestone is None:
                    errors.append(
                        f"{context}: counterfactual milestone impact references unknown activity {milestone_id}"
                    )
                elif milestone.get("kind") not in {
                    "start_milestone",
                    "finish_milestone",
                }:
                    errors.append(
                        f"{context}: counterfactual milestone impact {milestone_id} is not a milestone"
                    )
    return errors


def _validate_declared_relationship_oracles(
    schedule: dict[str, Any],
    expected_times: dict[str, Any],
    activities_by_id: dict[str, dict[str, Any]],
    calendars_by_id: dict[str, dict[str, Any]],
    case_name: str,
    errors: list[str],
) -> None:
    """Independently verify the declared FS/SS/FF/SF lower bounds."""

    progress_policy = schedule.get("project", {}).get("progress_policy")
    for relationship in schedule.get("relationships", []):
        relationship_id = relationship.get("id", "<missing>")
        predecessor_id = relationship.get("predecessor_id")
        successor_id = relationship.get("successor_id")
        relation_type = relationship.get("type")
        lag = relationship.get("lag")
        if (
            predecessor_id not in expected_times
            or successor_id not in expected_times
            or predecessor_id not in activities_by_id
            or successor_id not in activities_by_id
            or relation_type not in {"FS", "SS", "FF", "SF"}
            or not _is_int(lag)
        ):
            continue
        if relationship.get("lag_calendar") is not None:
            # Active-profile validation reports the unsupported semantic separately.
            continue

        predecessor_record = expected_times.get(predecessor_id, {})
        successor_record = expected_times.get(successor_id, {})
        predecessor_event_name = "finish" if relation_type[0] == "F" else "start"
        successor_event_name = "start" if relation_type[1] == "S" else "finish"
        predecessor_event = predecessor_record.get(predecessor_event_name)

        predecessor_activity = activities_by_id[predecessor_id]
        successor_activity = activities_by_id[successor_id]
        successor_event = successor_record.get(successor_event_name)

        if successor_event_name == "start" and _is_int(successor_activity.get("actual_start")):
            if (
                progress_policy == "progress_override"
                and not _is_int(predecessor_activity.get("actual_finish"))
            ):
                # The profile explicitly allows unfinished predecessor logic to be
                # non-governing for remaining successor work in this state.
                continue
            if progress_policy == "retained_logic" and _is_int(
                successor_record.get("remaining_start")
            ):
                successor_event = successor_record["remaining_start"]

        calendar_id = successor_activity.get("calendar_id")
        calendar = calendars_by_id.get(calendar_id)
        if not (_is_int(predecessor_event) and _is_int(successor_event) and calendar):
            continue
        bound = _add_working_lag(
            predecessor_event, lag, calendar.get("working_intervals", [])
        )
        if bound is None:
            errors.append(
                f"{case_name}: relationship {relationship_id} cannot consume signed lag {lag} "
                f"from predecessor {predecessor_event_name} {predecessor_event} on successor calendar {calendar_id}"
            )
        elif successor_event < bound:
            errors.append(
                f"{case_name}: relationship {relationship_id} ({relation_type}) expected "
                f"{successor_id}.{successor_event_name} {successor_event} violates lower bound {bound} "
                f"from {predecessor_id}.{predecessor_event_name} {predecessor_event} with lag {lag}"
            )


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
    declared_reference = data.get("expected", {}).get("reference_status") == "declared"

    if schedule.get("schema_version") != _CANONICAL_SCHEMA_VERSION:
        errors.append(
            f"{case_name}: schedule schema_version must be {_CANONICAL_SCHEMA_VERSION}"
        )
    if schedule.get("semantic_profile") != _ACTIVE_SEMANTIC_PROFILE_ID:
        errors.append(
            f"{case_name}: semantic_profile must resolve to {_ACTIVE_SEMANTIC_PROFILE_ID}"
        )

    activity_ids = set(_entity_ids(activities, "activity", case_name, errors))
    relationship_ids = set(_entity_ids(relationships, "relationship", case_name, errors))
    calendar_ids = set(_entity_ids(calendars, "calendar", case_name, errors))
    resource_ids = set(_entity_ids(resources, "resource", case_name, errors))
    wbs_ids = set(_entity_ids(wbs_nodes, "WBS", case_name, errors))
    _entity_ids(operational_constraints, "operational constraint", case_name, errors)

    activities_by_id = {
        activity["id"]: activity for activity in activities if isinstance(activity.get("id"), str)
    }
    calendars_by_id = {
        calendar["id"]: calendar for calendar in calendars if isinstance(calendar.get("id"), str)
    }
    resources_by_id = {
        resource["id"]: resource for resource in resources if isinstance(resource.get("id"), str)
    }

    _validate_calendar_intervals(schedule, case_name, errors)

    for node in wbs_nodes:
        parent_id = node.get("parent_id")
        if parent_id is not None and parent_id not in wbs_ids:
            errors.append(
                f"{case_name}: WBS node {node.get('id')} references unknown parent {parent_id}"
            )
        if parent_id == node.get("id"):
            errors.append(f"{case_name}: WBS node {node.get('id')} cannot be its own parent")
    _validate_wbs_hierarchy(wbs_nodes, case_name, errors)

    horizon = schedule.get("time_axis", {}).get("horizon")
    valid_horizon = horizon if _is_int(horizon) else None
    mode_ids_by_activity: dict[str, set[str]] = {}
    in_progress_actual_starts: list[int] = []
    constraint_ids: list[str] = []
    for activity in activities:
        activity_id = activity.get("id", "<missing>")
        if activity.get("calendar_id") not in calendar_ids:
            errors.append(f"{case_name}: unknown activity calendar {activity.get('calendar_id')}")
        wbs_id = activity.get("wbs_id")
        if wbs_id is not None and wbs_id not in wbs_ids:
            errors.append(f"{case_name}: activity {activity_id} references unknown WBS {wbs_id}")

        actual_start = activity.get("actual_start")
        actual_finish = activity.get("actual_finish")
        if _is_int(actual_finish) and not _is_int(actual_start):
            errors.append(
                f"{case_name}: activity {activity_id} actual_finish requires actual_start"
            )
        if _is_int(actual_start) and _is_int(actual_finish) and actual_finish < actual_start:
            errors.append(
                f"{case_name}: activity {activity_id} actual_finish precedes actual_start"
            )
        if _is_int(actual_start) and not _is_int(actual_finish):
            in_progress_actual_starts.append(actual_start)

        for constraint in activity.get("constraints", []):
            constraint_id = constraint.get("id")
            if isinstance(constraint_id, str):
                constraint_ids.append(constraint_id)
            if declared_reference:
                if constraint.get("type") in {"fixed_start", "fixed_finish"}:
                    errors.append(
                        f"{case_name}: {constraint.get('type')} is preserved by the canonical model but "
                        f"is not executable under {_ACTIVE_SEMANTIC_PROFILE_ID}; use native_validation_only"
                    )

        frozen_state = activity.get("frozen_state")
        if isinstance(frozen_state, dict) and frozen_state.get("is_frozen") is True:
            frozen_start = frozen_state.get("frozen_start")
            frozen_finish = frozen_state.get("frozen_finish")
            if _is_int(frozen_start) and _is_int(frozen_finish):
                if frozen_start > frozen_finish:
                    errors.append(
                        f"{case_name}: activity {activity_id} frozen start exceeds frozen finish"
                    )
                if valid_horizon is not None and (
                    frozen_start < 0 or frozen_finish > valid_horizon
                ):
                    errors.append(
                        f"{case_name}: activity {activity_id} frozen coordinates lie outside horizon [0, {valid_horizon}]"
                    )

        assignment_resource_ids: list[str] = []
        for assignment in activity.get("assignments", []):
            resource_id = assignment.get("resource_id")
            if isinstance(resource_id, str):
                assignment_resource_ids.append(resource_id)
            if resource_id not in resource_ids:
                errors.append(f"{case_name}: unknown resource {resource_id}")
        for duplicate in _duplicate_values(assignment_resource_ids):
            errors.append(
                f"{case_name}: activity {activity_id} has duplicate assignment for {duplicate}"
            )

        modes = activity.get("eligible_modes", [])
        mode_ids = _entity_ids(modes, f"mode on activity {activity_id}", case_name, errors)
        mode_ids_by_activity[str(activity_id)] = set(mode_ids)
        for mode in modes:
            mode_id = mode.get("id", "<missing>")
            if activity.get("kind") in {"start_milestone", "finish_milestone"} and mode.get(
                "duration"
            ) != 0:
                errors.append(
                    f"{case_name}: milestone activity {activity_id} mode {mode_id} must have zero duration"
                )
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

    for duplicate in _duplicate_values(constraint_ids):
        errors.append(f"{case_name}: duplicate constraint ID {duplicate!r}")

    if in_progress_actual_starts:
        status_time = schedule.get("project", {}).get("status_time")
        if not _is_int(status_time):
            errors.append(
                f"{case_name}: project.status_time must be an integer when any activity is in progress"
            )
        else:
            if valid_horizon is not None and not (0 <= status_time <= valid_horizon):
                errors.append(
                    f"{case_name}: project.status_time lies outside horizon [0, {valid_horizon}]"
                )
            latest_actual_start = max(in_progress_actual_starts)
            if status_time < latest_actual_start:
                errors.append(
                    f"{case_name}: project.status_time {status_time} precedes in-progress actual start {latest_actual_start}"
                )

    for resource in resources:
        if resource.get("calendar_id") not in calendar_ids:
            errors.append(f"{case_name}: unknown resource calendar {resource.get('calendar_id')}")
        if declared_reference and (
            resource.get("type") != "exclusive" or resource.get("capacity") != 1
        ):
            errors.append(
                f"{case_name}: resource {resource.get('id')} uses {resource.get('type')} capacity "
                f"{resource.get('capacity')}, which is preserved by the canonical model but is not "
                f"executable under {_ACTIVE_SEMANTIC_PROFILE_ID}; use native_validation_only"
            )

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
        if declared_reference and lag_calendar is not None:
            errors.append(
                f"{case_name}: relationship {relationship.get('id')} explicit lag calendar "
                f"{lag_calendar} is preserved by the canonical model but is not executable under "
                f"{_ACTIVE_SEMANTIC_PROFILE_ID}; use native_validation_only"
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
        window_start = constraint.get("window_start")
        window_finish = constraint.get("window_finish")
        if valid_horizon is not None:
            if _is_int(window_start) and not (0 <= window_start <= valid_horizon):
                errors.append(
                    f"{case_name}: operational constraint {constraint_id} window_start lies outside horizon"
                )
            if _is_int(window_finish) and not (0 <= window_finish <= valid_horizon):
                errors.append(
                    f"{case_name}: operational constraint {constraint_id} window_finish lies outside horizon"
                )
        if _is_int(window_start) and _is_int(window_finish) and window_start >= window_finish:
            errors.append(
                f"{case_name}: operational constraint {constraint_id} window must satisfy start < finish"
            )

    expected_state_types = {"baseline": "baseline", "approved_forecast": "approved_forecast"}
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
        _validate_state_activity_references(
            state,
            state_name,
            activities_by_id,
            mode_ids_by_activity,
            resources_by_id,
            calendars_by_id,
            valid_horizon,
            case_name,
            errors,
            require_complete=state_name in {"approved_forecast", "proposed_scenario"} and isinstance(state, dict),
        )

    proposed = schedule.get("proposed_scenario")
    if isinstance(proposed, dict):
        if proposed.get("objective_policy_id") != _ACTIVE_OBJECTIVE_POLICY_ID:
            errors.append(
                f"{case_name}: proposed_scenario objective_policy_id must be {_ACTIVE_OBJECTIVE_POLICY_ID}"
            )
        errors.extend(
            validate_objective_vector(
                proposed.get("objective_vector"), schedule, f"{case_name}: proposed_scenario"
            )
        )

    expected = data.get("expected", {})
    expected_times = expected.get("activity_times", {})
    expected_ids = set(expected_times) if isinstance(expected_times, dict) else set()
    unknown_expected = expected_ids - activity_ids
    if unknown_expected:
        errors.append(
            f"{case_name}: expected activity_times contains unknown IDs {sorted(unknown_expected)}"
        )

    if schedule.get("project", {}).get("progress_policy") == "actual_dates" and expected.get(
        "reference_status"
    ) != "native_validation_only":
        errors.append(
            f"{case_name}: actual_dates policy is native-validation-only under {_ACTIVE_SEMANTIC_PROFILE_ID}"
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
            if not _is_int(start):
                errors.append(
                    f"{case_name}: declared expected start missing/non-integer for {activity_id}"
                )
            if not _is_int(finish):
                errors.append(
                    f"{case_name}: declared expected finish missing/non-integer for {activity_id}"
                )
            if _is_int(start) and _is_int(finish):
                if start > finish:
                    errors.append(f"{case_name}: expected start exceeds finish for {activity_id}")
                if valid_horizon is not None and (start < 0 or finish > valid_horizon):
                    errors.append(
                        f"{case_name}: expected activity {activity_id} lies outside horizon [0, {valid_horizon}]"
                    )
                activity = activities_by_id.get(activity_id)
                if activity and activity.get("kind") in {
                    "start_milestone",
                    "finish_milestone",
                } and start != finish:
                    errors.append(
                        f"{case_name}: expected milestone {activity_id} must have start equal to finish"
                    )
        project_finish = expected.get("project_finish")
        if not _is_int(project_finish):
            errors.append(f"{case_name}: declared expected project_finish must be an integer")
        else:
            if valid_horizon is not None and not (0 <= project_finish <= valid_horizon):
                errors.append(
                    f"{case_name}: declared project_finish lies outside horizon [0, {valid_horizon}]"
                )
            if expected_times and all(_is_int(record.get("finish")) for record in expected_times.values()):
                calculated_finish = max(record["finish"] for record in expected_times.values())
                if calculated_finish != project_finish:
                    errors.append(
                        f"{case_name}: declared project_finish {project_finish} does not equal max activity finish {calculated_finish}"
                    )
        if isinstance(expected_times, dict):
            _validate_declared_relationship_oracles(
                schedule,
                expected_times,
                activities_by_id,
                calendars_by_id,
                case_name,
                errors,
            )

    driving_relationships = expected.get("driving_relationships", [])
    for relationship_id in driving_relationships:
        if relationship_id not in relationship_ids:
            errors.append(
                f"{case_name}: expected driving relationship is unknown: {relationship_id}"
            )
    for duplicate in _duplicate_values(driving_relationships):
        errors.append(f"{case_name}: duplicate expected driving relationship {duplicate}")

    resource_order = expected.get("resource_order", [])
    for activity_id in resource_order:
        if activity_id not in activity_ids:
            errors.append(
                f"{case_name}: expected resource order references unknown activity {activity_id}"
            )
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
        except Exception as exc:
            errors.append(f"{path.name}: invalid JSON Schema: {exc}")

    canonical = schemas.get("canonical-schedule.schema.json")
    case_schema = schemas.get("semantic-test-case.schema.json")
    if canonical is None or case_schema is None:
        return Draft202012Validator({}, format_checker=FormatChecker()), errors

    registry = Registry().with_resource(
        "https://example.invalid/dsc/canonical-schedule.schema.json",
        Resource.from_contents(canonical),
    )
    return (
        Draft202012Validator(case_schema, registry=registry, format_checker=FormatChecker()),
        errors,
    )


def _catalogue_expected_row(data: dict[str, Any]) -> dict[str, str]:
    expected = data.get("expected", {})
    native = data.get("native_validation", {})
    project_finish = expected.get("project_finish")
    return {
        "case_id": str(data.get("case_id", "")),
        "category": str(data.get("category", "")),
        "title": str(data.get("title", "")),
        "reference_status": str(expected.get("reference_status", "")),
        "project_finish": "" if project_finish is None else str(project_finish),
        "p6_validation": str(native.get("p6", "")),
        "microsoft_project_validation": str(native.get("microsoft_project", "")),
    }


def validate_cases(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    validator, schema_errors = _schema_validators(root)
    errors.extend(schema_errors)
    cases_dir = root / "benchmarks" / "semantic" / "cases"
    case_files = sorted(cases_dir.glob("*.json"))
    discovered_names = {path.name for path in case_files}
    expected_names = set(_EXPECTED_CASE_ID_BY_FILE)
    if len(case_files) != len(_EXPECTED_CASE_IDS):
        errors.append(
            f"Expected {len(_EXPECTED_CASE_IDS)} case files, found {len(case_files)}"
        )
    for missing in sorted(expected_names - discovered_names):
        errors.append(f"Frozen semantic fixture is missing: {missing}")
    for unexpected in sorted(discovered_names - expected_names):
        errors.append(f"Unexpected semantic fixture identity: {unexpected}")

    fixtures: dict[str, dict[str, Any]] = {}
    for path in case_files:
        try:
            data = load_json(path)
        except Exception as exc:
            errors.append(f"{path.name}: invalid JSON: {exc}")
            continue
        case_id = data.get("case_id", "<missing>")
        expected_case_id = _EXPECTED_CASE_ID_BY_FILE.get(path.name)
        if expected_case_id is not None and case_id != expected_case_id:
            errors.append(
                f"{path.name}: frozen case_id must be {expected_case_id}, found {case_id}"
            )
        if case_id in fixtures:
            errors.append(f"Duplicate case_id: {case_id}")
        elif isinstance(case_id, str):
            fixtures[case_id] = data
        for error in sorted(validator.iter_errors(data), key=lambda item: list(item.path)):
            location = ".".join(str(part) for part in error.path)
            errors.append(f"{path.name}:{location}: {error.message}")
        errors.extend(validate_case_document(data, path.name))

    catalogue = root / "benchmarks" / "semantic" / "catalogue.csv"
    try:
        with catalogue.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            fieldnames = reader.fieldnames or []
    except Exception as exc:
        errors.append(f"catalogue.csv: {exc}")
        return errors
    if fieldnames != _EXPECTED_CATALOGUE_FIELDS:
        errors.append(
            f"catalogue.csv: header must equal {','.join(_EXPECTED_CATALOGUE_FIELDS)}"
        )
    if len(rows) != len(_EXPECTED_CASE_IDS):
        errors.append(
            f"Expected {len(_EXPECTED_CASE_IDS)} catalogue rows, found {len(rows)}"
        )
    catalogue_ids = [row.get("case_id") for row in rows]
    if tuple(catalogue_ids) != _EXPECTED_CASE_IDS:
        errors.append("Catalogue case IDs/order do not match the frozen preregistered identity sequence")
    for duplicate in _duplicate_values(catalogue_ids):
        errors.append(f"Duplicate catalogue case_id: {duplicate}")
    if set(catalogue_ids) != set(fixtures):
        errors.append("Catalogue case IDs do not match fixture case IDs")

    for row in rows:
        case_id = row.get("case_id")
        fixture = fixtures.get(case_id) if isinstance(case_id, str) else None
        if fixture is None:
            continue
        expected_row = _catalogue_expected_row(fixture)
        for field in _EXPECTED_CATALOGUE_FIELDS:
            if row.get(field, "") != expected_row[field]:
                errors.append(
                    f"catalogue.csv: {case_id} field {field}={row.get(field)!r} "
                    f"does not match fixture value {expected_row[field]!r}"
                )
    return errors


def validate_registers(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    register_dir = root / "registers"
    discovered = {path.name for path in register_dir.glob("*.csv")}
    expected_names = set(_EXPECTED_REGISTERS)
    for missing in sorted(expected_names - discovered):
        errors.append(f"Required register is missing: {missing}")
    for unexpected in sorted(discovered - expected_names):
        errors.append(f"Unexpected register file: {unexpected}")

    for name in sorted(discovered & expected_names):
        path = register_dir / name
        with path.open("r", encoding="utf-8", newline="") as f:
            rows = list(csv.reader(f))
        if len(rows) != 1 or not rows[0] or any(not header for header in rows[0]):
            errors.append(f"{path.name}: expected exactly one non-empty header row")
            continue
        for duplicate in _duplicate_values(rows[0] if rows else []):
            errors.append(f"{path.name}: duplicate header {duplicate}")
        expected_header = _EXPECTED_REGISTERS[name]
        if rows[0] != expected_header:
            errors.append(
                f"{path.name}: header sequence does not match the frozen register definition"
            )
    return errors


def validate_configuration(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    config_dir = root / "config"
    discovered = {path.name for path in config_dir.glob("*.json")}
    for missing in sorted(_EXPECTED_CONFIG_FILES - discovered):
        errors.append(f"Required configuration is missing: {missing}")
    for unexpected in sorted(discovered - _EXPECTED_CONFIG_FILES):
        errors.append(f"Unexpected configuration file: {unexpected}")

    checks = [
        ("objective-policy-v0.3.json", _EXPECTED_OBJECTIVE_POLICY),
        ("deterministic-execution-profile-v0.1.json", _EXPECTED_DETERMINISTIC_PROFILE),
        ("semantic-profile-reference-v0.1.json", _EXPECTED_SEMANTIC_PROFILE_V1),
        ("semantic-profile-reference-v0.2.json", _EXPECTED_SEMANTIC_PROFILE_V2),
        ("semantic-profile-reference-v0.3.json", _EXPECTED_SEMANTIC_PROFILE),
    ]
    for name, expected in checks:
        path = config_dir / name
        if not path.exists():
            continue
        try:
            actual = load_json(path)
        except Exception as exc:
            errors.append(f"{name}: {exc}")
            continue
        if actual != expected:
            errors.append(f"{name}: complete frozen definition does not match the authoritative value")
    return errors


def validate_consolidated_protocol(root: Path = ROOT) -> list[str]:
    path = root / "PHASE-0-PROTOCOL-CONSOLIDATED.md"
    if not path.exists():
        return ["PHASE-0-PROTOCOL-CONSOLIDATED.md is missing"]
    try:
        authoritative_sources(root)
        expected = render_consolidated_protocol(root)
    except Exception as exc:
        return [f"Authoritative protocol chapter validation failed: {exc}"]
    actual = path.read_text(encoding="utf-8")
    if actual != expected:
        return [
            "PHASE-0-PROTOCOL-CONSOLIDATED.md does not match the numbered authoritative documents"
        ]
    return []


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
    for line_number, line in enumerate(
        manifest.read_text(encoding="utf-8").splitlines(), start=1
    ):
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
    print("- 50 exact preregistered semantic fixtures validated")
    print("- JSON Schemas resolved and meta-validated")
    print("- IDs, references, hierarchies, calendars, status, states, expected spans, and relationship formulas validated")
    print("- Frozen scenarios, explanation causes, counterfactual paths, spans, and objective vectors validated")
    print("- Register filenames, header sequences, and authoritative protocol chapters validated")
    print("- Objective, semantic, and deterministic profiles match frozen definitions")
    print("- Consolidated protocol matches authoritative documents")
    print("- SHA-256 manifest completeness and hashes verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
