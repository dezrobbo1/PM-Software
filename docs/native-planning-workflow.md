# Editable native planning workflow

This is the next integrated POC after PR #24. It connects editable native inputs, authorised activity-mode choice, productive calendars, physical resource allocation, a reported/accepted availability change, explicit plan approval, and save/reopen in one workflow. It does not require Microsoft Project, P6 or editing Python.

## Run the complete demonstration

From a checkout of the implementation branch:

```bash
python -m pip install -e .
python -m deterministic_scheduling_core.native_planning_workflow demo /tmp/pm-workspace-demo.json
```

Choose a new output path: `demo` and `init` refuse to overwrite an existing workspace.

The demonstration uses the same persistence and scheduling functions as the interactive commands. It creates eight activities, solves both authorised repair modes, saves the approved plan, records an unaccepted future outage, accepts the outage, calculates a separate recovery proposal, explicitly approves that proposal, then saves and reopens the full JSON workspace. Assertions check that the reported-only change leaves the approved plan and trusted-input hash unchanged, and that the complete final JSON round trip is identical.

The fixture checks these results:

| State | Repair mode | Controlling finish | Approval behaviour |
|---|---|---|---|
| Initial plan | SPECIALIST | Day 1 15:00 | Explicitly approved |
| M2 outage merely reported | Approved SPECIALIST retained | Day 1 15:00 | Trusted inputs unchanged |
| M2 outage accepted for Day 1 10:00–17:00 | NORMAL recovery proposal | Day 2 08:30 | Old approved plan retained and marked stale |
| Recovery approved and reopened | NORMAL | Day 2 08:30 | Previous approved plan remains in history |

The initial specialist repair consumes three productive hours: Day 1 10:00–12:00 and 12:30–13:30. M1 and M2 are assigned to separate simultaneous slots. Both rigging tasks retain pooled requirements and receive an independent physical allocation witness. The output shows changed dates, modes and assignments, accepted input reports and calculated objective results for the authorised alternatives.

## Use it yourself

```bash
python -m deterministic_scheduling_core.native_planning_workflow init my-plan.json
python -m deterministic_scheduling_core.native_planning_workflow plan my-plan.json
python -m deterministic_scheduling_core.native_planning_workflow approve my-plan.json --by planner

python -m deterministic_scheduling_core.native_planning_workflow report-unavailable my-plan.json --resource M2 --start 1@10:00 --finish 1@17:00 --by supervisor --reason "Expected specialist absence"
python -m deterministic_scheduling_core.native_planning_workflow show my-plan.json

python -m deterministic_scheduling_core.native_planning_workflow accept-report my-plan.json E001 --by planner
python -m deterministic_scheduling_core.native_planning_workflow plan my-plan.json
python -m deterministic_scheduling_core.native_planning_workflow approve my-plan.json --by planner
python -m deterministic_scheduling_core.native_planning_workflow show my-plan.json
```

`day@HH:MM` uses relative project days, not real dated/time-zone scheduling. Day 1 begins at tick zero; one tick is 30 minutes. Thus `2@08:30` is tick 65.

Change productive work with a command:

```bash
python -m deterministic_scheduling_core.native_planning_workflow set-work my-plan.json A03 NORMAL --hours 5.5
python -m deterministic_scheduling_core.native_planning_workflow plan my-plan.json
```

Or edit the native `project` object in JSON: activity names, predecessors, release ticks, authorised modes, processing ticks, eligibility sets and daily calendars. The scheduler consumes these values, not hidden fixture outputs. Recalculate after editing inputs. Do not edit calculated plan records to issue planning instructions.

## What is saved

The workspace contains native project inputs, original reports and acceptance metadata, the approved execution plan, an unapproved proposal and previous approved plans. Each calculated plan includes its trusted source snapshot, source hash, reference-plan hash, chosen modes, actual productive periods, named assignments or deferred pool slots, physical allocation witness, objective results, alternative evaluations, and solver version/configuration.

Report acceptance and plan approval are separate. Accepting a report does not rewrite the approved plan. A recovery remains a proposal until explicitly approved. A failed recovery does not reject the accepted report or erase the previous plan; the old plan is visibly stale. Input edits invalidate pending proposals and stale proposals cannot be approved.

## Implementation choices and limits

The new JSON profile is a bounded native POC alongside the original `Project` profile, not a wholesale schema migration. Native data and persistence are under `project/planning_workspace.py`; scheduling is under `scheduling/planning_workspace.py`; the command entry point is `native_planning_workflow.py`.

The compiler reuses PR #24's productive placement generation and independent exact assignment checker. It provisionally uses selective assignment. The two-rigger pool is retained only when both resources are genuinely interchangeable under the current input. If an accepted availability change breaks that equivalence, the compiler falls back to explicit physical assignments rather than silently retaining an invalid pool. This does not settle the earlier pooled-master versus integrated-assignment architectural question.

The declared policy is: controlling finish (zero allowed degradation), then preserve approved activity modes, minimise total start movement, preserve named assignments, then the weighted activity-start timing score. The code exhaustively evaluates at most 16 authorised activity-mode combinations. It is a bounded full replan with stability objectives, not adaptive-neighbourhood integration. Identical objective assignments need not be unique.

Repeatability means observed identical output under the same input ordering, solver version, parameters and environment. Hashes do not prove unique assignments or cross-version/platform reproducibility. This is also the clarification accepted in the PR #24 review; its legacy `canonical_signature` name must not be read as a stronger guarantee.

This loop supports future productive work, finish-to-start dependencies, capacity-one physical resources and daily calendar windows. It does not integrate partially completed work, actual-history scheduling, unrestricted handovers, structural alternative activity subgraphs, elapsed curing processes, arbitrary calendar recurrence, a browser UI or authenticated approval authority. Actor names record local single-user decisions; they are not an enterprise authorisation system. Accepted availability intervals are forecast assumptions, not historical actuals.

## Validation

```bash
python -m unittest tests.test_native_planning_workflow -v
```

The existing POC smoke workflow also runs the prior suite, these twelve workflow tests, the full command demonstration and compilation. Its `native-planning-workflow` artifact contains the saved example workspace and demonstration log. Previous experiment modules remain unchanged.

The next useful evaluation is to edit this small workspace and inspect the resulting planning decisions, not to require another general architecture or hardening programme before using it.
