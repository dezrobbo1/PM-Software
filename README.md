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

We have **not passed Gate 1**.

Earlier work produced useful foundations:

- a canonical schedule representation and semantic fixtures;
- productive calendar arithmetic;
- a bounded reference CPM kernel;
- an independent result validator;
- command-line and test infrastructure;
- extensive scheduling and practitioner research.

It also produced a large amount of protocol, governance and Microsoft Project validation machinery. That work is retained as history and possible future reference, but it is no longer the active direction.

The Microsoft Project headless-characterisation experiment was closed unmerged. Native Microsoft Project/P6 compatibility work is paused.

## Next experiment

The immediate objective is to pass **Gate 1** with the smallest useful deterministic-AI scheduling experiment.

A reasonable first experiment is approximately 10–30 activities with:

- durations;
- precedence;
- one or more constrained shared resources;
- a simple comparison or baseline;
- readable output showing the resulting sequence and important waiting/conflicts.

OR-Tools CP-SAT is a candidate for this experiment, not a permanent architectural commitment.

Once it works, inspect the result and decide what experiment teaches us the most next. Do not automatically harden Gate 1 before attempting Gate 2.

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
  tests.phase1.unit.test_independent_validator -v
```

## Repository map

- `src/deterministic_scheduling_core/` — current reusable calculation and validation code; the name is historical and may change as the concept develops.
- `benchmarks/semantic/` — existing small semantic cases.
- `tests/phase1/unit/` — focused reference-kernel tests.
- `docs/` — current and historical research documentation.
- `native-validation/` — paused Microsoft Project/P6 research material.
- `registers/` — historical evidence templates, not active development requirements.
- `docs/archive/` — superseded protocol snapshots, CI workflows, governance profile and manifest.
