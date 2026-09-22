"""Controlled practitioner trial built entirely from the native planning model."""
from __future__ import annotations

from copy import deepcopy
import os
from pathlib import Path
import subprocess

from deterministic_scheduling_core.project.planning_workspace import GROUP_SCHEMA, validate
from deterministic_scheduling_core.scheduling.planning_workspace import approve, propose, validate_stored_plans

TRIAL_ID = "planner-update-recovery-v1"
TRIAL_NAME = "Planner Update & Recovery Trial v1"
TRIAL_VERSION = "1"
STARTING_FINISH = 72
STATUS_POINT = 24
RECOVERED_FINISH = 77


def _mode(processing_ticks: int, *demands: tuple[str, int]) -> dict:
    return {
        "id": "FIXED",
        "processing_ticks": processing_ticks,
        "calendar_id": "DAY",
        "continuity": "SUSPENDABLE_AT_AVAILABILITY_GAPS",
        "requirements": [],
        "group_requirements": [
            {"group_id": group_id, "demand": demand}
            for group_id, demand in demands
        ],
    }


def _activity(
    identifier: str,
    name: str,
    processing_ticks: int,
    predecessors: list[str],
    *demands: tuple[str, int],
    not_before: int = 0,
) -> dict:
    return {
        "id": identifier,
        "name": name,
        "predecessors": predecessors,
        "not_before": not_before,
        "modes": [_mode(processing_ticks, *demands)],
    }


def _project() -> dict:
    return {
        "id": "conveyor-chute-recovery-trial",
        "name": "Conveyor chute liner replacement and return to service",
        "horizon_ticks": 144,
        "objective_activity_id": "A10",
        "pool_riggers": False,
        "calendars": [{"id": "DAY", "daily_windows": [[14, 24], [25, 34]]}],
        "resources": [],
        "resource_groups": [
            {"id": "MECH", "name": "Mechanical trades", "capacity": 3, "calendar_id": "DAY", "disjoint": True, "interchangeable": True},
            {"id": "OPS", "name": "Operations isolations and testing", "capacity": 1, "calendar_id": "DAY", "disjoint": True, "interchangeable": True},
            {"id": "QA", "name": "Quality inspection", "capacity": 1, "calendar_id": "DAY", "disjoint": True, "interchangeable": True},
            {"id": "ELEC", "name": "Electrical testing", "capacity": 1, "calendar_id": "DAY", "disjoint": True, "interchangeable": True},
        ],
        "activities": [
            _activity("A01", "Isolate conveyor and establish access", 2, [], ("OPS", 1)),
            _activity("A02", "Remove chute covers", 4, ["A01"], ("MECH", 2)),
            _activity("A03", "Inspect chute and confirm liner scope", 2, ["A02"], ("QA", 1)),
            _activity("A04", "Replace chute liners", 12, ["A03"], ("MECH", 2)),
            _activity("A05", "Repair feed skirt", 4, ["A02"], ("MECH", 1)),
            _activity("A06", "Prepare restart test equipment", 4, ["A02"], ("ELEC", 1), not_before=62),
            _activity("A07", "Refit chute covers", 4, ["A04", "A05"], ("MECH", 2)),
            _activity("A08", "Complete final quality inspection", 2, ["A07"], ("QA", 1)),
            _activity("A09", "Perform functional restart test", 3, ["A06", "A08"], ("OPS", 1), ("ELEC", 1)),
            _activity("A10", "Return conveyor to service", 0, ["A09"]),
        ],
    }


def new_trial_workspace() -> dict:
    """Return the identical pristine, independently validated approved plan."""
    workspace = {
        "schema": GROUP_SCHEMA,
        "project": _project(),
        "reports": [],
        "approved_plan": None,
        "proposal": None,
        "plan_history": [],
    }
    validate(workspace)
    plan = propose(workspace)
    if plan["project_finish"] != STARTING_FINISH:
        raise RuntimeError("trial starting-plan oracle changed")
    approve(workspace, "trial-owner")
    # Approval metadata is deliberately fixed so every participant receives
    # the same pristine artifact. It is not part of the plan hash.
    workspace["approved_plan"]["approved_at"] = "2026-09-22T00:00:00+00:00"
    validate(workspace)
    validate_stored_plans(workspace)
    return deepcopy(workspace)


def build_sha() -> str:
    """Resolve the deployed source identity without retaining server state."""
    for key in ("PM_BUILD_SHA", "VERCEL_GIT_COMMIT_SHA", "GITHUB_SHA"):
        value = os.environ.get(key, "").strip()
        if value:
            return value
    try:
        root = Path(__file__).resolve().parents[3]
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, check=True,
            capture_output=True, text=True, timeout=2,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def trial_metadata() -> dict:
    return {
        "id": TRIAL_ID,
        "name": TRIAL_NAME,
        "version": TRIAL_VERSION,
        "build_sha": build_sha(),
        "status_point": STATUS_POINT,
        "starting_finish": STARTING_FINISH,
        "recovered_finish": RECOVERED_FINISH,
    }
