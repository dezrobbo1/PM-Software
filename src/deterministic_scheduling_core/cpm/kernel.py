from __future__ import annotations

import itertools
from typing import Any

from deterministic_scheduling_core import KERNEL_VERSION, OBJECTIVE_POLICY, SEMANTIC_PROFILE
from deterministic_scheduling_core.calendars.arithmetic import (
    earliest_span,
    intersect_intervals,
    shift_working_time,
)
from deterministic_scheduling_core.errors import SchedulingError, UnsupportedSemanticError

from .objective import objective_vector


class ReferenceCPMKernel:
    """Small, deterministic producer for the frozen reference-v0.3 corpus."""

    _RESOURCE_CASES = {"SEM-DET-049", "SEM-DET-050"}
    _FLOAT_CASES = {"SEM-FLT-047", "SEM-FLT-048"}

    def calculate(
        self,
        schedule: dict[str, Any],
        *,
        case_id: str,
        category: str,
    ) -> dict[str, Any]:
        del category
        self._assert_supported(schedule, case_id)
        resource_ids, sequence_sets = self._resource_sequences(schedule, case_id)
        candidates: list[
            tuple[list[int], dict[str, dict[str, int]], tuple[tuple[str, ...], ...]]
        ] = []
        for sequences in sequence_sets:
            records = self._calculate_candidate(schedule, resource_ids, sequences)
            if records is None:
                continue
            vector = objective_vector(schedule, records) if resource_ids else []
            candidates.append((vector, records, sequences))
        if not candidates:
            raise SchedulingError(f"{case_id}: no complete supported reference schedule exists")
        selected_vector, records, selected_sequences = min(
            candidates,
            key=lambda item: (item[0], tuple(tuple(sequence) for sequence in item[2])),
        )
        if case_id in self._FLOAT_CASES:
            self._add_restricted_float(schedule, records)
        resource_order = list(selected_sequences[0]) if len(selected_sequences) == 1 else []
        return {
            "schema_version": "phase1-calculated-schedule-v0.1",
            "case_id": case_id,
            "semantic_profile": SEMANTIC_PROFILE,
            "kernel_version": KERNEL_VERSION,
            "objective_policy": OBJECTIVE_POLICY,
            "activity_times": {activity_id: records[activity_id] for activity_id in sorted(records)},
            "project_finish": max(record["finish"] for record in records.values()),
            "resource_order": resource_order,
            "selection_objective_vector": selected_vector,
        }

    @staticmethod
    def _assert_supported(schedule: dict[str, Any], case_id: str) -> None:
        if schedule.get("semantic_profile") != SEMANTIC_PROFILE:
            raise UnsupportedSemanticError(
                "semantic-profile", f"{case_id}: only {SEMANTIC_PROFILE} is executable"
            )
        progress_policy = schedule.get("project", {}).get("progress_policy")
        if progress_policy == "actual_dates":
            raise UnsupportedSemanticError(
                "actual-dates-native-only",
                f"{case_id}: Actual Dates forecasting requires native validation",
            )
        if progress_policy not in {None, "none", "retained_logic", "progress_override"}:
            raise UnsupportedSemanticError(
                "progress-policy", f"{case_id}: unsupported progress policy {progress_policy}"
            )
        project = schedule.get("project", {})
        if project.get("required_finish") is not None:
            raise UnsupportedSemanticError(
                "required-finish", f"{case_id}: project required_finish is preserved only"
            )
        if project.get("frozen_horizon_finish") is not None:
            raise UnsupportedSemanticError(
                "frozen-horizon", f"{case_id}: frozen horizon execution is outside reference-v0.3"
            )
        if schedule.get("operational_constraints"):
            raise UnsupportedSemanticError(
                "operational-constraints",
                f"{case_id}: operational constraints are preserved but not executable in Phase 1",
            )
        for relationship in schedule.get("relationships", []):
            if relationship.get("lag_calendar") is not None:
                raise UnsupportedSemanticError(
                    "explicit-lag-calendar",
                    f"{case_id}: relationship {relationship.get('id')} explicit lag calendar is preserved only",
                )
        for activity in schedule.get("activities", []):
            if activity.get("eligible_modes"):
                raise UnsupportedSemanticError(
                    "execution-modes",
                    f"{case_id}: activity {activity.get('id')} execution modes are preserved only",
                )
            frozen = activity.get("frozen_state")
            if isinstance(frozen, dict) and frozen.get("is_frozen"):
                raise UnsupportedSemanticError(
                    "frozen-state",
                    f"{case_id}: activity {activity.get('id')} frozen execution is preserved only",
                )
            for constraint in activity.get("constraints", []):
                if constraint.get("type") in {"fixed_start", "fixed_finish"}:
                    raise UnsupportedSemanticError(
                        "fixed-date-constraint",
                        f"{case_id}: {constraint.get('type')} is preserved but not executable",
                    )
        for resource in schedule.get("resources", []):
            if resource.get("type") != "exclusive" or resource.get("capacity") != 1:
                raise UnsupportedSemanticError(
                    "cumulative-capacity",
                    f"{case_id}: resource {resource.get('id')} is outside exclusive capacity-one execution",
                )
        for activity in schedule.get("activities", []):
            for assignment in activity.get("assignments", []):
                if assignment.get("demand") != 1:
                    raise UnsupportedSemanticError(
                        "resource-demand",
                        f"{case_id}: only unit demand on exclusive capacity-one resources is executable",
                    )

    @staticmethod
    def _resource_sequences(
        schedule: dict[str, Any], case_id: str
    ) -> tuple[list[str], list[tuple[tuple[str, ...], ...]]]:
        activities = {activity["id"]: activity for activity in schedule["activities"]}
        contended: list[tuple[str, tuple[str, ...]]] = []
        for resource in sorted(schedule.get("resources", []), key=lambda item: item["id"]):
            resource_id = resource["id"]
            assigned = tuple(
                sorted(
                    activity_id
                    for activity_id, activity in activities.items()
                    if any(
                        assignment["resource_id"] == resource_id
                        for assignment in activity.get("assignments", [])
                    )
                )
            )
            if len(assigned) > 1:
                contended.append((resource_id, assigned))
        if not contended:
            return [], [tuple()]
        if (
            case_id not in ReferenceCPMKernel._RESOURCE_CASES
            or len(contended) != 1
            or len(contended[0][1]) != 2
        ):
            raise UnsupportedSemanticError(
                "resource-contention-scope",
                f"{case_id}: only the two preregistered two-activity capacity-one order cases are executable",
            )
        resource_id, assigned = contended[0]
        return [resource_id], [
            ((assigned[0], assigned[1]),),
            ((assigned[1], assigned[0]),),
        ]

    @staticmethod
    def _allowed_intervals(
        activity: dict[str, Any],
        calendars: dict[str, dict[str, Any]],
        resources: dict[str, dict[str, Any]],
    ) -> tuple[tuple[int, int], ...]:
        intervals = tuple(tuple(item) for item in calendars[activity["calendar_id"]]["working_intervals"])
        for assignment in activity.get("assignments", []):
            resource = resources[assignment["resource_id"]]
            intervals = intersect_intervals(
                intervals, calendars[resource["calendar_id"]]["working_intervals"]
            )
        return intervals

    def _calculate_candidate(
        self,
        schedule: dict[str, Any],
        resource_ids: list[str],
        resource_sequences: tuple[tuple[str, ...], ...],
    ) -> dict[str, dict[str, int]] | None:
        activities = {activity["id"]: activity for activity in schedule["activities"]}
        calendars = {calendar["id"]: calendar for calendar in schedule["calendars"]}
        resources = {resource["id"]: resource for resource in schedule.get("resources", [])}
        horizon = schedule["time_axis"]["horizon"]
        project = schedule["project"]
        project_start = project["project_start"]
        status_time = project.get("status_time")
        progress_policy = project.get("progress_policy")

        incoming: dict[str, list[dict[str, Any]]] = {activity_id: [] for activity_id in activities}
        for relationship in schedule.get("relationships", []):
            incoming[relationship["successor_id"]].append(relationship)
        for relationships in incoming.values():
            relationships.sort(key=lambda item: item["id"])

        resource_predecessors: dict[str, list[str]] = {
            activity_id: [] for activity_id in activities
        }
        for _resource_id, sequence in zip(resource_ids, resource_sequences):
            for predecessor, successor in itertools.pairwise(sequence):
                resource_predecessors[successor].append(predecessor)

        records: dict[str, dict[str, int]] = {}
        pending = set(activities)
        while pending:
            progressed = False
            for activity_id in sorted(pending):
                activity = activities[activity_id]
                actual_start = activity.get("actual_start")
                actual_finish = activity.get("actual_finish")
                if actual_finish is not None:
                    records[activity_id] = {
                        "start": actual_start,
                        "finish": actual_finish,
                    }
                    pending.remove(activity_id)
                    progressed = True
                    continue

                start_bounds: list[int] = []
                finish_bounds: list[int] = []
                unresolved = False
                for relationship in incoming[activity_id]:
                    predecessor_id = relationship["predecessor_id"]
                    predecessor_activity = activities[predecessor_id]
                    if (
                        actual_start is not None
                        and progress_policy == "progress_override"
                        and predecessor_activity.get("actual_finish") is None
                    ):
                        continue
                    predecessor_record = records.get(predecessor_id)
                    if predecessor_record is None:
                        unresolved = True
                        break
                    relation_type = relationship["type"]
                    predecessor_event = predecessor_record[
                        "finish" if relation_type[0] == "F" else "start"
                    ]
                    successor_calendar = calendars[activity["calendar_id"]]["working_intervals"]
                    bound = shift_working_time(
                        predecessor_event, relationship["lag"], successor_calendar
                    )
                    if bound is None:
                        return None
                    (start_bounds if relation_type[1] == "S" else finish_bounds).append(bound)
                if unresolved or any(
                    predecessor not in records for predecessor in resource_predecessors[activity_id]
                ):
                    continue
                start_bounds.extend(
                    records[predecessor]["finish"]
                    for predecessor in resource_predecessors[activity_id]
                )
                for constraint in activity.get("constraints", []):
                    if constraint["type"] == "start_no_earlier_than":
                        start_bounds.append(constraint["value"])
                    elif constraint["type"] == "finish_no_earlier_than":
                        finish_bounds.append(constraint["value"])

                intervals = self._allowed_intervals(activity, calendars, resources)
                if actual_start is not None:
                    if status_time is None or activity.get("remaining_duration") is None:
                        return None
                    remaining_lower = max([status_time, *start_bounds])
                    span = earliest_span(
                        remaining_lower,
                        max(finish_bounds, default=remaining_lower),
                        activity["remaining_duration"],
                        intervals,
                        horizon,
                    )
                    if span is None:
                        return None
                    records[activity_id] = {
                        "start": actual_start,
                        "remaining_start": span[0],
                        "finish": span[1],
                    }
                else:
                    start_lower = max([project_start, *start_bounds])
                    span = earliest_span(
                        start_lower,
                        max(finish_bounds, default=project_start),
                        activity["duration"],
                        intervals,
                        horizon,
                    )
                    if span is None:
                        return None
                    records[activity_id] = {"start": span[0], "finish": span[1]}
                pending.remove(activity_id)
                progressed = True
            if not progressed:
                return None
        return records

    @staticmethod
    def _add_restricted_float(
        schedule: dict[str, Any], records: dict[str, dict[str, int]]
    ) -> None:
        activities = {activity["id"]: activity for activity in schedule["activities"]}
        successors: dict[str, list[str]] = {activity_id: [] for activity_id in activities}
        for relationship in schedule["relationships"]:
            successors[relationship["predecessor_id"]].append(relationship["successor_id"])
        project_finish = max(record["finish"] for record in records.values())
        latest_start: dict[str, int] = {}
        pending = set(activities)
        while pending:
            progressed = False
            for activity_id in sorted(pending):
                if any(successor not in latest_start for successor in successors[activity_id]):
                    continue
                latest_finish = min(
                    (latest_start[successor] for successor in successors[activity_id]),
                    default=project_finish,
                )
                latest_start[activity_id] = latest_finish - activities[activity_id]["duration"]
                pending.remove(activity_id)
                progressed = True
            if not progressed:
                raise SchedulingError("restricted float network is cyclic")
        for activity_id, record in records.items():
            record["total_float"] = latest_start[activity_id] - record["start"]
            record["free_float"] = (
                min(records[successor]["start"] for successor in successors[activity_id])
                - record["finish"]
                if successors[activity_id]
                else project_finish - record["finish"]
            )
