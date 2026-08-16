from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import validate_phase0  # noqa: E402
from repository_files import repository_paths  # noqa: E402

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class Phase0GuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.case_schema = load_json(ROOT / "schemas" / "semantic-test-case.schema.json")
        cls.canonical_schema = load_json(ROOT / "schemas" / "canonical-schedule.schema.json")
        registry = Registry().with_resource(
            "https://example.invalid/dsc/canonical-schedule.schema.json",
            Resource.from_contents(cls.canonical_schema),
        )
        cls.case_validator = Draft202012Validator(
            cls.case_schema, registry=registry, format_checker=FormatChecker()
        )
        cls.execution_validator = Draft202012Validator(
            load_json(ROOT / "schemas" / "execution-record.schema.json"),
            format_checker=FormatChecker(),
        )
        cls.explanation_validator = Draft202012Validator(
            load_json(ROOT / "schemas" / "structured-explanation.schema.json"),
            format_checker=FormatChecker(),
        )
        cls.relationship_case = load_json(
            ROOT / "benchmarks" / "semantic" / "cases" / "sem-rel-001.json"
        )
        cls.resource_case = load_json(
            ROOT / "benchmarks" / "semantic" / "cases" / "sem-det-050.json"
        )
        cls.milestone_case = load_json(
            ROOT / "benchmarks" / "semantic" / "cases" / "sem-mil-031.json"
        )

    def schema_errors(self, data: dict) -> list[str]:
        return [error.message for error in self.case_validator.iter_errors(data)]

    def cross_errors(self, data: dict) -> list[str]:
        return validate_phase0.validate_case_document(data, "case.json")

    def test_duplicate_stable_ids_are_rejected(self) -> None:
        mutations = []

        calendar_case = copy.deepcopy(self.relationship_case)
        calendar_case["schedule"]["calendars"].append(
            copy.deepcopy(calendar_case["schedule"]["calendars"][0])
        )
        mutations.append(("calendar", calendar_case))

        resource_case = copy.deepcopy(self.resource_case)
        resource_case["schedule"]["resources"].append(
            copy.deepcopy(resource_case["schedule"]["resources"][0])
        )
        mutations.append(("resource", resource_case))

        relationship_case = copy.deepcopy(self.relationship_case)
        relationship_case["schedule"]["relationships"].append(
            copy.deepcopy(relationship_case["schedule"]["relationships"][0])
        )
        mutations.append(("relationship", relationship_case))

        for entity, data in mutations:
            with self.subTest(entity=entity):
                self.assertTrue(
                    any(f"duplicate {entity}" in error.lower() for error in self.cross_errors(data))
                )

    def test_unknown_explicit_lag_calendar_is_rejected(self) -> None:
        data = copy.deepcopy(self.relationship_case)
        data["schedule"]["relationships"][0]["lag_calendar"] = "CAL-MISSING"
        self.assertTrue(any("unknown lag calendar" in error for error in self.cross_errors(data)))

    def test_invalid_calendar_intervals_are_rejected(self) -> None:
        cases = {
            "reversed": [[5, 5]],
            "overlap": [[0, 10], [9, 20]],
            "outside_horizon": [[0, 401]],
            "not_canonical_order": [[20, 30], [0, 10]],
        }
        for label, intervals in cases.items():
            with self.subTest(label=label):
                data = copy.deepcopy(self.relationship_case)
                data["schedule"]["calendars"][0]["working_intervals"] = intervals
                self.assertTrue(self.cross_errors(data))

    def test_declared_expected_oracle_must_be_complete_and_resolved(self) -> None:
        missing = copy.deepcopy(self.relationship_case)
        del missing["expected"]["activity_times"]["A"]
        self.assertTrue(any("omits" in error for error in self.cross_errors(missing)))

        unknown = copy.deepcopy(self.relationship_case)
        unknown["expected"]["activity_times"]["UNKNOWN"] = {"start": 0, "finish": 1}
        self.assertTrue(any("unknown IDs" in error for error in self.cross_errors(unknown)))

        incomplete = copy.deepcopy(self.relationship_case)
        del incomplete["expected"]["activity_times"]["A"]["start"]
        self.assertTrue(self.schema_errors(incomplete))
        self.assertTrue(any("start missing" in error for error in self.cross_errors(incomplete)))

    def test_milestone_duration_must_be_zero(self) -> None:
        data = copy.deepcopy(self.milestone_case)
        milestone = next(
            activity
            for activity in data["schedule"]["activities"]
            if activity["kind"] in {"start_milestone", "finish_milestone"}
        )
        milestone["duration"] = 1
        self.assertTrue(self.schema_errors(data))

    def test_exclusive_resource_capacity_must_be_one(self) -> None:
        data = copy.deepcopy(self.resource_case)
        data["schedule"]["resources"][0]["capacity"] = 2
        self.assertTrue(self.schema_errors(data))

    def test_canonical_schema_represents_declared_model_states(self) -> None:
        data = copy.deepcopy(self.relationship_case)
        schedule = data["schedule"]
        schedule["source_file_hash"] = HASH_A
        schedule["wbs"] = [{"id": "WBS-1", "name": "Test", "parent_id": None}]
        schedule["activities"][0]["wbs_id"] = "WBS-1"
        schedule["activities"][0]["eligible_modes"] = [
            {"id": "MODE-1", "duration": 4, "calendar_id": "CAL-24X7", "assignments": []}
        ]
        schedule["baseline"] = {
            "state_id": "BASE-1",
            "state_type": "baseline",
            "activity_states": [{"activity_id": "A", "start": 0, "finish": 4}],
        }
        schedule["approved_forecast"] = {
            "state_id": "FCST-1",
            "state_type": "approved_forecast",
            "activity_states": [
                {"activity_id": "A", "start": 0, "finish": 4, "mode_id": "MODE-1"}
            ],
        }
        schedule["proposed_scenario"] = {
            "scenario_id": "SCN-1",
            "status": "proposed",
            "objective_policy_id": "objective-v0.2",
            "objective_vector": [0, 7],
            "activity_states": [{"activity_id": "A", "start": 0, "finish": 4}],
            "governance": {},
        }
        self.assertEqual([], self.schema_errors(data))
        self.assertEqual([], self.cross_errors(data))

    @staticmethod
    def nonexecuted_record(status: str) -> dict:
        native = None
        if status == "native_validation_required":
            native = {
                "status": "required_not_run",
                "native_system": "p6",
                "evidence_hash": None,
            }
        return {
            "schema_version": "0.1.2",
            "execution_id": f"EX-{status}",
            "case_id": "SEM-REL-001",
            "executed_at": None,
            "execution_identity": None,
            "status": status,
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
            "native_roundtrip_result": native,
            "evidence_paths": [],
        }

    def test_all_protocol_result_labels_are_representable(self) -> None:
        statuses = [
            "not_executed",
            "not_accessible",
            "native_validation_required",
            "practitioner_validation_required",
            "buyer_validation_required",
        ]
        for status in statuses:
            with self.subTest(status=status):
                errors = list(self.execution_validator.iter_errors(self.nonexecuted_record(status)))
                self.assertEqual([], errors)

    def test_executed_pass_requires_evidence_hashes_and_validator(self) -> None:
        invalid = {
            **self.nonexecuted_record("not_executed"),
            "execution_id": "EX-BAD",
            "executed_at": "2026-08-16T12:00:00+08:00",
            "status": "executed_pass",
            "validator_status": "not_run",
            "feasibility_status": "not_run",
            "optimality_status": "not_run",
            "evidence_paths": [],
        }
        self.assertTrue(list(self.execution_validator.iter_errors(invalid)))

    def test_complete_executed_pass_record_is_valid(self) -> None:
        valid = {
            "schema_version": "0.1.2",
            "execution_id": "EX-1",
            "case_id": "SEM-REL-001",
            "executed_at": "2026-08-16T12:00:00+08:00",
            "execution_identity": HASH_A,
            "status": "executed_pass",
            "input_hash": HASH_B,
            "output_hash": HASH_C,
            "selected_scenario_hash": HASH_C,
            "explanation_hash": HASH_D,
            "evidence_bundle_hash": HASH_A,
            "validator_status": "pass",
            "feasibility_status": "feasible",
            "optimality_status": "not_applicable",
            "objective_vector": [],
            "best_bound": None,
            "optimality_gap": None,
            "native_roundtrip_result": {
                "status": "not_applicable",
                "native_system": "not_applicable",
                "evidence_hash": None,
            },
            "evidence_paths": ["evidence/EX-1.json"],
        }
        self.assertEqual([], list(self.execution_validator.iter_errors(valid)))

    @staticmethod
    def explanation(counterfactuals: list[dict]) -> dict:
        return {
            "schema_version": "0.1.2",
            "explanation_id": "EXP-1",
            "decision_scope": "optimisation_scenario",
            "scenario_id": "SCN-1",
            "activity_id": "A",
            "previous_start": 0,
            "previous_finish": 4,
            "proposed_start": 4,
            "proposed_finish": 8,
            "movement": 4,
            "movement_basis": "both",
            "reason_type": "resource_conflict",
            "governing_entity": {"type": "resource", "id": "R1"},
            "conflicting_activity_id": "B",
            "affected_milestone_id": "M1",
            "selection_reason": "lower mandatory milestone lateness",
            "selected_objective_vector": [0, 0, 8],
            "counterfactuals": counterfactuals,
            "model_version": "model-0.1",
            "solver_version": "solver-1",
            "objective_policy_version": "objective-v0.2",
            "input_hash": HASH_A,
            "output_hash": HASH_B,
            "recomputation": {
                "execution_identity": HASH_C,
                "validator_status": "pass",
                "evidence_paths": ["evidence/recompute.json"],
            },
        }

    def test_optimisation_explanation_requires_recomputable_counterfactual(self) -> None:
        self.assertTrue(
            list(self.explanation_validator.iter_errors(self.explanation(counterfactuals=[])))
        )

        counterfactual = {
            "counterfactual_id": "CF-1",
            "description": "Add one unit of R1 capacity",
            "input_patch": [{"op": "replace", "path": "/resources/0/capacity", "value": 2}],
            "execution_identity": HASH_A,
            "result_status": "feasible",
            "result_hash": HASH_B,
            "output_hash": HASH_C,
            "objective_vector": [0, 0, 4],
            "validator_status": "pass",
            "activity_start": 0,
            "activity_finish": 4,
            "milestone_impacts": [{"milestone_id": "M1", "movement": 0}],
            "evidence_paths": ["evidence/CF-1.json"],
        }
        self.assertEqual(
            [],
            list(
                self.explanation_validator.iter_errors(
                    self.explanation(counterfactuals=[counterfactual])
                )
            ),
        )


    def test_nonexecuted_records_cannot_claim_an_input_hash(self) -> None:
        data = self.nonexecuted_record("not_accessible")
        data["input_hash"] = HASH_A
        self.assertTrue(list(self.execution_validator.iter_errors(data)))

    def test_scenario_state_assignment_resources_must_resolve(self) -> None:
        data = copy.deepcopy(self.relationship_case)
        data["schedule"]["baseline"] = {
            "state_id": "BASE-1",
            "state_type": "baseline",
            "activity_states": [
                {
                    "activity_id": "A",
                    "start": 0,
                    "finish": 4,
                    "assignments": [{"resource_id": "R-MISSING", "demand": 1}],
                }
            ],
        }
        self.assertTrue(
            any("baseline activity A references unknown resource R-MISSING" in error for error in self.cross_errors(data))
        )

    def test_feasible_counterfactual_requires_validated_output_and_objective(self) -> None:
        base = {
            "counterfactual_id": "CF-1",
            "description": "Add one unit of R1 capacity",
            "input_patch": [{"op": "replace", "path": "/resources/0/capacity", "value": 2}],
            "execution_identity": HASH_A,
            "result_status": "feasible",
            "result_hash": HASH_B,
            "output_hash": HASH_C,
            "objective_vector": [0, 0, 4],
            "validator_status": "pass",
            "evidence_paths": ["evidence/CF-1.json"],
        }
        for label, mutation in {
            "missing_output": {"output_hash": None},
            "empty_objective": {"objective_vector": []},
            "failed_validator": {"validator_status": "fail"},
        }.items():
            with self.subTest(label=label):
                invalid = {**base, **mutation}
                self.assertTrue(
                    list(
                        self.explanation_validator.iter_errors(
                            self.explanation(counterfactuals=[invalid])
                        )
                    )
                )

    def test_date_time_formats_are_enforced(self) -> None:
        for value in ("not-a-date", "2026-08-16T12:00:00"):
            with self.subTest(value=value):
                data = copy.deepcopy(self.relationship_case)
                data["schedule"]["time_axis"]["origin"] = value
                self.assertTrue(self.schema_errors(data))

    def test_objective_policy_values_and_order_are_frozen(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "config"
            config.mkdir()
            objective = load_json(ROOT / "config" / "objective-policy-v0.2.json")
            deterministic = load_json(
                ROOT / "config" / "deterministic-execution-profile-v0.1.json"
            )
            (config / "deterministic-execution-profile-v0.1.json").write_text(
                json.dumps(deterministic), encoding="utf-8"
            )

            objective["milestone_priority_aggregation"]["group_primary"] = "maximum_lateness"
            (config / "objective-policy-v0.2.json").write_text(
                json.dumps(objective), encoding="utf-8"
            )
            self.assertTrue(
                any("aggregation values" in error for error in validate_phase0.validate_configuration(root))
            )

            objective = load_json(ROOT / "config" / "objective-policy-v0.2.json")
            objective["levels"] = list(reversed(objective["levels"]))
            (config / "objective-policy-v0.2.json").write_text(
                json.dumps(objective), encoding="utf-8"
            )
            self.assertTrue(
                any("ordered level definitions" in error for error in validate_phase0.validate_configuration(root))
            )

    def test_schedule_state_type_must_match_its_container(self) -> None:
        data = copy.deepcopy(self.relationship_case)
        data["schedule"]["baseline"] = {
            "state_id": "BAD-BASE",
            "state_type": "approved_forecast",
            "activity_states": [{"activity_id": "A", "start": 0, "finish": 4}],
        }
        self.assertTrue(self.schema_errors(data))
        self.assertTrue(any("baseline state_type" in error for error in self.cross_errors(data)))

    def test_passing_execution_rejects_infeasible_optimality(self) -> None:
        data = {
            "schema_version": "0.1.2",
            "execution_id": "EX-CONTRADICTORY",
            "case_id": "SEM-REL-001",
            "executed_at": "2026-08-16T12:00:00+08:00",
            "execution_identity": HASH_A,
            "status": "executed_pass",
            "input_hash": HASH_B,
            "output_hash": HASH_C,
            "selected_scenario_hash": HASH_C,
            "explanation_hash": HASH_D,
            "evidence_bundle_hash": HASH_A,
            "validator_status": "pass",
            "feasibility_status": "feasible",
            "optimality_status": "infeasible_proven",
            "objective_vector": [0],
            "best_bound": None,
            "optimality_gap": None,
            "native_roundtrip_result": None,
            "evidence_paths": ["evidence/EX.json"],
        }
        self.assertTrue(list(self.execution_validator.iter_errors(data)))

    def test_frozen_activity_requires_valid_coordinates(self) -> None:
        missing = copy.deepcopy(self.relationship_case)
        missing["schedule"]["activities"][0]["frozen_state"] = {"is_frozen": True}
        self.assertTrue(self.schema_errors(missing))

        reversed_coordinates = copy.deepcopy(self.relationship_case)
        reversed_coordinates["schedule"]["activities"][0]["frozen_state"] = {
            "is_frozen": True,
            "frozen_start": 10,
            "frozen_finish": 5,
        }
        self.assertTrue(
            any("frozen start exceeds" in error for error in self.cross_errors(reversed_coordinates))
        )

    def test_complete_required_register_set_is_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            register_dir = root / "registers"
            register_dir.mkdir()
            names = set(validate_phase0._EXPECTED_REGISTERS)
            for name in names:
                (register_dir / name).write_text("id\n", encoding="utf-8")
            self.assertEqual([], validate_phase0.validate_registers(root))

            missing = sorted(names)[0]
            (register_dir / missing).unlink()
            self.assertTrue(
                any(missing in error and "missing" in error for error in validate_phase0.validate_registers(root))
            )

    def test_manifest_file_set_excludes_git_metadata_and_detects_omission(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.txt").write_text("a\n", encoding="utf-8")
            (root / "b.txt").write_text("b\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "add", "a.txt", "b.txt"], check=True)

            paths = {path.as_posix() for path in repository_paths(root)}
            self.assertEqual({"a.txt", "b.txt"}, paths)
            self.assertFalse(any(path.startswith(".git/") for path in paths))

            digest = hashlib.sha256((root / "a.txt").read_bytes()).hexdigest()
            (root / "manifest.sha256").write_text(f"{digest}  a.txt\n", encoding="utf-8")
            errors = validate_phase0.validate_manifest(root)
            self.assertTrue(any("b.txt" in error and "missing from manifest" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
