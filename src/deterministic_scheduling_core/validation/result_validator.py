from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from deterministic_scheduling_core import KERNEL_VERSION, OBJECTIVE_POLICY, SEMANTIC_PROFILE
from deterministic_scheduling_core.canonical.model import LoadedCase
from deterministic_scheduling_core.provenance.canonical_json import canonical_bytes


@dataclass(frozen=True, slots=True)
class ValidationReport:
    case_id: str
    status: str
    checks: tuple[str, ...]
    errors: tuple[str, ...]

    def as_document(self, *, input_hash: str, output_hash: str) -> dict[str, Any]:
        return {
            "schema_version": "phase1-validation-evidence-v0.1",
            "case_id": self.case_id,
            "validator_version": "independent-reference-validator-v0.1.0",
            "input_hash": input_hash,
            "output_hash": output_hash,
            "status": self.status,
            "checks": list(self.checks),
            "errors": list(self.errors),
        }


def _units(intervals: list[list[int]]) -> frozenset[int]:
    return frozenset(unit for start, finish in intervals for unit in range(start, finish))


def _finish_from_units(
    start: int, duration: int, working: frozenset[int], horizon: int
) -> int | None:
    if duration == 0:
        return start if start in working else None
    if start not in working:
        return None
    remaining = duration
    for coordinate in range(start, horizon):
        if coordinate in working:
            remaining -= 1
            if remaining == 0:
                return coordinate + 1
    return None


def _lag_from_units(
    anchor: int, lag: int, working: frozenset[int], horizon: int
) -> int | None:
    if lag == 0:
        return anchor
    if lag > 0:
        available = [unit for unit in range(max(0, anchor), horizon) if unit in working]
        return available[lag - 1] + 1 if len(available) >= lag else None
    available = [unit for unit in range(min(anchor, horizon) - 1, -1, -1) if unit in working]
    return available[-lag - 1] if len(available) >= -lag else None


def _earliest_span_units(
    start_lower: int,
    finish_lower: int,
    duration: int,
    working: frozenset[int],
    horizon: int,
) -> tuple[int, int] | None:
    for start in range(max(0, start_lower), horizon + 1):
        finish = _finish_from_units(start, duration, working, horizon)
        if finish is not None and finish >= finish_lower:
            return start, finish
    return None


class IndependentResultValidator:
    """Validate output without invoking the CPM producer or its arithmetic path."""

    CHECKS = (
        "complete_result_coverage",
        "productive_activity_spans",
        "relationship_formulas_and_signed_lag",
        "project_and_date_lower_bounds",
        "milestone_zero_span",
        "actual_and_status_immutability",
        "exclusive_capacity_one_feasibility",
        "deterministic_project_finish",
        "restricted_float",
        "curated_governing_relationships",
        "canonical_objective_vector",
        "frozen_declared_oracle_equality",
        "deterministic_serialisation_domain",
    )

    def validate(self, case: LoadedCase, result: dict[str, Any]) -> ValidationReport:
        errors: list[str] = []
        schedule = case.schedule
        activities = {activity["id"]: activity for activity in schedule["activities"]}
        calendars = {calendar["id"]: calendar for calendar in schedule["calendars"]}
        resources = {resource["id"]: resource for resource in schedule.get("resources", [])}
        for relationship in schedule.get("relationships", []):
            if relationship.get("lag_calendar") is not None:
                errors.append("explicit alternate lag calendars are not executable")
        for resource in resources.values():
            if resource.get("type") != "exclusive" or resource.get("capacity") != 1:
                errors.append("cumulative resource capacity is not executable")
        for activity in activities.values():
            if activity.get("eligible_modes"):
                errors.append("execution modes are not executable")
            if any(
                constraint.get("type") in {"fixed_start", "fixed_finish"}
                for constraint in activity.get("constraints", [])
            ):
                errors.append("fixed-start and fixed-finish constraints are not executable")
        if schedule.get("operational_constraints"):
            errors.append("operational constraints are not executable in the reference kernel")
        try:
            canonical_bytes(result)
        except (TypeError, ValueError) as exc:
            errors.append(f"calculated output is outside canonical serialisation: {exc}")
        records = result.get("activity_times")
        if result.get("schema_version") != "phase1-calculated-schedule-v0.1":
            errors.append("calculated output schema_version is not pinned")
        if result.get("case_id") != case.case_id:
            errors.append("calculated output case_id does not match its input")
        if result.get("semantic_profile") != SEMANTIC_PROFILE:
            errors.append("calculated output semantic profile is not reference-v0.3")
        if result.get("kernel_version") != KERNEL_VERSION:
            errors.append("calculated output kernel version is not pinned")
        if result.get("objective_policy") != OBJECTIVE_POLICY:
            errors.append("calculated output objective policy is not pinned")
        if not isinstance(records, dict):
            errors.append("activity_times must be an object")
            return ValidationReport(case.case_id, "fail", self.CHECKS, tuple(errors))
        coverage_complete = set(records) == set(activities)
        if not coverage_complete:
            missing = sorted(set(activities) - set(records))
            extra = sorted(set(records) - set(activities))
            errors.append(f"activity result coverage differs: missing={missing}, extra={extra}")
        records_structurally_complete = coverage_complete and all(
            isinstance(record, dict)
            and isinstance(record.get("start"), int)
            and not isinstance(record.get("start"), bool)
            and isinstance(record.get("finish"), int)
            and not isinstance(record.get("finish"), bool)
            for record in records.values()
        )

        working_by_calendar = {
            calendar_id: _units(calendar["working_intervals"])
            for calendar_id, calendar in calendars.items()
        }
        horizon = schedule["time_axis"]["horizon"]
        project = schedule["project"]
        project_start = project["project_start"]
        status_time = project.get("status_time")
        progress_policy = project.get("progress_policy")

        allowed_by_activity: dict[str, frozenset[int]] = {}
        for activity_id, activity in activities.items():
            allowed = working_by_calendar[activity["calendar_id"]]
            for assignment in activity.get("assignments", []):
                resource = resources[assignment["resource_id"]]
                allowed &= working_by_calendar[resource["calendar_id"]]
            allowed_by_activity[activity_id] = allowed

        for activity_id in sorted(set(records) & set(activities)):
            activity = activities[activity_id]
            record = records[activity_id]
            if not isinstance(record, dict):
                errors.append(f"{activity_id}: result must be an object")
                continue
            start = record.get("start")
            finish = record.get("finish")
            if not (
                isinstance(start, int)
                and not isinstance(start, bool)
                and isinstance(finish, int)
                and not isinstance(finish, bool)
            ):
                errors.append(f"{activity_id}: start and finish must be integers")
                continue
            if start > finish or start < 0 or finish > horizon:
                errors.append(f"{activity_id}: result span lies outside the canonical horizon")
            actual_start = activity.get("actual_start")
            actual_finish = activity.get("actual_finish")
            if actual_finish is not None:
                if start != actual_start or finish != actual_finish:
                    errors.append(f"{activity_id}: completed actual coordinates changed")
            elif actual_start is not None:
                remaining_start = record.get("remaining_start")
                if start != actual_start:
                    errors.append(f"{activity_id}: actual_start changed")
                if not isinstance(remaining_start, int):
                    errors.append(f"{activity_id}: remaining_start is required")
                else:
                    if status_time is None or remaining_start < status_time:
                        errors.append(f"{activity_id}: remaining work begins before status_time")
                    derived_finish = _finish_from_units(
                        remaining_start,
                        activity["remaining_duration"],
                        allowed_by_activity[activity_id],
                        horizon,
                    )
                    if finish != derived_finish:
                        errors.append(f"{activity_id}: remaining-duration span is invalid")
            else:
                if start < project_start:
                    errors.append(f"{activity_id}: starts before project_start")
                derived_finish = _finish_from_units(
                    start, activity["duration"], allowed_by_activity[activity_id], horizon
                )
                if finish != derived_finish:
                    errors.append(f"{activity_id}: productive-duration span is invalid")
            if activity["kind"] in {"start_milestone", "finish_milestone"} and start != finish:
                errors.append(f"{activity_id}: milestone is not zero-span")
            for constraint in activity.get("constraints", []):
                if constraint["type"] == "start_no_earlier_than" and start < constraint["value"]:
                    errors.append(f"{activity_id}: violates start_no_earlier_than")
                if constraint["type"] == "finish_no_earlier_than" and finish < constraint["value"]:
                    errors.append(f"{activity_id}: violates finish_no_earlier_than")

        relationship_bounds: dict[str, tuple[int, int]] = {}
        for relationship in schedule.get("relationships", []):
            predecessor_id = relationship["predecessor_id"]
            successor_id = relationship["successor_id"]
            if predecessor_id not in records or successor_id not in records:
                continue
            predecessor_activity = activities[predecessor_id]
            successor_activity = activities[successor_id]
            if (
                successor_activity.get("actual_start") is not None
                and progress_policy == "progress_override"
                and predecessor_activity.get("actual_finish") is None
            ):
                continue
            relation_type = relationship["type"]
            predecessor_event = records[predecessor_id][
                "finish" if relation_type[0] == "F" else "start"
            ]
            bound = _lag_from_units(
                predecessor_event,
                relationship["lag"],
                working_by_calendar[successor_activity["calendar_id"]],
                horizon,
            )
            if bound is None:
                errors.append(f"{relationship['id']}: signed lag cannot be consumed")
                continue
            successor_event_name = "start" if relation_type[1] == "S" else "finish"
            successor_event = records[successor_id][successor_event_name]
            if (
                successor_event_name == "start"
                and successor_activity.get("actual_start") is not None
            ):
                successor_event = records[successor_id].get("remaining_start")
            if not isinstance(successor_event, int) or successor_event < bound:
                errors.append(
                    f"{relationship['id']}: {relation_type} signed-lag lower bound is violated"
                )
            else:
                relationship_bounds[relationship["id"]] = (bound, successor_event)

        resource_units: dict[str, dict[int, list[str]]] = {
            resource_id: {} for resource_id in resources
        }
        for activity_id, record in records.items():
            if activity_id not in activities or not isinstance(record, dict):
                continue
            start = record.get("remaining_start", record.get("start"))
            finish = record.get("finish")
            if not isinstance(start, int) or not isinstance(finish, int):
                continue
            used_units = [
                unit
                for unit in range(start, finish)
                if unit in allowed_by_activity[activity_id]
            ]
            for assignment in activities[activity_id].get("assignments", []):
                resource_id = assignment["resource_id"]
                for unit in used_units:
                    resource_units[resource_id].setdefault(unit, []).append(activity_id)
        for resource_id, by_unit in resource_units.items():
            for unit, activity_ids in sorted(by_unit.items()):
                if len(activity_ids) > 1:
                    errors.append(
                        f"resource {resource_id} is over capacity at {unit}: {sorted(activity_ids)}"
                    )
                    break

        valid_finishes = [
            record.get("finish")
            for record in records.values()
            if isinstance(record, dict) and isinstance(record.get("finish"), int)
        ]
        derived_project_finish = max(valid_finishes) if valid_finishes else None
        if result.get("project_finish") != derived_project_finish:
            errors.append("project_finish is not the maximum calculated finish")

        if case.case_id in {"SEM-FLT-047", "SEM-FLT-048"} and records_structurally_complete:
            self._validate_float(schedule, records, derived_project_finish, errors)
        elif any(
            "total_float" in record or "free_float" in record
            for record in records.values()
            if isinstance(record, dict)
        ):
            errors.append("float was emitted outside the two reviewed fixtures")

        if records_structurally_complete:
            self._validate_curated_drivers(
                case, records, activities, allowed_by_activity, working_by_calendar, errors
            )
        selected_vector = result.get("selection_objective_vector")
        if (
            case.case_id in {"SEM-DET-049", "SEM-DET-050"}
            and records_structurally_complete
        ):
            recomputed = self._objective_vector(schedule, records, allowed_by_activity)
            if selected_vector != recomputed:
                errors.append("selection objective vector does not equal objective-v0.3 recomputation")
        elif selected_vector != []:
            errors.append("non-contention semantic execution must not publish an objective vector")

        expected = case.expected
        for field in ("activity_times", "project_finish", "resource_order"):
            if result.get(field) != expected.get(field):
                errors.append(f"calculated {field} differs from the frozen declared oracle")
        if expected.get("reference_status") != "declared":
            errors.append("native-validation-only case cannot be validated as a calculated reference result")

        status = "pass" if not errors else "fail"
        return ValidationReport(case.case_id, status, self.CHECKS, tuple(errors))

    @staticmethod
    def _validate_float(
        schedule: dict[str, Any],
        records: dict[str, dict[str, Any]],
        project_finish: int | None,
        errors: list[str],
    ) -> None:
        if project_finish is None:
            return
        activities = {activity["id"]: activity for activity in schedule["activities"]}
        successors: dict[str, list[str]] = {activity_id: [] for activity_id in activities}
        for relationship in schedule["relationships"]:
            if relationship["type"] != "FS" or relationship["lag"] != 0:
                errors.append("restricted float case is not an FS-zero network")
                return
            successors[relationship["predecessor_id"]].append(relationship["successor_id"])
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
                errors.append("restricted float network is cyclic")
                return
        for activity_id, record in records.items():
            total_float = latest_start[activity_id] - record["start"]
            free_float = (
                min(records[successor]["start"] for successor in successors[activity_id])
                - record["finish"]
                if successors[activity_id]
                else project_finish - record["finish"]
            )
            if record.get("total_float") != total_float:
                errors.append(f"{activity_id}: total_float is incorrect")
            if record.get("free_float") != free_float:
                errors.append(f"{activity_id}: free_float is incorrect")

    @staticmethod
    def _validate_curated_drivers(
        case: LoadedCase,
        records: dict[str, dict[str, Any]],
        activities: dict[str, dict[str, Any]],
        allowed_by_activity: dict[str, frozenset[int]],
        calendar_units: dict[str, frozenset[int]],
        errors: list[str],
    ) -> None:
        schedule = case.schedule
        relationships = {
            relationship["id"]: relationship for relationship in schedule["relationships"]
        }
        project = schedule["project"]
        horizon = schedule["time_axis"]["horizon"]
        for relationship_id in case.expected.get("driving_relationships", []):
            relationship = relationships.get(relationship_id)
            if relationship is None:
                errors.append(f"curated driver {relationship_id} is unresolved")
                continue
            predecessor = activities[relationship["predecessor_id"]]
            successor = activities[relationship["successor_id"]]
            if predecessor["id"] not in records or successor["id"] not in records:
                errors.append(
                    f"curated driver {relationship_id} cannot be checked against incomplete results"
                )
                continue
            if (
                successor.get("actual_start") is not None
                and project.get("progress_policy") == "progress_override"
                and predecessor.get("actual_finish") is None
            ):
                errors.append(f"curated driver {relationship_id} is suppressed by progress_override")
                continue
            relation_type = relationship["type"]
            predecessor_event = records[predecessor["id"]][
                "finish" if relation_type[0] == "F" else "start"
            ]
            bound = _lag_from_units(
                predecessor_event,
                relationship["lag"],
                calendar_units[successor["calendar_id"]],
                horizon,
            )
            duration = (
                successor["remaining_duration"]
                if successor.get("actual_start") is not None
                else successor["duration"]
            )
            base = (
                project["status_time"]
                if successor.get("actual_start") is not None
                else project["project_start"]
            )
            baseline = _earliest_span_units(
                base, 0, duration, allowed_by_activity[successor["id"]], horizon
            )
            if bound is None or baseline is None:
                errors.append(f"curated driver {relationship_id} cannot be recomputed")
                continue
            if relation_type[1] == "S":
                candidate = (
                    _earliest_span_units(
                        bound, 0, duration, allowed_by_activity[successor["id"]], horizon
                    )
                    if bound >= baseline[0]
                    else None
                )
                declared = records[successor["id"]].get(
                    "remaining_start" if successor.get("actual_start") is not None else "start"
                )
                derived = candidate[0] if candidate is not None else None
            else:
                candidate = (
                    _earliest_span_units(
                        base, bound, duration, allowed_by_activity[successor["id"]], horizon
                    )
                    if bound >= baseline[1]
                    else None
                )
                declared = records[successor["id"]].get("finish")
                derived = candidate[1] if candidate is not None else None
            if derived != declared:
                errors.append(f"curated driver {relationship_id} is not governing")

    @staticmethod
    def _objective_vector(
        schedule: dict[str, Any],
        records: dict[str, dict[str, Any]],
        allowed_by_activity: dict[str, frozenset[int]],
    ) -> list[int]:
        activities = {activity["id"]: activity for activity in schedule["activities"]}
        resources = {resource["id"]: resource for resource in schedule.get("resources", [])}
        vector: list[int] = [0]
        groups: dict[int, list[str]] = {}
        for activity_id, activity in activities.items():
            if (
                activity["kind"] in {"start_milestone", "finish_milestone"}
                and activity.get("milestone_priority", 0) > 0
                and activity.get("due_time") is not None
            ):
                groups.setdefault(activity["milestone_priority"], []).append(activity_id)
        for priority in sorted(groups, reverse=True):
            lateness = [
                max(0, records[activity_id]["finish"] - activities[activity_id]["due_time"])
                for activity_id in sorted(groups[priority])
            ]
            vector.extend((sum(lateness), max(lateness, default=0), *lateness))
        project_finish = max(record["finish"] for record in records.values())
        approved = schedule.get("approved_forecast")
        movement = 0
        if isinstance(approved, dict):
            approved_states = {item["activity_id"]: item for item in approved["activity_states"]}
            movement = sum(
                abs(records[activity_id]["start"] - approved_states[activity_id]["start"])
                + abs(records[activity_id]["finish"] - approved_states[activity_id]["finish"])
                for activity_id in sorted(records)
            )

        segments_by_resource: dict[str, list[tuple[int, int, int]]] = {
            resource_id: [] for resource_id in resources
        }
        for activity_id, record in records.items():
            active_units = [
                unit
                for unit in range(record.get("remaining_start", record["start"]), record["finish"])
                if unit in allowed_by_activity[activity_id]
            ]
            ranges: list[tuple[int, int]] = []
            for unit in active_units:
                if not ranges or unit > ranges[-1][1]:
                    ranges.append((unit, unit + 1))
                else:
                    ranges[-1] = (ranges[-1][0], unit + 1)
            for assignment in activities[activity_id].get("assignments", []):
                segments_by_resource[assignment["resource_id"]].extend(
                    (start, finish, assignment["demand"]) for start, finish in ranges
                )

        block_count = 0
        peak_sum = 0
        for resource_id in sorted(resources):
            segments = sorted(segments_by_resource[resource_id])
            merged: list[list[int]] = []
            for start, finish, _ in segments:
                if not merged or start > merged[-1][1]:
                    merged.append([start, finish])
                else:
                    merged[-1][1] = max(merged[-1][1], finish)
            block_count += len(merged)
            demand_at_unit: dict[int, int] = {}
            for start, finish, demand in segments:
                for unit in range(start, finish):
                    demand_at_unit[unit] = demand_at_unit.get(unit, 0) + demand
            peak_sum += max(demand_at_unit.values(), default=0)
        vector.extend((project_finish, movement, 0, block_count, peak_sum, 0))
        resource_ids = sorted(resources)
        for activity_id in sorted(activities):
            demand = {
                assignment["resource_id"]: assignment["demand"]
                for assignment in activities[activity_id].get("assignments", [])
            }
            vector.extend((records[activity_id]["start"], records[activity_id]["finish"], 0))
            vector.extend(demand.get(resource_id, 0) for resource_id in resource_ids)
        return vector
