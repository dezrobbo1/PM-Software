from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import py_compile
import runpy
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from deterministic_scheduling_core.native.msproject import (
    freeze,
    headless,
    headless_compare,
    headless_com,
    pilot,
)


ROOT = Path(__file__).resolve().parents[3]
RUNNER = ROOT / "tools" / "run_msproject_headless_relationship_characterisation.py"
LEGACY_TEST = ROOT / "tests" / "phase1" / "unit" / "test_msproject_headless_characterisation.py"


def _runner() -> dict:
    return runpy.run_path(str(RUNNER))


def _artifact_files(workspace: Path, roles: set[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for role in roles:
        suffix = ".mpp" if role.endswith("mpp") else ".xml"
        path = workspace / f"{role}{suffix}"
        path.write_bytes(f"evidence:{role}".encode("ascii"))
        result[role] = str(path)
    return result


def _comparison() -> dict:
    cases = []
    for case_id in headless.CASE_IDS:
        normalized = {
            "case_id": case_id,
            "activities": {
                "A": {"start": 0, "finish": 4},
                "B": {"start": 4, "finish": 7},
            },
            "project_finish": 7,
            "extra_native_tasks": [],
        }
        values = {
            "activities.A.start": 0,
            "activities.A.finish": 4,
            "activities.B.start": 4,
            "activities.B.finish": 7,
            "project_finish": 7,
        }
        cases.append(
            {
                "case_id": case_id,
                "status": "characterisation_exact",
                "fields": [
                    {
                        "field": name,
                        "native": value,
                        "reference": value,
                        "classification": "exact_match",
                    }
                    for name, value in values.items()
                ],
                "normalized_native": normalized,
            }
        )
    return {
        "schema_version": "headless-msproject-comparison-v0.1",
        "characterisation_label": headless.TRACK_ID,
        "run_id": "run",
        "manual_native_semantic_parity_status_emitted": False,
        "oracle_provenance": {
            "schema_version": "headless-msproject-oracle-provenance-v0.1",
            "source_bundle": {
                source_role: {
                    "module": spec["module"],
                    "relative_path": spec["relative_path"],
                    "sha256": f"{index:064x}",
                }
                for index, (source_role, spec) in enumerate(
                    headless_compare.ORACLE_SOURCE_SPECS.items(), start=1
                )
            },
            "sealed_references": [
                {
                    "case_id": case_id,
                    "relative_path": (
                        "native-validation/pilot-kits/"
                        "microsoft-project-relationship-v0.1/"
                        f"sealed-expected-normalized/{case_id}.json"
                    ),
                    "sha256": f"{index:064x}",
                    "source_kind": "sealed_reference_byte_snapshot",
                    "bound_fixture": {
                        "case_id": case_id,
                        "relative_path": (
                            "benchmarks/semantic/cases/" f"{case_id.lower()}.json"
                        ),
                        "sha256": f"{index + 100:064x}",
                        "byte_size": 1000 + index,
                        "source_kind": "bound_fixture_byte_snapshot",
                    },
                }
                for index, case_id in enumerate(headless.CASE_IDS, start=1)
            ],
        },
        "cases": cases,
    }


def _synthetic_bound_oracle(
    case_id: str = "SEM-REL-001",
) -> tuple[dict, dict, bytes, str]:
    fixture = {
        "case_id": case_id,
        "expected": {
            "reference_status": "reference_exact",
            "activity_times": {
                "A": {"start": 0, "finish": 4},
                "B": {"start": 4, "finish": 7},
            },
            "project_finish": 7,
        },
    }
    fixture_bytes = headless.canonical_bytes(fixture) + b"\n"
    fixture_digest = hashlib.sha256(fixture_bytes).hexdigest()
    sealed = pilot._sealed_expected(case_id, fixture)
    sealed["source_bindings"]["fixture"]["raw_sha256"] = fixture_digest
    return sealed, fixture, fixture_bytes, fixture_digest


def _native_worker_event(
    *, sequence: int, worker_pid: int, stage: str, phase: str, details: dict
) -> dict:
    return {
        "sequence": sequence,
        "worker_pid": worker_pid,
        "stage": stage,
        "phase": phase,
        "details": details,
    }


def _write_synthetic_native_worker_evidence(
    command: list[str],
    *,
    worker_pid: int,
    result: dict,
    operation: str = "case",
    run_id: str = "run",
    case_id: str | None = "SEM-REL-001",
    intermediate_events: list[tuple[str, str, dict]] | None = None,
) -> tuple[str, list[dict]]:
    result_path = Path(command[command.index("--result") + 1])
    state_path = Path(command[command.index("--state") + 1])
    log_path = Path(command[command.index("--log") + 1])
    result_sha256 = headless.durable_write_canonical_json(result_path, result)
    events = [
        _native_worker_event(
            sequence=1,
            worker_pid=worker_pid,
            stage="worker",
            phase="start",
            details={
                "operation": operation,
                "run_id": run_id,
                "case_id": case_id,
            },
        )
    ]
    for stage, phase, details in intermediate_events or []:
        events.append(
            _native_worker_event(
                sequence=len(events) + 1,
                worker_pid=worker_pid,
                stage=stage,
                phase=phase,
                details=details,
            )
        )
    events.append(
        _native_worker_event(
            sequence=len(events) + 1,
            worker_pid=worker_pid,
            stage="worker",
            phase="complete",
            details={
                "operation": operation,
                "result_sha256": result_sha256,
            },
        )
    )
    headless.durable_write_bytes(
        log_path,
        b"".join(headless.canonical_bytes(event) + b"\n" for event in events),
    )
    headless.durable_write_canonical_json(state_path, events[-1])
    return result_sha256, events


def _owned_process_identity(
    *, pid: int, creation_time_100ns: int, executable_path: Path
) -> dict:
    return {
        "pid": pid,
        "executable_path": str(executable_path),
        "creation_time_100ns": creation_time_100ns,
        "ownership_caption": f"owned-{pid}",
        "ownership_hwnd": pid + 10_000,
        "activation_parent_pid": pid + 20_000,
        "activation_parent_executable_path": "C:/Windows/System32/svchost.exe",
        "activation_parent_creation_time_100ns": creation_time_100ns - 1,
        "ownership_origin_verified": True,
    }


class RunnerHardeningTests(unittest.TestCase):
    def test_new_winproj_identity_query_failure_is_retained_for_stop(self) -> None:
        runner = _runner()
        expected = Path("C:/Program Files/Microsoft Office/WINPROJ.EXE")
        queried = runner["_matching_new_project_processes"](
            [
                {
                    "pid": 321,
                    "creation_time_100ns": 9_999,
                    "executable_name": "WINPROJ.EXE",
                    "executable_path": None,
                }
            ],
            baseline_identities={(321, 9_999)},
            expected_path=expected,
        )

        self.assertEqual(1, len(queried))
        self.assertEqual(
            ["executable_path_unavailable"],
            queried[0]["identity_query_failures"],
        )

    def test_wrong_live_timezone_precedes_every_com_worker(self) -> None:
        runner = _runner()
        worker = Mock()
        with patch.object(
            runner["headless_com"],
            "_capture_windows_time_zone",
            return_value={
                "windows_name": "UTC",
                "utc_offset": "+00:00",
                "matches_required_perth_zone": False,
            },
        ), patch.dict(
            runner["_ensure_environment_and_preflight"].__globals__,
            {"run_supervised_worker": worker},
        ), self.assertRaisesRegex(
            runner["SupervisionError"], "required Australia/Perth"
        ):
            runner["_ensure_environment_and_preflight"](Mock())
        worker.assert_not_called()

    def test_calendar_worker_has_immediate_live_environment_gate(self) -> None:
        runner = _runner()
        observations = {
            case_id: {"case_id": case_id, "stop_conditions": []}
            for case_id in headless.CASE_IDS
        }
        environment = {"retained": "environment"}
        worker = Mock()
        live_gate = Mock(
            side_effect=runner["SupervisionError"]("live Perth gate failed")
        )
        with tempfile.TemporaryDirectory() as temporary:
            run = Mock(
                path=Path(temporary),
                repository_root=ROOT,
                run_id="run",
            )
            with patch.dict(
                runner["_complete_run"].__globals__,
                {
                    "_reject_run_stop_conditions": Mock(),
                    "verify_run_freeze_gate": Mock(return_value={}),
                    "_existing_calendar_result": Mock(return_value=None),
                    "_validate_environment_capture": live_gate,
                    "run_supervised_worker": worker,
                },
            ), self.assertRaisesRegex(
                runner["SupervisionError"], "live Perth gate failed"
            ):
                runner["_complete_run"](run, environment, observations)
        live_gate.assert_called_once_with(environment)
        worker.assert_not_called()

    def test_sparse_resume_prefix_is_rejected_before_any_worker(self) -> None:
        runner = _runner()
        worker = Mock()
        with tempfile.TemporaryDirectory() as temporary:
            run = headless.create_run_workspace(Path(temporary), "sparse-resume")
            (run.path / "cases" / "SEM-REL-001").mkdir(parents=True)
            (run.path / "cases" / "SEM-REL-003").mkdir(parents=True)
            with patch.dict(
                runner["_resume_existing_cases"].__globals__,
                {
                    "_validate_environment_capture": Mock(),
                    "run_supervised_worker": worker,
                },
            ), self.assertRaisesRegex(
                runner["SupervisionError"], "exact canonical prefix"
            ):
                runner["_resume_existing_cases"](run, {})
        worker.assert_not_called()

    def test_v02_cleanup_requires_revalidated_ownership_and_no_error(self) -> None:
        observation = {
            "schema_version": "headless-msproject-native-observation-v0.2",
            "stop_conditions": [],
            "process_sessions": [
                {
                    "pid": 42,
                    "exited": True,
                    "forced_termination": False,
                    "ownership_revalidated_before_quit": False,
                    "termination_error": "ownership changed",
                }
            ],
        }
        conditions = headless.effective_stop_conditions(observation)
        self.assertEqual(
            {
                "project_process_ownership_not_revalidated",
                "project_process_cleanup_error",
            },
            {item["condition"] for item in conditions},
        )

    def test_case_requires_exact_contained_native_artifacts(self) -> None:
        runner = _runner()
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            workspace = base / "workspace"
            workspace.mkdir()
            reported = _artifact_files(
                workspace, set(runner["CASE_NATIVE_ARTIFACT_ROLES"])
            )
            for filename in (
                "worker-native-result.json",
                "case-com-log.jsonl",
                "case-stage-state.json",
                "case-worker-stdout.log",
                "case-worker-stderr.log",
            ):
                (workspace / filename).write_text("retained\n", encoding="utf-8")
            artifacts = runner["_case_artifacts"](
                {"artifacts": reported}, workspace
            )
            self.assertEqual(
                set(runner["CASE_NATIVE_ARTIFACT_ROLES"])
                | set(runner["CASE_SUPPORT_ARTIFACT_ROLES"]),
                set(artifacts),
            )
            missing = dict(reported)
            missing.pop("reopened_xml")
            with self.assertRaisesRegex(
                runner["SupervisionError"], "exactly these artifact roles"
            ):
                runner["_case_artifacts"]({"artifacts": missing}, workspace)
            outside = base / "outside-native.xml"
            outside.write_bytes(b"outside")
            escaped = dict(reported)
            escaped["reopened_xml"] = str(outside)
            with self.assertRaisesRegex(
                runner["SupervisionError"], "escapes its workspace"
            ):
                runner["_case_artifacts"]({"artifacts": escaped}, workspace)

    def test_result_artifact_manifest_detects_native_artifact_mutation(self) -> None:
        runner = _runner()
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            result = workspace / "preflight.json"
            result.write_text("{}\n", encoding="utf-8")
            artifacts = {
                role: Path(path)
                for role, path in _artifact_files(
                    workspace, set(runner["CASE_NATIVE_ARTIFACT_ROLES"])
                ).items()
            }
            runner["_write_result_artifact_manifest"](
                result, workspace=workspace, artifacts=artifacts
            )
            runner["_verify_result_artifact_manifest"](
                result, workspace=workspace, artifacts=artifacts
            )
            alternate = workspace / "alternate-initial.xml"
            alternate.write_bytes(artifacts["initial_xml"].read_bytes())
            swapped = dict(artifacts)
            swapped["initial_xml"] = alternate
            with self.assertRaisesRegex(
                runner["SupervisionError"], "roles or paths"
            ):
                runner["_verify_result_artifact_manifest"](
                    result, workspace=workspace, artifacts=swapped
                )
            artifacts["initial_xml"].write_bytes(b"tampered")
            with self.assertRaisesRegex(
                runner["SupervisionError"], "artifact verification failed"
            ):
                runner["_verify_result_artifact_manifest"](
                    result, workspace=workspace, artifacts=artifacts
                )

    def test_cached_comparison_binds_status_and_native_coordinates(self) -> None:
        runner = _runner()
        comparison = _comparison()
        runner["_validate_comparison_result"](comparison, run_id="run")
        comparison["cases"][0]["fields"][0]["native"] = 99
        with self.assertRaisesRegex(
            runner["SupervisionError"], "normalized native value"
        ):
            runner["_validate_comparison_result"](comparison, run_id="run")

        comparison = _comparison()
        comparison["cases"][0]["fields"][0].update(
            {"reference": 99, "classification": "claim_field_mismatch"}
        )
        with self.assertRaisesRegex(
            runner["SupervisionError"], "status contradicts"
        ):
            runner["_validate_comparison_result"](comparison, run_id="run")

    def test_cached_comparison_rejects_numeric_type_aliases(self) -> None:
        runner = _runner()
        aliases = (
            ("native_false", 0, False, 0),
            ("reference_false", 0, 0, False),
            ("native_true", 1, True, 1),
            ("reference_true", 1, 1, True),
            ("native_float", 0, 0.0, 0),
            ("reference_float", 0, 0, 0.0),
        )
        for label, normalized, native, reference in aliases:
            with self.subTest(label=label):
                comparison = _comparison()
                comparison["cases"][0]["normalized_native"]["activities"]["A"][
                    "start"
                ] = normalized
                comparison["cases"][0]["fields"][0].update(
                    {"native": native, "reference": reference}
                )
                with self.assertRaisesRegex(
                    runner["SupervisionError"], "exact JSON integers"
                ):
                    runner["_validate_comparison_result"](
                        comparison, run_id="run"
                    )

    def test_cached_comparison_is_reexecuted_against_current_oracle(self) -> None:
        runner = _runner()
        cached = _comparison()

        def emit_current(*, result_path: Path, **_kwargs: object) -> dict:
            result_path.parent.mkdir(parents=True, exist_ok=True)
            digest = headless.durable_write_canonical_json(result_path, current)
            headless.durable_write_bytes(
                runner["_result_sidecar_path"](result_path),
                f"{digest}\n".encode("ascii"),
            )
            return current

        with tempfile.TemporaryDirectory() as temporary:
            run = Mock(
                path=Path(temporary),
                repository_root=ROOT,
                run_id="run",
            )
            current = json.loads(json.dumps(cached))
            with patch.dict(
                runner[
                    "_verify_cached_comparison_against_current_oracle"
                ].__globals__,
                {"run_comparison_worker": Mock(side_effect=emit_current)},
            ):
                runner["_verify_cached_comparison_against_current_oracle"](
                    run, cached
                )

            cached_alias = json.loads(json.dumps(cached))
            cached_alias["cases"][0]["fields"][0]["reference"] = False
            comparator = Mock(side_effect=emit_current)
            with patch.dict(
                runner[
                    "_verify_cached_comparison_against_current_oracle"
                ].__globals__,
                {"run_comparison_worker": comparator},
            ), self.assertRaisesRegex(
                runner["SupervisionError"], "exact JSON integers"
            ):
                runner["_verify_cached_comparison_against_current_oracle"](
                    run, cached_alias
                )
            comparator.assert_not_called()

            cached_alias = json.loads(json.dumps(cached))
            cached_alias["cases"][0]["cache_identity_probe"] = {"value": 0}
            current = json.loads(json.dumps(cached_alias))
            current["cases"][0]["cache_identity_probe"]["value"] = False
            with patch.dict(
                runner[
                    "_verify_cached_comparison_against_current_oracle"
                ].__globals__,
                {"run_comparison_worker": Mock(side_effect=emit_current)},
            ), self.assertRaisesRegex(
                runner["SupervisionError"], "current comparator or oracle"
            ):
                runner["_verify_cached_comparison_against_current_oracle"](
                    run, cached_alias
                )

            cached_alias = json.loads(json.dumps(cached))
            cached_alias["cases"][0]["cache_identity_probe"] = {"value": 0}
            current = json.loads(json.dumps(cached_alias))
            current["cases"][0]["cache_identity_probe"]["value"] = 0.0

            def emit_noncanonical_current(
                *, result_path: Path, **_kwargs: object
            ) -> dict:
                result_path.parent.mkdir(parents=True, exist_ok=True)
                result_path.write_text(
                    json.dumps(current, sort_keys=True) + "\n", encoding="utf-8"
                )
                headless.durable_write_bytes(
                    runner["_result_sidecar_path"](result_path),
                    f"{headless.sha256_file(result_path)}\n".encode("ascii"),
                )
                return current

            with patch.dict(
                runner[
                    "_verify_cached_comparison_against_current_oracle"
                ].__globals__,
                {
                    "run_comparison_worker": Mock(
                        side_effect=emit_noncanonical_current
                    )
                },
            ), self.assertRaisesRegex(
                runner["SupervisionError"], "outside canonical JSON"
            ):
                runner["_verify_cached_comparison_against_current_oracle"](
                    run, cached_alias
                )

            current = json.loads(json.dumps(cached))
            current["oracle_provenance"]["sealed_references"][0]["sha256"] = (
                "f" * 64
            )
            with patch.dict(
                runner[
                    "_verify_cached_comparison_against_current_oracle"
                ].__globals__,
                {"run_comparison_worker": Mock(side_effect=emit_current)},
            ), self.assertRaisesRegex(
                runner["SupervisionError"], "current comparator or oracle"
            ):
                runner["_verify_cached_comparison_against_current_oracle"](
                    run, cached
                )

            missing = json.loads(json.dumps(cached))
            del missing["oracle_provenance"]
            comparator = Mock()
            with patch.dict(
                runner[
                    "_verify_cached_comparison_against_current_oracle"
                ].__globals__,
                {"run_comparison_worker": comparator},
            ), self.assertRaisesRegex(
                runner["SupervisionError"], "lacks exact oracle-source"
            ):
                runner["_verify_cached_comparison_against_current_oracle"](
                    run, missing
                )
            comparator.assert_not_called()

    def test_cached_calendar_schedule_projection_must_remain_stable(self) -> None:
        runner = _runner()
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            artifacts = _artifact_files(
                workspace, set(runner["CALENDAR_ARTIFACT_ROLES"])
            )
            before = {
                "project": {
                    "start": "2026-01-05T08:00:00+08:00",
                    "finish": "2026-01-06T08:00:00+08:00",
                },
                "tasks": [
                    {
                        "name": "CAL-24X7-characterisation",
                        "start": "2026-01-05T08:00:00+08:00",
                        "finish": "2026-01-06T08:00:00+08:00",
                        "duration_minutes": 1_440,
                    }
                ],
            }
            changed = json.loads(json.dumps(before))
            changed["tasks"][0]["finish"] = "2026-01-06T09:00:00+08:00"
            xml_dates = {
                "project": {
                    "start": "2026-01-05T08:00:00",
                    "finish": "2026-01-06T08:00:00",
                },
                "tasks": [
                    {
                        "name": "CAL-24X7-characterisation",
                        "start": "2026-01-05T08:00:00",
                        "finish": "2026-01-06T08:00:00",
                        "duration": "PT24H0M0S",
                    }
                ],
            }
            calendar = {
                "schema_version": "headless-msproject-cal24x7-characterisation-v0.1",
                "characterisation_label": headless.TRACK_ID,
                "automatic_track_c_unblock": False,
                "calendar_representation_stable": True,
                "project_authored_xml": xml_dates,
                "reexported_xml": xml_dates,
                "calendar_representation_before": {"uid": "3"},
                "calendar_representation_after": {"uid": "3"},
                "process_sessions": [
                    {
                        "pid": 1,
                        "exited": True,
                        "forced_termination": False,
                        "ownership_revalidated_before_quit": True,
                        "termination_error": None,
                    }
                ],
                "task_dates_before_xml_reopen": before,
                "task_dates_after_xml_open": changed,
                "task_dates_after_xml_recalculate": changed,
                "artifacts": artifacts,
                "xml_reopen_method": "Application.OpenXML(exact_exported_utf8_text)",
                "xml_reopen_source_sha256": headless.sha256_file(
                    Path(artifacts["authored_xml"])
                ),
            }
            with patch.object(
                runner["headless"],
                "validated_cal24x7_calendar",
                return_value={"uid": "3"},
            ), patch.object(
                runner["headless"],
                "parse_project_xml_observation",
                return_value=xml_dates,
            ):
                stable = dict(calendar)
                stable["task_dates_after_xml_open"] = before
                stable["task_dates_after_xml_recalculate"] = before
                self.assertEqual(
                    set(runner["CALENDAR_ARTIFACT_ROLES"]),
                    set(
                        runner["_validate_calendar_result"](
                            stable, workspace=workspace
                        )
                    ),
                )
                with self.assertRaisesRegex(
                    runner["SupervisionError"], "task dates changed"
                ):
                    runner["_validate_calendar_result"](
                        calendar, workspace=workspace
                    )
                wrong_duration = json.loads(json.dumps(stable))
                wrong_duration["task_dates_before_xml_reopen"]["tasks"][0][
                    "duration_minutes"
                ] = 1_439
                with self.assertRaisesRegex(
                    runner["SupervisionError"], "task dates changed"
                ):
                    runner["_validate_calendar_result"](
                        wrong_duration, workspace=workspace
                    )
                malformed = dict(stable)
                malformed_capture = json.loads(json.dumps(before))
                malformed_capture["project"]["start"] = "not-a-timestamp"
                malformed["task_dates_before_xml_reopen"] = malformed_capture
                with self.assertRaisesRegex(
                    runner["SupervisionError"], "task dates changed"
                ):
                    runner["_validate_calendar_result"](
                        malformed, workspace=workspace
                    )

            shifted_xml = json.loads(json.dumps(xml_dates))
            shifted_xml["project"]["start"] = "2026-01-05T00:00:00"
            shifted_xml["project"]["finish"] = "2026-01-06T00:00:00"
            shifted_xml["tasks"][0]["start"] = "2026-01-05T00:00:00"
            shifted_xml["tasks"][0]["finish"] = "2026-01-06T00:00:00"
            shifted = dict(calendar)
            shifted["task_dates_after_xml_open"] = before
            shifted["task_dates_after_xml_recalculate"] = before
            shifted["project_authored_xml"] = shifted_xml
            shifted["reexported_xml"] = shifted_xml
            with patch.object(
                runner["headless"],
                "validated_cal24x7_calendar",
                return_value={"uid": "3"},
            ), patch.object(
                runner["headless"],
                "parse_project_xml_observation",
                return_value=shifted_xml,
            ), self.assertRaisesRegex(
                runner["SupervisionError"], "XML project start.*frozen origin"
            ):
                runner["_validate_calendar_result"](
                    shifted, workspace=workspace
                )

            wrong_xml_duration = json.loads(json.dumps(xml_dates))
            wrong_xml_duration["tasks"][0]["duration"] = "PT23H59M0S"
            duration_mismatch = dict(calendar)
            duration_mismatch["task_dates_after_xml_open"] = before
            duration_mismatch["task_dates_after_xml_recalculate"] = before
            duration_mismatch["project_authored_xml"] = wrong_xml_duration
            duration_mismatch["reexported_xml"] = wrong_xml_duration
            with patch.object(
                runner["headless"],
                "validated_cal24x7_calendar",
                return_value={"uid": "3"},
            ), patch.object(
                runner["headless"],
                "parse_project_xml_observation",
                return_value=wrong_xml_duration,
            ), self.assertRaisesRegex(
                runner["SupervisionError"], "exact XML/COM"
            ):
                runner["_validate_calendar_result"](
                    duration_mismatch, workspace=workspace
                )

    def test_sealed_snapshot_rejects_wrong_identity_and_schema_before_provenance(
        self,
    ) -> None:
        expected, _fixture, fixture_bytes, fixture_digest = (
            _synthetic_bound_oracle()
        )

        def wrong_fixture_case(candidate: dict) -> None:
            candidate["source_bindings"]["fixture"]["case_id"] = "SEM-REL-002"

        def swapped_fixture(candidate: dict) -> None:
            fixture = candidate["source_bindings"]["fixture"]
            fixture["case_id"] = "SEM-REL-002"
            fixture["path"] = "benchmarks/semantic/cases/sem-rel-002.json"
            fixture["relative_path"] = fixture["path"]
            fixture["raw_sha256"] = pilot.FIXTURE_RAW_SHA256_BY_CASE_ID[
                "SEM-REL-002"
            ]

        mutations = {
            "wrong_case": lambda candidate: candidate.update(
                {"case_id": "SEM-REL-002"}
            ),
            "wrong_schema": lambda candidate: candidate.update(
                {"schema_version": "alternate-v0.1"}
            ),
            "preregistration_binding": lambda candidate: candidate[
                "source_bindings"
            ]["preregistration"].update({"raw_sha256": "0" * 64}),
            "comparison_profile_binding": lambda candidate: candidate[
                "source_bindings"
            ]["comparison_profile"].update({"profile_id": "alternate-profile"}),
            "wrong_fixture_case": wrong_fixture_case,
            "swapped_fixture": swapped_fixture,
            "extra_source_binding_key": lambda candidate: candidate[
                "source_bindings"
            ]["fixture"].update({"extra": "unbound"}),
            "missing_source_binding_key": lambda candidate: candidate[
                "source_bindings"
            ]["fixture"].pop("relative_path"),
            "seal_control_type_alias": lambda candidate: candidate[
                "seal_control"
            ].update(
                {
                    "separate_from_operator_and_pre_execution_reviewer_material": 1
                }
            ),
            "coordinate_contract_type_alias": lambda candidate: candidate[
                "coordinate_contract"
            ].update({"timestamp_tolerance_seconds": False}),
            "claim_boundary_type_alias": lambda candidate: candidate[
                "claim_boundary"
            ].update({"pilot_case_count": 12.0}),
            "extra_claim_boundary_key": lambda candidate: candidate[
                "claim_boundary"
            ].update({"compatibility_claim_exists": False}),
            "alternate_projection_shape": lambda candidate: candidate.update(
                {
                    "expected_normalized": {
                        "reference_status": "reference_exact",
                        "activities": {
                            "A": {"start": 0, "finish": 4},
                            "B": {"start": 4, "finish": 7},
                        },
                        "project_finish": 7,
                    }
                }
            ),
            "projection_coordinate_type_alias": lambda candidate: candidate[
                "expected_normalized"
            ]["activity_times"]["A"].update({"start": False}),
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root.joinpath(
                *headless_compare.SEALED_DIRECTORY.parts,
                "SEM-REL-001.json",
            )
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps(expected, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            fixture_path = root / "benchmarks/semantic/cases/sem-rel-001.json"
            fixture_path.parent.mkdir(parents=True)
            fixture_path.write_bytes(fixture_bytes)
            known_digests = dict(pilot.FIXTURE_RAW_SHA256_BY_CASE_ID)
            known_digests["SEM-REL-001"] = fixture_digest
            with patch.object(
                headless_compare,
                "FIXTURE_RAW_SHA256_BY_CASE_ID",
                known_digests,
            ):
                loaded, identity = headless_compare._default_expected_snapshot(
                    root, "SEM-REL-001"
                )
            self.assertEqual(expected, loaded)
            self.assertEqual("SEM-REL-001", identity["case_id"])
            self.assertEqual(
                {
                    "case_id": "SEM-REL-001",
                    "relative_path": (
                        "benchmarks/semantic/cases/sem-rel-001.json"
                    ),
                    "sha256": fixture_digest,
                    "byte_size": len(fixture_bytes),
                    "source_kind": "bound_fixture_byte_snapshot",
                },
                identity["bound_fixture"],
            )

            for label, mutate in mutations.items():
                with self.subTest(label=label):
                    candidate = json.loads(json.dumps(expected))
                    mutate(candidate)
                    path.write_text(
                        json.dumps(candidate, sort_keys=True, separators=(",", ":"))
                        + "\n",
                        encoding="utf-8",
                    )
                    fixture_binding = Mock(
                        side_effect=AssertionError(
                            "invalid sealed identity reached fixture binding"
                        )
                    )
                    with patch.object(
                        headless_compare,
                        "_bound_fixture_identity",
                        fixture_binding,
                    ), patch.object(
                        headless_compare,
                        "FIXTURE_RAW_SHA256_BY_CASE_ID",
                        known_digests,
                    ), self.assertRaisesRegex(
                        headless.ObservationFreezeError, "schema or identity"
                    ):
                        headless_compare._default_expected_snapshot(
                            root, "SEM-REL-001"
                        )
                    fixture_binding.assert_not_called()

    def test_sealed_snapshot_is_bounded_before_json_parse(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sealed_path = root.joinpath(
                *headless_compare.SEALED_DIRECTORY.parts,
                "SEM-REL-001.json",
            )
            sealed_path.parent.mkdir(parents=True)
            sealed_path.write_bytes(
                b" " * (headless_compare.MAX_ORACLE_JSON_BYTES + 1)
            )
            with self.assertRaisesRegex(
                headless.ObservationFreezeError,
                "stable bounded regular-file snapshot",
            ):
                headless_compare._default_expected_snapshot(
                    root, "SEM-REL-001"
                )

    def test_sealed_snapshot_rejects_duplicate_json_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sealed_path = root.joinpath(
                *headless_compare.SEALED_DIRECTORY.parts,
                "SEM-REL-001.json",
            )
            sealed_path.parent.mkdir(parents=True)
            sealed_path.write_bytes(b'{"case_id":"one","case_id":"two"}\n')
            with self.assertRaisesRegex(
                headless.ObservationFreezeError,
                "strict UTF-8 JSON",
            ):
                headless_compare._default_expected_snapshot(
                    root, "SEM-REL-001"
                )

    def test_sealed_snapshot_classifies_path_replacement_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sealed_path = root.joinpath(
                *headless_compare.SEALED_DIRECTORY.parts,
                "SEM-REL-001.json",
            )
            stable_reader = Mock(
                side_effect=freeze.NativeEvidenceError(
                    "sealed path was replaced while it was read"
                )
            )
            with patch.object(
                headless_compare,
                "read_regular_file_snapshot",
                stable_reader,
            ), self.assertRaisesRegex(
                headless.ObservationFreezeError,
                "stable bounded regular-file snapshot",
            ):
                headless_compare._default_expected_snapshot(
                    root, "SEM-REL-001"
                )
            stable_reader.assert_called_once_with(
                sealed_path,
                label="sealed normalized expectation",
                max_bytes=headless_compare.MAX_ORACLE_JSON_BYTES,
            )

    def test_bound_fixture_projection_uses_one_exact_snapshot(self) -> None:
        sealed, _fixture, fixture_bytes, fixture_digest = (
            _synthetic_bound_oracle()
        )
        sealed["expected_normalized"]["activity_times"]["A"]["start"] = 1
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sealed_path = root.joinpath(
                *headless_compare.SEALED_DIRECTORY.parts,
                "SEM-REL-001.json",
            )
            sealed_path.parent.mkdir(parents=True)
            sealed_path.write_bytes(headless.canonical_bytes(sealed) + b"\n")
            fixture_path = root / "benchmarks/semantic/cases/sem-rel-001.json"
            fixture_path.parent.mkdir(parents=True)
            fixture_path.write_bytes(fixture_bytes)
            known_digests = dict(pilot.FIXTURE_RAW_SHA256_BY_CASE_ID)
            known_digests["SEM-REL-001"] = fixture_digest
            stable_reader = headless_compare.read_regular_file_snapshot
            with patch.object(
                headless_compare,
                "FIXTURE_RAW_SHA256_BY_CASE_ID",
                known_digests,
            ), patch.object(
                headless_compare,
                "read_regular_file_snapshot",
                wraps=stable_reader,
            ) as reader, self.assertRaisesRegex(
                headless.ObservationFreezeError, "differs from.*bound full fixture"
            ):
                headless_compare._default_expected_snapshot(
                    root, "SEM-REL-001"
                )
            self.assertEqual(2, reader.call_count)
            reader.assert_any_call(
                sealed_path,
                label="sealed normalized expectation",
                max_bytes=headless_compare.MAX_ORACLE_JSON_BYTES,
            )
            reader.assert_any_call(
                fixture_path,
                label="bound full fixture SEM-REL-001",
                max_bytes=headless_compare.MAX_ORACLE_JSON_BYTES,
            )

    def test_bound_fixture_rejects_digest_duplicate_keys_and_oversize(self) -> None:
        sealed, _fixture, fixture_bytes, fixture_digest = (
            _synthetic_bound_oracle()
        )
        duplicate_bytes = fixture_bytes.replace(
            b'{"case_id":',
            b'{"case_id":"SEM-REL-001","case_id":',
            1,
        )
        oversized_bytes = fixture_bytes + b" " * (
            headless_compare.MAX_ORACLE_JSON_BYTES - len(fixture_bytes) + 1
        )
        cases = {
            "wrong_digest": (fixture_bytes + b" ", fixture_digest, "digest"),
            "duplicate_key": (
                duplicate_bytes,
                hashlib.sha256(duplicate_bytes).hexdigest(),
                "strict canonical-domain JSON",
            ),
            "oversized": (
                oversized_bytes,
                hashlib.sha256(oversized_bytes).hexdigest(),
                "stable bounded regular-file snapshot",
            ),
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sealed_path = root.joinpath(
                *headless_compare.SEALED_DIRECTORY.parts,
                "SEM-REL-001.json",
            )
            sealed_path.parent.mkdir(parents=True)
            fixture_path = root / "benchmarks/semantic/cases/sem-rel-001.json"
            fixture_path.parent.mkdir(parents=True)
            for label, (data, digest, message) in cases.items():
                with self.subTest(label=label):
                    candidate = json.loads(json.dumps(sealed))
                    candidate["source_bindings"]["fixture"][
                        "raw_sha256"
                    ] = digest
                    sealed_path.write_bytes(
                        headless.canonical_bytes(candidate) + b"\n"
                    )
                    fixture_path.write_bytes(data)
                    known_digests = dict(pilot.FIXTURE_RAW_SHA256_BY_CASE_ID)
                    known_digests["SEM-REL-001"] = digest
                    with patch.object(
                        headless_compare,
                        "FIXTURE_RAW_SHA256_BY_CASE_ID",
                        known_digests,
                    ), self.assertRaisesRegex(
                        headless.ObservationFreezeError, message
                    ):
                        headless_compare._default_expected_snapshot(
                            root, "SEM-REL-001"
                        )

    def test_oracle_source_mutation_after_import_is_rejected(self) -> None:
        for source_role in headless_compare.ORACLE_SOURCE_SPECS:
            with (
                self.subTest(source_role=source_role),
                tempfile.TemporaryDirectory() as temporary,
            ):
                imported_bytes = f"synthetic imported {source_role} source\n".encode()
                imported_sha256 = hashlib.sha256(imported_bytes).hexdigest()
                root = Path(temporary)
                relative_path = headless_compare.ORACLE_SOURCE_SPECS[source_role][
                    "relative_path"
                ]
                source_path = root / relative_path
                source_path.parent.mkdir(parents=True)
                source_path.write_bytes(imported_bytes)
                with patch.dict(
                    headless_compare._IMPORTED_ORACLE_SOURCE_PATHS,
                    {source_role: source_path.resolve()},
                ), patch.dict(
                    headless_compare._IMPORTED_ORACLE_SOURCE_BYTES,
                    {source_role: imported_bytes},
                ), patch.dict(
                    headless_compare._IMPORTED_ORACLE_SOURCE_SHA256,
                    {source_role: imported_sha256},
                ):
                    identity = headless_compare._oracle_source_identity(
                        root,
                        source_role,
                        require_repository_source=True,
                    )
                    self.assertEqual(imported_sha256, identity["sha256"])

                    source_path.write_bytes(
                        f"synthetic mutated {source_role} source\n".encode()
                    )
                    with self.assertRaisesRegex(
                        headless.ObservationFreezeError,
                        "changed after.*import-time",
                    ):
                        headless_compare._oracle_source_identity(
                            root,
                            source_role,
                            require_repository_source=True,
                        )

    def test_parent_and_child_oracle_source_specs_match_exactly(self) -> None:
        runner = _runner()
        self.assertEqual(
            headless_compare.ORACLE_SOURCE_SPECS,
            runner["ORACLE_SOURCE_SPECS"],
        )
        self.assertEqual(
            {
                "comparator",
                "pilot",
                "headless",
                "freeze",
                "canonical_json",
                "msproject_package",
            },
            set(headless_compare.ORACLE_SOURCE_SPECS),
        )
        self.assertTrue(
            all(
                spec["relative_path"].endswith(".py")
                for spec in headless_compare.ORACLE_SOURCE_SPECS.values()
            )
        )

    def test_regular_file_snapshot_forces_binary_descriptor(self) -> None:
        payload = b"line-one\r\nline-two\r\n"
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "windows-crlf-source.py"
            path.write_bytes(payload)
            original_open = freeze.os.open
            observed_flags: list[int] = []

            def open_binary(target: Path, flags: int, *args: object) -> int:
                observed_flags.append(flags)
                return original_open(target, flags, *args)

            with patch.object(freeze.os, "open", side_effect=open_binary):
                snapshot = freeze.read_regular_file_snapshot(
                    path,
                    label="CRLF source",
                    max_bytes=1024,
                )
            self.assertEqual(payload, snapshot.data)
            self.assertEqual(len(payload), snapshot.byte_size)
            self.assertEqual(1, len(observed_flags))
            binary_flag = getattr(freeze.os, "O_BINARY", 0)
            if binary_flag:
                self.assertEqual(binary_flag, observed_flags[0] & binary_flag)

    def test_imported_sources_must_match_parent_prelaunch_bundle(self) -> None:
        imported = dict(headless_compare._IMPORTED_ORACLE_SOURCE_SHA256)
        expected_json = json.dumps(imported, sort_keys=True, separators=(",", ":"))
        headless_compare._require_parent_source_bundle(expected_json)
        imported["pilot"] = "b" * 64
        with self.assertRaisesRegex(
            headless.ObservationFreezeError, "parent prelaunch snapshots"
        ):
            headless_compare._require_parent_source_bundle(
                json.dumps(imported, sort_keys=True, separators=(",", ":"))
            )

    def test_worker_result_contradiction_fails_before_freeze(self) -> None:
        helpers = runpy.run_path(str(LEGACY_TEST))
        with tempfile.TemporaryDirectory() as temporary:
            run = headless.create_run_workspace(Path(temporary), "worker-mismatch")
            case = headless.create_case_workspace(run, "SEM-REL-001")
            observation = helpers["_observation"]("SEM-REL-001")
            shared = helpers["_provenance_for"](
                run, "SEM-REL-001", observation
            )
            artifacts = helpers["_freeze_artifacts"](
                case.path, observation, b"worker-mismatch"
            )
            contradictory = json.loads(json.dumps(observation))
            contradictory["stop_conditions"] = [{"condition": "stale-worker"}]
            artifacts["worker_result"].write_bytes(
                headless.canonical_bytes(contradictory) + b"\n"
            )
            with self.assertRaisesRegex(
                headless.ObservationFreezeError, "exact bytes disagree"
            ):
                headless.freeze_native_observation(
                    case,
                    observation,
                    artifacts,
                    shared_hashes=shared,
                )
            self.assertFalse((case.path / "native-observation.json").exists())

    def test_noncanonical_worker_result_resume_keeps_oracle_closed(self) -> None:
        helpers = runpy.run_path(str(LEGACY_TEST))
        calls: list[str] = []

        def reader(_root: Path, case_id: str) -> dict:
            calls.append(case_id)
            return {
                "activities": {
                    "A": {"start": 0, "finish": 4},
                    "B": {"start": 4, "finish": 7},
                },
                "project_finish": 7,
            }

        with tempfile.TemporaryDirectory() as temporary:
            run = headless.create_run_workspace(Path(temporary), "worker-resume")
            for case_id in headless.CASE_IDS:
                case = headless.create_case_workspace(run, case_id)
                observation = helpers["_observation"](case_id)
                shared = helpers["_provenance_for"](
                    run, case_id, observation
                )
                headless.freeze_native_observation(
                    case,
                    observation,
                    helpers["_freeze_artifacts"](
                        case.path, observation, case_id.encode("ascii")
                    ),
                    shared_hashes=shared,
                )

            last_case = run.path / "cases" / headless.CASE_IDS[-1]
            worker_path = last_case / "worker-native-result.json"
            worker_value = json.loads(worker_path.read_text(encoding="utf-8"))
            worker_path.write_text(
                json.dumps(worker_value, indent=2) + "\n", encoding="utf-8"
            )
            manifest_path = last_case / "case-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            worker_entry = next(
                item
                for item in manifest["artifacts"]
                if item["role"] == "worker_result"
            )
            worker_entry["byte_size"] = worker_path.stat().st_size
            worker_entry["sha256"] = headless.sha256_file(worker_path)
            manifest_path.write_text(
                json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            (last_case / "case-manifest.sha256").write_text(
                f"{headless.sha256_file(manifest_path)}\n", encoding="ascii"
            )

            with self.assertRaisesRegex(
                headless.ObservationFreezeError, "oracle gate remains closed"
            ):
                headless_compare.compare_frozen_observations(
                    run, expected_reader=reader
                )
        self.assertEqual([], calls)

    def test_post_gate_observation_mutation_keeps_oracle_closed(self) -> None:
        helpers = runpy.run_path(str(LEGACY_TEST))
        calls: list[str] = []

        def reader(_root: Path, case_id: str) -> dict:
            calls.append(case_id)
            return {
                "activities": {
                    "A": {"start": 0, "finish": 4},
                    "B": {"start": 4, "finish": 7},
                },
                "project_finish": 7,
            }

        with tempfile.TemporaryDirectory() as temporary:
            run = headless.create_run_workspace(Path(temporary), "toctou")
            for case_id in headless.CASE_IDS:
                case = headless.create_case_workspace(run, case_id)
                observation = helpers["_observation"](case_id)
                shared = helpers["_provenance_for"](
                    run, case_id, observation
                )
                headless.freeze_native_observation(
                    case,
                    observation,
                    helpers["_freeze_artifacts"](
                        case.path, observation, case_id.encode("ascii")
                    ),
                    shared_hashes=shared,
                )
            headless.verify_run_freeze_gate(run, write_index=True)

            original_gate = headless.verify_run_freeze_gate

            def mutate_after_gate(*args, **kwargs):
                index = original_gate(*args, **kwargs)
                path = (
                    run.path
                    / "cases"
                    / headless.CASE_IDS[0]
                    / "native-observation.json"
                )
                path.write_text("{}\n", encoding="utf-8")
                return index

            with patch.object(
                headless_compare,
                "verify_run_freeze_gate",
                side_effect=mutate_after_gate,
            ), self.assertRaisesRegex(
                headless.ObservationFreezeError, "changed after freeze verification"
            ):
                headless_compare.compare_frozen_observations(
                    run, expected_reader=reader
                )
        self.assertEqual([], calls)

    def test_v02_freeze_rejects_incomplete_native_artifact_roles(self) -> None:
        helpers = runpy.run_path(str(LEGACY_TEST))
        with tempfile.TemporaryDirectory() as temporary:
            run = headless.create_run_workspace(Path(temporary), "incomplete-artifacts")
            case = headless.create_case_workspace(run, headless.CASE_IDS[0])
            observation = helpers["_observation"](headless.CASE_IDS[0])
            shared = helpers["_provenance_for"](
                run, headless.CASE_IDS[0], observation
            )
            dummy = case.path / "dummy.mpp"
            dummy.write_bytes(b"incomplete")
            with self.assertRaisesRegex(
                headless.ObservationFreezeError, "exact MPP, XML"
            ):
                headless.freeze_native_observation(
                    case,
                    observation,
                    {"initial_mpp": dummy},
                    shared_hashes=shared,
                )


class TerminalizationRecoveryTests(unittest.TestCase):
    @staticmethod
    def _completion() -> dict:
        return {
            "schema_version": "headless-msproject-run-completion-v0.1",
            "characterisation_label": headless.TRACK_ID,
            "run_id": "run",
            "completed_at": "2026-08-31T12:00:00.000000+08:00",
            "comparison": _comparison(),
        }

    def test_raw_inventory_uses_one_snapshot_for_size_and_digest(self) -> None:
        runner = _runner()
        with tempfile.TemporaryDirectory() as temporary:
            run_path = Path(temporary) / "run"
            run_path.mkdir()
            artifact = run_path / "artifact.bin"
            original = b"one authenticated snapshot"
            replacement = b"later replacement with different bytes"
            artifact.write_bytes(original)
            stable_reader = runner["read_regular_file_snapshot"]

            def replace_after_snapshot(*args, **kwargs):
                snapshot = stable_reader(*args, **kwargs)
                artifact.write_bytes(replacement)
                return snapshot

            reader = Mock(side_effect=replace_after_snapshot)
            with patch.dict(
                runner["_raw_hash_inventory"].__globals__,
                {"read_regular_file_snapshot": reader},
            ):
                inventory = runner["_raw_hash_inventory"](run_path)

            self.assertEqual(
                [
                    {
                        "relative_path": "artifact.bin",
                        "byte_size": len(original),
                        "sha256": hashlib.sha256(original).hexdigest(),
                    }
                ],
                inventory,
            )
            self.assertEqual(replacement, artifact.read_bytes())
            reader.assert_called_once_with(
                artifact,
                label="raw inventory artifact artifact.bin",
                max_bytes=runner["MAX_RAW_INVENTORY_ARTIFACT_BYTES"],
            )

    def test_raw_inventory_rejects_artifact_mutation_or_replacement(self) -> None:
        runner = _runner()
        stable_reader = runner["read_regular_file_snapshot"]
        for mode in ("mutation", "replacement"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                run_path = Path(temporary) / "run"
                run_path.mkdir()
                artifact = run_path / "artifact.bin"
                artifact.write_bytes(b"evidence")

                def synthetic_stat(metadata, **changes):
                    fields = {
                        "st_mode": metadata.st_mode,
                        "st_dev": metadata.st_dev,
                        "st_ino": metadata.st_ino,
                        "st_size": metadata.st_size,
                        "st_mtime_ns": metadata.st_mtime_ns,
                    }
                    fields.update(changes)
                    return type("SyntheticArtifactStat", (), fields)()

                def race_snapshot(*args, **kwargs):
                    before = artifact.stat()
                    if mode == "mutation":
                        after = synthetic_stat(
                            before,
                            st_mtime_ns=before.st_mtime_ns + 1,
                        )
                        with patch.object(
                            freeze.os,
                            "fstat",
                            side_effect=(before, after),
                        ):
                            return stable_reader(*args, **kwargs)

                    replacement = synthetic_stat(
                        before,
                        st_ino=before.st_ino + 1,
                    )
                    real_stat = freeze.os.stat

                    def replaced_identity(candidate, *stat_args, **stat_kwargs):
                        if (
                            candidate == artifact
                            and stat_kwargs.get("follow_symlinks") is False
                        ):
                            return replacement
                        return real_stat(candidate, *stat_args, **stat_kwargs)

                    with patch.object(
                        freeze, "_require_regular_file"
                    ), patch.object(
                        freeze.os,
                        "stat",
                        side_effect=replaced_identity,
                    ):
                        return stable_reader(*args, **kwargs)

                reader = Mock(side_effect=race_snapshot)
                with patch.dict(
                    runner["_raw_hash_inventory"].__globals__,
                    {"read_regular_file_snapshot": reader},
                ), self.assertRaisesRegex(
                    runner["SupervisionError"],
                    "not a stable bounded snapshot",
                ):
                    runner["_raw_hash_inventory"](run_path)
                reader.assert_called_once_with(
                    artifact,
                    label="raw inventory artifact artifact.bin",
                    max_bytes=runner["MAX_RAW_INVENTORY_ARTIFACT_BYTES"],
                )

    def test_raw_inventory_rejects_oversize_before_hashing(self) -> None:
        runner = _runner()
        with tempfile.TemporaryDirectory() as temporary:
            run_path = Path(temporary) / "run"
            run_path.mkdir()
            artifact = run_path / "oversized.bin"
            artifact.write_bytes(b"12345")
            with patch.dict(
                runner["_raw_hash_inventory"].__globals__,
                {"MAX_RAW_INVENTORY_ARTIFACT_BYTES": 4},
            ), patch.object(
                freeze.hashlib, "sha256"
            ) as digester, self.assertRaisesRegex(
                runner["SupervisionError"],
                "not a stable bounded snapshot",
            ):
                runner["_raw_hash_inventory"](run_path)
            digester.assert_not_called()

    def test_terminal_snapshot_rejects_link_or_junction_before_reader(self) -> None:
        runner = _runner()
        component = Mock()
        component.is_symlink.return_value = False
        component.is_junction.return_value = True
        self.assertTrue(runner["_is_no_follow_link_component"](component))

        reader = Mock()
        link_check = Mock(return_value=True)
        with patch.dict(
            runner["_terminal_snapshot"].__globals__,
            {
                "_is_no_follow_link_component": link_check,
                "read_regular_file_snapshot": reader,
            },
        ), self.assertRaisesRegex(
            runner["SupervisionError"],
            "symbolic links or junctions",
        ):
            runner["_terminal_snapshot"](
                Path("C:/synthetic/run-completion.json"),
                label="run completion",
                max_bytes=runner["MAX_RUN_COMPLETION_BYTES"],
            )
        reader.assert_not_called()

    def test_raw_inventory_rejects_junction_directory_before_descent(self) -> None:
        runner = _runner()
        reader = Mock()
        with tempfile.TemporaryDirectory() as temporary:
            run_path = Path(temporary) / "run"
            run_path.mkdir()

            def is_link(component: Path) -> bool:
                return component.name == "junction"

            with patch.dict(
                runner["_raw_hash_inventory"].__globals__,
                {
                    "_is_no_follow_link_component": is_link,
                    "read_regular_file_snapshot": reader,
                },
            ), patch.object(
                runner["os"],
                "walk",
                return_value=iter([(str(run_path), ["junction"], [])]),
            ), self.assertRaisesRegex(
                runner["SupervisionError"],
                "symbolic links or junctions",
            ):
                runner["_raw_hash_inventory"](run_path)

        reader.assert_not_called()

    def test_raw_inventory_excludes_only_root_terminal_outputs(self) -> None:
        runner = _runner()
        with tempfile.TemporaryDirectory() as temporary:
            run_path = Path(temporary) / "run"
            nested = run_path / "cases" / "SEM-REL-001"
            nested.mkdir(parents=True)
            (run_path / "raw-artifact-hashes.json").write_bytes(b"root inventory")
            (run_path / "raw-artifact-hashes.sha256").write_bytes(b"root sidecar")
            (nested / "raw-artifact-hashes.json").write_bytes(b"nested inventory")
            (nested / "raw-artifact-hashes.sha256").write_bytes(b"nested sidecar")

            inventory = runner["_raw_hash_inventory"](run_path)

        self.assertEqual(
            {
                "cases/SEM-REL-001/raw-artifact-hashes.json",
                "cases/SEM-REL-001/raw-artifact-hashes.sha256",
            },
            {entry["relative_path"] for entry in inventory},
        )

    def test_terminalization_recovers_completion_only_and_missing_sidecar(
        self,
    ) -> None:
        runner = _runner()
        with tempfile.TemporaryDirectory() as temporary:
            run_path = Path(temporary) / "run"
            run_path.mkdir()
            run = Mock(path=run_path, run_id="run")
            completion = self._completion()
            completion_path = run_path / "run-completion.json"
            headless.durable_write_canonical_json(completion_path, completion)
            completion_bytes = completion_path.read_bytes()
            completion_mtime = completion_path.stat().st_mtime_ns

            first = runner["_terminalize_run_outputs"](run, completion)
            inventory_path = run_path / "raw-artifact-hashes.json"
            sidecar_path = run_path / "raw-artifact-hashes.sha256"
            inventory_bytes = inventory_path.read_bytes()
            inventory_mtime = inventory_path.stat().st_mtime_ns
            self.assertTrue(sidecar_path.is_file())

            sidecar_path.unlink()
            second = runner["_terminalize_run_outputs"](run, completion)
            sidecar_bytes = sidecar_path.read_bytes()
            sidecar_mtime = sidecar_path.stat().st_mtime_ns
            third = runner["_terminalize_run_outputs"](run, completion)

            self.assertEqual(first, second)
            self.assertEqual(second, third)
            self.assertEqual(completion_bytes, completion_path.read_bytes())
            self.assertEqual(completion_mtime, completion_path.stat().st_mtime_ns)
            self.assertEqual(inventory_bytes, inventory_path.read_bytes())
            self.assertEqual(inventory_mtime, inventory_path.stat().st_mtime_ns)
            self.assertEqual(sidecar_bytes, sidecar_path.read_bytes())
            self.assertEqual(sidecar_mtime, sidecar_path.stat().st_mtime_ns)
            self.assertEqual(
                f"{second['raw_hash_inventory_sha256']}\n",
                sidecar_path.read_text(encoding="ascii"),
            )

    def test_existing_terminal_bytes_must_match_without_overwrite(self) -> None:
        runner = _runner()
        with tempfile.TemporaryDirectory() as temporary:
            run_path = Path(temporary) / "run"
            run_path.mkdir()
            run = Mock(path=run_path, run_id="run")
            completion = self._completion()
            headless.durable_write_canonical_json(
                run_path / "run-completion.json", completion
            )
            inventory_path = run_path / "raw-artifact-hashes.json"
            retained = headless.canonical_bytes({"unexpected": True}) + b"\n"
            inventory_path.write_bytes(retained)

            with self.assertRaisesRegex(
                runner["SupervisionError"],
                "differs from the exact terminal bytes",
            ):
                runner["_terminalize_run_outputs"](run, completion)

            self.assertEqual(retained, inventory_path.read_bytes())
            self.assertFalse(
                (run_path / "raw-artifact-hashes.sha256").exists()
            )

    def test_retained_completion_reuses_exact_original_timestamp_and_bytes(
        self,
    ) -> None:
        runner = _runner()
        body = {"schema_version": "synthetic-terminal-body-v0.1", "value": 1}
        retained = {
            **body,
            "completed_at": "2026-08-31T12:00:00.000000+08:00",
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "run-completion.json"
            headless.durable_write_canonical_json(path, retained)
            original_bytes = path.read_bytes()
            original_mtime = path.stat().st_mtime_ns

            observed = runner["_completion_with_retained_timestamp"](
                path, body
            )
            self.assertEqual(retained, observed)
            self.assertEqual(original_bytes, path.read_bytes())
            self.assertEqual(original_mtime, path.stat().st_mtime_ns)

            with self.assertRaisesRegex(
                runner["SupervisionError"],
                "differs from exact frozen run evidence",
            ):
                runner["_completion_with_retained_timestamp"](
                    path,
                    {**body, "value": 2},
                )

            type_alias_path = Path(temporary) / "type-alias-completion.json"
            headless.durable_write_canonical_json(
                type_alias_path,
                {
                    **body,
                    "value": True,
                    "completed_at": "2026-08-31T12:00:00.000000+08:00",
                },
            )
            with self.assertRaisesRegex(
                runner["SupervisionError"],
                "differs from exact frozen run evidence",
            ):
                runner["_completion_with_retained_timestamp"](
                    type_alias_path,
                    body,
                )

    def test_recovery_binds_completion_to_retained_results_and_observations(
        self,
    ) -> None:
        runner = _runner()
        comparison = _comparison()
        calendar = {"synthetic": "retained-calendar"}
        observations = {
            case_id: {"case_id": case_id}
            for case_id in headless.CASE_IDS
        }
        reopen_results = [
            {"case_id": case_id} for case_id in headless.CASE_IDS
        ]
        with tempfile.TemporaryDirectory() as temporary:
            run_path = Path(temporary) / "run"
            run_path.mkdir()
            run = Mock(path=run_path, run_id="run")
            comparison_path = run_path / "comparison.json"
            calendar_path = (
                run_path
                / "calendar-characterisation"
                / "calendar-characterisation.json"
            )
            comparison_sha = headless.durable_write_canonical_json(
                comparison_path, comparison
            )
            headless.durable_write_bytes(
                runner["_result_sidecar_path"](comparison_path),
                f"{comparison_sha}\n".encode("ascii"),
            )
            calendar_sha = headless.durable_write_canonical_json(
                calendar_path, calendar
            )
            headless.durable_write_bytes(
                runner["_result_sidecar_path"](calendar_path),
                f"{calendar_sha}\n".encode("ascii"),
            )
            body = runner["_run_completion_body"](
                run,
                comparison_path=comparison_path,
                calendar_path=calendar_path,
                comparison=comparison,
                reopen_results=reopen_results,
                calendar=calendar,
            )
            completion = {
                **body,
                "completed_at": "2026-08-31T12:00:00.000000+08:00",
            }
            headless.durable_write_canonical_json(
                run_path / "run-completion.json", completion
            )
            calendar_validator = Mock(return_value={})
            manifest_validator = Mock()

            with patch.dict(
                runner["_recover_existing_run_completion"].__globals__,
                {
                    "_validate_calendar_result": calendar_validator,
                    "_verify_result_artifact_manifest": manifest_validator,
                    "_reopen_result": lambda observation: {
                        "case_id": observation["case_id"]
                    },
                },
            ):
                recovered = runner["_recover_existing_run_completion"](
                    run, observations
                )

        self.assertEqual(completion, recovered)
        calendar_validator.assert_called_once_with(
            calendar,
            workspace=calendar_path.parent,
        )
        manifest_validator.assert_called_once_with(
            calendar_path,
            workspace=calendar_path.parent,
            artifacts={},
        )

    def test_complete_run_recovers_terminal_outputs_before_new_workers(self) -> None:
        runner = _runner()
        observations = {
            case_id: {"case_id": case_id, "stop_conditions": []}
            for case_id in headless.CASE_IDS
        }
        completion = self._completion()
        result = {"run_id": "run", "recovered": True}
        freeze_gate = Mock()
        recover = Mock(return_value=completion)
        terminalize = Mock(return_value=result)
        calendar = Mock()
        worker = Mock()
        with tempfile.TemporaryDirectory() as temporary:
            run_path = Path(temporary) / "run"
            run_path.mkdir()
            (run_path / "run-completion.json").write_bytes(b"{}\n")
            run = Mock(path=run_path, run_id="run")
            with patch.dict(
                runner["_complete_run"].__globals__,
                {
                    "_reject_run_stop_conditions": Mock(),
                    "verify_run_freeze_gate": freeze_gate,
                    "_recover_existing_run_completion": recover,
                    "_terminalize_run_outputs": terminalize,
                    "_existing_calendar_result": calendar,
                    "run_supervised_worker": worker,
                    "run_comparison_worker": worker,
                },
            ):
                observed = runner["_complete_run"](run, {}, observations)

        self.assertEqual(result, observed)
        freeze_gate.assert_called_once_with(run, write_index=False)
        recover.assert_called_once_with(run, observations)
        terminalize.assert_called_once_with(run, completion)
        calendar.assert_not_called()
        worker.assert_not_called()

    def test_main_retained_completion_never_launches_missing_or_standalone_case(
        self,
    ) -> None:
        runner = _runner()
        environment = {"retained": "environment"}
        full_observations = {
            case_id: {"case_id": case_id, "stop_conditions": []}
            for case_id in headless.CASE_IDS
        }
        with tempfile.TemporaryDirectory() as temporary:
            run_path = Path(temporary) / "run"
            run_path.mkdir()
            (run_path / "run-completion.json").write_bytes(b"{}\n")
            run = Mock(path=run_path, run_id="run", repository_root=ROOT)

            for mode in ("missing", "complete", "standalone", "removed"):
                with self.subTest(mode=mode):
                    run_case = Mock()
                    native_worker = Mock()
                    comparison_worker = Mock()
                    complete_run = (
                        Mock(wraps=runner["_complete_run"])
                        if mode == "removed"
                        else Mock(return_value={"run_id": "run"})
                    )
                    ensure = Mock(return_value=(environment, {}))
                    retained = (
                        dict(list(full_observations.items())[:-1])
                        if mode == "missing"
                        else full_observations
                    )
                    if mode == "removed":
                        def remove_completion(*_args, **_kwargs):
                            (run_path / "run-completion.json").unlink()
                            return retained

                        resume = Mock(side_effect=remove_completion)
                    else:
                        resume = Mock(return_value=retained)
                    arguments = [
                        "--repository-root",
                        str(ROOT),
                        "--run-id",
                        "run",
                        "--resume",
                    ]
                    arguments.extend(
                        ["--case", "SEM-REL-001"]
                        if mode == "standalone"
                        else ["--all-relationship-cases"]
                    )
                    with patch.dict(
                        runner["main"].__globals__,
                        {
                            "create_run_workspace": Mock(return_value=run),
                            "_ensure_environment_and_preflight": ensure,
                            "_resume_existing_cases": resume,
                            "_run_one_case": run_case,
                            "_complete_run": complete_run,
                            "run_supervised_worker": native_worker,
                            "run_comparison_worker": comparison_worker,
                        },
                    ), patch("builtins.print") as printer:
                        return_code = runner["main"](arguments)

                    self.assertEqual(0 if mode == "complete" else 1, return_code)
                    run_case.assert_not_called()
                    native_worker.assert_not_called()
                    comparison_worker.assert_not_called()
                    if mode == "complete":
                        ensure.assert_called_once_with(run, resume_existing=True)
                        resume.assert_called_once_with(
                            run,
                            environment,
                            selected_case_id=None,
                        )
                        complete_run.assert_called_once_with(
                            run,
                            environment,
                            full_observations,
                            require_retained_completion=True,
                        )
                    elif mode == "removed":
                        complete_run.assert_called_once_with(
                            run,
                            environment,
                            full_observations,
                            require_retained_completion=True,
                        )
                        emitted = json.loads(printer.call_args.args[0])
                        self.assertIn(
                            "disappeared before terminalization recovery",
                            emitted["error"],
                        )
                    else:
                        complete_run.assert_not_called()
                    if mode == "standalone":
                        ensure.assert_not_called()
                        resume.assert_not_called()


class NativeSupervisorReviewRegressionTests(unittest.TestCase):
    def test_native_worker_uses_fresh_cache_and_one_authenticated_snapshot(self) -> None:
        runner = _runner()
        expected = Path("C:/Program Files/Microsoft Office/WINPROJ.EXE")

        class Process:
            pid = 7_301

            def __init__(self) -> None:
                self.poll_count = 0

            def poll(self) -> int | None:
                self.poll_count += 1
                return None if self.poll_count == 1 else 0

            def wait(self, timeout: int | None = None) -> int:
                return 0

        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "case"
            result_path = workspace / "result.json"
            pending = {
                "pid": 501,
                "creation_time_100ns": 9_001,
                "executable_name": "WINPROJ.EXE",
                "executable_path": str(expected),
            }
            commands: list[list[str]] = []
            result_digests: list[str] = []
            cache_token = "a" * 32

            def popen(command: list[str], **_kwargs: object) -> Process:
                commands.append(command)
                prefix = Path(command[command.index("-X") + 1].split("=", 1)[1])
                self.assertFalse(prefix.exists())
                digest, _events = _write_synthetic_native_worker_evidence(
                    command,
                    worker_pid=Process.pid,
                    result={"status": "authenticated"},
                    intermediate_events=[
                        ("project_creation", "complete", {"elapsed": 1}),
                        ("diagnostic", "error", {"retained": True}),
                    ],
                )
                result_digests.append(digest)
                return Process()

            late_hash = Mock(
                side_effect=AssertionError(
                    "authenticated native sidecar must not reread the result path"
                )
            )
            dependency_guard = Mock(
                wraps=runner["_imported_automation_source_hashes"]
            )
            with (
                patch.object(
                    runner["headless_com"],
                    "registered_project_executable",
                    return_value=expected,
                ),
                patch.object(
                    runner["headless_com"],
                    "list_winproj_processes",
                    side_effect=[[], [pending], []],
                ),
                patch.object(runner["subprocess"], "Popen", side_effect=popen),
                patch.object(runner["secrets"], "token_hex", return_value=cache_token),
                patch.object(runner["time"], "sleep"),
                patch.dict(
                    runner["run_supervised_worker"].__globals__,
                    {
                        "sha256_file": late_hash,
                        "_imported_automation_source_hashes": dependency_guard,
                    },
                ),
            ):
                result = runner["run_supervised_worker"](
                    operation="case",
                    repository_root=ROOT,
                    run_id="run",
                    workspace=workspace,
                    result_path=result_path,
                    case_id="SEM-REL-001",
                )

            self.assertEqual({"status": "authenticated"}, result)
            self.assertEqual(
                [
                    sys.executable,
                    "-B",
                    "-X",
                    f"pycache_prefix={workspace / f'case-import-pycache-{cache_token}'}",
                    "-m",
                ],
                commands[0][:5],
            )
            self.assertEqual(
                "deterministic_scheduling_core.native.msproject.headless_worker",
                commands[0][5],
            )
            self.assertFalse(
                (workspace / f"case-import-pycache-{cache_token}").exists()
            )
            self.assertEqual(
                f"{result_digests[0]}\n",
                runner["_result_sidecar_path"](result_path).read_text(
                    encoding="ascii"
                ),
            )
            late_hash.assert_not_called()
            self.assertEqual(
                [(ROOT,), (ROOT,)],
                [item.args for item in dependency_guard.call_args_list],
            )

    def test_native_worker_rejects_preexisting_random_cache_prefix(self) -> None:
        runner = _runner()
        cache_token = "b" * 32
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "case"
            (workspace / f"case-import-pycache-{cache_token}").mkdir(parents=True)
            popen = Mock()
            project_lookup = Mock()
            with (
                patch.object(
                    runner["secrets"], "token_hex", return_value=cache_token
                ),
                patch.object(
                    runner["headless_com"],
                    "registered_project_executable",
                    project_lookup,
                ),
                patch.object(runner["subprocess"], "Popen", popen),
                self.assertRaisesRegex(
                    runner["SupervisionError"],
                    "pycache prefix must be fresh and nonexistent",
                ),
            ):
                runner["run_supervised_worker"](
                    operation="case",
                    repository_root=ROOT,
                    run_id="run",
                    workspace=workspace,
                    result_path=workspace / "result.json",
                    case_id="SEM-REL-001",
                )
            project_lookup.assert_not_called()
            popen.assert_not_called()

    def test_redirected_nonexistent_cache_ignores_valid_stale_default_pyc(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "cache_probe.py"
            source.write_text('VALUE = "stale"\n', encoding="utf-8")
            source_metadata = source.stat()
            py_compile.compile(
                str(source),
                doraise=True,
                invalidation_mode=py_compile.PycInvalidationMode.TIMESTAMP,
            )
            source.write_text('VALUE = "fresh"\n', encoding="utf-8")
            os.utime(
                source,
                ns=(source_metadata.st_atime_ns, source_metadata.st_mtime_ns),
            )
            probe = "import cache_probe; print(cache_probe.VALUE)"
            stale = subprocess.run(
                [sys.executable, "-B", "-c", probe],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual("stale", stale.stdout.strip())

            fresh_prefix = root / "cryptographically-random-nonexistent-prefix"
            self.assertFalse(fresh_prefix.exists())
            fresh = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    "-X",
                    f"pycache_prefix={fresh_prefix}",
                    "-c",
                    probe,
                ],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual("fresh", fresh.stdout.strip())
            self.assertFalse(fresh_prefix.exists())

    def test_multiple_exact_path_identities_stop_same_poll_with_owned_only_cleanup(
        self,
    ) -> None:
        runner = _runner()
        expected = Path("C:/Program Files/Microsoft Office/WINPROJ.EXE")
        identities = [
            _owned_process_identity(
                pid=501, creation_time_100ns=9_001, executable_path=expected
            ),
            _owned_process_identity(
                pid=502, creation_time_100ns=9_002, executable_path=expected
            ),
        ]

        class RunningProcess:
            pid = 7_302

            def __init__(self) -> None:
                self.return_code: int | None = None

            def poll(self) -> int | None:
                return self.return_code

            def terminate(self) -> None:
                self.return_code = 0

            def kill(self) -> None:
                self.return_code = -9

            def wait(self, timeout: int | None = None) -> int:
                return 0 if self.return_code is None else self.return_code

        for verified_count in (0, 1, 2):
            with (
                self.subTest(verified_count=verified_count),
                tempfile.TemporaryDirectory() as temporary,
            ):
                workspace = Path(temporary) / "case"
                log_path = workspace / "case-com-log.jsonl"
                worker = RunningProcess()

                def popen(_command: list[str], **_kwargs: object) -> RunningProcess:
                    if verified_count:
                        log_path.write_bytes(
                            b"".join(
                                headless.canonical_bytes(
                                    {
                                        "phase": "process_identified",
                                        "details": identity,
                                    }
                                )
                                + b"\n"
                                for identity in identities[:verified_count]
                            )
                        )
                    return worker

                cleanup = Mock(return_value=True)
                sleeper = Mock()
                with (
                    patch.object(
                        runner["headless_com"],
                        "registered_project_executable",
                        return_value=expected,
                    ),
                    patch.object(
                        runner["headless_com"],
                        "list_winproj_processes",
                        side_effect=[[], identities, identities],
                    ) as process_listing,
                    patch.object(
                        runner["headless_com"], "windows_for_pid", return_value=[]
                    ),
                    patch.object(
                        runner["headless_com"],
                        "terminate_verified_project_process",
                        cleanup,
                    ),
                    patch.object(runner["subprocess"], "Popen", side_effect=popen),
                    patch.object(runner["time"], "sleep", sleeper),
                    self.assertRaisesRegex(
                        runner["SupervisionError"],
                        "multiple_project_process_identities",
                    ),
                ):
                    runner["run_supervised_worker"](
                        operation="case",
                        repository_root=ROOT,
                        run_id="run",
                        workspace=workspace,
                        result_path=workspace / "result.json",
                        case_id="SEM-REL-001",
                    )

                self.assertEqual(3, process_listing.call_count)
                sleeper.assert_not_called()
                stop = json.loads(
                    (workspace / "case-watchdog-stop.json").read_text(
                        encoding="utf-8"
                    )
                )
                self.assertEqual(
                    "multiple_project_process_identities", stop["condition"]
                )
                self.assertEqual(
                    [501, 502], [item["pid"] for item in stop["processes"]]
                )
                self.assertEqual(
                    [item["pid"] for item in identities[verified_count:]],
                    [
                        item["pid"]
                        for item in stop[
                            "unverified_exact_path_project_processes"
                        ]
                    ],
                )
                self.assertEqual(
                    [item["pid"] for item in identities[:verified_count]],
                    [call.args[0] for call in cleanup.call_args_list],
                )

    def test_native_result_rejects_raced_or_misidentified_terminal_evidence(
        self,
    ) -> None:
        runner = _runner()
        expected = Path("C:/Program Files/Microsoft Office/WINPROJ.EXE")
        cases = (
            ("result_replacement", "does not authenticate"),
            ("state_disagreement", "state disagrees"),
            ("pid_mismatch", "identity or schema"),
            ("sequence_gap", "identity or schema"),
            ("earlier_worker_terminal", "earlier conflicting"),
            ("wrong_start", "start event is malformed"),
            ("wrong_terminal_operation", "well-formed terminal"),
            ("noncanonical_log", "not exact canonical JSON"),
            ("noncanonical_result", "not exact canonical JSON"),
        )
        for mode, message in cases:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                workspace = Path(temporary) / "case"
                result_path = workspace / "result.json"
                worker_pid = 7_400
                mutation: list[object] = []

                class ExitedProcess:
                    pid = worker_pid

                    def poll(self) -> int:
                        return 0

                    def wait(self, timeout: int | None = None) -> int:
                        callback = mutation[0]
                        callback()
                        return 0

                def popen(command: list[str], **_kwargs: object) -> ExitedProcess:
                    _digest, events = _write_synthetic_native_worker_evidence(
                        command,
                        worker_pid=worker_pid,
                        result={"status": "child-result"},
                    )
                    state_path = Path(command[command.index("--state") + 1])
                    log_path = Path(command[command.index("--log") + 1])

                    def mutate() -> None:
                        changed = json.loads(json.dumps(events))
                        if mode == "result_replacement":
                            result_path.write_bytes(
                                headless.canonical_bytes(
                                    {"status": "post-exit-replacement"}
                                )
                                + b"\n"
                            )
                            return
                        if mode == "state_disagreement":
                            changed[-1]["details"]["result_sha256"] = "f" * 64
                            state_path.write_bytes(
                                headless.canonical_bytes(changed[-1]) + b"\n"
                            )
                            return
                        if mode == "pid_mismatch":
                            changed[-1]["worker_pid"] += 1
                        elif mode == "sequence_gap":
                            changed[-1]["sequence"] += 1
                        elif mode == "earlier_worker_terminal":
                            prior = _native_worker_event(
                                sequence=2,
                                worker_pid=worker_pid,
                                stage="worker",
                                phase="error",
                                details={"retained": True},
                            )
                            changed[-1]["sequence"] = 3
                            changed = [changed[0], prior, changed[-1]]
                        elif mode == "wrong_start":
                            changed[0]["details"]["case_id"] = "SEM-REL-002"
                        elif mode == "wrong_terminal_operation":
                            changed[-1]["details"]["operation"] = "preflight"
                        elif mode == "noncanonical_log":
                            log_path.write_bytes(
                                b"".join(
                                    json.dumps(event, sort_keys=True).encode("utf-8")
                                    + b"\n"
                                    for event in changed
                                )
                            )
                            return
                        elif mode == "noncanonical_result":
                            result_path.write_text(
                                json.dumps({"status": "child-result"}, indent=2)
                                + "\n",
                                encoding="utf-8",
                            )
                            return
                        log_path.write_bytes(
                            b"".join(
                                headless.canonical_bytes(event) + b"\n"
                                for event in changed
                            )
                        )
                        state_path.write_bytes(
                            headless.canonical_bytes(changed[-1]) + b"\n"
                        )

                    mutation.append(mutate)
                    return ExitedProcess()

                with (
                    patch.object(
                        runner["headless_com"],
                        "registered_project_executable",
                        return_value=expected,
                    ),
                    patch.object(
                        runner["headless_com"],
                        "list_winproj_processes",
                        side_effect=[[], []],
                    ),
                    patch.object(runner["subprocess"], "Popen", side_effect=popen),
                    self.assertRaisesRegex(runner["SupervisionError"], message),
                ):
                    runner["run_supervised_worker"](
                        operation="case",
                        repository_root=ROOT,
                        run_id="run",
                        workspace=workspace,
                        result_path=result_path,
                        case_id="SEM-REL-001",
                    )
                self.assertFalse(
                    runner["_result_sidecar_path"](result_path).exists()
                )

    def test_standalone_resume_verifies_its_selected_nonprefix_case(self) -> None:
        runner = _runner()
        helpers = runpy.run_path(str(LEGACY_TEST))
        case_id = "SEM-REL-005"
        with tempfile.TemporaryDirectory() as temporary:
            run = headless.create_run_workspace(Path(temporary), "standalone-resume")
            workspace = headless.create_case_workspace(run, case_id)
            observation = helpers["_observation"](case_id)
            shared = helpers["_provenance_for"](run, case_id, observation)
            artifacts = helpers["_freeze_artifacts"](
                workspace.path, observation
            )
            headless.freeze_native_observation(
                workspace,
                observation,
                artifacts,
                shared_hashes=shared,
            )
            environment = {"project_executable": {"sha256": "e" * 64}}
            automation = dict(observation["automation_source_hashes"])
            environment_gate = Mock()
            with patch.dict(
                runner["_resume_existing_cases"].__globals__,
                {
                    "_automation_hashes": Mock(return_value=automation),
                    "_validate_environment_capture": environment_gate,
                },
            ):
                resumed = runner["_resume_existing_cases"](
                    run,
                    environment,
                    selected_case_id=case_id,
                )

            self.assertEqual([case_id], list(resumed))
            self.assertEqual(case_id, resumed[case_id]["case_id"])
            environment_gate.assert_called_once_with(environment)

    def test_standalone_resume_rejects_unrelated_retained_case(self) -> None:
        runner = _runner()
        with tempfile.TemporaryDirectory() as temporary:
            run = headless.create_run_workspace(Path(temporary), "unrelated-resume")
            (run.path / "cases" / "SEM-REL-004").mkdir(parents=True)
            (run.path / "cases" / "SEM-REL-005").mkdir(parents=True)
            worker = Mock()
            with patch.dict(
                runner["_resume_existing_cases"].__globals__,
                {
                    "_validate_environment_capture": Mock(),
                    "run_supervised_worker": worker,
                },
            ), self.assertRaisesRegex(
                runner["SupervisionError"], "unrelated case workspaces"
            ):
                runner["_resume_existing_cases"](
                    run,
                    {},
                    selected_case_id="SEM-REL-005",
                )
            worker.assert_not_called()

    def test_case_resume_cli_scopes_retained_verification_to_selected_case(
        self,
    ) -> None:
        runner = _runner()
        run = Mock(
            run_id="standalone-cli",
            path=ROOT / "synthetic-run",
            repository_root=ROOT,
        )
        environment = {"retained": True}
        resume = Mock(return_value={})
        run_case = Mock(return_value={"case_id": "SEM-REL-007"})
        with patch.dict(
            runner["main"].__globals__,
            {
                "create_run_workspace": Mock(return_value=run),
                "_ensure_environment_and_preflight": Mock(
                    return_value=(environment, {})
                ),
                "_resume_existing_cases": resume,
                "_run_one_case": run_case,
            },
        ), patch("builtins.print"):
            return_code = runner["main"](
                [
                    "--case",
                    "SEM-REL-007",
                    "--repository-root",
                    str(ROOT),
                    "--run-id",
                    "standalone-cli",
                    "--resume",
                ]
            )

        self.assertEqual(0, return_code)
        resume.assert_called_once_with(
            run,
            environment,
            selected_case_id="SEM-REL-007",
        )
        run_case.assert_called_once_with(
            run,
            "SEM-REL-007",
            environment,
            resume_existing=True,
        )

    def test_project_start_must_equal_source_origin_by_wall_clock(self) -> None:
        helpers = runpy.run_path(str(LEGACY_TEST))
        facts = helpers["_source"]()["source_facts"]
        assignment = {"native_type_supplied": 1}
        expected_origin = facts["time_axis"]["origin"]

        for stage in (
            "initial_calculated",
            "after_open",
            "after_recalculation",
            "preflight",
        ):
            with self.subTest(stage=stage):
                capture = helpers["_capture"]()
                # This denotes the same UTC instant as the frozen +08:00
                # origin, but Project's local wall-clock start has changed.
                capture["project"]["start"] = "2026-01-05T00:00:00+00:00"
                conditions = headless_com._case_capture_stop_conditions(
                    capture,
                    facts,
                    assignment,
                    stage=stage,
                )
                starts = [
                    item
                    for item in conditions
                    if item.get("condition") == "native_project_start_changed"
                ]
                self.assertEqual(
                    [
                        {
                            "condition": "native_project_start_changed",
                            "stage": stage,
                            "expected": expected_origin,
                            "observed": "2026-01-05T00:00:00+00:00",
                        }
                    ],
                    starts,
                )

        capture = helpers["_capture"]()
        capture["project"]["start"] = "2026-01-05T08:00:00+00:00"
        conditions = headless_com._case_capture_stop_conditions(
            capture,
            facts,
            assignment,
            stage="offset-only-change",
        )
        self.assertNotIn(
            "native_project_start_changed",
            {item.get("condition") for item in conditions},
        )

    def test_worker_and_parent_bind_dependencies_without_worker_oracle_imports(
        self,
    ) -> None:
        runner = _runner()
        script = r"""
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0, sys.argv[1])
from deterministic_scheduling_core.native.msproject import headless_worker

hashes = headless_worker._automation_source_hashes(Path(sys.argv[2]))
original_reader = headless_worker._stable_source_snapshot
def changed_reader(path, *, label, max_bytes):
    data, digest = original_reader(path, label=label, max_bytes=max_bytes)
    if label == "current native-worker canonical_json source":
        data += b"synthetic-post-import-change"
        digest = hashlib.sha256(data).hexdigest()
    return data, digest
headless_worker._stable_source_snapshot = changed_reader
try:
    headless_worker._automation_source_hashes(Path(sys.argv[2]))
except ValueError as error:
    mutation_error = str(error)
else:
    mutation_error = None
forbidden = sorted(
    name
    for name in sys.modules
    if name in {
        "deterministic_scheduling_core.canonical.frozen_suite",
        "deterministic_scheduling_core.native.msproject.freeze",
        "deterministic_scheduling_core.native.msproject.headless_compare",
        "deterministic_scheduling_core.native.msproject.pilot",
    }
)
print(json.dumps({
    "hashes": hashes,
    "forbidden": forbidden,
    "canonical_json_loaded": (
        "deterministic_scheduling_core.provenance.canonical_json" in sys.modules
    ),
    "imported_canonical_json_sha256": (
        headless_worker._IMPORTED_CANONICAL_JSON_SHA256
    ),
    "mutation_error": mutation_error,
}, sort_keys=True))
"""
        completed = subprocess.run(
            [sys.executable, "-c", script, str(ROOT / "src"), str(ROOT)],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(completed.stdout)
        expected_roles = {
            "automation_tool_sha256",
            "headless_core_sha256",
            "headless_com_sha256",
            "headless_worker_sha256",
            "canonical_json_sha256",
            "freeze_sha256",
        }
        self.assertEqual(expected_roles, set(payload["hashes"]))
        self.assertEqual(runner["_automation_hashes"](ROOT), payload["hashes"])
        self.assertTrue(payload["canonical_json_loaded"])
        self.assertEqual(
            payload["hashes"]["canonical_json_sha256"],
            payload["imported_canonical_json_sha256"],
        )
        self.assertIn(
            "changed after the native worker imported it",
            payload["mutation_error"],
        )
        self.assertEqual([], payload["forbidden"])

    def test_native_worker_rechecks_imported_dependency_after_result_write(
        self,
    ) -> None:
        from deterministic_scheduling_core.native.msproject import (
            headless_worker,
        )

        stable_hashes = {"canonical_json_sha256": "1" * 64}
        changed_hashes = {"canonical_json_sha256": "2" * 64}
        hash_reader = Mock(
            side_effect=(stable_hashes, stable_hashes, changed_hashes)
        )
        journal = Mock()
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "case"
            result_path = workspace / "result.json"
            with patch.object(
                headless_worker,
                "_automation_source_hashes",
                hash_reader,
            ), patch.object(
                headless_worker,
                "load_source_only_projection_with_identity",
                return_value=({}, "a" * 64),
            ), patch.object(
                headless_worker,
                "run_native_case",
                return_value={
                    "schema_version": (
                        "headless-msproject-native-observation-v0.2"
                    )
                },
            ), patch.object(
                headless_worker, "StageJournal", return_value=journal
            ), patch("builtins.print"):
                return_code = headless_worker.main(
                    [
                        "--worker",
                        "case",
                        "--case",
                        "SEM-REL-001",
                        "--repository-root",
                        str(ROOT),
                        "--run-id",
                        "dependency-race",
                        "--workspace",
                        str(workspace),
                        "--result",
                        str(result_path),
                        "--state",
                        str(workspace / "state.json"),
                        "--log",
                        str(workspace / "log.jsonl"),
                    ]
                )

            self.assertEqual(1, return_code)
            self.assertEqual(3, hash_reader.call_count)
            self.assertTrue(result_path.is_file())
            phases = [call.args[1] for call in journal.call_args_list]
            self.assertEqual(["start", "error"], phases)
            self.assertIn(
                "changed while the native case result was serialized",
                journal.call_args_list[-1].args[2]["error"],
            )

    def test_parent_dependency_hashes_are_import_pinned_and_stably_revalidated(
        self,
    ) -> None:
        runner = _runner()
        reader = Mock(wraps=runner["read_regular_file_snapshot"])
        with patch.dict(
            runner["_automation_hashes"].__globals__,
            {"read_regular_file_snapshot": reader},
        ):
            hashes = runner["_automation_hashes"](ROOT)
        self.assertEqual(
            runner["_IMPORTED_AUTOMATION_SOURCE_SHA256"]["canonical_json"],
            hashes["canonical_json_sha256"],
        )
        self.assertEqual(
            runner["_IMPORTED_AUTOMATION_SOURCE_SHA256"]["freeze"],
            hashes["freeze_sha256"],
        )
        self.assertEqual(2, reader.call_count)
        self.assertTrue(
            all(
                call.kwargs["max_bytes"]
                == runner["MAX_IMPORTED_AUTOMATION_SOURCE_BYTES"]
                for call in reader.call_args_list
            )
        )

        original_reader = runner["read_regular_file_snapshot"]
        for source_role in ("canonical_json", "freeze"):
            with self.subTest(source_role=source_role):
                def changed_snapshot(
                    path: Path, *, label: str, max_bytes: int | None = None
                ) -> object:
                    snapshot = original_reader(
                        path, label=label, max_bytes=max_bytes
                    )
                    if label.endswith(source_role):
                        changed = snapshot.data + b"synthetic-post-import-change"
                        return runner["RegularFileSnapshot"](
                            data=changed,
                            sha256=hashlib.sha256(changed).hexdigest(),
                            byte_size=len(changed),
                            device=snapshot.device,
                            inode=snapshot.inode,
                            resolved_path=snapshot.resolved_path,
                        )
                    return snapshot

                with patch.dict(
                    runner["_automation_hashes"].__globals__,
                    {"read_regular_file_snapshot": changed_snapshot},
                ), self.assertRaisesRegex(
                    runner["SupervisionError"], "changed after its import-time"
                ):
                    runner["_automation_hashes"](ROOT)

        with tempfile.TemporaryDirectory() as temporary:
            replacement = Path(temporary) / "canonical_json.py"
            replacement.write_text("# different module path\n", encoding="utf-8")
            with patch.object(
                runner["canonical_json_module"], "__file__", str(replacement)
            ), self.assertRaisesRegex(
                runner["SupervisionError"], "not the captured checked-out source"
            ):
                runner["_automation_hashes"](ROOT)

    def test_supervision_rejects_alternate_checkout_before_launch(self) -> None:
        runner = _runner()
        with tempfile.TemporaryDirectory() as temporary:
            alternate_root = Path(temporary) / "alternate-checkout"
            canonical_copy = alternate_root.joinpath(
                *runner["_IMPORTED_AUTOMATION_SOURCE_RELATIVE_PATHS"][
                    "canonical_json"
                ].split("/")
            )
            canonical_copy.parent.mkdir(parents=True)
            canonical_copy.write_bytes(
                runner["_IMPORTED_AUTOMATION_SOURCE_BYTES"]["canonical_json"]
            )
            for entrypoint, keyword_arguments in (
                (
                    runner["run_supervised_worker"],
                    {
                        "operation": "case",
                        "repository_root": alternate_root,
                        "run_id": "run",
                        "workspace": alternate_root / "native-worker",
                        "result_path": alternate_root
                        / "native-worker"
                        / "result.json",
                        "case_id": "SEM-REL-001",
                    },
                ),
                (
                    runner["run_comparison_worker"],
                    {
                        "repository_root": alternate_root,
                        "run_id": "run",
                        "workspace": alternate_root / "comparison-worker",
                        "result_path": alternate_root
                        / "comparison-worker"
                        / "result.json",
                    },
                ),
            ):
                with self.subTest(entrypoint=entrypoint.__name__):
                    launcher = Mock()
                    with patch.object(
                        runner["subprocess"], "Popen", launcher
                    ), self.assertRaisesRegex(
                        runner["SupervisionError"],
                        "not the captured checked-out source",
                    ):
                        entrypoint(**keyword_arguments)
                    launcher.assert_not_called()

    def test_dependency_paths_reject_windows_junction_and_reparse_components(
        self,
    ) -> None:
        from deterministic_scheduling_core.native.msproject import (
            headless_worker,
        )

        runner = _runner()
        modern_junction = Mock()
        modern_junction.is_symlink.return_value = False
        modern_junction.is_junction.return_value = True
        self.assertTrue(
            runner["_dependency_path_component_is_link"](modern_junction)
        )
        self.assertTrue(
            headless_worker._source_path_component_is_link(modern_junction)
        )

        class LegacyWindowsJunction:
            @staticmethod
            def is_symlink() -> bool:
                return False

            @staticmethod
            def lstat() -> object:
                return type(
                    "SyntheticReparseStat",
                    (),
                    {"st_file_attributes": 0x400},
                )()

        with patch.object(runner["os"], "name", "nt"), patch.object(
            runner["stat"],
            "FILE_ATTRIBUTE_REPARSE_POINT",
            0x400,
            create=True,
        ):
            self.assertTrue(
                runner["_dependency_path_component_is_link"](
                    LegacyWindowsJunction()
                )
            )
        with patch.object(headless_worker.os, "name", "nt"), patch.object(
            headless_worker.stat,
            "FILE_ATTRIBUTE_REPARSE_POINT",
            0x400,
            create=True,
        ):
            self.assertTrue(
                headless_worker._source_path_component_is_link(
                    LegacyWindowsJunction()
                )
            )

        parent_link_check = Mock(
            side_effect=(
                None,
                None,
                OSError("synthetic retained post-read junction"),
            )
        )
        parent_reader = Mock(wraps=runner["read_regular_file_snapshot"])
        with patch.dict(
            runner["_imported_automation_source_hashes"].__globals__,
            {
                "_reject_dependency_link_components": parent_link_check,
                "read_regular_file_snapshot": parent_reader,
            },
        ), self.assertRaisesRegex(
            runner["SupervisionError"], "stable bounded snapshot"
        ):
            runner["_imported_automation_source_hashes"](ROOT)
        self.assertEqual(3, parent_link_check.call_count)
        self.assertEqual(1, parent_reader.call_count)

        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source.py"
            source.write_bytes(b"VALUE = 1\n")
            worker_link_check = Mock(
                side_effect=(
                    None,
                    ValueError("synthetic retained post-read junction"),
                )
            )
            with patch.object(
                headless_worker,
                "_reject_source_link_components",
                worker_link_check,
            ), self.assertRaisesRegex(
                ValueError, "post-read junction"
            ):
                headless_worker._stable_source_snapshot(
                    source,
                    label="synthetic source",
                    max_bytes=1024,
                )
            self.assertEqual(2, worker_link_check.call_count)

    def test_calendar_every_com_and_xml_start_must_equal_frozen_origin(
        self,
    ) -> None:
        runner = _runner()

        def com_capture(start: str, finish: str) -> dict:
            return {
                "project": {"start": start, "finish": finish},
                "tasks": [
                    {
                        "name": "CAL-24X7-characterisation",
                        "start": start,
                        "finish": finish,
                        "duration_minutes": 1_440,
                    }
                ],
            }

        def xml_capture(start: str, finish: str) -> dict:
            return {
                "project": {"start": start, "finish": finish},
                "tasks": [
                    {
                        "name": "CAL-24X7-characterisation",
                        "start": start,
                        "finish": finish,
                        "duration": "PT24H0M0S",
                    }
                ],
            }

        origin_com = com_capture(
            "2026-01-05T08:00:00+08:00",
            "2026-01-06T08:00:00+08:00",
        )
        shifted_com = com_capture(
            "2026-01-05T09:00:00+08:00",
            "2026-01-06T09:00:00+08:00",
        )
        origin_xml = xml_capture(
            "2026-01-05T08:00:00", "2026-01-06T08:00:00"
        )
        shifted_xml = xml_capture(
            "2026-01-05T09:00:00", "2026-01-06T09:00:00"
        )
        com_keys = (
            "task_dates_before_xml_reopen",
            "task_dates_after_xml_open",
            "task_dates_after_xml_recalculate",
        )
        xml_keys = ("project_authored_xml", "reexported_xml")

        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            artifacts = _artifact_files(
                workspace, set(runner["CALENDAR_ARTIFACT_ROLES"])
            )
            baseline = {
                "schema_version": (
                    "headless-msproject-cal24x7-characterisation-v0.1"
                ),
                "characterisation_label": headless.TRACK_ID,
                "automatic_track_c_unblock": False,
                "calendar_representation_stable": True,
                "project_authored_xml": origin_xml,
                "reexported_xml": origin_xml,
                "calendar_representation_before": {"uid": "3"},
                "calendar_representation_after": {"uid": "3"},
                "process_sessions": [
                    {
                        "pid": 1,
                        "exited": True,
                        "forced_termination": False,
                        "ownership_revalidated_before_quit": True,
                        "termination_error": None,
                    }
                ],
                **{key: origin_com for key in com_keys},
                "artifacts": artifacts,
                "xml_reopen_method": (
                    "Application.OpenXML(exact_exported_utf8_text)"
                ),
                "xml_reopen_source_sha256": headless.sha256_file(
                    Path(artifacts["authored_xml"])
                ),
            }

            def validate(candidate: dict) -> None:
                def parsed(path: Path) -> dict:
                    if path == Path(artifacts["authored_xml"]).resolve():
                        return candidate["project_authored_xml"]
                    return candidate["reexported_xml"]

                with patch.object(
                    runner["headless"],
                    "validated_cal24x7_calendar",
                    return_value={"uid": "3"},
                ), patch.object(
                    runner["headless"],
                    "parse_project_xml_observation",
                    side_effect=parsed,
                ):
                    runner["_validate_calendar_result"](
                        candidate, workspace=workspace
                    )

            validate(json.loads(json.dumps(baseline)))
            for capture_key in com_keys:
                candidate = json.loads(json.dumps(baseline))
                candidate[capture_key] = shifted_com
                with self.subTest(capture=capture_key), self.assertRaisesRegex(
                    runner["SupervisionError"], "COM project start.*frozen origin"
                ):
                    validate(candidate)

            for capture_key in xml_keys:
                candidate = json.loads(json.dumps(baseline))
                candidate[capture_key] = shifted_xml
                with self.subTest(capture=capture_key), self.assertRaisesRegex(
                    runner["SupervisionError"], "XML project start.*frozen origin"
                ):
                    validate(candidate)

            stable_shift = json.loads(json.dumps(baseline))
            for capture_key in com_keys:
                stable_shift[capture_key] = shifted_com
            for capture_key in xml_keys:
                stable_shift[capture_key] = shifted_xml
            with self.assertRaisesRegex(
                runner["SupervisionError"], "project start.*frozen origin"
            ):
                validate(stable_shift)

    def test_legacy_v01_gate_and_v02_provenance_roles_are_schema_scoped(
        self,
    ) -> None:
        helpers = runpy.run_path(str(LEGACY_TEST))
        with tempfile.TemporaryDirectory() as temporary:
            run = headless.create_run_workspace(Path(temporary), "legacy-v01-gate")
            for case_id in headless.CASE_IDS:
                workspace = headless.create_case_workspace(run, case_id)
                observation = helpers["_observation"](case_id)
                shared = helpers["_provenance_for"](
                    run, case_id, observation
                )
                headless.freeze_native_observation(
                    workspace,
                    observation,
                    helpers["_freeze_artifacts"](
                        workspace.path, observation, case_id.encode("ascii")
                    ),
                    shared_hashes=shared,
                )

                observation_path = workspace.path / "native-observation.json"
                legacy_observation = json.loads(
                    observation_path.read_text(encoding="utf-8")
                )
                legacy_observation["schema_version"] = (
                    "headless-msproject-native-observation-v0.1"
                )
                legacy_observation.pop("source_projection_sha256")
                legacy_observation.pop("automation_source_hashes")
                observation_path.write_bytes(
                    headless.canonical_bytes(legacy_observation) + b"\n"
                )

                manifest_path = workspace.path / "case-manifest.json"
                legacy_manifest = json.loads(
                    manifest_path.read_text(encoding="utf-8")
                )
                legacy_manifest["schema_version"] = (
                    "headless-msproject-artifact-manifest-v0.1"
                )
                legacy_manifest["shared_hashes"].pop("canonical_json_sha256")
                legacy_manifest["shared_hashes"].pop("freeze_sha256")
                observation_entry = next(
                    item
                    for item in legacy_manifest["artifacts"]
                    if item["role"] == "native_observation"
                )
                observation_entry["byte_size"] = observation_path.stat().st_size
                observation_entry["sha256"] = headless.sha256_file(
                    observation_path
                )
                manifest_path.write_bytes(
                    headless.canonical_bytes(legacy_manifest) + b"\n"
                )
                (workspace.path / "native-observation.sha256").write_text(
                    f"{headless.sha256_file(observation_path)}\n",
                    encoding="ascii",
                )
                (workspace.path / "case-manifest.sha256").write_text(
                    f"{headless.sha256_file(manifest_path)}\n",
                    encoding="ascii",
                )

            written = headless.verify_run_freeze_gate(run, write_index=True)
            audited = headless.verify_run_freeze_gate(
                run,
                write_index=False,
                allow_legacy_stop_evidence_for_audit=True,
            )
            self.assertEqual(written, audited)

        for manifest_version, observation_version in (
            (
                "headless-msproject-artifact-manifest-v0.2",
                "headless-msproject-native-observation-v0.1",
            ),
            (
                "headless-msproject-artifact-manifest-v0.1",
                "headless-msproject-native-observation-v0.2",
            ),
        ):
            with self.subTest(
                manifest_version=manifest_version,
                observation_version=observation_version,
            ):
                self.assertEqual(
                    headless._ALL_SHARED_HASH_ROLES,
                    headless._required_shared_hash_roles(
                        manifest_version, observation_version
                    ),
                )

        for missing_role in ("canonical_json_sha256", "freeze_sha256"):
            with (
                self.subTest(missing_role=missing_role),
                tempfile.TemporaryDirectory() as temporary,
            ):
                run = headless.create_run_workspace(
                    Path(temporary), f"missing-{missing_role}"
                )
                workspace = headless.create_case_workspace(
                    run, "SEM-REL-001"
                )
                observation = helpers["_observation"]("SEM-REL-001")
                shared = helpers["_provenance_for"](
                    run, "SEM-REL-001", observation
                )
                del shared[missing_role]
                with self.assertRaisesRegex(
                    headless.ObservationFreezeError,
                    "exact valid shared provenance hashes",
                ):
                    headless.freeze_native_observation(
                        workspace,
                        observation,
                        helpers["_freeze_artifacts"](
                            workspace.path, observation, b"v02"
                        ),
                        shared_hashes=shared,
                    )

    def test_native_result_snapshot_and_journal_are_bounded(self) -> None:
        runner = _runner()
        expected = Path("C:/Program Files/Microsoft Office/WINPROJ.EXE")

        class ExitedProcess:
            pid = 7_501

            def poll(self) -> int:
                return 0

            def wait(self, timeout: int | None = None) -> int:
                return 0

        for bounded_role in ("result", "journal"):
            with (
                self.subTest(bounded_role=bounded_role),
                tempfile.TemporaryDirectory() as temporary,
            ):
                workspace = Path(temporary) / "case"
                result_path = workspace / "result.json"

                def popen(command: list[str], **_kwargs: object) -> ExitedProcess:
                    _write_synthetic_native_worker_evidence(
                        command,
                        worker_pid=ExitedProcess.pid,
                        result={"payload": "x" * 64},
                    )
                    return ExitedProcess()

                limits = {
                    "MAX_NATIVE_RESULT_BYTES": (
                        8
                        if bounded_role == "result"
                        else runner["MAX_NATIVE_RESULT_BYTES"]
                    ),
                    "MAX_NATIVE_JOURNAL_BYTES": (
                        8
                        if bounded_role == "journal"
                        else runner["MAX_NATIVE_JOURNAL_BYTES"]
                    ),
                }
                with (
                    patch.object(
                        runner["headless_com"],
                        "registered_project_executable",
                        return_value=expected,
                    ),
                    patch.object(
                        runner["headless_com"],
                        "list_winproj_processes",
                        side_effect=[[], []],
                    ),
                    patch.object(runner["subprocess"], "Popen", side_effect=popen),
                    patch.dict(
                        runner["run_supervised_worker"].__globals__, limits
                    ),
                    self.assertRaisesRegex(
                        runner["SupervisionError"], "exceeds its byte limit"
                    ),
                ):
                    runner["run_supervised_worker"](
                        operation="case",
                        repository_root=ROOT,
                        run_id="run",
                        workspace=workspace,
                        result_path=result_path,
                        case_id="SEM-REL-001",
                    )
                self.assertFalse(
                    runner["_result_sidecar_path"](result_path).exists()
                )


if __name__ == "__main__":
    unittest.main()
