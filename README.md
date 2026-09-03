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

**Gate 1 through Gate 4 are provisionally demonstrated by working experiments.**

Gate 1:

```bash
python -m deterministic_scheduling_core run-gate1-experiment
```

The 18-activity resource-constrained sample produces a feasible 48-hour fixed-priority baseline and an optimal 38-hour CP-SAT schedule. The core advances the long vessel branch so its cure/hold overlaps other work, reducing makespan by 10 hours without breaking precedence or double-booking constrained resources.

Gate 2:

```bash
python -m deterministic_scheduling_core.gate2_experiment
```

The same repair can run in `NORMAL` mode (8h, MECH) or `ACCELERATED` mode (5h, MECH + scarce SPEC). In a lightly loaded specialist context, both the local rule and global optimiser choose `ACCELERATED` and finish in 16h. In a competing specialist context, the local rule still chooses `ACCELERATED` and finishes in 22h, while the global optimiser deliberately chooses the locally slower `NORMAL` mode and finishes in 19h. The useful learning is that the shortest individual activity mode is not necessarily the best whole-project decision.

Gate 3:

```bash
python -m deterministic_scheduling_core.gate3_experiment
```

The 10-activity case compares an already optimised resource-capacity model with the same project after adding only two operational facts: an H04-H09 heavy-lift permit/access window and a workface exclusion between scaffold stripping and the exchanger lift. The 16h capacity-only optimum is resource-feasible but not executable. The operational model uses `CRANE-C04` on another lift while the exchanger workface clears, then performs the exchanger lift H05-H08 and finishes at H17. The useful learning is that a mathematically shorter resource-feasible schedule can still be the wrong plan when operational facts are absent.

Gate 4:

```bash
python -m deterministic_scheduling_core.gate4_experiment
```

Gate 4 begins from the approved 17h Gate 3 plan, sets a status point at H04, freezes work already started, and then introduces an unexpected `CRANE-C04` outage from H05-H06. The revised optimiser minimises project finish first and movement from the approved future plan second.

The exchanger lift moves from H05-H08 to H06-H09, still inside its permit/access window. Its downstream chain (`O04`, `O08`, `O09`, `O10`) moves one hour, while unrelated future inspection `O05` remains H05-H08 and already-started work remains fixed. The revised project finishes at H18, a one-hour impact, with five future activities moved by one hour each.

The useful learning is that **a small execution disturbance can be propagated through the operational plan without rewriting work that does not need to move, while keeping the cause and downstream consequence explicit**.

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

The project now moves to **Gate 5 — Real-world proof**.

The next experiment should use representative real or anonymised project information and ask whether the current approach remains useful outside carefully constructed synthetic examples.

Prefer the smallest real slice that lets us test actual logic, scarce resources, operational constraints or replanning behaviour. Do not build a broad importer, native compatibility programme, production UI or enterprise architecture merely to begin this test.

If suitable representative shutdown/turnaround data already exists in the parallel `STO-Scheduler-Tracker-Research` repository, selectively reuse or extract a bounded test case rather than forcing an early repository merge.

The important question is whether these ideas survive contact with less-curated project data and produce a plan or decision that an experienced practitioner considers sensible enough to justify continuing.

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
  tests.test_gate2_experiment \
  tests.test_gate3_experiment \
  tests.test_gate4_experiment -v
python -m deterministic_scheduling_core run-gate1-experiment
python -m deterministic_scheduling_core.gate2_experiment
python -m deterministic_scheduling_core.gate3_experiment
python -m deterministic_scheduling_core.gate4_experiment
```

## Repository map

- `src/deterministic_scheduling_core/` — current reusable calculation and validation code; the name is historical and may change as the concept develops.
- `benchmarks/semantic/` — existing small semantic cases.
- `tests/phase1/unit/` — focused reference-kernel tests.
- `docs/` — current and historical research documentation.
- `native-validation/` — paused Microsoft Project/P6 research material.
- `registers/` — historical evidence templates, not active development requirements.
- `docs/archive/` — superseded protocol snapshots, CI workflows, governance profile and manifest.
