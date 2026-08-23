from __future__ import annotations

import copy
import json
from pathlib import PurePosixPath, Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from deterministic_scheduling_core.canonical.model import LoadedCase
from deterministic_scheduling_core.provenance.canonical_json import canonical_bytes, sha256_digest


def execution_record_hash(record: dict[str, Any]) -> str:
    """Hash the deterministic record identity projection.

    `executed_at` remains honest wall-clock metadata in the schema-valid record but
    is explicitly outside deterministic-v0.2 identity and evidence hashes.
    """

    projection = copy.deepcopy(record)
    projection.pop("executed_at", None)
    return sha256_digest(projection)


class EvidenceValidator:
    def __init__(self, repository_root: Path):
        schema_dir = repository_root / "schemas"
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
        bundle: dict[str, Any],
        record: dict[str, Any],
    ) -> list[str]:
        errors = self._schema_errors(self.execution_validator, record, "execution record")
        errors.extend(self._schema_errors(self.explanation_validator, explanation, "explanation"))
        output_hash = sha256_digest(output)
        selected_hash = sha256_digest(selected_state)
        validation_hash = sha256_digest(validation)
        explanation_hash = sha256_digest(explanation)
        identity_hash = sha256_digest(identity)
        bundle_hash = sha256_digest(bundle)
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
        }
        for label, (actual, wanted) in expected.items():
            if actual != wanted:
                errors.append(f"{label} is inconsistent with canonical artifact hash")
        if identity.get("canonical_input_hash") != case.input_hash:
            errors.append("execution identity does not bind the canonical input")
        for label, artifact in (
            ("output", output),
            ("selected state", selected_state),
            ("validation", validation),
            ("bundle", bundle),
            ("record", record),
        ):
            if artifact.get("case_id") != case.case_id:
                errors.append(f"{label} case_id does not bind the canonical case")
        selected_by_id = {
            state.get("activity_id"): state
            for state in selected_state.get("activity_states", [])
            if isinstance(state, dict)
        }
        output_times = output.get("activity_times", {})
        if set(selected_by_id) != set(output_times):
            errors.append("selected state does not completely cover the calculated output")
        else:
            for activity_id in sorted(output_times):
                for field in ("start", "finish"):
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
        evidence_paths = list(record.get("evidence_paths", []))
        evidence_paths.extend(bundle.get("evidence_paths", []))
        evidence_paths.extend(explanation.get("recomputation", {}).get("evidence_paths", []))
        evidence_paths.extend(
            explanation.get("calculation_trace", {}).get("evidence_paths", [])
        )
        errors.extend(self._path_errors(evidence_paths, "execution evidence"))
        for label, artifact in (
            ("calculated output", output),
            ("selected state", selected_state),
            ("validation", validation),
            ("explanation", explanation),
            ("execution identity", identity),
            ("evidence bundle", bundle),
        ):
            canonical_bytes(artifact)
            errors.extend(self._volatile_key_errors(artifact, label))
        return errors

    def validate_native_record(self, record: dict[str, Any]) -> list[str]:
        return self._schema_errors(self.execution_validator, record, "execution record")
