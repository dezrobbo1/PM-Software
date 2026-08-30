#!/usr/bin/env python3
"""Run bounded headless characterisation through the real Project COM engine."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import secrets
import stat
import subprocess
import sys
import time
from typing import Any, Mapping

from deterministic_scheduling_core.native.msproject import (
    freeze as native_freeze,
    headless,
    headless_com,
)
from deterministic_scheduling_core.native.msproject.freeze import (
    NativeEvidenceError,
    RegularFileSnapshot,
    read_regular_file_snapshot,
)
from deterministic_scheduling_core.native.msproject.headless import (
    CASE_IDS,
    TRACK_ID,
    ObservationFreezeError,
    create_case_workspace,
    create_run_workspace,
    durable_write_canonical_json,
    freeze_native_observation,
    load_source_only_projection_with_identity,
    normalize_observation,
    sha256_file,
    verify_observation_freeze,
    verify_run_freeze_gate,
)
from deterministic_scheduling_core.provenance import (
    canonical_json as canonical_json_module,
)
from deterministic_scheduling_core.provenance.canonical_json import canonical_bytes


PERTH_TZ = timezone(timedelta(hours=8), name="Australia/Perth")
DEFAULT_TIMEOUTS = {
    "worker": 30,
    "startup": 45,
    "project_startup": 45,
    "environment_project_startup": 45,
    "reopen_startup": 45,
    "calendar_startup": 45,
    "calendar_reopen_startup": 45,
    "project_creation": 30,
    "calculation": 30,
    "calendar_calculation": 30,
    "save": 30,
    "reopen_save": 30,
    "calendar_save": 30,
    "xml_export": 30,
    "reopen_xml_export": 30,
    "calendar_xml_export": 30,
    "calendar_reexport": 30,
    "reopen": 30,
    "calendar_xml_reopen": 30,
    "recalculation": 30,
    "calendar_recalculation": 30,
    "close": 20,
    "reopen_close": 20,
    "quit": 20,
    "reopen_quit": 20,
}
NATIVE_WORKER_OPERATIONS = frozenset({"environment", "preflight", "case", "calendar"})
COMPARISON_TIMEOUT_SECONDS = 60
MAX_COMPARATOR_SOURCE_BYTES = 1024 * 1024
MAX_COMPARISON_RESULT_BYTES = 4 * 1024 * 1024
MAX_COMPARISON_JOURNAL_BYTES = 1024 * 1024
MAX_NATIVE_RESULT_BYTES = 4 * 1024 * 1024
MAX_NATIVE_JOURNAL_BYTES = 1024 * 1024
PREFLIGHT_REQUIRED_OPERATIONS = frozenset(
    {
        "create_blank_project",
        "remain_hidden",
        "set_calculation_mode",
        "set_project_start",
        "create_tasks",
        "set_durations",
        "set_task_mode",
        "set_task_type",
        "set_effort_driven",
        "set_predecessors",
        "set_signed_lag",
        "assign_24_hours_calendar",
        "invoke_native_calculation",
        "read_start_finish",
        "save_mpp",
        "close",
        "reopen",
        "recalculate",
        "export_project_xml",
        "quit_cleanly",
    }
)
CASE_NATIVE_ARTIFACT_ROLES = headless.CASE_NATIVE_ARTIFACT_ROLES
CASE_SUPPORT_ARTIFACT_ROLES = headless.CASE_SUPPORT_ARTIFACT_ROLES
CALENDAR_ARTIFACT_ROLES = frozenset(
    {"authored_mpp", "authored_xml", "reexported_xml"}
)
COMPARATOR_MODULE = "deterministic_scheduling_core.native.msproject.headless_compare"
COMPARATOR_SOURCE_RELATIVE_PATH = (
    "src/deterministic_scheduling_core/native/msproject/headless_compare.py"
)
ORACLE_SOURCE_SPECS = {
    "comparator": {
        "module": COMPARATOR_MODULE,
        "relative_path": COMPARATOR_SOURCE_RELATIVE_PATH,
    },
    "pilot": {
        "module": "deterministic_scheduling_core.native.msproject.pilot",
        "relative_path": "src/deterministic_scheduling_core/native/msproject/pilot.py",
    },
    "headless": {
        "module": "deterministic_scheduling_core.native.msproject.headless",
        "relative_path": "src/deterministic_scheduling_core/native/msproject/headless.py",
    },
    "freeze": {
        "module": "deterministic_scheduling_core.native.msproject.freeze",
        "relative_path": "src/deterministic_scheduling_core/native/msproject/freeze.py",
    },
    "canonical_json": {
        "module": "deterministic_scheduling_core.provenance.canonical_json",
        "relative_path": "src/deterministic_scheduling_core/provenance/canonical_json.py",
    },
    "msproject_package": {
        "module": "deterministic_scheduling_core.native.msproject",
        "relative_path": "src/deterministic_scheduling_core/native/msproject/__init__.py",
    },
}
SEALED_REFERENCE_RELATIVE_DIRECTORY = (
    "native-validation/pilot-kits/microsoft-project-relationship-v0.1/"
    "sealed-expected-normalized"
)
ORACLE_PROVENANCE_SCHEMA = "headless-msproject-oracle-provenance-v0.1"


class SupervisionError(RuntimeError):
    pass


def _require_live_perth_time_zone() -> dict[str, Any]:
    """Fail before any COM worker when Windows is not on the frozen zone."""

    observed = headless_com._capture_windows_time_zone()
    if (
        not isinstance(observed, Mapping)
        or observed.get("windows_name") != "W. Australia Standard Time"
        or observed.get("utc_offset") != "+08:00"
        or observed.get("matches_required_perth_zone") is not True
    ):
        raise SupervisionError(
            "live Windows time zone is not the required Australia/Perth zone"
        )
    return dict(observed)


def _now() -> str:
    return datetime.now(PERTH_TZ).isoformat(timespec="microseconds")


def _default_run_id() -> str:
    return datetime.now(PERTH_TZ).strftime("%Y%m%dT%H%M%Sp0800")


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SupervisionError(f"expected a JSON object: {path}")
    return value


def _safe_state(path: Path) -> dict[str, Any] | None:
    try:
        return _read_json(path)
    except (FileNotFoundError, json.JSONDecodeError, OSError, SupervisionError):
        return None


def _parse_canonical_json_object(data: bytes, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise SupervisionError(f"{label} is not valid UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise SupervisionError(f"{label} must be a JSON object")
    try:
        canonical = canonical_bytes(value) + b"\n"
    except (TypeError, ValueError, UnicodeError) as error:
        raise SupervisionError(f"{label} is outside canonical JSON") from error
    if data != canonical:
        raise SupervisionError(f"{label} is not exact canonical JSON")
    return value


def _read_canonical_json_object_snapshot(
    path: Path, *, label: str, max_bytes: int
) -> tuple[dict[str, Any], RegularFileSnapshot]:
    try:
        snapshot = read_regular_file_snapshot(
            path, label=label, max_bytes=max_bytes
        )
    except NativeEvidenceError as error:
        raise SupervisionError(
            f"{label} is missing, unsafe, replaced, or exceeds its byte limit"
        ) from error
    return _parse_canonical_json_object(snapshot.data, label=label), snapshot


def _validate_comparison_journal_event(
    event: Mapping[str, Any],
    *,
    expected_sequence: int,
    expected_worker_pid: int,
) -> None:
    if (
        set(event) != {"sequence", "worker_pid", "stage", "phase", "details"}
        or type(event.get("sequence")) is not int
        or event.get("sequence") != expected_sequence
        or type(event.get("worker_pid")) is not int
        or event.get("worker_pid") != expected_worker_pid
        or event.get("stage") != "comparison"
        or not isinstance(event.get("phase"), str)
        or type(event.get("details")) is not dict
    ):
        raise SupervisionError(
            "comparison journal event identity or schema is malformed"
        )


def _read_comparison_terminal_digest(
    *,
    state_path: Path,
    log_path: Path,
    run_id: str,
    worker_pid: int,
) -> str:
    state, state_snapshot = _read_canonical_json_object_snapshot(
        state_path,
        label="comparison terminal state",
        max_bytes=MAX_COMPARISON_JOURNAL_BYTES,
    )
    try:
        log_snapshot = read_regular_file_snapshot(
            log_path,
            label="comparison append-only journal",
            max_bytes=MAX_COMPARISON_JOURNAL_BYTES,
        )
    except NativeEvidenceError as error:
        raise SupervisionError(
            "comparison append-only journal is missing, unsafe, replaced, or exceeds its byte limit"
        ) from error
    if not log_snapshot.data or not log_snapshot.data.endswith(b"\n"):
        raise SupervisionError("comparison append-only journal is malformed")
    event_lines = log_snapshot.data.splitlines(keepends=True)
    events = [
        _parse_canonical_json_object(
            line, label=f"comparison journal event {sequence}"
        )
        for sequence, line in enumerate(event_lines, start=1)
    ]
    for sequence, event in enumerate(events, start=1):
        _validate_comparison_journal_event(
            event,
            expected_sequence=sequence,
            expected_worker_pid=worker_pid,
        )
    first = events[0]
    if first["phase"] != "start" or first["details"] != {"run_id": run_id}:
        raise SupervisionError("comparison journal start event is malformed")
    if any(event["phase"] in {"complete", "error"} for event in events[:-1]):
        raise SupervisionError(
            "comparison journal contains an earlier conflicting terminal event"
        )
    terminal = events[-1]
    _validate_comparison_journal_event(
        state,
        expected_sequence=len(events),
        expected_worker_pid=worker_pid,
    )
    if state_snapshot.data != event_lines[-1]:
        raise SupervisionError(
            "comparison state disagrees with the append-only journal terminal event"
        )
    terminal_details = terminal["details"]
    if (
        terminal["phase"] != "complete"
        or set(terminal_details) != {"result_sha256"}
        or not _is_sha256(terminal_details.get("result_sha256"))
    ):
        raise SupervisionError(
            "comparison journal lacks one well-formed terminal complete event"
        )
    return str(terminal_details["result_sha256"])


def _validate_native_worker_journal_event(
    event: Mapping[str, Any],
    *,
    expected_sequence: int,
    expected_worker_pid: int,
) -> None:
    if (
        set(event) != {"sequence", "worker_pid", "stage", "phase", "details"}
        or type(event.get("sequence")) is not int
        or event.get("sequence") != expected_sequence
        or type(event.get("worker_pid")) is not int
        or event.get("worker_pid") != expected_worker_pid
        or type(event.get("stage")) is not str
        or not event.get("stage")
        or type(event.get("phase")) is not str
        or not event.get("phase")
        or type(event.get("details")) is not dict
    ):
        raise SupervisionError(
            "native worker journal event identity or schema is malformed"
        )


def _read_native_worker_terminal_digest(
    *,
    state_path: Path,
    log_path: Path,
    operation: str,
    run_id: str,
    case_id: str | None,
    worker_pid: int,
) -> str:
    state, state_snapshot = _read_canonical_json_object_snapshot(
        state_path,
        label="native worker terminal state",
        max_bytes=MAX_NATIVE_JOURNAL_BYTES,
    )
    try:
        log_snapshot = read_regular_file_snapshot(
            log_path,
            label="native worker append-only journal",
            max_bytes=MAX_NATIVE_JOURNAL_BYTES,
        )
    except NativeEvidenceError as error:
        raise SupervisionError(
            "native worker append-only journal is missing, unsafe, replaced, "
            "or exceeds its byte limit"
        ) from error
    if not log_snapshot.data or not log_snapshot.data.endswith(b"\n"):
        raise SupervisionError("native worker append-only journal is malformed")
    event_lines = log_snapshot.data.splitlines(keepends=True)
    events = [
        _parse_canonical_json_object(
            line, label=f"native worker journal event {sequence}"
        )
        for sequence, line in enumerate(event_lines, start=1)
    ]
    for sequence, event in enumerate(events, start=1):
        _validate_native_worker_journal_event(
            event,
            expected_sequence=sequence,
            expected_worker_pid=worker_pid,
        )
    first = events[0]
    if (
        first["stage"] != "worker"
        or first["phase"] != "start"
        or first["details"]
        != {"operation": operation, "run_id": run_id, "case_id": case_id}
    ):
        raise SupervisionError("native worker journal start event is malformed")
    if any(event["stage"] == "worker" for event in events[1:-1]):
        raise SupervisionError(
            "native worker journal contains an earlier conflicting worker terminal event"
        )
    terminal = events[-1]
    _validate_native_worker_journal_event(
        state,
        expected_sequence=len(events),
        expected_worker_pid=worker_pid,
    )
    if state_snapshot.data != event_lines[-1]:
        raise SupervisionError(
            "native worker state disagrees with the append-only journal terminal event"
        )
    terminal_details = terminal["details"]
    if (
        terminal["stage"] != "worker"
        or terminal["phase"] != "complete"
        or set(terminal_details) != {"operation", "result_sha256"}
        or terminal_details.get("operation") != operation
        or not _is_sha256(terminal_details.get("result_sha256"))
    ):
        raise SupervisionError(
            "native worker journal lacks one well-formed terminal complete event"
        )
    return str(terminal_details["result_sha256"])


def _identified_processes_from_log(log_path: Path) -> list[dict[str, Any]]:
    """Return full caption-bound identities emitted by the COM worker.

    A PID alone is never authority for destructive cleanup.  The creation
    identity, exact executable path, Windows COM activation-parent provenance,
    ownership caption and HWND all come from the append-only worker journal and
    are revalidated immediately before a forced termination.
    """

    try:
        lines = log_path.read_text(encoding="utf-8").splitlines()
    except (FileNotFoundError, OSError):
        return []
    identified: dict[int, dict[str, Any]] = {}
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        details = event.get("details")
        if (
            event.get("phase")
            in {"ownership_caption_set", "process_identified"}
            and isinstance(details, dict)
            and isinstance(details.get("pid"), int)
            and isinstance(details.get("executable_path"), str)
            and isinstance(details.get("creation_time_100ns"), int)
            and isinstance(details.get("ownership_caption"), str)
            and isinstance(details.get("ownership_hwnd"), int)
            and isinstance(details.get("activation_parent_pid"), int)
            and isinstance(details.get("activation_parent_executable_path"), str)
            and isinstance(
                details.get("activation_parent_creation_time_100ns"), int
            )
            and details.get("ownership_origin_verified") is True
        ):
            identified[int(details["pid"])] = {
                "pid": int(details["pid"]),
                "executable_path": details["executable_path"],
                "creation_time_100ns": int(details["creation_time_100ns"]),
                "ownership_caption": details["ownership_caption"],
                "ownership_hwnd": int(details["ownership_hwnd"]),
                "activation_parent_pid": int(details["activation_parent_pid"]),
                "activation_parent_executable_path": details[
                    "activation_parent_executable_path"
                ],
                "activation_parent_creation_time_100ns": int(
                    details["activation_parent_creation_time_100ns"]
                ),
                "ownership_origin_verified": True,
            }
    return list(identified.values())


def _identified_pids_from_log(log_path: Path) -> list[int]:
    """Return caption-bound PIDs for diagnostics, never destructive cleanup."""

    try:
        lines = log_path.read_text(encoding="utf-8").splitlines()
    except (FileNotFoundError, OSError):
        return []
    identified: list[int] = []
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        details = event.get("details")
        if (
            event.get("phase") == "process_identified"
            and isinstance(details, dict)
            and isinstance(details.get("pid"), int)
            and int(details["pid"]) not in identified
        ):
            identified.append(int(details["pid"]))
    return identified


def _ownership_captions_from_log(log_path: Path) -> list[str]:
    try:
        lines = log_path.read_text(encoding="utf-8").splitlines()
    except (FileNotFoundError, OSError):
        return []
    captions: list[str] = []
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        details = event.get("details")
        caption = details.get("ownership_caption") if isinstance(details, dict) else None
        if isinstance(caption, str) and caption and caption not in captions:
            captions.append(caption)
    return captions


def _caption_bound_pids(captions: list[str], expected_path: Path) -> list[int]:
    if not captions:
        return []
    bound: list[int] = []
    for process in headless_com.list_winproj_processes():
        raw_path = process.get("executable_path")
        if not raw_path or Path(str(raw_path)).resolve(strict=False) != expected_path.resolve(strict=False):
            continue
        titles = [str(window.get("title", "")) for window in headless_com.windows_for_pid(int(process["pid"]))]
        if any(caption in title for caption in captions for title in titles):
            bound.append(int(process["pid"]))
    return bound


def _terminate_worker(process: subprocess.Popen[Any]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _matching_new_project_processes(
    processes: list[dict[str, Any]],
    *,
    baseline_identities: set[tuple[int, int | None]],
    expected_path: Path,
) -> list[dict[str, Any]]:
    expected = expected_path.resolve(strict=False)
    result: list[dict[str, Any]] = []
    for process in processes:
        pid = process.get("pid")
        creation = process.get("creation_time_100ns")
        raw_path = process.get("executable_path")
        if not isinstance(pid, int):
            continue
        identity = (pid, creation if isinstance(creation, int) else None)
        complete_identity = (
            isinstance(creation, int)
            and isinstance(raw_path, str)
            and bool(raw_path)
        )
        if complete_identity and identity in baseline_identities:
            continue
        retained = dict(process)
        query_failures: list[str] = []
        if not isinstance(creation, int):
            query_failures.append("creation_time_unavailable")
        if not isinstance(raw_path, str) or not raw_path:
            query_failures.append("executable_path_unavailable")
        if query_failures:
            retained["identity_query_failures"] = query_failures
        elif Path(raw_path).resolve(strict=False) != expected:
            retained["identity_mismatch"] = "unexpected_executable_path"
        result.append(retained)
    return result


def _verified_owned_identities(
    log_path: Path,
    *,
    new_processes: list[dict[str, Any]],
    expected_path: Path,
) -> list[dict[str, Any]]:
    current_by_identity = {
        (int(item["pid"]), item.get("creation_time_100ns")): item
        for item in new_processes
    }
    expected = expected_path.resolve(strict=False)
    verified: list[dict[str, Any]] = []
    for identity in _identified_processes_from_log(log_path):
        key = (int(identity["pid"]), identity.get("creation_time_100ns"))
        current = current_by_identity.get(key)
        if current is None:
            continue
        if Path(str(identity["executable_path"])).resolve(strict=False) != expected:
            continue
        current_path = current.get("executable_path")
        if (
            current.get("identity_query_failures")
            or current.get("identity_mismatch")
            or not isinstance(current_path, str)
            or not current_path
            or Path(current_path).resolve(strict=False) != expected
        ):
            continue
        verified.append(identity)
    return verified


def _queryable_exact_path_processes(
    new_processes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return new WINPROJ identities whose creation time and path are exact."""

    return [
        item
        for item in new_processes
        if not item.get("identity_query_failures")
        and not item.get("identity_mismatch")
    ]


def _window_inventory(processes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    inventory: list[dict[str, Any]] = []
    for process in processes:
        item = dict(process)
        try:
            item["windows"] = headless_com.windows_for_pid(int(process["pid"]))
        except Exception as error:
            item["window_enumeration_error"] = f"{type(error).__name__}: {error}"
        inventory.append(item)
    return inventory


def run_supervised_worker(
    *,
    operation: str,
    repository_root: Path,
    run_id: str,
    workspace: Path,
    result_path: Path,
    case_id: str | None = None,
    timeouts: Mapping[str, int] = DEFAULT_TIMEOUTS,
) -> dict[str, Any]:
    if operation not in NATIVE_WORKER_OPERATIONS:
        raise SupervisionError(
            f"refusing non-native operation in COM worker: {operation!r}"
        )
    workspace.mkdir(parents=True, exist_ok=True)
    state_path = workspace / f"{operation}-stage-state.json"
    log_path = workspace / f"{operation}-com-log.jsonl"
    stdout_path = workspace / f"{operation}-worker-stdout.log"
    stderr_path = workspace / f"{operation}-worker-stderr.log"
    result_sidecar_path = _result_sidecar_path(result_path)
    pycache_prefix = workspace / (
        f"{operation}-import-pycache-{secrets.token_hex(16)}"
    )
    for path in (
        state_path,
        log_path,
        stdout_path,
        stderr_path,
        result_path,
        result_sidecar_path,
    ):
        if path.exists():
            raise SupervisionError(f"refusing to overwrite worker evidence: {path}")
    if pycache_prefix.exists():
        raise SupervisionError(
            f"native worker pycache prefix must be fresh and nonexistent: {pycache_prefix}"
        )
    executable = headless_com.registered_project_executable()
    baseline_processes = headless_com.list_winproj_processes()
    baseline_identities = {
        (
            int(item["pid"]),
            item.get("creation_time_100ns")
            if isinstance(item.get("creation_time_100ns"), int)
            else None,
        )
        for item in baseline_processes
        if isinstance(item.get("pid"), int)
    }
    command = [
        sys.executable,
        "-B",
        "-X",
        f"pycache_prefix={pycache_prefix}",
        "-m",
        "deterministic_scheduling_core.native.msproject.headless_worker",
        "--worker",
        operation,
        "--repository-root",
        str(repository_root),
        "--run-id",
        run_id,
        "--workspace",
        str(workspace),
        "--result",
        str(result_path),
        "--state",
        str(state_path),
        "--log",
        str(log_path),
    ]
    if case_id:
        command.extend(("--case", case_id))
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
        process = subprocess.Popen(
            command,
            cwd=repository_root,
            stdout=stdout,
            stderr=stderr,
            creationflags=creationflags,
        )
        sequence = -1
        stage_started = time.monotonic()
        current_stage = "worker"
        latest_new_processes: list[dict[str, Any]] = []
        latest_verified_identities: list[dict[str, Any]] = []
        stopped: dict[str, Any] | None = None
        while process.poll() is None:
            state = _safe_state(state_path)
            if state:
                try:
                    observed_sequence = int(state["sequence"])
                    observed_stage = state["stage"]
                    observed_phase = state["phase"]
                    if not isinstance(observed_stage, str) or not isinstance(
                        observed_phase, str
                    ):
                        raise TypeError("stage and phase must be strings")
                except (KeyError, TypeError, ValueError) as error:
                    stopped = {
                        "schema_version": "headless-msproject-watchdog-stop-v0.1",
                        "characterisation_label": TRACK_ID,
                        "classification": "characterisation_inconclusive",
                        "condition": "invalid_worker_stage_state",
                        "operation": operation,
                        "case_id": case_id,
                        "stage": current_stage,
                        "error": f"{type(error).__name__}: {error}",
                        "recorded_at": _now(),
                    }
                    break
                if observed_sequence != sequence:
                    sequence = observed_sequence
                    current_stage = observed_stage
                    if observed_phase in {"start", "started"}:
                        stage_started = time.monotonic()
            try:
                latest_new_processes = _matching_new_project_processes(
                    headless_com.list_winproj_processes(),
                    baseline_identities=baseline_identities,
                    expected_path=executable,
                )
                latest_verified_identities = _verified_owned_identities(
                    log_path,
                    new_processes=latest_new_processes,
                    expected_path=executable,
                )
            except Exception as error:
                stopped = {
                    "schema_version": "headless-msproject-watchdog-stop-v0.1",
                    "characterisation_label": TRACK_ID,
                    "classification": "characterisation_inconclusive",
                    "condition": "project_process_enumeration_failure",
                    "operation": operation,
                    "case_id": case_id,
                    "stage": current_stage,
                    "error": f"{type(error).__name__}: {error}",
                    "recorded_at": _now(),
                }
                break
            exact_path_processes = _queryable_exact_path_processes(
                latest_new_processes
            )
            if len(exact_path_processes) > 1:
                verified_keys = {
                    (
                        int(identity["pid"]),
                        int(identity["creation_time_100ns"]),
                    )
                    for identity in latest_verified_identities
                }
                unverified_exact_path_processes = [
                    item
                    for item in exact_path_processes
                    if (
                        int(item["pid"]),
                        int(item["creation_time_100ns"]),
                    )
                    not in verified_keys
                ]
                stopped = {
                    "schema_version": "headless-msproject-watchdog-stop-v0.1",
                    "characterisation_label": TRACK_ID,
                    "classification": "characterisation_inconclusive",
                    "condition": "multiple_project_process_identities",
                    "operation": operation,
                    "case_id": case_id,
                    "stage": current_stage,
                    "expected_project_executable": str(executable),
                    "processes": _window_inventory(exact_path_processes),
                    "all_new_project_processes": _window_inventory(
                        latest_new_processes
                    ),
                    "verified_owned_project_identities": latest_verified_identities,
                    "unverified_exact_path_project_processes": _window_inventory(
                        unverified_exact_path_processes
                    ),
                    "recorded_at": _now(),
                }
                break
            identity_query_failures = [
                item
                for item in latest_new_processes
                if item.get("identity_query_failures")
            ]
            if identity_query_failures:
                stopped = {
                    "schema_version": "headless-msproject-watchdog-stop-v0.1",
                    "characterisation_label": TRACK_ID,
                    "classification": "characterisation_inconclusive",
                    "condition": "project_process_identity_query_failure",
                    "operation": operation,
                    "case_id": case_id,
                    "stage": current_stage,
                    "processes": _window_inventory(identity_query_failures),
                    "recorded_at": _now(),
                }
                break
            identity_mismatches = [
                item
                for item in latest_new_processes
                if item.get("identity_mismatch")
            ]
            if identity_mismatches:
                stopped = {
                    "schema_version": "headless-msproject-watchdog-stop-v0.1",
                    "characterisation_label": TRACK_ID,
                    "classification": "characterisation_inconclusive",
                    "condition": "project_process_identity_mismatch",
                    "operation": operation,
                    "case_id": case_id,
                    "stage": current_stage,
                    "expected_project_executable": str(executable),
                    "processes": _window_inventory(identity_mismatches),
                    "recorded_at": _now(),
                }
                break
            for owned_identity in latest_verified_identities:
                try:
                    visible = [
                        item
                        for item in headless_com.windows_for_pid(
                            int(owned_identity["pid"])
                        )
                        if item.get("visible")
                    ]
                except Exception as error:
                    stopped = {
                        "schema_version": "headless-msproject-watchdog-stop-v0.1",
                        "characterisation_label": TRACK_ID,
                        "classification": "characterisation_inconclusive",
                        "condition": "project_window_enumeration_failure",
                        "operation": operation,
                        "case_id": case_id,
                        "stage": current_stage,
                        "project_process_identity": owned_identity,
                        "error": f"{type(error).__name__}: {error}",
                        "recorded_at": _now(),
                    }
                    break
                if visible:
                    stopped = {
                        "schema_version": "headless-msproject-watchdog-stop-v0.1",
                        "characterisation_label": TRACK_ID,
                        "classification": "characterisation_inconclusive",
                        "condition": "unexpected_visible_window_or_dialog",
                        "operation": operation,
                        "case_id": case_id,
                        "stage": current_stage,
                        "project_pid": owned_identity["pid"],
                        "project_process_identity": owned_identity,
                        "project_windows": visible,
                        "recorded_at": _now(),
                    }
                    break
            if stopped is not None:
                break
            timeout = int(timeouts.get(current_stage, timeouts.get("worker", 30)))
            if time.monotonic() - stage_started >= timeout:
                stopped = {
                    "schema_version": "headless-msproject-watchdog-stop-v0.1",
                    "characterisation_label": TRACK_ID,
                    "classification": "characterisation_inconclusive",
                    "condition": "timeout",
                    "operation": operation,
                    "case_id": case_id,
                    "stage": current_stage,
                    "timeout_seconds": timeout,
                    "baseline_project_processes": baseline_processes,
                    "new_project_processes": _window_inventory(
                        latest_new_processes
                    ),
                    "verified_owned_project_identities": latest_verified_identities,
                    "recorded_at": _now(),
                }
                break
            time.sleep(0.1)
        if stopped is not None:
            _terminate_worker(process)
            try:
                latest_new_processes = _matching_new_project_processes(
                    headless_com.list_winproj_processes(),
                    baseline_identities=baseline_identities,
                    expected_path=executable,
                )
                latest_verified_identities = _verified_owned_identities(
                    log_path,
                    new_processes=latest_new_processes,
                    expected_path=executable,
                )
            except Exception as error:
                stopped["cleanup_enumeration_error"] = (
                    f"{type(error).__name__}: {error}"
                )
            cleanup_attempts: list[dict[str, Any]] = []
            for identity in latest_verified_identities:
                attempt = {
                    "pid": identity["pid"],
                    "forced_termination_attempted": True,
                }
                try:
                    attempt["terminated"] = bool(
                        headless_com.terminate_verified_project_process(
                            int(identity["pid"]),
                            executable,
                            process_identity=identity,
                        )
                    )
                except Exception as error:
                    attempt["terminated"] = False
                    attempt["error"] = f"{type(error).__name__}: {error}"
                cleanup_attempts.append(attempt)
            stopped["new_project_processes_after_worker_stop"] = _window_inventory(
                latest_new_processes
            )
            stopped["verified_owned_project_identities_after_worker_stop"] = (
                latest_verified_identities
            )
            durable_write_canonical_json(
                workspace / f"{operation}-watchdog-stop.json", stopped
            )
            durable_write_canonical_json(
                workspace / f"{operation}-watchdog-cleanup.json",
                {
                    "schema_version": "headless-msproject-watchdog-cleanup-v0.1",
                    "operation": operation,
                    "case_id": case_id,
                    "only_fully_verified_new_processes_were_eligible": True,
                    "attempts": cleanup_attempts,
                    "recorded_at": _now(),
                },
            )
            raise SupervisionError(
                f"{operation} stopped at {current_stage}: {stopped['condition']}"
            )
        return_code = process.wait()
    remaining_new = _matching_new_project_processes(
        headless_com.list_winproj_processes(),
        baseline_identities=baseline_identities,
        expected_path=executable,
    )
    remaining_owned = _verified_owned_identities(
        log_path, new_processes=remaining_new, expected_path=executable
    )
    if remaining_owned:
        cleanup_attempts: list[dict[str, Any]] = []
        for identity in remaining_owned:
            attempt = {"pid": identity["pid"], "forced_termination_attempted": True}
            try:
                attempt["terminated"] = bool(
                    headless_com.terminate_verified_project_process(
                        int(identity["pid"]),
                        executable,
                        process_identity=identity,
                    )
                )
            except Exception as error:
                attempt["terminated"] = False
                attempt["error"] = f"{type(error).__name__}: {error}"
            cleanup_attempts.append(attempt)
        durable_write_canonical_json(
            workspace / f"{operation}-process-leak-cleanup.json",
            {
                "schema_version": "headless-msproject-process-leak-cleanup-v0.1",
                "operation": operation,
                "case_id": case_id,
                "only_fully_verified_new_processes_were_eligible": True,
                "attempts": cleanup_attempts,
                "recorded_at": _now(),
            },
        )
        raise SupervisionError(
            f"{operation} left verified owned Project processes running: "
            f"{_window_inventory(remaining_new)}"
        )
    if remaining_new:
        durable_write_canonical_json(
            workspace / f"{operation}-unverified-project-process.json",
            {
                "schema_version": "headless-msproject-unverified-process-v0.1",
                "operation": operation,
                "case_id": case_id,
                "classification": "characterisation_inconclusive",
                "forced_termination_attempted": False,
                "reason": "new exact-path WINPROJ process lacked full ownership identity",
                "processes": _window_inventory(remaining_new),
                "recorded_at": _now(),
            },
        )
        raise SupervisionError(
            f"{operation} left an unverified new Project process; it was not terminated"
        )
    if return_code != 0:
        message = stderr_path.read_text(encoding="utf-8", errors="replace").strip()
        raise SupervisionError(f"{operation} worker failed ({return_code}): {message}")
    if not result_path.is_file():
        raise SupervisionError(f"{operation} worker did not write its result")
    result, result_snapshot = _read_canonical_json_object_snapshot(
        result_path,
        label=f"{operation} native worker result",
        max_bytes=MAX_NATIVE_RESULT_BYTES,
    )
    terminal_digest = _read_native_worker_terminal_digest(
        state_path=state_path,
        log_path=log_path,
        operation=operation,
        run_id=run_id,
        case_id=case_id,
        worker_pid=process.pid,
    )
    if result_snapshot.sha256 != terminal_digest:
        raise SupervisionError(
            "native worker terminal journal digest does not authenticate the stable result snapshot"
        )
    _write_result_sidecar(result_path, result_sha256=result_snapshot.sha256)
    return result


def run_comparison_worker(
    *,
    repository_root: Path,
    run_id: str,
    workspace: Path,
    result_path: Path,
    timeout_seconds: int = COMPARISON_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Run the oracle-capable comparator separately with no COM imports or invocation."""

    workspace.mkdir(parents=True, exist_ok=True)
    state_path = workspace / "comparison-stage-state.json"
    log_path = workspace / "comparison-log.jsonl"
    stdout_path = workspace / "comparison-worker-stdout.log"
    stderr_path = workspace / "comparison-worker-stderr.log"
    result_sidecar_path = _result_sidecar_path(result_path)
    pycache_prefix = workspace / (
        f"comparison-import-pycache-{secrets.token_hex(16)}"
    )
    for path in (
        state_path,
        log_path,
        stdout_path,
        stderr_path,
        result_path,
        result_sidecar_path,
    ):
        if path.exists():
            raise SupervisionError(f"refusing to overwrite comparison evidence: {path}")
    if pycache_prefix.exists():
        raise SupervisionError(
            f"comparison pycache prefix must be fresh and nonexistent: {pycache_prefix}"
        )
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
        source_snapshots = {}
        try:
            for source_role, spec in ORACLE_SOURCE_SPECS.items():
                source_snapshots[source_role] = read_regular_file_snapshot(
                    repository_root / spec["relative_path"],
                    label=f"prelaunch oracle source {source_role}",
                    max_bytes=MAX_COMPARATOR_SOURCE_BYTES,
                )
        except (OSError, NativeEvidenceError) as error:
            raise SupervisionError(
                "oracle source bundle could not be captured before launch"
            ) from error
        expected_source_bundle_json = json.dumps(
            {
                source_role: snapshot.sha256
                for source_role, snapshot in source_snapshots.items()
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        command = [
            sys.executable,
            "-B",
            "-X",
            f"pycache_prefix={pycache_prefix}",
            "-m",
            "deterministic_scheduling_core.native.msproject.headless_compare",
            "--repository-root",
            str(repository_root),
            "--run-id",
            run_id,
            "--expected-source-bundle-json",
            expected_source_bundle_json,
            "--result",
            str(result_path),
            "--state",
            str(state_path),
            "--log",
            str(log_path),
        ]
        process = subprocess.Popen(
            command,
            cwd=repository_root,
            stdout=stdout,
            stderr=stderr,
            creationflags=creationflags,
        )
        try:
            return_code = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            _terminate_worker(process)
            durable_write_canonical_json(
                workspace / "comparison-watchdog-stop.json",
                {
                    "schema_version": "headless-msproject-comparison-stop-v0.1",
                    "characterisation_label": TRACK_ID,
                    "classification": "characterisation_inconclusive",
                    "condition": "timeout",
                    "timeout_seconds": timeout_seconds,
                    "com_code_path_invoked": False,
                    "recorded_at": _now(),
                },
            )
            raise SupervisionError(
                f"comparison worker exceeded {timeout_seconds} seconds"
            ) from None
    if return_code != 0:
        message = stderr_path.read_text(encoding="utf-8", errors="replace").strip()
        raise SupervisionError(
            f"comparison worker failed ({return_code}): {message}"
        )
    result, result_snapshot = _read_canonical_json_object_snapshot(
        result_path,
        label="comparison result",
        max_bytes=MAX_COMPARISON_RESULT_BYTES,
    )
    terminal_digest = _read_comparison_terminal_digest(
        state_path=state_path,
        log_path=log_path,
        run_id=run_id,
        worker_pid=process.pid,
    )
    if result_snapshot.sha256 != terminal_digest:
        raise SupervisionError(
            "comparison terminal journal digest does not authenticate the stable result snapshot"
        )
    provenance = result.get("oracle_provenance")
    source_bundle = (
        provenance.get("source_bundle")
        if isinstance(provenance, Mapping)
        else None
    )
    if (
        not isinstance(source_bundle, Mapping)
        or set(source_bundle) != set(ORACLE_SOURCE_SPECS)
        or any(
            not isinstance(source_bundle.get(source_role), Mapping)
            or set(source_bundle[source_role])
            != {"module", "relative_path", "sha256"}
            or source_bundle[source_role].get("module") != spec["module"]
            or source_bundle[source_role].get("relative_path")
            != spec["relative_path"]
            or source_bundle[source_role].get("sha256")
            != source_snapshots[source_role].sha256
            for source_role, spec in ORACLE_SOURCE_SPECS.items()
        )
    ):
        raise SupervisionError(
            "comparison result oracle source provenance differs from the prelaunch snapshots"
        )
    _write_result_sidecar(result_path, result_sha256=result_snapshot.sha256)
    return result


def _automation_hashes(repository_root: Path) -> dict[str, str]:
    paths = {
        "automation_tool_sha256": Path(__file__).resolve(),
        "headless_core_sha256": Path(headless.__file__).resolve(),
        "headless_com_sha256": Path(headless_com.__file__).resolve(),
        "headless_worker_sha256": Path(
            sys.modules.get(
                "deterministic_scheduling_core.native.msproject.headless_worker",
                type("Missing", (), {"__file__": repository_root / "src/deterministic_scheduling_core/native/msproject/headless_worker.py"}),
            ).__file__
        ).resolve(),
        "canonical_json_sha256": Path(canonical_json_module.__file__).resolve(),
        "freeze_sha256": Path(native_freeze.__file__).resolve(),
    }
    if not paths["headless_worker_sha256"].is_file():
        paths["headless_worker_sha256"] = repository_root / "src/deterministic_scheduling_core/native/msproject/headless_worker.py"
    return {role: sha256_file(path) for role, path in paths.items()}


def _result_sidecar_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.sha256")


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and value == value.lower()
        and all(character in "0123456789abcdef" for character in value)
    )


def _write_result_sidecar(
    path: Path, *, result_sha256: str | None = None
) -> None:
    digest = sha256_file(path) if result_sha256 is None else result_sha256
    if not _is_sha256(digest):
        raise SupervisionError(f"result digest is malformed: {path}")
    headless.durable_write_bytes(
        _result_sidecar_path(path), f"{digest}\n".encode("ascii")
    )


def _verify_result_sidecar(path: Path) -> None:
    sidecar = _result_sidecar_path(path)
    if not path.is_file() or not sidecar.is_file():
        raise SupervisionError(f"cached result is not hash-bound: {path}")
    recorded = sidecar.read_text(encoding="ascii")
    if recorded != f"{sha256_file(path)}\n":
        raise SupervisionError(f"cached result digest mismatch: {path}")


def _clean_process_sessions(value: Any, *, label: str) -> None:
    try:
        conditions = headless.effective_stop_conditions(
            {
                "schema_version": "headless-msproject-native-observation-v0.2",
                "stop_conditions": [],
                "process_sessions": value,
            }
        )
    except ObservationFreezeError as error:
        raise SupervisionError(f"{label} process evidence is malformed: {error}") from error
    if not isinstance(value, list) or not value or conditions:
        raise SupervisionError(f"{label} process cleanup is incomplete: {conditions}")


def _validate_environment_capture(environment: Mapping[str, Any]) -> None:
    if environment.get("schema_version") != "headless-msproject-environment-v0.1":
        raise SupervisionError("environment capture has an unexpected schema")
    product = environment.get("microsoft_project")
    executable = environment.get("project_executable")
    cleanup = environment.get("project_process_cleanup")
    time_zone = environment.get("time_zone")
    if not isinstance(product, Mapping) or not isinstance(executable, Mapping):
        raise SupervisionError("environment capture lacks Project identity")
    if (
        product.get("com_prog_id") != "MSProject.Application"
        or product.get("visible") is not False
        or not isinstance(product.get("process_id"), int)
        or isinstance(product.get("process_id"), bool)
        or not all(product.get(key) not in (None, "") for key in ("name", "version", "build"))
    ):
        raise SupervisionError("environment capture has invalid COM process identity")
    if (
        not isinstance(cleanup, Mapping)
        or cleanup.get("exited") is not True
        or cleanup.get("forced_termination") is not False
        or cleanup.get("ownership_revalidated_before_quit") is not True
        or cleanup.get("termination_error") not in (None, "")
    ):
        raise SupervisionError("environment Project process did not quit cleanly")
    if (
        not isinstance(time_zone, Mapping)
        or time_zone.get("windows_name") != "W. Australia Standard Time"
        or time_zone.get("utc_offset") != "+08:00"
        or time_zone.get("matches_required_perth_zone") is not True
    ):
        raise SupervisionError("environment capture is not the required Perth time zone")
    live_time_zone = headless_com._capture_windows_time_zone()
    if live_time_zone.get("matches_required_perth_zone") is not True:
        raise SupervisionError("live Windows time zone changed from the required Perth zone")
    recorded_path = executable.get("path")
    recorded_sha = executable.get("sha256")
    if not isinstance(recorded_path, str) or not isinstance(recorded_sha, str):
        raise SupervisionError("environment executable identity is incomplete")
    live_executable = headless_com.registered_project_executable().resolve()
    if Path(recorded_path).resolve() != live_executable:
        raise SupervisionError("registered Project executable changed after environment capture")
    live_sha = sha256_file(live_executable)
    if live_sha.lower() != recorded_sha.lower():
        raise SupervisionError("live Project executable hash differs from environment capture")
    if product.get("process_executable") and (
        Path(str(product["process_executable"])).resolve() != live_executable
    ):
        raise SupervisionError("COM process executable differs from registered Project executable")


def _validated_reported_artifacts(
    value: Any,
    *,
    workspace: Path,
    expected_roles: frozenset[str],
    label: str,
) -> dict[str, Path]:
    """Require an exact, contained set of non-symlink native artifacts."""

    if not isinstance(value, Mapping) or set(value) != set(expected_roles):
        raise SupervisionError(
            f"{label} must report exactly these artifact roles: "
            f"{sorted(expected_roles)}"
        )
    root = workspace.resolve(strict=True)
    validated: dict[str, Path] = {}
    for role in sorted(expected_roles):
        raw_path = value.get(role)
        if not isinstance(raw_path, str) or not raw_path:
            raise SupervisionError(f"{label} artifact {role} has no path")
        supplied = Path(raw_path)
        try:
            metadata = supplied.lstat()
            resolved = supplied.resolve(strict=True)
            resolved.relative_to(root)
        except (FileNotFoundError, OSError, RuntimeError, ValueError) as error:
            raise SupervisionError(
                f"{label} artifact {role} is missing or escapes its workspace"
            ) from error
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise SupervisionError(
                f"{label} artifact {role} must be a non-symlink regular file"
            )
        if metadata.st_size <= 0:
            raise SupervisionError(f"{label} artifact {role} is empty")
        validated[role] = resolved
    return validated


def _result_artifact_manifest_path(result_path: Path) -> Path:
    return result_path.with_name(f"{result_path.stem}-artifact-manifest.json")


def _write_result_artifact_manifest(
    result_path: Path,
    *,
    workspace: Path,
    artifacts: Mapping[str, Path],
) -> None:
    manifest_path = _result_artifact_manifest_path(result_path)
    digest = headless.write_artifact_manifest(
        manifest_path,
        {"result": result_path, **artifacts},
        root=workspace,
    )
    headless.durable_write_bytes(
        manifest_path.with_suffix(manifest_path.suffix + ".sha256"),
        f"{digest}\n".encode("ascii"),
    )


def _verify_result_artifact_manifest(
    result_path: Path,
    *,
    workspace: Path,
    artifacts: Mapping[str, Path],
) -> None:
    manifest_path = _result_artifact_manifest_path(result_path)
    sidecar_path = manifest_path.with_suffix(manifest_path.suffix + ".sha256")
    try:
        recorded_digest = sidecar_path.read_text(encoding="ascii").strip()
    except (FileNotFoundError, OSError, UnicodeDecodeError) as error:
        raise SupervisionError(
            f"retained artifact manifest sidecar is missing: {sidecar_path}"
        ) from error
    if recorded_digest != sha256_file(manifest_path):
        raise SupervisionError(
            f"retained artifact manifest digest mismatch: {manifest_path}"
        )
    try:
        manifest = headless.verify_artifact_manifest(manifest_path, root=workspace)
    except headless.DurableEvidenceError as error:
        raise SupervisionError(
            f"retained result artifact verification failed: {result_path}"
        ) from error
    entries = manifest.get("artifacts")
    if not isinstance(entries, list):
        raise SupervisionError(
            f"retained result artifact roles are incomplete: {result_path}"
        )
    root = workspace.resolve(strict=True)
    expected_paths = {
        role: path.resolve(strict=True).relative_to(root).as_posix()
        for role, path in {"result": result_path, **artifacts}.items()
    }
    observed_paths = {
        str(item.get("role")): item.get("relative_path")
        for item in entries
        if isinstance(item, Mapping)
    }
    if observed_paths != expected_paths:
        raise SupervisionError(
            f"retained result artifact roles or paths are incomplete: {result_path}"
        )


def _validate_preflight_capture(
    preflight: Mapping[str, Any], *, workspace: Path
) -> dict[str, Path]:
    if (
        preflight.get("schema_version") != "headless-msproject-preflight-v0.1"
        or preflight.get("characterisation_label") != TRACK_ID
    ):
        raise SupervisionError("headless preflight has an unexpected identity or schema")
    required_operations = preflight.get("required_operations")
    if (
        not isinstance(required_operations, Mapping)
        or set(required_operations) != PREFLIGHT_REQUIRED_OPERATIONS
        or any(value is not True for value in required_operations.values())
    ):
        raise SupervisionError("headless preflight did not verify the exact required operations")
    observed_time_zone = preflight.get("observed_time_zone")
    if (
        not isinstance(observed_time_zone, Mapping)
        or observed_time_zone.get("windows_name") != "W. Australia Standard Time"
        or observed_time_zone.get("utc_offset") != "+08:00"
        or observed_time_zone.get("matches_required_perth_zone") is not True
    ):
        raise SupervisionError("headless preflight did not retain the required Perth time zone")
    _clean_process_sessions(preflight.get("process_sessions"), label="preflight")
    if not isinstance(preflight.get("xml_observation"), Mapping):
        raise SupervisionError("headless preflight lacks XML or artifact evidence")
    return _validated_reported_artifacts(
        preflight.get("artifact_paths"),
        workspace=workspace,
        expected_roles=CASE_NATIVE_ARTIFACT_ROLES,
        label="headless preflight",
    )


def _ensure_environment_and_preflight(
    run: headless.RunWorkspace, *, resume_existing: bool = False
) -> tuple[dict[str, Any], dict[str, Any]]:
    # This read-only OS gate deliberately precedes environment capture because
    # capture itself starts Project to query independent COM product identity.
    _require_live_perth_time_zone()
    environment_path = run.path / "environment.json"
    preflight_path = run.path / "preflight" / "preflight.json"
    if environment_path.exists():
        if resume_existing:
            _verify_result_sidecar(environment_path)
        environment = _read_json(environment_path)
    else:
        if resume_existing:
            raise SupervisionError("resume requires retained hash-bound environment evidence")
        environment = run_supervised_worker(
            operation="environment",
            repository_root=run.repository_root,
            run_id=run.run_id,
            workspace=run.path / "environment-operation",
            result_path=environment_path,
        )
        _validate_environment_capture(environment)
    _validate_environment_capture(environment)
    if preflight_path.exists():
        if resume_existing:
            _verify_result_sidecar(preflight_path)
        preflight = _read_json(preflight_path)
    else:
        if resume_existing:
            raise SupervisionError("resume requires retained hash-bound preflight evidence")
        preflight = run_supervised_worker(
            operation="preflight",
            repository_root=run.repository_root,
            run_id=run.run_id,
            workspace=run.path / "preflight",
            result_path=preflight_path,
        )
        preflight_artifacts = _validate_preflight_capture(
            preflight, workspace=preflight_path.parent
        )
        _write_result_artifact_manifest(
            preflight_path,
            workspace=preflight_path.parent,
            artifacts=preflight_artifacts,
        )
    preflight_artifacts = _validate_preflight_capture(
        preflight, workspace=preflight_path.parent
    )
    if resume_existing:
        _verify_result_artifact_manifest(
            preflight_path,
            workspace=preflight_path.parent,
            artifacts=preflight_artifacts,
        )
    return environment, preflight


def _case_artifacts(observation: Mapping[str, Any], workspace: Path) -> dict[str, Path]:
    artifacts = _validated_reported_artifacts(
        observation.get("artifacts"),
        workspace=workspace,
        expected_roles=CASE_NATIVE_ARTIFACT_ROLES,
        label="native case",
    )
    support = {
        "worker_result": workspace / "worker-native-result.json",
        "com_log": workspace / "case-com-log.jsonl",
        "stage_state": workspace / "case-stage-state.json",
        "worker_stdout": workspace / "case-worker-stdout.log",
        "worker_stderr": workspace / "case-worker-stderr.log",
    }
    root = workspace.resolve(strict=True)
    for role, path in support.items():
        try:
            metadata = path.lstat()
            resolved = path.resolve(strict=True)
            resolved.relative_to(root)
        except (FileNotFoundError, OSError, RuntimeError, ValueError) as error:
            raise SupervisionError(f"native case support artifact is missing: {role}") from error
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise SupervisionError(
                f"native case support artifact must be a regular file: {role}"
            )
        artifacts[role] = resolved
    return artifacts


def _verify_case_manifest_roles(workspace: headless.CaseWorkspace) -> None:
    manifest = _read_json(workspace.path / "case-manifest.json")
    entries = manifest.get("artifacts")
    if not isinstance(entries, list):
        raise SupervisionError(
            f"{workspace.case_id} manifest has no artifact inventory"
        )
    roles = {item.get("role") for item in entries if isinstance(item, Mapping)}
    expected = {
        "native_observation",
        *CASE_NATIVE_ARTIFACT_ROLES,
        *CASE_SUPPORT_ARTIFACT_ROLES,
    }
    if roles != expected:
        raise SupervisionError(
            f"{workspace.case_id} manifest does not bind the exact required artifacts"
        )


def _reject_stop_conditions(
    observation: Mapping[str, Any], *, case_id: str, resumed: bool
) -> None:
    """Require an explicit empty native stop-condition list.

    In particular, a hash-valid frozen observation is not resumable when the
    native worker retained a type/lag/mode/dialog/process stop.  This check is
    intentionally performed before a run freeze gate or comparator spawn.
    """

    context = "resumed " if resumed else ""
    try:
        conditions = headless.effective_stop_conditions(observation)
    except ObservationFreezeError as error:
        raise SupervisionError(
            f"{context}{case_id} observation has malformed stop evidence: {error}"
        ) from error
    if conditions:
        raise SupervisionError(
            f"{context}{case_id} retained native stop conditions: {conditions}"
        )


def _reject_run_stop_conditions(
    observations: Mapping[str, Mapping[str, Any]], *, resumed: bool
) -> None:
    for case_id in CASE_IDS:
        observation = observations.get(case_id)
        if observation is not None:
            _reject_stop_conditions(
                observation, case_id=case_id, resumed=resumed
            )


def _resume_existing_cases(
    run: headless.RunWorkspace,
    environment: Mapping[str, Any],
    *,
    selected_case_id: str | None = None,
) -> dict[str, Mapping[str, Any]]:
    """Verify retained cases and shared identity before any new launch.

    Batch resumes require the retained workspaces to be a canonical prefix.
    A standalone resume is intentionally scoped to its selected case and
    rejects any unrelated retained case workspace.
    """

    if selected_case_id is not None and selected_case_id not in CASE_IDS:
        raise SupervisionError(
            f"standalone resume selected an unknown case: {selected_case_id}"
        )
    _validate_environment_capture(environment)
    cases_root = run.path / "cases"
    if not cases_root.exists():
        return {}
    unexpected = sorted(
        path.name
        for path in cases_root.iterdir()
        if path.is_dir() and path.name not in CASE_IDS
    )
    if unexpected:
        raise SupervisionError(f"resume contains unexpected case workspaces: {unexpected}")
    existing_case_ids = [
        case_id for case_id in CASE_IDS if (cases_root / case_id).is_dir()
    ]
    if selected_case_id is None:
        expected_prefix = list(CASE_IDS[: len(existing_case_ids)])
        if existing_case_ids != expected_prefix:
            raise SupervisionError(
                "resume case workspaces must form an exact canonical prefix; "
                f"found={existing_case_ids}, expected={expected_prefix}"
            )
    else:
        unrelated = [
            case_id for case_id in existing_case_ids if case_id != selected_case_id
        ]
        if unrelated:
            raise SupervisionError(
                "standalone resume contains unrelated case workspaces; "
                f"selected={selected_case_id}, unrelated={unrelated}"
            )
    current_automation = _automation_hashes(run.repository_root)
    expected_common = {
        **current_automation,
        "environment_sha256": sha256_file(run.path / "environment.json"),
        "project_executable_sha256": str(
            environment["project_executable"]["sha256"]
        ).lower(),
    }
    observations: dict[str, Mapping[str, Any]] = {}
    for case_id in CASE_IDS:
        case_path = cases_root / case_id
        if not case_path.exists():
            continue
        observation_path = case_path / "native-observation.json"
        if not observation_path.is_file():
            raise SupervisionError(
                f"resume case workspace is incomplete before native launch: {case_path}"
            )
        workspace = create_case_workspace(run, case_id, resume=True)
        observation = _read_json(observation_path)
        _reject_stop_conditions(observation, case_id=case_id, resumed=True)
        verify_observation_freeze(workspace)
        _verify_case_manifest_roles(workspace)
        manifest = _read_json(case_path / "case-manifest.json")
        shared = manifest.get("shared_hashes")
        if not isinstance(shared, Mapping) or any(
            str(shared.get(role, "")).lower() != digest.lower()
            for role, digest in expected_common.items()
        ):
            raise SupervisionError(
                f"resume {case_id} is bound to stale environment or automation identity"
            )
        normalize_observation(observation)
        observations[case_id] = observation
    return observations


def _run_one_case(
    run: headless.RunWorkspace,
    case_id: str,
    environment: Mapping[str, Any],
    *,
    resume_existing: bool,
) -> dict[str, Any]:
    case_path = run.path / "cases" / case_id
    if case_path.exists():
        if not resume_existing:
            raise SupervisionError(f"case workspace already exists: {case_path}")
        workspace = create_case_workspace(run, case_id, resume=True)
        observation = _read_json(workspace.path / "native-observation.json")
        _reject_stop_conditions(observation, case_id=case_id, resumed=True)
        verify_observation_freeze(workspace)
        _verify_case_manifest_roles(workspace)
        normalize_observation(observation)
        return observation
    _validate_environment_capture(environment)
    environment_digest_before = sha256_file(run.path / "environment.json")
    workspace = create_case_workspace(run, case_id)
    automation_hashes_before = _automation_hashes(run.repository_root)
    _projection, source_digest_before = load_source_only_projection_with_identity(
        run.repository_root, case_id
    )
    result_path = workspace.path / "worker-native-result.json"
    observation = run_supervised_worker(
        operation="case",
        repository_root=run.repository_root,
        run_id=run.run_id,
        workspace=workspace.path,
        result_path=result_path,
        case_id=case_id,
    )
    _projection_after, source_digest_after = load_source_only_projection_with_identity(
        run.repository_root, case_id
    )
    automation_hashes_after = _automation_hashes(run.repository_root)
    _validate_environment_capture(environment)
    environment_digest_after = sha256_file(run.path / "environment.json")
    worker_source_digest = observation.get("source_projection_sha256")
    if not (
        isinstance(worker_source_digest, str)
        and worker_source_digest == source_digest_before == source_digest_after
    ):
        raise SupervisionError(
            f"{case_id} source projection changed or was not bound by the native worker"
        )
    if not (
        isinstance(observation.get("automation_source_hashes"), Mapping)
        and dict(observation["automation_source_hashes"])
        == automation_hashes_before
        == automation_hashes_after
    ):
        raise SupervisionError(
            f"{case_id} automation sources changed or were not bound by the native worker"
        )
    if environment_digest_before != environment_digest_after:
        raise SupervisionError(
            f"{case_id} environment evidence changed during native construction"
        )
    shared_hashes = {
        **automation_hashes_after,
        "environment_sha256": environment_digest_after,
        "project_executable_sha256": str(environment["project_executable"]["sha256"]).lower(),
        "source_only_projection_sha256": source_digest_after,
    }
    freeze_native_observation(
        workspace,
        observation,
        _case_artifacts(observation, workspace.path),
        shared_hashes=shared_hashes,
    )
    normalize_observation(observation)
    _reject_stop_conditions(observation, case_id=case_id, resumed=False)
    return observation


def _claimed_projection(observation: Mapping[str, Any], key: str) -> dict[str, Any]:
    capture = observation[key]
    return {
        "tasks": {
            item["name"]: {"start": item["start"], "finish": item["finish"]}
            for item in capture["tasks"]
            if item.get("name") in {"A", "B"}
        },
        "project_finish": capture["project"]["finish"],
    }


def _reopen_result(observation: Mapping[str, Any]) -> dict[str, Any]:
    before = _claimed_projection(observation, "initial_calculated")
    after_open = _claimed_projection(observation, "reopen_after_open")
    after_recalculate = _claimed_projection(observation, "reopen_after_recalculate")
    changes = []
    for label, candidate in (("after_open", after_open), ("after_explicit_recalculate", after_recalculate)):
        if candidate != before:
            changes.append({"stage": label, "before": before, "after": candidate})
    initial_links = [
        link
        for task in observation["initial_xml_observation"]["tasks"]
        for link in task["predecessor_links"]
    ]
    reopened_links = [
        link
        for task in observation["reopened_xml_observation"]["tasks"]
        for link in task["predecessor_links"]
    ]
    return {
        "case_id": observation["case_id"],
        "before_reopen": before,
        "after_open": after_open,
        "after_explicit_recalculate": after_recalculate,
        "claimed_field_changes": changes,
        "reopen_stable": not changes,
        "xml_relationship_preserved": initial_links == reopened_links and len(initial_links) == 1,
        "initial_xml_relationship": initial_links,
        "reopened_xml_relationship": reopened_links,
    }


def _raw_hash_inventory(run_path: Path) -> list[dict[str, Any]]:
    excluded = {"raw-artifact-hashes.json", "raw-artifact-hashes.sha256"}
    entries = []
    for path in sorted(run_path.rglob("*"), key=lambda item: item.as_posix()):
        if path.is_file() and path.name not in excluded:
            entries.append(
                {
                    "relative_path": path.relative_to(run_path).as_posix(),
                    "byte_size": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
    return entries


def _next_attempt_workspace(run_path: Path, stem: str) -> Path:
    primary = run_path / stem
    if not primary.exists():
        return primary
    for attempt in range(2, 1000):
        candidate = run_path / f"{stem}-attempt-{attempt:03d}"
        if not candidate.exists():
            return candidate
    raise SupervisionError(f"no unused {stem} attempt workspace remains")


def _existing_calendar_result(run_path: Path) -> tuple[Path, dict[str, Any]] | None:
    candidates = sorted(
        run_path.glob("calendar-characterisation*/calendar-characterisation.json"),
        key=lambda path: path.as_posix(),
    )
    if not candidates:
        return None
    path = candidates[-1]
    _verify_result_sidecar(path)
    result = _read_json(path)
    artifacts = _validate_calendar_result(result, workspace=path.parent)
    _verify_result_artifact_manifest(
        path, workspace=path.parent, artifacts=artifacts
    )
    return path, result


def _exact_wall_clock(value: Any, *, require_perth_offset: bool) -> str | None:
    """Return a canonical second-resolution wall clock without converting it."""

    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.microsecond != 0 or value != parsed.isoformat(timespec="seconds"):
        return None
    offset = parsed.utcoffset()
    if require_perth_offset:
        if offset != timedelta(hours=8):
            return None
    elif parsed.tzinfo is not None or offset is not None:
        return None
    return parsed.replace(tzinfo=None).isoformat(timespec="seconds")


def _calendar_schedule_projection(capture: Any) -> dict[str, Any] | None:
    """Return the exact claimed CAL task/project dates from a COM capture."""

    if not isinstance(capture, Mapping):
        return None
    project = capture.get("project")
    tasks = capture.get("tasks")
    if (
        not isinstance(project, Mapping)
        or not isinstance(project.get("start"), str)
        or not isinstance(project.get("finish"), str)
        or not isinstance(tasks, list)
        or len(tasks) != 1
        or not isinstance(tasks[0], Mapping)
        or tasks[0].get("name") != "CAL-24X7-characterisation"
        or not isinstance(tasks[0].get("start"), str)
        or not isinstance(tasks[0].get("finish"), str)
        or not isinstance(tasks[0].get("duration_minutes"), int)
        or isinstance(tasks[0].get("duration_minutes"), bool)
        or tasks[0].get("duration_minutes") != 1_440
    ):
        return None
    task = tasks[0]
    wall_clocks = [
        _exact_wall_clock(value, require_perth_offset=True)
        for value in (
            project["start"],
            project["finish"],
            task["start"],
            task["finish"],
        )
    ]
    if any(value is None for value in wall_clocks):
        return None
    return {
        "project": {
            "start": wall_clocks[0],
            "finish": wall_clocks[1],
        },
        "task": {
            "name": task["name"],
            "start": wall_clocks[2],
            "finish": wall_clocks[3],
            "duration_minutes": 1_440,
        },
    }


def _calendar_xml_schedule_projection(
    observation: Any,
) -> dict[str, Any] | None:
    """Return exact CAL project/task wall clocks from parsed bound XML bytes."""

    if not isinstance(observation, Mapping):
        return None
    project = observation.get("project")
    tasks = observation.get("tasks")
    matching_tasks = (
        [
            item
            for item in tasks
            if isinstance(item, Mapping)
            and item.get("name") == "CAL-24X7-characterisation"
        ]
        if isinstance(tasks, list)
        else []
    )
    if not isinstance(project, Mapping) or len(matching_tasks) != 1:
        return None
    task = matching_tasks[0]
    if task.get("duration") != "PT24H0M0S":
        return None
    wall_clocks = [
        _exact_wall_clock(value, require_perth_offset=False)
        for value in (
            project.get("start"),
            project.get("finish"),
            task.get("start"),
            task.get("finish"),
        )
    ]
    if any(value is None for value in wall_clocks):
        return None
    return {
        "project": {"start": wall_clocks[0], "finish": wall_clocks[1]},
        "task": {
            "name": "CAL-24X7-characterisation",
            "start": wall_clocks[2],
            "finish": wall_clocks[3],
            "duration_minutes": 1_440,
        },
    }


def _validate_calendar_result(
    calendar: Mapping[str, Any], *, workspace: Path
) -> dict[str, Path]:
    if (
        calendar.get("schema_version")
        != "headless-msproject-cal24x7-characterisation-v0.1"
        or calendar.get("characterisation_label") != TRACK_ID
        or calendar.get("automatic_track_c_unblock") is not False
        or calendar.get("calendar_representation_stable") is not True
    ):
        raise SupervisionError(
            "CAL-24X7 result is incomplete or attempts to alter the Track C blocker"
        )
    first_xml = calendar.get("project_authored_xml")
    second_xml = calendar.get("reexported_xml")
    if not isinstance(first_xml, Mapping) or not isinstance(second_xml, Mapping):
        raise SupervisionError("CAL-24X7 result lacks both XML observations")
    artifacts = _validated_reported_artifacts(
        calendar.get("artifacts"),
        workspace=workspace,
        expected_roles=CALENDAR_ARTIFACT_ROLES,
        label="CAL-24X7",
    )
    if (
        calendar.get("xml_reopen_method")
        != "Application.OpenXML(exact_exported_utf8_text)"
        or calendar.get("xml_reopen_source_sha256")
        != sha256_file(artifacts["authored_xml"])
    ):
        raise SupervisionError(
            "CAL-24X7 result does not bind the exact Project-authored XML reopen source"
        )
    try:
        parsed_first = headless.parse_project_xml_observation(
            artifacts["authored_xml"]
        )
        parsed_second = headless.parse_project_xml_observation(
            artifacts["reexported_xml"]
        )
        if parsed_first != first_xml or parsed_second != second_xml:
            raise SupervisionError(
                "CAL-24X7 inline XML observations disagree with bound artifacts"
            )
        first_calendar = headless.validated_cal24x7_calendar(first_xml)
        second_calendar = headless.validated_cal24x7_calendar(second_xml)
    except headless.XmlObservationError as error:
        raise SupervisionError(f"CAL-24X7 XML observation is invalid: {error}") from error
    if (
        first_calendar != second_calendar
        or calendar.get("calendar_representation_before") != first_calendar
        or calendar.get("calendar_representation_after") != second_calendar
    ):
        raise SupervisionError("CAL-24X7 cached representation is internally inconsistent")
    _clean_process_sessions(calendar.get("process_sessions"), label="CAL-24X7")
    captures = [
        calendar.get("task_dates_before_xml_reopen"),
        calendar.get("task_dates_after_xml_open"),
        calendar.get("task_dates_after_xml_recalculate"),
    ]
    if not all(isinstance(capture, Mapping) for capture in captures):
        raise SupervisionError("CAL-24X7 result lacks retained task-date or artifact evidence")
    projections = [_calendar_schedule_projection(capture) for capture in captures]
    if any(projection is None for projection in projections) or not (
        projections[0] == projections[1] == projections[2]
    ):
        raise SupervisionError(
            "CAL-24X7 task dates changed across XML reopen or explicit recalculation"
        )
    xml_projections = [
        _calendar_xml_schedule_projection(parsed_first),
        _calendar_xml_schedule_projection(parsed_second),
    ]
    if (
        any(projection is None for projection in xml_projections)
        or xml_projections[0] != projections[0]
        or xml_projections[1] != projections[2]
    ):
        raise SupervisionError(
            "CAL-24X7 exact XML/COM project or task wall clocks disagree"
        )
    return artifacts


def _validate_comparison_result(
    comparison: Mapping[str, Any], *, run_id: str
) -> None:
    if (
        comparison.get("schema_version") != "headless-msproject-comparison-v0.1"
        or comparison.get("characterisation_label") != TRACK_ID
        or comparison.get("run_id") != run_id
        or comparison.get("manual_native_semantic_parity_status_emitted") is not False
    ):
        raise SupervisionError("comparison has an invalid schema, identity or claim boundary")
    encoded_comparison = json.dumps(comparison, ensure_ascii=False, sort_keys=True)
    if "executed_pass" in encoded_comparison:
        raise SupervisionError("comparison attempted to emit a manual-track pass status")
    comparison_cases = comparison.get("cases")
    if not isinstance(comparison_cases, list) or [
        item.get("case_id") if isinstance(item, Mapping) else None
        for item in comparison_cases
    ] != list(CASE_IDS):
        raise SupervisionError(
            "comparison did not return twelve unique cases in canonical order"
        )
    provenance = comparison.get("oracle_provenance")
    source_bundle = (
        provenance.get("source_bundle")
        if isinstance(provenance, Mapping)
        else None
    )
    references = (
        provenance.get("sealed_references")
        if isinstance(provenance, Mapping)
        else None
    )
    expected_reference_paths = [
        f"{SEALED_REFERENCE_RELATIVE_DIRECTORY}/{case_id}.json"
        for case_id in CASE_IDS
    ]
    if (
        not isinstance(provenance, Mapping)
        or set(provenance) != {"schema_version", "source_bundle", "sealed_references"}
        or provenance.get("schema_version") != ORACLE_PROVENANCE_SCHEMA
        or not isinstance(source_bundle, Mapping)
        or set(source_bundle) != set(ORACLE_SOURCE_SPECS)
        or any(
            not isinstance(source_bundle.get(source_role), Mapping)
            or set(source_bundle[source_role]) != {"module", "relative_path", "sha256"}
            or source_bundle[source_role].get("module") != spec["module"]
            or source_bundle[source_role].get("relative_path") != spec["relative_path"]
            or not _is_sha256(source_bundle[source_role].get("sha256"))
            for source_role, spec in ORACLE_SOURCE_SPECS.items()
        )
        or not isinstance(references, list)
        or len(references) != len(CASE_IDS)
    ):
        raise SupervisionError(
            "comparison lacks exact oracle-source and sealed-reference provenance"
        )
    for case_id, relative_path, reference in zip(
        CASE_IDS, expected_reference_paths, references, strict=True
    ):
        expected_fixture_path = (
            f"benchmarks/semantic/cases/{case_id.lower()}.json"
        )
        bound_fixture = (
            reference.get("bound_fixture")
            if isinstance(reference, Mapping)
            else None
        )
        if (
            not isinstance(reference, Mapping)
            or set(reference)
            != {
                "case_id",
                "relative_path",
                "sha256",
                "source_kind",
                "bound_fixture",
            }
            or reference.get("case_id") != case_id
            or reference.get("relative_path") != relative_path
            or reference.get("source_kind") != "sealed_reference_byte_snapshot"
            or not _is_sha256(reference.get("sha256"))
            or not isinstance(bound_fixture, Mapping)
            or set(bound_fixture)
            != {
                "case_id",
                "relative_path",
                "sha256",
                "byte_size",
                "source_kind",
            }
            or bound_fixture.get("case_id") != case_id
            or bound_fixture.get("relative_path") != expected_fixture_path
            or not _is_sha256(bound_fixture.get("sha256"))
            or not isinstance(bound_fixture.get("byte_size"), int)
            or isinstance(bound_fixture.get("byte_size"), bool)
            or bound_fixture.get("byte_size") <= 0
            or bound_fixture.get("source_kind")
            != "bound_fixture_byte_snapshot"
        ):
            raise SupervisionError(
                "comparison sealed-reference provenance is malformed or noncanonical"
            )
    allowed_statuses = {
        "characterisation_exact",
        "characterisation_mismatch",
        "characterisation_inconclusive",
    }
    allowed_classifications = {
        "exact_match",
        "approved_transformation_match",
        "claim_field_mismatch",
        "missing_claim_field",
        "extra_unclaimed_field",
    }
    expected_fields = [
        "activities.A.start",
        "activities.A.finish",
        "activities.B.start",
        "activities.B.finish",
        "project_finish",
    ]
    for case_id, item in zip(CASE_IDS, comparison_cases, strict=True):
        fields = item.get("fields")
        normalized = item.get("normalized_native")
        if (
            item.get("status") not in allowed_statuses
            or not isinstance(fields, list)
            or [
                field.get("field") if isinstance(field, Mapping) else None
                for field in fields
            ]
            != expected_fields
            or any(
                not isinstance(field, Mapping)
                or field.get("classification") not in allowed_classifications
                for field in fields
            )
            or not isinstance(normalized, Mapping)
            or normalized.get("case_id") != case_id
        ):
            raise SupervisionError(f"comparison record is malformed for {case_id}")
        activities = normalized.get("activities")
        if (
            not isinstance(activities, Mapping)
            or set(activities) != {"A", "B"}
            or any(
                not isinstance(activities.get(activity_id), Mapping)
                or set(activities[activity_id]) != {"start", "finish"}
                or any(
                    not isinstance(activities[activity_id].get(coordinate), int)
                    or isinstance(activities[activity_id].get(coordinate), bool)
                    for coordinate in ("start", "finish")
                )
                for activity_id in ("A", "B")
            )
            or not isinstance(normalized.get("project_finish"), int)
            or isinstance(normalized.get("project_finish"), bool)
        ):
            raise SupervisionError(
                f"comparison normalized native coordinates are malformed for {case_id}"
            )
        native_by_field = {
            "activities.A.start": activities["A"]["start"],
            "activities.A.finish": activities["A"]["finish"],
            "activities.B.start": activities["B"]["start"],
            "activities.B.finish": activities["B"]["finish"],
            "project_finish": normalized["project_finish"],
        }
        classifications: list[str] = []
        for field in fields:
            name = str(field["field"])
            classification = str(field["classification"])
            native = field.get("native")
            reference = field.get("reference")
            if type(native) is not int or (
                reference is not None and type(reference) is not int
            ):
                raise SupervisionError(
                    "comparison coordinate fields require exact JSON integers or null "
                    f"for {case_id}: {name}"
                )
            if native != native_by_field[name]:
                raise SupervisionError(
                    f"comparison field disagrees with normalized native value for {case_id}: {name}"
                )
            coherent = (
                (classification == "exact_match" and native == reference)
                or (
                    classification == "claim_field_mismatch"
                    and native is not None
                    and reference is not None
                    and native != reference
                )
                or (
                    classification == "missing_claim_field"
                    and native is None
                    and reference is not None
                )
                or (
                    classification == "extra_unclaimed_field"
                    and native is not None
                    and reference is None
                )
                or (
                    classification == "approved_transformation_match"
                    and native is not None
                    and reference is not None
                    and native != reference
                    and isinstance(field.get("approved_transformation"), Mapping)
                )
            )
            if not coherent:
                raise SupervisionError(
                    f"comparison classification is internally inconsistent for {case_id}: {name}"
                )
            classifications.append(classification)
        expected_status = (
            "characterisation_exact"
            if all(value == "exact_match" for value in classifications)
            else "characterisation_mismatch"
        )
        if item.get("status") == "characterisation_inconclusive":
            reasons = item.get("inconclusive_reasons")
            if not isinstance(reasons, list) or not reasons:
                raise SupervisionError(
                    f"comparison inconclusive status has no reasons for {case_id}"
                )
        elif item.get("status") != expected_status:
            raise SupervisionError(
                f"comparison status contradicts field classifications for {case_id}"
            )


def _verify_cached_comparison_against_current_oracle(
    run: headless.RunWorkspace,
    cached: Mapping[str, Any],
) -> None:
    """Re-execute the isolated comparator and require exact cache identity."""

    _validate_comparison_result(cached, run_id=run.run_id)
    verification_workspace = _next_attempt_workspace(
        run.path, "comparison-cache-verification"
    )
    verification_path = verification_workspace / "comparison.json"
    current = run_comparison_worker(
        repository_root=run.repository_root,
        run_id=run.run_id,
        workspace=verification_workspace,
        result_path=verification_path,
    )
    _verify_result_sidecar(verification_path)
    _validate_comparison_result(current, run_id=run.run_id)
    try:
        current_bytes = canonical_bytes(current)
        cached_bytes = canonical_bytes(cached)
    except (TypeError, ValueError) as error:
        raise SupervisionError(
            "cached or current comparison is outside canonical JSON"
        ) from error
    if current_bytes != cached_bytes:
        raise SupervisionError(
            "cached comparison disagrees with the current comparator or oracle"
        )


def _complete_run(
    run: headless.RunWorkspace,
    environment: Mapping[str, Any],
    observations: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    if set(observations) != set(CASE_IDS):
        missing = sorted(set(CASE_IDS) - set(observations))
        extra = sorted(set(observations) - set(CASE_IDS))
        raise ObservationFreezeError(
            f"complete run observation identity mismatch; missing={missing}, extra={extra}"
        )
    # Stop evidence has priority over a hash-valid resume.  Do not even enter
    # the twelve-case freeze gate while any case retains a native stop.
    _reject_run_stop_conditions(observations, resumed=True)
    freeze_index_path = run.path / "observation-freeze-index.json"
    verify_run_freeze_gate(run, write_index=not freeze_index_path.exists())
    existing_calendar = _existing_calendar_result(run.path)
    if existing_calendar is None:
        calendar_workspace = _next_attempt_workspace(run.path, "calendar-characterisation")
        calendar_path = calendar_workspace / "calendar-characterisation.json"
        # Calendar construction is a separate COM launch and therefore needs
        # the same just-in-time live environment/Perth gate as every case.
        _validate_environment_capture(environment)
        calendar = run_supervised_worker(
            operation="calendar",
            repository_root=run.repository_root,
            run_id=run.run_id,
            workspace=calendar_workspace,
            result_path=calendar_path,
        )
    else:
        calendar_path, calendar = existing_calendar
    calendar_artifacts = _validate_calendar_result(
        calendar, workspace=calendar_path.parent
    )
    if existing_calendar is None:
        _write_result_artifact_manifest(
            calendar_path,
            workspace=calendar_path.parent,
            artifacts=calendar_artifacts,
        )
    # Re-read and reject the frozen observations immediately before handing
    # control to the separate oracle-capable process.  That process repeats
    # the durable gate independently.
    comparator_observations = {
        case_id: _read_json(
            run.path / "cases" / case_id / "native-observation.json"
        )
        for case_id in CASE_IDS
    }
    _reject_run_stop_conditions(comparator_observations, resumed=True)
    verify_run_freeze_gate(run, write_index=False)
    comparison_path = run.path / "comparison.json"
    if comparison_path.exists():
        _verify_result_sidecar(comparison_path)
        comparison = _read_json(comparison_path)
        # A digest sidecar binds only the old bytes to themselves.  Re-run the
        # isolated oracle-capable comparator after the freeze gate and require
        # byte-content equivalence of the semantic result plus its comparator
        # source and twelve exact sealed-reference snapshot digests.
        _verify_cached_comparison_against_current_oracle(run, comparison)
    else:
        comparison_workspace = _next_attempt_workspace(run.path, "comparison-operation")
        if comparison_workspace.name != "comparison-operation":
            comparison_path = comparison_workspace / "comparison.json"
        comparison = run_comparison_worker(
            repository_root=run.repository_root,
            run_id=run.run_id,
            workspace=comparison_workspace,
            result_path=comparison_path,
        )
    _verify_result_sidecar(comparison_path)
    _validate_comparison_result(comparison, run_id=run.run_id)
    reopen_results = [_reopen_result(observations[case_id]) for case_id in CASE_IDS]
    completion = {
        "schema_version": "headless-msproject-run-completion-v0.1",
        "characterisation_label": TRACK_ID,
        "run_id": run.run_id,
        "completed_at": _now(),
        "environment_path": "environment.json",
        "preflight_path": "preflight/preflight.json",
        "comparison_path": comparison_path.relative_to(run.path).as_posix(),
        "calendar_characterisation_path": calendar_path.relative_to(run.path).as_posix(),
        "cases_attempted": list(CASE_IDS),
        "cases_completed": list(CASE_IDS),
        "comparison": comparison,
        "reopen_results": reopen_results,
        "calendar_characterisation": calendar,
        "claim_boundary": {
            "manual_native_semantic_parity_track_executed": False,
            "saved_file_reopen_recalculate_stability_track_executed": False,
            "adapter_interchange_round_trip_track_executed": False,
            "track_c_preparation_blocked_unchanged": True,
            "full_microsoft_project_compatibility_claim": False,
            "optimizer_involved": False,
        },
    }
    completion_path = run.path / "run-completion.json"
    durable_write_canonical_json(completion_path, completion)
    inventory = _raw_hash_inventory(run.path)
    inventory_path = run.path / "raw-artifact-hashes.json"
    inventory_sha = durable_write_canonical_json(
        inventory_path,
        {
            "schema_version": "headless-msproject-raw-artifact-hashes-v0.1",
            "run_id": run.run_id,
            "artifacts": inventory,
        },
    )
    headless.durable_write_bytes(
        run.path / "raw-artifact-hashes.sha256", f"{inventory_sha}\n".encode("ascii")
    )
    return {
        "run_id": run.run_id,
        "raw_evidence_directory": str(run.path),
        "completion_path": str(completion_path),
        "raw_hash_inventory_path": str(inventory_path),
        "raw_hash_inventory_sha256": inventory_sha,
        "case_statuses": {item["case_id"]: item["status"] for item in comparison["cases"]},
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--case", choices=CASE_IDS)
    group.add_argument("--all-relationship-cases", action="store_true")
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--run-id")
    parser.add_argument("--resume", action="store_true")
    return parser


def main(arguments: list[str] | None = None) -> int:
    args = _parser().parse_args(arguments)
    repository_root = args.repository_root.resolve()
    run_id = args.run_id or _default_run_id()
    if args.resume and not args.run_id:
        raise SystemExit("--resume requires --run-id")
    try:
        run = create_run_workspace(repository_root, run_id, resume=args.resume)
        environment, _preflight = _ensure_environment_and_preflight(
            run, resume_existing=args.resume
        )
        selected = list(CASE_IDS) if args.all_relationship_cases else [args.case]
        observations: dict[str, Mapping[str, Any]] = (
            _resume_existing_cases(
                run,
                environment,
                selected_case_id=(
                    None if args.all_relationship_cases else args.case
                ),
            )
            if args.resume
            else {}
        )
        for case_id in selected:
            observations[case_id] = _run_one_case(
                run, case_id, environment, resume_existing=args.resume
            )
        if args.all_relationship_cases:
            missing = [case_id for case_id in CASE_IDS if case_id not in observations]
            if missing:
                raise ObservationFreezeError(f"all-case run is missing observations: {missing}")
            result = _complete_run(run, environment, observations)
        else:
            result = {
                "run_id": run.run_id,
                "raw_evidence_directory": str(run.path),
                "case_id": args.case,
                "status": "characterisation_observation_frozen",
                "case_manifest": str(run.path / "cases" / args.case / "case-manifest.json"),
                "comparison_performed": False,
            }
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as error:
        print(
            json.dumps(
                {
                    "run_id": run_id,
                    "status": "characterisation_inconclusive",
                    "batch_stopped": True,
                    "error_type": type(error).__name__,
                    "error": str(error),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
