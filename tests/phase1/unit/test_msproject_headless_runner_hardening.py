from __future__ import annotations

import json
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import Mock, patch

from deterministic_scheduling_core.native.msproject import headless, headless_compare


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
            "comparator": {
                "module": "deterministic_scheduling_core.native.msproject.headless_compare",
                "relative_path": "src/deterministic_scheduling_core/native/msproject/headless_compare.py",
                "sha256": "a" * 64,
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
                }
                for index, case_id in enumerate(headless.CASE_IDS, start=1)
            ],
        },
        "cases": cases,
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

    def test_cached_comparison_is_reexecuted_against_current_oracle(self) -> None:
        runner = _runner()
        cached = _comparison()

        def emit_current(*, result_path: Path, **_kwargs: object) -> dict:
            result_path.parent.mkdir(parents=True, exist_ok=True)
            headless.durable_write_canonical_json(result_path, current)
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
                runner["SupervisionError"], "lacks exact comparator"
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
                runner["SupervisionError"], "exact XML/COM"
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


if __name__ == "__main__":
    unittest.main()
