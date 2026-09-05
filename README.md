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

## Architecture correction after Prototype 1

Prototype 1 proved that a real Microsoft Project XML schedule can expose a real planning problem to the experimental core. That was useful evidence, but Microsoft Project must not become the centre of the product architecture.

The active dependency direction is now:

```text
Microsoft Project XML ─┐
P6/XER later           ├──> external adapters ──> PM-Software native project ──> native scheduler/core
manual/native input ───┘
```

External-system fields stop at adapter boundaries. The native project model and scheduling core must not depend on Microsoft Project, P6 or any other scheduling package.

`prototype1_workspace.py` remains as a real-file bridge, but it now follows that dependency direction: MSPDI is translated into the PM-Software native model before scheduling.

## Prototype 2 — Native Project Core

Prototype 2 establishes that PM-Software can exist and operate without Microsoft Project in the workflow.

Run:

```bash
python -m deterministic_scheduling_core.prototype2_native /tmp/pm-native-project.json
```

The command:

1. creates a project directly in the PM-Software native model;
2. saves it as PM-Software native JSON;
3. reopens it;
4. schedules and optimises it;
5. changes a project fact;
6. saves the changed project;
7. recalculates it;
8. demonstrates a different whole-project execution-mode decision after the change.

The native model currently has first-class concepts for:

- projects;
- activities and milestones;
- finish-to-start predecessors;
- resources and capacity demand;
- alternative execution modes;
- not-before and latest-finish boundaries;
- workface/SIMOPS-style exclusion groups;
- planned coordinates for stable replanning objectives;
- frozen activity coordinates/modes;
- a controlling objective activity or milestone.

The native scheduler consumes only that model. It has no MSPDI dependency.

## Microsoft Project XML is now an adapter

The bounded adapter lives under:

```text
src/deterministic_scheduling_core/adapters/msproject_xml.py
```

It currently imports only the narrow MSPDI subset needed for the validated real decision-area experiment. It translates that source into the same `Project` model used by native JSON and by projects created directly in code.

Do not expand MSPDI compatibility merely because more Microsoft Project fields exist. Add adapter behaviour only when a useful product experiment needs it.

## Current next step

The next useful prototype should build on the **native project model**, not on Microsoft Project semantics.

A likely next capability is a small native project workspace where a user can create or open a PM-Software project, inspect hierarchy/tasks and a simple timeline, change a duration/resource/constraint, recalculate, and understand what changed and why.

XML import can seed that workspace, but it must remain optional input rather than the product model.

Do not start a broad compatibility programme, production hardening phase, P6/MSP clone, or large UI framework before that native workflow is demonstrated.

## Earlier runnable experiments

```bash
python -m deterministic_scheduling_core run-gate1-experiment
python -m deterministic_scheduling_core.gate2_experiment
python -m deterministic_scheduling_core.gate3_experiment
python -m deterministic_scheduling_core.gate4_experiment
python -m deterministic_scheduling_core.gate5_experiment
python -m deterministic_scheduling_core.prototype1_workspace /path/to/project.xml
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
  tests.test_native_project_core -v
```

## Active repository map

- `src/deterministic_scheduling_core/project/` — PM-Software-owned native project model and JSON persistence.
- `src/deterministic_scheduling_core/scheduling/` — scheduler/optimiser consuming only the native model.
- `src/deterministic_scheduling_core/adapters/` — optional external-system translators such as bounded MSPDI import.
- `src/deterministic_scheduling_core/prototype2_native.py` — first end-to-end native project workflow.
- `tests/` — focused reference and prototype tests.
- `docs/` and `docs/archive/` — current direction and historical research.
