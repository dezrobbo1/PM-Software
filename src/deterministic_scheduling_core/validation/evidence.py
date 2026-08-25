from __future__ import annotations

import copy
import json
from pathlib import PurePosixPath, Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from deterministic_scheduling_core import KERNEL_VERSION, OBJECTIVE_POLICY, SEMANTIC_PROFILE
from deterministic_scheduling_core.canonical.model import LoadedCase
from deterministic_scheduling_core.provenance.canonical_json import canonical_bytes, sha256_digest
from deterministic_scheduling_core.provenance.runtime import (
    execution_identity_document,
    load_execution_profile,
    verified_source_manifest_hash,
)


def _units(intervals: list[list[int]]) -> frozenset[int]:
    return frozenset(unit for start, finish in intervals for unit in range(start, finish))


def _allowed_units(schedule: dict[str, Any], activity: dict[str, Any]) -> frozenset[int]:
    calendars = {item["id"]: item for item in schedule["calendars"]}
    resources = {item["id"]: item for item in schedule.get("resources", [])}
    allowed = _units(calendars[activity["calendar_id"]]["working_intervals"])
    for assignment in activity.get("assignments", []):
        resource = resources[assignment["resource_id"]]
        allowed &= _units(calendars[resource["calendar_id"]]["working_intervals"])
    return allowed


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


def execution_record_hash(record: dict[str, Any]) -> str:
    """Hash the deterministic record identity projection.

    `executed_at` remains honest wall-clock metadata in the schema-valid record but
    is explicitly outside deterministic-v0.3 environment-evidence hashes.
    """

    projection = copy.deepcopy(record)
    projection.pop("executed_at", None)
    return sha256_digest(projection)


def portable_explanation_document(explanation: dict[str, Any]) -> dict[str, Any]:
    """Remove the environment identity while retaining every semantic trace fact."""

    projection = copy.deepcopy(explanation)
    recomputation = projection.get("recomputation")
    if isinstance(recomputation, dict):
        recomputation.pop("execution_identity", None)
    return projection


def portable_semantic_result_document(
    *,
    case: LoadedCase,
    profile: dict[str, Any],
    source_manifest_hash: str,
    output_hash: str,
    selected_state_hash: str,
    validation_hash: str,
    explanation: dict[str, Any],
    native_requirements_hash: str,
) -> dict[str, Any]:
    return {
        "schema_version": profile["portable_semantic_result_projection"],
        "case_id": case.case_id,
        "fixture_hash": case.fixture_hash,
        "input_hash": case.input_hash,
        "source_manifest_hash": source_manifest_hash,
        "dependency_lock_sha256": profile["dependency_lock_sha256"],
        "semantic_profile": SEMANTIC_PROFILE,
        "objective_policy": OBJECTIVE_POLICY,
        "kernel_version": KERNEL_VERSION,
        "deterministic_profile": profile["profile_id"],
        "output_hash": output_hash,
        "selected_state_hash": selected_state_hash,
        "validation_hash": validation_hash,
        "portable_explanation_hash": sha256_digest(
            portable_explanation_document(explanation)
        ),
        "native_requirements_hash": native_requirements_hash,
    }


def native_roundtrip_document(case: LoadedCase) -> dict[str, Any]:
    native = case.document["native_validation"]
    if (
        native.get("p6") == "not_applicable"
        and native.get("microsoft_project") == "not_applicable"
    ):
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
        "notes": (
            "This frozen execution-record field carries the P6 disposition. "
            "The bound native-requirements sidecar separately records P6 and Microsoft Project."
        ),
    }


def native_requirements_document(case: LoadedCase) -> dict[str, Any]:
    plans = {
        "p6": (
            "p6-semantic-microcases-v0.1",
            "native-files/p6/p6-semantic-microcases-v0.1",
        ),
        "microsoft_project": (
            "microsoft-project-semantic-microcases-v0.1",
            "native-files/microsoft-project/microsoft-project-semantic-microcases-v0.1",
        ),
    }
    requirements = []
    for native_system in ("p6", "microsoft_project"):
        plan_id, evidence_root = plans[native_system]
        required = case.document["native_validation"].get(native_system) == "required"
        requirements.append(
            {
                "native_system": native_system,
                "status": "required_not_run" if required else "not_applicable",
                "preregistration_id": plan_id if required else None,
                "evidence_root": evidence_root if required else None,
                "evidence_hash": None,
            }
        )
    return {
        "schema_version": "phase1-native-requirements-v0.1",
        "case_id": case.case_id,
        "requirements": requirements,
        "claim_boundary": (
            "Portable reference execution is not native compatibility evidence. "
            "Each product requires its own environment-bound run and evidence hash."
        ),
    }


def failure_evidence_document(
    *, case: LoadedCase, failure_code: str, message: str
) -> dict[str, Any]:
    return {
        "schema_version": "phase1-failure-evidence-v0.1",
        "case_id": case.case_id,
        "input_hash": case.input_hash,
        "failure_code": failure_code,
        "message": message,
    }


def portable_failure_result_document(
    *,
    case: LoadedCase,
    profile: dict[str, Any],
    source_manifest_hash: str,
    failure: dict[str, Any],
    native_requirements_hash: str,
) -> dict[str, Any]:
    """Bind the stable failed-case outcome outside environment-only evidence."""

    return {
        "schema_version": profile["portable_failure_result_projection"],
        "case_id": case.case_id,
        "fixture_hash": case.fixture_hash,
        "input_hash": case.input_hash,
        "source_manifest_hash": source_manifest_hash,
        "dependency_lock_sha256": profile["dependency_lock_sha256"],
        "semantic_profile": SEMANTIC_PROFILE,
        "objective_policy": OBJECTIVE_POLICY,
        "kernel_version": KERNEL_VERSION,
        "deterministic_profile": profile["profile_id"],
        "failure_code": failure["failure_code"],
        "failure_hash": sha256_digest(failure),
        "native_requirements_hash": native_requirements_hash,
    }


def failure_evidence_bundle_document(
    *,
    case: LoadedCase,
    execution_identity_hash: str,
    failure_hash: str,
    native_requirements_hash: str,
    portable_failure_result_hash: str,
) -> dict[str, Any]:
    prefix = f"cases/{case.case_id}"
    return {
        "schema_version": "phase1-failure-bundle-v0.1",
        "case_id": case.case_id,
        "input_hash": case.input_hash,
        "execution_identity": execution_identity_hash,
        "failure_hash": failure_hash,
        "native_requirements_hash": native_requirements_hash,
        "portable_semantic_result_hash": None,
        "portable_failure_result_hash": portable_failure_result_hash,
        "evidence_paths": [
            f"{prefix}/failure.json",
            f"{prefix}/execution-identity.json",
            f"{prefix}/native-requirements.json",
            f"{prefix}/portable-failure-result.json",
        ],
    }


def failure_execution_record_document(
    *,
    case: LoadedCase,
    executed_at: str,
    execution_identity_hash: str,
    evidence_bundle_hash: str,
    failure_code: str,
) -> dict[str, Any]:
    prefix = f"cases/{case.case_id}"
    return {
        "schema_version": "0.1.4",
        "execution_id": f"PHASE1-{case.case_id}",
        "case_id": case.case_id,
        "executed_at": executed_at,
        "execution_identity": execution_identity_hash,
        "status": "executed_fail",
        "input_hash": case.input_hash,
        "output_hash": None,
        "selected_scenario_hash": None,
        "explanation_hash": None,
        "evidence_bundle_hash": evidence_bundle_hash,
        "validator_status": "fail",
        "feasibility_status": "unknown",
        "optimality_status": "unknown",
        "objective_vector": [],
        "best_bound": None,
        "optimality_gap": None,
        "native_roundtrip_result": native_roundtrip_document(case),
        "evidence_paths": [
            f"{prefix}/evidence-bundle.json",
            f"{prefix}/failure.json",
            f"{prefix}/execution-identity.json",
            f"{prefix}/native-requirements.json",
            f"{prefix}/portable-failure-result.json",
        ],
        "failure_code": failure_code,
        "notes": "Unexplained calculation or evidence discrepancy retained by the suite harness.",
    }


def environment_evidence_document(
    *,
    profile: dict[str, Any],
    case_id: str,
    portable_semantic_result_hash: str | None,
    portable_failure_result_hash: str | None,
    execution_identity_hash: str,
    explanation_hash: str | None,
    evidence_bundle_hash: str,
    execution_record_hash_value: str,
) -> dict[str, Any]:
    return {
        "schema_version": profile["environment_evidence_projection"],
        "case_id": case_id,
        "portable_semantic_result_hash": portable_semantic_result_hash,
        "portable_failure_result_hash": portable_failure_result_hash,
        "execution_identity_hash": execution_identity_hash,
        "explanation_hash": explanation_hash,
        "evidence_bundle_hash": evidence_bundle_hash,
        "execution_record_hash": execution_record_hash_value,
    }


class EvidenceValidator:
    def __init__(
        self,
        repository_root: Path,
        *,
        profile: dict[str, Any] | None = None,
        source_manifest_hash: str | None = None,
    ):
        schema_dir = repository_root / "schemas"
        self.profile = profile or load_execution_profile(repository_root)
        self.source_manifest_hash = source_manifest_hash or verified_source_manifest_hash(
            repository_root
        )
        self.execution_validator = Draft202012Validator(
            json.loads((schema_dir / "execution-record.schema.json").read_text(encoding="utf-8")),
            format_checker=FormatChecker(),
        )
        self.explanation_validator = Draft202012Validator(
            json.loads(
                (schema_dir / "structured-explanation.schema.json").read_text(encoding="utf-8")
            ),
            format_checker=FormatChecker(),
        )

    @staticmethod
    def _schema_errors(validator: Draft202012Validator, value: Any, label: str) -> list[str]:
        errors: list[str] = []
        for error in sorted(
            validator.iter_errors(value),
            key=lambda item: tuple(str(part) for part in item.absolute_path),
        ):
            location = "/".join(str(part) for part in error.absolute_path) or "<root>"
            errors.append(f"{label} {location}: {error.message}")
        return errors

    @staticmethod
    def _path_errors(paths: list[str], label: str) -> list[str]:
        errors: list[str] = []
        for value in paths:
            path = PurePosixPath(value)
            if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
                errors.append(f"{label} contains unsafe evidence path {value!r}")
            if "\\" in value:
                errors.append(f"{label} path must use POSIX separators: {value!r}")
        return errors

    @staticmethod
    def _evidence_path_values(value: Any, label: str) -> tuple[list[str], list[str]]:
        if not isinstance(value, list):
            return [], [f"{label} evidence_paths must be an array"]
        paths: list[str] = []
        errors: list[str] = []
        for index, item in enumerate(value):
            if not isinstance(item, str):
                errors.append(f"{label} evidence_paths/{index} must be a string")
            else:
                paths.append(item)
        return paths, errors

    @staticmethod
    def _volatile_key_errors(value: Any, label: str) -> list[str]:
        errors: list[str] = []
        volatile = {"executed_at", "generated_at", "created_at", "wall_clock_time", "hostname", "username", "absolute_path"}

        def walk(item: Any, path: tuple[str, ...]) -> None:
            if isinstance(item, dict):
                for key, child in item.items():
                    if key in volatile:
                        errors.append(f"{label} hashed artifact contains volatile field {'/'.join((*path, key))}")
                    walk(child, (*path, key))
            elif isinstance(item, list):
                for index, child in enumerate(item):
                    walk(child, (*path, str(index)))

        walk(value, tuple())
        return errors

    def validate_executed_artifacts(
        self,
        *,
        case: LoadedCase,
        output: dict[str, Any],
        selected_state: dict[str, Any],
        validation: dict[str, Any],
        explanation: dict[str, Any],
        identity: dict[str, Any],
        native_requirements: dict[str, Any],
        portable_result: dict[str, Any],
        bundle: dict[str, Any],
        record: dict[str, Any],
    ) -> list[str]:
        artifacts = {
            "calculated output": output,
            "selected state": selected_state,
            "validation": validation,
            "explanation": explanation,
            "execution identity": identity,
            "native requirements": native_requirements,
            "portable semantic result": portable_result,
            "evidence bundle": bundle,
            "execution record": record,
        }
        errors = [
            f"{label} must be a JSON object"
            for label, artifact in artifacts.items()
            if not isinstance(artifact, dict)
        ]
        if errors:
            return errors
        errors.extend(self._schema_errors(self.execution_validator, record, "execution record"))
        errors.extend(self._schema_errors(self.explanation_validator, explanation, "explanation"))
        output_hash = sha256_digest(output)
        selected_hash = sha256_digest(selected_state)
        validation_hash = sha256_digest(validation)
        explanation_hash = sha256_digest(explanation)
        identity_hash = sha256_digest(identity)
        native_requirements_hash = sha256_digest(native_requirements)
        portable_result_hash = sha256_digest(portable_result)
        bundle_hash = sha256_digest(bundle)
        expected_portable_result = portable_semantic_result_document(
            case=case,
            profile=self.profile,
            source_manifest_hash=self.source_manifest_hash,
            output_hash=output_hash,
            selected_state_hash=selected_hash,
            validation_hash=validation_hash,
            explanation=explanation,
            native_requirements_hash=native_requirements_hash,
        )
        expected_identity = execution_identity_document(
            schedule=case.schedule,
            input_hash=case.input_hash,
            profile=self.profile,
            source_manifest_hash=self.source_manifest_hash,
        )
        expected = {
            "record.input_hash": (record.get("input_hash"), case.input_hash),
            "record.output_hash": (record.get("output_hash"), output_hash),
            "record.selected_scenario_hash": (record.get("selected_scenario_hash"), selected_hash),
            "record.explanation_hash": (record.get("explanation_hash"), explanation_hash),
            "record.execution_identity": (record.get("execution_identity"), identity_hash),
            "record.evidence_bundle_hash": (record.get("evidence_bundle_hash"), bundle_hash),
            "validation.input_hash": (validation.get("input_hash"), case.input_hash),
            "validation.output_hash": (validation.get("output_hash"), output_hash),
            "explanation.input_hash": (explanation.get("input_hash"), case.input_hash),
            "explanation.output_hash": (explanation.get("output_hash"), output_hash),
            "explanation.recomputation_hash": (
                explanation.get("calculation_trace", {}).get("recomputation_hash"),
                validation_hash,
            ),
            "bundle.input_hash": (bundle.get("input_hash"), case.input_hash),
            "bundle.output_hash": (bundle.get("output_hash"), output_hash),
            "bundle.selected_scenario_hash": (bundle.get("selected_scenario_hash"), selected_hash),
            "bundle.validation_hash": (bundle.get("validation_hash"), validation_hash),
            "bundle.explanation_hash": (bundle.get("explanation_hash"), explanation_hash),
            "bundle.execution_identity": (bundle.get("execution_identity"), identity_hash),
            "bundle.fixture_hash": (bundle.get("fixture_hash"), case.fixture_hash),
            "bundle.native_requirements_hash": (
                bundle.get("native_requirements_hash"),
                native_requirements_hash,
            ),
            "bundle.portable_semantic_result_hash": (
                bundle.get("portable_semantic_result_hash"),
                portable_result_hash,
            ),
        }
        for label, (actual, wanted) in expected.items():
            if actual != wanted:
                errors.append(f"{label} is inconsistent with canonical artifact hash")
        if portable_result != expected_portable_result:
            errors.append("portable semantic result does not match its complete projection")
        if identity != expected_identity:
            errors.append("execution identity does not match the pinned evidence environment")
        if native_requirements != native_requirements_document(case):
            errors.append("native requirements do not match the complete preregistered projection")
        for label, artifact in (
            ("output", output),
            ("selected state", selected_state),
            ("validation", validation),
            ("bundle", bundle),
            ("record", record),
            ("native requirements", native_requirements),
            ("portable result", portable_result),
        ):
            if artifact.get("case_id") != case.case_id:
                errors.append(f"{label} case_id does not bind the canonical case")
        selected_items = selected_state.get("activity_states", [])
        selected_ids = [
            state.get("activity_id") for state in selected_items if isinstance(state, dict)
        ]
        duplicate_selected_ids = sorted(
            {activity_id for activity_id in selected_ids if selected_ids.count(activity_id) > 1}
        )
        if duplicate_selected_ids:
            errors.append(
                "selected state contains duplicate activity_id values: "
                + ", ".join(duplicate_selected_ids)
            )
        selected_by_id = {
            state.get("activity_id"): state
            for state in selected_items
            if isinstance(state, dict)
        }
        output_times = output.get("activity_times", {})
        if set(selected_by_id) != set(output_times):
            errors.append("selected state does not completely cover the calculated output")
        else:
            for activity_id in sorted(output_times):
                for field in ("start", "finish", "remaining_start"):
                    if (field in selected_by_id[activity_id]) != (field in output_times[activity_id]):
                        errors.append(
                            f"selected state {activity_id}.{field} presence differs from calculated output"
                        )
                        continue
                    if selected_by_id[activity_id].get(field) != output_times[activity_id].get(field):
                        errors.append(
                            f"selected state {activity_id}.{field} differs from calculated output"
                        )
        if selected_state.get("resource_order") != output.get("resource_order"):
            errors.append("selected state resource order differs from calculated output")
        if selected_state.get("selection_objective_vector") != output.get(
            "selection_objective_vector"
        ):
            errors.append("selected state objective vector differs from calculated output")
        if validation.get("status") != "pass" or record.get("validator_status") != "pass":
            errors.append("passing evidence does not retain independent validator pass status")
        if explanation.get("activity_id") not in {
            activity["id"] for activity in case.schedule["activities"]
        }:
            errors.append("explanation activity_id is unresolved")
        governing = explanation.get("governing_entity")
        if isinstance(governing, dict):
            entity_type = governing.get("type")
            entity_id = governing.get("id")
            resolved_ids = {
                "activity": {item["id"] for item in case.schedule["activities"]},
                "actual_event": {item["id"] for item in case.schedule["activities"]},
                "calendar": {item["id"] for item in case.schedule["calendars"]},
                "relationship": {item["id"] for item in case.schedule["relationships"]},
                "constraint": {
                    item["id"]
                    for activity in case.schedule["activities"]
                    for item in activity.get("constraints", [])
                },
                "resource": {item["id"] for item in case.schedule.get("resources", [])},
                "operational_constraint": {
                    item["id"] for item in case.schedule.get("operational_constraints", [])
                },
                "objective_policy": {"objective-v0.3"},
            }
            if entity_id not in resolved_ids.get(entity_type, set()):
                errors.append("explanation governing entity is unresolved")
        errors.extend(self._calculation_trace_errors(case, output, explanation))
        previous_start = explanation.get("previous_start")
        previous_finish = explanation.get("previous_finish")
        proposed_start = explanation.get("proposed_start")
        proposed_finish = explanation.get("proposed_finish")
        basis = explanation.get("movement_basis")
        if all(
            value is not None
            for value in (previous_start, previous_finish, proposed_start, proposed_finish)
        ):
            movement = 0
            if basis in {"start", "both"}:
                movement += abs(proposed_start - previous_start)
            if basis in {"finish", "both"}:
                movement += abs(proposed_finish - previous_finish)
            if explanation.get("movement") != movement:
                errors.append("explanation movement is not coordinate-derived")
        recomputation = explanation.get("recomputation")
        calculation_trace = explanation.get("calculation_trace")
        path_sources = (
            ("execution record", record.get("evidence_paths")),
            ("evidence bundle", bundle.get("evidence_paths")),
            (
                "explanation recomputation",
                recomputation.get("evidence_paths")
                if isinstance(recomputation, dict)
                else None,
            ),
            (
                "explanation calculation trace",
                calculation_trace.get("evidence_paths")
                if isinstance(calculation_trace, dict)
                else None,
            ),
        )
        evidence_paths: list[str] = []
        for label, values in path_sources:
            valid_paths, path_value_errors = self._evidence_path_values(values, label)
            evidence_paths.extend(valid_paths)
            errors.extend(path_value_errors)
        errors.extend(self._path_errors(evidence_paths, "execution evidence"))
        for label, artifact in (
            ("calculated output", output),
            ("selected state", selected_state),
            ("validation", validation),
            ("explanation", explanation),
            ("execution identity", identity),
            ("native requirements", native_requirements),
            ("portable semantic result", portable_result),
            ("evidence bundle", bundle),
        ):
            canonical_bytes(artifact)
            errors.extend(self._volatile_key_errors(artifact, label))
        return errors

    def validate_native_requirements(
        self, case: LoadedCase, native_requirements: Any
    ) -> list[str]:
        if not isinstance(native_requirements, dict):
            return ["native requirements must be a JSON object"]
        errors: list[str] = []
        if native_requirements != native_requirements_document(case):
            errors.append("native requirements do not match the complete preregistered projection")
        try:
            canonical_bytes(native_requirements)
        except (TypeError, ValueError) as exc:
            errors.append(f"native requirements are not canonical JSON: {exc}")
        errors.extend(self._volatile_key_errors(native_requirements, "native requirements"))
        return errors

    def validate_failure_artifacts(
        self,
        *,
        case: LoadedCase,
        failure: Any,
        identity: Any,
        native_requirements: Any,
        portable_failure_result: Any,
        bundle: Any,
        record: Any,
    ) -> list[str]:
        artifacts = {
            "failure evidence": failure,
            "execution identity": identity,
            "native requirements": native_requirements,
            "portable failure result": portable_failure_result,
            "failure evidence bundle": bundle,
            "failure execution record": record,
        }
        errors = [
            f"{label} must be a JSON object"
            for label, artifact in artifacts.items()
            if not isinstance(artifact, dict)
        ]
        if errors:
            return errors
        errors.extend(self._schema_errors(self.execution_validator, record, "execution record"))

        failure_code = failure.get("failure_code")
        message = failure.get("message")
        if not isinstance(failure_code, str):
            errors.append("failure evidence failure_code must be a string")
        if not isinstance(message, str):
            errors.append("failure evidence message must be a string")
        if not isinstance(failure_code, str) or not isinstance(message, str):
            return errors

        expected_failure = failure_evidence_document(
            case=case,
            failure_code=failure_code,
            message=message,
        )
        expected_identity = execution_identity_document(
            schedule=case.schedule,
            input_hash=case.input_hash,
            profile=self.profile,
            source_manifest_hash=self.source_manifest_hash,
        )
        expected_native_requirements = native_requirements_document(case)
        native_requirements_hash = sha256_digest(native_requirements)
        expected_portable_failure_result = portable_failure_result_document(
            case=case,
            profile=self.profile,
            source_manifest_hash=self.source_manifest_hash,
            failure=failure,
            native_requirements_hash=native_requirements_hash,
        )
        expected_bundle = failure_evidence_bundle_document(
            case=case,
            execution_identity_hash=sha256_digest(identity),
            failure_hash=sha256_digest(failure),
            native_requirements_hash=native_requirements_hash,
            portable_failure_result_hash=sha256_digest(portable_failure_result),
        )
        expected_record = failure_execution_record_document(
            case=case,
            executed_at=record.get("executed_at"),
            execution_identity_hash=sha256_digest(identity),
            evidence_bundle_hash=sha256_digest(bundle),
            failure_code=failure_code,
        )
        for label, actual, expected in (
            ("failure evidence", failure, expected_failure),
            ("execution identity", identity, expected_identity),
            ("native requirements", native_requirements, expected_native_requirements),
            (
                "portable failure result",
                portable_failure_result,
                expected_portable_failure_result,
            ),
            ("failure evidence bundle", bundle, expected_bundle),
            ("failure execution record", record, expected_record),
        ):
            if actual != expected:
                errors.append(f"{label} does not match its complete canonical projection")
            try:
                canonical_bytes(actual)
            except (TypeError, ValueError) as exc:
                errors.append(f"{label} is not canonical JSON: {exc}")
            volatile_projection = actual
            if label == "failure execution record":
                volatile_projection = copy.deepcopy(actual)
                volatile_projection.pop("executed_at", None)
            errors.extend(self._volatile_key_errors(volatile_projection, label))

        evidence_paths: list[str] = []
        for label, values in (
            ("failure evidence bundle", bundle.get("evidence_paths")),
            ("failure execution record", record.get("evidence_paths")),
        ):
            valid_paths, path_value_errors = self._evidence_path_values(values, label)
            evidence_paths.extend(valid_paths)
            errors.extend(path_value_errors)
        errors.extend(self._path_errors(evidence_paths, "failure evidence"))
        return errors

    @staticmethod
    def _calculation_trace_errors(
        case: LoadedCase,
        output: dict[str, Any],
        explanation: dict[str, Any],
    ) -> list[str]:
        errors: list[str] = []
        trace = explanation.get("calculation_trace")
        if not isinstance(trace, dict):
            return ["calculation trace is missing"]
        inputs = trace.get("input_values")
        if not isinstance(inputs, dict):
            return ["calculation trace input_values are missing"]
        schedule = case.schedule
        activities = {item["id"]: item for item in schedule["activities"]}
        resources = {item["id"]: item for item in schedule.get("resources", [])}
        relationships = {item["id"]: item for item in schedule.get("relationships", [])}
        activity_id = explanation.get("activity_id")
        activity = activities.get(activity_id)
        record = output.get("activity_times", {}).get(activity_id)
        if activity is None or not isinstance(record, dict):
            return ["calculation trace activity is absent from the calculated output"]
        expected_start = record.get("remaining_start", record.get("start"))
        if trace.get("derived_start") != expected_start:
            errors.append("calculation trace derived_start differs from the calculated forecast state")
        if trace.get("derived_finish") != record.get("finish"):
            errors.append("calculation trace derived_finish differs from the calculated forecast state")
        if inputs.get("activity_id") != activity_id:
            errors.append("calculation trace input activity_id is inconsistent")

        governing = explanation.get("governing_entity")
        governing_type = governing.get("type") if isinstance(governing, dict) else None
        governing_id = governing.get("id") if isinstance(governing, dict) else None
        reason = explanation.get("reason_type")
        horizon = schedule["time_axis"]["horizon"]
        allowed = _allowed_units(schedule, activity)
        trace_intervals = inputs.get("allowed_intervals")
        if not isinstance(trace_intervals, list) or _units(trace_intervals) != allowed:
            errors.append("calculation trace allowed_intervals do not match canonical availability")

        if reason == "actual_progress":
            expected_source = (
                "actual_finish" if activity.get("actual_finish") is not None else "actual_start"
            )
            if (
                activity.get("actual_start") is None
                or governing_type != "actual_event"
                or governing_id != activity_id
                or governing.get("source_field") != expected_source
            ):
                errors.append("actual-progress trace does not identify the preserved actual event")
            for field in ("actual_start", "actual_finish", "remaining_duration"):
                if inputs.get(field) != activity.get(field):
                    errors.append(f"actual-progress trace {field} is inconsistent")
            if inputs.get("status_time") != schedule["project"].get("status_time"):
                errors.append("actual-progress trace status_time is inconsistent")
        elif reason == "calendar":
            if governing_type != "calendar" or governing_id != activity["calendar_id"]:
                errors.append("calendar trace does not identify the activity calendar")
            if inputs.get("calendar_id") != activity["calendar_id"]:
                errors.append("calendar trace calendar_id is inconsistent")
            if inputs.get("project_start") != schedule["project"]["project_start"]:
                errors.append("calendar trace project_start is inconsistent")
            if inputs.get("duration") != activity["duration"]:
                errors.append("calendar trace duration is inconsistent")
        elif reason == "date_constraint":
            constraints = {
                constraint["id"]: constraint
                for candidate in schedule["activities"]
                if candidate["id"] == activity_id
                for constraint in candidate.get("constraints", [])
            }
            constraint = constraints.get(governing_id)
            if governing_type != "constraint" or constraint is None:
                errors.append("date-constraint trace does not identify a constraint on the activity")
            else:
                expected_inputs = {
                    "constraint_id": constraint["id"],
                    "constraint_type": constraint["type"],
                    "constraint_value": constraint["value"],
                    "duration": activity["duration"],
                    "calendar_id": activity["calendar_id"],
                    "project_start": schedule["project"]["project_start"],
                }
                for field, expected in expected_inputs.items():
                    if inputs.get(field) != expected:
                        errors.append(f"date-constraint trace {field} is inconsistent")
                start_lower = schedule["project"]["project_start"]
                finish_lower = schedule["project"]["project_start"]
                if constraint["type"] == "start_no_earlier_than":
                    start_lower = max(start_lower, constraint["value"])
                elif constraint["type"] == "finish_no_earlier_than":
                    finish_lower = max(finish_lower, constraint["value"])
                expected_span = _earliest_span_units(
                    start_lower, finish_lower, activity["duration"], allowed, horizon
                )
                if expected_span != (record.get("start"), record.get("finish")):
                    errors.append("declared date constraint is not the governing supported span")
        elif reason == "resource_conflict":
            conflicting_id = explanation.get("conflicting_activity_id")
            conflicting = activities.get(conflicting_id)
            order = output.get("resource_order")
            if (
                governing_type != "resource"
                or governing_id not in resources
                or conflicting is None
                or not isinstance(order, list)
                or len(order) < 2
                or order[:2] != [conflicting_id, activity_id]
            ):
                errors.append("resource-conflict trace does not identify the selected capacity-one order")
            else:
                assigned = {
                    item["resource_id"] for item in activity.get("assignments", [])
                }
                conflicting_assigned = {
                    item["resource_id"] for item in conflicting.get("assignments", [])
                }
                if governing_id not in assigned & conflicting_assigned:
                    errors.append("resource-conflict trace resource is not shared by both activities")
                conflict_finish = output["activity_times"][conflicting_id]["finish"]
                expected_inputs = {
                    "resource_id": governing_id,
                    "conflicting_activity_id": conflicting_id,
                    "conflicting_activity_finish": conflict_finish,
                    "selected_resource_order": order,
                    "duration": activity["duration"],
                    "calendar_id": activity["calendar_id"],
                }
                for field, expected in expected_inputs.items():
                    if inputs.get(field) != expected:
                        errors.append(f"resource-conflict trace {field} is inconsistent")
                expected_span = _earliest_span_units(
                    conflict_finish,
                    conflict_finish,
                    activity["duration"],
                    allowed,
                    horizon,
                )
                if expected_span != (record.get("start"), record.get("finish")):
                    errors.append("declared resource conflict is not the governing supported span")
        elif reason == "precedence":
            relationship = relationships.get(governing_id)
            if (
                governing_type != "relationship"
                or relationship is None
                or relationship.get("successor_id") != activity_id
                or governing_id not in case.expected.get("driving_relationships", [])
            ):
                errors.append("precedence trace does not identify a curated governing relationship")
            else:
                relation_type = relationship["type"]
                predecessor_record = output["activity_times"][relationship["predecessor_id"]]
                predecessor_event_name = "finish" if relation_type[0] == "F" else "start"
                predecessor_coordinate = predecessor_record[predecessor_event_name]
                calendar = next(
                    item for item in schedule["calendars"] if item["id"] == activity["calendar_id"]
                )
                bound = _lag_from_units(
                    predecessor_coordinate,
                    relationship["lag"],
                    _units(calendar["working_intervals"]),
                    horizon,
                )
                expected_inputs = {
                    "relationship_id": relationship["id"],
                    "relationship_type": relation_type,
                    "predecessor_id": relationship["predecessor_id"],
                    "predecessor_event": predecessor_event_name,
                    "predecessor_coordinate": predecessor_coordinate,
                    "lag": relationship["lag"],
                    "lag_calendar": "successor_activity_calendar",
                    "relationship_bound": bound,
                    "calendar_id": activity["calendar_id"],
                }
                for field, expected in expected_inputs.items():
                    if inputs.get(field) != expected:
                        errors.append(f"precedence trace {field} is inconsistent")
        else:
            errors.append(f"calculation trace reason {reason!r} is not supported by Phase 1 evidence")
        return errors

    def validate_native_record(self, record: dict[str, Any]) -> list[str]:
        return self._schema_errors(self.execution_validator, record, "execution record")
