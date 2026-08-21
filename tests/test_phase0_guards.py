from __future__ import annotations

import copy
import csv
import hashlib
import json
import subprocess
import shutil
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

    @staticmethod
    def expected_activity_states(data: dict) -> list[dict]:
        return [
            {
                "activity_id": activity_id,
                "start": record["start"],
                "finish": record["finish"],
            }
            for activity_id, record in sorted(
                data["expected"]["activity_times"].items()
            )
        ]

    def objective_vector(self, schedule: dict, activity_states: list[dict]) -> list[int]:
        vector, errors = validate_phase0.recompute_objective_vector(
            schedule, activity_states, "test scenario"
        )
        self.assertEqual([], errors)
        self.assertIsNotNone(vector)
        return vector or []

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

        constraint_case = copy.deepcopy(self.relationship_case)
        constraint_case["schedule"]["activities"][0]["constraints"] = [
            {"id": "C-DUP", "type": "start_no_earlier_than", "value": 0},
            {"id": "C-DUP", "type": "finish_no_earlier_than", "value": 4},
        ]
        mutations.append(("constraint", constraint_case))

        for entity, data in mutations:
            with self.subTest(entity=entity):
                self.assertTrue(
                    any(f"duplicate {entity}" in error.lower() for error in self.cross_errors(data))
                )

    def test_unknown_explicit_lag_calendar_is_rejected(self) -> None:
        unknown = copy.deepcopy(self.relationship_case)
        unknown["schedule"]["relationships"][0]["lag_calendar"] = "CAL-MISSING"
        self.assertTrue(any("unknown lag calendar" in error for error in self.cross_errors(unknown)))

        known_but_unsupported = copy.deepcopy(self.relationship_case)
        known_but_unsupported["schedule"]["relationships"][0]["lag_calendar"] = "CAL-24X7"
        self.assertTrue(
            any(
                "explicit lag calendar CAL-24X7" in error
                and "not executable under reference-v0.3" in error
                for error in self.cross_errors(known_but_unsupported)
            )
        )

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
                {"activity_id": "A", "start": 0, "finish": 4, "mode_id": "MODE-1"},
                {"activity_id": "B", "start": 4, "finish": 7},
            ],
        }
        schedule["proposed_scenario"] = {
            "scenario_id": "SCN-1",
            "status": "proposed",
            "objective_policy_id": "objective-v0.3",
            "activity_states": [
                {"activity_id": "A", "start": 0, "finish": 4},
                {"activity_id": "B", "start": 4, "finish": 7},
            ],
            "governance": {},
        }
        schedule["proposed_scenario"]["objective_vector"] = self.objective_vector(
            schedule, schedule["proposed_scenario"]["activity_states"]
        )
        data["expected"]["reference_status"] = "native_validation_only"
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
            "schema_version": "0.1.4",
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
            "schema_version": "0.1.4",
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
            "schema_version": "0.1.3",
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
            "objective_policy_version": "objective-v0.3",
            "input_hash": HASH_A,
            "output_hash": HASH_B,
            "calculation_trace": None,
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
            for name in validate_phase0._EXPECTED_CONFIG_FILES:
                shutil.copy2(ROOT / "config" / name, config / name)

            objective_path = config / "objective-policy-v0.3.json"
            objective = load_json(objective_path)
            objective["milestone_priority_aggregation"]["group_primary"] = "maximum_lateness"
            objective_path.write_text(json.dumps(objective), encoding="utf-8")
            self.assertTrue(
                any("complete frozen definition" in error for error in validate_phase0.validate_configuration(root))
            )

            shutil.copy2(ROOT / "config" / "objective-policy-v0.3.json", objective_path)
            objective = load_json(objective_path)
            objective["levels"] = list(reversed(objective["levels"]))
            objective_path.write_text(json.dumps(objective), encoding="utf-8")
            self.assertTrue(
                any("complete frozen definition" in error for error in validate_phase0.validate_configuration(root))
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
            "schema_version": "0.1.4",
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
            "native_roundtrip_result": {
                "status": "not_applicable",
                "native_system": "not_applicable",
                "evidence_hash": None,
            },
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

        outside_frozen_horizon = copy.deepcopy(self.relationship_case)
        outside_frozen_horizon["schedule"]["project"]["frozen_horizon_finish"] = 2
        outside_frozen_horizon["schedule"]["activities"][0]["frozen_state"] = {
            "is_frozen": True,
            "frozen_start": 0,
            "frozen_finish": 4,
        }
        self.assertTrue(
            any(
                "exceeds frozen_horizon_finish 2" in error
                for error in self.cross_errors(outside_frozen_horizon)
            )
        )

    def test_complete_required_register_set_is_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            register_dir = root / "registers"
            register_dir.mkdir()
            names = set(validate_phase0._EXPECTED_REGISTERS)
            for name in names:
                header = ",".join(validate_phase0._EXPECTED_REGISTERS[name])
                (register_dir / name).write_text(header + "\n", encoding="utf-8")
            self.assertEqual([], validate_phase0.validate_registers(root))

            missing = sorted(names)[0]
            (register_dir / missing).unlink()
            self.assertTrue(
                any(missing in error and "missing" in error for error in validate_phase0.validate_registers(root))
            )

    def test_register_header_sequences_are_frozen(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            register_dir = root / "registers"
            register_dir.mkdir()
            for name, fields in validate_phase0._EXPECTED_REGISTERS.items():
                (register_dir / name).write_text(",".join(fields) + "\n", encoding="utf-8")
            target = register_dir / "input-economics-log.csv"
            target.write_text("id\n", encoding="utf-8")
            self.assertTrue(
                any(
                    "input-economics-log.csv" in error and "header sequence" in error
                    for error in validate_phase0.validate_registers(root)
                )
            )

    def test_reversed_schedule_state_interval_is_rejected(self) -> None:
        data = copy.deepcopy(self.relationship_case)
        data["schedule"]["baseline"] = {
            "state_id": "BASE-1",
            "state_type": "baseline",
            "activity_states": [{"activity_id": "A", "start": 5, "finish": 4}],
        }
        self.assertTrue(any("start exceeds finish" in error for error in self.cross_errors(data)))

    def test_attempted_native_roundtrip_requires_real_system(self) -> None:
        data = {
            "schema_version": "0.1.4",
            "execution_id": "EX-NATIVE",
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
            "feasibility_status": "not_applicable",
            "optimality_status": "not_applicable",
            "objective_vector": [],
            "best_bound": None,
            "optimality_gap": None,
            "native_roundtrip_result": {
                "status": "pass",
                "native_system": "not_applicable",
                "evidence_hash": HASH_D,
            },
            "evidence_paths": ["evidence/native.json"],
        }
        self.assertTrue(list(self.execution_validator.iter_errors(data)))

    def test_catalogue_metadata_must_match_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(ROOT / "schemas", root / "schemas")
            shutil.copytree(ROOT / "benchmarks", root / "benchmarks")
            catalogue = root / "benchmarks" / "semantic" / "catalogue.csv"
            text = catalogue.read_text(encoding="utf-8")
            catalogue.write_text(text.replace("FS zero lag", "Wrong title", 1), encoding="utf-8")
            self.assertTrue(
                any("does not match fixture value" in error for error in validate_phase0.validate_cases(root))
            )

    def test_wbs_multi_node_cycle_is_rejected(self) -> None:
        data = copy.deepcopy(self.relationship_case)
        data["schedule"]["wbs"] = [
            {"id": "WBS-A", "name": "A", "parent_id": "WBS-B"},
            {"id": "WBS-B", "name": "B", "parent_id": "WBS-A"},
        ]
        self.assertTrue(any("WBS hierarchy contains cycle" in error for error in self.cross_errors(data)))

    def test_in_progress_activity_requires_remaining_duration(self) -> None:
        data = copy.deepcopy(self.relationship_case)
        activity = data["schedule"]["activities"][0]
        activity["actual_start"] = 1
        activity["actual_finish"] = None
        activity.pop("remaining_duration", None)
        self.assertTrue(self.schema_errors(data))

    def test_explanation_movement_is_derived_from_coordinates(self) -> None:
        data = self.explanation(counterfactuals=[{
            "counterfactual_id": "CF-1",
            "description": "No change",
            "input_patch": [{"op": "replace", "path": "/resources/0/capacity", "value": 2}],
            "execution_identity": HASH_A,
            "result_status": "feasible",
            "result_hash": HASH_B,
            "output_hash": HASH_C,
            "objective_vector": [0],
            "validator_status": "pass",
            "evidence_paths": ["evidence/cf.json"],
        }])
        data["movement"] = 0
        errors = validate_phase0.validate_explanation_document(data)
        self.assertTrue(any("coordinate-derived movement" in error for error in errors))

    def test_objective_vector_shape_is_case_specific_and_complete(self) -> None:
        schedule = copy.deepcopy(self.relationship_case["schedule"])
        activity_states = self.expected_activity_states(self.relationship_case)
        vector = self.objective_vector(schedule, activity_states)
        expected = len(validate_phase0.objective_vector_layout(schedule))
        self.assertTrue(
            validate_phase0.validate_execution_record(
                {
                    "optimality_status": "optimal",
                    "selected_scenario_hash": HASH_A,
                    "objective_vector": [0] * (expected - 1),
                },
                schedule,
                activity_states_by_selected_scenario_hash={HASH_A: activity_states},
            )
        )
        self.assertEqual(
            [],
            validate_phase0.validate_execution_record(
                {
                    "optimality_status": "optimal",
                    "selected_scenario_hash": HASH_A,
                    "objective_vector": vector,
                },
                schedule,
                activity_states_by_selected_scenario_hash={HASH_A: activity_states},
            ),
        )

        milestone_schedule = copy.deepcopy(self.milestone_case["schedule"])
        without_priority = len(validate_phase0.objective_vector_layout(milestone_schedule))
        milestone = next(
            activity
            for activity in milestone_schedule["activities"]
            if activity["kind"] in {"start_milestone", "finish_milestone"}
        )
        milestone["milestone_priority"] = 10
        milestone["due_time"] = 5
        self.assertGreater(
            len(validate_phase0.objective_vector_layout(milestone_schedule)),
            without_priority,
        )

    def test_operational_constraint_windows_are_ordered_and_bounded(self) -> None:
        for label, start, finish in (
            ("reversed", 10, 5),
            ("outside", 0, 401),
        ):
            with self.subTest(label=label):
                data = copy.deepcopy(self.relationship_case)
                data["schedule"]["operational_constraints"] = [{
                    "id": "OC-1",
                    "type": "permit_window",
                    "hard": True,
                    "activity_ids": ["A"],
                    "resource_ids": [],
                    "window_start": start,
                    "window_finish": finish,
                }]
                self.assertTrue(any("operational constraint" in error for error in self.cross_errors(data)))

    def test_complete_deterministic_profile_is_frozen(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "config"
            config.mkdir()
            for name in validate_phase0._EXPECTED_CONFIG_FILES:
                shutil.copy2(ROOT / "config" / name, config / name)
            profile = load_json(config / "deterministic-execution-profile-v0.1.json")
            profile["worker_count"] = 2
            (config / "deterministic-execution-profile-v0.1.json").write_text(
                json.dumps(profile), encoding="utf-8"
            )
            self.assertTrue(any("complete frozen definition" in error for error in validate_phase0.validate_configuration(root)))

    def test_actual_dates_cannot_publish_declared_reference_results(self) -> None:
        data = copy.deepcopy(self.relationship_case)
        data["schedule"]["project"]["progress_policy"] = "actual_dates"
        data["expected"]["reference_status"] = "declared"
        self.assertTrue(any("native-validation-only" in error for error in self.cross_errors(data)))

    def test_proposed_scenario_must_cover_every_activity(self) -> None:
        data = copy.deepcopy(self.relationship_case)
        schedule = data["schedule"]
        schedule["proposed_scenario"] = {
            "scenario_id": "SCN-1",
            "status": "proposed",
            "objective_policy_id": "objective-v0.3",
            "objective_vector": [0] * len(validate_phase0.objective_vector_layout(schedule)),
            "activity_states": [{"activity_id": "A", "start": 0, "finish": 4}],
        }
        self.assertTrue(any("exactly cover" in error for error in self.cross_errors(data)))

    def test_approved_scenario_requires_approval_governance(self) -> None:
        data = copy.deepcopy(self.relationship_case)
        schedule = data["schedule"]
        schedule["proposed_scenario"] = {
            "scenario_id": "SCN-1",
            "status": "approved",
            "objective_policy_id": "objective-v0.3",
            "objective_vector": [0] * len(validate_phase0.objective_vector_layout(schedule)),
            "activity_states": [
                {"activity_id": "A", "start": 0, "finish": 4},
                {"activity_id": "B", "start": 4, "finish": 7},
            ],
            "governance": {},
        }
        self.assertTrue(self.schema_errors(data))

    def test_semantic_profile_is_frozen_and_resolved(self) -> None:
        data = copy.deepcopy(self.relationship_case)
        data["schedule"]["semantic_profile"] = "invented-v9"
        self.assertTrue(any("semantic_profile must resolve" in error for error in self.cross_errors(data)))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "config"
            config.mkdir()
            for name in validate_phase0._EXPECTED_CONFIG_FILES:
                shutil.copy2(ROOT / "config" / name, config / name)
            profile = load_json(config / "semantic-profile-reference-v0.3.json")
            profile["lag_policy"] = "changed"
            (config / "semantic-profile-reference-v0.3.json").write_text(
                json.dumps(profile), encoding="utf-8"
            )
            self.assertTrue(any("complete frozen definition" in error for error in validate_phase0.validate_configuration(root)))

    def test_milestone_execution_modes_must_be_zero_duration(self) -> None:
        data = copy.deepcopy(self.milestone_case)
        milestone = next(
            activity
            for activity in data["schedule"]["activities"]
            if activity["kind"] in {"start_milestone", "finish_milestone"}
        )
        milestone["eligible_modes"] = [{
            "id": "MODE-1",
            "duration": 1,
            "assignments": [],
        }]
        self.assertTrue(self.schema_errors(data))
        self.assertTrue(any("mode MODE-1 must have zero duration" in error for error in self.cross_errors(data)))

    def test_actual_date_intervals_are_valid(self) -> None:
        missing_start = copy.deepcopy(self.relationship_case)
        missing_start["schedule"]["activities"][0]["actual_finish"] = 4
        self.assertTrue(self.schema_errors(missing_start))
        self.assertTrue(any("actual_finish requires actual_start" in error for error in self.cross_errors(missing_start)))

        reversed_dates = copy.deepcopy(self.relationship_case)
        reversed_dates["schedule"]["activities"][0]["actual_start"] = 5
        reversed_dates["schedule"]["activities"][0]["actual_finish"] = 4
        self.assertTrue(any("actual_finish precedes" in error for error in self.cross_errors(reversed_dates)))

    def test_declared_milestone_oracle_has_zero_span(self) -> None:
        data = copy.deepcopy(self.milestone_case)
        milestone = next(
            activity
            for activity in data["schedule"]["activities"]
            if activity["kind"] in {"start_milestone", "finish_milestone"}
        )
        record = data["expected"]["activity_times"][milestone["id"]]
        record["finish"] = record["start"] + 1
        data["expected"]["project_finish"] = max(
            item["finish"] for item in data["expected"]["activity_times"].values()
        )
        self.assertTrue(any("must have start equal to finish" in error for error in self.cross_errors(data)))

        nonworking = copy.deepcopy(self.milestone_case)
        nonworking["schedule"]["calendars"][0]["working_intervals"] = [[4, 400]]
        self.assertTrue(
            any(
                "M.start 0" in error and "canonical value 4" in error
                for error in self.cross_errors(nonworking)
            )
        )

    def test_mandatory_milestone_rule_excludes_normal_tasks(self) -> None:
        schedule = copy.deepcopy(self.relationship_case["schedule"])
        schedule["activities"][0]["milestone_priority"] = 10
        schedule["activities"][0]["due_time"] = 2
        self.assertEqual({}, validate_phase0.mandatory_milestones(schedule))
        policy = load_json(ROOT / "config" / "objective-policy-v0.3.json")
        self.assertIn("kind_in_start_or_finish_milestone", policy["milestone_priority_aggregation"]["mandatory_definition"])

    def test_level_five_penalty_is_an_explicit_tuple(self) -> None:
        policy = load_json(ROOT / "config" / "objective-policy-v0.3.json")
        self.assertEqual(
            ["overtime_units", "mobilisation_block_count", "resource_peak_demand_sum"],
            policy["operational_resource_penalty"]["components"],
        )
        self.assertEqual("lexicographic", policy["operational_resource_penalty"]["ordering"])

    def test_passing_execution_requires_explicit_roundtrip_disposition(self) -> None:
        data = {
            "schema_version": "0.1.4",
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
            "feasibility_status": "not_applicable",
            "optimality_status": "not_applicable",
            "objective_vector": [],
            "best_bound": None,
            "optimality_gap": None,
            "native_roundtrip_result": None,
            "evidence_paths": ["evidence/EX-1.json"],
        }
        self.assertTrue(list(self.execution_validator.iter_errors(data)))

    def test_canonical_schema_version_advanced(self) -> None:
        self.assertEqual("0.1.3", self.relationship_case["schedule"]["schema_version"])
        data = copy.deepcopy(self.relationship_case)
        data["schedule"]["schema_version"] = "0.1.0"
        self.assertTrue(self.schema_errors(data))

    def test_authoritative_protocol_chapter_set_is_complete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(ROOT / "docs", root / "docs")
            (root / "docs" / validate_phase0.AUTHORITATIVE_CHAPTERS[0]).unlink()
            with self.assertRaises(RuntimeError):
                validate_phase0.authoritative_sources(root)

    def test_schedule_state_span_must_consume_declared_duration(self) -> None:
        data = copy.deepcopy(self.relationship_case)
        data["schedule"]["baseline"] = {
            "state_id": "BASE-1",
            "state_type": "baseline",
            "activity_states": [{"activity_id": "A", "start": 0, "finish": 0}],
        }
        self.assertTrue(any("calendar-derived finish" in error for error in self.cross_errors(data)))

    def test_declared_reference_results_are_bounded_by_horizon(self) -> None:
        data = copy.deepcopy(self.relationship_case)
        data["expected"]["activity_times"]["B"]["finish"] = 401
        data["expected"]["project_finish"] = 401
        self.assertTrue(any("outside horizon" in error for error in self.cross_errors(data)))

    def test_optimal_result_requires_zero_gap(self) -> None:
        data = {
            "schema_version": "0.1.4",
            "execution_id": "EX-OPT",
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
            "optimality_status": "optimal",
            "objective_vector": [0],
            "best_bound": 0,
            "optimality_gap": 1,
            "native_roundtrip_result": {
                "status": "not_applicable",
                "native_system": "not_applicable",
                "evidence_hash": None,
            },
            "evidence_paths": ["evidence/EX-OPT.json"],
        }
        self.assertTrue(list(self.execution_validator.iter_errors(data)))

    def test_calculation_trace_scope_requires_trace_evidence(self) -> None:
        data = self.explanation(counterfactuals=[])
        data.update({
            "decision_scope": "calculation_trace",
            "scenario_id": None,
            "selected_objective_vector": [],
            "counterfactuals": [],
            "solver_version": None,
            "objective_policy_version": None,
            "calculation_trace": None,
        })
        self.assertTrue(list(self.explanation_validator.iter_errors(data)))

    def test_passing_semantic_execution_can_be_not_applicable_to_optimisation(self) -> None:
        data = {
            "schema_version": "0.1.4",
            "execution_id": "EX-SEMANTIC",
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
            "feasibility_status": "not_applicable",
            "optimality_status": "not_applicable",
            "objective_vector": [],
            "best_bound": None,
            "optimality_gap": None,
            "native_roundtrip_result": {
                "status": "not_applicable",
                "native_system": "not_applicable",
                "evidence_hash": None,
            },
            "evidence_paths": ["evidence/semantic.json"],
        }
        self.assertEqual([], list(self.execution_validator.iter_errors(data)))

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

    def test_proposed_scenario_preserves_frozen_coordinates(self) -> None:
        data = copy.deepcopy(self.relationship_case)
        schedule = data["schedule"]
        schedule["activities"][0]["frozen_state"] = {
            "is_frozen": True,
            "frozen_start": 0,
            "frozen_finish": 4,
            "reason": "committed near-term work",
        }
        schedule["proposed_scenario"] = {
            "scenario_id": "SCN-FROZEN",
            "status": "proposed",
            "objective_policy_id": "objective-v0.3",
            "objective_vector": [0] * len(validate_phase0.objective_vector_layout(schedule)),
            "activity_states": [
                {"activity_id": "A", "start": 1, "finish": 5},
                {"activity_id": "B", "start": 5, "finish": 8},
            ],
        }
        self.assertTrue(
            any("must preserve frozen coordinates" in error for error in self.cross_errors(data))
        )

    def test_unexercised_fixed_constraints_are_not_claimed_by_reference_profile(self) -> None:
        historical = load_json(ROOT / "config" / "semantic-profile-reference-v0.1.json")
        intermediate = load_json(ROOT / "config" / "semantic-profile-reference-v0.2.json")
        active = load_json(ROOT / "config" / "semantic-profile-reference-v0.3.json")
        self.assertIn("fixed_start", historical["constraints"])
        self.assertIn("fixed_finish", historical["constraints"])
        self.assertNotIn("fixed_start", intermediate["constraints"])
        self.assertNotIn("fixed_finish", active["constraints"])
        self.assertEqual("reference-v0.1", intermediate["supersedes"])
        self.assertEqual("reference-v0.2", active["supersedes"])
        self.assertEqual("successor_calendar_only", active["lag_policy"])
        self.assertEqual("exclusive_capacity_one_only", active["resource_capacity_semantics"])

        data = copy.deepcopy(self.relationship_case)
        data["schedule"]["activities"][0]["constraints"].append(
            {"id": "C-FIXED", "type": "fixed_start", "value": 0}
        )
        self.assertTrue(
            any("is not executable under reference-v0.3" in error for error in self.cross_errors(data))
        )

    def test_explanation_causes_resolve_against_canonical_input(self) -> None:
        schedule = copy.deepcopy(self.resource_case["schedule"])
        states = self.expected_activity_states(self.resource_case)
        vector = self.objective_vector(schedule, states)
        schedule["proposed_scenario"] = {
            "scenario_id": "SCN-1",
            "status": "proposed",
            "objective_policy_id": "objective-v0.3",
            "objective_vector": vector,
            "activity_states": states,
        }
        counterfactual = {
            "counterfactual_id": "CF-1",
            "description": "Rename an activity without changing its schedule",
            "input_patch": [
                {"op": "replace", "path": "/activities/0/name", "value": "A revised"}
            ],
            "execution_identity": HASH_A,
            "result_status": "feasible",
            "result_hash": HASH_B,
            "output_hash": HASH_C,
            "objective_vector": vector,
            "validator_status": "pass",
            "milestone_impacts": [{"milestone_id": "MA", "movement": 0}],
            "evidence_paths": ["evidence/CF-1.json"],
        }
        explanation = self.explanation(counterfactuals=[counterfactual])
        explanation["selected_objective_vector"] = vector
        explanation["governing_entity"] = {"type": "resource", "id": "R-MISSING"}
        explanation["affected_milestone_id"] = "MA"
        evidence = {HASH_B: states, HASH_C: states}
        errors = validate_phase0.validate_explanation_document(
            explanation,
            schedule,
            activity_states_by_output_hash=evidence,
        )
        self.assertTrue(any("unknown ID R-MISSING" in error for error in errors))

        explanation["governing_entity"]["id"] = "R1"
        self.assertEqual(
            [],
            validate_phase0.validate_explanation_document(
                explanation,
                schedule,
                activity_states_by_output_hash=evidence,
            ),
        )

    def test_counterfactual_patch_paths_use_valid_json_pointer_escapes(self) -> None:
        base = {
            "counterfactual_id": "CF-1",
            "description": "Change an activity",
            "input_patch": [{"op": "replace", "path": "/activities/~2", "value": 1}],
            "execution_identity": HASH_A,
            "result_status": "feasible",
            "result_hash": HASH_B,
            "output_hash": HASH_C,
            "objective_vector": [0],
            "validator_status": "pass",
            "evidence_paths": ["evidence/CF-1.json"],
        }
        self.assertTrue(
            list(
                self.explanation_validator.iter_errors(
                    self.explanation(counterfactuals=[base])
                )
            )
        )
        base["input_patch"][0]["path"] = "/activities/0/source_fields/name~1code"
        self.assertEqual(
            [],
            list(
                self.explanation_validator.iter_errors(
                    self.explanation(counterfactuals=[base])
                )
            ),
        )

    def test_declared_relationship_oracle_enforces_all_formulas_and_signed_lags(self) -> None:
        mutations = {
            "sem-rel-001.json": ("B", {"start": 3, "finish": 6}),
            "sem-rel-002.json": ("A", {"start": 1, "finish": 5}),
            "sem-rel-003.json": ("A", {"start": 1, "finish": 5}),
            "sem-rel-004.json": ("A", {"start": 5, "finish": 9}),
            "sem-rel-005.json": ("B", {"start": 5, "finish": 8}),
            "sem-rel-006.json": ("B", {"start": 1, "finish": 4}),
            "sem-rel-007.json": ("B", {"start": 2, "finish": 5}),
            "sem-rel-008.json": ("B", {"start": 2, "finish": 5}),
            "sem-rel-009.json": ("B", {"start": 5, "finish": 8}),
            "sem-rel-010.json": ("B", {"start": 1, "finish": 4}),
            "sem-rel-011.json": ("B", {"start": 2, "finish": 5}),
            "sem-rel-012.json": ("B", {"start": 2, "finish": 5}),
        }
        for filename, (activity_id, coordinates) in mutations.items():
            with self.subTest(filename=filename):
                data = load_json(ROOT / "benchmarks" / "semantic" / "cases" / filename)
                data["expected"]["activity_times"][activity_id].update(coordinates)
                data["expected"]["project_finish"] = max(
                    record["finish"]
                    for record in data["expected"]["activity_times"].values()
                )
                self.assertTrue(
                    any(
                        "violates lower bound" in error
                        for error in self.cross_errors(data)
                    )
                )

    def test_declared_expected_spans_consume_activity_or_remaining_duration(self) -> None:
        duration_case = copy.deepcopy(self.relationship_case)
        duration_case["expected"]["activity_times"]["A"]["finish"] = 3
        duration_case["expected"]["activity_times"]["B"] = {
            "start": 3,
            "finish": 6,
        }
        duration_case["expected"]["project_finish"] = 6
        self.assertTrue(
            any(
                "A finish 3 does not equal calendar-derived finish 4" in error
                for error in self.cross_errors(duration_case)
            )
        )

        remaining_case = load_json(
            ROOT / "benchmarks" / "semantic" / "cases" / "sem-sta-040.json"
        )
        remaining_case["expected"]["activity_times"]["A"]["finish"] = 7
        remaining_case["expected"]["project_finish"] = 7
        self.assertTrue(
            any(
                "remaining-duration-derived finish 8" in error
                for error in self.cross_errors(remaining_case)
            )
        )

        actual_case = load_json(
            ROOT / "benchmarks" / "semantic" / "cases" / "sem-sta-039.json"
        )
        actual_case["expected"]["activity_times"]["A"]["finish"] = 5
        actual_case["expected"]["project_finish"] = 5
        self.assertTrue(
            any(
                "must preserve actual [1, 6]" in error
                for error in self.cross_errors(actual_case)
            )
        )

    def test_declared_expected_coordinates_enforce_supported_lower_bounds(self) -> None:
        mutations = []

        snet = load_json(
            ROOT / "benchmarks" / "semantic" / "cases" / "sem-con-035.json"
        )
        snet["expected"]["activity_times"]["A"] = {"start": 0, "finish": 3}
        snet["expected"]["project_finish"] = 3
        mutations.append(("start_no_earlier_than 5", snet))

        fnet = load_json(
            ROOT / "benchmarks" / "semantic" / "cases" / "sem-con-036.json"
        )
        fnet["expected"]["activity_times"]["A"] = {"start": 0, "finish": 3}
        fnet["expected"]["project_finish"] = 3
        mutations.append(("finish_no_earlier_than 7", fnet))

        project_start = copy.deepcopy(self.relationship_case)
        project_start["schedule"]["project"]["project_start"] = 1
        mutations.append(("precedes project start 1", project_start))

        status = load_json(
            ROOT / "benchmarks" / "semantic" / "cases" / "sem-sta-040.json"
        )
        status["expected"]["activity_times"]["A"]["remaining_start"] = 4
        status["expected"]["activity_times"]["A"]["finish"] = 7
        status["expected"]["project_finish"] = 7
        mutations.append(("precedes status time 5", status))

        for expected_error, data in mutations:
            with self.subTest(expected_error=expected_error):
                self.assertTrue(
                    any(
                        expected_error in error for error in self.cross_errors(data)
                    )
                )

        operational = copy.deepcopy(self.relationship_case)
        operational["schedule"]["operational_constraints"] = [
            {
                "id": "OC-1",
                "type": "permit_window",
                "hard": True,
                "activity_ids": ["A"],
                "resource_ids": [],
                "window_start": 10,
                "window_finish": 20,
            }
        ]
        self.assertTrue(
            any(
                "operational constraints" in error
                and "not executable under reference-v0.3" in error
                for error in self.cross_errors(operational)
            )
        )

        required_finish = copy.deepcopy(self.relationship_case)
        required_finish["schedule"]["project"]["required_finish"] = 2
        self.assertTrue(
            any(
                "project.required_finish" in error
                and "not executable under reference-v0.3" in error
                for error in self.cross_errors(required_finish)
            )
        )

    def test_declared_exclusive_resources_are_independently_feasible(self) -> None:
        overlap = load_json(
            ROOT / "benchmarks" / "semantic" / "cases" / "sem-det-049.json"
        )
        overlap["expected"]["activity_times"]["B"] = {"start": 0, "finish": 4}
        overlap["expected"]["project_finish"] = 4
        self.assertTrue(
            any(
                "concurrent demand 2 exceeds exclusive capacity 1" in error
                for error in self.cross_errors(overlap)
            )
        )

        excessive_demand = load_json(
            ROOT / "benchmarks" / "semantic" / "cases" / "sem-cal-027.json"
        )
        excessive_demand["schedule"]["activities"][0]["assignments"][0]["demand"] = 2
        self.assertTrue(
            any(
                "demand 2 exceeds resource R1 capacity 1" in error
                for error in self.cross_errors(excessive_demand)
            )
        )

        swapped_tie_break = load_json(
            ROOT / "benchmarks" / "semantic" / "cases" / "sem-det-049.json"
        )
        swapped_tie_break["expected"]["activity_times"] = {
            "A": {"start": 4, "finish": 8},
            "B": {"start": 0, "finish": 4},
        }
        swapped_tie_break["expected"]["resource_order"] = ["B", "A"]
        self.assertTrue(
            any(
                "objective-selected exclusive-resource order ['A', 'B']" in error
                for error in self.cross_errors(swapped_tie_break)
            )
        )

        touching = load_json(
            ROOT / "benchmarks" / "semantic" / "cases" / "sem-det-049.json"
        )
        self.assertFalse(
            any(
                "concurrent demand" in error for error in self.cross_errors(touching)
            )
        )

        unsupported_contention = load_json(
            ROOT / "benchmarks" / "semantic" / "cases" / "sem-det-049.json"
        )
        third = copy.deepcopy(unsupported_contention["schedule"]["activities"][1])
        third["id"] = "C"
        third["name"] = "C"
        unsupported_contention["schedule"]["activities"].append(third)
        unsupported_contention["expected"]["activity_times"]["C"] = {
            "start": 8,
            "finish": 12,
        }
        unsupported_contention["expected"]["project_finish"] = 12
        unsupported_contention["expected"]["resource_order"] = ["A", "B", "C"]
        self.assertTrue(
            any(
                "cannot be independently recomputed" in error
                for error in self.cross_errors(unsupported_contention)
            )
        )

    def test_objective_vectors_are_recomputed_from_complete_scenarios(self) -> None:
        data = load_json(
            ROOT / "benchmarks" / "semantic" / "cases" / "sem-det-050.json"
        )
        schedule = data["schedule"]
        states = self.expected_activity_states(data)
        vector = self.objective_vector(schedule, states)
        self.assertEqual(
            [
                0, 0, 0, 0, 4, 4, 4, 8, 0, 0, 1, 1, 0,
                4, 8, 0, 1, 0, 4, 0, 1, 8, 8, 0, 0, 4, 4, 0, 0,
            ],
            vector,
        )

        for index in range(len(vector)):
            with self.subTest(objective_index=index):
                corrupted = vector.copy()
                corrupted[index] += 1
                self.assertTrue(
                    any(
                        f"objective vector entry {index}" in error
                        for error in validate_phase0.validate_objective_vector(
                            corrupted,
                            schedule,
                            "scenario",
                            activity_states=states,
                        )
                    )
                )

        proposed = copy.deepcopy(data)
        proposed["schedule"]["proposed_scenario"] = {
            "scenario_id": "SCN-1",
            "status": "proposed",
            "objective_policy_id": "objective-v0.3",
            "objective_vector": vector.copy(),
            "activity_states": states,
        }
        self.assertEqual([], self.cross_errors(proposed))
        proposed["schedule"]["proposed_scenario"]["objective_vector"][7] = -1
        self.assertTrue(
            any(
                "project_finish" in error for error in self.cross_errors(proposed)
            )
        )

        record = {
            "optimality_status": "optimal",
            "selected_scenario_hash": HASH_A,
            "objective_vector": vector,
        }
        self.assertEqual(
            [],
            validate_phase0.validate_execution_record(
                record,
                schedule,
                activity_states_by_selected_scenario_hash={HASH_A: states},
            ),
        )
        self.assertTrue(validate_phase0.validate_execution_record(record, schedule))
        corrupted_record = copy.deepcopy(record)
        corrupted_record["objective_vector"][7] = -1
        self.assertTrue(
            any(
                "project_finish" in error
                for error in validate_phase0.validate_execution_record(
                    corrupted_record,
                    schedule,
                    activity_states_by_selected_scenario_hash={HASH_A: states},
                )
            )
        )
        unknown_record = {
            "optimality_status": "unknown",
            "selected_scenario_hash": HASH_A,
            "objective_vector": vector.copy(),
        }
        self.assertEqual(
            [],
            validate_phase0.validate_execution_record(
                unknown_record,
                schedule,
                activity_states_by_selected_scenario_hash={HASH_A: states},
            ),
        )
        unknown_record["objective_vector"][7] = 107
        self.assertTrue(
            any(
                "project_finish" in error
                for error in validate_phase0.validate_execution_record(
                    unknown_record,
                    schedule,
                    activity_states_by_selected_scenario_hash={HASH_A: states},
                )
            )
        )
        self.assertTrue(
            validate_phase0.validate_execution_record(
                record,
                schedule,
                activity_states_by_selected_scenario_hash={HASH_D: states},
            )
        )
        for demand in (0, -1):
            with self.subTest(invalid_external_demand=demand):
                invalid_states = copy.deepcopy(states)
                invalid_states[0]["assignments"] = [
                    {"resource_id": "R1", "demand": demand}
                ]
                demand_errors = validate_phase0.validate_execution_record(
                    record,
                    schedule,
                    activity_states_by_selected_scenario_hash={
                        HASH_A: invalid_states
                    },
                )
                self.assertTrue(demand_errors)
                self.assertTrue(any("minimum of 1" in error for error in demand_errors))

        malformed_values = (None, "oops", [None], {"resource_id": "R1", "demand": 1})
        for malformed in malformed_values:
            with self.subTest(malformed_external_assignments=malformed):
                malformed_states = copy.deepcopy(states)
                malformed_states[0]["assignments"] = malformed
                self.assertTrue(
                    validate_phase0.validate_execution_record(
                        record,
                        schedule,
                        activity_states_by_selected_scenario_hash={
                            HASH_A: malformed_states
                        },
                    )
                )
        malformed_mode = copy.deepcopy(states)
        malformed_mode[0]["mode_id"] = 7
        self.assertTrue(
            validate_phase0.validate_execution_record(
                record,
                schedule,
                activity_states_by_selected_scenario_hash={HASH_A: malformed_mode},
            )
        )

        schedule_with_scenario = copy.deepcopy(schedule)
        schedule_with_scenario["proposed_scenario"] = {
            "scenario_id": "SCN-1",
            "status": "proposed",
            "objective_policy_id": "objective-v0.3",
            "objective_vector": vector.copy(),
            "activity_states": states,
        }
        patched_schedule = copy.deepcopy(schedule)
        patched_schedule["activities"][2]["due_time"] = 3
        counterfactual_vector = self.objective_vector(patched_schedule, states)
        counterfactual = {
            "counterfactual_id": "CF-1",
            "description": "Move MA's mandatory due coordinate one unit earlier",
            "input_patch": [
                {"op": "replace", "path": "/activities/2/due_time", "value": 3}
            ],
            "execution_identity": HASH_A,
            "result_status": "feasible",
            "result_hash": HASH_B,
            "output_hash": HASH_C,
            "objective_vector": counterfactual_vector.copy(),
            "validator_status": "pass",
            "milestone_impacts": [{"milestone_id": "MA", "movement": 0}],
            "evidence_paths": ["evidence/CF-1.json"],
        }
        explanation = self.explanation(counterfactuals=[counterfactual])
        explanation["selected_objective_vector"] = vector.copy()
        explanation["affected_milestone_id"] = "MA"
        self.assertEqual(
            [],
            validate_phase0.validate_explanation_document(
                explanation,
                schedule_with_scenario,
                activity_states_by_output_hash={HASH_B: states, HASH_C: states},
            ),
        )
        missing_selected_states = validate_phase0.validate_explanation_document(
            explanation,
            schedule_with_scenario,
            activity_states_by_output_hash={HASH_C: states},
        )
        self.assertTrue(
            any(
                "complete activity states" in error
                and "counterfactual CF-1" not in error
                for error in missing_selected_states
            )
        )
        missing_counterfactual_states = validate_phase0.validate_explanation_document(
            explanation,
            schedule_with_scenario,
            activity_states_by_output_hash={HASH_B: states},
        )
        self.assertTrue(
            any(
                "counterfactual CF-1" in error
                and "complete activity states" in error
                for error in missing_counterfactual_states
            )
        )
        explanation["counterfactuals"][0]["objective_vector"][0] = 1
        self.assertTrue(
            any(
                "counterfactual CF-1" in error and "hard_violation_count" in error
                for error in validate_phase0.validate_explanation_document(
                    explanation,
                    schedule_with_scenario,
                    activity_states_by_output_hash={HASH_B: states, HASH_C: states},
                )
            )
        )

        invalid_profile = copy.deepcopy(explanation)
        invalid_profile["counterfactuals"][0]["input_patch"] = [
            {
                "op": "replace",
                "path": "/semantic_profile",
                "value": "invented-v9",
            }
        ]
        self.assertTrue(
            any(
                "semantic_profile must resolve" in error
                for error in validate_phase0.validate_explanation_document(
                    invalid_profile,
                    schedule_with_scenario,
                    activity_states_by_output_hash={HASH_B: states, HASH_C: states},
                )
            )
        )

        forecast_patch = copy.deepcopy(explanation)
        forecast_patch["counterfactuals"][0]["input_patch"] = [
            {"op": "replace", "path": "/approved_forecast", "value": None}
        ]
        self.assertTrue(
            any(
                "cannot modify the immutable approved forecast" in error
                for error in validate_phase0.validate_explanation_document(
                    forecast_patch,
                    schedule_with_scenario,
                    activity_states_by_output_hash={HASH_B: states, HASH_C: states},
                )
            )
        )

        proposed_patch = copy.deepcopy(explanation)
        proposed_patch["counterfactuals"][0]["input_patch"] = [
            {
                "op": "replace",
                "path": "/proposed_scenario/objective_vector/0",
                "value": 99,
            }
        ]
        self.assertTrue(
            any(
                "cannot modify the immutable proposed scenario" in error
                for error in validate_phase0.validate_explanation_document(
                    proposed_patch,
                    schedule_with_scenario,
                    activity_states_by_output_hash={HASH_B: states, HASH_C: states},
                )
            )
        )

        invalid_array_index = copy.deepcopy(explanation)
        invalid_array_index["counterfactuals"][0]["input_patch"] = [
            {
                "op": "replace",
                "path": "/activities/-1/name",
                "value": "invalid",
            }
        ]
        self.assertTrue(
            any(
                "invalid array index '-1'" in error
                for error in validate_phase0.validate_explanation_document(
                    invalid_array_index,
                    schedule_with_scenario,
                    activity_states_by_output_hash={HASH_B: states, HASH_C: states},
                )
            )
        )
        for path, expected_error in (
            ("/activities/01/name", "invalid array index '01'"),
            ("/activities/999", "cannot be applied: 999"),
        ):
            with self.subTest(invalid_counterfactual_array_path=path):
                bad_pointer = copy.deepcopy(explanation)
                bad_pointer["counterfactuals"][0]["input_patch"] = [
                    {"op": "add", "path": path, "value": {}}
                ]
                self.assertTrue(
                    any(
                        expected_error in error
                        for error in validate_phase0.validate_explanation_document(
                            bad_pointer,
                            schedule_with_scenario,
                            activity_states_by_output_hash={
                                HASH_B: states,
                                HASH_C: states,
                            },
                        )
                    )
                )

        self.assertEqual(
            [],
            validate_phase0.validate_execution_record(
                {"optimality_status": "not_applicable", "objective_vector": []},
                schedule,
            ),
        )

    def test_objective_recomputation_covers_nonconstant_policy_components(self) -> None:
        schedule = copy.deepcopy(self.resource_case["schedule"])
        schedule["relationships"] = []
        schedule["resources"].append(
            {
                "id": "R2",
                "type": "exclusive",
                "capacity": 1,
                "calendar_id": "CAL-24X7",
                "skills": [],
            }
        )
        activity_a, activity_b, milestone_a, milestone_b = schedule["activities"]
        activity_a["duration"] = 2
        activity_a["eligible_modes"] = [
            {
                "id": "MODE-1",
                "duration": 2,
                "calendar_id": "CAL-24X7",
                "assignments": [{"resource_id": "R1", "demand": 1}],
            },
            {
                "id": "MODE-2",
                "duration": 2,
                "calendar_id": "CAL-24X7",
                "assignments": [
                    {"resource_id": "R1", "demand": 1},
                    {"resource_id": "R2", "demand": 1},
                ],
            },
        ]
        activity_b["duration"] = 2
        milestone_a.update(
            {
                "id": "M1",
                "name": "M1",
                "milestone_priority": 10,
                "due_time": 0,
                "constraints": [
                    {
                        "id": "C-M1-01",
                        "type": "start_no_earlier_than",
                        "value": 5,
                    }
                ],
            }
        )
        milestone_b.update(
            {
                "id": "M2",
                "name": "M2",
                "milestone_priority": 10,
                "due_time": 0,
                "constraints": [
                    {
                        "id": "C-M2-01",
                        "type": "start_no_earlier_than",
                        "value": 2,
                    }
                ],
            }
        )
        states = [
            {
                "activity_id": "A",
                "start": 0,
                "finish": 2,
                "mode_id": "MODE-2",
            },
            {"activity_id": "B", "start": 4, "finish": 6},
            {"activity_id": "M1", "start": 5, "finish": 5},
            {"activity_id": "M2", "start": 2, "finish": 2},
        ]
        schedule["approved_forecast"] = {
            "state_id": "FCST-RICH",
            "state_type": "approved_forecast",
            "activity_states": [
                {"activity_id": "A", "start": 1, "finish": 3},
                {"activity_id": "B", "start": 3, "finish": 5},
                {"activity_id": "M1", "start": 4, "finish": 4},
                {"activity_id": "M2", "start": 1, "finish": 1},
            ],
        }
        vector = self.objective_vector(schedule, states)
        self.assertEqual(
            [
                0,
                7,
                5,
                5,
                2,
                6,
                8,
                0,
                3,
                2,
                0,
                0,
                2,
                2,
                1,
                1,
                4,
                6,
                0,
                1,
                0,
                5,
                5,
                0,
                0,
                0,
                2,
                2,
                0,
                0,
                0,
            ],
            vector,
        )

        invalid_forecast = copy.deepcopy(schedule)
        invalid_forecast["approved_forecast"]["activity_states"][0]["start"] = "bad"
        recomputed, errors = validate_phase0.recompute_objective_vector(
            invalid_forecast, states, "rich scenario"
        )
        self.assertIsNone(recomputed)
        self.assertTrue(any("is not of type 'integer'" in error for error in errors))

        mode_calendar = copy.deepcopy(self.relationship_case["schedule"])
        mode_calendar["calendars"].append(
            {
                "id": "CAL-LATE",
                "name": "Late",
                "working_intervals": [[10, 400]],
                "exceptions": [],
            }
        )
        mode_calendar["relationships"][0]["lag"] = 2
        mode_calendar["activities"][1]["eligible_modes"] = [
            {
                "id": "MODE-LATE",
                "duration": 3,
                "calendar_id": "CAL-LATE",
                "assignments": [],
            }
        ]
        mode_states = [
            {"activity_id": "A", "start": 0, "finish": 4},
            {
                "activity_id": "B",
                "start": 10,
                "finish": 13,
                "mode_id": "MODE-LATE",
            },
        ]
        _, mode_errors = validate_phase0.recompute_objective_vector(
            mode_calendar, mode_states, "mode-calendar scenario"
        )
        self.assertTrue(any("violates lower bound 12" in error for error in mode_errors))

    def test_declared_float_is_complete_and_recomputed(self) -> None:
        wrong_total = load_json(
            ROOT / "benchmarks" / "semantic" / "cases" / "sem-flt-047.json"
        )
        wrong_total["expected"]["activity_times"]["C"]["total_float"] = 999
        self.assertTrue(
            any(
                "C.total_float 999" in error
                for error in self.cross_errors(wrong_total)
            )
        )

        missing_free = load_json(
            ROOT / "benchmarks" / "semantic" / "cases" / "sem-flt-047.json"
        )
        del missing_free["expected"]["activity_times"]["D"]["free_float"]
        self.assertTrue(
            any(
                "requires integer D.free_float" in error
                for error in self.cross_errors(missing_free)
            )
        )

        missing_activity = load_json(
            ROOT / "benchmarks" / "semantic" / "cases" / "sem-flt-047.json"
        )
        del missing_activity["expected"]["activity_times"]["D"]
        self.assertTrue(
            any(
                "requires complete integer start/finish coordinates" in error
                for error in self.cross_errors(missing_activity)
            )
        )

        wrong_free = load_json(
            ROOT / "benchmarks" / "semantic" / "cases" / "sem-flt-048.json"
        )
        wrong_free["expected"]["activity_times"]["E"]["free_float"] = 0
        self.assertTrue(
            any(
                "E.free_float 0" in error
                for error in self.cross_errors(wrong_free)
            )
        )

        out_of_scope = copy.deepcopy(self.relationship_case)
        out_of_scope["expected"]["activity_times"]["A"].update(
            {"total_float": 999, "free_float": -999}
        )
        self.assertTrue(
            any(
                "executable only in the preregistered SEM-FLT-047/048" in error
                for error in self.cross_errors(out_of_scope)
            )
        )

        frozen = load_json(
            ROOT / "benchmarks" / "semantic" / "cases" / "sem-flt-047.json"
        )
        frozen["schedule"]["activities"][0]["frozen_state"] = {
            "is_frozen": True,
            "frozen_start": 0,
            "frozen_finish": 2,
        }
        self.assertTrue(
            any(
                "restricted to the preregistered 24x7" in error
                for error in self.cross_errors(frozen)
            )
        )

        native_only = load_json(
            ROOT / "benchmarks" / "semantic" / "cases" / "sem-sta-045.json"
        )
        native_only["expected"]["activity_times"]["A"].update(
            {"total_float": 999, "free_float": 999}
        )
        self.assertTrue(
            any(
                "executable only in the preregistered SEM-FLT-047/048" in error
                for error in self.cross_errors(native_only)
            )
        )

    def test_declared_oracle_matches_recomputed_canonical_earliest_schedule(self) -> None:
        shifted = copy.deepcopy(self.relationship_case)
        for record in shifted["expected"]["activity_times"].values():
            record["start"] += 1
            record["finish"] += 1
        shifted["expected"]["project_finish"] += 1
        self.assertTrue(
            any(
                "independently recomputed canonical value" in error
                for error in self.cross_errors(shifted)
            )
        )

        delayed_calendar = load_json(
            ROOT / "benchmarks" / "semantic" / "cases" / "sem-cal-025.json"
        )
        delayed_calendar["expected"]["activity_times"]["B"] = {
            "start": 25,
            "finish": 27,
        }
        delayed_calendar["expected"]["project_finish"] = 27
        self.assertTrue(
            any(
                "B.start 25" in error and "canonical value 24" in error
                for error in self.cross_errors(delayed_calendar)
            )
        )

        delayed_finish_bound = load_json(
            ROOT / "benchmarks" / "semantic" / "cases" / "sem-rel-003.json"
        )
        delayed_finish_bound["expected"]["activity_times"]["B"] = {
            "start": 2,
            "finish": 5,
        }
        delayed_finish_bound["expected"]["project_finish"] = 5
        self.assertTrue(
            any(
                "B.start 2" in error and "canonical value 1" in error
                for error in self.cross_errors(delayed_finish_bound)
            )
        )

    def test_declared_driving_relationships_are_governing(self) -> None:
        replaced = load_json(
            ROOT / "benchmarks" / "semantic" / "cases" / "sem-net-013.json"
        )
        replaced["expected"]["driving_relationships"] = ["R1"]
        errors = self.cross_errors(replaced)
        self.assertTrue(any("preregistered curated assertion set" in error for error in errors))
        self.assertTrue(any("does not govern C.start" in error for error in errors))

        removed = load_json(
            ROOT / "benchmarks" / "semantic" / "cases" / "sem-net-013.json"
        )
        removed["expected"]["driving_relationships"] = []
        self.assertTrue(
            any(
                "preregistered curated assertion set ['R2']" in error
                for error in self.cross_errors(removed)
            )
        )

        dominated = load_json(
            ROOT / "benchmarks" / "semantic" / "cases" / "sem-con-037.json"
        )
        dominated["expected"]["driving_relationships"] = ["R1"]
        self.assertTrue(
            any(
                "does not govern B.start" in error
                for error in self.cross_errors(dominated)
            )
        )

        for filename in ("sem-cal-025.json", "sem-net-017.json"):
            with self.subTest(valid_curated_subset=filename):
                control = load_json(
                    ROOT / "benchmarks" / "semantic" / "cases" / filename
                )
                self.assertFalse(
                    any(
                        "driving relationship" in error
                        for error in self.cross_errors(control)
                    )
                )

        native_only = load_json(
            ROOT / "benchmarks" / "semantic" / "cases" / "sem-sta-045.json"
        )
        native_only["expected"]["driving_relationships"] = ["R1"]
        self.assertTrue(
            any(
                "preregistered curated assertion set []" in error
                for error in self.cross_errors(native_only)
            )
        )

    def test_declared_cumulative_resource_is_not_claimed_without_a_fixture(self) -> None:
        data = copy.deepcopy(self.resource_case)
        data["schedule"]["resources"][0]["type"] = "cumulative"
        data["schedule"]["resources"][0]["capacity"] = 2
        self.assertEqual([], self.schema_errors(data))
        self.assertTrue(
            any(
                "cumulative capacity 2" in error
                and "not executable under reference-v0.3" in error
                for error in self.cross_errors(data)
            )
        )

    def test_frozen_fixture_identities_reject_well_formed_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(ROOT / "schemas", root / "schemas")
            shutil.copytree(ROOT / "benchmarks" / "semantic", root / "benchmarks" / "semantic")
            cases = root / "benchmarks" / "semantic" / "cases"
            old_path = cases / "sem-rel-001.json"
            replacement = load_json(old_path)
            replacement["case_id"] = "SEM-REL-099"
            old_path.unlink()
            (cases / "sem-rel-099.json").write_text(
                json.dumps(replacement, indent=2) + "\n", encoding="utf-8"
            )

            catalogue = root / "benchmarks" / "semantic" / "catalogue.csv"
            with catalogue.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
                fieldnames = list(rows[0])
            rows[0]["case_id"] = "SEM-REL-099"
            with catalogue.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)

            errors = validate_phase0.validate_cases(root)
            self.assertTrue(any("Frozen semantic fixture is missing: sem-rel-001.json" in error for error in errors))
            self.assertTrue(any("Unexpected semantic fixture identity: sem-rel-099.json" in error for error in errors))

    def test_approved_forecast_must_cover_every_activity(self) -> None:
        valid = {
            "state_id": "FCST-VALID",
            "state_type": "approved_forecast",
            "activity_states": [
                {"activity_id": "A", "start": 0, "finish": 4},
                {"activity_id": "B", "start": 4, "finish": 7},
            ],
        }

        missing = copy.deepcopy(self.relationship_case)
        missing["schedule"]["approved_forecast"] = copy.deepcopy(valid)
        missing["schedule"]["approved_forecast"]["activity_states"].pop()
        self.assertTrue(
            any(
                "approved_forecast activity states must exactly cover" in error
                for error in self.cross_errors(missing)
            )
        )

        invalid_states = {
            "unknown activity": {"activity_id": "UNKNOWN", "start": 4, "finish": 7},
            "duplicate activity state": {"activity_id": "A", "start": 4, "finish": 8},
            "unknown resource": {
                "activity_id": "B",
                "start": 4,
                "finish": 7,
                "assignments": [{"resource_id": "R-MISSING", "demand": 1}],
            },
            "unknown mode": {
                "activity_id": "B",
                "start": 4,
                "finish": 7,
                "mode_id": "MODE-MISSING",
            },
            "calendar-derived finish": {"activity_id": "B", "start": 4, "finish": 6},
        }
        for expected_error, invalid_state in invalid_states.items():
            with self.subTest(expected_error=expected_error):
                data = copy.deepcopy(self.relationship_case)
                data["schedule"]["approved_forecast"] = copy.deepcopy(valid)
                data["schedule"]["approved_forecast"]["activity_states"][1] = invalid_state
                self.assertTrue(
                    any(expected_error in error for error in self.cross_errors(data))
                )

        absent = copy.deepcopy(self.relationship_case)
        absent["schedule"]["approved_forecast"] = None
        self.assertFalse(
            any("approved_forecast" in error for error in self.cross_errors(absent))
        )

    def test_infeasible_proven_result_clears_selected_schedule_and_objective_evidence(self) -> None:
        record = {
            "schema_version": "0.1.4",
            "execution_id": "EX-INFEASIBLE",
            "case_id": "SEM-REL-001",
            "executed_at": "2026-08-17T12:00:00+08:00",
            "execution_identity": HASH_A,
            "status": "executed_fail",
            "input_hash": HASH_B,
            "output_hash": None,
            "selected_scenario_hash": None,
            "explanation_hash": None,
            "evidence_bundle_hash": HASH_C,
            "validator_status": "pass",
            "feasibility_status": "infeasible",
            "optimality_status": "infeasible_proven",
            "objective_vector": [],
            "best_bound": None,
            "optimality_gap": None,
            "native_roundtrip_result": None,
            "evidence_paths": ["evidence/infeasible.json"],
        }
        self.assertEqual([], list(self.execution_validator.iter_errors(record)))
        self.assertEqual(
            [],
            validate_phase0.validate_execution_record(
                record, self.relationship_case["schedule"]
            ),
        )

        proof_evidence = copy.deepcopy(record)
        proof_evidence["output_hash"] = HASH_D
        proof_evidence["explanation_hash"] = HASH_A
        self.assertEqual([], list(self.execution_validator.iter_errors(proof_evidence)))
        self.assertEqual(
            [],
            validate_phase0.validate_execution_record(
                proof_evidence, self.relationship_case["schedule"]
            ),
        )

        invalid_fields = {
            "feasibility_status": (
                "feasibility_status",
                "feasible",
                "must be classified infeasible",
            ),
            "selected_scenario_hash": (
                "selected_scenario_hash",
                HASH_D,
                "must not publish a selected-scenario hash",
            ),
            "objective_vector_nonempty": (
                "objective_vector",
                [0],
                "must have an empty objective vector",
            ),
            "objective_vector_null": (
                "objective_vector",
                None,
                "must have an empty objective vector",
            ),
            "best_bound": ("best_bound", 0, "must not publish a best bound"),
            "optimality_gap": (
                "optimality_gap",
                0,
                "must not publish an optimality gap",
            ),
        }
        for label, (field, invalid_value, expected_error) in invalid_fields.items():
            with self.subTest(field=label):
                invalid = copy.deepcopy(record)
                invalid[field] = invalid_value
                self.assertTrue(list(self.execution_validator.iter_errors(invalid)))
                self.assertTrue(
                    any(
                        expected_error in error
                        for error in validate_phase0.validate_execution_record(
                            invalid, self.relationship_case["schedule"]
                        )
                    )
                )

    def test_frozen_semantic_corpus_validates(self) -> None:
        self.assertEqual([], validate_phase0.validate_cases(ROOT))

    def test_in_progress_activity_requires_valid_status_time(self) -> None:
        data = copy.deepcopy(self.relationship_case)
        activity = data["schedule"]["activities"][0]
        activity["actual_start"] = 1
        activity["actual_finish"] = None
        activity["remaining_duration"] = 3
        data["schedule"]["project"]["status_time"] = None
        self.assertTrue(
            any("status_time must be an integer" in error for error in self.cross_errors(data))
        )

        data["schedule"]["project"]["status_time"] = 0
        self.assertTrue(
            any("precedes in-progress actual start" in error for error in self.cross_errors(data))
        )

        data["schedule"]["project"]["status_time"] = 1
        self.assertFalse(
            any("status_time" in error for error in self.cross_errors(data))
        )


if __name__ == "__main__":
    unittest.main()
