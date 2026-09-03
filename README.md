# PM-Software — deterministic AI project-management research

**Status: exploratory R&D / proof of concept**

## Aim

This project exists to investigate whether modern technology can enable a **new, better and leaner approach to professional project planning, scheduling and execution control**.

The original technical idea is a **deterministic AI core**: a trustworthy computational core that can reason about project logic, resources, operational constraints, alternatives and changing execution conditions, while modern AI can assist where it adds genuine value.

We are not trying to copy Primavera P6 or Microsoft Project. Existing products are useful sources of knowledge, comparison and potentially future interoperability, but they do not define our architecture or product model.

No final product architecture is assumed. Optimisation, constraint programming, AI, conventional scheduling mathematics, new data models and other approaches may all be researched and tested where useful.

## How this project progresses

The working loop is:

**Research → Idea → Prototype → Test → Learn → Next experiment**

Research and ideas are valuable when they lead toward something we can test. We should not spend excessive time proving an idea theoretically when a small experiment can teach us more quickly.

A failed experiment is useful progress when it tells us an approach does not work or shows us what to try next.

### Forward Progress Principle

Everything we do should either:

- increase working capability;
- test a promising idea;
- answer an important question that changes what we build next; or
- remove a real blocker to doing one of those things.

Research, documentation, tests, refactoring, validation, compatibility work and hardening support the project. They are not progress by themselves.

Before starting substantial work, ask:

> **What will we be able to do, demonstrate or know after this that we cannot do or know now?**

If there is no clear answer, reconsider the work.

A newly discovered issue does not automatically become the next task. If it does not stop the current experiment or materially invalidate what we are learning, record it and continue.

Prefer moving to the next useful experiment with known limitations over repeatedly perfecting the previous experiment.

## Progress gates

These gates measure capability and learning, not process completion.

### Gate 1 — Core works

Can the deterministic AI core create a useful schedule?

Pass when a small, understandable project can be given to the core and it produces a feasible schedule that respects the constraints implemented in the experiment.

### Gate 2 — Core adds value

Does the new approach do something worth pursuing?

Pass when at least one controlled case demonstrates a useful scheduling, resource or planning decision that a simpler conventional approach misses or handles less effectively.

### Gate 3 — Operational reality

Can the approach represent meaningful real-world project restrictions without becoming impractical?

Examples to explore include specialist crews, equipment, workfaces, access, permits, isolations, materials, shifts, supervision and SIMOPS. These are examples, not a mandatory feature list.

Pass when selected operational constraints can be represented and the resulting plan is useful enough to justify continuing.

### Gate 4 — Change and replanning

Can the core remain useful when execution changes the plan?

Test progress, delays, changed durations, emergent work, unavailable resources and other realistic disturbances.

Pass when the system can produce a sensible revised plan and make the important consequences understandable.

### Gate 5 — Real-world proof

Does the approach remain useful outside synthetic examples?

Pass when representative real or anonymised project information can be tested and experienced users judge the results useful enough to continue development.

### Later — Productisation

Production hardening, comprehensive security, broad compatibility, deployment, large-scale performance guarantees and exhaustive validation belong later, if the experiments justify building a product.

## Current position

**Gate 1 and Gate 2 are provisionally demonstrated by working experiments.**

Gate 1:

```bash
python -m deterministic_scheduling_core run-gate1-experiment
```

The 18-activity resource-constrained sample produces a feasible 48-hour fixed-priority baseline and an optimal 38-hour CP-SAT schedule. The core advances the long vessel branch so its cure/hold overlaps other work, reducing makespan by 10 hours without breaking precedence or double-booking constrained resources.

Gate 2:

```bash
python -m deterministic_scheduling_core.gate2_experiment
```

Gate 2 tests the same repair choice in two different specialist-resource contexts:

- `NORMAL`: 8 hours using MECH only;
- `ACCELERATED`: 5 hours using MECH + scarce SPEC.

The local baseline always chooses the shorter activity mode and then receives optimal sequencing, so the comparison isolates the value of whole-project mode choice rather than poor sequencing.

In **G2-A**, the specialist is lightly loaded. Both the local rule and global optimiser choose `ACCELERATED`, finishing in 16 hours; forcing `NORMAL` finishes in 19 hours.

In **G2-B**, the specialist drives another branch. The local rule still chooses `ACCELERATED` and the best schedule under that choice finishes in 22 hours. The global optimiser instead chooses the locally slower `NORMAL` mode, lets the repair and specialist branch proceed in parallel, and finishes in 19 hours — a 3-hour improvement.

The useful learning is simple: **the shortest activity mode is not inherently the best project decision. Its value depends on what else needs the scarce resource.**

These remain narrow proof-of-concept experiments, not production scheduling claims.

Earlier work also produced useful foundations:

- a canonical schedule representation and semantic fixtures;
- productive calendar arithmetic;
- a bounded reference CPM kernel;
- an independent result validator;
- command-line and test infrastructure;
- extensive scheduling and practitioner research.

It also produced a large amount of protocol, governance and Microsoft Project validation machinery. That work is retained as history and possible future reference, but it is no longer the active direction.

The Microsoft Project headless-characterisation experiment was closed unmerged. Native Microsoft Project/P6 compatibility work is paused.

## Next experiment

The project now moves to **Gate 3 — Operational reality**.

The next experiment should add only a small number of operational constraints that are meaningful beyond generic resource capacity. A strong first candidate is a **permit/access window plus one exclusive named equipment or workface restriction**, using a similarly small transparent case.

The question is not whether CP-SAT can express arbitrary constraints. The useful question is whether representing a real operational restriction changes the plan in an understandable and useful way without requiring ridiculous modelling effort.

Do not automatically harden or generalise Gate 1 or Gate 2 before attempting Gate 3.

## Parallel STO research

`dezrobbo1/STO-Scheduler-Tracker-Research` is a separate STO-focused scheduling and live-execution experiment. It is not subordinate to this repository and is not being frozen by this reset.

If the STO repository is producing useful capability or evidence, it should continue in its own direction. The two projects should compare results and selectively reuse useful ideas, tests or code rather than forcing an early merge or preventing productive parallel exploration.

A future shared core, package or repository merge should be considered only when working experiments show that it would simplify development or improve the product.

## Existing research and history

The earlier Phase 0 material, schemas, registers, semantic corpus and native-validation work remain available because they contain potentially useful research and implementation work. They are not current acceptance criteria.

See `docs/README.md` for the documentation map and `docs/archive/` for superseded top-level control material.

## Development setup

Python 3.11 or later is required.

```bash
python -m pip install -e .
python -m unittest \
  tests.phase1.unit.test_canonical_json_and_calendars \
  tests.phase1.unit.test_kernel \
  tests.phase1.unit.test_independent_validator \
  tests.test_gate1_experiment \
  tests.test_gate2_experiment -v
python -m deterministic_scheduling_core run-gate1-experiment
python -m deterministic_scheduling_core.gate2_experiment
```

## Repository map

- `src/deterministic_scheduling_core/` — current reusable calculation and validation code; the name is historical and may change as the concept develops.
- `benchmarks/semantic/` — existing small semantic cases.
- `tests/phase1/unit/` — focused reference-kernel tests.
- `docs/` — current and historical research documentation.
- `native-validation/` — paused Microsoft Project/P6 research material.
- `registers/` — historical evidence templates, not active development requirements.
- `docs/archive/` — superseded protocol snapshots, CI workflows, governance profile and manifest.
