# PM-Software — deterministic AI project-management research

**Status: exploratory R&D / proof of concept**

## Aim

This project investigates whether modern technology can enable a **new, better and leaner approach to professional project planning, scheduling and execution control**.

The original technical idea is a **deterministic AI core**: a trustworthy computational core that can reason about project logic, resources, operational constraints, alternatives and changing execution conditions, while modern AI can assist where it adds genuine value.

We are not trying to copy Primavera P6 or Microsoft Project. Existing products are useful sources of knowledge, comparison and potentially future interoperability, but they do not define our architecture or product model.

No final product architecture is assumed. Optimisation, constraint programming, AI, conventional scheduling mathematics, new data models and other approaches may all be researched and tested where useful.

## Working loop

**Research → Idea → Prototype → Test → Learn → Next experiment**

Before substantial work, ask:

> **What will we be able to do, demonstrate or know after this that we cannot do or know now?**

Research, documentation, tests, refactoring, validation, compatibility work and hardening support the project. They are not progress by themselves.

## Progress gates

These gates measure capability and useful learning, not process completion.

### Gate 1 — Core works

Can the deterministic AI core create a useful schedule?

### Gate 2 — Core adds value

Can it make a useful whole-project decision that a simpler local approach misses or handles less effectively?

### Gate 3 — Operational reality

Can meaningful real-world restrictions such as scarce resources, workfaces, access or permit windows be represented without impractical modelling overhead?

### Gate 4 — Change and replanning

Can the core respond sensibly when execution changes the plan, preserving unaffected work where possible and explaining important consequences?

### Gate 5 — Real-world proof

Does the approach remain useful outside synthetic examples?

Gate 5 passes when representative real or anonymised project information has been tested and an experienced practitioner judges the result useful enough to continue development.

## Current position

**Gate 1 through Gate 5 are provisionally demonstrated.**

Gate 1 showed that the core can produce a feasible resource-constrained schedule and beat a fixed-priority baseline.

Gate 2 showed that the locally shortest activity mode can be the wrong whole-project decision when a scarce specialist is needed elsewhere.

Gate 3 showed that a mathematically shorter resource-feasible schedule can still be operationally wrong when permit/access and workface restrictions are missing.

Gate 4 showed that a small execution disturbance can be propagated through the plan while preserving work that does not need to move and explaining the downstream consequence.

Gate 5 used an anonymised derivative of a real shutdown schedule slice. The source contained a declared resource overload. The core removed it while preserving the `Stage 2 Detag Complete` handoff and moving only two activities. The experienced practitioner accepted that result because preserving the Stage 2 detag handoff means the controlling downstream completion is not moved in this schedule context.

These remain proof-of-concept results, not production scheduling claims.

## Prototype 1 — Real Schedule Decision Workspace

The next step is to integrate the useful Gate 1–5 ideas into the first runnable workspace against a real Microsoft Project XML file.

The first Prototype 1 capability is deliberately narrow:

```bash
python -m deterministic_scheduling_core.prototype1_workspace /path/to/project.xml
```

By default it reads the real decision area:

- summary scope: `Remove Calciner Isolation Blanks`;
- controlling handoff: `Stage 2 Detag Complete`.

Prototype 1 currently:

1. reads a real MSPDI XML file directly;
2. finds the selected summary-task decision area and its leaf activities;
3. reads source starts/finishes, zero-lag FS links, resource assignments and declared `MaxUnits` capacities;
4. treats source starts as not-before boundaries so unmodelled external/calendar readiness is not silently pulled earlier;
5. detects declared resource-capacity conflicts in the source plan;
6. calculates a capacity-feasible stable revision with CP-SAT;
7. protects the controlling handoff first, then minimises unnecessary later-start movement;
8. prints the real resource names, real activity names, proposed movements, handoff impact and project-completion implication.

For the validated Calciner case, the expected useful result is the already accepted decision:

- detect the `WGP-NTP` overload around the Stage 2 detag work;
- move `Remove Blank LFS Chute` later;
- move `Swing ESP to 50H Blank Open` later as required;
- keep `Stage 2 Detag Complete` unchanged;
- therefore leave the downstream/project completion unchanged in this validated case.

This is **not** a general Microsoft Project importer or compatibility programme. It intentionally supports only what this first real decision workspace needs. Unsupported relationship/calendar behaviour should remain visible rather than triggering a broad architecture exercise.

## Earlier runnable experiments

```bash
python -m deterministic_scheduling_core run-gate1-experiment
python -m deterministic_scheduling_core.gate2_experiment
python -m deterministic_scheduling_core.gate3_experiment
python -m deterministic_scheduling_core.gate4_experiment
python -m deterministic_scheduling_core.gate5_experiment
```

## Parallel STO research

`dezrobbo1/STO-Scheduler-Tracker-Research` remains a separate STO-focused scheduling and live-execution experiment. It is not subordinate to this repository and should continue productive work in its own direction.

The two projects should compare results and selectively reuse useful ideas, tests or code. A future shared core, package or repository merge should be considered only when working experiments show that it would simplify development or improve the product.

## Existing research and history

Earlier Phase 0 material, schemas, registers, semantic work and native-validation work remain available as research references. They are not current acceptance criteria.

See `docs/README.md` and `docs/archive/`.

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
  tests.test_prototype1_workspace -v
```

## Repository map

- `src/deterministic_scheduling_core/` — current reusable calculation and experimental code.
- `tests/` — focused reference and experiment tests.
- `docs/` — current and historical research documentation.
- `native-validation/` — paused Microsoft Project/P6 research material.
- `registers/` — historical evidence templates, not active development requirements.
- `docs/archive/` — superseded protocol snapshots, CI workflows, governance profile and manifest.
