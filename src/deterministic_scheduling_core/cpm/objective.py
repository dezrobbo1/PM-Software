from __future__ import annotations

from typing import Any

from deterministic_scheduling_core.calendars.arithmetic import (
    intersect_intervals,
    productive_segments,
)


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


def objective_vector(
    schedule: dict[str, Any], records: dict[str, dict[str, int]]
) -> list[int]:
    """Encode objective-v0.3 for a complete supported candidate."""

    activities = {item["id"]: item for item in schedule["activities"]}
    resources = {item["id"]: item for item in schedule.get("resources", [])}
    calendars = {item["id"]: item for item in schedule["calendars"]}

    vector: list[int] = [0]
    milestone_groups: dict[int, list[str]] = {}
    for activity_id, activity in activities.items():
        if (
            activity["kind"] in {"start_milestone", "finish_milestone"}
            and activity.get("milestone_priority", 0) > 0
            and activity.get("due_time") is not None
        ):
            milestone_groups.setdefault(activity["milestone_priority"], []).append(activity_id)
    for priority in sorted(milestone_groups, reverse=True):
        lateness = [
            max(0, records[activity_id]["finish"] - activities[activity_id]["due_time"])
            for activity_id in sorted(milestone_groups[priority])
        ]
        vector.extend((sum(lateness), max(lateness, default=0), *lateness))

    project_finish = max(record["finish"] for record in records.values())
    approved = schedule.get("approved_forecast")
    movement = 0
    if isinstance(approved, dict):
        approved_by_id = {
            state["activity_id"]: state for state in approved.get("activity_states", [])
        }
        movement = sum(
            abs(records[activity_id]["start"] - approved_by_id[activity_id]["start"])
            + abs(records[activity_id]["finish"] - approved_by_id[activity_id]["finish"])
            for activity_id in sorted(records)
        )

    resource_segments: dict[str, list[tuple[int, int, int]]] = {
        resource_id: [] for resource_id in resources
    }
    for activity_id, record in records.items():
        activity = activities[activity_id]
        segments = productive_segments(
            record.get("remaining_start", record["start"]),
            record["finish"],
            _allowed_intervals(activity, calendars, resources),
        )
        for assignment in activity.get("assignments", []):
            resource_segments[assignment["resource_id"]].extend(
                (start, finish, assignment["demand"]) for start, finish in segments
            )

    mobilisation_blocks = 0
    peak_sum = 0
    for resource_id in sorted(resources):
        segments = sorted(resource_segments[resource_id])
        merged: list[list[int]] = []
        for start, finish, _ in segments:
            if not merged or start > merged[-1][1]:
                merged.append([start, finish])
            else:
                merged[-1][1] = max(merged[-1][1], finish)
        mobilisation_blocks += len(merged)
        events: dict[int, int] = {}
        for start, finish, demand in segments:
            events[start] = events.get(start, 0) + demand
            events[finish] = events.get(finish, 0) - demand
        concurrent = peak = 0
        for coordinate in sorted(events):
            concurrent += events[coordinate]
            peak = max(peak, concurrent)
        peak_sum += peak

    vector.extend((project_finish, movement, 0, mobilisation_blocks, peak_sum, 0))
    resource_ids = sorted(resources)
    for activity_id in sorted(activities):
        record = records[activity_id]
        demand_by_resource = {
            assignment["resource_id"]: assignment["demand"]
            for assignment in activities[activity_id].get("assignments", [])
        }
        vector.extend((record["start"], record["finish"], 0))
        vector.extend(demand_by_resource.get(resource_id, 0) for resource_id in resource_ids)
    return vector
