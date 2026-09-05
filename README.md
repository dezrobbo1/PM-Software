# PM-Software — deterministic AI project-management research

**Status: exploratory R&D / proof of concept**

## Aim

This project investigates whether modern technology can enable a **new, better and leaner approach to professional project planning, scheduling and execution control**.

The original technical idea is a **deterministic AI core**: a trustworthy computational core that can reason about project logic, resources, operational constraints, alternatives and changing execution conditions, while modern AI can assist where it adds genuine value.

We are not trying to copy Primavera P6 or Microsoft Project. Existing products are useful sources of knowledge, comparison and future interchange, but they do not define our architecture, semantics or product model.

## Working loop

**Research → Idea → Prototype → Test → Learn → Next experiment**

Before substantial work, ask:

> **What will we be able to do, demonstrate or know after this that we cannot do or know now?**

Research, documentation, tests, refactoring, validation, compatibility work and hardening support the project. They are not progress by themselves.

## Progress so far

**Gate 1 through Gate 5 are provisionally demonstrated.**

- Gate 1: feasible resource-constrained scheduling and a better whole-project sequence than a fixed-priority baseline.
- Gate 2: context-sensitive execution-mode choice; the locally fastest activity mode is not always the best project decision.
- Gate 3: permit/access and workface constraints can change a mathematically shorter but non-executable plan into an executable one.
- Gate 4: a small execution disturbance can be propagated while preserving work that does not need to move and explaining the consequence.
- Gate 5: a real shutdown schedule slice contained a declared resource overload; the core removed it while preserving `Stage 2 Detag Complete`, and the experienced practitioner accepted the result.

These are proof-of-concept results, not production scheduling claims.

## Native product boundary

Prototype 1 proved that a real Microsoft Project XML schedule can expose a real planning problem to the experimental core. That was useful evidence, but Microsoft Project must not become the centre of the product architecture.

The active dependency direction is:

```text
Microsoft Project XML ─┐
P6/XER later           ├──> external adapters ──> PM-Software native project ──> native scheduler/core
manual/native input ───┘
```

External-system fields stop at adapter boundaries. The native project model and scheduling core must not depend on Microsoft Project, P6 or any other scheduling package.

`prototype1_workspace.py` remains as a completed real-file bridge: MSPDI is translated into the PM-Software native model before scheduling.

## Prototype 2 — Native Project Core

Prototype 2 established that PM-Software can exist and operate without Microsoft Project in the workflow.

```bash
python -m deterministic_scheduling_core.prototype2_native /tmp/pm-native-project.json
```

It creates a native PM-Software project, saves and reopens it, optimises it, changes a project fact and recalculates a different whole-project execution-mode decision.

The current native model has first-class concepts for projects, activities/milestones, finish-to-start precedence, resources/capacity demand, alternative activity execution modes, not-before/latest-finish boundaries, workface-style exclusion groups, planned/frozen coordinates and a controlling objective activity.

The native scheduler consumes only that model. It has no MSPDI dependency.

## Planning-model experiment — Work–Method–Execution

Targeted research then challenged a deeper assumption: **must the planner completely choose one activity network before the scheduling engine can reason about the project?**

The bounded working hypothesis is:

```text
required work / outcome
        ↓
finite authorised execution methods
        ↓
method-specific activities and activity modes
        ↓
integrated method + resource + sequence + timing decision
        ↓
explicit execution plan
```

Activities remain the executable primitives. The engine is not allowed to invent scope or arbitrary work methods; it may choose only among explicit authorised alternatives.

The first falsification experiment is runnable with:

```bash
python -m deterministic_scheduling_core.work_method_experiment
```

It compares the same six-work-package planning problem two ways:

1. **Control oracle:** materialise and solve all 8 authorised fixed activity-network structures with the existing native scheduler.
2. **Candidate:** hold all authorised methods once and select method + activity mode + timing jointly in one bounded model.

The case contains 33 possible activities, pooled and named resources, alternative qualified inspectors, a named crane, one workface exclusion, a protected handoff, a crane outage, a specialist-availability change and a narrowed access/permit condition.

The candidate matched the exhaustive fixed-network oracle in all three scenarios:

| Scenario | Best fixed-network oracle | Work–Method candidate | Structural decision |
|---|---:|---:|---|
| A — normal conditions | H37 | H37 | SCAFFOLD / CRANE / NORMAL |
| B — crane unavailable H10–H18 | H41 | H41 | SCAFFOLD / SEGMENTED / NORMAL |
| C — specialist earlier, scaffold limit H09 | H35 | H35 | ROPE / CRANE / SPECIALIST |

The changed conditions caused three authorised method reselections without a human editing activity topology. Scenario B replaced four crane-method activities with four segmented-removal activities. Scenario C replaced seven baseline activities with six activities from the rope-access and specialist methods.

The bounded representation held **33 activity facts and 33 relationship facts** once, compared with **180 activity facts and 176 relationship facts** across the eight materialised fixed networks.

**Result: the Work–Method–Execution hypothesis was not falsified by this bounded experiment.**

That is useful evidence, not a settled product architecture. The experiment remains isolated in `work_method_experiment.py`; the production `Project` model has not yet been expanded into a general WorkPackage/ExecutionMethod ontology.

This result does **not** justify unrestricted goal/state planning, automatic invention of work methods, or treating CP-SAT as the permanent engine.

## Execution-state experiment — Trusted Live Project State

The latest targeted research challenged another assumption: **should incoming field reports directly update the authoritative schedule, or should the schedule be derived from trusted live project state?**

The bounded hypothesis is:

```text
field reality
    ↓
reported event + provenance
    ↓
validation / acceptance
    ↓
trusted project state
    ↓
unchanged deterministic scheduler
    ↓
executable plan
```

Unvalidated reports may be used for provisional impact analysis, but they do not replace authoritative project state. Validated historical facts are non-optimisable; validated future estimates remain forecast assumptions; emergent scope becomes executable only after explicit approval.

The falsification experiment is runnable with:

```bash
python -m deterministic_scheduling_core.trusted_state_experiment
```

It uses the same 20-activity native project and compares direct mutation against a bounded event/provenance + trusted-state projection. The event sequence contains an initially wrong actual-start report, a remaining-duration estimate, a three-hour crane outage and inspection-created emergent work.

Observed result:

- approved handover: **8h00m**;
- direct mutation: **7 authoritative replans**, including **4 from unvalidated reports**;
- direct mutation later corrected **3** of those report-driven states;
- those later-corrected reports caused **22 moved starts / 48h15m total start movement** before correction;
- trusted-state path: **4 provisional impact calculations**, **4 authoritative replans**, **0 authoritative replans from unvalidated reports**;
- accepted events retained: `E02, E04, E06, E08, E09`;
- final handover: **11h30m** in both paths once the same accepted facts were applied;
- validated A05 actual start remained fixed at **2h00m**;
- A08 remaining duration remained a **3h00m forecast assumption**, not historical fact;
- emergent repair activated only after explicit scope approval;
- reordered delivery of the same accepted events reproduced the same trusted-state and execution-plan hashes.

**Result: the trusted-live-state hypothesis was not falsified by this bounded experiment.**

This is evidence for the boundary, not a decision to event-source the whole application. The experiment remains isolated in `trusted_state_experiment.py`; the production native `Project` model has not been expanded into a generic field-event/workflow/provenance framework.

## Current research direction

The strongest current architectural hypothesis is now:

- executable resource/constraint-feasible schedules should be authoritative rather than CPM dates followed by post-hoc levelling;
- CPM/temporal analysis remains useful as an analytical layer;
- activities remain the language of execution;
- bounded work packages and finite authorised execution methods may become the language of planning choice;
- the scheduler may jointly choose authorised method, resource/mode, sequence and timing;
- the live object should be **trusted project state**, with the schedule derived from accepted facts and assumptions rather than directly mutated by field reports;
- CP-SAT remains the primary experimental optimisation backend for now, but it is not the native architecture;
- human/project rules remain authoritative over required work, admissible methods, validation authority, real constraints, protected commitments and objective policy.

Do not promote these hypotheses into large schemas or product frameworks merely because bounded experiments worked.

High-value unresolved questions include the **objective-policy falsification experiment** (fastest recovery versus stable recovery under explicit aspiration bounds), **scalable decomposition/incremental repair** for large professional schedules, and later **calendar/state semantics** if they become rich enough to challenge CP-SAT materially.

Do not start a broad compatibility programme, production-hardening phase, P6/MSP clone, full event-sourcing architecture or large UI framework in place of those core experiments.

## Microsoft Project XML remains an adapter

The bounded adapter lives under:

```text
src/deterministic_scheduling_core/adapters/msproject_xml.py
```

It imports only the narrow MSPDI subset needed for the validated real decision-area experiment and translates that source into the same `Project` model used by native projects.

Do not expand MSPDI compatibility merely because more Microsoft Project fields exist. Add adapter behaviour only when a useful product experiment needs it.

## Earlier runnable experiments

```bash
python -m deterministic_scheduling_core run-gate1-experiment
python -m deterministic_scheduling_core.gate2_experiment
python -m deterministic_scheduling_core.gate3_experiment
python -m deterministic_scheduling_core.gate4_experiment
python -m deterministic_scheduling_core.gate5_experiment
python -m deterministic_scheduling_core.prototype1_workspace /path/to/project.xml
python -m deterministic_scheduling_core.prototype2_native /tmp/pm-native-project.json
python -m deterministic_scheduling_core.work_method_experiment
python -m deterministic_scheduling_core.trusted_state_experiment
```

## Parallel STO research

`dezrobbo1/STO-Scheduler-Tracker-Research` remains a separate STO-focused scheduling and live-execution experiment. It is not subordinate to PM-Software.

The repositories should exchange useful ideas, tests and code deliberately. A future merge or shared package should happen only if working experiments show that it simplifies development or improves the product.

## Existing research and history

Earlier Phase 0 material, schemas, registers, semantic work and native-validation work remain research references. They are not current acceptance criteria.

The large historical Microsoft Project machinery under `native/`, `native-validation/` and archived documentation is **not an active architecture foundation**. Do not extend it unless a future experiment explicitly reopens that research.

## Development setup

Python 3.11 or later is required.

```bash
python -m pip install -e .
python -m unittest \
  tests.phase1.unit.test_canonical_json_and_calendars \
  tests.phase1.unit.test_kernel \
  tests.phase1.unit.test_independent_validator \
  tests.test_gate1_experiment \
  tests.test_gate2_experiment \
  tests.test_gate3_experiment \
  tests.test_gate4_experiment \
  tests.test_gate5_experiment \
  tests.test_prototype1_workspace \
  tests.test_native_project_core \
  tests.test_work_method_experiment \
  tests.test_trusted_state_experiment -v
```

## Active repository map

- `src/deterministic_scheduling_core/project/` — PM-Software-owned current native activity project model and JSON persistence.
- `src/deterministic_scheduling_core/scheduling/` — current scheduler/optimiser consuming only that native model.
- `src/deterministic_scheduling_core/adapters/` — optional external-system translators such as bounded MSPDI import.
- `src/deterministic_scheduling_core/work_method_experiment.py` — isolated falsification experiment for bounded structural planning choice.
- `src/deterministic_scheduling_core/trusted_state_experiment.py` — isolated falsification experiment for field event → validation → trusted state → replan.
- `src/deterministic_scheduling_core/prototype2_native.py` — first end-to-end native project workflow.
- `tests/` — focused reference and prototype tests.
- `docs/` and `docs/archive/` — current direction and historical research.
