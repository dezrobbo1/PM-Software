#!/usr/bin/env python3
"""Finalize frozen headless Project observations without launching Project."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any, Iterator, Mapping

from deterministic_scheduling_core.native.msproject.headless import (
    CASE_IDS,
    RAW_ROOT,
    TRACK_ID,
    build_tracked_summary,
    create_run_workspace,
    durable_write_bytes,
    durable_write_canonical_json,
    parse_project_xml_observation,
    sha256_file,
    validated_cal24x7_calendar,
    verify_run_freeze_gate,
)


AUTOMATION_HASH_ROLES = (
    "automation_tool_sha256",
    "headless_core_sha256",
    "headless_com_sha256",
    "headless_worker_sha256",
)
RETAINED_RUN_ID = "20260830T185000p0800"

RawTreeSnapshot = dict[str, tuple[str, int | None, str | None]]


class RawTreeImmutabilityError(RuntimeError):
    """The summary-only finalizer changed or could not reverify raw evidence."""


def _stable_raw_file_identity(path: Path, *, label: str) -> tuple[int, str]:
    """Hash one stable regular file through an explicitly binary descriptor."""

    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_BINARY", 0)
    )
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise RawTreeImmutabilityError(
            f"{label} could not be opened safely: {error}"
        ) from error
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise RawTreeImmutabilityError(f"{label} is not a regular file")
        digest = hashlib.sha256()
        observed_size = 0
        while True:
            block = os.read(descriptor, 1024 * 1024)
            if not block:
                break
            digest.update(block)
            observed_size += len(block)
        after_handle = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    try:
        current = os.stat(path, follow_symlinks=False)
    except OSError as error:
        raise RawTreeImmutabilityError(f"{label} changed while read: {error}") from error
    stable_fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns")
    if (
        not stat.S_ISREG(current.st_mode)
        or any(
            getattr(before, field) != getattr(after_handle, field)
            for field in stable_fields
        )
        or any(
            getattr(after_handle, field) != getattr(current, field)
            for field in stable_fields
        )
        or observed_size != after_handle.st_size
    ):
        raise RawTreeImmutabilityError(f"{label} changed while it was hashed")
    return observed_size, digest.hexdigest()


def _raw_tree_snapshot(raw_root: Path) -> RawTreeSnapshot:
    """Capture every raw-tree path plus stable file bytes and SHA-256 identity."""

    if raw_root.is_symlink() or not raw_root.is_dir():
        raise RawTreeImmutabilityError(
            f"frozen raw evidence root must be a real directory: {raw_root}"
        )
    entries: RawTreeSnapshot = {}
    for path in sorted(raw_root.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(raw_root).as_posix()
        if path.is_symlink():
            raise RawTreeImmutabilityError(
                f"frozen raw evidence tree contains a symbolic link: {relative}"
            )
        if path.is_dir():
            entries[relative] = ("directory", None, None)
            continue
        if not path.is_file():
            raise RawTreeImmutabilityError(
                f"frozen raw evidence tree contains a special path: {relative}"
            )
        byte_size, digest = _stable_raw_file_identity(
            path, label=f"frozen raw artifact {relative}"
        )
        entries[relative] = ("file", byte_size, digest)
    return entries


def _assert_raw_tree_unchanged(
    raw_root: Path, before: RawTreeSnapshot
) -> None:
    try:
        after = _raw_tree_snapshot(raw_root)
    except Exception as error:
        raise RawTreeImmutabilityError(
            "frozen raw evidence tree could not be reverified after --summary-only"
        ) from error
    if after == before:
        return
    before_paths = set(before)
    after_paths = set(after)
    added = sorted(after_paths - before_paths)
    removed = sorted(before_paths - after_paths)
    changed = sorted(
        path
        for path in before_paths & after_paths
        if before[path] != after[path]
    )
    raise RawTreeImmutabilityError(
        "frozen raw evidence tree changed during --summary-only; "
        f"added={added[:5]}, removed={removed[:5]}, changed={changed[:5]}"
    )


@contextmanager
def _raw_tree_immutability_guard(raw_root: Path) -> Iterator[RawTreeSnapshot]:
    """Fail even when a summary-only operation mutates raw bytes then errors."""

    before = _raw_tree_snapshot(raw_root)
    try:
        yield before
    except BaseException as operation_error:
        try:
            _assert_raw_tree_unchanged(raw_root, before)
        except RawTreeImmutabilityError as mutation_error:
            raise mutation_error from operation_error
        raise
    else:
        _assert_raw_tree_unchanged(raw_root, before)


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _named_task(capture: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    matches = [task for task in capture["tasks"] if task.get("name") == name]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one native task named {name!r}")
    return matches[0]


def _claimed(capture: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "A": {
            "start": _named_task(capture, "A")["start"],
            "finish": _named_task(capture, "A")["finish"],
        },
        "B": {
            "start": _named_task(capture, "B")["start"],
            "finish": _named_task(capture, "B")["finish"],
        },
        "project_finish": capture["project"]["finish"],
    }


def _xml_links(observation: Mapping[str, Any], key: str) -> list[Mapping[str, Any]]:
    return [
        link
        for task in observation[key]["tasks"]
        for link in task["predecessor_links"]
    ]


def _wall_clock(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"expected an ISO wall-clock string, received {value!r}")
    return datetime.fromisoformat(value).replace(tzinfo=None)


def _xml_claimed(observation: Mapping[str, Any], key: str) -> dict[str, Any]:
    xml = observation[key]
    return {
        "A": {
            "start": _named_task(xml, "A")["start"],
            "finish": _named_task(xml, "A")["finish"],
        },
        "B": {
            "start": _named_task(xml, "B")["start"],
            "finish": _named_task(xml, "B")["finish"],
        },
        "project_finish": xml["project"]["finish"],
    }


def _wall_clock_deltas(
    com_capture: Mapping[str, Any], xml_capture: Mapping[str, Any]
) -> list[int | float]:
    deltas: list[int | float] = []
    for task_name in ("A", "B"):
        for field in ("start", "finish"):
            hours = (
                _wall_clock(xml_capture[task_name][field])
                - _wall_clock(com_capture[task_name][field])
            ).total_seconds() / 3600
            deltas.append(int(hours) if hours.is_integer() else hours)
    hours = (
        _wall_clock(xml_capture["project_finish"])
        - _wall_clock(com_capture["project_finish"])
    ).total_seconds() / 3600
    deltas.append(int(hours) if hours.is_integer() else hours)
    return deltas


def _executed_automation_identity(run_path: Path) -> dict[str, Any]:
    identities: dict[str, str] | None = None
    for case_id in CASE_IDS:
        manifest = _read_object(run_path / "cases" / case_id / "case-manifest.json")
        shared = manifest.get("shared_hashes")
        if not isinstance(shared, Mapping):
            raise ValueError(f"{case_id} has no shared hash identity")
        candidate = {role: str(shared.get(role, "")) for role in AUTOMATION_HASH_ROLES}
        if any(len(value) != 64 for value in candidate.values()):
            raise ValueError(f"{case_id} has incomplete automation hashes")
        if identities is None:
            identities = candidate
        elif candidate != identities:
            raise ValueError("executed automation hashes differ across cases")
    return {
        **(identities or {}),
        "identity_source": (
            "identical shared_hashes values in all twelve frozen case manifests; "
            "the immutable v0.1 worker observations do not self-report these identities"
        ),
        "reviewed_branch_code_is_post_run_hardened": True,
    }


def _global_raw_inventory(raw_root: Path) -> list[dict[str, Any]]:
    excluded = {
        "all-attempt-raw-artifact-hashes.json",
        "all-attempt-raw-artifact-hashes.sha256",
    }
    entries: list[dict[str, Any]] = []
    for path in sorted(raw_root.rglob("*"), key=lambda item: item.as_posix()):
        if path.is_file() and path.name not in excluded:
            relative = path.relative_to(raw_root)
            entries.append(
                {
                    "run_id": relative.parts[0],
                    "relative_path": Path(*relative.parts[1:]).as_posix(),
                    "byte_size": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
    return entries


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--tracked-output", type=Path, required=True)
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help=(
            "rebuild the tracked summary without mutating frozen raw outputs; "
            "the retained inventory and sidecar are verified instead"
        ),
    )
    return parser


def _tracked_output_path(repository_root: Path, candidate: Path) -> Path:
    output = candidate if candidate.is_absolute() else repository_root / candidate
    output = output.resolve()
    raw_root = repository_root.joinpath(*RAW_ROOT.parts).resolve()
    if output == raw_root or raw_root in output.parents:
        raise ValueError("tracked summary output must remain outside frozen RAW_ROOT")
    return output


def _require_retained_run_id(run_id: str) -> None:
    if run_id != RETAINED_RUN_ID:
        raise ValueError(
            f"this incident finalizer is restricted to retained run {RETAINED_RUN_ID}"
        )


def _finalize(args: argparse.Namespace, repository_root: Path) -> int:
    output = _tracked_output_path(repository_root, args.tracked_output)
    run = create_run_workspace(repository_root, args.run_id, resume=True)
    verify_run_freeze_gate(
        run,
        write_index=False,
        allow_legacy_stop_evidence_for_audit=True,
    )
    environment = _read_object(run.path / "environment.json")
    comparison = _read_object(run.path / "comparison.json")
    anomalies = _read_object(run.path / "run-anomalies.json")
    comparison_by_case = {item["case_id"]: item for item in comparison["cases"]}

    cases: list[dict[str, Any]] = []
    reopen_results: list[dict[str, Any]] = []
    absolute_time_affected_cases: list[str] = []
    observed_wall_clock_deltas: set[int | float] = set()
    for case_id in CASE_IDS:
        observation = _read_object(run.path / "cases" / case_id / "native-observation.json")
        before = _claimed(observation["initial_calculated"])
        after_open = _claimed(observation["reopen_after_open"])
        after_recalculate = _claimed(observation["reopen_after_recalculate"])
        initial_links = _xml_links(observation, "initial_xml_observation")
        reopened_links = _xml_links(observation, "reopened_xml_observation")
        initial_xml_times = _xml_claimed(observation, "initial_xml_observation")
        reopened_xml_times = _xml_claimed(observation, "reopened_xml_observation")
        case_deltas = _wall_clock_deltas(before, initial_xml_times) + _wall_clock_deltas(
            after_recalculate, reopened_xml_times
        )
        for com_key, xml_key in (
            ("initial_calculated", "initial_xml_observation"),
            ("reopen_after_recalculate", "reopened_xml_observation"),
        ):
            project_start_delta = (
                _wall_clock(observation[xml_key]["project"]["start"])
                - _wall_clock(observation[com_key]["project"]["start"])
            ).total_seconds() / 3600
            case_deltas.append(
                int(project_start_delta)
                if project_start_delta.is_integer()
                else project_start_delta
            )
        observed_wall_clock_deltas.update(case_deltas)
        absolute_time_consistent = all(delta == 0 for delta in case_deltas)
        if not absolute_time_consistent:
            absolute_time_affected_cases.append(case_id)
        forced = [
            int(item["pid"])
            for item in observation["process_sessions"]
            if item.get("forced_termination")
        ]
        reopen_stable = before == after_open == after_recalculate
        xml_preserved = initial_links == reopened_links and len(initial_links) == 1
        comparison_record = comparison_by_case[case_id]
        retained_stops = observation.get("stop_conditions")
        execution_status = (
            "characterisation_inconclusive"
            if forced or not absolute_time_consistent or retained_stops
            else comparison_record["status"]
        )
        notes: list[str] = []
        if forced:
            notes.append(
                "A Project process was attributed to this worker by the then-current "
                "PID/path-delta logic and forcibly terminated after evidence capture; "
                "full creation/caption/HWND ownership proof was not retained."
            )
        if not absolute_time_consistent:
            notes.append(
                "Overall inconclusive: Project-authored initial and reopened XML wall-clock timestamps disagree with serialized COM timestamps."
            )
        if retained_stops:
            notes.append("The frozen observation retained native stop conditions.")
        cases.append(
            {
                "case_id": case_id,
                "relationship": observation["relationship_assignment"]["source_type"],
                "source_lag_hours": observation["relationship_assignment"]["source_lag_hours"],
                "native_relationship_assignment": observation["relationship_assignment"],
                "native_timestamps": before,
                "normalized_native": comparison_record["normalized_native"],
                "reference_comparison": comparison_record["status"],
                "reference_comparison_is_provisional": not absolute_time_consistent,
                "field_classifications": comparison_record["fields"],
                "reopen_stable": reopen_stable,
                "xml_relationship_preserved": xml_preserved,
                "process_ids": [int(item["pid"]) for item in observation["process_sessions"]],
                "all_processes_exited": all(item.get("exited") for item in observation["process_sessions"]),
                "forced_termination_pids": forced,
                "native_stop_conditions_recorded_at_freeze": observation["stop_conditions"],
                "execution_status": execution_status,
                "absolute_time_consistency": (
                    "consistent"
                    if absolute_time_consistent
                    else "characterisation_inconclusive"
                ),
                "notes": notes,
            }
        )
        reopen_results.append(
            {
                "case_id": case_id,
                "before_reopen": before,
                "after_open": after_open,
                "after_explicit_recalculate": after_recalculate,
                "reopen_stable": reopen_stable,
                "xml_relationship_preserved": xml_preserved,
                "absolute_time_semantics_established": absolute_time_consistent,
            }
        )

    calendar_xml = (
        run.path / "calendar-characterisation" / "project-authored-24-hours.xml"
    )
    calendar_xml_observation = parse_project_xml_observation(calendar_xml)
    calendar_24_hours = validated_cal24x7_calendar(calendar_xml_observation)
    calendar_characterisation = {
        **anomalies["calendar_characterisation"],
        "authored_xml_sha256": sha256_file(calendar_xml),
        "namespace": calendar_xml_observation["namespace"],
        "save_version": calendar_xml_observation["save_version"],
        "project_calendar_uid": calendar_xml_observation["project"]["calendar_uid"],
        "project_authored_24_hours_calendar": calendar_24_hours,
        "dialog_evidence_basis": "post_run_operator_attestation",
        "durable_watchdog_window_inventory_complete": False,
        "ran_after_mandatory_stop_trigger": True,
        "interpretation": "provisional_characterisation_after_mandatory_stop_breach",
        "finding": (
            "Post-run operator attestation reports that FileOpenEx displayed "
            "Import Wizard - Import Mode and that it was not dismissed. The "
            "durable watchdog stop has a stale PID and empty window inventory, "
            "so the title is not machine-journalled evidence."
        ),
    }
    forced_cases = [item["case_id"] for item in cases if item["forced_termination_pids"]]
    inconclusive_cases = [
        item["case_id"]
        for item in cases
        if item["execution_status"] == "characterisation_inconclusive"
    ]
    process_incident = dict(anomalies.get("process_ownership_incident", {}))
    procedural_blinding = dict(anomalies.get("procedural_blinding", {}))
    procedural_blinding.update(
        {
            "construction_path_used_source_only_loader": True,
            "runtime_source_isolation_enforced": False,
            "summary": (
                "The executed construction branch used the source-only loader "
                "and a separate post-freeze comparison process, but no operating-"
                "system or ACL boundary made the construction process technically "
                "unable to read the sealed tree."
            ),
        }
    )
    has_protocol_defect = bool(
        inconclusive_cases
        or calendar_characterisation.get("status")
        == "characterisation_inconclusive"
        or process_incident.get("safety_violation")
        or procedural_blinding.get("clean_blind_classification_permitted") is False
    )
    run_status = {
        "schema_version": "headless-msproject-run-status-v0.1",
        "characterisation_label": TRACK_ID,
        "run_id": run.run_id,
        "status": (
            "characterisation_completed_with_protocol_tooling_defects"
            if has_protocol_defect
            else "characterisation_completed"
        ),
        "cases_attempted": list(CASE_IDS),
        "cases_observation_frozen": list(CASE_IDS),
        "reference_comparison_exact_cases": [
            item["case_id"]
            for item in cases
            if item["reference_comparison"] == "characterisation_exact"
        ],
        "execution_integrity_inconclusive_cases": inconclusive_cases,
        "reopen_stable_cases": [item["case_id"] for item in cases if item["reopen_stable"]],
        "xml_relationship_preserved_cases": [
            item["case_id"] for item in cases if item["xml_relationship_preserved"]
        ],
        "calendar_characterisation_status": calendar_characterisation["status"],
        "process_ownership_safety_violation": bool(
            process_incident.get("safety_violation")
        ),
        "recommendation": anomalies["recommendation"],
    }
    run_status_path = run.path / "run-status.json"
    if not args.summary_only:
        durable_write_canonical_json(run_status_path, run_status)

    raw_root = repository_root.joinpath(*RAW_ROOT.parts)
    inventory = _global_raw_inventory(raw_root)
    inventory_path = run.path / "all-attempt-raw-artifact-hashes.json"
    inventory_payload = {
        "schema_version": "headless-msproject-all-attempt-raw-artifact-hashes-v0.1",
        "final_run_id": run.run_id,
        "artifacts": inventory,
    }
    if args.summary_only:
        if _read_object(inventory_path) != inventory_payload:
            raise ValueError("retained raw inventory does not match recomputed hashes")
        inventory_sha = sha256_file(inventory_path)
    else:
        inventory_sha = durable_write_canonical_json(inventory_path, inventory_payload)
    inventory_sidecar = run.path / "all-attempt-raw-artifact-hashes.sha256"
    if args.summary_only:
        if inventory_sidecar.read_text(encoding="ascii") != f"{inventory_sha}\n":
            raise ValueError("retained raw inventory sidecar does not match inventory")
    else:
        durable_write_bytes(inventory_sidecar, f"{inventory_sha}\n".encode("ascii"))

    project = environment["microsoft_project"]
    executable = environment["project_executable"]
    windows = environment["windows"]
    curated_environment = {
        "microsoft_project": {
            "name": project["name"],
            "edition": project["edition"],
            "version": project["version"],
            "build": project["build"],
            "com_prog_id": project["com_prog_id"],
            "visible": project["visible"],
        },
        "project_executable": {
            "path": executable["path"],
            "sha256": executable["sha256"],
            "size_bytes": executable["size_bytes"],
            "numeric_file_version": executable["version_info"]["numeric_file_version"],
        },
        "windows": windows,
        "python": {
            "version": environment["python"]["version"],
            "implementation": environment["python"]["implementation"],
            "architecture": environment["python"]["architecture"],
        },
        "locale": environment["locale"],
        "time_zone": environment["time_zone"],
    }
    summary = build_tracked_summary(
        run_id=run.run_id,
        environment=curated_environment,
        comparison=comparison,
        reopen_results=reopen_results,
        calendar_characterisation=calendar_characterisation,
        raw_hashes=inventory,
        procedural_blinding=procedural_blinding,
        native_execution_evidence={
            "process_ids_by_case": {
                item["case_id"]: item["process_ids"] for item in cases
            }
        },
    )
    uniform_delta: int | float | None = (
        next(iter(observed_wall_clock_deltas))
        if len(observed_wall_clock_deltas) == 1
        else None
    )
    absolute_time_consistency = {
        "status": (
            "consistent"
            if not absolute_time_affected_cases
            else "characterisation_inconclusive"
        ),
        "affected_cases": absolute_time_affected_cases,
        "com_to_project_xml_wall_clock_delta_hours": uniform_delta,
        "project_local_wall_clock_origin_established": not absolute_time_affected_cases,
        "requested_2026_01_05_0800_perth_start_established": not absolute_time_affected_cases,
        "raw_coordinate_comparison_is_provisional": bool(
            absolute_time_affected_cases
        ),
        "finding": (
            "Serialized COM and Project-authored XML task/project wall clocks agree."
            if not absolute_time_affected_cases
            else (
                "Project-authored initial and reopened XML task/project wall clocks "
                "disagree with the serialized COM observations"
                + (
                    f" by a uniform {uniform_delta:+g} hours."
                    if uniform_delta is not None
                    else "."
                )
            )
        ),
    }
    if process_incident:
        process_incident.update(
            {
                "evidence_basis": "post_run_operator_attestation",
                "durable_watchdog_window_and_parent_evidence_retained": False,
                "summary": (
                    "Post-run operator attestation reports that cleanup "
                    "misclassified and terminated an unrelated user Project "
                    "process. The retained watchdog journal does not establish "
                    "the reported window-title or parent-process details."
                ),
            }
        )
    summary.update(
        {
            "status": run_status["status"],
            "starting_main_sha": "4c7c6d62902c62e822f059ee33aa4db40aba9594",
            "feature_branch": "phase1-msproject-headless-characterisation",
            "cases": cases,
            "case_counts": {
                "attempted": len(cases),
                "observation_frozen": len(cases),
                "reference_comparison_exact_provisional": sum(
                    item["reference_comparison"] == "characterisation_exact"
                    for item in cases
                ),
                "execution_integrity_inconclusive": len(inconclusive_cases),
            },
            "absolute_time_consistency": absolute_time_consistency,
            "comparison_interpretation": {
                "raw_frozen_comparison_preserved": True,
                "mandatory_batch_stop_breached": bool(forced_cases),
                "comparison_ran_after_stop_trigger": bool(forced_cases),
                "status": (
                    "provisional_due_to_absolute_time_inconsistency_and_mandatory_stop_breach"
                    if absolute_time_affected_cases and forced_cases
                    else "provisional_due_to_absolute_time_inconsistency"
                    if absolute_time_affected_cases
                    else "provisional_due_to_mandatory_stop_breach"
                    if forced_cases
                    else "interpretable_within_characterisation_boundary"
                ),
                "summary": (
                    "The embedded comparison is preserved mechanically but is not an overall semantic result because Project-authored XML contradicts the COM wall-clock origin and comparison ran after a mandatory batch-stop trigger."
                    if absolute_time_affected_cases and forced_cases
                    else "The embedded comparison is preserved mechanically but is not an overall semantic result because Project-authored XML contradicts the COM wall-clock origin."
                    if absolute_time_affected_cases
                    else "The embedded comparison ran after a mandatory batch-stop trigger and is retained only as provisional raw evidence."
                    if forced_cases
                    else "The embedded comparison is interpretable only within the stated characterisation boundary."
                ),
            },
            "raw_evidence_directory": "native-files/headless-msproject-characterisation/",
            "all_attempt_raw_evidence_root": "native-files/headless-msproject-characterisation/",
            "final_run_raw_evidence_directory": f"native-files/headless-msproject-characterisation/{run.run_id}/",
            "all_attempt_raw_hash_inventory": {
                "path": f"native-files/headless-msproject-characterisation/{run.run_id}/{inventory_path.name}",
                "sha256": inventory_sha,
                "sidecar_sha256": sha256_file(inventory_sidecar),
                "artifact_count": len(inventory),
            },
            "process_ownership_incident": process_incident,
            "executed_automation_identity": _executed_automation_identity(run.path),
            "superseded_raw_interpretations": {
                "native-files/headless-msproject-characterisation/20260830T185000p0800/run-status.json": (
                    "Contemporaneous raw status classified only three forced-termination "
                    "cases as inconclusive; the evidence-derived tracked interpretation "
                    "classifies all twelve as inconclusive due to the COM/XML wall-clock defect."
                ),
                "native-files/headless-msproject-characterisation/20260830T185000p0800/run-anomalies.json": (
                    "Contemporaneous raw narrative asserted technical runtime source isolation "
                    "and direct dialog/process details; the tracked interpretation records no "
                    "OS/ACL oracle boundary and labels those details as post-run operator attestation."
                ),
                "native-files/headless-msproject-characterisation/20260830T185000p0800/observation-freeze-index.json": (
                    "The hash/freeze identities remain audit-valid, but its oracle-access-permitted "
                    "conclusion is superseded because legacy empty stop_conditions omitted retained "
                    "forced-termination session evidence."
                ),
                "native-files/headless-msproject-characterisation/20260830T185000p0800/comparison.json": (
                    "The immutable mechanical comparison ran after a mandatory batch-stop trigger; "
                    "its coordinate classifications are retained only as provisional raw evidence."
                ),
            },
            "recommendation": anomalies["recommendation"],
        }
    )
    if forced_cases:
        summary["limitations"].append(
            f"{len(forced_cases)} Project processes were worker-attributed by the then-current PID/path-delta logic and forcibly terminated after evidence capture; full creation/caption/HWND ownership proof was not retained, so those executions are integrity-inconclusive."
        )
        summary["limitations"].append(
            "The retained batch continued after the first worker-attributed forced termination despite the protocol's mandatory-stop rule; the hardened runner now stops immediately."
        )
    if calendar_characterisation.get("status") == "characterisation_inconclusive":
        summary["limitations"].append(
            "The Project-authored CAL-24X7 XML was captured, but exact XML reopen/recalculate/re-export remained incomplete."
        )
    summary["limitations"].append(
        "CAL-24X7 native work also ran after the first mandatory batch-stop trigger; its retained serialization is provisional characterisation only."
    )
    if process_incident.get("safety_violation"):
        summary["limitations"].append(
            "Post-run operator attestation reports a process-ownership safety violation; supporting window/parent details were not retained in the machine watchdog journal, and further native execution stopped."
        )
    if "bound method" in str(project.get("file_build_id", "")):
        summary["limitations"].append(
            "The optional COM FileBuildID member was serialized as a bound-method representation in raw environment capture; Application.Build plus the executable file version and SHA-256 remain independently captured."
        )
    if absolute_time_affected_cases:
        summary["limitations"].append(
            f"All {len(absolute_time_affected_cases)} Project-authored XML case exports contradict the serialized COM wall-clock origin; the requested Perth origin and semantic comparison are not established."
        )
    encoded = json.dumps(summary, sort_keys=True)
    if "executed_pass" in encoded:
        raise ValueError("tracked characterisation summary cannot emit executed_pass")
    if args.summary_only and output.exists():
        if _read_object(output) != summary:
            raise ValueError("tracked summary differs from the evidence-derived rebuild")
    else:
        durable_write_canonical_json(output, summary)
    print(
        json.dumps(
            {
                "tracked_summary": str(output),
                "tracked_summary_sha256": sha256_file(output),
                "raw_inventory": str(inventory_path),
                "raw_inventory_sha256": inventory_sha,
                "raw_artifact_count": len(inventory),
            },
            sort_keys=True,
        )
    )
    return 0


def main(arguments: list[str] | None = None) -> int:
    args = _parser().parse_args(arguments)
    _require_retained_run_id(args.run_id)
    repository_root = args.repository_root.resolve()
    if not args.summary_only:
        return _finalize(args, repository_root)
    raw_root = repository_root.joinpath(*RAW_ROOT.parts)
    with _raw_tree_immutability_guard(raw_root):
        return _finalize(args, repository_root)


if __name__ == "__main__":
    raise SystemExit(main())
