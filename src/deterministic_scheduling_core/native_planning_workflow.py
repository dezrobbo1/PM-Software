"""Editable native planning loop: python -m deterministic_scheduling_core.native_planning_workflow."""
from __future__ import annotations

import argparse
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from pathlib import Path

from deterministic_scheduling_core.errors import SchedulingError
from deterministic_scheduling_core.project.planning_workspace import (
    accept_report, load, new_demo_workspace, report_unavailable, save,
    set_processing, state_hash,
)
from deterministic_scheduling_core.scheduling.planning_workspace import approve, propose
from deterministic_scheduling_core.working_time_experiment import format_tick


def parse_time(text: str) -> int:
    """Relative day@HH:MM, where day 1 begins at tick 0; 30-minute resolution."""
    try:
        day_text, clock = text.split("@")
        hour_text, minute_text = clock.split(":")
        day, hour, minute = int(day_text), int(hour_text), int(minute_text)
        if day < 1 or not 0 <= hour <= 24 or minute not in (0, 30) or (hour == 24 and minute):
            raise ValueError
        return (day - 1) * 48 + hour * 2 + minute // 30
    except ValueError as error:
        raise argparse.ArgumentTypeError("use day@HH:MM on a half-hour boundary, e.g. 1@10:00") from error


def parse_hours(text: str) -> int:
    try:
        value = Decimal(text) * 2
        if not value.is_finite() or value <= 0 or value != value.to_integral_value():
            raise ValueError
        return int(value)
    except (InvalidOperation, ValueError) as error:
        raise argparse.ArgumentTypeError("hours must be a positive multiple of 0.5") from error


def _periods(entry: dict) -> str:
    return "; ".join(f"{format_tick(start)} to {format_tick(end)}" for start, end in entry["periods"]) or "milestone"


def render_plan(workspace: dict, plan: dict, label: str) -> str:
    current = plan["source_state_hash"] == state_hash(workspace)
    lines = [f"{label}: {'CURRENT INPUTS' if current else 'STALE - accepted inputs changed; recalculate before use'}",
             f"Controlling finish: {format_tick(plan['project_finish'])}",
             f"Physical allocation: {plan['physical_status']}",
             f"Plan hash: {plan['plan_hash']}",
             "ID | Mode | Assignment (POOL means deferred) | Productive execution"]
    for entry in plan["entries"]:
        assigned = ", ".join(f"{slot}={resource or 'POOL'}" for slot, resource in entry["assignments"]) or "none"
        lines.append(f"{entry['activity_id']} | {plan['selected_modes'][entry['activity_id']]} | {assigned} | {_periods(entry)}")
    return "\n".join(lines)


def render_changes(previous: dict | None, current: dict) -> str:
    if previous is None:
        return "Initial proposal; no approved reference plan."
    before = {entry["activity_id"]: entry for entry in previous["entries"]}
    lines = ["CHANGES FROM APPROVED PLAN",
             f"Controlling finish: {format_tick(previous['project_finish'])} -> {format_tick(current['project_finish'])}"]
    for entry in current["entries"]:
        identifier = entry["activity_id"]
        old = before.get(identifier)
        mode_before = previous["selected_modes"].get(identifier)
        mode_after = current["selected_modes"][identifier]
        if old != entry or mode_before != mode_after:
            lines.append(f"{identifier}: mode {mode_before} -> {mode_after}; "
                         f"execution {_periods(old) if old else 'new'} -> {_periods(entry)}; "
                         f"assignments {old['assignments'] if old else []} -> {entry['assignments']}")
    lines.append("Accepted availability inputs for this calculation:")
    reports = current["source_snapshot"]["accepted_reports"]
    lines.extend(f"{r['id']}: {r['resource_id']} unavailable {format_tick(r['start'])} to {format_tick(r['finish'])}; {r['reason']}; accepted by {r['accepted_by']}" for r in reports)
    if not reports:
        lines.append("None; native project input edits are visible in the saved source snapshots.")
    lines.append("Authorised alternatives evaluated (objective: finish, mode changes, start movement, assignment changes, timing):")
    for alternative in current["alternatives"]:
        lines.append(f"{alternative['modes']}: {alternative['status']} {alternative.get('objective', '')}")
    lines.append("These are computed differences and alternative results, not a general root-cause proof.")
    return "\n".join(lines)


def show(workspace: dict) -> str:
    lines = [workspace["project"]["name"], "Native planning workspace POC - 30-minute units; future work only."]
    for report in workspace["reports"]:
        lines.append(f"{report['id']} {report['status']}: {report['resource_id']} "
                     f"{format_tick(report['start'])} to {format_tick(report['finish'])} - {report['reason']}")
    lines.append("Reported-only availability does not alter trusted scheduling inputs.")
    if workspace["approved_plan"]:
        lines.append(render_plan(workspace, workspace["approved_plan"], "APPROVED PLAN"))
    else:
        lines.append("No approved plan.")
    if workspace["proposal"]:
        lines.append(render_plan(workspace, workspace["proposal"], "UNAPPROVED PROPOSAL"))
        lines.append(render_changes(workspace["approved_plan"], workspace["proposal"]))
    lines.append(f"Previous approved plans retained: {len(workspace['plan_history'])}")
    return "\n\n".join(lines)


def run_demo(path: str | Path) -> dict:
    destination = Path(path)
    if destination.exists():
        raise ValueError("demo destination already exists; choose a new file")
    workspace = new_demo_workspace()
    save(workspace, destination)
    workspace = load(destination)
    propose(workspace)
    approve(workspace, "demo-planner")
    save(workspace, destination)
    baseline = deepcopy(workspace["approved_plan"])
    print("INITIAL NATIVE PLAN\n" + show(workspace))
    event = report_unavailable(workspace, "M2", 20, 34, "demo-supervisor", "Synthetic future M2 unavailability")
    save(workspace, destination)
    workspace = load(destination)
    assert workspace["approved_plan"] == baseline
    assert state_hash(workspace) == baseline["source_state_hash"]
    print(f"\nREPORT {event}: approved plan and trusted input hash unchanged.")
    accept_report(workspace, event, "demo-planner")
    save(workspace, destination)
    workspace = load(destination)
    assert workspace["approved_plan"] == baseline
    assert state_hash(workspace) != baseline["source_state_hash"]
    print("ACCEPTED REPORT: old approved plan retained and labelled stale.")
    proposal = propose(workspace)
    print("\n" + render_changes(baseline, proposal))
    print("\n" + render_plan(workspace, proposal, "UNAPPROVED RECOVERY"))
    assert workspace["approved_plan"] == baseline
    save(workspace, destination)
    workspace = load(destination)
    approve(workspace, "demo-planner")
    expected = deepcopy(workspace)
    save(workspace, destination)
    reopened = load(destination)
    assert reopened == expected
    print(f"\nRecovery explicitly approved. Saved and reopened: {destination}")
    print(f"Reopened finish: {format_tick(reopened['approved_plan']['project_finish'])}")
    print(f"Approved history retained: {len(reopened['plan_history'])}; full JSON round-trip identical: True")
    print("Scope: activity-mode choices, calendars, physical allocation and report acceptance are integrated; no partial-progress or adaptive-neighbourhood integration is claimed.")
    return reopened


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "show", "plan", "demo"):
        command = commands.add_parser(name)
        command.add_argument("path")
    approval = commands.add_parser("approve")
    approval.add_argument("path")
    approval.add_argument("--by", required=True)
    report = commands.add_parser("report-unavailable")
    report.add_argument("path")
    report.add_argument("--resource", required=True)
    report.add_argument("--start", type=parse_time, required=True)
    report.add_argument("--finish", type=parse_time, required=True)
    report.add_argument("--by", required=True)
    report.add_argument("--reason", required=True)
    acceptance = commands.add_parser("accept-report")
    acceptance.add_argument("path")
    acceptance.add_argument("report_id")
    acceptance.add_argument("--by", required=True)
    edit = commands.add_parser("set-work")
    edit.add_argument("path")
    edit.add_argument("activity_id")
    edit.add_argument("mode_id")
    edit.add_argument("--hours", type=parse_hours, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "demo":
            run_demo(args.path)
            return 0
        if args.command == "init":
            if Path(args.path).exists():
                raise ValueError("workspace already exists; init will not overwrite it")
            workspace = new_demo_workspace()
        else:
            workspace = load(args.path)
        if args.command == "show":
            print(show(workspace))
            return 0
        if args.command == "plan":
            try:
                propose(workspace)
            except SchedulingError:
                workspace["proposal"] = None
                save(workspace, args.path)
                raise
        elif args.command == "approve":
            approve(workspace, args.by)
        elif args.command == "report-unavailable":
            event = report_unavailable(workspace, args.resource, args.start, args.finish, args.by, args.reason)
            print(f"Recorded {event}; scheduling inputs remain unchanged until acceptance.")
        elif args.command == "accept-report":
            accept_report(workspace, args.report_id, args.by)
        elif args.command == "set-work":
            set_processing(workspace, args.activity_id, args.mode_id, args.hours)
        save(workspace, args.path)
        print(show(workspace))
        return 0
    except (ValueError, KeyError, OSError, SchedulingError) as error:
        print(f"Unable to complete {args.command}: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
