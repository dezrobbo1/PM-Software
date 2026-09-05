from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from hashlib import sha256
import json

from deterministic_scheduling_core.project.model import (
    Activity,
    ExecutionMode,
    Project,
    Resource,
    ResourceRequirement,
)
from deterministic_scheduling_core.scheduling import ScheduleResult, schedule_project


TICKS_PER_HOUR = 4
OUTAGE_ACTIVITY_ID = "FIELD-OUTAGE-CRANE"


@dataclass(frozen=True, slots=True)
class FieldEvent:
    event_id: str
    subject_id: str
    event_type: str
    occurred_at: int
    received_at: int
    payload: int | str | tuple[str, int, int]
    epistemic_status: str
    scheduling_role: str
    source: str
    actor_role: str
    evidence: str | None = None
    validated_by: str | None = None
    supersedes_event_id: str | None = None


@dataclass(frozen=True, slots=True)
class TrustedProjectState:
    accepted_event_ids: tuple[str, ...]
    actual_starts: tuple[tuple[str, int], ...]
    remaining_durations: tuple[tuple[str, int], ...]
    resource_outages: tuple[tuple[str, int, int], ...]
    inspection_facts: tuple[tuple[str, str], ...]
    committed_emergent_work: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class ReplanRecord:
    event_id: str
    authoritative: bool
    moved_activities: int
    total_start_movement: int
    plan_hash: str
    protective_gate: bool = False


@dataclass(frozen=True, slots=True)
class PathResult:
    name: str
    final_project: Project
    final_schedule: ScheduleResult
    records: tuple[ReplanRecord, ...]
    untrusted_authoritative_replans: int
    corrected_authoritative_replans: int
    corrected_report_moved_activities: int
    corrected_report_start_movement: int


@dataclass(frozen=True, slots=True)
class CandidateResult:
    path: PathResult
    ledger: tuple[FieldEvent, ...]
    trusted_state: TrustedProjectState
    trusted_state_hash: str
    provisional_records: tuple[ReplanRecord, ...]
    replay_state_hash: str
    replay_plan_hash: str


@dataclass(frozen=True, slots=True)
class ExperimentResult:
    approved_project: Project
    approved_schedule: ScheduleResult
    events: tuple[FieldEvent, ...]
    direct: PathResult
    candidate: CandidateResult
    final_plans_match: bool
    replay_matches: bool
    final_actual_start_is_correct: bool
    forecast_duration_is_not_history: bool
    emergent_work_waited_for_approval: bool
    falsified: bool


def _req(*resource_ids: str) -> tuple[ResourceRequirement, ...]:
    return tuple(ResourceRequirement(resource_id) for resource_id in resource_ids)


def _mode(
    mode_id: str,
    duration: int,
    *resource_ids: str,
    name: str | None = None,
) -> tuple[ExecutionMode, ...]:
    return (ExecutionMode(mode_id, duration, _req(*resource_ids), name),)


def _activity(
    activity_id: str,
    name: str,
    duration: int,
    *resource_ids: str,
    pred: tuple[str, ...] = (),
    not_before: int = 0,
    milestone: bool = False,
) -> Activity:
    return Activity(
        id=activity_id,
        name=name,
        modes=_mode(
            "MILESTONE" if milestone else "FIXED",
            0 if milestone else duration,
            *resource_ids,
        ),
        predecessors=pred,
        not_before=not_before,
        kind="milestone" if milestone else "task",
    )


def build_base_project() -> Project:
    """Create the 20-activity execution case used by both field-state paths."""

    activities = (
        _activity("A01", "Issue work permit", 1),
        _activity("A02", "Establish isolation", 2, "MECH", pred=("A01",)),
        _activity("A03", "Verify isolation", 1, "INSPECT", pred=("A02",)),
        _activity(
            "A04",
            "Open workface",
            2,
            "MECH",
            pred=("A03",),
            not_before=4,
        ),
        _activity("A05", "Remove access cover", 4, "MECH", "CRANE", pred=("A04",)),
        _activity("A06", "Inspect internals", 2, "INSPECT", pred=("A05",)),
        Activity(
            id="A07",
            name="Emergent repair slot",
            modes=(
                ExecutionMode("NO-WORK", 0),
                ExecutionMode("REPAIR", 8, _req("MECH")),
            ),
            predecessors=("A06",),
            frozen_mode_id="NO-WORK",
        ),
        _activity("A08", "Repair component", 8, "MECH", pred=("A07",)),
        _activity("A09", "QA repair", 2, "INSPECT", pred=("A08",)),
        _activity("A10", "Reinstall cover", 4, "MECH", "CRANE", pred=("A09",)),
        _activity("A11", "Final torque", 2, "MECH", pred=("A10",)),
        _activity("A12", "Isolate electrical", 2, "E&I", pred=("A03",)),
        _activity("A13", "Electrical inspection", 4, "E&I", pred=("A12",)),
        _activity("A14", "Electrical maintenance", 8, "E&I", pred=("A13",)),
        _activity("A15", "Electrical test", 4, "E&I", pred=("A14",)),
        _activity("A16", "Clean ancillary line", 6, "MECH", pred=("A04",)),
        _activity("A17", "Inspect ancillary line", 2, "INSPECT", pred=("A16",)),
        _activity("A18", "Close ancillary line", 4, "MECH", pred=("A17",)),
        _activity(
            "A19",
            "Functional test",
            4,
            "E&I",
            pred=("A11", "A15", "A18"),
        ),
        _activity("A20", "Protected handover", 0, pred=("A19",), milestone=True),
    )
    return Project(
        id="trusted-live-state-poc",
        name="Trusted live state falsification experiment",
        activities=activities,
        resources=(
            Resource("MECH", "Mechanical pooled crew", 2),
            Resource("E&I", "Electrical/instrument pooled crew", 1),
            Resource("CRANE", "Crane C04", 1),
            Resource("INSPECT", "Inspection capability", 1),
        ),
        objective_activity_id="A20",
        time_unit="15min",
    )


def build_approved_project() -> tuple[Project, ScheduleResult]:
    """Create a deterministic approved reference plan V0."""

    raw = build_base_project()
    first = schedule_project(raw)
    activities = tuple(
        replace(
            activity,
            planned_start=first.by_id[activity.id].start,
            planned_mode_id=first.by_id[activity.id].mode_id,
        )
        for activity in raw.activities
    )
    approved = replace(raw, activities=activities)
    approved_schedule = schedule_project(approved)
    return approved, approved_schedule


def build_field_events(
    approved_project: Project,
    approved_schedule: ScheduleResult,
) -> tuple[FieldEvent, ...]:
    """Create four field circumstances plus the evidence/validation needed to resolve them."""

    cover_start = approved_schedule.by_id["A05"].start
    repair_mode = approved_project.activity_by_id["A08"].modes[0]
    crane_window_start = approved_schedule.by_id["A10"].start + 8
    crane_window_finish = crane_window_start + (3 * TICKS_PER_HOUR)
    inspection_finish = approved_schedule.by_id["A06"].finish

    return (
        FieldEvent(
            "E01",
            "A05",
            "actual_start",
            cover_start + 3,
            101,
            cover_start + 3,
            "REPORTED",
            "HISTORICAL_ACTUAL",
            "field-supervisor",
            "supervisor",
        ),
        FieldEvent(
            "E02",
            "A05",
            "actual_start",
            cover_start + 2,
            102,
            cover_start + 2,
            "VALIDATED",
            "HISTORICAL_ACTUAL",
            "access-log",
            "planner",
            evidence="access log confirms a 30-minute late start",
            validated_by="planner",
            supersedes_event_id="E01",
        ),
        FieldEvent(
            "E03",
            "A08",
            "remaining_duration",
            inspection_finish,
            103,
            repair_mode.duration + (2 * TICKS_PER_HOUR),
            "REPORTED",
            "FORECAST_ASSUMPTION",
            "field-supervisor",
            "supervisor",
        ),
        FieldEvent(
            "E04",
            "A08",
            "remaining_duration",
            inspection_finish,
            104,
            repair_mode.duration + TICKS_PER_HOUR,
            "VALIDATED",
            "FORECAST_ASSUMPTION",
            "planner-review",
            "planner",
            evidence="joint review reduced the estimate to one additional hour",
            validated_by="planner",
            supersedes_event_id="E03",
        ),
        FieldEvent(
            "E05",
            "CRANE",
            "resource_outage",
            crane_window_start,
            106,
            ("CRANE", crane_window_start, crane_window_finish),
            "REPORTED",
            "CURRENT_OPERATIONAL_FACT",
            "crane-operator",
            "operator",
        ),
        FieldEvent(
            "E06",
            "CRANE",
            "resource_outage",
            crane_window_start,
            107,
            ("CRANE", crane_window_start, crane_window_finish),
            "VALIDATED",
            "CURRENT_OPERATIONAL_FACT",
            "maintenance-control",
            "controller",
            evidence="maintenance control confirmed the outage interval",
            validated_by="controller",
            supersedes_event_id="E05",
        ),
        FieldEvent(
            "E07",
            "A07",
            "emergent_scope",
            inspection_finish,
            105,
            6 * TICKS_PER_HOUR,
            "REPORTED",
            "PROPOSED_CHANGE",
            "inspector",
            "inspector",
            evidence="damage found during internal inspection",
        ),
        FieldEvent(
            "E08",
            "A06",
            "inspection_result",
            inspection_finish,
            108,
            "damage-confirmed",
            "VALIDATED",
            "HISTORICAL_ACTUAL",
            "inspection-authority",
            "inspector",
            evidence="inspection disposition confirms damage",
            validated_by="inspection-authority",
        ),
        FieldEvent(
            "E09",
            "A07",
            "emergent_scope",
            inspection_finish,
            109,
            2 * TICKS_PER_HOUR,
            "VALIDATED",
            "COMMITTED_FUTURE",
            "scope-approval",
            "project-manager",
            evidence="approved two-hour emergent repair package",
            validated_by="project-manager",
            supersedes_event_id="E07",
        ),
    )


def _set_activity(project: Project, activity_id: str, **changes: object) -> Project:
    activities = tuple(
        replace(activity, **changes) if activity.id == activity_id else activity
        for activity in project.activities
    )
    if activities == project.activities:
        raise KeyError(activity_id)
    return replace(project, activities=activities)


def _set_mode_duration(
    project: Project,
    activity_id: str,
    mode_id: str,
    duration: int,
) -> Project:
    changed = False
    activities: list[Activity] = []
    for activity in project.activities:
        if activity.id != activity_id:
            activities.append(activity)
            continue
        modes: list[ExecutionMode] = []
        for mode in activity.modes:
            if mode.id == mode_id:
                modes.append(replace(mode, duration=duration))
                changed = True
            else:
                modes.append(mode)
        activities.append(replace(activity, modes=tuple(modes)))
    if not changed:
        raise KeyError(f"{activity_id}/{mode_id}")
    return replace(project, activities=tuple(activities))


def _upsert_outage(project: Project, resource_id: str, start: int, finish: int) -> Project:
    resource = project.resource_by_id[resource_id]
    without = tuple(
        activity for activity in project.activities if activity.id != OUTAGE_ACTIVITY_ID
    )
    outage = Activity(
        id=OUTAGE_ACTIVITY_ID,
        name=f"Validated outage for {resource.name}",
        modes=(
            ExecutionMode(
                "OUTAGE",
                finish - start,
                (ResourceRequirement(resource_id, resource.capacity),),
            ),
        ),
        frozen_start=start,
        frozen_mode_id="OUTAGE",
    )
    return replace(project, activities=without + (outage,))


def apply_field_event_direct(project: Project, event: FieldEvent) -> Project:
    """Control path: treat every incoming scheduling report as authoritative immediately."""

    if event.event_type == "actual_start":
        activity = project.activity_by_id[event.subject_id]
        mode_id = activity.planned_mode_id or activity.modes[0].id
        return _set_activity(
            project,
            event.subject_id,
            frozen_start=int(event.payload),
            frozen_mode_id=mode_id,
        )
    if event.event_type == "remaining_duration":
        return _set_mode_duration(
            project,
            event.subject_id,
            project.activity_by_id[event.subject_id].modes[0].id,
            int(event.payload),
        )
    if event.event_type == "resource_outage":
        resource_id, start, finish = event.payload
        return _upsert_outage(project, resource_id, start, finish)
    if event.event_type == "emergent_scope":
        project = _set_mode_duration(
            project,
            event.subject_id,
            "REPAIR",
            int(event.payload),
        )
        return _set_activity(project, event.subject_id, frozen_mode_id="REPAIR")
    return project


def project_trusted_state(events: tuple[FieldEvent, ...]) -> TrustedProjectState:
    """Materialise trusted current state from validated events, independent of arrival order."""

    accepted = sorted(
        (event for event in events if event.epistemic_status == "VALIDATED"),
        key=lambda event: (event.occurred_at, event.event_id),
    )
    actual_starts: dict[str, int] = {}
    remaining_durations: dict[str, int] = {}
    resource_outages: dict[str, tuple[int, int]] = {}
    inspection_facts: dict[str, str] = {}
    emergent_work: dict[str, int] = {}

    for event in accepted:
        if event.event_type == "actual_start":
            actual_starts[event.subject_id] = int(event.payload)
        elif event.event_type == "remaining_duration":
            remaining_durations[event.subject_id] = int(event.payload)
        elif event.event_type == "resource_outage":
            resource_id, start, finish = event.payload
            resource_outages[resource_id] = (start, finish)
        elif event.event_type == "inspection_result":
            inspection_facts[event.subject_id] = str(event.payload)
        elif event.event_type == "emergent_scope":
            emergent_work[event.subject_id] = int(event.payload)

    return TrustedProjectState(
        accepted_event_ids=tuple(sorted(event.event_id for event in accepted)),
        actual_starts=tuple(sorted(actual_starts.items())),
        remaining_durations=tuple(sorted(remaining_durations.items())),
        resource_outages=tuple(
            sorted((resource_id, start, finish) for resource_id, (start, finish) in resource_outages.items())
        ),
        inspection_facts=tuple(sorted(inspection_facts.items())),
        committed_emergent_work=tuple(sorted(emergent_work.items())),
    )


def compile_trusted_state(base_project: Project, state: TrustedProjectState) -> Project:
    """Compile the materialised trusted state into the unchanged native scheduling model."""

    project = base_project
    for activity_id, start in state.actual_starts:
        activity = project.activity_by_id[activity_id]
        project = _set_activity(
            project,
            activity_id,
            frozen_start=start,
            frozen_mode_id=activity.planned_mode_id or activity.modes[0].id,
        )
    for activity_id, duration in state.remaining_durations:
        project = _set_mode_duration(
            project,
            activity_id,
            project.activity_by_id[activity_id].modes[0].id,
            duration,
        )
    for activity_id, duration in state.committed_emergent_work:
        project = _set_mode_duration(project, activity_id, "REPAIR", duration)
        project = _set_activity(project, activity_id, frozen_mode_id="REPAIR")
    for resource_id, start, finish in state.resource_outages:
        project = _upsert_outage(project, resource_id, start, finish)
    return project


def _hash_json(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(encoded).hexdigest()


def trusted_state_hash(state: TrustedProjectState) -> str:
    return _hash_json(asdict(state))


def schedule_hash(schedule: ScheduleResult) -> str:
    return _hash_json(
        [
            {
                "activity_id": entry.activity_id,
                "mode_id": entry.mode_id,
                "start": entry.start,
                "finish": entry.finish,
            }
            for entry in sorted(schedule.entries, key=lambda item: item.activity_id)
        ]
    )


def _movement(before: ScheduleResult, after: ScheduleResult) -> tuple[int, int]:
    common = set(before.by_id) & set(after.by_id)
    deltas = [
        abs(after.by_id[activity_id].start - before.by_id[activity_id].start)
        for activity_id in common
        if after.by_id[activity_id].start != before.by_id[activity_id].start
    ]
    return len(deltas), sum(deltas)


def _corrected_report_ids(events: tuple[FieldEvent, ...]) -> set[str]:
    by_id = {event.event_id: event for event in events}
    corrected: set[str] = set()
    for event in events:
        if event.supersedes_event_id is None:
            continue
        prior = by_id[event.supersedes_event_id]
        if prior.payload != event.payload:
            corrected.add(prior.event_id)
    return corrected


def run_direct_mutation(
    approved_project: Project,
    approved_schedule: ScheduleResult,
    events: tuple[FieldEvent, ...],
) -> PathResult:
    project = approved_project
    schedule = approved_schedule
    records: list[ReplanRecord] = []
    corrected_ids = _corrected_report_ids(events)

    for event in events:
        changed = apply_field_event_direct(project, event)
        if changed == project:
            continue
        next_schedule = schedule_project(changed)
        moved, movement = _movement(schedule, next_schedule)
        records.append(
            ReplanRecord(
                event.event_id,
                True,
                moved,
                movement,
                schedule_hash(next_schedule),
            )
        )
        project = changed
        schedule = next_schedule

    corrected_records = [record for record in records if record.event_id in corrected_ids]
    return PathResult(
        name="direct-mutation",
        final_project=project,
        final_schedule=schedule,
        records=tuple(records),
        untrusted_authoritative_replans=sum(
            1
            for record in records
            if next(event for event in events if event.event_id == record.event_id).epistemic_status
            != "VALIDATED"
        ),
        corrected_authoritative_replans=len(corrected_records),
        corrected_report_moved_activities=sum(record.moved_activities for record in corrected_records),
        corrected_report_start_movement=sum(
            record.total_start_movement for record in corrected_records
        ),
    )


def run_trusted_pipeline(
    approved_project: Project,
    approved_schedule: ScheduleResult,
    events: tuple[FieldEvent, ...],
) -> CandidateResult:
    ledger: list[FieldEvent] = []
    current_state = project_trusted_state(())
    current_project = approved_project
    current_schedule = approved_schedule
    authoritative_records: list[ReplanRecord] = []
    provisional_records: list[ReplanRecord] = []

    for event in events:
        ledger.append(event)
        if event.epistemic_status != "VALIDATED":
            provisional_project = apply_field_event_direct(current_project, event)
            if provisional_project != current_project:
                provisional_schedule = schedule_project(provisional_project)
                moved, movement = _movement(current_schedule, provisional_schedule)
                provisional_records.append(
                    ReplanRecord(
                        event.event_id,
                        False,
                        moved,
                        movement,
                        schedule_hash(provisional_schedule),
                        protective_gate=(event.event_type == "resource_outage"),
                    )
                )
            continue

        next_state = project_trusted_state(tuple(ledger))
        next_project = compile_trusted_state(approved_project, next_state)
        if next_project != current_project:
            next_schedule = schedule_project(next_project)
            moved, movement = _movement(current_schedule, next_schedule)
            authoritative_records.append(
                ReplanRecord(
                    event.event_id,
                    True,
                    moved,
                    movement,
                    schedule_hash(next_schedule),
                )
            )
            current_project = next_project
            current_schedule = next_schedule
        current_state = next_state

    replay_order = tuple(
        sorted(
            ledger,
            key=lambda event: (event.received_at % 3, -event.received_at, event.event_id),
        )
    )
    replay_state = project_trusted_state(replay_order)
    replay_project = compile_trusted_state(approved_project, replay_state)
    replay_schedule = schedule_project(replay_project)

    path = PathResult(
        name="trusted-state",
        final_project=current_project,
        final_schedule=current_schedule,
        records=tuple(authoritative_records),
        untrusted_authoritative_replans=0,
        corrected_authoritative_replans=0,
        corrected_report_moved_activities=0,
        corrected_report_start_movement=0,
    )
    return CandidateResult(
        path=path,
        ledger=tuple(ledger),
        trusted_state=current_state,
        trusted_state_hash=trusted_state_hash(current_state),
        provisional_records=tuple(provisional_records),
        replay_state_hash=trusted_state_hash(replay_state),
        replay_plan_hash=schedule_hash(replay_schedule),
    )


def run_experiment() -> ExperimentResult:
    approved_project, approved_schedule = build_approved_project()
    events = build_field_events(approved_project, approved_schedule)
    direct = run_direct_mutation(approved_project, approved_schedule, events)
    candidate = run_trusted_pipeline(approved_project, approved_schedule, events)

    final_plans_match = schedule_hash(direct.final_schedule) == schedule_hash(
        candidate.path.final_schedule
    )
    replay_matches = (
        candidate.trusted_state_hash == candidate.replay_state_hash
        and schedule_hash(candidate.path.final_schedule) == candidate.replay_plan_hash
    )
    expected_actual = approved_schedule.by_id["A05"].start + 2
    final_actual_start_is_correct = dict(candidate.trusted_state.actual_starts).get("A05") == expected_actual
    forecast_duration_is_not_history = (
        "A08" in dict(candidate.trusted_state.remaining_durations)
        and "A08" not in dict(candidate.trusted_state.actual_starts)
    )

    before_scope_approval = run_trusted_pipeline(
        approved_project,
        approved_schedule,
        events[:-1],
    )
    emergent_work_waited_for_approval = (
        before_scope_approval.path.final_schedule.by_id["A07"].mode_id == "NO-WORK"
        and candidate.path.final_schedule.by_id["A07"].mode_id == "REPAIR"
    )

    falsified = not (
        final_plans_match
        and replay_matches
        and final_actual_start_is_correct
        and forecast_duration_is_not_history
        and emergent_work_waited_for_approval
        and direct.corrected_authoritative_replans > 0
        and direct.corrected_report_start_movement > 0
        and candidate.path.untrusted_authoritative_replans == 0
        and any(record.protective_gate for record in candidate.provisional_records)
    )
    return ExperimentResult(
        approved_project=approved_project,
        approved_schedule=approved_schedule,
        events=events,
        direct=direct,
        candidate=candidate,
        final_plans_match=final_plans_match,
        replay_matches=replay_matches,
        final_actual_start_is_correct=final_actual_start_is_correct,
        forecast_duration_is_not_history=forecast_duration_is_not_history,
        emergent_work_waited_for_approval=emergent_work_waited_for_approval,
        falsified=falsified,
    )


def _ticks(value: int) -> str:
    hours, remainder = divmod(value, TICKS_PER_HOUR)
    minutes = remainder * 15
    return f"{hours}h{minutes:02d}m"


def main() -> int:
    result = run_experiment()
    direct = result.direct
    candidate = result.candidate

    print("TRUSTED LIVE PROJECT STATE — BOUNDED FALSIFICATION EXPERIMENT")
    print("Architecture under test: field event -> validation -> trusted state -> unchanged native scheduler")
    print(f"Approved activities: {len(result.approved_project.activities)}")
    print(f"Approved handover: {_ticks(result.approved_schedule.objective_finish)}")
    print(f"Field/provenance events retained: {len(result.events)}")
    print()
    print("DIRECT MUTATION CONTROL")
    print(f"  authoritative replans: {len(direct.records)}")
    print(f"  replans from unvalidated reports: {direct.untrusted_authoritative_replans}")
    print(f"  replans later corrected: {direct.corrected_authoritative_replans}")
    print(
        "  churn caused by later-corrected reports: "
        f"{direct.corrected_report_moved_activities} moved starts / "
        f"{_ticks(direct.corrected_report_start_movement)} total start movement"
    )
    print(f"  final handover: {_ticks(direct.final_schedule.objective_finish)}")
    print()
    print("TRUSTED-STATE CANDIDATE")
    print(f"  provisional impact calculations: {len(candidate.provisional_records)}")
    print(f"  authoritative replans: {len(candidate.path.records)}")
    print(f"  replans from unvalidated reports: {candidate.path.untrusted_authoritative_replans}")
    print(f"  retained accepted events: {', '.join(candidate.trusted_state.accepted_event_ids)}")
    print(f"  final handover: {_ticks(candidate.path.final_schedule.objective_finish)}")
    print(
        "  actual start A05: "
        f"{_ticks(dict(candidate.trusted_state.actual_starts)['A05'])} "
        "(validated history; solver cannot move it)"
    )
    print(
        "  A08 remaining duration: "
        f"{_ticks(dict(candidate.trusted_state.remaining_durations)['A08'])} "
        "(validated forecast assumption, not history)"
    )
    print(
        "  emergent repair: "
        f"{candidate.path.final_schedule.by_id['A07'].mode_id} "
        "only after explicit scope approval"
    )
    print(f"  event-order replay reproduces state + plan: {result.replay_matches}")
    print(f"  final direct and trusted-state plans match: {result.final_plans_match}")
    print()
    if result.falsified:
        print("RESULT: trusted-state hypothesis FALSIFIED or materially weakened")
        return 1
    print("RESULT: trusted-state hypothesis NOT FALSIFIED by this bounded experiment")
    print(
        "Learning: the project state can stay live while unvalidated reports remain provisional; "
        "the authoritative schedule is recalculated only from accepted state."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
