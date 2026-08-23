from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rfc3339_validator import validate_rfc3339

from deterministic_scheduling_core import (
    DETERMINISTIC_PROFILE,
    KERNEL_VERSION,
    OBJECTIVE_POLICY,
    SEMANTIC_PROFILE,
)
from deterministic_scheduling_core.canonical import CanonicalLoader, LoadedCase
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
        output_dir = output_dir.resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        suite_executed_at = executed_at or _utc_now()
        if not validate_rfc3339(suite_executed_at):
            raise ValueError("executed_at must be a timezone-qualified RFC 3339 timestamp")
        cases = self.loader.discover_frozen_suite(cases_dir, catalogue_path)
        case_summaries: list[dict[str, Any]] = []
        for case in cases:
            if case.expected["reference_status"] == "native_validation_only":
                case_summaries.append(
                    self._write_native_disposition(case, output_dir)
                )
                continue
            try:
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

        selected_state = {
            "schema_version": "phase1-selected-state-v0.1",
            "case_id": case.case_id,
            "activity_states": [
                {
                    "activity_id": activity_id,
                    "start": record["start"],
                    "finish": record["finish"],
                }
                for activity_id, record in sorted(result["activity_times"].items())
            ],
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
        focus_activity_id = sorted(result["activity_times"])[0]
        focus_activity = next(
            activity for activity in case.schedule["activities"] if activity["id"] == focus_activity_id
        )
        focus_record = result["activity_times"][focus_activity_id]
        if focus_activity.get("actual_start") is not None:
            reason_type = "actual_progress"
            source_field = (
                "actual_finish" if focus_activity.get("actual_finish") is not None else "actual_start"
            )
            governing_entity = {
                "type": "actual_event",
                "id": focus_activity_id,
                "source_field": source_field,
            }
        else:
            reason_type = "calendar"
            governing_entity = {
                "type": "calendar",
                "id": focus_activity["calendar_id"],
                "source_field": None,
            }
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
                "rule_id": "reference-v0.3-earliest-supported-span",
                "input_values": {
                    "activity_id": focus_activity_id,
                    "duration": focus_activity["duration"],
                    "calendar_id": focus_activity["calendar_id"],
                    "project_start": case.schedule["project"]["project_start"],
                },
                "derived_start": focus_record["start"],
                "derived_finish": focus_record["finish"],
                "recomputation_hash": validation_hash,
                "validator_status": "pass",
                "evidence_paths": [f"{prefix}/validation.json"],
            },
        }
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
