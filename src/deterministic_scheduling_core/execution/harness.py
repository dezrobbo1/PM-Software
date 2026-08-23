from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import shutil
from typing import Any

from rfc3339_validator import validate_rfc3339

from deterministic_scheduling_core import (
    DETERMINISTIC_PROFILE,
    KERNEL_VERSION,
    OBJECTIVE_POLICY,
    SEMANTIC_PROFILE,
)
from deterministic_scheduling_core.canonical import CanonicalLoader, LoadedCase
from deterministic_scheduling_core.calendars.arithmetic import (
    earliest_span,
    intersect_intervals,
    shift_working_time,
)
from deterministic_scheduling_core.cpm import ReferenceCPMKernel
from deterministic_scheduling_core.errors import UnsupportedSemanticError, ValidationFailure
from deterministic_scheduling_core.provenance.canonical_json import (
    sha256_digest,
    write_canonical_json,
)
from deterministic_scheduling_core.provenance.runtime import (
    execution_identity_document,
    load_execution_profile,
)
from deterministic_scheduling_core.validation import (
    EvidenceValidator,
    IndependentResultValidator,
    execution_record_hash,
)


@dataclass(frozen=True, slots=True)
class SuiteRun:
    summary: dict[str, Any]
    passed: bool
    output_dir: Path


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _native_roundtrip(case: LoadedCase) -> dict[str, Any]:
    native = case.document["native_validation"]
    if native.get("p6") == "not_applicable" and native.get("microsoft_project") == "not_applicable":
        return {
            "status": "not_applicable",
            "native_system": "not_applicable",
            "evidence_hash": None,
            "notes": "The preregistered case does not require a native round trip.",
        }
    return {
        "status": "required_not_run",
        "native_system": "p6",
        "evidence_hash": None,
        "notes": "P6 and Microsoft Project native validation remain required and were not run by the reference kernel.",
    }


def _allowed_intervals(
    schedule: dict[str, Any], activity: dict[str, Any]
) -> tuple[tuple[int, int], ...]:
    calendars = {item["id"]: item for item in schedule["calendars"]}
    resources = {item["id"]: item for item in schedule.get("resources", [])}
    intervals = tuple(
        tuple(item) for item in calendars[activity["calendar_id"]]["working_intervals"]
    )
    for assignment in activity.get("assignments", []):
        resource = resources[assignment["resource_id"]]
        intervals = intersect_intervals(
            intervals, calendars[resource["calendar_id"]]["working_intervals"]
        )
    return intervals


def _trace_details(
    case: LoadedCase, result: dict[str, Any]
) -> tuple[str, str, dict[str, Any], str, dict[str, Any], str | None]:
    """Select one honestly governing, independently checkable cause for the case."""

    schedule = case.schedule
    activities = {item["id"]: item for item in schedule["activities"]}
    records = result["activity_times"]
    project = schedule["project"]
    horizon = schedule["time_axis"]["horizon"]

    actual_ids = sorted(
        activity_id
        for activity_id, activity in activities.items()
        if activity.get("actual_start") is not None
    )
    if actual_ids:
        activity_id = actual_ids[0]
        activity = activities[activity_id]
        source_field = (
            "actual_finish" if activity.get("actual_finish") is not None else "actual_start"
        )
        rule_id = (
            "reference-v0.3-preserve-completed-actual"
            if source_field == "actual_finish"
            else "reference-v0.3-remaining-work-from-status-time"
        )
        return (
            activity_id,
            "actual_progress",
            {"type": "actual_event", "id": activity_id, "source_field": source_field},
            rule_id,
            {
                "activity_id": activity_id,
                "actual_start": activity.get("actual_start"),
                "actual_finish": activity.get("actual_finish"),
                "remaining_duration": activity.get("remaining_duration"),
                "status_time": project.get("status_time"),
                "calendar_id": activity["calendar_id"],
                "allowed_intervals": [list(item) for item in _allowed_intervals(schedule, activity)],
            },
            None,
        )

    resource_order = result.get("resource_order", [])
    if len(resource_order) >= 2:
        conflicting_id, activity_id = resource_order[0], resource_order[1]
        conflicting_resources = {
            assignment["resource_id"]
            for assignment in activities[conflicting_id].get("assignments", [])
        }
        activity_resources = {
            assignment["resource_id"]
            for assignment in activities[activity_id].get("assignments", [])
        }
        resource_id = sorted(conflicting_resources & activity_resources)[0]
        activity = activities[activity_id]
        return (
            activity_id,
            "resource_conflict",
            {"type": "resource", "id": resource_id, "source_field": None},
            "reference-v0.3-exclusive-capacity-one-order",
            {
                "activity_id": activity_id,
                "duration": activity["duration"],
                "calendar_id": activity["calendar_id"],
                "allowed_intervals": [list(item) for item in _allowed_intervals(schedule, activity)],
                "resource_id": resource_id,
                "conflicting_activity_id": conflicting_id,
                "conflicting_activity_finish": records[conflicting_id]["finish"],
                "selected_resource_order": list(resource_order),
            },
            conflicting_id,
        )

    for activity_id in sorted(activities):
        activity = activities[activity_id]
        intervals = _allowed_intervals(schedule, activity)
        for constraint in sorted(activity.get("constraints", []), key=lambda item: item["id"]):
            start_lower = project["project_start"]
            finish_lower = project["project_start"]
            if constraint["type"] == "start_no_earlier_than":
                start_lower = max(start_lower, constraint["value"])
            elif constraint["type"] == "finish_no_earlier_than":
                finish_lower = max(finish_lower, constraint["value"])
            else:
                continue
            constraint_span = earliest_span(
                start_lower,
                finish_lower,
                activity["duration"],
                intervals,
                horizon,
            )
            record = records[activity_id]
            if constraint_span != (record["start"], record["finish"]):
                continue
            return (
                activity_id,
                "date_constraint",
                {"type": "constraint", "id": constraint["id"], "source_field": None},
                f"reference-v0.3-{constraint['type']}",
                {
                    "activity_id": activity_id,
                    "duration": activity["duration"],
                    "calendar_id": activity["calendar_id"],
                    "allowed_intervals": [list(item) for item in intervals],
                    "project_start": project["project_start"],
                    "constraint_id": constraint["id"],
                    "constraint_type": constraint["type"],
                    "constraint_value": constraint["value"],
                },
                None,
            )

    relationships = {item["id"]: item for item in schedule.get("relationships", [])}
    driving_relationships = case.expected.get("driving_relationships", [])
    if driving_relationships:
        relationship = relationships[driving_relationships[0]]
        activity_id = relationship["successor_id"]
        activity = activities[activity_id]
        relation_type = relationship["type"]
        predecessor_record = records[relationship["predecessor_id"]]
        predecessor_event_name = "finish" if relation_type[0] == "F" else "start"
        predecessor_event = predecessor_record[predecessor_event_name]
        successor_calendar = next(
            item for item in schedule["calendars"] if item["id"] == activity["calendar_id"]
        )
        relationship_bound = shift_working_time(
            predecessor_event,
            relationship["lag"],
            successor_calendar["working_intervals"],
        )
        return (
            activity_id,
            "precedence",
            {"type": "relationship", "id": relationship["id"], "source_field": None},
            "reference-v0.3-relationship-lower-bound",
            {
                "activity_id": activity_id,
                "duration": activity.get("remaining_duration")
                if activity.get("actual_start") is not None
                else activity["duration"],
                "calendar_id": activity["calendar_id"],
                "allowed_intervals": [list(item) for item in _allowed_intervals(schedule, activity)],
                "relationship_id": relationship["id"],
                "relationship_type": relation_type,
                "predecessor_id": relationship["predecessor_id"],
                "predecessor_event": predecessor_event_name,
                "predecessor_coordinate": predecessor_event,
                "lag": relationship["lag"],
                "lag_calendar": "successor_activity_calendar",
                "relationship_bound": relationship_bound,
            },
            None,
        )

    activity_id = sorted(activities)[0]
    activity = activities[activity_id]
    return (
        activity_id,
        "calendar",
        {"type": "calendar", "id": activity["calendar_id"], "source_field": None},
        "reference-v0.3-project-start-and-productive-calendar",
        {
            "activity_id": activity_id,
            "duration": activity["duration"],
            "calendar_id": activity["calendar_id"],
            "project_start": project["project_start"],
            "allowed_intervals": [list(item) for item in _allowed_intervals(schedule, activity)],
        },
        None,
    )


class SemanticSuiteHarness:
    def __init__(self, repository_root: Path):
        self.root = repository_root.resolve()
        self.loader = CanonicalLoader(self.root)
        self.kernel = ReferenceCPMKernel()
        self.result_validator = IndependentResultValidator()
        self.evidence_validator = EvidenceValidator(self.root)
        self.profile = load_execution_profile(self.root)

    def run(
        self,
        *,
        output_dir: Path,
        cases_dir: Path | None = None,
        catalogue_path: Path | None = None,
        executed_at: str | None = None,
    ) -> SuiteRun:
        if output_dir.is_symlink():
            raise ValueError("output_dir must not be a symbolic link")
        output_dir = output_dir.resolve()
        suite_executed_at = executed_at or _utc_now()
        if not validate_rfc3339(suite_executed_at):
            raise ValueError("executed_at must be a timezone-qualified RFC 3339 timestamp")
        cases = self.loader.discover_frozen_suite(cases_dir, catalogue_path)
        self._prepare_output_directory(output_dir)
        case_summaries: list[dict[str, Any]] = []
        for case in cases:
            try:
                if case.expected["reference_status"] == "native_validation_only":
                    case_summary = self._write_native_disposition(case, output_dir)
                else:
                    case_summary = self._execute_case(case, output_dir, suite_executed_at)
            except Exception as exc:  # Retain every unexplained discrepancy as evidence.
                case_summary = self._write_failure(case, output_dir, suite_executed_at, exc)
            case_summaries.append(case_summary)

        counts = {
            "executed_pass": sum(item["status"] == "executed_pass" for item in case_summaries),
            "executed_fail": sum(item["status"] == "executed_fail" for item in case_summaries),
            "native_validation_required": sum(
                item["status"] == "native_validation_required" for item in case_summaries
            ),
            "total": len(case_summaries),
        }
        base_summary = {
            "schema_version": "phase1-semantic-suite-summary-v0.1",
            "semantic_profile": SEMANTIC_PROFILE,
            "deterministic_profile": DETERMINISTIC_PROFILE,
            "objective_policy": OBJECTIVE_POLICY,
            "kernel_version": KERNEL_VERSION,
            "case_order": [item["case_id"] for item in case_summaries],
            "counts": counts,
            "cases": case_summaries,
        }
        summary = {**base_summary, "suite_hash": sha256_digest(base_summary)}
        write_canonical_json(output_dir / "suite-summary.json", summary)
        passed = counts == {
            "executed_pass": 49,
            "executed_fail": 0,
            "native_validation_required": 1,
            "total": 50,
        }
        return SuiteRun(summary=summary, passed=passed, output_dir=output_dir)

    def _prepare_output_directory(self, output_dir: Path) -> None:
        if output_dir == self.root:
            raise ValueError("output_dir must not be the repository root")
        output_dir.mkdir(parents=True, exist_ok=True)
        allowed_entries = {"cases", "suite-summary.json"}
        unexpected = sorted(path.name for path in output_dir.iterdir() if path.name not in allowed_entries)
        if unexpected:
            raise ValueError(
                f"output_dir contains non-suite entries and was preserved unchanged: {unexpected}"
            )
        cases_path = output_dir / "cases"
        if cases_path.exists() or cases_path.is_symlink():
            if cases_path.is_symlink() or not cases_path.is_dir():
                raise ValueError("output_dir/cases must be a real directory")
            shutil.rmtree(cases_path)
        summary_path = output_dir / "suite-summary.json"
        if summary_path.exists() or summary_path.is_symlink():
            if summary_path.is_symlink() or not summary_path.is_file():
                raise ValueError("output_dir/suite-summary.json must be a regular file")
            summary_path.unlink()

    def _execute_case(
        self, case: LoadedCase, output_dir: Path, executed_at: str
    ) -> dict[str, Any]:
        result = self.kernel.calculate(
            case.schedule,
            case_id=case.case_id,
            category=case.document["category"],
        )
        output_hash = sha256_digest(result)
        report = self.result_validator.validate(case, result)
        validation = report.as_document(input_hash=case.input_hash, output_hash=output_hash)
        if report.status != "pass":
            raise ValidationFailure("; ".join(report.errors))

        selected_activity_states = []
        for activity_id, record in sorted(result["activity_times"].items()):
            state = {
                "activity_id": activity_id,
                "start": record["start"],
                "finish": record["finish"],
            }
            if "remaining_start" in record:
                state["remaining_start"] = record["remaining_start"]
            selected_activity_states.append(state)
        selected_state = {
            "schema_version": "phase1-selected-state-v0.1",
            "case_id": case.case_id,
            "activity_states": selected_activity_states,
            "resource_order": result["resource_order"],
            "selection_objective_vector": result["selection_objective_vector"],
        }
        selected_hash = sha256_digest(selected_state)
        validation_hash = sha256_digest(validation)
        identity = execution_identity_document(
            schedule=case.schedule, input_hash=case.input_hash, profile=self.profile
        )
        identity_hash = sha256_digest(identity)
        prefix = f"cases/{case.case_id}"
        evidence_paths = [
            f"{prefix}/canonical-input.json",
            f"{prefix}/calculated-output.json",
            f"{prefix}/selected-state.json",
            f"{prefix}/validation.json",
            f"{prefix}/explanation.json",
            f"{prefix}/execution-identity.json",
        ]
        (
            focus_activity_id,
            reason_type,
            governing_entity,
            rule_id,
            trace_inputs,
            conflicting_activity_id,
        ) = _trace_details(case, result)
        focus_record = result["activity_times"][focus_activity_id]
        explanation = {
            "schema_version": "0.1.3",
            "explanation_id": f"TRACE-{case.case_id}",
            "decision_scope": "calculation_trace",
            "scenario_id": None,
            "activity_id": focus_activity_id,
            "previous_start": focus_record["start"],
            "previous_finish": focus_record["finish"],
            "proposed_start": focus_record["start"],
            "proposed_finish": focus_record["finish"],
            "movement": 0,
            "movement_basis": "both",
            "reason_type": reason_type,
            "governing_entity": governing_entity,
            "selected_objective_vector": [],
            "counterfactuals": [],
            "model_version": KERNEL_VERSION,
            "solver_version": None,
            "objective_policy_version": None,
            "input_hash": case.input_hash,
            "output_hash": output_hash,
            "recomputation": {
                "execution_identity": identity_hash,
                "validator_status": "pass",
                "evidence_paths": [f"{prefix}/validation.json"],
            },
            "calculation_trace": {
                "rule_id": rule_id,
                "input_values": trace_inputs,
                "derived_start": focus_record.get("remaining_start", focus_record["start"]),
                "derived_finish": focus_record["finish"],
                "recomputation_hash": validation_hash,
                "validator_status": "pass",
                "evidence_paths": [f"{prefix}/validation.json"],
            },
        }
        if conflicting_activity_id is not None:
            explanation["conflicting_activity_id"] = conflicting_activity_id
        explanation_hash = sha256_digest(explanation)
        bundle = {
            "schema_version": "phase1-evidence-bundle-v0.1",
            "case_id": case.case_id,
            "fixture_hash": case.fixture_hash,
            "input_hash": case.input_hash,
            "output_hash": output_hash,
            "selected_scenario_hash": selected_hash,
            "validation_hash": validation_hash,
            "explanation_hash": explanation_hash,
            "execution_identity": identity_hash,
            "evidence_paths": evidence_paths,
        }
        bundle_hash = sha256_digest(bundle)
        record = {
            "schema_version": "0.1.4",
            "execution_id": f"PHASE1-{case.case_id}",
            "case_id": case.case_id,
            "executed_at": executed_at,
            "execution_identity": identity_hash,
            "status": "executed_pass",
            "input_hash": case.input_hash,
            "output_hash": output_hash,
            "selected_scenario_hash": selected_hash,
            "explanation_hash": explanation_hash,
            "evidence_bundle_hash": bundle_hash,
            "validator_status": "pass",
            "feasibility_status": "not_applicable",
            "optimality_status": "not_applicable",
            "objective_vector": [],
            "best_bound": None,
            "optimality_gap": None,
            "native_roundtrip_result": _native_roundtrip(case),
            "evidence_paths": [
                f"{prefix}/evidence-bundle.json",
                f"{prefix}/validation.json",
                f"{prefix}/explanation.json",
            ],
            "failure_code": None,
            "notes": (
                "Reference semantic execution; feasibility and optimality are not applicable. "
                "Any bounded resource-order ranking is retained in the calculated output, not claimed as optimiser evidence."
            ),
        }
        evidence_errors = self.evidence_validator.validate_executed_artifacts(
            case=case,
            output=result,
            selected_state=selected_state,
            validation=validation,
            explanation=explanation,
            identity=identity,
            bundle=bundle,
            record=record,
        )
        if evidence_errors:
            raise ValidationFailure("; ".join(evidence_errors))

        case_dir = output_dir / "cases" / case.case_id
        artifacts = {
            "canonical-input.json": case.schedule,
            "calculated-output.json": result,
            "selected-state.json": selected_state,
            "validation.json": validation,
            "explanation.json": explanation,
            "execution-identity.json": identity,
            "evidence-bundle.json": bundle,
            "execution-record.json": record,
        }
        for filename, artifact in artifacts.items():
            write_canonical_json(case_dir / filename, artifact)
        return {
            "case_id": case.case_id,
            "status": "executed_pass",
            "input_hash": case.input_hash,
            "fixture_hash": case.fixture_hash,
            "output_hash": output_hash,
            "selected_scenario_hash": selected_hash,
            "validation_hash": validation_hash,
            "explanation_hash": explanation_hash,
            "evidence_bundle_hash": bundle_hash,
            "execution_identity": identity_hash,
            "execution_record_hash": execution_record_hash(record),
            "native_disposition_hash": None,
        }

    def _write_native_disposition(
        self, case: LoadedCase, output_dir: Path
    ) -> dict[str, Any]:
        activities = {activity["id"]: activity for activity in case.schedule["activities"]}
        expected_times = case.expected.get("activity_times", {})
        native_errors: list[str] = []
        if set(expected_times) != set(activities):
            native_errors.append("native-only oracle does not completely cover actual activities")
        for activity_id, expected in expected_times.items():
            activity = activities.get(activity_id)
            if activity is None:
                continue
            if expected.get("start") != activity.get("actual_start"):
                native_errors.append(f"{activity_id}: declared actual start was not preserved")
            if expected.get("finish") is not None:
                native_errors.append(f"{activity_id}: native-only forecast finish must remain null")
        if (
            case.expected.get("project_finish") is not None
            or case.expected.get("driving_relationships", [])
            or case.expected.get("resource_order", [])
        ):
            native_errors.append("native-only fixture contains fabricated calculated evidence")
        if native_errors:
            raise ValidationFailure("; ".join(native_errors))
        disposition = {
            "schema_version": "phase1-native-disposition-v0.1",
            "case_id": case.case_id,
            "status": "native_validation_required",
            "semantic_profile": SEMANTIC_PROFILE,
            "progress_policy": case.schedule["project"].get("progress_policy"),
            "preserved_actuals": [
                {
                    "activity_id": activity["id"],
                    "actual_start": activity.get("actual_start"),
                    "actual_finish": activity.get("actual_finish"),
                }
                for activity in sorted(case.schedule["activities"], key=lambda item: item["id"])
            ],
            "required_native_systems": ["p6", "microsoft_project"],
            "notes": "No reference-v0.3 forecast was calculated for product-specific Actual Dates behaviour.",
        }
        record = {
            "schema_version": "0.1.4",
            "execution_id": f"PHASE1-{case.case_id}",
            "case_id": case.case_id,
            "executed_at": None,
            "execution_identity": None,
            "status": "native_validation_required",
            "input_hash": None,
            "output_hash": None,
            "selected_scenario_hash": None,
            "explanation_hash": None,
            "evidence_bundle_hash": None,
            "validator_status": "not_run",
            "feasibility_status": "not_run",
            "optimality_status": "not_run",
            "objective_vector": [],
            "best_bound": None,
            "optimality_gap": None,
            "native_roundtrip_result": {
                "status": "required_not_run",
                "native_system": "p6",
                "evidence_hash": None,
                "notes": "P6 and Microsoft Project native execution remain required.",
            },
            "evidence_paths": [],
            "failure_code": None,
            "notes": "Non-executed native-validation-only disposition; hashes are null by protocol.",
        }
        schema_errors = self.evidence_validator.validate_native_record(record)
        if schema_errors:
            raise ValidationFailure("; ".join(schema_errors))
        case_dir = output_dir / "cases" / case.case_id
        write_canonical_json(case_dir / "native-disposition.json", disposition)
        write_canonical_json(case_dir / "execution-record.json", record)
        return {
            "case_id": case.case_id,
            "status": "native_validation_required",
            "input_hash": case.input_hash,
            "fixture_hash": case.fixture_hash,
            "output_hash": None,
            "selected_scenario_hash": None,
            "validation_hash": None,
            "explanation_hash": None,
            "evidence_bundle_hash": None,
            "execution_identity": None,
            "execution_record_hash": execution_record_hash(record),
            "native_disposition_hash": sha256_digest(disposition),
        }

    def _write_failure(
        self,
        case: LoadedCase,
        output_dir: Path,
        executed_at: str,
        error: Exception,
    ) -> dict[str, Any]:
        code = error.code if isinstance(error, UnsupportedSemanticError) else type(error).__name__
        failure = {
            "schema_version": "phase1-failure-evidence-v0.1",
            "case_id": case.case_id,
            "input_hash": case.input_hash,
            "failure_code": code,
            "message": str(error),
        }
        identity = execution_identity_document(
            schedule=case.schedule, input_hash=case.input_hash, profile=self.profile
        )
        identity_hash = sha256_digest(identity)
        failure_hash = sha256_digest(failure)
        prefix = f"cases/{case.case_id}"
        bundle = {
            "schema_version": "phase1-failure-bundle-v0.1",
            "case_id": case.case_id,
            "input_hash": case.input_hash,
            "execution_identity": identity_hash,
            "failure_hash": failure_hash,
            "evidence_paths": [f"{prefix}/failure.json", f"{prefix}/execution-identity.json"],
        }
        record = {
            "schema_version": "0.1.4",
            "execution_id": f"PHASE1-{case.case_id}",
            "case_id": case.case_id,
            "executed_at": executed_at,
            "execution_identity": identity_hash,
            "status": "executed_fail",
            "input_hash": case.input_hash,
            "output_hash": None,
            "selected_scenario_hash": None,
            "explanation_hash": None,
            "evidence_bundle_hash": sha256_digest(bundle),
            "validator_status": "fail",
            "feasibility_status": "unknown",
            "optimality_status": "unknown",
            "objective_vector": [],
            "best_bound": None,
            "optimality_gap": None,
            "native_roundtrip_result": _native_roundtrip(case),
            "evidence_paths": [f"{prefix}/evidence-bundle.json", f"{prefix}/failure.json"],
            "failure_code": str(code),
            "notes": "Unexplained calculation or evidence discrepancy retained by the suite harness.",
        }
        schema_errors = self.evidence_validator.validate_native_record(record)
        if schema_errors:
            raise ValidationFailure("; ".join(schema_errors)) from error
        case_dir = output_dir / "cases" / case.case_id
        for filename, artifact in (
            ("failure.json", failure),
            ("execution-identity.json", identity),
            ("evidence-bundle.json", bundle),
            ("execution-record.json", record),
        ):
            write_canonical_json(case_dir / filename, artifact)
        return {
            "case_id": case.case_id,
            "status": "executed_fail",
            "input_hash": case.input_hash,
            "fixture_hash": case.fixture_hash,
            "output_hash": None,
            "selected_scenario_hash": None,
            "validation_hash": None,
            "explanation_hash": None,
            "evidence_bundle_hash": sha256_digest(bundle),
            "execution_identity": identity_hash,
            "execution_record_hash": execution_record_hash(record),
            "native_disposition_hash": None,
        }
