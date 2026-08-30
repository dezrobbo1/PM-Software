from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from deterministic_scheduling_core.native.msproject import headless, headless_com
from deterministic_scheduling_core.native.msproject import headless_compare


ROOT = Path(__file__).resolve().parents[3]


def _source(case_id: str = "SEM-REL-001") -> dict:
    return headless.load_source_only_projection(ROOT, case_id)


def _capture(pid: int = 1) -> dict:
    return {
        "project": {
            "name": "Project1",
            "start": "2026-01-05T08:00:00+08:00",
            "finish": "2026-01-05T15:00:00+08:00",
            "schedule_from_start": True,
            "calendar": "24 Hours",
            "status_date": "NA",
            "resource_count": 0,
            "default_task_type": 1,
            "default_effort_driven": False,
            "new_tasks_created_as_manual": False,
            "calculation_mode": 0,
            "resource_leveling_automatic": False,
            "process_id": pid,
            "process_executable": "WINPROJ.EXE",
            "captured_at": "2026-08-30T12:00:00+08:00",
        },
        "tasks": [
            {
                "id": 1,
                "unique_id": 1,
                "name": "A",
                "start": "2026-01-05T08:00:00+08:00",
                "finish": "2026-01-05T12:00:00+08:00",
                "duration_minutes": 240,
                "manual": False,
                "type": 1,
                "effort_driven": False,
                "calendar": "24 Hours",
                "constraint_type": 0,
                "constraint_date": "NA",
                "actual_start": "NA",
                "actual_finish": "NA",
                "percent_complete": 0,
                "resource_names": "",
                "task_dependencies": [
                    {
                        "from_task_id": 1,
                        "from_task_unique_id": 1,
                        "to_task_id": 2,
                        "to_task_unique_id": 2,
                        "type": 1,
                        "type_name": "FS",
                        "lag_minutes": 0,
                        "lag_type": 5,
                    }
                ],
            },
            {
                "id": 2,
                "unique_id": 2,
                "name": "B",
                "start": "2026-01-05T12:00:00+08:00",
                "finish": "2026-01-05T15:00:00+08:00",
                "duration_minutes": 180,
                "manual": False,
                "type": 1,
                "effort_driven": False,
                "calendar": "24 Hours",
                "constraint_type": 0,
                "constraint_date": "NA",
                "actual_start": "NA",
                "actual_finish": "NA",
                "percent_complete": 0,
                "resource_names": "",
                "task_dependencies": [
                    {
                        "from_task_id": 1,
                        "from_task_unique_id": 1,
                        "to_task_id": 2,
                        "to_task_unique_id": 2,
                        "type": 1,
                        "type_name": "FS",
                        "lag_minutes": 0,
                        "lag_type": 5,
                    }
                ],
            },
        ],
    }


def _owned_process_identity(
    *,
    pid: int = 42,
    executable_path: str = "C:/Program Files/Microsoft Office/WINPROJ.EXE",
) -> dict:
    return {
        "pid": pid,
        "executable_path": executable_path,
        "creation_time_100ns": 2_000,
        "ownership_caption": "unique-caption",
        "ownership_hwnd": 5_678,
        "activation_parent_pid": 888,
        "activation_parent_executable_path": "C:/Windows/System32/svchost.exe",
        "activation_parent_creation_time_100ns": 1_000,
        "ownership_origin_verified": True,
    }


def _observation(case_id: str) -> dict:
    return {
        "schema_version": "headless-msproject-native-observation-v0.2",
        "characterisation_label": headless.TRACK_ID,
        "case_id": case_id,
        "initial_calculated": _capture(),
        "reopen_after_open": _capture(2),
        "reopen_after_recalculate": _capture(2),
        "stop_conditions": [],
    }


def _provenance_for(
    run: headless.RunWorkspace,
    case_id: str,
    observation: dict,
) -> dict[str, str]:
    source = headless.source_projection_path(run.repository_root, case_id)
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(headless.source_projection_path(ROOT, case_id).read_bytes())
    environment = run.path / "environment.json"
    if not environment.exists():
        environment.write_text(
            json.dumps({"project_executable": {"sha256": "e" * 64}}),
            encoding="utf-8",
        )
    automation = {
        "automation_tool_sha256": "a" * 64,
        "headless_core_sha256": "b" * 64,
        "headless_com_sha256": "c" * 64,
        "headless_worker_sha256": "d" * 64,
    }
    shared = {
        **automation,
        "environment_sha256": headless.sha256_file(environment),
        "project_executable_sha256": "e" * 64,
        "source_only_projection_sha256": headless.sha256_file(source),
    }
    observation["source_projection_sha256"] = shared[
        "source_only_projection_sha256"
    ]
    observation["automation_source_hashes"] = automation
    return shared


def _freeze_artifacts(
    case_path: Path,
    observation: dict,
    payload: bytes = b"artifact",
) -> dict[str, Path]:
    artifacts: dict[str, Path] = {}
    for role, filename in sorted(headless.CASE_ARTIFACT_FILENAMES.items()):
        path = case_path / filename
        path.write_bytes(payload + b":" + role.encode("ascii"))
        artifacts[role] = path
    observation["artifacts"] = {
        role: str(artifacts[role])
        for role in sorted(headless.CASE_NATIVE_ARTIFACT_ROLES)
    }
    return artifacts


def _valid_calendar() -> dict:
    return {
        "uid": "3",
        "name": "24 Hours",
        "is_base_calendar": "1",
        "base_calendar_uid": "0",
        "weekdays": [
            {
                "day_type": str(day),
                "day_working": "1",
                "working_times": [
                    {"from_time": "00:00:00", "to_time": "00:00:00"}
                ],
            }
            for day in range(1, 8)
        ],
    }


def _valid_xml_observation(capture: dict | None = None) -> dict:
    capture = capture or _capture()
    native = {task["name"]: task for task in capture["tasks"]}

    def xml_task(name: str) -> dict:
        task = native[name]
        return {
            "uid": str(task["unique_id"]),
            "id": str(task["id"]),
            "name": name,
            "start": task["start"][:19],
            "finish": task["finish"][:19],
            "duration": f"PT{task['duration_minutes'] // 60}H0M0S",
            "manual": "0",
            "type": "1",
            "effort_driven": "0",
            "calendar_uid": "3",
            "constraint_type": "0",
            "constraint_date": None,
            "actual_start": None,
            "actual_finish": None,
            "actual_duration": "PT0H0M0S",
            "actual_work": "PT0H0M0S",
            "percent_complete": "0",
            "predecessor_links": []
            if name == "A"
            else [
                {
                    "predecessor_uid": "1",
                    "type": "1",
                    "link_lag": "0",
                    "lag_format": "5",
                }
            ],
        }

    return {
        "namespace": "http://schemas.microsoft.com/project",
        "save_version": "14",
        "project": {
            "start": capture["project"]["start"][:19],
            "finish": capture["project"]["finish"][:19],
            "calendar_uid": "3",
            "status_date": None,
        },
        "calendars": [_valid_calendar()],
        "tasks": [
            {
                "uid": "0",
                "id": "0",
                "name": "summary",
                "predecessor_links": [],
            },
            xml_task("A"),
            xml_task("B"),
        ],
        "resources": [
            {
                "uid": "0",
                "id": "0",
                "name": None,
                "is_null": "0",
                "actual_work": "PT0H0M0S",
            }
        ],
        "assignments": [
            {
                "uid": str(index),
                "task_uid": str(index),
                "resource_uid": "-65535",
                "percent_work_complete": "0",
                "actual_start": None,
                "actual_finish": None,
                "actual_work": "PT0H0M0S",
            }
            for index in (1, 2)
        ],
    }


class SourceIsolationTests(unittest.TestCase):
    def test_exact_source_projection_is_used(self) -> None:
        projection = _source()
        self.assertTrue(projection["projection_contract"]["construction_inputs_only"])
        self.assertFalse(projection["projection_contract"]["oracle_content_included"])
        self.assertEqual("FS", projection["source_facts"]["relationship_inputs"][0]["type"])

    def test_full_fixture_and_sealed_paths_are_rejected_before_read(self) -> None:
        for path in (
            ROOT / "benchmarks/semantic/cases/sem-rel-001.json",
            ROOT
            / "native-validation/pilot-kits/microsoft-project-relationship-v0.1"
            / "sealed-expected-normalized/SEM-REL-001.json",
        ):
            with self.assertRaises(headless.SourceIsolationError):
                headless.load_source_only_projection(ROOT, "SEM-REL-001", path=path)

    def test_recursive_oracle_key_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = headless.source_projection_path(root, "SEM-REL-001")
            path.parent.mkdir(parents=True)
            payload = _source()
            payload["source_facts"]["nested"] = {"expected": {"A": 1}}
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(headless.SourceIsolationError):
                headless.load_source_only_projection(root, "SEM-REL-001")

    def test_native_worker_and_transitive_core_have_no_oracle_capability(self) -> None:
        from deterministic_scheduling_core.native.msproject import headless_worker

        worker_path = ROOT / "src/deterministic_scheduling_core/native/msproject/headless_worker.py"
        worker_source = worker_path.read_text(encoding="utf-8")
        core_source = Path(headless.__file__).read_text(encoding="utf-8")
        self.assertNotIn("headless_compare", worker_source)
        self.assertNotIn("compare_frozen_observations", worker_source)
        self.assertNotIn("SEALED_DIRECTORY", core_source)
        self.assertNotIn("read_expected_normalized", core_source)
        self.assertNotIn("compare_frozen_observations", core_source)
        arguments = [
            "--worker",
            "compare",
            "--repository-root",
            str(ROOT),
            "--run-id",
            "test",
            "--workspace",
            str(ROOT),
            "--result",
            str(ROOT / "result.json"),
            "--state",
            str(ROOT / "state.json"),
            "--log",
            str(ROOT / "log.jsonl"),
        ]
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            headless_worker._parser().parse_args(arguments)

    def test_exact_parsed_source_bytes_have_a_worker_bindable_digest(self) -> None:
        payload, digest = headless.load_source_only_projection_with_identity(
            ROOT, "SEM-REL-001"
        )
        self.assertEqual("SEM-REL-001", payload["case_id"])
        self.assertEqual(
            headless.sha256_file(
                headless.source_projection_path(ROOT, "SEM-REL-001")
            ),
            digest,
        )

    def test_native_import_graph_has_no_oracle_capability(self) -> None:
        self.assertFalse(hasattr(headless, "compare_frozen_observations"))
        self.assertFalse(hasattr(headless, "SEALED_DIRECTORY"))
        worker_source = (
            ROOT
            / "src/deterministic_scheduling_core/native/msproject/headless_worker.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("headless_compare", worker_source)
        self.assertNotIn("compare_frozen_observations", worker_source)
        self.assertTrue(hasattr(headless_compare, "compare_frozen_observations"))

    def test_fresh_native_worker_import_does_not_load_legacy_oracle_modules(self) -> None:
        script = """
import json
import runpy
import sys
sys.path.insert(0, sys.argv[1])
try:
    runpy.run_module(
        'deterministic_scheduling_core.native.msproject.headless_worker',
        run_name='__oracle_boundary_probe__',
    )
except SystemExit:
    pass
print(json.dumps(sorted(
    name for name in sys.modules
    if name in {
        'deterministic_scheduling_core.native.msproject.pilot',
        'deterministic_scheduling_core.native.msproject.normalizer',
    }
)))
"""
        completed = subprocess.run(
            [sys.executable, "-c", script, str(ROOT / "src")],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual("[]", completed.stdout.strip())


class EvidenceBoundaryTests(unittest.TestCase):
    def test_unique_run_and_case_workspaces_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run = headless.create_run_workspace(Path(temporary), "run-1")
            headless.create_case_workspace(run, "SEM-REL-001")
            with self.assertRaises(headless.DurableEvidenceError):
                headless.create_run_workspace(Path(temporary), "run-1")
            with self.assertRaises(headless.DurableEvidenceError):
                headless.create_case_workspace(run, "SEM-REL-001")

    def test_oracle_reader_cannot_run_before_all_observations_freeze(self) -> None:
        calls: list[str] = []

        def reader(_root: Path, case_id: str) -> dict:
            calls.append(case_id)
            return {
                "activities": {"A": {"start": 0, "finish": 4}, "B": {"start": 4, "finish": 7}},
                "project_finish": 7,
            }

        with tempfile.TemporaryDirectory() as temporary:
            run = headless.create_run_workspace(Path(temporary), "freeze-order")
            first = headless.create_case_workspace(run, "SEM-REL-001")
            observation = _observation("SEM-REL-001")
            shared = _provenance_for(run, "SEM-REL-001", observation)
            headless.freeze_native_observation(
                first,
                observation,
                _freeze_artifacts(first.path, observation, b"mpp"),
                shared_hashes=shared,
            )
            with self.assertRaises(headless.ObservationFreezeError):
                headless_compare.compare_frozen_observations(
                    run, expected_reader=reader
                )
            self.assertEqual([], calls)

    def test_all_hashes_verify_before_oracle_reader(self) -> None:
        calls: list[str] = []

        def reader(_root: Path, case_id: str) -> dict:
            calls.append(case_id)
            return {
                "activities": {"A": {"start": 0, "finish": 4}, "B": {"start": 4, "finish": 7}},
                "project_finish": 7,
            }

        with tempfile.TemporaryDirectory() as temporary:
            run = headless.create_run_workspace(Path(temporary), "complete-freeze")
            for case_id in headless.CASE_IDS:
                case = headless.create_case_workspace(run, case_id)
                observation = _observation(case_id)
                shared = _provenance_for(run, case_id, observation)
                headless.freeze_native_observation(
                    case,
                    observation,
                    _freeze_artifacts(case.path, observation, case_id.encode()),
                    shared_hashes=shared,
                )
            headless.verify_run_freeze_gate(run, write_index=True)
            result = headless_compare.compare_frozen_observations(
                run, expected_reader=reader
            )
            self.assertEqual(list(headless.CASE_IDS), calls)
            self.assertTrue(all(item["status"] == "characterisation_exact" for item in result["cases"]))

    def test_legacy_forced_session_keeps_oracle_closed_before_first_read(self) -> None:
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
            run = headless.create_run_workspace(Path(temporary), "legacy-forced-stop")
            for case_id in headless.CASE_IDS:
                case = headless.create_case_workspace(run, case_id)
                observation = _observation(case_id)
                if case_id == "SEM-REL-005":
                    observation["process_sessions"] = [
                        {
                            "pid": 27112,
                            "forced_termination": True,
                            "exited": True,
                        }
                    ]
                shared = _provenance_for(run, case_id, observation)
                headless.freeze_native_observation(
                    case,
                    observation,
                    _freeze_artifacts(case.path, observation, case_id.encode()),
                    shared_hashes=shared,
                )
            with self.assertRaisesRegex(
                headless.ObservationFreezeError, "audit override is read-only"
            ):
                headless.verify_run_freeze_gate(
                    run,
                    write_index=True,
                    allow_legacy_stop_evidence_for_audit=True,
                )
            with self.assertRaisesRegex(
                headless.ObservationFreezeError, "oracle gate remains closed"
            ):
                headless_compare.compare_frozen_observations(
                    run, expected_reader=reader
                )
        self.assertEqual([], calls)

    def test_late_malformed_observation_cannot_follow_any_oracle_read(self) -> None:
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
            run = headless.create_run_workspace(Path(temporary), "late-malformed")
            for case_id in headless.CASE_IDS:
                case = headless.create_case_workspace(run, case_id)
                observation = _observation(case_id)
                if case_id == headless.CASE_IDS[-1]:
                    observation["initial_calculated"]["tasks"][0][
                        "start"
                    ] = "2026-01-05T08:30:00+08:00"
                shared = _provenance_for(run, case_id, observation)
                headless.freeze_native_observation(
                    case,
                    observation,
                    _freeze_artifacts(case.path, observation, case_id.encode()),
                    shared_hashes=shared,
                )
            headless.verify_run_freeze_gate(run, write_index=True)
            with self.assertRaises(headless.OffGridTimestampError):
                headless_compare.compare_frozen_observations(
                    run, expected_reader=reader
                )
        self.assertEqual([], calls)

    def test_finalizer_rejects_tracked_output_under_raw_root(self) -> None:
        finalizer = runpy.run_path(
            str(ROOT / "tools" / "finalize_msproject_headless_characterisation.py")
        )
        candidate = (
            ROOT
            / "native-files"
            / "headless-msproject-characterisation"
            / "forbidden-summary.json"
        )
        with self.assertRaisesRegex(ValueError, "outside frozen RAW_ROOT"):
            finalizer["_tracked_output_path"](ROOT, candidate)
        with self.assertRaisesRegex(ValueError, "restricted to retained run"):
            finalizer["_require_retained_run_id"]("some-other-run")

    def test_summary_only_guards_raw_tree_bytes_and_hashes(self) -> None:
        finalizer = runpy.run_path(
            str(ROOT / "tools" / "finalize_msproject_headless_characterisation.py")
        )
        with tempfile.TemporaryDirectory() as temporary:
            repository_root = Path(temporary)
            raw_root = repository_root.joinpath(*headless.RAW_ROOT.parts)
            artifact = raw_root / "synthetic-run" / "observation.bin"
            artifact.parent.mkdir(parents=True)
            artifact.write_bytes(b"alpha")

            def mutate_raw_tree(_args: object, _root: Path) -> int:
                # Same byte count proves the guard checks content hashes, not
                # merely path presence and size.
                artifact.write_bytes(b"omega")
                return 0

            function_globals = finalizer["main"].__globals__
            with patch.dict(function_globals, {"_finalize": mutate_raw_tree}):
                with self.assertRaisesRegex(
                    finalizer["RawTreeImmutabilityError"],
                    "changed during --summary-only",
                ):
                    finalizer["main"](
                        [
                            "--repository-root",
                            str(repository_root),
                            "--run-id",
                            finalizer["RETAINED_RUN_ID"],
                            "--tracked-output",
                            "tracked-summary.json",
                            "--summary-only",
                        ]
                    )

    def test_cached_comparison_rejects_duplicate_cases_and_digest_tamper(self) -> None:
        runner = runpy.run_path(
            str(ROOT / "tools" / "run_msproject_headless_relationship_characterisation.py")
        )
        fields = [
            {
                "field": name,
                "native": 0,
                "reference": 0,
                "classification": "exact_match",
            }
            for name in (
                "activities.A.start",
                "activities.A.finish",
                "activities.B.start",
                "activities.B.finish",
                "project_finish",
            )
        ]
        cases = [
            {
                "case_id": case_id,
                "status": "characterisation_exact",
                "fields": fields,
                "normalized_native": {"case_id": case_id},
            }
            for case_id in headless.CASE_IDS
        ]
        cases[-1] = dict(cases[0])
        comparison = {
            "schema_version": "headless-msproject-comparison-v0.1",
            "characterisation_label": headless.TRACK_ID,
            "run_id": "run",
            "manual_native_semantic_parity_status_emitted": False,
            "cases": cases,
        }
        with self.assertRaisesRegex(
            runner["SupervisionError"], "unique cases in canonical order"
        ):
            runner["_validate_comparison_result"](comparison, run_id="run")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "comparison.json"
            path.write_text("{}\n", encoding="utf-8")
            runner["_result_sidecar_path"](path).write_text(
                f"{'0' * 64}\n", encoding="ascii"
            )
            with self.assertRaisesRegex(
                runner["SupervisionError"], "digest mismatch"
            ):
                runner["_verify_result_sidecar"](path)

    def test_cached_calendar_is_revalidated_from_both_xml_observations(self) -> None:
        runner = runpy.run_path(
            str(ROOT / "tools" / "run_msproject_headless_relationship_characterisation.py")
        )
        first = _valid_xml_observation()
        second = json.loads(json.dumps(first))
        representation = headless.validated_cal24x7_calendar(first)
        calendar_capture = {
            "project": {
                "start": "2026-01-05T08:00:00+08:00",
                "finish": "2026-01-06T08:00:00+08:00",
            },
            "tasks": [
                {
                    "name": "CAL-24X7-characterisation",
                    "start": "2026-01-05T08:00:00+08:00",
                    "finish": "2026-01-06T08:00:00+08:00",
                }
            ],
        }
        calendar = {
            "schema_version": "headless-msproject-cal24x7-characterisation-v0.1",
            "characterisation_label": headless.TRACK_ID,
            "automatic_track_c_unblock": False,
            "calendar_representation_stable": True,
            "project_authored_xml": first,
            "reexported_xml": second,
            "calendar_representation_before": representation,
            "calendar_representation_after": representation,
            "process_sessions": [
                {
                    "pid": 1,
                    "exited": True,
                    "forced_termination": False,
                    "ownership_revalidated_before_quit": True,
                    "termination_error": None,
                }
            ],
            "task_dates_before_xml_reopen": calendar_capture,
            "task_dates_after_xml_open": calendar_capture,
            "task_dates_after_xml_recalculate": calendar_capture,
            "artifacts": {},
        }
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            artifacts = {}
            for role, suffix in (
                ("authored_mpp", ".mpp"),
                ("authored_xml", ".xml"),
                ("reexported_xml", ".xml"),
            ):
                path = workspace / f"{role}{suffix}"
                path.write_bytes(role.encode("ascii"))
                artifacts[role] = str(path)
            calendar["artifacts"] = artifacts
            calendar["xml_reopen_method"] = (
                "Application.OpenXML(exact_exported_utf8_text)"
            )
            calendar["xml_reopen_source_sha256"] = headless.sha256_file(
                Path(artifacts["authored_xml"])
            )

            def parse(path: Path) -> dict:
                return second if path == Path(artifacts["reexported_xml"]) else first

            with patch.object(
                runner["headless"],
                "parse_project_xml_observation",
                side_effect=parse,
            ):
                validated = runner["_validate_calendar_result"](
                    calendar, workspace=workspace
                )
                self.assertEqual(set(artifacts), set(validated))

                second["calendars"][0]["weekdays"][0]["day_working"] = "0"
                with self.assertRaisesRegex(
                    runner["SupervisionError"], "XML observation is invalid"
                ):
                    runner["_validate_calendar_result"](
                        calendar, workspace=workspace
                    )

    def test_off_grid_timestamp_is_rejected_without_rounding(self) -> None:
        observation = _observation("SEM-REL-001")
        observation["initial_calculated"]["tasks"][0]["start"] = "2026-01-05T08:30:00+08:00"
        with self.assertRaises(headless.OffGridTimestampError):
            headless.normalize_observation(observation)

    def test_duplicate_or_extra_native_tasks_are_rejected(self) -> None:
        for extra in (
            dict(_capture()["tasks"][0]),
            {**_capture()["tasks"][0], "name": "C"},
        ):
            observation = _observation("SEM-REL-001")
            observation["initial_calculated"]["tasks"].append(extra)
            with self.assertRaises(headless.ObservationFreezeError):
                headless.normalize_observation(observation)

    def test_worker_source_and_automation_identity_are_required_at_freeze(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run = headless.create_run_workspace(Path(temporary), "identity-required")
            case = headless.create_case_workspace(run, "SEM-REL-001")
            observation = _observation("SEM-REL-001")
            shared = _provenance_for(run, "SEM-REL-001", observation)
            del observation["source_projection_sha256"]
            with self.assertRaisesRegex(
                headless.ObservationFreezeError, "worker source digest"
            ):
                headless.freeze_native_observation(
                    case,
                    observation,
                    _freeze_artifacts(case.path, observation, b"mpp"),
                    shared_hashes=shared,
                )

    def test_freeze_status_requires_durable_readback_verification(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run = headless.create_run_workspace(Path(temporary), "readback-required")
            case = headless.create_case_workspace(run, "SEM-REL-001")
            observation = _observation("SEM-REL-001")
            shared = _provenance_for(run, "SEM-REL-001", observation)
            with (
                patch.object(
                    headless,
                    "verify_observation_freeze",
                    side_effect=headless.ObservationFreezeError("readback changed"),
                ),
                self.assertRaisesRegex(
                    headless.ObservationFreezeError, "readback changed"
                ),
            ):
                headless.freeze_native_observation(
                    case,
                    observation,
                    _freeze_artifacts(case.path, observation, b"mpp"),
                    shared_hashes=shared,
                )

    def test_cross_case_shared_provenance_must_be_identical(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run = headless.create_run_workspace(Path(temporary), "cross-case-hash")
            for case_id in headless.CASE_IDS:
                case = headless.create_case_workspace(run, case_id)
                observation = _observation(case_id)
                shared = _provenance_for(run, case_id, observation)
                if case_id == headless.CASE_IDS[-1]:
                    shared["automation_tool_sha256"] = "f" * 64
                    observation["automation_source_hashes"][
                        "automation_tool_sha256"
                    ] = "f" * 64
                headless.freeze_native_observation(
                    case,
                    observation,
                    _freeze_artifacts(case.path, observation, case_id.encode()),
                    shared_hashes=shared,
                )
            with self.assertRaisesRegex(
                headless.ObservationFreezeError, "shared provenance differs"
            ):
                headless.verify_run_freeze_gate(run, write_index=True)

    def test_summary_never_emits_manual_track_pass_or_unblocks_track_c(self) -> None:
        summary = headless.build_tracked_summary(
            run_id="run",
            environment={},
            comparison={"cases": []},
            reopen_results=[],
            calendar_characterisation={"automatic_track_c_unblock": False},
            raw_hashes=[],
            procedural_blinding={"status": "breached_preexecution_search"},
        )
        encoded = json.dumps(summary)
        self.assertNotIn("executed_pass", encoded)
        self.assertFalse(summary["actual_microsoft_project_engine_ran"])
        self.assertFalse(summary["claim_boundary"]["manual_native_semantic_parity_track_executed"])
        self.assertTrue(summary["claim_boundary"]["track_c_preparation_blocked_unchanged"])

        evidenced = headless.build_tracked_summary(
            run_id="run",
            environment={
                "microsoft_project": {
                    "com_prog_id": "MSProject.Application",
                    "version": "16.0",
                },
                "project_executable": {"sha256": "a" * 64},
            },
            comparison={
                "cases": [{"case_id": case_id} for case_id in headless.CASE_IDS]
            },
            reopen_results=[],
            calendar_characterisation={"automatic_track_c_unblock": False},
            raw_hashes=[],
            procedural_blinding={"status": "breached_preexecution_search"},
            native_execution_evidence={
                "process_ids_by_case": {
                    case_id: [index]
                    for index, case_id in enumerate(headless.CASE_IDS, start=1)
                }
            },
        )
        self.assertTrue(evidenced["actual_microsoft_project_engine_ran"])


class XmlCharacterisationTests(unittest.TestCase):
    def test_actual_namespace_saveversion_relationship_and_midnight_are_retained(self) -> None:
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<Project xmlns="urn:test-project"><SaveVersion>99</SaveVersion><StartDate>2026-01-05T08:00:00</StartDate>
<FinishDate>2026-01-05T15:00:00</FinishDate><CalendarUID>3</CalendarUID><Calendars><Calendar><UID>3</UID>
<Name>24 Hours</Name><IsBaseCalendar>1</IsBaseCalendar><BaseCalendarUID>-1</BaseCalendarUID><WeekDays><WeekDay>
<DayType>1</DayType><DayWorking>1</DayWorking><WorkingTimes><WorkingTime><FromTime>00:00:00</FromTime>
<ToTime>00:00:00</ToTime></WorkingTime></WorkingTimes></WeekDay></WeekDays></Calendar></Calendars><Tasks><Task>
<UID>2</UID><ID>2</ID><Name>B</Name><Start>2026-01-05T12:00:00</Start><Finish>2026-01-05T15:00:00</Finish>
<PredecessorLink><PredecessorUID>1</PredecessorUID><Type>1</Type><LinkLag>1200</LinkLag><LagFormat>5</LagFormat>
</PredecessorLink></Task></Tasks></Project>"""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "project.xml"
            path.write_text(xml, encoding="utf-8")
            observed = headless.parse_project_xml_observation(path)
        self.assertEqual("urn:test-project", observed["namespace"])
        self.assertEqual("99", observed["save_version"])
        self.assertEqual("1200", observed["tasks"][0]["predecessor_links"][0]["link_lag"])
        working = observed["calendars"][0]["weekdays"][0]["working_times"][0]
        self.assertEqual({"from_time": "00:00:00", "to_time": "00:00:00"}, working)

    def test_cal24x7_requires_one_complete_selected_base_calendar(self) -> None:
        valid = _valid_xml_observation()
        self.assertEqual(
            "3", headless.validated_cal24x7_calendar(valid)["uid"]
        )
        invalid_variants = []
        missing = json.loads(json.dumps(valid))
        missing["calendars"] = []
        invalid_variants.append(missing)
        duplicate = json.loads(json.dumps(valid))
        duplicate["calendars"].append(json.loads(json.dumps(_valid_calendar())))
        invalid_variants.append(duplicate)
        incomplete = json.loads(json.dumps(valid))
        incomplete["calendars"][0]["weekdays"].pop()
        invalid_variants.append(incomplete)
        duplicate_day = json.loads(json.dumps(valid))
        duplicate_day["calendars"][0]["weekdays"][6]["day_type"] = "6"
        invalid_variants.append(duplicate_day)
        for candidate in invalid_variants:
            with self.assertRaises(headless.XmlObservationError):
                headless.validated_cal24x7_calendar(candidate)

    def test_xml_validation_rejects_com_wall_clock_shift_and_reopened_mutation(self) -> None:
        capture = _capture()
        xml = _valid_xml_observation(capture)
        assignment = {
            "native_type_supplied": 1,
        }
        self.assertEqual(
            [],
            headless_com._xml_case_stop_conditions(
                xml,
                capture,
                _source()["source_facts"],
                assignment,
                stage="initial_xml",
            ),
        )
        shifted = json.loads(json.dumps(xml))
        shifted["tasks"][1]["start"] = "2026-01-05T00:00:00"
        conditions = headless_com._xml_case_stop_conditions(
            shifted,
            capture,
            _source()["source_facts"],
            assignment,
            stage="reopened_xml",
        )
        self.assertTrue(
            any(
                item["condition"] == "xml_com_wall_clock_mismatch"
                for item in conditions
            )
        )

    def test_xml_validation_rejects_missing_or_malformed_required_timestamps(self) -> None:
        assignment = {"native_type_supplied": 1}
        variants = []

        missing_capture = _capture()
        missing_xml = _valid_xml_observation(missing_capture)
        missing_capture["project"]["start"] = None
        missing_xml["project"]["start"] = None
        variants.append((missing_capture, missing_xml, "project.start"))

        malformed_capture = _capture()
        malformed_xml = _valid_xml_observation(malformed_capture)
        malformed_capture["tasks"][0]["finish"] = "not-a-timestamp"
        malformed_xml["tasks"][1]["finish"] = "not-a-timestamp"
        variants.append((malformed_capture, malformed_xml, "tasks.A.finish"))

        missing_xml_only_capture = _capture()
        missing_xml_only = _valid_xml_observation(missing_xml_only_capture)
        missing_xml_only["tasks"][2].pop("start")
        variants.append(
            (missing_xml_only_capture, missing_xml_only, "tasks.B.start")
        )

        for capture, xml, field in variants:
            with self.subTest(field=field):
                conditions = headless_com._xml_case_stop_conditions(
                    xml,
                    capture,
                    _source()["source_facts"],
                    assignment,
                    stage="reopened_xml",
                )
                self.assertTrue(
                    any(
                        item["condition"] == "required_schedule_timestamp_invalid"
                        and item["field"] == field
                        for item in conditions
                    ),
                    conditions,
                )

    def test_xml_validation_rejects_resources_progress_and_relationship_changes(self) -> None:
        capture = _capture()
        xml = _valid_xml_observation(capture)
        xml["tasks"][2]["percent_complete"] = "10"
        xml["tasks"][2]["predecessor_links"][0]["type"] = "3"
        xml["resources"].append(
            {"uid": "1", "id": "1", "name": "Unexpected"}
        )
        conditions = headless_com._xml_case_stop_conditions(
            xml,
            capture,
            _source()["source_facts"],
            {"native_type_supplied": 1},
            stage="reopened_xml",
        )
        observed = {item["condition"] for item in conditions}
        self.assertIn("unexpected_xml_resources", observed)
        self.assertIn("xml_task_properties_changed", observed)
        self.assertIn("xml_relationship_or_lag_transformed", observed)


class ParentOwnershipEvidenceTests(unittest.TestCase):
    def test_append_only_log_is_only_pid_and_caption_authority(self) -> None:
        runner = runpy.run_path(
            str(ROOT / "tools" / "run_msproject_headless_relationship_characterisation.py")
        )
        identity = _owned_process_identity(
            executable_path="C:/WINPROJ.EXE"
        )
        events = [
            {"phase": "start", "details": {"pid": 999}},
            {
                "phase": "ownership_caption_set",
                "details": {"ownership_caption": "unique-caption"},
            },
            {
                "phase": "process_identified",
                "details": identity,
            },
        ]
        with tempfile.TemporaryDirectory() as temporary:
            log_path = Path(temporary) / "worker-events.jsonl"
            log_path.write_text(
                "".join(json.dumps(event) + "\n" for event in events), encoding="utf-8"
            )
            self.assertEqual([42], runner["_identified_pids_from_log"](log_path))
            self.assertEqual(
                ["unique-caption"], runner["_ownership_captions_from_log"](log_path)
            )
            self.assertEqual(
                [identity],
                runner["_identified_processes_from_log"](log_path),
            )

    def test_pid_only_journal_is_never_destructive_authority(self) -> None:
        runner = runpy.run_path(
            str(ROOT / "tools" / "run_msproject_headless_relationship_characterisation.py")
        )
        with tempfile.TemporaryDirectory() as temporary:
            log_path = Path(temporary) / "worker-events.jsonl"
            log_path.write_text(
                json.dumps({"phase": "process_identified", "details": {"pid": 42}})
                + "\n",
                encoding="utf-8",
            )
            self.assertEqual([], runner["_identified_processes_from_log"](log_path))

    def test_com_worker_rejects_compare_before_project_lookup(self) -> None:
        runner = runpy.run_path(
            str(ROOT / "tools" / "run_msproject_headless_relationship_characterisation.py")
        )
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(
                runner["headless_com"], "registered_project_executable"
            ) as project_lookup:
                with self.assertRaisesRegex(runner["SupervisionError"], "non-native"):
                    runner["run_supervised_worker"](
                        operation="compare",
                        repository_root=ROOT,
                        run_id="test",
                        workspace=Path(temporary),
                        result_path=Path(temporary) / "result.json",
                    )
            project_lookup.assert_not_called()

    def test_stop_conditions_precede_freeze_gate_and_comparator(self) -> None:
        runner = runpy.run_path(
            str(ROOT / "tools" / "run_msproject_headless_relationship_characterisation.py")
        )
        observations = {
            case_id: {"case_id": case_id, "stop_conditions": []}
            for case_id in headless.CASE_IDS
        }
        observations[headless.CASE_IDS[0]]["stop_conditions"] = [
            {"condition": "forced_termination"}
        ]
        run = Mock()
        function_globals = runner["_complete_run"].__globals__
        freeze_gate = Mock()
        comparator = Mock()
        with patch.dict(
            function_globals,
            {"verify_run_freeze_gate": freeze_gate, "run_comparison_worker": comparator},
        ):
            with self.assertRaisesRegex(runner["SupervisionError"], "stop conditions"):
                runner["_complete_run"](run, {}, observations)
            freeze_gate.assert_not_called()
            comparator.assert_not_called()

    def test_stop_conditions_must_be_an_explicit_empty_list(self) -> None:
        runner = runpy.run_path(
            str(ROOT / "tools" / "run_msproject_headless_relationship_characterisation.py")
        )
        for observation in ({}, {"stop_conditions": "none"}, {"stop_conditions": [{}]}):
            with self.subTest(observation=observation):
                with self.assertRaises(runner["SupervisionError"]):
                    runner["_reject_stop_conditions"](
                        observation, case_id="SEM-REL-001", resumed=True
                    )

    def test_legacy_forced_or_nonexited_session_is_a_resume_stop(self) -> None:
        runner = runpy.run_path(
            str(ROOT / "tools" / "run_msproject_headless_relationship_characterisation.py")
        )
        for session in (
            {"pid": 27112, "forced_termination": True, "exited": True},
            {"pid": 27112, "forced_termination": False, "exited": False},
        ):
            with self.subTest(session=session), self.assertRaisesRegex(
                runner["SupervisionError"], "retained native stop conditions"
            ):
                runner["_reject_stop_conditions"](
                    {"stop_conditions": [], "process_sessions": [session]},
                    case_id="SEM-REL-005",
                    resumed=True,
                )

    def test_stale_cached_environment_cannot_launch_a_worker(self) -> None:
        runner = runpy.run_path(
            str(ROOT / "tools" / "run_msproject_headless_relationship_characterisation.py")
        )
        with tempfile.TemporaryDirectory() as temporary:
            run = headless.create_run_workspace(Path(temporary), "stale-environment")
            environment_path = run.path / "environment.json"
            environment_path.write_text("{}\n", encoding="utf-8")
            runner["_result_sidecar_path"](environment_path).write_text(
                f"{headless.sha256_file(environment_path)}\n", encoding="ascii"
            )
            worker = Mock()
            validator = Mock(
                side_effect=runner["SupervisionError"]("stale environment")
            )
            function_globals = runner["_ensure_environment_and_preflight"].__globals__
            with (
                patch.dict(
                    function_globals,
                    {
                        "run_supervised_worker": worker,
                        "_validate_environment_capture": validator,
                    },
                ),
                self.assertRaisesRegex(
                    runner["SupervisionError"], "stale environment"
                ),
            ):
                runner["_ensure_environment_and_preflight"](
                    run, resume_existing=True
                )
            worker.assert_not_called()

    def test_resume_sweep_failure_precedes_any_case_worker(self) -> None:
        runner = runpy.run_path(
            str(ROOT / "tools" / "run_msproject_headless_relationship_characterisation.py")
        )
        run = Mock(run_id="run")
        case_worker = Mock()
        function_globals = runner["main"].__globals__
        with (
            patch.dict(
                function_globals,
                {
                    "create_run_workspace": Mock(return_value=run),
                    "_ensure_environment_and_preflight": Mock(
                        return_value=({}, {})
                    ),
                    "_resume_existing_cases": Mock(
                        side_effect=runner["SupervisionError"]("stale case")
                    ),
                    "_run_one_case": case_worker,
                },
            ),
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            return_code = runner["main"](
                [
                    "--case",
                    "SEM-REL-001",
                    "--run-id",
                    "run",
                    "--resume",
                    "--repository-root",
                    str(ROOT),
                ]
            )
        self.assertEqual(1, return_code)
        case_worker.assert_not_called()

    def test_comparison_worker_invokes_only_compare_module(self) -> None:
        runner = runpy.run_path(
            str(ROOT / "tools" / "run_msproject_headless_relationship_characterisation.py")
        )

        class CompletedProcess:
            def wait(self, timeout: int | None = None) -> int:
                return 0

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result_path = root / "comparison.json"
            commands: list[list[str]] = []

            def popen(command: list[str], **_kwargs: object) -> CompletedProcess:
                commands.append(command)
                result_path.write_text('{"status":"ok"}\n', encoding="utf-8")
                return CompletedProcess()

            with patch.object(runner["subprocess"], "Popen", side_effect=popen):
                result = runner["run_comparison_worker"](
                    repository_root=ROOT,
                    run_id="test",
                    workspace=root / "worker",
                    result_path=result_path,
                )
            self.assertEqual("ok", result["status"])
            self.assertIn(
                "deterministic_scheduling_core.native.msproject.headless_compare",
                commands[0],
            )
            self.assertNotIn(
                "deterministic_scheduling_core.native.msproject.headless_worker",
                commands[0],
            )

    def test_timeout_cleanup_passes_full_identity(self) -> None:
        runner = runpy.run_path(
            str(ROOT / "tools" / "run_msproject_headless_relationship_characterisation.py")
        )
        expected = Path("C:/Program Files/Microsoft Office/WINPROJ.EXE")
        identity = _owned_process_identity(executable_path=str(expected))

        class RunningProcess:
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

        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "case"
            log_path = workspace / "case-com-log.jsonl"

            def popen(*_args: object, **_kwargs: object) -> RunningProcess:
                log_path.write_text(
                    json.dumps({"phase": "process_identified", "details": identity}) + "\n",
                    encoding="utf-8",
                )
                return RunningProcess()

            terminate = Mock(return_value=True)
            process_list_calls = 0

            def list_processes() -> list[dict[str, object]]:
                nonlocal process_list_calls
                process_list_calls += 1
                return [] if process_list_calls == 1 else [identity]

            with (
                patch.object(runner["headless_com"], "registered_project_executable", return_value=expected),
                patch.object(runner["headless_com"], "list_winproj_processes", side_effect=list_processes),
                patch.object(runner["headless_com"], "windows_for_pid", return_value=[]),
                patch.object(runner["headless_com"], "terminate_verified_project_process", terminate),
                patch.object(runner["subprocess"], "Popen", side_effect=popen),
            ):
                with self.assertRaisesRegex(runner["SupervisionError"], "timeout"):
                    runner["run_supervised_worker"](
                        operation="case",
                        repository_root=ROOT,
                        run_id="test",
                        workspace=workspace,
                        result_path=workspace / "result.json",
                        case_id="SEM-REL-001",
                        timeouts={"worker": -1},
                    )
            terminate.assert_called_once_with(42, expected, process_identity=identity)

    def test_success_and_failure_process_leaks_use_full_identity_cleanup(self) -> None:
        runner = runpy.run_path(
            str(ROOT / "tools" / "run_msproject_headless_relationship_characterisation.py")
        )
        expected = Path("C:/Program Files/Microsoft Office/WINPROJ.EXE")
        identity = _owned_process_identity(executable_path=str(expected))

        class ExitedProcess:
            def __init__(self, return_code: int) -> None:
                self.return_code = return_code

            def poll(self) -> int:
                return self.return_code

            def wait(self, timeout: int | None = None) -> int:
                return self.return_code

        for return_code in (0, 1):
            with self.subTest(return_code=return_code), tempfile.TemporaryDirectory() as temporary:
                workspace = Path(temporary) / "case"
                log_path = workspace / "case-com-log.jsonl"

                def popen(*_args: object, **_kwargs: object) -> ExitedProcess:
                    log_path.write_text(
                        json.dumps({"phase": "process_identified", "details": identity})
                        + "\n",
                        encoding="utf-8",
                    )
                    return ExitedProcess(return_code)

                terminate = Mock(return_value=True)
                with (
                    patch.object(runner["headless_com"], "registered_project_executable", return_value=expected),
                    patch.object(runner["headless_com"], "list_winproj_processes", side_effect=[[], [identity]]),
                    patch.object(runner["headless_com"], "windows_for_pid", return_value=[]),
                    patch.object(runner["headless_com"], "terminate_verified_project_process", terminate),
                    patch.object(runner["subprocess"], "Popen", side_effect=popen),
                ):
                    with self.assertRaisesRegex(
                        runner["SupervisionError"], "left verified owned Project processes"
                    ):
                        runner["run_supervised_worker"](
                            operation="case",
                            repository_root=ROOT,
                            run_id="test",
                            workspace=workspace,
                            result_path=workspace / "result.json",
                            case_id="SEM-REL-001",
                        )
                terminate.assert_called_once_with(42, expected, process_identity=identity)


class FakeDependency:
    def __init__(self, predecessor: "FakeTask", successor: "FakeTask", type_value: int, lag_minutes: int, lag_type: int):
        self.From = predecessor
        self.To = successor
        self.Type = type_value
        self.Lag = lag_minutes
        self.LagType = lag_type


class FakeDependencies:
    def __init__(self, owner: "FakeTask", *, type_delta: int = 0, lag_sign: int = 1, lag_type: int = 5):
        self.owner = owner
        self.type_delta = type_delta
        self.lag_sign = lag_sign
        self.lag_type = lag_type

    def Add(self, predecessor: "FakeTask", type_value: int, lag: str) -> FakeDependency:
        hours = int(lag[:-1])
        return FakeDependency(predecessor, self.owner, type_value + self.type_delta, hours * 60 * self.lag_sign, self.lag_type)


class FakeTask:
    def __init__(self, name: str, task_id: int, **dependency_options: int):
        self.ID = task_id
        self.UniqueID = task_id
        self.Name = name
        self.Manual = True
        self.Type = 0
        self.EffortDriven = True
        self.Calendar = "None"
        self.ConstraintType = 0
        self.ConstraintDate = None
        self._duration = 0
        self.TaskDependencies = FakeDependencies(self, **dependency_options)

    @property
    def Duration(self) -> int:
        return self._duration

    @Duration.setter
    def Duration(self, value: str) -> None:
        self._duration = int(value[:-1]) * 60


class FakeTasks:
    def __init__(self, **dependency_options: int):
        self.values: list[FakeTask] = []
        self.dependency_options = dependency_options

    def Add(self, name: str) -> FakeTask:
        task = FakeTask(name, len(self.values) + 1, **self.dependency_options)
        self.values.append(task)
        return task


class FakeProject:
    def __init__(self, **dependency_options: int):
        self.Tasks = FakeTasks(**dependency_options)


class ComFailClosedTests(unittest.TestCase):
    def test_missing_windows_or_pywin32_fails_closed(self) -> None:
        with patch.object(headless_com.os, "name", "posix"):
            with self.assertRaises(headless_com.ProjectNotInstalledError):
                headless_com._load_pywin32()

    def test_com_creation_failure_is_not_replaced_by_another_scheduler(self) -> None:
        pythoncom = Mock()
        client = Mock()
        client.DispatchEx.side_effect = RuntimeError("COM unavailable")
        with (
            patch.object(headless_com, "_load_pywin32", return_value=(pythoncom, Mock(), client)),
            patch.object(headless_com, "registered_project_executable", return_value=Path("C:/WINPROJ.EXE")),
            patch.object(headless_com, "list_winproj_processes", return_value=[]),
        ):
            with self.assertRaises(RuntimeError):
                headless_com._open_application(None)
        pythoncom.CoInitialize.assert_called_once()
        pythoncom.CoUninitialize.assert_called_once()

    def test_unsupported_required_property_fails_closed(self) -> None:
        class Unsupported:
            def __setattr__(self, name: str, value: object) -> None:
                raise AttributeError(name)

        with self.assertRaises(headless_com.RequiredNativePropertyError):
            headless_com._required_set(Unsupported(), "Manual", False)

    def test_relationship_type_mismatch_is_retained(self) -> None:
        project = FakeProject(type_delta=1)
        _construction, assignment = headless_com._build_source_project(project, _source()["source_facts"])
        self.assertTrue(assignment["type_transformed"])
        self.assertEqual(1, assignment["native_type_supplied"])
        self.assertEqual(2, assignment["native_type_readback"])

    def test_lag_sign_mismatch_is_retained(self) -> None:
        project = FakeProject(lag_sign=-1)
        _construction, assignment = headless_com._build_source_project(
            project, _source("SEM-REL-005")["source_facts"]
        )
        self.assertTrue(assignment["lag_transformed"])
        self.assertEqual(2, assignment["source_lag_hours"])
        self.assertEqual(-120, assignment["native_lag_readback_minutes"])

    def test_project_session_always_quits_and_terminates_only_owned_process(self) -> None:
        app = Mock()
        pythoncom = Mock()
        session = headless_com._ProjectSession(
            app,
            pythoncom,
            {"pid": 42, "executable_path": "C:/Program Files/Microsoft Office/WINPROJ.EXE"},
            Path("C:/Program Files/Microsoft Office/WINPROJ.EXE"),
        )
        with (
            patch.object(headless_com, "_owned_process_identity_matches", return_value=True),
            patch.object(headless_com, "_wait_process_exit", return_value=True),
        ):
            result = session.quit()
        app.Quit.assert_called_once_with(0)
        pythoncom.CoUninitialize.assert_called_once()
        self.assertTrue(result["exited"])

    def test_ctypes_process_and_window_apis_have_explicit_handle_signatures(self) -> None:
        kernel32 = Mock()
        user32 = Mock()
        callback_type = object()
        with patch.object(
            headless_com.ctypes,
            "WinDLL",
            side_effect=[kernel32, user32],
        ):
            configured_kernel32 = headless_com._configured_kernel32()
            configured_user32 = headless_com._configured_user32(callback_type)

        self.assertIs(configured_kernel32.OpenProcess.restype, headless_com.wintypes.HANDLE)
        self.assertEqual(
            [headless_com.wintypes.HANDLE],
            configured_kernel32.CloseHandle.argtypes,
        )
        self.assertIs(
            configured_kernel32.CreateToolhelp32Snapshot.restype,
            headless_com.wintypes.HANDLE,
        )
        self.assertEqual(
            [callback_type, headless_com.wintypes.LPARAM],
            configured_user32.EnumWindows.argtypes,
        )
        self.assertEqual(
            [headless_com.wintypes.HWND],
            configured_user32.GetWindowTextLengthW.argtypes,
        )

    def test_new_project_process_requires_system_svchost_parent_origin(self) -> None:
        expected = Path("C:/Program Files/Microsoft Office/WINPROJ.EXE")
        process = {
            "pid": 20,
            "executable_path": str(expected),
            "parent_pid": 888,
            "creation_time_100ns": 2_000,
        }

        with (
            patch.dict(
                headless_com.os.environ,
                {"SystemRoot": "C:/Windows"},
                clear=False,
            ),
            patch.object(
                headless_com,
                "list_winproj_processes",
                return_value=[process],
            ),
            patch.object(
                headless_com,
                "_query_process_path",
                return_value="C:/Windows/System32/svchost.exe",
            ),
            patch.object(
                headless_com,
                "_query_process_creation_time_100ns",
                return_value=1_000,
            ),
        ):
            observed = headless_com._find_new_project_process(
                set(),
                expected,
                activation_not_before_100ns=1_500,
                timeout=0.1,
            )
        self.assertEqual(20, observed["pid"])
        self.assertEqual(888, observed["activation_parent_pid"])
        self.assertTrue(observed["ownership_origin_verified"])

    def test_concurrent_user_parent_is_rejected_as_com_origin(self) -> None:
        expected = Path("C:/Program Files/Microsoft Office/WINPROJ.EXE")
        process = {
            "pid": 20,
            "executable_path": str(expected),
            "parent_pid": 999,
            "creation_time_100ns": 2_000,
        }
        with (
            patch.dict(
                headless_com.os.environ,
                {"SystemRoot": "C:/Windows"},
                clear=False,
            ),
            patch.object(
                headless_com,
                "list_winproj_processes",
                return_value=[process],
            ),
            patch.object(
                headless_com,
                "_query_process_path",
                return_value="C:/Windows/explorer.exe",
            ),
            patch.object(
                headless_com,
                "_query_process_creation_time_100ns",
                return_value=1_000,
            ),
            self.assertRaisesRegex(
                headless_com.ProjectComError,
                "activation-parent provenance",
            ),
        ):
            headless_com._find_new_project_process(
                set(),
                expected,
                activation_not_before_100ns=1_500,
                timeout=0.1,
            )

    def test_forced_quit_is_a_stop_condition(self) -> None:
        conditions = headless_com._process_cleanup_stop_conditions(
            [
                {
                    "pid": 10,
                    "exited": True,
                    "forced_termination": False,
                    "ownership_revalidated_before_quit": True,
                    "termination_error": None,
                },
                {
                    "pid": 20,
                    "exited": True,
                    "forced_termination": True,
                    "ownership_revalidated_before_quit": True,
                    "termination_error": None,
                },
                {
                    "pid": 30,
                    "exited": True,
                    "forced_termination": False,
                    "ownership_revalidated_before_quit": False,
                    "termination_error": "ownership changed",
                },
            ]
        )
        self.assertEqual(
            [
                {
                    "condition": "project_process_required_forced_termination",
                    "pid": 20,
                    "exited": True,
                    "termination_error": None,
                    "ownership_revalidated_before_quit": True,
                },
                {
                    "condition": "project_process_ownership_not_revalidated",
                    "pid": 30,
                    "exited": True,
                    "termination_error": "ownership changed",
                    "ownership_revalidated_before_quit": False,
                }
            ],
            conditions,
        )

    def test_existing_project_process_prevents_com_activation(self) -> None:
        pythoncom = Mock()
        client = Mock()
        with (
            patch.object(headless_com, "_load_pywin32", return_value=(pythoncom, Mock(), client)),
            patch.object(
                headless_com,
                "registered_project_executable",
                return_value=Path("C:/Program Files/Microsoft Office/WINPROJ.EXE"),
            ),
            patch.object(
                headless_com,
                "list_winproj_processes",
                return_value=[{"pid": 77, "executable_path": "C:/WINPROJ.EXE"}],
            ),
        ):
            with self.assertRaisesRegex(headless_com.ProjectComError, "already exists"):
                headless_com._open_application(None)
        pythoncom.CoInitialize.assert_not_called()
        client.DispatchEx.assert_not_called()

    def test_unproven_com_object_is_never_quit(self) -> None:
        pythoncom = Mock()
        app = Mock()
        app.Visible = False
        client = Mock()
        client.DispatchEx.return_value = app
        with (
            patch.object(headless_com, "_load_pywin32", return_value=(pythoncom, Mock(), client)),
            patch.object(
                headless_com,
                "registered_project_executable",
                return_value=Path("C:/Program Files/Microsoft Office/WINPROJ.EXE"),
            ),
            patch.object(headless_com, "list_winproj_processes", return_value=[]),
            patch.object(
                headless_com,
                "_find_new_project_process",
                side_effect=headless_com.ProjectComError("no owned process"),
            ),
        ):
            with self.assertRaisesRegex(headless_com.ProjectComError, "no owned process"):
                headless_com._open_application(None)
        app.Quit.assert_not_called()
        pythoncom.CoUninitialize.assert_called_once()

    def test_process_identity_events_emit_every_destructive_authority_field(self) -> None:
        expected = Path("C:/Program Files/Microsoft Office/WINPROJ.EXE")
        candidate = _owned_process_identity(executable_path=str(expected))
        candidate.pop("ownership_caption")
        candidate.pop("ownership_hwnd")
        candidate["parent_pid"] = candidate["activation_parent_pid"]
        events: list[tuple[str, dict]] = []
        pythoncom = Mock()
        app = Mock()
        app.Visible = False
        client = Mock()
        client.DispatchEx.return_value = app

        def bind(
            process: dict,
            _expected: Path,
            caption: str,
            **_kwargs: object,
        ) -> dict:
            return {
                **process,
                "ownership_caption": caption,
                "ownership_hwnd": 5_678,
            }

        def callback(_stage: str, phase: str, details: dict) -> None:
            events.append((phase, details))

        with (
            patch.dict(
                headless_com.os.environ,
                {"SystemRoot": "C:/Windows"},
                clear=False,
            ),
            patch.object(
                headless_com,
                "_load_pywin32",
                return_value=(pythoncom, Mock(), client),
            ),
            patch.object(
                headless_com,
                "registered_project_executable",
                return_value=expected,
            ),
            patch.object(headless_com, "list_winproj_processes", return_value=[]),
            patch.object(
                headless_com,
                "_find_new_project_process",
                return_value=candidate,
            ),
            patch.object(headless_com, "windows_for_pid", return_value=[]),
            patch.object(headless_com, "_bind_process_to_caption", side_effect=bind),
        ):
            session = headless_com._open_application(callback)

        authoritative = {
            phase: details
            for phase, details in events
            if phase in {"ownership_caption_set", "process_identified"}
        }
        self.assertEqual(
            {"ownership_caption_set", "process_identified"},
            set(authoritative),
        )
        required = set(headless_com.OWNED_PROCESS_IDENTITY_FIELDS)
        for details in authoritative.values():
            self.assertTrue(required.issubset(details), details)
        with (
            patch.object(
                headless_com,
                "_owned_process_identity_matches",
                return_value=True,
            ),
            patch.object(headless_com, "_wait_process_exit", return_value=True),
        ):
            session.quit()

    def test_termination_requires_full_current_ownership_identity(self) -> None:
        with self.assertRaisesRegex(headless_com.ProjectComError, "full ownership identity"):
            headless_com.terminate_verified_project_process(
                42, Path("C:/Program Files/Microsoft Office/WINPROJ.EXE")
            )

    def test_termination_authorizes_and_acts_on_the_same_kernel_handle(self) -> None:
        expected = Path("C:/Program Files/Microsoft Office/WINPROJ.EXE")
        identity = _owned_process_identity(executable_path=str(expected))
        kernel32 = Mock()
        handle = object()
        kernel32.OpenProcess.return_value = handle
        with (
            patch.dict(
                headless_com.os.environ,
                {"SystemRoot": "C:/Windows"},
                clear=False,
            ),
            patch.object(headless_com, "_configured_kernel32", return_value=kernel32),
            patch.object(
                headless_com,
                "_query_process_path_from_handle",
                return_value=str(expected),
            ) as path_query,
            patch.object(
                headless_com,
                "_query_process_creation_time_from_handle",
                return_value=9_999,
            ) as creation_query,
            patch.object(
                headless_com,
                "_query_process_path",
                side_effect=AssertionError("PID-only lookup must not authorize termination"),
            ),
            self.assertRaisesRegex(
                headless_com.ProjectComError, "handle identity changed"
            ),
        ):
            headless_com.terminate_verified_project_process(
                42, expected, process_identity=identity
            )
        path_query.assert_called_once_with(kernel32, handle)
        creation_query.assert_called_once_with(kernel32, handle)
        kernel32.TerminateProcess.assert_not_called()
        kernel32.CloseHandle.assert_called_once_with(handle)

    def test_changed_session_identity_is_never_closed_or_quit(self) -> None:
        app = Mock()
        pythoncom = Mock()
        session = headless_com._ProjectSession(
            app,
            pythoncom,
            {
                "pid": 42,
                "executable_path": "C:/Program Files/Microsoft Office/WINPROJ.EXE",
                "creation_time_100ns": 123,
                "ownership_caption": "token",
                "ownership_hwnd": 456,
            },
            Path("C:/Program Files/Microsoft Office/WINPROJ.EXE"),
        )
        with patch.object(headless_com, "_owned_process_identity_matches", return_value=False):
            with self.assertRaisesRegex(headless_com.ProjectComError, "ownership identity changed"):
                session.close_project()
        app.FileCloseEx.assert_not_called()
        with (
            patch.object(headless_com, "_owned_process_identity_matches", return_value=False),
            patch.object(headless_com, "_wait_process_exit", return_value=False),
        ):
            result = session.quit()
        app.Quit.assert_not_called()
        self.assertFalse(result["exited"])
        self.assertIn("refused Application.Quit", result["termination_error"])

    def test_optional_com_method_is_invoked_before_serialization(self) -> None:
        app = Mock()
        app.FileBuildID.return_value = "16.0.20228.20186"
        self.assertEqual(
            "16.0.20228.20186",
            headless_com._optional_call(app, "FileBuildID"),
        )
        app.FileBuildID.assert_called_once_with()

    def test_project_xml_reopen_uses_exact_exported_text(self) -> None:
        app = Mock()
        app.OpenXML.return_value = 0
        marker = object()
        app.ActiveProject = marker
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "exact.xml"
            path.write_bytes(b"\xef\xbb\xbf<Project><Name>exact</Name></Project>")
            observed = headless_com._open_project_xml(app, path)
        self.assertIs(marker, observed)
        app.OpenXML.assert_called_once_with("<Project><Name>exact</Name></Project>")

    def test_datetime_serialization_preserves_project_wall_clock_components(self) -> None:
        tagged = headless_com._json_value(
            headless_com.datetime(
                2026,
                1,
                5,
                0,
                0,
                tzinfo=headless_com.timezone(headless_com.timedelta(hours=-3)),
            )
        )
        self.assertEqual("2026-01-05T00:00:00", tagged[:19])

    def test_capture_validation_enforces_no_resources_progress_status_and_exact_link(self) -> None:
        capture = _capture()
        assignment = {"native_type_supplied": 1}
        self.assertEqual(
            [],
            headless_com._case_capture_stop_conditions(
                capture,
                _source()["source_facts"],
                assignment,
                stage="after_open",
            ),
        )
        changed = json.loads(json.dumps(capture))
        changed["project"]["resource_count"] = 1
        changed["project"]["status_date"] = "2026-01-05T08:00:00+08:00"
        changed["tasks"][1]["percent_complete"] = 10
        changed["tasks"][1]["task_dependencies"][0]["type"] = 3
        conditions = headless_com._case_capture_stop_conditions(
            changed,
            _source()["source_facts"],
            assignment,
            stage="after_recalculation",
        )
        observed = {item["condition"] for item in conditions}
        self.assertIn("unexpected_native_resources", observed)
        self.assertIn("unexpected_native_status_date", observed)
        self.assertIn("unexpected_native_progress", observed)
        self.assertIn("native_relationship_readback_changed", observed)

    def test_capture_validation_rejects_missing_or_malformed_required_timestamps(self) -> None:
        capture = _capture()
        capture["project"]["start"] = None
        capture["tasks"][1]["finish"] = "2026-01-05"
        capture["tasks"][0]["start"] = "2026-01-05T08:00:00"
        conditions = headless_com._case_capture_stop_conditions(
            capture,
            _source()["source_facts"],
            {"native_type_supplied": 1},
            stage="after_open",
        )
        invalid_fields = {
            item["field"]
            for item in conditions
            if item["condition"] == "required_schedule_timestamp_invalid"
        }
        self.assertEqual(
            {"project.start", "tasks.A.start", "tasks.B.finish"},
            invalid_fields,
        )

    def test_preflight_rejects_non_perth_observation_before_project_launch(self) -> None:
        with (
            patch.object(
                headless_com,
                "_capture_windows_time_zone",
                return_value={
                    "windows_name": "UTC",
                    "utc_offset": "+00:00",
                    "matches_required_perth_zone": False,
                },
            ),
            patch.object(headless_com, "run_native_case") as run_case,
        ):
            with self.assertRaisesRegex(
                headless_com.ProjectComError, "requires the observed"
            ):
                headless_com.run_preflight(Path("unused"))
        run_case.assert_not_called()

    def test_case_uses_distinct_initial_and_reopen_sessions(self) -> None:
        class App:
            def __init__(self) -> None:
                self.Calculation = 0
                self.AutoLevel = False

            def CalculateProject(self) -> bool:
                return True

            def LevelingOptions(self, automatic: bool) -> bool:
                self.AutoLevel = automatic
                return True

        class Session:
            def __init__(self, pid: int) -> None:
                self.pid = pid
                self.app = App()
                self.pythoncom = Mock()
                self.process = {"pid": pid, "executable_path": "WINPROJ.EXE"}
                self.closed = False

            def close_project(self) -> None:
                self.closed = True

            def quit(self) -> dict:
                return {
                    "pid": self.pid,
                    "exited": True,
                    "forced_termination": False,
                    "ownership_revalidated_before_quit": True,
                    "termination_error": None,
                }

        sessions = [Session(101), Session(202)]

        def save(_app: object, path: Path) -> None:
            path.write_bytes(b"mpp")

        def export(_app: object, _pythoncom: object, path: Path) -> None:
            path.write_text("<x/>", encoding="utf-8")

        xml_observation = {
            "namespace": "urn:test",
            "save_version": "1",
            "project": {},
            "calendars": [],
            "tasks": [{"predecessor_links": [{"type": "1", "link_lag": "0", "lag_format": "5"}]}],
        }
        with tempfile.TemporaryDirectory() as temporary:
            with (
                patch.object(headless_com, "_open_application", side_effect=sessions),
                patch.object(headless_com, "_configure_blank_project", return_value=object()),
                patch.object(
                    headless_com,
                    "_build_source_project",
                    return_value=(
                        {"tasks": []},
                        {
                            "native_type_supplied": 1,
                            "type_transformed": False,
                            "lag_transformed": False,
                        },
                    ),
                ),
                patch.object(
                    headless_com,
                    "_capture_project",
                    side_effect=[_capture(101), _capture(202), _capture(202)],
                ),
                patch.object(headless_com, "_save_mpp", side_effect=save),
                patch.object(headless_com, "_export_xml", side_effect=export),
                patch.object(
                    headless_com,
                    "parse_project_xml_observation",
                    return_value=xml_observation,
                ),
                patch.object(headless_com, "_open_file", return_value=object()),
            ):
                result = headless_com.run_native_case(_source(), Path(temporary))
        self.assertEqual([101, 202], [item["pid"] for item in result["process_sessions"]])
        self.assertTrue(all(session.closed for session in sessions))

    def test_initial_cleanup_failure_prevents_reopen_process_launch(self) -> None:
        session = Mock()
        session.pid = 101
        session.pythoncom = Mock()
        session.process = {"pid": 101, "executable_path": "WINPROJ.EXE"}
        session.app.CalculateProject.return_value = True
        session.quit.return_value = {
            "pid": 101,
            "exited": True,
            "forced_termination": True,
        }
        open_application = Mock(return_value=session)
        assignment = {
            "native_type_supplied": 1,
            "type_transformed": False,
            "lag_transformed": False,
        }
        with tempfile.TemporaryDirectory() as temporary:
            with (
                patch.object(
                    headless_com, "_open_application", open_application
                ),
                patch.object(
                    headless_com, "_configure_blank_project", return_value=object()
                ),
                patch.object(
                    headless_com,
                    "_build_source_project",
                    return_value=({"tasks": []}, assignment),
                ),
                patch.object(
                    headless_com, "_capture_project", return_value=_capture(101)
                ),
                patch.object(headless_com, "_save_mpp"),
                patch.object(headless_com, "_export_xml"),
                patch.object(
                    headless_com,
                    "parse_project_xml_observation",
                    return_value={"project": {}, "tasks": []},
                ),
                self.assertRaisesRegex(
                    headless_com.ProjectComError, "cleanup failed before reopen"
                ),
            ):
                headless_com.run_native_case(_source(), Path(temporary))
        open_application.assert_called_once()


if __name__ == "__main__":
    unittest.main()
